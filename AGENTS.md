# AGENTS.md — psych-cert-gen

## Project Overview

Tauri v2 desktop app for generating CE certificates from Zoom attendance and Qualtrics survey data. Also provides a Python CLI for scripting.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri v2 (Rust) |
| Frontend | React + TypeScript + Vite + shadcn/ui + Tailwind CSS v4 |
| Backend | Python 3.12+ FastAPI (runs as sidecar, localhost:8008) |
| PDF generation | fpdf2 (pure Python) |
| Excel I/O | openpyxl |
| **Node package manager** | **Bun** (not npm, not pnpm) |
| Python package manager | uv |
| CI | GitHub Actions (builds macOS/Windows/Linux) |

## Commands

```bash
bun install          # install frontend dependencies
bun run build        # TypeScript type-check + Vite production build
bun run tauri dev    # start Tauri dev server (hot reload)
bun run tauri build  # build Tauri installer for current platform

uv sync              # install Python dependencies
uv run pytest        # run Python tests (23)
uv run python src/backends/main.py  # start FastAPI backend
```

## Architecture

```
Tauri v2 (Rust) → React frontend (ui/src/) → HTTP localhost:8008 → FastAPI (src/backends/)
                                                                   → pipeline (src/pipeline.py)
                                                                   → parsers/matcher/validator/generator
```

## Key Files

- `src-tauri/src/lib.rs` — sidecar lifecycle management
- `src/backends/main.py` — FastAPI app entry point
- `src/backends/routes.py` — API endpoints (parse, match, preview, generate, download-zip)
- `src/pipeline.py` — extracted pipeline orchestration
- `certgen.py` — original CLI entry point (still works)
- `ui/src/App.tsx` — 4-step wizard state machine
- `.github/workflows/build.yml` — CI/CD for macOS/Windows/Linux

## Rules

- No `as any`, `@ts-ignore`, `@ts-expect-error` in TypeScript
- No `# type: ignore` or bare `except:` in Python
- Original Python modules in `src/parser/`, `src/matcher/`, `src/validator/` must not be modified
- All 23 existing Python tests must pass
