// Package handlers contains HTTP handlers for the inventory service.
//
// Design rule: emit only natural telemetry. Failure injection MUST be
// invisible at the telemetry layer — the only observable consequence
// should be the kind of signal a real failure would produce (a slow
// span, an HTTP 5xx, a saturated pool). The investigation engine has
// to figure out *what* happened from these signals without any
// pre-classified labels.
package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

// flakyDependencyCounters is per-order request counter used by the
// flaky_dependency stress-test mode. Lives at process level so the
// pattern persists across HTTP requests for the same order_id.
var flakyDependencyCounters sync.Map // string -> *atomic.Int32

const failureModeHeader = "X-Failure-Mode"

const slowQueryDelay = 300 * time.Millisecond

// poolHoldDuration is how long the pool_exhaustion injection holds onto
// a checked-out connection while sleeping. Sized so that with a small
// pool (POOL_MAX_CONNS=3) and a handful of concurrent requests, late
// arrivals visibly wait on Acquire.
const poolHoldDuration = 1500 * time.Millisecond

// slowAcquireThreshold is the wait-for-a-connection latency above which
// we emit a WARN log. The OTel span always carries the wait stat;
// the log makes the same fact discoverable via log search.
const slowAcquireThreshold = 100 * time.Millisecond

// Handler holds shared state for inventory HTTP handlers.
type Handler struct {
	pool   *pgxpool.Pool
	logger *slog.Logger
	tracer trace.Tracer
}

// New constructs a Handler.
func New(pool *pgxpool.Pool, logger *slog.Logger) *Handler {
	return &Handler{
		pool:   pool,
		logger: logger,
		tracer: otel.Tracer("inventory-service"),
	}
}

type reserveRequest struct {
	SKU      string `json:"sku"`
	Quantity int    `json:"quantity"`
	OrderID  string `json:"order_id"`
}

type reserveResponse struct {
	SKU       string `json:"sku"`
	Reserved  int    `json:"reserved"`
	Remaining int    `json:"remaining"`
}

var (
	errInsufficient = errors.New("insufficient stock")
	errUnknownSKU   = errors.New("unknown sku")
)

// Healthz is a liveness endpoint.
func (h *Handler) Healthz(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, "ok\n")
}

// Reserve atomically decrements stock for a SKU.
func (h *Handler) Reserve(w http.ResponseWriter, r *http.Request) {
	ctx, span := h.tracer.Start(r.Context(), "inventory.handle_reserve")
	defer span.End()

	var req reserveRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, "decode")
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if req.Quantity <= 0 {
		http.Error(w, "quantity must be positive", http.StatusBadRequest)
		return
	}

	span.SetAttributes(
		attribute.String("inventory.sku", req.SKU),
		attribute.Int("inventory.quantity", req.Quantity),
		attribute.String("order.id", req.OrderID),
	)

	traceID := span.SpanContext().TraceID().String()

	if !h.applyInjection(ctx, w, r.Header.Get(failureModeHeader), traceID, req) {
		return
	}

	remaining, err := h.decrementStock(ctx, req.SKU, req.Quantity)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		h.logger.Error("reserve failed",
			"sku", req.SKU,
			"order_id", req.OrderID,
			"trace_id", traceID,
			"error", err,
		)
		switch {
		case errors.Is(err, errUnknownSKU):
			http.Error(w, err.Error(), http.StatusNotFound)
		case errors.Is(err, errInsufficient):
			http.Error(w, err.Error(), http.StatusConflict)
		default:
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
		return
	}

	h.logger.Info("stock reserved",
		"sku", req.SKU,
		"order_id", req.OrderID,
		"trace_id", traceID,
		"quantity", req.Quantity,
		"remaining", remaining,
	)

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(reserveResponse{
		SKU:       req.SKU,
		Reserved:  req.Quantity,
		Remaining: remaining,
	})
}

