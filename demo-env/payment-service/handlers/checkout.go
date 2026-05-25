// Package handlers contains HTTP handlers for the payment service.
//
// Design rule: handlers emit only the kind of telemetry a real
// production service would emit (spans, logs, metrics). They MUST NOT
// emit any signal that exists purely for the investigation engine's
// convenience — no "anomaly.*" attributes, no special states named
// "X_with_race", no events that pre-classify a failure. The engine has
// to derive its conclusions from natural telemetry the same way it
// would for an opaque third-party service.
package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/arip/payment-service/state"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

// failureModeHeader is forwarded to inventory-service so a single client
// call can drive downstream behaviour. The header itself is forwarded
// as-is; it is NOT mirrored onto spans as an attribute, because real
// services don't tag their spans with "this request was meant to fail".
const failureModeHeader = "X-Failure-Mode"

// Production-style retry policy for transient downstream failures. The
// retry loop is ALWAYS on — it is not specific to any test scenario.
// The failure-injector merely arranges for the downstream to return
// retriable errors so the loop is exercised.
const (
	retryMaxAttempts    = 5
	retryInitialBackoff = 50 * time.Millisecond
	retryMultiplier     = 2.0
)

// Handler holds shared state for payment HTTP handlers.
type Handler struct {
	inventoryURL string
	client       *http.Client
	logger       *slog.Logger
	tracer       trace.Tracer
	orders       *state.Store
}

// New constructs a Handler. The HTTP client is instrumented so outgoing
// requests automatically inject W3C TraceContext headers for inventory.
func New(inventoryURL string, orders *state.Store, logger *slog.Logger) *Handler {
	return &Handler{
		inventoryURL: inventoryURL,
		client: &http.Client{
			Timeout:   5 * time.Second,
			Transport: otelhttp.NewTransport(http.DefaultTransport),
		},
		logger: logger,
		tracer: otel.Tracer("payment-service"),
		orders: orders,
	}
}

type checkoutRequest struct {
	OrderID  string `json:"order_id"`
	SKU      string `json:"sku"`
	Quantity int    `json:"quantity"`
}

type checkoutResponse struct {
	OrderID   string `json:"order_id"`
	Status    string `json:"status"`
	TraceID   string `json:"trace_id"`
	Reserved  int    `json:"reserved"`
	Remaining int    `json:"remaining"`
}

type webhookRequest struct {
	OrderID string `json:"order_id"`
}

// Healthz is a liveness endpoint.
func (h *Handler) Healthz(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, "ok\n")
}

