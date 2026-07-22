import { test, expect } from "@playwright/test";

import { installMockApi } from "../helpers/mock-api";
import {
  expectStep,
  fillStep1Valid,
  parseWithE2ePaths,
  waitForWizard,
} from "../helpers/wizard";

test.describe("Mock e2e — happy path", () => {
  test("completes all four wizard steps with stubbed API", async ({ page }) => {
    await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);
    await expectStep(page, 1);

    await fillStep1Valid(page);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: /Step 2: Upload Files/i }),
    ).toBeVisible();

    await parseWithE2ePaths(page, "/tmp/mock-zoom.xlsx", "/tmp/mock-qualtrics.xlsx");
    await page.getByRole("button", { name: "Next" }).click();

    await expect(
      page.getByRole("heading", { name: /Review Name Matches/i }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Alex Rivera").first()).toBeVisible();

    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: /Generate/i }),
    ).toBeVisible();

    await page.getByRole("button", { name: /Generate All Certificates/i }).click();
    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Alex Rivera").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Generate Again/i })).toBeVisible();
  });
});