// applyInjection performs the failure-mode behaviour, if any. Returns
// true if the request should continue, false if a response has been
// written and the caller should stop. No telemetry attributes or
// events advertise the injection — only the natural consequence
// (slow span, saturated pool, HTTP 5xx) is observable.
func (h *Handler) applyInjection(
	ctx context.Context,
	w http.ResponseWriter,
	mode, traceID string,
	req reserveRequest,
) bool {
	switch mode {
	case "":
		return true
	case "slow_query":
		select {
		case <-time.After(slowQueryDelay):
			return true
		case <-ctx.Done():
			http.Error(w, ctx.Err().Error(), http.StatusGatewayTimeout)
			return false
		}
	case "pool_exhaustion":
		// Check a connection out from the pool and hold it across a
		// slow operation. With POOL_MAX_CONNS small and concurrent
		// requests, this is what drives the pool toward saturation.
		// Production analogue: a long-running transaction or batch.
		return h.holdConnectionWhileSleeping(ctx, w, poolHoldDuration)
	case "inventory_error":
		h.logger.Error("reserve failed",
			"sku", req.SKU,
			"order_id", req.OrderID,
			"trace_id", traceID,
			"error", "internal error",
		)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return false
	case "retry_storm":
		// Simulate a transient downstream failure. The service returns
		// 503 — a retriable status code — which the upstream client's
		// retry policy is supposed to handle. The same shape would
		// come from a real overloaded backend, a rolling deploy, or
		// a flaky dependency. No special telemetry advertises that
		// this is the retry-storm scenario.
		h.logger.Error("reserve failed",
			"sku", req.SKU,
			"order_id", req.OrderID,
			"trace_id", traceID,
			"error", "service temporarily unavailable",
		)
		http.Error(w, "service temporarily unavailable", http.StatusServiceUnavailable)
		return false
	case "flaky_dependency":
		// Stress-test mode designed to NOT fit any single rule cleanly:
		//   - first call for a given order: transient 503
		//   - subsequent calls: slow (250ms) but successful
		// Payment-service's retry policy recovers the request to 200,
		// but the cumulative latency violates a tight SLA. Used by
		// the manual stress harness to check whether ARIP overcommits
		// to a high-confidence root cause on mixed-signal traces.
		counterVal, _ := flakyDependencyCounters.LoadOrStore(req.OrderID, &atomic.Int32{})
		n := counterVal.(*atomic.Int32).Add(1)
		if n == 1 {
			h.logger.Error("reserve failed",
				"sku", req.SKU,
				"order_id", req.OrderID,
				"trace_id", traceID,
				"error", "upstream temporarily unavailable",
			)
			http.Error(w, "upstream temporarily unavailable", http.StatusServiceUnavailable)
			return false
		}
		select {
		case <-time.After(250 * time.Millisecond):
			return true
		case <-ctx.Done():
			http.Error(w, ctx.Err().Error(), http.StatusGatewayTimeout)
			return false
		}
	default:
		return true
	}
}

// holdConnectionWhileSleeping checks out a pool connection and keeps
// it busy for ``d``. It records the acquire wait time and pool stats
// on a dedicated ``db.connection_hold`` span — production-style
// "I'm doing slow work with a checked-out connection" telemetry.
func (h *Handler) holdConnectionWhileSleeping(ctx context.Context, w http.ResponseWriter, d time.Duration) bool {
	holdCtx, span := h.tracer.Start(ctx, "db.connection_hold")
	defer span.End()
	span.SetAttributes(
		attribute.String("db.system", "postgresql"),
		attribute.String("db.operation", "HOLD"),
	)

	acquireStart := time.Now()
	conn, err := h.pool.Acquire(holdCtx)
	waitMs := time.Since(acquireStart).Milliseconds()
	h.recordPoolStats(span, waitMs)

	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		http.Error(w, "db acquire failed: "+err.Error(), http.StatusServiceUnavailable)
		return false
	}
	defer conn.Release()

	if waitMs >= slowAcquireThreshold.Milliseconds() {
		h.logger.Warn("slow db connection acquire",
			"trace_id", span.SpanContext().TraceID().String(),
			"wait_ms", waitMs,
			"pool_acquired", h.pool.Stat().AcquiredConns(),
			"pool_max", h.pool.Stat().MaxConns(),
		)
	}

	select {
	case <-time.After(d):
		return true
	case <-holdCtx.Done():
		span.SetStatus(codes.Error, "request cancelled while holding connection")
		http.Error(w, holdCtx.Err().Error(), http.StatusGatewayTimeout)
		return false
	}
}

