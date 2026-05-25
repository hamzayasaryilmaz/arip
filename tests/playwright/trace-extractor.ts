/**
 * Helpers for ARIP-instrumented Playwright tests.
 *
 * Two annotation contracts the collector reads:
 *
 *   - `trace_id`  (required for any failure to be investigated)
 *   - `order_id`  (optional; lets ARIP correlate across separate traces
 *                  via the business key)
 *   - `assertion` (optional; the human-readable invariant the test
 *                  asserted, shown verbatim in the report)
 *
 * Tests should call `arip.attach(testInfo, { traceId, orderId, assertion })`
 * once they know the values. The helper also captures the X-Trace-Id
 * response header from an APIResponse if one is provided, so the
 * caller doesn't need to dig it out manually.
 */

import { TestInfo, APIResponse } from "@playwright/test";

export interface AttachInput {
  traceId?: string;
  orderId?: string;
  assertion?: string;
  /** If provided, traceId is read from `X-Trace-Id` on the response. */
  fromResponse?: APIResponse;
}

export const arip = {
  /** Attach the ARIP correlation annotations to the running test. */
  attach(testInfo: TestInfo, input: AttachInput): { traceId: string } {
    let traceId = input.traceId ?? "";
    if (!traceId && input.fromResponse) {
      traceId = input.fromResponse.headers()["x-trace-id"] ?? "";
    }
    if (traceId) {
      testInfo.annotations.push({ type: "trace_id", description: traceId });
    }
    if (input.orderId) {
      testInfo.annotations.push({ type: "order_id", description: input.orderId });
    }
    if (input.assertion) {
      testInfo.annotations.push({ type: "assertion", description: input.assertion });
    }
    return { traceId };
  },
};