// Checkout processes a checkout by reserving inventory in the downstream
// inventory-service and confirming the order.
func (h *Handler) Checkout(w http.ResponseWriter, r *http.Request) {
	ctx, span := h.tracer.Start(r.Context(), "checkout.process")
	defer span.End()

	var req checkoutRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, "decode failed")
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	failureMode := r.Header.Get(failureModeHeader)
	captureFlag := r.Header.Get("X-Arip-Capture")
	traceID := span.SpanContext().TraceID().String()
	w.Header().Set("X-Trace-Id", traceID)

	// Only the business key gets tagged on the span. The failure-mode
	// header is forwarded downstream but not echoed onto telemetry.
	span.SetAttributes(
		attribute.String("order.id", req.OrderID),
		attribute.String("order.sku", req.SKU),
		attribute.Int("order.quantity", req.Quantity),
	)

	h.transition(span, req.OrderID, req.SKU, "pending", traceID, "checkout started")

	reserved, remaining, err := h.reserveInventory(ctx, req, failureMode, captureFlag)
	if err != nil {
		h.transition(span, req.OrderID, req.SKU, "failed", traceID, "inventory reservation failed: "+err.Error())
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		h.logger.Error("reserve failed",
			"order_id", req.OrderID, "trace_id", traceID, "error", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	// Move the order to "confirmed". If the order is in any state other
	// than "pending", something else has already mutated it — likely
	// concurrent with our reservation. Log the surprise; this is the
	// kind of WARN a careful production service would emit.
	prev := h.transition(span, req.OrderID, req.SKU, "confirmed", traceID, "inventory reserved")
	if prev != "pending" {
		h.logger.Warn("order in unexpected state during confirmation",
			"order_id", req.OrderID,
			"trace_id", traceID,
			"expected_previous", "pending",
			"actual_previous", prev,
		)
	}

	h.logger.Info("checkout confirmed",
		"order_id", req.OrderID, "trace_id", traceID,
		"sku", req.SKU, "reserved", reserved)

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(checkoutResponse{
		OrderID:   req.OrderID,
		Status:    "confirmed",
		TraceID:   traceID,
		Reserved:  reserved,
		Remaining: remaining,
	})
}

// Webhook handles an asynchronous "payment received" notification.
func (h *Handler) Webhook(w http.ResponseWriter, r *http.Request) {
	_, span := h.tracer.Start(r.Context(), "webhook.process")
	defer span.End()

	var req webhookRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, "decode")
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	traceID := span.SpanContext().TraceID().String()
	w.Header().Set("X-Trace-Id", traceID)
	span.SetAttributes(attribute.String("order.id", req.OrderID))

	prev := h.transition(span, req.OrderID, "", "paid", traceID, "payment webhook received")

	// A real service might log a warning if the webhook arrives in an
	// unexpected state (e.g. before checkout completes). It does NOT
	// know whether this is a race; it just notes the observation.
	if prev != "confirmed" {
		h.logger.Warn("payment webhook applied to order not in confirmed state",
			"order_id", req.OrderID,
			"trace_id", traceID,
			"expected_previous", "confirmed",
			"actual_previous", prev,
		)
	} else {
		h.logger.Info("payment webhook applied",
			"order_id", req.OrderID,
			"trace_id", traceID,
			"previous_status", prev,
		)
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"order_id":        req.OrderID,
		"status":          "paid",
		"previous_status": prev,
		"trace_id":        traceID,
	})
}

