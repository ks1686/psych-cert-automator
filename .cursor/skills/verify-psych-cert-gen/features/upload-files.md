# Upload files

The second step asks for a Zoom attendance workbook and a Qualtrics CE survey workbook, then parses both. The status line reports how many participants and how many CE requests were found.

## Sub-features

- `upload-zoom` stores the Zoom workbook the user picks.
- `upload-qualtrics` stores the Qualtrics workbook the user picks.
- `upload-parse` shows the participant count and the CE request count.

## How to get to it (user POV)

- Finish Training Metadata and choose Next.
- The card heading is `Step 2: Upload Files`.
- Choose `Select Zoom Report`, then `Select Qualtrics Survey`, then `Parse Files`.

## Driving it with verify-psych-cert-gen

Preconditions:

- The metadata drive would enable Next for the pilot session.
- The fixture files exist at `tests/fixtures/pilot_zoom.xlsx` and `tests/fixtures/pilot_qualtrics.xlsx`.
- The run's output directory is the empty folder under the state directory.

Packaged check: `verify-psych-cert-gen drive --id RUN_ID upload-files`.

- **Reach the step.** After the metadata fields are filled and APA, NASP, NY, and NBCC are checked, run `verify-psych-cert-gen browser --id RUN_ID -- click-role button Next`, then `verify-psych-cert-gen browser --id RUN_ID -- wait-heading "Step 2: Upload Files"`. The heading is `Step 2: Upload Files`.
- **Point the dialog stub at the fixtures.** Run `verify-psych-cert-gen browser --id RUN_ID -- seed-paths <zoom.xlsx> <qualtrics.xlsx> <output-dir>` with the two fixture paths and the run output directory. This sets `window.__E2E_PATHS__` before the clicks. The native dialog is not opened.
- **Choose the files.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Select Zoom Report"` and `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Select Qualtrics Survey"`. Each row shows the chosen file name.
- **Parse.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Parse Files"`, then `verify-psych-cert-gen browser --id RUN_ID -- expect-text "14 participants found, 14 CE requests found"`. That sentence is visible.

## Gotchas

- `Parse Files` stays disabled until both files are chosen. Seed the paths before the Select clicks. Seeding after the clicks leaves the parse button disabled.
- The dialog titles the stub matches are `Select Zoom Attendance Report` and `Select Qualtrics CE Survey`. The button names the user sees are `Select Zoom Report` and `Select Qualtrics Survey`.
- The status sentence is exact, including the comma. A different fixture will show different counts, and this recipe will fail until the feature file is updated.
- Parsing calls the real API. If `/health` is a different process than the one launch recorded, stop and run doctor.
