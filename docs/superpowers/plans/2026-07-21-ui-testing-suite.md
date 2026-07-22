# UI-Centered Testing Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a layered UI testing suite (Vitest + Playwright mock e2e + Playwright integration e2e) wired into PR CI, with Tauri smoke documented for manual/nightly use.

**Architecture:** Keep pytest as the domain base. Add Vitest/RTL for wizard components. Split Playwright into auto-started Vite + mocked API vs Vite + real FastAPI. Add Ubuntu CI jobs for unit/e2e without blocking the existing multi-OS Tauri build matrix on Tauri WebDriver.

**Tech Stack:** Bun, Vitest, @testing-library/react, jsdom, Playwright, FastAPI, GitHub Actions, existing sample xlsx under `input/` / `tests/fixtures/`.

## Global Constraints

- Package manager: **Bun** (not npm/pnpm)
- Python tests: `uv run pytest` / CI `python -m pytest` — all existing tests must keep passing
- No `as any`, `@ts-ignore`, `@ts-expect-error` in TypeScript
- Do not modify `src/parser/`, `src/matcher/`, `src/validator/`
- PR CI must **not** require Tauri WebDriver
- Soft-fail PDF is acceptable in integration e2e (docx OK)

## File map

| Path | Responsibility |
|------|----------------|
| `vitest.config.ts` | Vitest + jsdom + path aliases matching Vite |
| `ui/src/test/setup.ts` | Testing Library jest-dom matchers, cleanup |
| `ui/src/components/*.test.tsx` | Component tests for Steps 1/3/4 |
| `e2e/fixtures/api/*` | Mock HTTP/SSE responses |
| `e2e/helpers/mock-api.ts` | `page.route` helpers for mock suite |
| `e2e/helpers/wizard.ts` | Shared fill/assert helpers |
| `e2e/playwright.mock.config.ts` | Mock e2e: webServer Vite |
| `e2e/playwright.integration.config.ts` | Integration: webServer Vite + assumes API on 8008 |
| `e2e/mock/*.spec.ts` | Mocked wizard scenarios |
| `e2e/integration/*.spec.ts` | Real backend scenarios |
| `e2e/README.md` | Update commands / architecture |
| `.github/workflows/test-ui.yml` | PR jobs: unit + mock e2e + integration e2e |
| `package.json` | `test:unit`, `test:e2e:mock`, `test:e2e:integration` scripts |

---

### Task 1: Vitest + Testing Library scaffolding

**Files:**
- Create: `vitest.config.ts`
- Create: `ui/src/test/setup.ts`
- Modify: `package.json`
- Modify: `tsconfig.json` or `tsconfig.node.json` if needed for vitest types

**Interfaces:**
- Produces: `bun run test:unit` runs Vitest against `ui/src/**/*.{test,spec}.tsx`

- [ ] **Step 1: Add dev dependencies**

```bash
cd /Users/ks1686/Documents/Repos/psych-cert-gen
bun add -d vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @vitest/coverage-v8
```

