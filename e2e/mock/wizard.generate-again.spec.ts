import { test, expect } from "@playwright/test";

import { installMockApi } from "../helpers/mock-api";
import { advanceToGenerateStep, waitForWizard } from "../helpers/wizard";

test.describe("Mock e2e — Generate Again", () => {
  test("allows a second generate after completion", async ({ page }) => {
    const mockApi = await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);

    await advanceToGenerateStep(page, {
      zoom: "/tmp/mock-zoom.xlsx",
      qualtrics: "/tmp/mock-qualtrics.xlsx",
    });

    await page.getByRole("button", { name: /Generate All Certificates/i }).click();
    await expect(page.getByRole("button", { name: /Generate Again/i })).toBeVisible({
      timeout: 30_000,
    });
    expect(mockApi.getGenerateCallCount()).toBe(1);

    await page.getByRole("button", { name: /Generate Again/i }).click();
    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 30_000,
    });
    expect(mockApi.getGenerateCallCount()).toBe(2);
  });
});
