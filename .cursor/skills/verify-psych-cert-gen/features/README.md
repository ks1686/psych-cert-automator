# Psych Cert Gen verification map

This directory is the maintained source for verifying Psych Cert Gen from the user's point of view. Read the index, then follow one feature file.

The primary surface is the four-step certificate wizard. The same screens run in the Tauri window and, for this harness, in the browser at `http://127.0.0.1:1420/`. `certgen.py` is the second surface.

## Baseline preconditions

- `uv sync` and `bun install` have been run in the repo.
- `node`, `pdftotext`, and Google Chrome or Chromium are on `PATH`.
- `PSYCH_CERT_TOKEN` is unset.
- Ports `8008` and `1420` are free. One verification run owns both. Launch refuses a second copy.
- Fixture workbooks only: `tests/fixtures/pilot_zoom.xlsx` and `tests/fixtures/pilot_qualtrics.xlsx`.
- Invoke `verify-psych-cert-gen` by its absolute path under `.cursor/skills/verify-psych-cert-gen/bin/`. The working directory does not matter.

## Driving conventions

- `verify-psych-cert-gen launch` is the baseline. Ready means the heading `Training Metadata` is visible.
- Run `verify-psych-cert-gen doctor --id RUN_ID` before a drive when a previous step looked wrong.
- Prefer the feature's `drive` command. Use `verify-psych-cert-gen browser --id RUN_ID -- OP ...` when a recipe names a single action.
- Roles and accessible names are exact. The path checked by `expect-url` is `/`.
- Seed dialog paths with `seed-paths` immediately before the Select buttons. That is the `VITE_E2E=1` dialog stub the app already ships.
- The generate output directory is the run's empty `output` folder. A second generate into a folder that already holds PDFs suffixes `_2`.
- Leave `Open output folder` and `Save Session` unclicked.

## Proof and skip reporting

- UI proof is a screenshot plus the heading or status text the recipe names.
- Generate proof also includes `pdftotext -layout` of the new PDFs: attendee name, date, instructor, title, and credit hours.
- CLI proof is the command's exit code plus those same PDF strings.
- Record the feature id and the `evidence=` path with the artifacts.
- If a step cannot run, report the command and the unmet precondition. A browser run does not verify the native Tauri window, the macOS `.dmg`, or the Windows `.msi`.

## Feature entry contract

Each feature file starts with an H1 and one paragraph, then exactly these H2 sections, in order:

1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with verify-psych-cert-gen`
4. `Gotchas`

## Features

- [Training metadata](./training-metadata.md) covers the first step: title, date, instructor, credits, CE types, and session times.
- [Upload files](./upload-files.md) covers choosing the Zoom and Qualtrics workbooks and parsing them.
- [Review matches](./review-matches.md) covers matched, ambiguous, and missing names, and the host row that is excluded.
- [Generate certificates](./generate-certificates.md) covers preview, generate, the PDF contents, and the zip download.
- [CLI batch](./cli-batch.md) covers `certgen.py` writing the same certificates into a folder.