- [ ] **Step 2: Add `vitest.config.ts`**

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./ui/src/test/setup.ts"],
    include: ["ui/src/**/*.{test,spec}.{ts,tsx}"],
    css: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./ui/src"),
    },
  },
});
```

- [ ] **Step 3: Add setup file + package scripts**

```ts
// ui/src/test/setup.ts
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
```

```json
"test:unit": "vitest run",
"test:unit:watch": "vitest"
```

- [ ] **Step 4: Smoke test that Vitest runs**

Create a tiny `ui/src/test/smoke.test.ts` asserting `expect(true).toBe(true)`, run `bun run test:unit`, then delete the smoke file once real tests land in Task 2 (or leave until Task 2 replaces it).

- [ ] **Step 5: Commit**

```bash
git add package.json bun.lock vitest.config.ts ui/src/test/setup.ts
git commit -m "test: add Vitest and Testing Library scaffolding"
```

---

### Task 2: Component tests for Steps 1, 3, 4

**Files:**
- Create: `ui/src/components/StepMetadata.test.tsx`
- Create: `ui/src/components/StepMatchReview.test.tsx`
- Create: `ui/src/components/StepGenerate.test.tsx`
- Possibly small test helpers under `ui/src/test/`

**Interfaces:**
- Consumes: exported components + prop types from Step* files
- Produces: failing→passing unit coverage for milestone behaviors

- [ ] **Step 1: Write failing StepMetadata tests**

Cover:
- Next disabled when required fields empty
- Multi-day requires end date
- In-person requires location
- CE types are APA/NASP/NY (no BCBA checkbox in document)

Use `@testing-library/user-event` and `getByRole` / `getByLabelText`.

- [ ] **Step 2: Run `bun run test:unit` — expect failures, then fix only if product bugs are found; otherwise tests should pass against current UI**

If labels/ids differ, adjust selectors to match existing DOM (`#title`, `#isMultiDay`, etc.).

- [ ] **Step 3: StepMatchReview — host pre-excluded + Exclude toggle**

Render with `initialData` including `zoomHost: "Jessica Benas"` and a matching CE request; assert exclude checkbox checked; uncheck and click Next; assert `onNext` receives `excludedNames` without that person.

Mock `fetch` for Apply Corrections if needed.

- [ ] **Step 4: StepGenerate — Generate Again visible after complete**

Drive component into `phase === "complete"` by mocking `fetch` SSE complete event; assert button named `/Generate Again/i` is visible and enabled when eligible entries exist.

- [ ] **Step 5: Commit**

```bash
git commit -m "test: add Vitest coverage for wizard step behaviors"
```

---

### Task 3: Mock API fixtures + Playwright mock config

**Files:**
- Create: `e2e/fixtures/api/parse.json`
- Create: `e2e/fixtures/api/match.json`
- Create: `e2e/fixtures/api/sessions.json`
- Create: `e2e/fixtures/api/generate-complete.sse` (or build SSE in helper)
- Create: `e2e/helpers/mock-api.ts`
- Create: `e2e/helpers/wizard.ts`
- Create: `e2e/playwright.mock.config.ts`
- Modify: `package.json` (`test:e2e:mock`)

**Interfaces:**
- Produces: `installMockApi(page)` that routes `http://127.0.0.1:8008/api/**`
- Produces: helpers `fillStep1Valid(page)`, `expectStep(page, n)`

- [ ] **Step 1: Write fixture JSON matching current API shapes**

Include `zoom_host`, `excluded`-compatible match payloads, and generate complete event with `certificates` + optional `conversion_warning`.

- [ ] **Step 2: Implement `installMockApi`**

```ts
export async function installMockApi(page: Page): Promise<void> {
  await page.route("http://127.0.0.1:8008/api/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    // match /health, /parse, /match, /preview, /generate, /sessions, /pdf, /download-zip
    // fulfill from fixtures; for /generate return text/event-stream body
  });
}
```

Also stub `**/api/health` or ensure StartupScreen can be bypassed: prefer navigating after mock health returns healthy, or set a test-only flag if StartupScreen blocks — inspect `StartupScreen` and choose the least invasive approach (mock health + Tauri listen no-op).

- [ ] **Step 3: Playwright mock config with webServer**

```ts
webServer: {
  command: "bun run dev -- --host 127.0.0.1 --port 1420",
  url: "http://127.0.0.1:1420",
  reuseExistingServer: !process.env.CI,
},
use: { baseURL: "http://127.0.0.1:1420" },
```

- [ ] **Step 4: Commit fixtures + helpers + config**

---

### Task 4: Mock e2e specs (milestone scenarios)

**Files:**
- Create: `e2e/mock/wizard.happy-path.spec.ts`
- Create: `e2e/mock/wizard.validation.spec.ts`
- Create: `e2e/mock/wizard.session.spec.ts`
- Create: `e2e/mock/wizard.generate-again.spec.ts`
- Deprecate or trim: `e2e/wizard.spec.ts` (move useful bits; delete obsolete dark-mode/Tauri-only assumptions)

