package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/arip/inventory-service/handlers"
	"github.com/arip/inventory-service/otel"

	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	otelAttr "go.opentelemetry.io/otel/attribute"
	otelTrace "go.opentelemetry.io/otel/trace"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	serviceName := envOr("OTEL_SERVICE_NAME", "inventory-service")
	port := envOr("PORT", "8081")
	dsn := envOr("POSTGRES_DSN", "postgres://arip:arip@localhost:5432/arip?sslmode=disable")

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

	poolCfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		logger.Error("pgxpool.ParseConfig failed", "error", err)
		os.Exit(1)
	}
	if v := os.Getenv("POOL_MAX_CONNS"); v != "" {
		if n, perr := strconv.Atoi(v); perr == nil && n > 0 {
			poolCfg.MaxConns = int32(n)
		}
	}
	logger.Info("postgres pool configured", "max_conns", poolCfg.MaxConns)

	pool, err := pgxpool.NewWithConfig(rootCtx, poolCfg)
	if err != nil {
		logger.Error("pgxpool.NewWithConfig failed", "error", err)
		os.Exit(1)
	}
	defer pool.Close()

	if err := waitForDB(rootCtx, pool, logger); err != nil {
		logger.Error("postgres unreachable", "error", err)
		os.Exit(1)
	}

	h := handlers.New(pool, logger)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.Healthz)
	mux.Handle("POST /reserve", otelhttp.WithRouteTag("/reserve", http.HandlerFunc(h.Reserve)))
	mux.Handle("GET /stock/{sku}", otelhttp.WithRouteTag("/stock/{sku}", http.HandlerFunc(h.Stock)))

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           otelhttp.NewHandler(captureMiddleware(mux), "inventory-service"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	serverErr := make(chan error, 1)
	go func() {
		logger.Info("inventory-service listening", "port", port)
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

func waitForDB(ctx context.Context, pool *pgxpool.Pool, logger *slog.Logger) error {
	deadline := time.Now().Add(30 * time.Second)
	var lastErr error
	for time.Now().Before(deadline) {
		pingCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		err := pool.Ping(pingCtx)
		cancel()
		if err == nil {
			return nil
		}
		lastErr = err
		logger.Info("waiting for postgres", "error", err)
		time.Sleep(time.Second)
	}
	return lastErr
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
// survives baseline downsampling.
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
