import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { fillStep1Valid, waitForWizard } from "../helpers/wizard";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ZOOM = path.join(ROOT, "tests/fixtures/pilot_zoom.xlsx");
const QUALTRICS = path.join(ROOT, "tests/fixtures/pilot_qualtrics.xlsx");

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

async function seedPaths(
  page: import("@playwright/test").Page,
  output: string,
): Promise<void> {
  await page.evaluate(
    ({ zoom, qualtrics, outputDir }) => {
      const w = window as Window & {
        __E2E_PATHS__?: { zoom?: string; qualtrics?: string; output?: string };
      };
      w.__E2E_PATHS__ = { zoom, qualtrics, output: outputDir };
    },
    { zoom: ZOOM, qualtrics: QUALTRICS, outputDir: output },
  );
}

function pdfsIn(dir: string): string[] {
  return fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".pdf"))
    .sort();
}

function pdfText(file: string): string {
  return execFileSync("pdftotext", ["-layout", file, "-"], {
    encoding: "utf8",
  });
}

test("pilot pair: review excludes, generate, zip, and generate again", async ({
  page,
}) => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "psych-cert-pilot-"));
  await page.goto("/");
  await waitForWizard(page);
  await fillStep1Valid(page, STEP1);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Step 2: Upload Files/i }),
  ).toBeVisible();

  await seedPaths(page, output);
  await page.getByRole("button", { name: "Select Zoom Report" }).click();
  await page.getByRole("button", { name: "Select Qualtrics Survey" }).click();
  await page.getByRole("button", { name: "Parse Files" }).click();
  await expect(page.getByText("14 participants found, 14 CE requests found")).toBeVisible();

  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Review Name Matches/i }),
  ).toBeVisible();
  await expect(page.getByText("11 matched")).toBeVisible();
  await expect(page.getByText("1 ambiguous")).toBeVisible();
  await expect(page.getByText("1 not found")).toBeVisible();
  await expect(page.getByText("3 ineligible")).toBeVisible();

  const hostRow = page.getByRole("row").filter({ hasText: "Morgan Hale" });
  await expect(hostRow.getByRole("checkbox")).toBeChecked();
  await expect(hostRow.getByText("Host")).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Noah Blake" }).getByText("Ambiguous"),
  ).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Rowan Blake" }).getByText("Not Found"),
  ).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Taylor Brooks" }).getByText("missed 20.0m"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Generate Certificates/i }),
  ).toBeVisible();
  await expect(page.getByText("8 eligible certificates ready to generate.")).toBeVisible();

  await page.getByRole("button", { name: "Preview Certificate" }).click();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Choose output folder" }).click();
  await page.getByRole("button", { name: "Generate All Certificates" }).click();
  await expect(page.getByText("Generated Certificates (8)")).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByRole("table").getByText("Avery Chen")).toBeVisible();
  await expect(page.getByRole("table").getByText("Riley Okonkwo")).toBeVisible();
  await expect(page.getByRole("table").getByText("Samira N. Patel")).toBeVisible();
  await expect(page.getByRole("table").getByText("Quinn Alvarez")).toBeVisible();
  const certTable = page.getByRole("table").filter({ has: page.getByRole("link", { name: "View" }) });
  await expect(certTable.getByText("Morgan Hale")).toHaveCount(0);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "Morgan Hale" })
      .getByText("Excluded", { exact: true }),
  ).toBeVisible();

  const firstPdfs = pdfsIn(output);
  expect(firstPdfs).toHaveLength(8);
  const combined = firstPdfs.map((name) => pdfText(path.join(output, name))).join("\n");
  expect(combined).toContain("012345");
  expect(combined).toContain("067890");
  expect(combined).not.toContain("Morgan Hale");
  expect(fs.existsSync(path.join(output, "ineligibility_report.xlsx"))).toBe(true);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download All as ZIP" }).click();
  const download = await downloadPromise;
  const zipPath = path.join(output, "certificates.zip");
  await download.saveAs(zipPath);
  const listing = execFileSync("unzip", ["-Z1", zipPath], { encoding: "utf8" });
  expect(listing.trim().split("\n").filter((name) => name.endsWith(".pdf"))).toHaveLength(8);

  for (const name of firstPdfs) {
    fs.unlinkSync(path.join(output, name));
  }
  expect(pdfsIn(output)).toHaveLength(0);
  await page.getByRole("button", { name: "Generate Again" }).click();
  await expect(page.getByText("Generated Certificates (8)")).toBeVisible({
    timeout: 90_000,
  });
  expect(pdfsIn(output)).toHaveLength(8);
});

test("pilot pair: in-person multi-day wording from the wizard", async ({ page }) => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), "psych-cert-pilot-ip-"));
  await page.goto("/");
  await waitForWizard(page);
  await fillStep1Valid(page, STEP1);
  await page.locator("#isMultiDay").check();
  await page.locator("#endDate").fill("2026-10-07");
  await page.locator("#isVirtual").uncheck();
  await page.locator("#location").fill("Rutgers University in Piscataway, NJ");
  await page.getByRole("button", { name: "Next" }).click();

  await seedPaths(page, output);
  await page.getByRole("button", { name: "Select Zoom Report" }).click();
  await page.getByRole("button", { name: "Select Qualtrics Survey" }).click();
  await page.getByRole("button", { name: "Parse Files" }).click();
  await expect(page.getByText("14 participants found, 14 CE requests found")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: /Review Name Matches/i }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Choose output folder" }).click();
  await page.getByRole("button", { name: "Generate All Certificates" }).click();
  await expect(page.getByText("Generated Certificates (8)")).toBeVisible({
    timeout: 90_000,
  });

  const texts = pdfsIn(output).map((name) => pdfText(path.join(output, name)));
  const nasp = texts.find((text) => text.includes("Samira N. Patel"));
  const apa = texts.find((text) => text.includes("Avery Chen"));
  expect(nasp).toBeTruthy();
  expect(apa).toBeTruthy();
  expect(nasp).toContain("at Rutgers University in Piscataway, NJ");
  expect(nasp).not.toContain("via Live Zoom Webinar");
  expect(apa).toContain("In-Person");
  expect(apa).toContain("October 6");
  expect(apa).toContain("7, 2026");
});
