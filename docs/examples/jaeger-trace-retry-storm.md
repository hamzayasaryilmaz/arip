# Example: Retry storm trace as ARIP sees it

The investigation engine fetches this trace from Jaeger via
`/api/traces/905fed60a72cfab5b908328ff01a2a22` and reads the spans below.

This is the same data you would see in the Jaeger UI at
`http://localhost:16686/trace/905fed60a72cfab5b908328ff01a2a22`, rendered as a textual
timeline so it can live in docs.

```
service              operation                         duration  status  retry / pool stats
--------------------------------------------------------------------------------------------------------------
payment-service      payment-service                    762.4ms  ERROR   
payment-service      checkout.process                   762.3ms  ERROR   
payment-service      inventory.reserve_call             762.2ms  ERROR   policy=exponential attempts_used=5
payment-service      inventory.reserve_attempt            0.7ms  ERROR   attempt=1 backoff=0ms
payment-service      HTTP POST                            0.7ms  ERROR   
inventory-service    inventory-service                    0.2ms  ERROR   
inventory-service    inventory.handle_reserve             0.1ms          
payment-service      inventory.reserve_attempt            1.1ms  ERROR   attempt=2 backoff=50ms
payment-service      HTTP POST                            1.0ms  ERROR   
inventory-service    inventory-service                    0.2ms  ERROR   
inventory-service    inventory.handle_reserve             0.1ms          
payment-service      inventory.reserve_attempt            0.6ms  ERROR   attempt=3 backoff=100ms
payment-service      HTTP POST                            0.5ms  ERROR   
inventory-service    inventory-service                    0.1ms  ERROR   
inventory-service    inventory.handle_reserve             0.1ms          
payment-service      inventory.reserve_attempt            0.8ms  ERROR   attempt=4 backoff=200ms
payment-service      HTTP POST                            0.7ms  ERROR   
inventory-service    inventory-service                    0.1ms  ERROR   
inventory-service    inventory.handle_reserve             0.1ms          
payment-service      inventory.reserve_attempt            0.7ms  ERROR   attempt=5 backoff=400ms
payment-service      HTTP POST                            0.6ms  ERROR   
inventory-service    inventory-service                    0.1ms  ERROR   
inventory-service    inventory.handle_reserve             0.1ms          
```

Notice the shape — this is the *deterministic signature* the
`RetryStormRule` reads against:

1. The outer `inventory.reserve_call` span carries the policy.
2. Five `inventory.reserve_attempt` spans carry `retry.attempt=1..5`
   and `retry.backoff_ms=0/50/100/200/400` — the exponential pattern.
3. Every attempt is ERROR; every downstream `inventory-service`
   server span is ERROR. Same shape, same reason, five times.

The engine does NOT look at the *failure-mode header* the demo
used to inject this. It reads only what production instrumentation
would emit anyway.
