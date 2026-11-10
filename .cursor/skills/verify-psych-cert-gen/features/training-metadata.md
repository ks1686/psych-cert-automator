# Training metadata

The first wizard step collects the session a certificate will name: title, date, instructor, credit hours, which CE types are offered, and the start and end times. Virtual delivery is the default, so the location field stays hidden until the user turns virtual off.

## Sub-features

- `metadata-required` keeps Next disabled until title, date, instructor, credits, one CE type, and both times are set.
- `metadata-virtual` leaves the event virtual, with no location field.
- `metadata-types` records APA, NASP, NY, and NBCC when each box is checked.

## How to get to it (user POV)

- Open the app. The first card heading is `Training Metadata`.
- The startup screen must finish first. It shows a ready message for about 1.5 seconds after the backend answers, then the form appears.

## Driving it with verify-psych-cert-gen

Preconditions:

- `verify-psych-cert-gen launch` printed a run id.
- The heading `Training Metadata` is visible.
- `verify-psych-cert-gen doctor --id RUN_ID` prints `version=` and `ui=http://127.0.0.1:1420/`.

Packaged check: `verify-psych-cert-gen drive --id RUN_ID training-metadata`. It fills the pilot session and requires Next to be enabled. The steps below are that drive.

- **Open the form.** Launch already opened `/`. Run `verify-psych-cert-gen browser --id RUN_ID -- expect-url /` and `verify-psych-cert-gen browser --id RUN_ID -- wait-heading "Training Metadata"`. The path is `/` and the heading is `Training Metadata`.
- **Enter the session.** Run `verify-psych-cert-gen browser --id RUN_ID -- fill-label "Training Title" "Ethics and Practice in School-Based Mental Health"`, then the same `fill-label` op for `Date` = `2026-10-06`, `Instructor Name` = `Dr. Amira Solano`, `CE Credits` = `3`, `Start Time` = `09:00`, and `End Time` = `12:00`. Each control shows the value you typed.
- **Choose CE types.** Run `verify-psych-cert-gen browser --id RUN_ID -- check-role checkbox APA`. The APA box is checked. The packaged metadata drive checks APA. The generate drive also checks NASP, NY, and NBCC the same way.
- **Continue.** Run `verify-psych-cert-gen browser --id RUN_ID -- expect-enabled button Next`. The Next button is enabled.

## Gotchas

- Next stays disabled while a required field is empty. Credits use a number input; fill `3`, not `3.0`, unless you mean three point zero.
- Date is `YYYY-MM-DD`. Time is `HH:MM`.
- Virtual is already on. Unchecking `Virtual event` reveals `In-person location`, and Next stays disabled until that field has text. The generate proof leaves virtual on.
- The address must stay `http://127.0.0.1:1420/`. `http://localhost:1420/` is a different origin and fails the exact path check the helper uses for the host.
