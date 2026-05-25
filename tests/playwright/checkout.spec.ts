import { test, expect, APIRequestContext } from "@playwright/test";
import { arip } from "./trace-extractor";

/**
 * End-to-end checkout tests against the ARIP demo stack.
 *
 * Tests assert business invariants only — they do NOT inspect any
 * "anomaly" hint set by the application. The investigation engine
 * must derive its conclusions from natural telemetry, not from labels
 * pre-classified by the system under test.
 */

const SKU = "SKU-001";

async function checkout(
  request: APIRequestContext,
  body: { order_id: string; sku: string; quantity: number },
  failureMode?: string,
) {
  const headers: Record<string, string> = {};
  if (failureMode) headers["X-Failure-Mode"] = failureMode;
  return await request.post("/checkout", { data: body, headers });
}

test("checkout succeeds with confirmed status (baseline)", async ({ request }, testInfo) => {
  const orderId = `ORD-OK-${Date.now()}`;
  const resp = await checkout(request, { order_id: orderId, sku: SKU, quantity: 1 });

  arip.attach(testInfo, {
    fromResponse: resp,
    orderId,
    assertion: "status === 'confirmed'",
  });

  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.status).toBe("confirmed");
});

test("checkout returns 200 OK (FAILS under inventory_error)", async ({ request }, testInfo) => {
  // Designed to fail. The application is asked to fail; the test does
  // not know which scenario triggered it. It just asserts the business
  // contract — checkout should return 200.
  const orderId = `ORD-INV-ERR-${Date.now()}`;
  const resp = await checkout(
    request,
    { order_id: orderId, sku: SKU, quantity: 1 },
    "inventory_error",
  );

  arip.attach(testInfo, {
    fromResponse: resp,
    orderId,
    assertion: "checkout returns 200; received non-2xx",
  });

  expect(resp.status(), `expected 200 OK but got ${resp.status()}`).toBe(200);
});

test("checkout latency stays within SLA under concurrent load (FAILS under pool_exhaustion)", async ({
  request,
}, testInfo) => {
  // Business invariant being tested:
  //
  //   No checkout should take longer than the SLA, even under bursty
  //   concurrent traffic. The test fires more concurrent requests
  //   than the inventory service has DB pool capacity for; if the
  //   pool is sized correctly for the workload, every request still
  //   completes within the SLA.
  //
  // The test does NOT know about pool sizes or connection holding.
  // It just measures latency and asserts an SLA.

  const N = 6;
  const SLA_MS = 800;

  const ids = Array.from({ length: N }, (_, i) => `ORD-POOL-${Date.now()}-${i}`);
  const t0 = Date.now();

  const results = await Promise.all(
    ids.map(async (id) => {
      const started = Date.now();
      const resp = await request.post("/checkout", {
        data: { order_id: id, sku: SKU, quantity: 1 },
        headers: { "X-Failure-Mode": "pool_exhaustion" },
      });
      return {
        order_id: id,
        status: resp.status(),
        elapsed_ms: Date.now() - started,
        trace_id: resp.headers()["x-trace-id"] ?? "",
      };
    }),
  );
  const wall_ms = Date.now() - t0;

  // Pick the slowest request as the "victim" trace to investigate.
  results.sort((a, b) => b.elapsed_ms - a.elapsed_ms);
  const slowest = results[0];

  arip.attach(testInfo, {
    traceId: slowest.trace_id,
    orderId: slowest.order_id,
    assertion: `all ${N} concurrent checkouts complete within ${SLA_MS}ms`,
  });

  const slow = results.filter((r) => r.elapsed_ms >= SLA_MS);
  expect(
    slow.length,
    `${slow.length}/${N} requests exceeded SLA ${SLA_MS}ms (wall=${wall_ms}ms). ` +
      `Slowest: ${slowest.elapsed_ms}ms order=${slowest.order_id} trace=${slowest.trace_id}`,
  ).toBe(0);
});

test("checkout succeeds without exhausting retries (FAILS under retry_storm)", async ({
  request,
}, testInfo) => {
  // Business invariant: a single checkout request should complete
  // successfully without burning through the entire retry budget.
  // When the downstream is consistently returning a retriable error,
  // the retry policy will exhaust and the client sees an error —
  // exactly the case we want to investigate.
  const orderId = `ORD-RETRY-${Date.now()}`;
  const resp = await request.post("/checkout", {
    data: { order_id: orderId, sku: SKU, quantity: 1 },
    headers: { "X-Failure-Mode": "retry_storm" },
  });

  arip.attach(testInfo, {
    fromResponse: resp,
    orderId,
    assertion: "checkout returns 200 OK",
  });

  expect(
    resp.status(),
    `expected 200 OK; got ${resp.status()} after retry policy ran`,
  ).toBe(200);
});

test("order transitions stay non-interleaved across traces", async ({
  request,
}, testInfo) => {
  // Business invariant being tested:
  //
  //   No two operations should interleave their state transitions on
  //   the same order. If trace A transitions an order, then trace B
  //   transitions it, then trace A transitions it again, A and B were
  //   acting on the order concurrently — a race.
  //
  // The test does NOT know about webhooks or checkout flows
  // specifically; it just checks the resulting state history.
  const orderId = `ORD-RACE-${Date.now()}`;

  const checkoutPromise = checkout(
    request,
    { order_id: orderId, sku: SKU, quantity: 1 },
    "slow_query",
  );

  await new Promise((r) => setTimeout(r, 50));
  await request.post("/webhook", { data: { order_id: orderId } });

  const resp = await checkoutPromise;

  // Fetch the resulting order state and inspect it.
  const orderResp = await request.get(`/orders/${orderId}`);
  expect(orderResp.status(), "order lookup failed").toBe(200);
  const order = await orderResp.json();

  arip.attach(testInfo, {
    fromResponse: resp,
    orderId,
    assertion: "order history has no interleaved trace_ids",
  });

  const traces: string[] = order.history.map((h: { trace_id: string }) => h.trace_id);

  // Count "segments" — contiguous runs of the same trace_id. A healthy
  // single-writer-at-a-time history has at most ONE segment per trace,
  // i.e. segments.length === unique trace count.
  const segments: string[] = [];
  for (const t of traces) {
    if (segments[segments.length - 1] !== t) segments.push(t);
  }
  const unique = new Set(traces).size;

  expect(
    segments.length,
    `transitions interleaved across traces. history=${JSON.stringify(order.history)}`,
  ).toBe(unique);
});
