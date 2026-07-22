import { test, expect } from "@playwright/test";

import { installMockApi } from "../helpers/mock-api";
import { waitForWizard } from "../helpers/wizard";

test.describe("Mock e2e — session save/load", () => {
  test("restores multi-day and in-person fields from a saved session", async ({
    page,
  }) => {
    await installMockApi(page);
    await page.goto("/");
    await waitForWizard(page);

    await page.getByRole("button", { name: "Load Session" }).click();
    await expect(page.getByText("Saved Sessions")).toBeVisible();
    await page
      .getByRole("button", { name: /Cognitive Behavioral Therapy Workshop/i })
      .click();

    await expect(page.locator("#title")).toHaveValue(
      "Cognitive Behavioral Therapy Workshop",
    );
    await expect(page.locator("#isMultiDay")).toBeChecked();
    await expect(page.locator("#endDate")).toHaveValue("2026-09-11");
    await expect(page.locator("#isVirtual")).not.toBeChecked();
    await expect(page.locator("#location")).toHaveValue(
      "Rutgers University in Piscataway, NJ",
    );
    await expect(page.locator("#ny")).toBeChecked();
  });
});
