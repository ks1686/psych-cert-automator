import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import { fillStep1Valid, waitForWizard } from "../helpers/wizard";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ZOOM = path.join(ROOT, "tests/fixtures/pilot_zoom.xlsx");
const QUALTRICS = path.join(ROOT, "tests/fixtures/pilot_qualtrics.xlsx");
const SESSIONS = path.join(os.homedir(), ".psych-cert-gen", "sessions");

const STEP1 = {
  title: "Ethics and Practice in School-Based Mental Health",
  date: "2026-10-06",
  instructor: "Dr. Amira Solano",
  ceCredits: "3",
  startTime: "09:00",
  endTime: "12:00",
  apa: true,
  nasp: true,
  ny: true,
  nbcc: true,
} as const;

async function seedPaths(page: Page, output: string, zoom = ZOOM): Promise<void> {
  await page.evaluate(
    ({ zoomPath, qualtrics, outputDir }) => {
      const w = window as Window & {
        __E2E_PATHS__?: { zoom?: string; qualtrics?: string; output?: string };
      };
      w.__E2E_PATHS__ = { zoom: zoomPath, qualtrics, output: outputDir };
    },
    { zoomPath: zoom, qualtrics: QUALTRICS, outputDir: output },
  );
}

async function parsePilot(page: Page, output: string, zoom = ZOOM): Promise<void> {
  await seedPaths(page, output, zoom);
  await page.getByRole("button", { name: "Select Zoom Report" }).click();
  await page.getByRole("button", { name: "Select Qualtrics Survey" }).click();
  await page.getByRole("button", { name: "Parse Files" }).click();
}

async function chooseMatch(page: Page, rowText: string, option: string): Promise<void> {
  const row = page.getByRole("row").filter({ hasText: rowText });
  await row.getByRole("combobox").click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("corrections, include host, exclude straggler, view, and stale link", async ({
  page,
}) => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "psych-cert-edges-"));
  await page.goto("/");
  await waitForWizard(page);
  await fillStep1Valid(page, STEP1);
  await page.getByRole("button", { name: "Next" }).click();
  await parsePilot(page, output);
  await expect(page.getByText("14 participants found, 14 CE requests found")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: /Review Name Matches/i })).toBeVisible();

  await chooseMatch(page, "Noah Blake", "Noah Blake Adams");
  await chooseMatch(page, "Rowan Blake", "Robin Cho");
  await page.getByRole("button", { name: "Apply Corrections" }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "Noah Blake" }).getByText("Matched", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Rowan Blake" }).getByText("Matched", { exact: true }),
  ).toBeVisible();

  await page.getByRole("row").filter({ hasText: "Morgan Hale" }).getByRole("checkbox").uncheck();
  await page.getByRole("row").filter({ hasText: "Quinn Alvarez" }).getByRole("checkbox").check();

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("10 eligible certificates ready to generate.")).toBeVisible();
  await page.getByRole("button", { name: "Choose output folder" }).click();
  await page.getByRole("button", { name: "Generate All Certificates" }).click();
  await expect(page.getByText("Generated Certificates (10)")).toBeVisible({
    timeout: 90_000,
  });

  const certTable = page.getByRole("table").filter({
    has: page.getByRole("link", { name: "View" }),
  });
  await expect(certTable.getByText("Morgan Hale")).toBeVisible();
  await expect(certTable.getByText("Noah Blake")).toBeVisible();
  await expect(certTable.getByText("Rowan Blake")).toBeVisible();
  await expect(certTable.getByText("Casey Nguyen")).toHaveCount(2);
  await expect(certTable.getByText("Quinn Alvarez")).toHaveCount(0);
  await expect(
    page.getByRole("row").filter({ hasText: "Quinn Alvarez" }).getByText("Excluded", { exact: true }),
  ).toBeVisible();

  const firstView = await certTable.getByRole("link", { name: "View" }).first().getAttribute("href");
  expect(firstView).toBeTruthy();
  const firstPdf = await page.request.get(firstView ?? "");
  expect(firstPdf.ok()).toBeTruthy();
  expect(firstPdf.headers()["content-type"]).toContain("pdf");

  await page.getByRole("button", { name: "Generate Again" }).click();
  await expect(page.getByText("Generated Certificates (10)")).toBeVisible({
    timeout: 90_000,
  });
  const stale = await page.request.get(firstView ?? "");
  expect(stale.status()).toBe(404);
  const secondView = await certTable.getByRole("link", { name: "View" }).first().getAttribute("href");
  const secondPdf = await page.request.get(secondView ?? "");
  expect(secondPdf.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Start Over" }).click();
  await expect(page.getByRole("heading", { name: "Training Metadata" })).toBeVisible();
  await expect(page.locator("#title")).toHaveValue("");
});

