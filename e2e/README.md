# E2E Tests

Playwright end-to-end tests for the Psych Cert Gen Tauri application.

## Quick Start

```sh
# 1. Install dependencies (first time only)
pnpm install

# 2. Start the FastAPI backend
uv run uvicorn certgen:app --port 8008

# 3. Start the Tauri app in dev mode (separate terminal)
pnpm tauri dev

# 4. Run the tests
pnpm test:e2e
```

## Test Scenarios

| # | Scenario | File |
|---|----------|------|
| 1 | Full happy path — complete all 4 steps, verify results | `wizard.spec.ts` |
| 2 | Step 1 validation — empty fields, invalid date, end before start | `wizard.spec.ts` |
| 3 | Step 2 edge cases — missing file, corrupted xlsx handling | `wizard.spec.ts` |
| 4 | Step 3 match review — ambiguous correction, not-found match, skip | `wizard.spec.ts` |
| 5 | Step 4 preview — preview loads, progress bar, results table | `wizard.spec.ts` |
| 6 | Session save/load — save session, reload, verify fields restored | `wizard.spec.ts` |
| 7 | Dark mode toggle — verify theme switches | `wizard.spec.ts` |
| 8 | Startup timeout — simulate backend failure, verify error screen | `wizard.spec.ts` |

## Architecture

| Component | Endpoint |
|-----------|----------|
| Tauri WebDriver | `http://127.0.0.1:4444` |
| Vite dev server | `http://localhost:1420` |
| FastAPI backend | `http://localhost:8008` |

The Playwright config at `e2e/playwright.config.ts` is configured for Chromium
desktop with a 1200×950 viewport matching the Tauri window. Tauri manages its own
application process, so no `webServer` block is needed.

## Writing New Tests

- Prefer `page.getByRole()` for buttons, inputs, and headings.
- Use `page.locator('#id')` for elements with DOM IDs (form fields).
- Use `page.getByText()` for text content assertions.
- Avoid `page.waitForTimeout()` — use `expect().toBeVisible()` or
  `page.waitForSelector()` instead.
- Run with `--debug` for headed mode: `pnpm test:e2e --debug`
