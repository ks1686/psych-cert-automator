import { expect, type Page } from "@playwright/test";

const STEP_LABELS = [
  "Training Metadata",
  "Upload Files",
  "Review Matches",
  "Generate",
] as const;

export interface Step1Overrides {
  title?: string;
  date?: string;
  instructor?: string;
  ceCredits?: string;
  startTime?: string;
  endTime?: string;
  apa?: boolean;
  nasp?: boolean;
  ny?: boolean;
}

const DEFAULT_STEP1 = {
  title: "Ethics in School Psychology",
  date: "2026-06-15",
  instructor: "Dr. Jane Smith",
  ceCredits: "3",
  startTime: "08:00",
  endTime: "12:00",
  apa: true,
  nasp: false,
  ny: false,
} as const;

/** Fill Step 1 with a valid virtual single-day session. Does not click Next. */
export async function fillStep1Valid(
  page: Page,
  overrides: Step1Overrides = {},
): Promise<void> {
  const data = { ...DEFAULT_STEP1, ...overrides };

  await page.locator("#title").fill(data.title);
  await page.locator("#date").fill(data.date);
  await page.locator("#instructor").fill(data.instructor);
  await page.locator("#ceCredits").fill(data.ceCredits);
  await page.locator("#startTime").fill(data.startTime);
  await page.locator("#endTime").fill(data.endTime);

  await setCheckbox(page, "#apa", data.apa);
  await setCheckbox(page, "#nasp", data.nasp);
  await setCheckbox(page, "#ny", data.ny);
}

async function setCheckbox(
  page: Page,
  selector: string,
  checked: boolean,
): Promise<void> {
  if (checked) {
    await page.locator(selector).check();
  } else {
    await page.locator(selector).uncheck();
  }
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
 * Seed Zoom/Qualtrics paths for the VITE_E2E dialog stub, click Select + Parse.
 * Requires Vite started with `VITE_E2E=1` (dialog alias active).
 */
export async function parseWithE2ePaths(
  page: Page,
  zoomPath: string,
  qualtricsPath: string,
): Promise<void> {
  await page.evaluate(
    ({ zoom, qualtrics }) => {
      const w = window as Window & {
        __E2E_PATHS__?: { zoom?: string; qualtrics?: string };
      };
      w.__E2E_PATHS__ = { zoom, qualtrics };
    },
    { zoom: zoomPath, qualtrics: qualtricsPath },
  );

  await page.getByRole("button", { name: "Select Zoom Report" }).click();
  await page.getByRole("button", { name: "Select Qualtrics Survey" }).click();
  await page.getByRole("button", { name: "Parse Files" }).click();
  await expect(page.getByText(/\d+ participants? found/i)).toBeVisible({
    timeout: 30_000,
  });
}

/** Drive Steps 1→4 until the Generate screen is visible. */
export async function advanceToGenerateStep(
  page: Page,
  paths: { zoom: string; qualtrics: string },
  step1Overrides: Step1Overrides = {},
): Promise<void> {
  await fillStep1Valid(page, step1Overrides);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Step 2: Upload Files/i }),
  ).toBeVisible();

  await parseWithE2ePaths(page, paths.zoom, paths.qualtrics);
  await page.getByRole("button", { name: "Next" }).click();

  await expect(
    page.getByRole("heading", { name: /Review Name Matches/i }),
  ).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Generate Certificates/i }),
  ).toBeVisible();

  await page.evaluate((output) => {
    const w = window as Window & {
      __E2E_PATHS__?: { zoom?: string; qualtrics?: string; output?: string };
    };
    w.__E2E_PATHS__ = { ...w.__E2E_PATHS__, output };
  }, "/tmp/e2e-certs");
  await page.getByRole("button", { name: /Choose output folder/i }).click();
  await expect(page.getByText(/e2e-certs/)).toBeVisible();
}
