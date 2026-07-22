import {
  browserE2eConfig,
  ROOT,
  VITE_E2E_WEB_SERVER,
} from "./playwright.base";

/** Playwright config for integration e2e: Vite + real FastAPI on :8008. */
export default browserE2eConfig({
  testDir: "./integration",
  timeout: 120_000,
  expectTimeout: 30_000,
  outputName: "integration",
  webServer: [
    {
      command: "uv run python src/backends/main.py",
      cwd: ROOT,
      url: "http://127.0.0.1:8008/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    VITE_E2E_WEB_SERVER,
  ],
});
