---
name: verify-psych-cert-gen
description: "Drive Psych Cert Gen the way a user does: the React certificate wizard served by Vite, the FastAPI backend, and the certgen.py CLI. Use to launch an isolated run, check it is healthy, walk a fixture Zoom and Qualtrics journey, and prove the generated certificate PDFs."
---

# Verify Psych Cert Gen

Psych Cert Gen is a Tauri desktop app. The user-facing surface proved here is the same React wizard the desktop shell loads, plus the `certgen.py` command. The wizard talks to FastAPI on `127.0.0.1:8008`. During verification the wizard is served by Vite at `http://127.0.0.1:1420/` with `VITE_E2E=1`, which swaps only the native file dialog and the "open folder" opener for the repo's existing stubs. Parse, match, preview, and PDF generation still hit the real backend and the real Word templates.

Use fixture files only. The pilot pair is `tests/fixtures/pilot_zoom.xlsx` and `tests/fixtures/pilot_qualtrics.xlsx`. Those rows are synthetic. Do not invent attendee names, and do not point the wizard at a real export.

The helper binary works from any working directory:

```bash
HELPER="<repo>/.cursor/skills/verify-psych-cert-gen/bin/verify-psych-cert-gen"
```

In the feature map, `verify-psych-cert-gen` means that binary. Call it by absolute path.

## Launch

Preconditions, from the repo root, once per machine:

- `uv sync` so `.venv/bin/python` exists
- `bun install` so Vite and Playwright can start
- `node`, `pdftotext`, and Google Chrome on `PATH`. The wizard browser is Playwright with `channel: "chrome"`. Chromium does not satisfy that launch.
- ports `8008` and `1420` free

Leave `PSYCH_CERT_TOKEN` unset. A token makes the browser UI receive 401, because the dev client sends a token only inside the Tauri shell.

```bash
"$HELPER" launch
```

Launch refuses the run when either port is already taken. It does not kill a process it did not start. Two copies cannot share the dev ports, because the UI client always calls `127.0.0.1:8008`.

What launch starts, in order:

1. A private state directory (`mktemp`, mode `0700`) with an isolated `HOME` and `TMPDIR`. The real home is not the process home.
2. The API as `"$REPO/.venv/bin/python" src/backends/main.py` with `PSYCH_CERT_PORT=8008`. The supervised pid is the API process. `/health` must report that same pid.
3. Vite: `VITE_E2E=1 bun run dev -- --host 127.0.0.1 --port 1420`.
4. Headless Google Chrome driven by Playwright with `channel: "chrome"`.
5. A navigation to `http://127.0.0.1:1420/` and a wait until the heading `Training Metadata` is visible.

Ready means that heading. The startup screen can already show a healthy backend for about 1.5 seconds before the wizard mounts. A passing `/health` is not ready.

Launch prints `run_id`, `evidence`, `ui`, and `api`. Keep the run id. The evidence directory is the proof location and survives cleanup.

## Doctor

```bash
"$HELPER" doctor --id RUN_ID
```

Doctor is read-only. It passes only when all of these are true:

- `package.json`, `pyproject.toml`, and `src-tauri/tauri.conf.json` publish the same version
- the recorded API pid is still the process this run started (command, start time, owner) and `http://127.0.0.1:8008/health` reports that pid
- `http://127.0.0.1:1420/` returns 200 and the path is exactly `/`
- the recorded UI and browser pids still match what this run started

Doctor always uses those two URLs. It does not read a port or a binary path out of the run state file.

## Drive

Feature recipes live in `features/`. Drive one feature with:

```bash
"$HELPER" drive --id RUN_ID generate-certificates
```

Other feature ids: `training-metadata`, `upload-files`, `review-matches`, `cli-batch`.

A single browser action, when a recipe needs one step:

```bash
"$HELPER" browser --id RUN_ID -- click-role button "Next"
"$HELPER" browser --id RUN_ID -- fill-label "Training Title" "Ethics and Practice in School-Based Mental Health"
"$HELPER" browser --id RUN_ID -- expect-url /
```

