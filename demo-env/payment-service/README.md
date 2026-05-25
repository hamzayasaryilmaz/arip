# payment-service

Go HTTP service that accepts checkout requests and reserves inventory in
`inventory-service`. Instrumented with OpenTelemetry (OTLP/HTTP exporter,
W3C TraceContext propagation).

## Endpoints

| Method | Path        | Description                                  |
|--------|-------------|----------------------------------------------|
| GET    | `/healthz`  | Liveness probe                               |
| POST   | `/checkout` | Reserves `quantity` of `sku` for an order    |

### POST /checkout

Request:
```json
{ "order_id": "ORD-1", "sku": "SKU-001", "quantity": 2 }
```

Response (200):
```json
{
  "order_id":  "ORD-1",
  "status":    "confirmed",
  "trace_id":  "abc...",
  "reserved":  2,
  "remaining": 98
}
```

The trace ID is also surfaced as the `X-Trace-Id` response header.

## Environment

| Variable                       | Default                      |
|--------------------------------|------------------------------|
| `PORT`                         | `8080`                       |
| `INVENTORY_URL`                | `http://localhost:8081`      |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | (env / `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_PROTOCOL`  | `http/protobuf`              |
| `OTEL_SERVICE_NAME`            | `payment-service`            |
