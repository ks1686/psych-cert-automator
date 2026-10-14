# CE Certificate Automator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/ks1686/psych-cert-automator)](https://github.com/ks1686/psych-cert-automator/releases/latest)

Turns a Zoom attendance report and a Qualtrics CE survey into one certificate per eligible person and CE type.

Built for the GSAPP Psychology Department at Rutgers. Desktop installers are published for macOS, Windows, and Linux. People who use the installer do not need Python.

## What it does

1. Reads a Zoom attendance workbook (who joined, when they left, and who the host was).
2. Reads a Qualtrics CE request export (name, email, requested CE type, and an optional NY license number).
3. Matches people across the two files by name.
4. Keeps a request when late arrival, early departure, and total time missed (including mid-session gaps) are each 15 minutes or less. Waiting-room rows are ignored.
5. Fills the official Word template for that CE type and writes a PDF.
6. Writes `ineligibility_report.xlsx` for anyone who was skipped, with the reason.

The Zoom host is pre-excluded and can be included again from Review Matches. Any other row can be excluded with its own checkbox. The same names can be passed to the CLI with repeatable `--exclude`.

Deleting the output files and running again creates a fresh set of certificates.

## Certificate types

| Requested type | Template | Page |
| --- | --- | --- |
| APA, or psychologist (APA) | `templates/apa.docx` | US Letter, landscape |
| NY, New York, or psychologist (New York) | `templates/ny.docx` | US Letter, landscape |
| NASP, or school psychologist | `templates/nasp.docx` | US Letter, portrait |
| NBCC, or counselor | `templates/nbcc.docx` | US Letter, landscape |
| Anything else, including a former BCBA request | `templates/attendance.docx` | US Letter, portrait |

Certificate of Attendance is the fallback when the Qualtrics choice does not match NY, APA, NASP, or NBCC. The desktop wizard offers APA, NASP, NY, and NBCC. Attendance is selected automatically.

Virtual events keep the template's virtual location and format. NASP virtual certificates say "via Live Zoom Webinar". In-person events print the location you enter, and NASP says "at {location}". A multi-day event with an end date prints a start and end date on the certificate.

Each file is named `LastName_CECertificate_InstructorLastName_M.D.YY.pdf` (for example `Chen_CECertificate_Solano_10.6.26.pdf`). If two certificates would share that name, the first name is added, then the CE type, then a number. Characters that are unsafe in a filename, including accents, are replaced in the file name. The name printed on the certificate keeps accents, apostrophes, and hyphens.

PDF conversion uses the bundled `dxpdf` converter. LibreOffice and Microsoft Word are optional fallbacks. If conversion fails, the filled `.docx` is kept and a warning is logged. Template fonts such as Californian FB, Calibri, and Times are not embedded in the Word files. `dxpdf` substitutes and embeds Arimo, Tinos, and Noto Sans. That substitution is the look these tests lock in.

The CLI writes files into `--output-dir` and does not build a zip. The desktop app and `POST /api/download-zip` can bundle the PDFs (and any leftover `.docx` files) into a zip.

## Desktop app

