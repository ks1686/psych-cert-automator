import { test, expect } from "@playwright/test";

import { installMockApi } from "../helpers/mock-api";
import { waitForWizard } from "../helpers/wizard";

test.describe("Mock e2e — Step 1 validation", () => {
  test("keeps Next disabled until required fields are valid", async ({
    page,
  }) => {
    await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);

    const next = page.getByRole("button", { name: "Next" });
    await expect(next).toBeDisabled();

    await page.locator("#title").fill("Ethics");
    await expect(next).toBeDisabled();

    await page.locator("#date").fill("2026-06-15");
    await page.locator("#instructor").fill("Dr. Jane Smith");
    await page.locator("#ceCredits").fill("3");
    await page.locator("#apa").check();
    await page.locator("#startTime").fill("08:00");
    await page.locator("#endTime").fill("12:00");

    await expect(next).toBeEnabled();
  });
});
