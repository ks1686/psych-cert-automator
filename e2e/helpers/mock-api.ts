import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { Page, Route } from "@playwright/test";

const API_ORIGIN = "http://127.0.0.1:8008";

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
const generateJson = readFixture("generate-complete.json");

/** Minimal PDF header bytes so preview can return a non-empty body. */
const PREVIEW_PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
  "utf8",
);

type RouteKey = `${string} ${string}`;

interface MockApiState {
  generateCallCount: number;
}

function buildFulfillers(state: MockApiState): Map<
  RouteKey,
  (route: Route) => Promise<void>
> {
  return new Map([
    [
      "GET /api/sessions",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: sessionsJson,
        });
      },
    ],
    [
      "POST /api/sessions",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "saved",
            path: "/tmp/mock-session.json",
          }),
        });
      },
    ],
    [
      "POST /api/parse",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: parseJson,
        });
      },
    ],
    [
      "POST /api/match",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: matchJson,
        });
      },
    ],
    [
      "POST /api/preview",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/pdf",
          body: PREVIEW_PDF,
        });
      },
    ],
    [
      "POST /api/generate",
      async (route) => {
        state.generateCallCount += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: generateJson,
        });
      },
    ],
    [
      "POST /api/download-zip",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/zip",
          body: Buffer.from("PK\u0003\u0004"),
          headers: {
            "Content-Disposition": "attachment; filename=certificates.zip",
          },
        });
      },
    ],
    [
      "GET /api/pdf",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/pdf",
          body: PREVIEW_PDF,
        });
      },
    ],
  ]);
}

export interface MockApiHandle {
  getGenerateCallCount(): number;
}

/**
 * Route backend health + `/api/**` calls to local fixtures so mock e2e
 * can run without FastAPI.
 */
export async function installMockApi(page: Page): Promise<MockApiHandle> {
  const state: MockApiState = { generateCallCount: 0 };
  const fulfillers = buildFulfillers(state);

  await page.route(`${API_ORIGIN}/health`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "healthy", pid: 1 }),
    });
  });

  await page.route(`${API_ORIGIN}/api/**`, async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}` as RouteKey;
    const fulfill = fulfillers.get(key);
    if (fulfill) {
      await fulfill(route);
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        detail: `Unhandled mock route: ${route.request().method()} ${url.pathname}`,
      }),
    });
  });

  return {
    getGenerateCallCount: () => state.generateCallCount,
  };
}
