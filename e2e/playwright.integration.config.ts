import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Playwright config for integration e2e: Vite + real FastAPI on :8008.
 */
export default defineConfig({
  testDir: "./integration",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "report/integration" }],
  ],
  outputDir: "test-results/integration",
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1200, height: 950 },
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },
  webServer: [
    {
      command: "uv run python src/backends/main.py",
      cwd: ROOT,
      url: "http://127.0.0.1:8008/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "VITE_E2E=1 bun run dev -- --host 127.0.0.1 --port 1420",
      cwd: ROOT,
      url: "http://127.0.0.1:1420",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
