import path from "node:path";
import { fileURLToPath } from "node:url";

import { test, expect } from "@playwright/test";

import {
  fillStep1Valid,
  parseWithE2ePaths,
  waitForWizard,
} from "../helpers/wizard";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ZOOM_FIXTURE = path.join(ROOT, "tests/fixtures/sample_zoom.xlsx");
const QUALTRICS_FIXTURE = path.join(
  ROOT,
  "tests/fixtures/sample_qualtrics.xlsx",
);

test.describe("Integration e2e — real FastAPI pipeline", () => {
  test("parses fixtures, shows matches, and generates at least one certificate", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForWizard(page);

    await fillStep1Valid(page);
    // Align Step 1 date with Zoom fixture session (2026-03-20).
    await page.locator("#date").fill("2026-03-20");
    await page.locator("#startTime").fill("08:47");
    await page.locator("#endTime").fill("12:11");
    await page.locator("#nasp").check();

    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: /Step 2: Upload Files/i }),
    ).toBeVisible();

    await parseWithE2ePaths(page, ZOOM_FIXTURE, QUALTRICS_FIXTURE);
    await page.getByRole("button", { name: "Next" }).click();

    await expect(
      page.getByRole("heading", { name: /Review Name Matches/i }),
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Hannah Lee").first()).toBeVisible();

    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: /Generate Certificates/i }),
    ).toBeVisible();

    const generateBtn = page.getByRole("button", {
      name: /Generate All Certificates|Generate Again/i,
    });
    await expect(generateBtn).toBeEnabled();
    await generateBtn.click();

    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 90_000,
    });
    await expect(page.getByRole("table").getByText("Hannah Lee").first()).toBeVisible();
  });
});
