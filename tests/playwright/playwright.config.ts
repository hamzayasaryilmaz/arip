import { defineConfig } from "@playwright/test";

// API-only test suite — no browser needed. We use Playwright purely as a
// runner so we can plug into its rich reporter ecosystem.
export default defineConfig({
  testDir: "./",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "playwright-report.json" }],
  ],
  use: {
    baseURL: process.env.PAYMENT_URL ?? "http://localhost:8080",
    extraHTTPHeaders: {
      "content-type": "application/json",
      // Mark every test-originated request as must-keep at the tail
      // sampler. Without this, fast OK traces (e.g. the webhook side
      // of webhook_race) can be dropped by the probabilistic baseline.
      "X-Arip-Capture": "true",
    },
  },
});
