import path from "node:path";
import { fileURLToPath } from "node:url";

import { test, expect } from "@playwright/test";

import { advanceToGenerateStep, waitForWizard } from "../helpers/wizard";

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

    await advanceToGenerateStep(
      page,
      { zoom: ZOOM_FIXTURE, qualtrics: QUALTRICS_FIXTURE },
      {
        date: "2026-03-20",
        startTime: "08:47",
        endTime: "12:11",
        nasp: true,
      },
    );

    const generateBtn = page.getByRole("button", {
      name: /Generate All Certificates|Generate Again/i,
    });
    await expect(generateBtn).toBeEnabled();
    await generateBtn.click();

    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 90_000,
    });
    await expect(
      page.getByRole("table").getByText("Hannah Lee").first(),
    ).toBeVisible();
  });
});
