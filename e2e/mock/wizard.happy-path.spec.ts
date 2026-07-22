import { test, expect } from "@playwright/test";

import { installMockApi } from "../helpers/mock-api";
import {
  advanceToGenerateStep,
  expectStep,
  waitForWizard,
} from "../helpers/wizard";

test.describe("Mock e2e — happy path", () => {
  test("completes all four wizard steps with stubbed API", async ({ page }) => {
    await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);
    await expectStep(page, 1);

    await advanceToGenerateStep(page, {
      zoom: "/tmp/mock-zoom.xlsx",
      qualtrics: "/tmp/mock-qualtrics.xlsx",
    });

    await page.getByRole("button", { name: /Generate All Certificates/i }).click();
    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Alex Rivera").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Generate Again/i })).toBeVisible();
  });
});
