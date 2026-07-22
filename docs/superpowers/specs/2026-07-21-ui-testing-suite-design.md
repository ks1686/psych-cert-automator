# UI-Centered Testing Suite — Design

**Date:** 2026-07-21  
**Status:** Approved

## Goal

Build a layered testing pyramid so UI regressions are caught in CI without requiring Tauri on every PR, while keeping an optional path to real desktop smoke tests.

## Decisions

| Topic | Choice |
|-------|--------|
| Architecture | Layered: pytest + Vitest/RTL + Playwright mock e2e + Playwright integration e2e + optional Tauri smoke |
| PR CI | Vitest + mock Playwright + integration Playwright + existing pytest; **no** Tauri in PR CI |
| Playwright backends | Mock API fixtures by default; separate real FastAPI + sample xlsx job |
| Tauri | Manual / nightly / `workflow_dispatch` only (v1) |

## Layers

| Layer | Tool | Proves | PR CI |
|-------|------|--------|-------|
| Domain | pytest | Parsers, pipeline, templates, sessions | Yes (existing build job) |
| Components | Vitest + Testing Library + jsdom | Step validation, exclude/host, Generate Again | Yes (new job) |
| UI e2e mock | Playwright → Vite | Full wizard with stubbed `/api/*` | Yes |
| UI e2e integration | Playwright → Vite + FastAPI | Parse/match/generate with sample files | Yes (Ubuntu) |
| Tauri smoke | Playwright + tauri-driver (later) | App boots + Step 1 | Manual/nightly |

## Fixtures

- `e2e/fixtures/api/` — JSON / SSE stubs for mock e2e (`parse`, `match`, `preview`, `generate`, `sessions`)
- `input/` or `tests/fixtures/` sample Zoom/Qualtrics for integration e2e
- Component tests: in-memory props; stub `@tauri-apps/plugin-dialog` where needed

## Local commands

```bash
uv run pytest
bun run test:unit
bun run test:e2e:mock
bun run test:e2e:integration
bun run test:e2e:tauri   # documented; not PR-blocking
```

## First milestone coverage

**Vitest:** StepMetadata validation (multi-day, location, CE types); StepMatchReview exclude/host; StepGenerate “Generate Again”.

**Mock e2e:** Happy path; Step 1 validation; session save/load with new fields; Generate Again.

**Integration e2e:** Real sample files → matches → generate reports certificates (PDF or docx soft-fail OK).

## Out of scope (v1)

- Tauri WebDriver in PR CI
- Visual regression
- Dark-mode suite (unless feature is confirmed live)
- Rewriting existing Python tests
