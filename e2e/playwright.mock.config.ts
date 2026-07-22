import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Playwright config for mock e2e: Vite + stubbed FastAPI via page.route.
 */
export default defineConfig({
  testDir: "./mock",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "report/mock" }],
  ],
  outputDir: "test-results/mock",
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1200, height: 950 },
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },
  webServer: {
    command: "VITE_E2E=1 bun run dev -- --host 127.0.0.1 --port 1420",
    cwd: ROOT,
    url: "http://127.0.0.1:1420",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
