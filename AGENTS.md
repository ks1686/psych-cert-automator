# AGENTS.md — psych-cert-gen

## Project Overview

Tauri v2 desktop app for generating CE certificates from Zoom attendance and Qualtrics survey data. Also provides a Python CLI for scripting.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri v2 (Rust) |
| Frontend | React + TypeScript + Vite + shadcn/ui + Tailwind CSS v4 |
| Backend | Python 3.12+ FastAPI (runs as sidecar, localhost:8008) |
| PDF generation | Official Word templates (lxml + zipfile) + bundled dxpdf (LibreOffice/Word optional fallback) |
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
bun run test:unit    # Vitest + Testing Library (wizard components)
bun run test:e2e:mock          # Playwright mock e2e (stubbed API)
bun run test:e2e:integration   # Playwright + real FastAPI + fixtures

uv sync              # install Python dependencies
uv run pytest        # run Python tests
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
- `.github/workflows/test.yml` — pytest, ruff, cargo check, Vitest, Playwright (mock + integration)
- `.github/workflows/build.yml` — sidecar + signed installers on main/tags (PRs skip Tauri)

## Rules

- No `as any`, `@ts-ignore`, `@ts-expect-error` in TypeScript
- No `# type: ignore` or bare `except:` in Python
- Original Python modules in `src/parser/`, `src/matcher/`, `src/validator/` must not be modified
- Existing Python tests must pass; do not drop coverage to hit a count

## Learned User Preferences

- Prefer filling official Word (`.docx`) CE templates (mail-merge) over the generic fpdf layout; PDF conversion uses bundled `dxpdf` and soft-fails to writing `.docx` with a warning if conversion fails
- Supported CE types are NY, APA, NASP, NBCC (Counselors), and Certificate of Attendance; remove BCBA
- Certificate of Attendance is the fallback when the Qualtrics CE type has no matching NY/APA/NASP/NBCC template
- Multi-day events should show a start–end date range on the certificate (single-date vs range may change later)
- Keep event span (single-day vs multi-day) and delivery (virtual vs in-person) as separate controls; in-person shows a Location field, virtual locks the template’s virtual Location/Format strings
- Auto-detect the Zoom host from the attendance report and pre-exclude them in Review Matches with an override checkbox
- Provide a per-row Exclude checkbox in Review Matches for stragglers who should not receive a certificate
- Use the combined NASP template that supports both virtual and in-person wording (`NASP Certificate TEMPLATE.docx`), not the virtual-only `TEMPLATE-2`
- Emit one certificate file per person named `LastName_CECertificate_InstructorLastName_Date` (zip optional); disambiguate when attendees share the same name; Downloads as the output location is fine without a custom path system
- After a generate run, deleting output files and running again must recreate certificates (do not leave Generate permanently unavailable or rely on stale download tokens)
- Prefer signed and notarized macOS builds distributed via GitHub Releases (Developer ID Application); Apple Development identity is for local codesign only — not Gatekeeper/release/notarization
- When verifying, run the full UI workflow end-to-end on the live app; keep Windows, macOS, and Linux support intact

## Learned Workspace Facts

- GitHub remote is `ks1686/psych-cert-automator` (local workspace folder may be named `psych-cert-gen`)
- FastAPI CORS must allow the Windows Tauri webview origin `http://tauri.localhost`
- Official CE Word templates (APA, NY, NASP, NBCC, Certificate of Attendance) are the source of truth for certificate layout and are intended to live under the project (e.g. `templates/`) rather than only in `~/Downloads`
- Apple Developer Program is available; release signing/notarization uses Developer ID + App Store Connect API materials kept outside the repo (genv / `~/.appstoreconnect/`) — never commit `.p8`, `.p12`, or private keys
- Tauri updater `TAURI_SIGNING_*` secrets are separate from Apple codesign/notarization; macOS builds were previously unsigned (`signingIdentity: null`)
