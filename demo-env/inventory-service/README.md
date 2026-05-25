# inventory-service

Go HTTP service that owns the inventory table in PostgreSQL. Called by
`payment-service` during checkout. Instrumented with OpenTelemetry.

## Endpoints

| Method | Path           | Description                              |
|--------|----------------|------------------------------------------|
| GET    | `/healthz`     | Liveness probe                           |
| GET    | `/stock/{sku}` | Returns the current stock for a SKU      |
| POST   | `/reserve`     | Atomically decrements stock for a SKU    |

### POST /reserve

Request:
```json
{ "sku": "SKU-001", "quantity": 2, "order_id": "ORD-1" }
```

Response (200):
```json
{ "sku": "SKU-001", "reserved": 2, "remaining": 98 }
```

Response codes:
- `404` — unknown SKU
- `409` — insufficient stock

## Environment

| Variable                       | Default                                                  |
|--------------------------------|----------------------------------------------------------|
| `PORT`                         | `8081`                                                   |
| `POSTGRES_DSN`                 | `postgres://arip:arip@localhost:5432/arip?sslmode=disable` |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | (env)                                                    |
| `OTEL_EXPORTER_OTLP_PROTOCOL`  | `http/protobuf`                                          |
| `OTEL_SERVICE_NAME`            | `inventory-service`                                      |
