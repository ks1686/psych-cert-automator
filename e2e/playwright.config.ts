import { defineConfig } from "@playwright/test";

/**
 * Playwright configuration for Tauri e2e testing.
 *
 * ## Prerequisites
 *
 * 1. Start the Tauri app in dev mode:
 *    ```sh
 *    bun run tauri dev
 *    ```
 *
 * 2. Start the FastAPI backend:
 *    ```sh
 *    uv run python src/backends/main.py
 *    ```
 *
 * 3. Run the tests:
 *    ```sh
 *    bun run test:e2e
 *    ```
 *
 * ## Tauri WebDriver mode (recommended for CI)
 *
 * When running with tauri-driver, start the app with WebDriver support
 * and connect via `connectOptions.wsEndpoint` pointing to the
 * WebDriver CDP endpoint (ws://127.0.0.1:4444).
 *
 * ```sh
 * cargo install tauri-driver
 * tauri-driver &
 * cargo tauri dev -- --remote-debugging-port=9222
 * ```
 *
 * Then uncomment the `connectOptions` block in the project config below.
 */
export default defineConfig({
  /** Directory containing test spec files */
  testDir: ".",

  /** Per-test timeout (60 seconds) */
  timeout: 60_000,

  /** Assertion timeout */
  expect: {
    timeout: 10_000,
  },

  /** Retry configuration */
  retries: 0,

  /** Worker count — serial execution recommended for Tauri */
  workers: 1,

  /**
   * Reporter configuration.
   * Use `html` for a rich HTML report, `list` for terminal output.
   */
  reporter: [["list"], ["html", { outputFolder: "e2e/report" }]],

  /**
   * Tauri manages its own application process (both the Rust backend and
   * the webview). No `webServer` block is needed — the app must already
   * be running before `bun run test:e2e` is invoked.
   *
   * If you prefer Playwright to launch Tauri automatically, create a
   * `globalSetup` script at `e2e/global-setup.ts`.
   */

  /** Shared settings for all projects */
  use: {
    /**
     * Base URL of the Vite dev server.
     * When tests navigate to relative paths, they resolve against this URL.
     *
     * In production Tauri builds, the app is served via `tauri://localhost`
     * or a custom protocol. Set `baseURL` accordingly for those environments.
     */
    baseURL: "http://localhost:1420",

    /**
     * Viewport matching the Tauri window dimensions declared in
     * `src-tauri/tauri.conf.json` (default: 1200×950).
     */
    viewport: { width: 1200, height: 950 },

    /** Capture Playwright trace on first retry */
    trace: "on-first-retry",

    /** Screenshot only when a test fails */
    screenshot: "only-on-failure",

    /** Record video of each test (off by default — enable for debugging) */
    video: "off",
  },

  /** Project matrix */
  projects: [
    {
      name: "chromium-desktop",

      use: {
        /** Use the system Chromium / Google Chrome browser */
        channel: "chromium",

        /**
         * Connect to an already-running Tauri WebDriver session.
         * Uncomment when running with `tauri-driver`.
         *
         * When this is set, `channel` and `viewport` are ignored
         * (the connected session owns the window).
         */
        // connectOptions: {
        //   wsEndpoint: 'ws://127.0.0.1:4444',
        // },
      },
    },
  ],
});
