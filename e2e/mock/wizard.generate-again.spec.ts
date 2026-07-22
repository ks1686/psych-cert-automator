import { test, expect } from "@playwright/test";

import {
  getMockGenerateCallCount,
  installMockApi,
} from "../helpers/mock-api";
import {
  fillStep1Valid,
  parseWithE2ePaths,
  waitForWizard,
} from "../helpers/wizard";

test.describe("Mock e2e — Generate Again", () => {
  test("allows a second generate after completion", async ({ page }) => {
    await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);

    await fillStep1Valid(page);
    await page.getByRole("button", { name: "Next" }).click();
    await parseWithE2ePaths(page, "/tmp/mock-zoom.xlsx", "/tmp/mock-qualtrics.xlsx");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: /Review Name Matches/i }),
    ).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Next" }).click();

    await page.getByRole("button", { name: /Generate All Certificates/i }).click();
    await expect(page.getByRole("button", { name: /Generate Again/i })).toBeVisible({
      timeout: 30_000,
    });
    expect(getMockGenerateCallCount()).toBe(1);

    await page.getByRole("button", { name: /Generate Again/i }).click();
    await expect(page.getByText(/Generated Certificates/i)).toBeVisible({
      timeout: 30_000,
    });
    expect(getMockGenerateCallCount()).toBe(2);
  });
});
