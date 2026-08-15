# CE Certificate Automator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/ks1686/psych-cert-automator)](https://github.com/ks1686/psych-cert-automator/releases/latest)

**Turns your Zoom attendance and Qualtrics survey into individual CE certificates — automatically.**

Built for the GSAPP Psychology Department at Rutgers. Desktop installers for macOS, Windows, and Linux — no Python required for end users.

---

## What it does

1. Reads your Zoom attendance report (who showed up, when they joined/left)
2. Reads your Qualtrics CE request survey (who wants which CE credits)
3. Matches people across both files by name
4. Checks that each person attended the full session (no more than 15 minutes missed)
5. Generates a professional PDF certificate for each eligible person, per CE type
6. Produces a summary spreadsheet of anyone who was skipped and why

**What used to take hours of manual work now takes seconds.**

---

## Desktop App (recommended)

Download the latest installer from [Releases](https://github.com/ks1686/psych-cert-automator/releases):

| Platform | Download |
|----------|----------|
| macOS | `.dmg` file — drag to Applications |
| Windows | `.msi` file — double-click to install |
| Linux | `.deb` file — install with your system package manager |

The app is self-contained — no Python, Node, or other dependencies needed. Works fully offline.

> **macOS note**: Release builds are signed with Developer ID and notarized by Apple. After installing from the `.dmg`, the app should open normally under Gatekeeper.

## CLI (for automation / scripts)

### One-time setup

```bash
# Prerequisites: Python 3.12+, uv
pip install uv
git clone https://github.com/ks1686/psych-cert-automator.git
cd psych-cert-automator
uv sync
```

### Usage

```
uv run python certgen.py \
  --title "Training Title Here" \
  --date "2026-03-20" \
  --instructor "Dr. Jane Smith" \
  --ce-credits 3 \
  --ce-types "APA,NASP,NY" \
  --start-time "08:47" \
  --end-time "12:11" \
  --zoom-report "path/to/zoom_attendance.xlsx" \
  --qualtrics-report "path/to/qualtrics_export.xlsx" \
  --output-dir "./output"
```

---

## Development

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Python** | 3.12+ | [python.org](https://www.python.org/downloads/) |
| **uv** | latest | `pip install uv` |
| **Rust** | 1.80+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| **Bun** | 1.3+ | `curl -fsSL https://bun.sh/install \| bash` |

> **Node.js package management uses Bun**, not npm or pnpm. `bun install`, `bun run build`, etc.

### Setup

```bash
git clone https://github.com/ks1686/psych-cert-automator.git
cd psych-cert-automator

# Python backend
uv sync

# Frontend + Tauri
bun install
```

### Run locally

```bash
# Terminal 1 — Python backend (http://localhost:8008)
uv run python src/backends/main.py

# Terminal 2 — Tauri desktop app (hot-reload)
bun run tauri dev
```

### Testing

```bash
uv run pytest                    # Python tests
bun run test:unit                # Vitest wizard unit tests
bun run test:e2e:mock            # Playwright mock e2e (stubbed API)
bun run test:e2e:integration     # Playwright + real FastAPI + fixtures
bun run build                    # TypeScript type-check + Vite build
cargo check --manifest-path src-tauri/Cargo.toml  # Rust compilation
# GitHub Actions: Test workflow on every PR/main push; full installers on main/tags
```

### Build for distribution

```bash
# Build Python sidecar
uv run python build/build.py

# Build Tauri installer for current platform
bun run tauri build
# → src-tauri/target/release/bundle/  (.dmg / .msi / .deb)
```

### Release

```bash
# Bump version in pyproject.toml, src-tauri/tauri.conf.json, package.json
git add pyproject.toml src-tauri/tauri.conf.json package.json
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags
# CI builds macOS arm64, Windows x64, and Linux x64 installers,
# then creates a GitHub Release automatically
```

---

## Questions?

For technical details see [PLAN.md](PLAN.md). For department-specific questions, ask your program coordinator.