// Stock returns the current stock for a SKU.
func (h *Handler) Stock(w http.ResponseWriter, r *http.Request) {
	ctx, span := h.tracer.Start(r.Context(), "inventory.get_stock")
	defer span.End()

	sku := r.PathValue("sku")
	span.SetAttributes(attribute.String("inventory.sku", sku))

	var stock int
	err := h.pool.QueryRow(ctx, "SELECT stock FROM inventory WHERE sku = $1", sku).Scan(&stock)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			http.Error(w, "unknown sku", http.StatusNotFound)
			return
		}
		span.RecordError(err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"sku": sku, "stock": stock})
}

// decrementStock atomically decrements stock for a SKU. It explicitly
// separates connection acquisition from query execution so the
// investigation engine can attribute latency to the right layer
// (slow query vs slow acquire = pool exhaustion).
func (h *Handler) decrementStock(ctx context.Context, sku string, qty int) (int, error) {
	conn, releaseSpan, err := h.acquire(ctx)
	if err != nil {
		return 0, err
	}
	defer releaseSpan(conn)

	queryCtx, span := h.tracer.Start(ctx, "db.decrement_stock")
	defer span.End()
	span.SetAttributes(
		attribute.String("db.system", "postgresql"),
		attribute.String("db.operation", "UPDATE"),
		attribute.String("db.sql.table", "inventory"),
	)

	var remaining int
	err = conn.QueryRow(queryCtx,
		`UPDATE inventory
		    SET stock = stock - $2
		  WHERE sku = $1 AND stock >= $2
		RETURNING stock`,
		sku, qty,
	).Scan(&remaining)
	if err == nil {
		return remaining, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return 0, err
	}

	var exists bool
	if e := conn.QueryRow(queryCtx,
		"SELECT EXISTS(SELECT 1 FROM inventory WHERE sku = $1)", sku,
	).Scan(&exists); e != nil {
		return 0, e
	}
	if !exists {
		return 0, errUnknownSKU
	}
	return 0, errInsufficient
}

// acquire wraps pool.Acquire in a dedicated `db.acquire_connection`
// span and tags it with the pool's current state plus the wait time.
// Callers MUST call the returned release function to close the span
// and return the connection.
//
// The pool-stats attribute set is the durable contract between this
// service and the investigation engine: see PoolExhaustionRule.
func (h *Handler) acquire(ctx context.Context) (*pgxpool.Conn, func(*pgxpool.Conn), error) {
	acqCtx, span := h.tracer.Start(ctx, "db.acquire_connection")
	span.SetAttributes(attribute.String("db.system", "postgresql"))

	start := time.Now()
	conn, err := h.pool.Acquire(acqCtx)
	waitMs := time.Since(start).Milliseconds()
	h.recordPoolStats(span, waitMs)

	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		span.End()
		return nil, nil, err
	}

	if waitMs >= slowAcquireThreshold.Milliseconds() {
		h.logger.Warn("slow db connection acquire",
			"trace_id", span.SpanContext().TraceID().String(),
			"wait_ms", waitMs,
			"pool_acquired", h.pool.Stat().AcquiredConns(),
			"pool_max", h.pool.Stat().MaxConns(),
		)
	}

	release := func(c *pgxpool.Conn) {
		if c != nil {
			c.Release()
		}
		span.End()
	}
	return conn, release, nil
}

// recordPoolStats attaches the pool's current state to the given span.
// These are the keys the PoolExhaustionRule reads — keep them stable.
func (h *Handler) recordPoolStats(span trace.Span, waitMs int64) {
	stat := h.pool.Stat()
	span.SetAttributes(
		attribute.Int64("db.pool.acquired", int64(stat.AcquiredConns())),
		attribute.Int64("db.pool.idle", int64(stat.IdleConns())),
		attribute.Int64("db.pool.max", int64(stat.MaxConns())),
		attribute.Int64("db.pool.total", int64(stat.TotalConns())),
		attribute.Int64("db.pool.empty_acquires_total", stat.EmptyAcquireCount()),
		attribute.Int64("db.pool.wait_ms", waitMs),
	)
}