// GetOrder returns the current state and state-history of an order.
func (h *Handler) GetOrder(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	o, ok := h.orders.Get(id)
	if !ok {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(o)
}

// transition mutates the store and emits the corresponding span event
// using the standard `state.transition` name + `from`/`to`/`order.id`
// attributes. This is a generic, production-style event — no specific
// failure pattern is named here.
func (h *Handler) transition(span trace.Span, orderID, sku, newStatus, traceID, note string) string {
	prev := h.orders.Transition(orderID, sku, newStatus, traceID, note)
	span.AddEvent("state.transition", trace.WithAttributes(
		attribute.String("order.id", orderID),
		attribute.String("state.from", prev),
		attribute.String("state.to", newStatus),
	))
	h.logger.Info("order transition",
		"order_id", orderID, "trace_id", traceID,
		"from", prev, "to", newStatus,
	)
	return prev
}

// reserveInventory invokes the inventory service with a retry loop on
// transient (5xx) failures. The retry policy is exponential.
//
// Each attempt is emitted as a child span named
// ``inventory.reserve_attempt`` with deterministic ``retry.*``
// attributes — exactly what the RetryStormRule reads against. The
// outer span captures the policy itself; child spans capture per-try
// state. This shape is the durable contract between this service and
// the investigation engine.
func (h *Handler) reserveInventory(ctx context.Context, req checkoutRequest, failureMode, captureFlag string) (int, int, error) {
	ctx, span := h.tracer.Start(ctx, "inventory.reserve_call")
	defer span.End()
	span.SetAttributes(
		attribute.Int("retry.max_attempts", retryMaxAttempts),
		attribute.String("retry.policy", "exponential"),
		attribute.Int64("retry.backoff_initial_ms", retryInitialBackoff.Milliseconds()),
		attribute.Float64("retry.backoff_multiplier", retryMultiplier),
	)

	backoff := retryInitialBackoff
	var lastErr error
	for attempt := 1; attempt <= retryMaxAttempts; attempt++ {
		backoffForThisAttempt := time.Duration(0)
		if attempt > 1 {
			backoffForThisAttempt = backoff
			select {
			case <-time.After(backoffForThisAttempt):
			case <-ctx.Done():
				return 0, 0, ctx.Err()
			}
			backoff = time.Duration(float64(backoff) * retryMultiplier)
		}

		reserved, remaining, attemptErr, retriable := h.doReserveAttempt(
			ctx, req, failureMode, captureFlag,
			attempt, backoffForThisAttempt,
		)
		if attemptErr == nil {
			if attempt > 1 {
				span.SetAttributes(attribute.Int("retry.successful_attempt", attempt))
			}
			return reserved, remaining, nil
		}
		lastErr = attemptErr
		if !retriable {
			// 4xx / non-transient: don't burn retries on something
			// retries will not fix. Mark the outer span as ERROR
			// explicitly so the investigation engine sees the failure
			// propagated all the way up (without this, the call-stack
			// chain looks "recovered" from the engine's perspective
			// even though the client received an error).
			span.SetStatus(codes.Error, attemptErr.Error())
			return 0, 0, attemptErr
		}
	}

	span.SetStatus(codes.Error, "retries exhausted")
	span.SetAttributes(attribute.Int("retry.attempts_used", retryMaxAttempts))
	return 0, 0, fmt.Errorf("inventory reserve: exhausted %d retries: %w", retryMaxAttempts, lastErr)
}

// doReserveAttempt executes a single HTTP attempt and emits an
// ``inventory.reserve_attempt`` span tagged with the retry metadata.
// The ``retriable`` return tells the caller whether to retry.
func (h *Handler) doReserveAttempt(
	ctx context.Context,
	req checkoutRequest,
	failureMode, captureFlag string,
	attempt int,
	backoffApplied time.Duration,
) (reserved, remaining int, err error, retriable bool) {
	ctx, span := h.tracer.Start(ctx, "inventory.reserve_attempt")
	defer span.End()
	span.SetAttributes(
		attribute.String("order.id", req.OrderID),
		attribute.Int("retry.attempt", attempt),
		attribute.Int("retry.max_attempts", retryMaxAttempts),
		attribute.Int64("retry.backoff_ms", backoffApplied.Milliseconds()),
		attribute.String("retry.policy", "exponential"),
	)

	payload, _ := json.Marshal(map[string]any{
		"sku":      req.SKU,
		"quantity": req.Quantity,
		"order_id": req.OrderID,
	})
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, h.inventoryURL+"/reserve", bytes.NewReader(payload))
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		span.SetAttributes(attribute.String("retry.reason", err.Error()))
		return 0, 0, err, false
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if failureMode != "" {
		httpReq.Header.Set(failureModeHeader, failureMode)
	}
	if captureFlag != "" {
		httpReq.Header.Set("X-Arip-Capture", captureFlag)
	}

	resp, err := h.client.Do(httpReq)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		span.SetAttributes(attribute.String("retry.reason", err.Error()))
		return 0, 0, fmt.Errorf("inventory call: %w", err), true // network errors are retriable
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		bodyStr := string(body)
		errMsg := fmt.Sprintf("inventory status %d: %s", resp.StatusCode, bodyStr)
		// Conservative retry policy: only the infrastructure-flavour
		// 5xx codes are considered retriable. 500 ("the server has a
		// bug") will not get better with retries and would just amplify
		// load against a broken endpoint.
		isRetriable := resp.StatusCode == http.StatusBadGateway ||
			resp.StatusCode == http.StatusServiceUnavailable ||
			resp.StatusCode == http.StatusGatewayTimeout
		span.SetStatus(codes.Error, errMsg)
		span.SetAttributes(
			attribute.Int("http.response.status_code", resp.StatusCode),
			attribute.String("retry.reason", fmt.Sprintf("upstream %d: %s", resp.StatusCode, bodyStr)),
			attribute.Bool("retry.retriable", isRetriable),
		)
		return 0, 0, fmt.Errorf("%s", errMsg), isRetriable
	}

	var out struct {
		Reserved  int `json:"reserved"`
		Remaining int `json:"remaining"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return 0, 0, fmt.Errorf("decode inventory response: %w", err), false
	}
	return out.Reserved, out.Remaining, nil, false
}