test("withholding a CE type marks those requests not offered", async ({ page }) => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "psych-cert-nasp-"));
  await page.goto("/");
  await waitForWizard(page);
  await fillStep1Valid(page, { ...STEP1, apa: false, ny: false, nbcc: false, nasp: true });
  await page.getByRole("button", { name: "Next" }).click();
  await parsePilot(page, output);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: /Review Name Matches/i })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("2 eligible certificates ready to generate.")).toBeVisible();
  await page.getByRole("button", { name: "Choose output folder" }).click();
  await page.getByRole("button", { name: "Generate All Certificates" }).click();
  await expect(page.getByText(/Generated Certificates \(\d+\)/)).toBeVisible({
    timeout: 90_000,
  });

  const certTable = page.getByRole("table").filter({
    has: page.getByRole("link", { name: "View" }),
  });
  await expect(certTable.getByText("Samira N. Patel")).toBeVisible();
  await expect(certTable.getByText("Quinn Alvarez")).toBeVisible();
  await expect(certTable.getByText("Avery Chen")).toHaveCount(0);
  await expect(
    page.getByRole("row").filter({ hasText: "Avery Chen" }).getByText("Not Offered", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Drew Kim" }).getByText("Attendance", { exact: true }),
  ).toBeVisible();
});

test("a file that is not a Zoom report shows a parse error", async ({ page }) => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "psych-cert-bad-"));
  const badZoom = path.join(output, "not-zoom.xlsx");
  fs.writeFileSync(badZoom, "this is not a workbook");

  await page.goto("/");
  await waitForWizard(page);
  await fillStep1Valid(page, STEP1);
  await page.getByRole("button", { name: "Next" }).click();
  await parsePilot(page, output, badZoom);
  await expect(page.getByText("Parse Error")).toBeVisible();
  await expect(page.getByText(/Could not read spreadsheet/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("save and load round-trips metadata through the backend", async ({ page }) => {
  const title = `ZZ Pilot Confidence ${Date.now()}`;
  const cleanup = () => {
    if (!fs.existsSync(SESSIONS)) return;
    for (const name of fs.readdirSync(SESSIONS)) {
      if (!name.endsWith(".json")) continue;
      const file = path.join(SESSIONS, name);
      const raw = fs.readFileSync(file, "utf8");
      if (raw.includes(title)) fs.unlinkSync(file);
    }
  };

  try {
    await page.goto("/");
    await waitForWizard(page);
    await fillStep1Valid(page, { ...STEP1, title });
    await page.locator("#isMultiDay").check();
    await page.locator("#endDate").fill("2026-10-07");
    await page.locator("#isVirtual").uncheck();
    await page.locator("#location").fill("Rutgers University in Piscataway, NJ");
    await page.getByRole("button", { name: "Save Session" }).click();
    await expect(page.getByRole("button", { name: "Saved!" })).toBeVisible();

    await page.reload();
    await waitForWizard(page);
    await page.getByRole("button", { name: "Load Session" }).click();
    await page.getByRole("button", { name: new RegExp(title) }).click();

    await expect(page.locator("#title")).toHaveValue(title);
    await expect(page.locator("#isMultiDay")).toBeChecked();
    await expect(page.locator("#endDate")).toHaveValue("2026-10-07");
    await expect(page.locator("#isVirtual")).not.toBeChecked();
    await expect(page.locator("#location")).toHaveValue(
      "Rutgers University in Piscataway, NJ",
    );
    await expect(page.locator("#apa")).toBeChecked();
    await expect(page.locator("#nasp")).toBeChecked();
    await expect(page.locator("#ny")).toBeChecked();
    await expect(page.locator("#nbcc")).toBeChecked();
    await expect(page.locator("#instructor")).toHaveValue("Dr. Amira Solano");
  } finally {
    cleanup();
  }
});
