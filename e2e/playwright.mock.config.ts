import {
  browserE2eConfig,
  VITE_E2E_WEB_SERVER,
} from "./playwright.base";

/** Playwright config for mock e2e: Vite + stubbed FastAPI via page.route. */
export default browserE2eConfig({
  testDir: "./mock",
  timeout: 60_000,
  expectTimeout: 10_000,
  outputName: "mock",
  webServer: VITE_E2E_WEB_SERVER,
});