Allowed browser ops are `goto`, `expect-url`, `wait-heading`, `click-role`, `fill-label`, `check-role`, `expect-enabled`, `expect-output`, `expect-text`, `expect-host`, `seed-paths`, `wait-canvas`, `screenshot`, `aria`, `scan-side-effects`, and `download-zip`. `goto` accepts only `/`, and the page must stay on `http://127.0.0.1:1420/`.

`seed-paths` writes `window.__E2E_PATHS__` before the Select buttons. That is the same seam `VITE_E2E=1` already uses in the repo's Playwright tests. The buttons that follow are the real wizard buttons.

The generate journey fills the metadata form, selects the two fixture workbooks, parses, reviews matches, previews, chooses an empty output folder, generates, and then reads the PDF bytes with `pdftotext -layout`. The output proof requires exactly 8 new PDFs and one `ineligibility_report.xlsx`. Any other new file, including a `.docx` from a failed conversion, fails the journey. The folded PDF text must contain `Avery Chen`, `October 6, 2026`, `Amira Solano`, the training title, and either `CE CREDITS: 3` or `CE CREDIT HOURS: 3`. It must not contain the host name `Morgan Hale`.

Do not click `Open output folder`. Do not click `Save Session`. Both would reach outside the isolated home or the stubbed opener.

## Evidence

Each run's evidence directory is printed as `evidence=` by launch, doctor, and cleanup. Captures are mode `0600`. The generate drive writes:

- `metadata-desktop.png`, `upload-desktop.png`, and `review-desktop.png`, each the 1280x900 viewport
- `generate-desktop.png` (1280x900), `generate-tablet.png` (768x1024), and `generate-mobile.png` (375x812), each the viewport
- `full-` copies of those screenshots, the whole scrollable page at the same viewport width
- `generate.aria.txt`
- `drive.log`, `pdf-text.txt`, `pdf-names.txt`, `side-effects.txt`

The unsuffixed PNGs are the viewport, so their pixel size is the width and height requested. A `full-` PNG is the whole page at that same viewport width; a wide table can make that bitmap wider than the viewport. At 375px the step names in the top nav are hidden by `hidden sm:inline`. The card heading is still on screen.

The output PDFs and `ineligibility_report.xlsx` land in the run's private `output` directory. Cleanup deletes that scratch directory. Copy any PDF or screenshot you need to keep into the evidence directory before cleanup, or rely on the files the drive already copied there (`pdf-text.txt`, `pdf-names.txt`, and the screenshots).

## Cleanup

```bash
"$HELPER" cleanup --id RUN_ID
```

Cleanup signals only the API, UI, and browser pids this run recorded, and only after the live command, start time, and owner still match. Start time is read with `TZ=UTC0` and `LC_ALL=C`. On a match it removes the isolated home, temp, output, and logs, prints a line `cleaned`, then prints `evidence=`. The evidence directory stays.

If identity cannot be confirmed, cleanup exits nonzero, leaves the state directory in place, and does not print `cleaned`. The recovery command, once you have confirmed the processes are already gone, is:

```bash
"$HELPER" cleanup --id RUN_ID --abandon
```

Abandon signals nothing. It removes scratch only when every recorded pid is already dead and the real home's `~/.psych-cert-gen` snapshot is unchanged. It prints `abandoned`.

Cleanup requires the explicit run id. It will not pick the latest run.

## Helpers

Regression, from any directory on Linux or macOS:

```bash
bash "<repo>/.cursor/skills/verify-psych-cert-gen/bin/regress.sh"
```

The script creates its own scratch with `mktemp`, proves the guards below, and deletes that scratch on the way out. A passing run prints `regression passed` and exits 0.

Guards the helpers enforce, and that `regress.sh` fails on if they regress:

