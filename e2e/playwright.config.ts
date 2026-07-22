import { defineConfig } from "@playwright/test";

/**
 * Manual / nightly Tauri smoke config.
 *
 * Prefer `bun run test:e2e:mock` and `bun run test:e2e:integration` for PR CI.
 * This config does not auto-start Tauri or WebDriver — see e2e/README.md.
 */
export default defineConfig({
  testDir: "./tauri",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "report/tauri" }]],
  outputDir: "test-results/tauri",
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1200, height: 950 },
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium-desktop",
      use: { browserName: "chromium" },
    },
  ],
});
