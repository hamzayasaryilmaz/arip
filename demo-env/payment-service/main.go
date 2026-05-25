package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/arip/payment-service/handlers"
	"github.com/arip/payment-service/otel"
	"github.com/arip/payment-service/state"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	otelAttr "go.opentelemetry.io/otel/attribute"
	otelTrace "go.opentelemetry.io/otel/trace"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	serviceName := envOr("OTEL_SERVICE_NAME", "payment-service")
	port := envOr("PORT", "8080")
	inventoryURL := envOr("INVENTORY_URL", "http://localhost:8081")

	rootCtx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	shutdown, err := otel.Init(rootCtx, serviceName)
	if err != nil {
		logger.Error("otel init failed", "error", err)
		os.Exit(1)
	}
	defer func() {
		c, cc := context.WithTimeout(context.Background(), 5*time.Second)
		defer cc()
		if err := shutdown(c); err != nil {
			logger.Error("otel shutdown failed", "error", err)
		}
	}()

	orders := state.NewStore()
	h := handlers.New(inventoryURL, orders, logger)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.Healthz)
	mux.Handle("POST /checkout", otelhttp.WithRouteTag("/checkout", http.HandlerFunc(h.Checkout)))
	mux.Handle("POST /webhook", otelhttp.WithRouteTag("/webhook", http.HandlerFunc(h.Webhook)))
	mux.Handle("GET /orders/{id}", otelhttp.WithRouteTag("/orders/{id}", http.HandlerFunc(h.GetOrder)))

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           otelhttp.NewHandler(captureMiddleware(mux), "payment-service"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	serverErr := make(chan error, 1)
	go func() {
		logger.Info("payment-service listening", "port", port, "inventory_url", inventoryURL)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			serverErr <- err
		}
	}()

	select {
	case <-rootCtx.Done():
		logger.Info("shutdown signal received")
	case err := <-serverErr:
		logger.Error("server crashed", "error", err)
	}

	stopCtx, sc := context.WithTimeout(context.Background(), 5*time.Second)
	defer sc()
	_ = srv.Shutdown(stopCtx)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// captureMiddleware honours the `X-Arip-Capture` sampling-control
// header by tagging the current span with `arip.force_sample=true`,
// which the OTel Collector's tail sampler uses to guarantee the trace
// survives baseline downsampling. This is a standard production
// pattern for "always sample this specific request" overrides.
func captureMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Header.Get("X-Arip-Capture")
		if v == "true" || v == "1" {
			span := otelTrace.SpanFromContext(r.Context())
			if span.SpanContext().IsValid() {
				span.SetAttributes(otelAttr.String("arip.force_sample", "true"))
			}
		}
		next.ServeHTTP(w, r)
	})
}
