import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  defineConfig,
  type PlaywrightTestConfig,
} from "@playwright/test";

export const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

export const VITE_E2E_WEB_SERVER = {
  command: "VITE_E2E=1 bun run dev -- --host 127.0.0.1 --port 1420",
  cwd: ROOT,
  url: "http://127.0.0.1:1420",
  reuseExistingServer: !process.env.CI,
  timeout: 120_000,
} as const;

export function browserE2eConfig(opts: {
  testDir: string;
  timeout: number;
  expectTimeout: number;
  outputName: string;
  retries?: number;
  webServer?: PlaywrightTestConfig["webServer"];
  projectName?: string;
}): PlaywrightTestConfig {
  return defineConfig({
    testDir: opts.testDir,
    timeout: opts.timeout,
    expect: { timeout: opts.expectTimeout },
    retries: opts.retries ?? (process.env.CI ? 1 : 0),
    workers: 1,
    reporter: [
      ["list"],
      ["html", { open: "never", outputFolder: `report/${opts.outputName}` }],
    ],
    outputDir: `test-results/${opts.outputName}`,
    use: {
      baseURL: "http://127.0.0.1:1420",
      viewport: { width: 1200, height: 950 },
      trace: "on-first-retry",
      screenshot: "only-on-failure",
      video: "off",
    },
    webServer: opts.webServer,
    projects: [
      {
        name: opts.projectName ?? "chromium",
        use: { browserName: "chromium" },
      },
    ],
  });
}