Download the latest installer from [Releases](https://github.com/ks1686/psych-cert-automator/releases):

| Platform | Download |
| --- | --- |
| macOS | `.dmg` (drag to Applications) |
| Windows | `.msi` |
| Linux | `.deb` |

Release builds run on pushes to `main` and on `v*` tags. macOS release builds are signed with Developer ID and notarized when the Apple secrets are present. A local `bun run tauri build` stays unsigned: `signingIdentity` in `src-tauri/tauri.conf.json` is null. The published Linux artifact is the `.deb`. The Tauri bundle list also names `rpm`, but the release workflow uploads the `.deb`.

The app is offline. Its Python sidecar listens on `http://127.0.0.1:8008`.

The wizard has four steps: upload the two workbooks, enter the session, review matches, then generate. Session metadata can be saved as JSON under `~/.psych-cert-gen/sessions` through `POST /api/sessions`. There is no separate CLI config file. The CLI flags are the script interface, and that JSON API is the saved-session interface.

## CLI

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ks1686/psych-cert-automator.git
cd psych-cert-automator
uv sync

uv run python certgen.py \
  --title "Training Title Here" \
  --date "2026-03-20" \
  --instructor "Dr. Jane Smith" \
  --ce-credits 3 \
  --ce-types "APA,NASP,NY,NBCC" \
  --start-time "08:47" \
  --end-time "12:11" \
  --zoom-report "path/to/zoom_attendance.xlsx" \
  --qualtrics-report "path/to/qualtrics_export.xlsx" \
  --output-dir "./output"
```

| Flag | Required | Purpose |
| --- | --- | --- |
| `--title` | yes | Training title |
| `--date` | yes | Start date, `YYYY-MM-DD` |
| `--end-date` | no | Multi-day end date, `YYYY-MM-DD` |
| `--instructor` | yes | Instructor name printed on the certificate |
| `--ce-credits` | yes | Integer credit count |
| `--ce-types` | yes | Comma-separated types offered, for example `APA,NASP,NY,NBCC` |
| `--start-time` | yes | Session start, `HH:MM` |
| `--end-time` | yes | Session end, `HH:MM` |
| `--in-person` | no | In-person wording. Default is virtual |
| `--location` | with `--in-person` | Location text. Required when `--in-person` is set |
| `--exclude` | no | Qualtrics certificate name to skip. Repeat the flag for more names |
| `--zoom-report` | yes | Zoom attendance `.xlsx` |
| `--qualtrics-report` | yes | Qualtrics export `.xlsx` |
| `--output-dir` | no | Output directory. Default `./output` |
| `--manual-overrides` | no | CSV of Qualtrics name to Zoom name overrides |

A Qualtrics row with an empty name or an empty CE type is skipped by the parser. One corrupt Zoom duration cell fails that workbook and the CLI exits with an error. The ineligibility workbook is written only after a successful parse.

## Development

| Tool | Version | Install |
| --- | --- | --- |
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) |
| uv | latest | see uv docs |
| Rust | 1.80+ | [rustup](https://rustup.rs/) |
| Bun | 1.3+ | [bun.sh](https://bun.sh/) |
| poppler | 24.02 for golden tests | `poppler-utils` (`pdftoppm`, `pdftotext`, `pdfinfo`, `pdffonts`) |

Frontend packages use Bun, not npm or pnpm.

```bash
uv sync
bun install

# Terminal 1: API at http://localhost:8008
uv run python src/backends/main.py

# Terminal 2: desktop app with hot reload
bun run tauri dev
```

### Tests

```bash
uv run pytest                    # Python tests, including certificate layout
bun run test:unit                # Vitest wizard tests
bun run test:e2e:mock            # Playwright with a stubbed API
bun run test:e2e:integration     # Playwright plus the real FastAPI app
bun run build                    # TypeScript check and Vite build
cargo check --manifest-path src-tauri/Cargo.toml
```

`tests/test_certificate_layout.py` renders every template, checks that text stays inside the page, and compares the PNG to `tests/fixtures/golden/`. Regenerate those fixtures only after an intentional layout change:

```bash
UPDATE_CERTIFICATE_GOLDENS=1 uv run pytest tests/test_certificate_layout.py
```

The Test workflow on Ubuntu 24.04 installs poppler, `fonts-croscore`, and `fonts-noto-core`, then runs pytest. `tests/conftest.py` points fontconfig at `tests/fixtures/fontconfig/fonts.conf` so Californian FB becomes Tinos and Arial Unicode MS uses Ubuntu's Noto Sans file. Golden images are tied to poppler 24.02 and those font packages. A different poppler build or a different Noto Sans file can fail the 0.1 percent pixel threshold even when the wording is unchanged.

### Installers

```bash
uv run python build/build.py
bun run tauri build
# src-tauri/target/release/bundle/  (.dmg, .msi, or .deb)
```

Tagging `vX.Y.Z` on `main` runs the release workflow, which builds the macOS, Windows, and Linux installers and publishes a GitHub Release. Bump `pyproject.toml`, `package.json`, `src-tauri/tauri.conf.json`, and `src-tauri/Cargo.toml` together, then refresh `uv.lock`.

## Further reading

[PLAN.md](PLAN.md) is a historical design note. It is not the current spec. Use this README for what the app does today.
