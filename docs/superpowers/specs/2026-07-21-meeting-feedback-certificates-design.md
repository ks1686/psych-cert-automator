# Meeting Feedback Certificates — Design

**Date:** 2026-07-21  
**Status:** Approved for implementation

## Problem

1. Second generate after deleting outputs does not reliably recreate certificates (UI locks Generate; download tokens go stale).
2. Meeting feedback requires official Word templates, CE-type changes, delivery/span metadata, Zoom-host exclusion, and straggler exclude in Review Matches.

## Decisions

| Topic | Decision |
|-------|----------|
| Generation | Fill official `.docx` templates; convert to PDF when Word/LibreOffice available; otherwise write `.docx` + warn |
| CE types | NY, APA, NASP; remove BCBA; Certificate of Attendance when Qualtrics type has no template |
| NASP template | Combined `NASP Certificate TEMPLATE.docx` (virtual + in-person wording) |
| Multi-day | Toggle; certificate date field is a start–end range |
| Delivery | Separate Virtual / In-person toggle; in-person shows Location text field; virtual uses template virtual strings |
| Host | Auto-detect from Zoom `C2` host cell; pre-exclude in Review Matches with override |
| Stragglers | Per-row Exclude checkbox; excluded names skipped at generate |
| Filename | `{LastName}_CECertificate_{InstructorLastName}_{Date}` (+ extension); sanitize `@` and unsafe chars |
| Output dir | Keep `./output` / Downloads-style simplicity |
| Parsers | Do not modify `src/parser/`, `src/matcher/`, `src/validator/`; host read lives in a new helper |

## Architecture

```
Metadata (span + delivery + CE types)
  → Upload / Parse (return zoom_host)
  → Match Review (exclude set, host pre-checked)
  → Generate (run_pipeline + excluded_names + delivery fields)
       → map CE type → template
       → fill docx placeholders
       → convert to PDF (soft-fail → keep docx)
```

### Template mapping

| Qualtrics CE signal | Template |
|---------------------|----------|
| APA / Psychologist (APA) | `templates/apa.docx` |
| NY / New York | `templates/ny.docx` |
| NASP | `templates/nasp.docx` |
| Anything else (incl. former BCBA) | `templates/attendance.docx` |

### Placeholder fill

Replace literal template tokens (NAME, TITLE, dates, location/format, license, instructor, times, credits) via `python-docx` text substitution that preserves runs where possible.

### Regeneration

- Keep Generate available after complete (or add “Generate again”).
- Always overwrite output files; never skip-if-exists.
- Re-register PDF/docx tokens on each successful generate; clear stale tokens for that run’s prior set when practical.

## Out of scope

- Custom output-path picker
- Per-day time schedules for multi-day
- Perfect pixel parity if LibreOffice/Word conversion differs slightly
- Editing protected parser/matcher/validator modules
