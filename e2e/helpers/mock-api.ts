import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { Page, Route } from "@playwright/test";

const FIXTURES_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "api",
);

function readFixture(name: string): string {
  return readFileSync(path.join(FIXTURES_DIR, name), "utf8");
}

const parseJson = readFixture("parse.json");
const matchJson = readFixture("match.json");
const sessionsJson = readFixture("sessions.json");
const generateSse = readFixture("generate-complete.sse");

/** Minimal PDF header bytes so preview can return a non-empty body. */
const PREVIEW_PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
  "utf8",
);

let generateCallCount = 0;

/**
 * Route backend health + `/api/**` calls to local fixtures so mock e2e
 * can run without FastAPI.
 */
export async function installMockApi(page: Page): Promise<void> {
  generateCallCount = 0;

  await page.route("http://127.0.0.1:8008/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "healthy", pid: 1 }),
    });
  });

  await page.route("http://127.0.0.1:8008/api/**", async (route) => {
    await fulfillApiRoute(route);
  });
}

async function fulfillApiRoute(route: Route): Promise<void> {
  const url = new URL(route.request().url());
  const method = route.request().method();
  const pathname = url.pathname;

  if (pathname === "/api/sessions" && method === "GET") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: sessionsJson,
    });
    return;
  }

  if (pathname === "/api/sessions" && method === "POST") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "saved", path: "/tmp/mock-session.json" }),
    });
    return;
  }

  if (pathname === "/api/parse" && method === "POST") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: parseJson,
    });
    return;
  }

  if (pathname === "/api/match" && method === "POST") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: matchJson,
    });
    return;
  }

  if (pathname === "/api/preview" && method === "POST") {
    await route.fulfill({
      status: 200,
      contentType: "application/pdf",
      body: PREVIEW_PDF,
    });
    return;
  }

  if (pathname === "/api/generate" && method === "POST") {
    generateCallCount += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: generateSse,
    });
    return;
  }

  if (pathname === "/api/download-zip" && method === "POST") {
    await route.fulfill({
      status: 200,
      contentType: "application/zip",
      body: Buffer.from("PK\u0003\u0004"),
      headers: {
        "Content-Disposition": "attachment; filename=certificates.zip",
      },
    });
    return;
  }

  if (pathname === "/api/pdf" && method === "GET") {
    await route.fulfill({
      status: 200,
      contentType: "application/pdf",
      body: PREVIEW_PDF,
    });
    return;
  }

  await route.fulfill({
    status: 404,
    contentType: "application/json",
    body: JSON.stringify({ detail: `Unhandled mock route: ${method} ${pathname}` }),
  });
}

export function getMockGenerateCallCount(): number {
  return generateCallCount;
}
