# CLI batch

`certgen.py` runs the same pipeline without the wizard. The user passes the session fields and the two workbooks and gets one certificate file per eligible person in the output directory.

## Sub-features

- `cli-run` writes certificates from the pilot fixtures with the virtual session defaults.
- `cli-contents` puts the same name, date, instructor, title, and credit hours in the PDF text.
- `cli-host` leaves the Zoom host out unless `--include-host` is passed.

## How to get to it (user POV)

- From a terminal, with the repo's virtualenv Python:

```bash
.venv/bin/python certgen.py \
  --title "Ethics and Practice in School-Based Mental Health" \
  --date 2026-10-06 \
  --instructor "Dr. Amira Solano" \
  --ce-credits 3 \
  --ce-types APA,NASP,NY,NBCC \
  --start-time 09:00 \
  --end-time 12:00 \
  --zoom-report tests/fixtures/pilot_zoom.xlsx \
  --qualtrics-report tests/fixtures/pilot_qualtrics.xlsx \
  --output-dir <empty-directory>
```

- The command exits 0 and the directory contains PDFs plus `ineligibility_report.xlsx`.

## Driving it with verify-psych-cert-gen

Preconditions:

- `verify-psych-cert-gen launch` has created a run, so the output directory is the isolated one under that run. The CLI drive uses `<state>/output/cli`, which it creates empty.
- `.venv/bin/python` exists. The API and the browser can stay up; the CLI does not use port 8008.

Packaged check: `verify-psych-cert-gen drive --id RUN_ID cli-batch`.

- **Run the command.** The drive executes the argument list above with `--output-dir` set to the run's `output/cli` directory, under the isolated home. The process exits 0.
- **Read the PDFs.** The drive checks the new files the same way as generate: exactly 8 PDFs, one `ineligibility_report.xlsx`, and no other new file. Folded text contains `Avery Chen`, `October 6, 2026`, `Amira Solano`, the training title, and `CE CREDITS: 3` or `CE CREDIT HOURS: 3`. `Morgan Hale` is absent.

## Gotchas

- `--in-person` requires `--location`. The packaged drive leaves the default, which is virtual.
- `--include-host` would print a certificate for Morgan Hale and fail this proof.
- The CLI writes `.docx` files when PDF conversion fails. `prove-pdfs` fails when any new `.docx` or any other unexpected file is present, and when the PDF count is not exactly 8.
- Run the CLI through the helper so the child home is the run's isolated home. A hand-run from a normal terminal writes session data under the real `~/.psych-cert-gen` if the command is pointed at a path that stores sessions there. `certgen.py` itself writes certificates only to `--output-dir`.
