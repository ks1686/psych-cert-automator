import { expect, type Page } from "@playwright/test";

const STEP_LABELS = [
  "Training Metadata",
  "Upload Files",
  "Review Matches",
  "Generate",
] as const;

/** Fill Step 1 with a valid virtual single-day session. Does not click Next. */
export async function fillStep1Valid(page: Page): Promise<void> {
  await page.locator("#title").fill("Ethics in School Psychology");
  await page.locator("#date").fill("2026-06-15");
  await page.locator("#instructor").fill("Dr. Jane Smith");
  await page.locator("#ceCredits").fill("3");
  await page.locator("#apa").check();
  await page.locator("#startTime").fill("08:00");
  await page.locator("#endTime").fill("12:00");
}

/** Assert the step indicator highlights the given wizard step. */
export async function expectStep(
  page: Page,
  step: 1 | 2 | 3 | 4,
): Promise<void> {
  const label = STEP_LABELS[step - 1];
  await expect(
    page.getByRole("navigation").getByText(label, { exact: true }),
  ).toBeVisible();
}

/** Wait until StartupScreen hands off to the wizard. */
export async function waitForWizard(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { name: "Training Metadata" }),
  ).toBeVisible({ timeout: 30_000 });
}

/**
 * Set Zoom/Qualtrics paths via the VITE_E2E path inputs and parse.
 * Requires the Vite server to be started with `VITE_E2E=1`.
 */
export async function parseWithE2ePaths(
  page: Page,
  zoomPath: string,
  qualtricsPath: string,
): Promise<void> {
  await page.getByLabel("Zoom report path (E2E)").fill(zoomPath);
  await page.getByLabel("Qualtrics survey path (E2E)").fill(qualtricsPath);
  await page.getByRole("button", { name: "Parse Files" }).click();
  await expect(page.getByText(/\d+ participants? found/i)).toBeVisible({
    timeout: 30_000,
  });
}