- State and evidence directories are created with `mktemp` and mode `0700`. An existing directory the caller names is refused when it is not owned by this user or is writable by group or other. The helpers never chmod a directory the caller passed in. Evidence files are mode `0600`.
- `run.env` is parsed as `KEY=value` lines. Nothing sources or evals it. `HOME`, tool paths, and the ports doctor connects to come from the process that started the run, not from values stored in `run.env`.
- Run ids match `^[A-Za-z0-9_-]+$`. `.` and `..` are rejected. Each launch gets a new id. Cleanup without an id exits 2.
- A failed launch kills that pid, and signals the process group only when the live group id is that pid. Cleanup compares `ps` command, owner, and UTC start time before any signal. A mismatch signals nothing.
- Evidence writes resolve the target, require it to sit inside this run's evidence directory, refuse symlinks, and refuse names that would overwrite helper files (`run.env`, `evidence-name`, and the other reserved names).
- The child environment keeps `GOMODCACHE`, `GOENV`, `PLAYWRIGHT_BROWSERS_PATH`, and the npm cache, and sets `GOTELEMETRY=off`. On macOS it also sets `CFFIXED_USER_HOME` to the isolated home. Read-only caches under the isolated home are made writable before removal.
- The shell is written for bash 3.2: no `mapfile`, and empty arrays are expanded safely under `set -u`.
- `tel:`, `sms:`, `mailto:`, and `payment:` links are recorded and the drive fails if a page contains one. The helper does not open them.
- `copy-sandbox` copies only `git ls-files` paths.
- Accessible names come from the rendered control. URL checks compare the path exactly (`/` is the only wizard path).
- Process start times use `TZ=UTC0 LC_ALL=C ps -o lstart=`. If `ps` fails, cleanup fails closed.
- Hash and snapshot walks fail when any entry is unreadable. Path checks use the whole real path, so `/tmp/a/../../etc/passwd` is outside `/tmp`. An unsupported `uname` exits before any directory is created.
- `run -- COMMAND` returns that command's status. `run -- false` exits 1.
- A process group is signaled only after the live group id is read, not from a stored group id.
- The real `~/.psych-cert-gen` tree is snapshotted before launch and compared again during cleanup, by full path. On macOS the comparison also includes `~/Library/Preferences/edu.rutgers.gsapp.psych-cert-gen.plist` and `~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist`, each by full path.

```bash
"$HELPER" run -- pdftotext -layout path/to/certificate.pdf -
"$HELPER" copy-sandbox /path/to/repo /path/to/empty-dir
```

## Unverified here

These stay unverified until a run on that platform does them. The skill's commands for them are still the real ones; this Linux proof did not execute them.

- The native Tauri window (`bun run tauri dev` / the packaged `.deb`). It needs WebKitGTK and a desktop session. This proof uses the Vite URL the Tauri window loads, with the real FastAPI process.
- The signed macOS `.dmg`, Developer ID signing, and notarization.
- The Windows `.msi`, and the webview origin `http://tauri.localhost`.
- A release sidecar that picks a random port and requires `PSYCH_CERT_TOKEN`.
- The native file dialog. `VITE_E2E=1` uses the repo's dialog stub, which is the production boundary for that plugin during browser runs.
- The `Open output folder` button. The opener plugin is stubbed and the drive does not click it.
- A real macOS preferences database. The Darwin home check in `regress.sh` sets `CFFIXED_USER_HOME` and compares a fixture plist path; it does not launch the `.app`.
- First Mac check: cleanup also snapshots `com.apple.launchservices.secure.plist`. Launch Services is a system database, and another app can rewrite it during a run. On a Mac, confirm a quiet run still prints `cleaned`, and that a change to that plist keeps state and does not print `cleaned`. This Linux run cannot prove that file.

## Maintenance

When the wizard steps, certificate wording, or fixture counts change, run `/maintain-verification-skill` and update the feature file that owns the changed step. The generate journey's PDF strings are part of the proof; keep them aligned with `src/generator/templates.py`.
