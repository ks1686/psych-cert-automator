# E2E Tests

Layered Playwright coverage for the Psych Cert Gen wizard.

| Suite | Command | Backend | Notes |
|-------|---------|---------|-------|
| Mock e2e | `bun run test:e2e:mock` | Stubbed via `page.route` | Default `bun run test:e2e`; starts Vite with `VITE_E2E=1` |
| Integration e2e | `bun run test:e2e:integration` | Real FastAPI on `:8008` | Uses `tests/fixtures/*.xlsx`; soft-fail PDF → `.docx` OK |
| Tauri smoke | `bun run test:e2e:tauri` | Sidecar + Tauri | **Manual / nightly only** — not in PR CI |

## Quick Start (mock)

```sh
bun install
bunx playwright install chromium
bun run test:e2e:mock
```

## Integration (real FastAPI)

```sh
bun install
uv sync
bunx playwright install chromium
bun run test:e2e:integration
```

The integration Playwright config starts FastAPI and Vite automatically.
For a manual split:

```sh
uv run python src/backends/main.py &
VITE_E2E=1 bun run test:e2e:integration
```

## Architecture

| Component | Endpoint |
|-----------|----------|
| Vite (browser e2e) | `http://127.0.0.1:1420` |
| FastAPI backend | `http://127.0.0.1:8008` |
| Tauri WebDriver (manual) | `http://127.0.0.1:4444` |

When `VITE_E2E=1`, Step 2 shows path text inputs so browser tests can set
Zoom/Qualtrics paths without Tauri file dialogs.

## Writing New Tests

- Prefer `page.getByRole()` for buttons, inputs, and headings.
- Use `page.locator('#id')` for elements with DOM IDs (form fields).
- Use shared helpers in `e2e/helpers/wizard.ts`.
- Avoid `page.waitForTimeout()` — use `expect().toBeVisible()`.
- Run headed: `bun run test:e2e:mock -- --headed`

## Tauri smoke (manual)

PR CI does **not** run Tauri WebDriver. For local smoke against the desktop shell:

1. `uv run python src/backends/main.py`
2. `bun run tauri dev`
3. `bun run test:e2e:tauri` (expects the Vite surface at `:1420`; full WebDriver wiring is optional — see comments in `e2e/playwright.config.ts`)
