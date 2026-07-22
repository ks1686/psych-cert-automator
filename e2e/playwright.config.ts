import { browserE2eConfig } from "./playwright.base";

/**
 * Manual / nightly Tauri smoke config.
 *
 * Prefer `bun run test:e2e:mock` and `bun run test:e2e:integration` for PR CI.
 * This config does not auto-start Tauri or WebDriver — see e2e/README.md.
 */
export default browserE2eConfig({
  testDir: "./tauri",
  timeout: 60_000,
  expectTimeout: 10_000,
  outputName: "tauri",
  retries: 0,
  projectName: "chromium-desktop",
});