- [ ] **Step 1: Happy path mock test** — Steps 1→4 with mocked parse/match/generate; assert results table
- [ ] **Step 2: Validation test** — empty Step 1 keeps Next disabled
- [ ] **Step 3: Session test** — save + load restores multi-day / location fields (mock POST/GET sessions)
- [ ] **Step 4: Generate Again** — after complete, button visible; second generate clears/re-registers
- [ ] **Step 5: Run locally**

```bash
bun run test:e2e:mock
```

- [ ] **Step 6: Commit**

---

### Task 5: Integration e2e (real FastAPI)

**Files:**
- Create: `e2e/playwright.integration.config.ts`
- Create: `e2e/integration/wizard.pipeline.spec.ts`
- Create: `e2e/scripts/run-integration.sh` (optional) or document GH Actions steps
- Modify: `package.json` (`test:e2e:integration`)

**Interfaces:**
- Consumes: sample files at `input/Zoom Attendance Report Arnoff 3.20.26.xlsx` and `input/Sample qualtrics.xlsx` (or `tests/fixtures/*` if those are the CI-safe copies — prefer fixtures checked into repo)
- Requires: backend on `127.0.0.1:8008`

- [ ] **Step 1: Confirm fixture paths exist in repo for CI**

If `input/` is gitignored, copy minimal fixtures under `tests/fixtures/` and use those paths. File dialogs in Tauri won’t work in browser — for browser integration tests, either:

1. Expose a **test hook** to set paths via `window` / query param (preferred for browser), or  
2. Mock only the file-picker but call real `/api/parse` with absolute fixture paths from the test via `page.evaluate` fetch.

**Chosen approach for v1:** Integration tests call the real API with known fixture paths using Playwright `request` / injected UI state: add a small `data-testid` or dev-only callback on StepUpload to set paths when `import.meta.env.MODE === 'test'` **OR** drive parse by evaluating fetch and then hydrating wizard — keep product change minimal.

Minimal product change (allowed): In `StepUpload`, if `import.meta.env.VITE_E2E === "1"`, show optional path inputs (hidden in prod). Playwright sets `VITE_E2E=1` when starting Vite for integration.

- [ ] **Step 2: Write integration spec** asserting match table non-empty and generate yields ≥1 certificate row
- [ ] **Step 3: Document local run**

```bash
uv run python src/backends/main.py &
VITE_E2E=1 bun run test:e2e:integration
```

- [ ] **Step 4: Commit**

---

### Task 6: CI workflow `test-ui.yml`

**Files:**
- Create: `.github/workflows/test-ui.yml`
- Modify: `e2e/README.md`
- Modify: `AGENTS.md` Commands table (add test scripts)

- [ ] **Step 1: Add workflow**

Jobs on `ubuntu-latest` for `pull_request` + `push` to `main`:

1. `unit` — bun install → `bun run test:unit` → `bun run build`
2. `e2e-mock` — bun install → Playwright Chromium → `bun run test:e2e:mock`
3. `e2e-integration` — bun + uv/python → start backend → `VITE_E2E=1 bun run test:e2e:integration`

Keep existing `build.yml` pytest as-is (still runs inside matrix builds).

- [ ] **Step 2: Add Tauri smoke section to README (manual only)** — do not implement driver yet beyond docs stub
- [ ] **Step 3: Open PR, ensure new workflow green
- [ ] **Step 4: Final commit**

```bash
git commit -m "ci: add UI unit and Playwright e2e jobs"
```

---

## Self-review checklist

1. Spec coverage: Vitest + mock e2e + integration e2e + CI + Tauri deferred — each has a task  
2. No TBDs remaining for v1 path (E2E path injection uses `VITE_E2E`)  
3. Commands use Bun / uv consistently  

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-21-ui-testing-suite.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
