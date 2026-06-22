# CE Certificate Generator — Project Plan

## Overview

A Python CLI tool that takes a Zoom attendance report, a Qualtrics CE request export, and Word template files as input, validates attendance, and outputs individual PDF certificates per person per CE type — plus a summary report of ineligible participants.

---

## Inputs

| # | Input | Format | Description |
|---|-------|--------|-------------|
| 1 | Training metadata | CLI args / config | Title, date, instructor name, CE credits offered, session start/end times |
| 2 | Zoom attendance report | `.xlsx` | Per-participant join/leave timestamps (see format below) |
| 3 | Qualtrics CE request export | `.xlsx` | Per-person CE type request(s) with name, email, license/cert numbers |
| 4 | Word certificate templates | `.docx` | One template per CE type, with placeholder fields for mail-merge style filling |

## Outputs

| # | Output | Format | Description |
|---|--------|--------|-------------|
| 1 | Individual certificates | `.pdf` | One PDF per person per approved CE type, named `{LastName}_{FirstName}_{CEType}.pdf` |
| 2 | Ineligibility summary | `.xlsx` or `.csv` | Names, reasons for exclusion, and requested CE types |

---

## Workflow (End-to-End)

```
┌──────────────┐    ┌──────────────┐    ┌─────────────────┐
│ Training     │    │ Zoom         │    │ Qualtrics       │
│ Metadata     │    │ Attendance   │    │ CE Requests     │
│ (CLI/config) │    │ (.xlsx)      │    │ (.xlsx)         │
└──────┬───────┘    └──────┬───────┘    └──────┬──────────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
                  ┌─────────────────┐
                  │ 1. Parse &      │
                  │    Normalize    │
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │ 2. Match names  │
                  │    across files │
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │ 3. Validate     │
                  │    attendance   │
                  └────────┬────────┘
                      ┌────┴────┐
                      ▼         ▼
              ┌──────────┐ ┌──────────┐
              │ ELIGIBLE │ │INELIGIBLE│
              └─────┬────┘ └────┬─────┘
                    ▼            ▼
           ┌──────────────┐ ┌──────────────┐
           │ 4. Generate  │ │ 5. Summary   │
           │    PDFs      │ │    Report    │
           │ (docx→pdf)   │ │  (.xlsx/csv) │
           └──────────────┘ └──────────────┘
```

---

## Step 1: Parse & Normalize

### 1a. Training Metadata

Collected via CLI arguments or a JSON/YAML config file:

```
python certgen.py \
  --title "Providing Culturally-Responsive and Ethical Treatment..." \
  --date "2026-03-20" \
  --instructor "Dr. Jane Smith" \
  --ce-credits 3 \
  --ce-types "APA,NASP,BCBA" \
  --start-time "08:47" \
  --end-time "12:11" \
  --zoom-report "zoom_attendance.xlsx" \
  --qualtrics-report "qualtrics_export.xlsx" \
  --templates-dir "./templates/" \
  --output-dir "./output/"
```

Alternative: read session start/end times directly from the Zoom report (row 2, columns E/F).

### 1b. Zoom Attendance Parsing

**Format observed** (from sample):
- Rows 1–3: Meeting metadata (Topic, ID, Host, Duration, Start/End time, Participant count)
- Row 4: Participant column headers
- Rows 5+: One row per join/leave segment per participant

**Columns:**
| Col | Header | Type | Notes |
|-----|--------|------|-------|
| A | Name (original name) | string | May include parenthetical display names, pronouns, credentials, e.g. `"Jaimee Arnoff# Ph.D. (she/her) (Jaimee Arnoff)"` |
| B | Email | string | Often empty for Guest=Yes entries |
| C | Join time | datetime | Timezone-naive; assume local time |
| D | Leave time | datetime | Timezone-naive; assume local time |
| E | Duration (minutes) | int | Per-segment duration |
| F | Guest | Yes/No | |
| G | In waiting room | Yes/No | **Must be excluded** from attendance calculation |

**Normalization needed:**
1. **Filter out "In waiting room = Yes" rows** — these do not count as attendance.
2. **Name normalization** — strip parentheticals, pronouns, credentials, trailing spaces, lowercase for matching. Strategy:
   - Extract the "base name" — the part before any `(` or `#` in the original name
   - Handle entries like `"Sheryl"` that are first-name-only (match to `"Sheryl Aaron (she/her/hers)"` via partial matching)
   - Normalize prefixes: Dr., Ph.D., etc. may or may not appear
   - **Decision needed:** Fuzzy matching threshold or exact-after-normalization?

### 1c. Qualtrics CE Requests Parsing

**Format observed** (from sample):
- Row 1: Column headers (standard Qualtrics metadata + custom questions)
- Row 2+: One row per survey response

**Key columns identified:**
| Col | Header snippet | Content |
|-----|---------------|---------|
| R | `Name (as you would like it to appear on your CE certificate)` | e.g. `"Jessica Benas"` |
| S | `Preferred email address` | e.g. `"jbenas@gsapp.rutgers.edu"` |
| T | `Type of CE credit needed: ... - Selected Choice` | e.g. `"Psychologist (APA)"` |
| U | `... Psychologist (New York) ... - Text` | License number (if applicable) |
| V | `... BCBA ... - Text` | Certificate number (if applicable) |

**⚠️ Open design question — Multi-CE support:**
The user stated one person can request multiple CE types, and each gets a separate PDF. The current sample Qualtrics format shows a single-select CE question (column T). Options:
- **(A)** The revamped survey allows multi-select (checkbox question), and Qualtrics exports it as comma-separated or multiple columns per choice.
- **(B)** A person fills out the survey multiple times (one response per CE type). We'd group by name/email and aggregate CE types across rows.
- **(C)** Configure the tool to accept either format, auto-detecting the structure.

**Decision:** Support both modes — detect whether CE type column contains single values or delimited lists, and whether multiple rows exist for the same person. Emit a warning if ambiguous.

**License/Cert number extraction:** Each CE type may have an associated text field for a license or certificate number. The tool should:
1. Accept a mapping config: `{ "APA": "license_col", "BCBA": "cert_col", ... }`
2. Or auto-detect by scanning column headers for CE type names

---

## Step 2: Name Matching (Zoom ↔ Qualtrics)

### Problem

Names in Zoom and Qualtrics will not match exactly:
- Zoom: `"Dr. Patricia A. Farrell"`, `"Emmett Lincoln (Emmett)"`, `"Sheryl"`
- Qualtrics: The person typed their own name as they want it on the certificate (e.g., `"Patricia Farrell"`, `"Emmett Lincoln"`, `"Sheryl Aaron"`)

### Strategy

1. **Normalize both sides:**
   - Lowercase
   - Strip parenthetical content: remove `(...)` including nested
   - Strip titles/credentials: Dr., Ph.D., Psy.D., etc.
   - Strip punctuation: `#`, `.`, `,`
   - Collapse whitespace
   - Extract first name + last name tokens

2. **Matching pipeline (try each, stop on first unambiguous match):**
   a. **Exact normalized match** — normalized strings are identical
   b. **Token-set match** — first name + last name tokens as sets; require all tokens from one side present in the other (handles middle initials, name order)
   c. **First-name partial match** — for Zoom entries with only a first name (e.g., `"Emmett"`, `"Sheryl"`), look for Qualtrics entries whose first name matches
   d. **Manual override file** — accept a CSV of `zoom_name,qualtrics_name` for edge cases

3. **Unmatched handling:**
   - Zoom attendees with no Qualtrics request → skip (they didn't request CE)
   - Qualtrics requesters not in Zoom → include in ineligibility report as "Not found in attendance"

### Ambiguity resolution

- If one Zoom name matches multiple Qualtrics names → flag for manual resolution
- If multiple Zoom names match one Qualtrics name → flag for manual resolution
- Unresolved ambiguities go into the ineligibility report with reason

---

## Step 3: Attendance Validation

### Rules (from stakeholder)

1. **Late join:** First join time must be ≤ 15 minutes after session start
2. **Early leave:** Last leave time must be ≥ 15 minutes before session end
3. **Total absence:** Cumulative missed time must be ≤ 15 minutes

Missed time = total gaps between leave/join for consecutive segments + time before first join + time after last leave.

### Algorithm

```
For each participant, across all non-waiting-room segments sorted by join time:

  first_join  = min(join_times)
  last_leave  = max(leave_times)
  
  late_minutes     = max(0, first_join - session_start)     # in minutes
  early_minutes    = max(0, session_end - last_leave)       # in minutes
  
  attended_minutes = sum(duration for each segment)
  gap_minutes      = total_session_duration - attended_minutes
  # (This accounts for all time outside the meeting,
  #  including late start, early leave, and mid-session gaps)
  
  eligible = (late_minutes <= 15) AND (early_minutes <= 15) AND (gap_minutes <= 15)
```

**Note on gap calculation:** `gap_minutes` as defined above naturally includes late join and early leave time, so a separate `gap_minutes <= 15` check may be redundant with the first two. The intent is: **no more than 15 minutes of cumulative absence of any kind.** Using `attended_minutes >= total_session_duration - 15` captures this as a single clean check. Confirm with stakeholder during review.

### Special cases

| Case | Handling |
|------|----------|
| Multiple Zoom accounts (same person, different devices) | Merge by normalized name before validation |
| Participant in waiting room for 30 min before admit | Waiting room rows already excluded; late-join check uses first non-waiting-room join |
| Host/co-host | Typically excluded from CE requests; configurable skip list |
| Duration < 1 min segments (reconnects) | Include; they're part of attendance |

---

## Step 4: PDF Certificate Generation

### Template Model

One `.docx` file per CE type. Templates use placeholder syntax:

```
{full_name}
{cert_title}
{ce_type}
{ce_credits}
{training_title}
{training_date}
{instructor_name}
{license_number}   # optional, per CE type
{issue_date}
```

**Template mapping config** (JSON):
```json
{
  "APA": {
    "template": "templates/apa_certificate.docx",
    "fields": ["full_name", "ce_credits", "training_title", "training_date", "instructor_name", "issue_date"]
  },
  "NASP": {
    "template": "templates/nasp_certificate.docx",
    "fields": ["full_name", "ce_credits", "training_title", "training_date", "instructor_name", "license_number", "issue_date"]
  }
}
```

### Generation pipeline

```
For each eligible person:
  For each CE type they requested:
    1. Load the corresponding .docx template
    2. Perform placeholder substitution (python-docx)
    3. Convert .docx → .pdf (LibreOffice headless or python-docx2pdf)
    4. Save to output directory
```

### File naming

`{LastName}_{FirstName}_{CEType}_{TrainingDate}.pdf`

Example: `Benas_Jessica_APA_2026-03-20.pdf`

---

## Step 5: Ineligibility Summary Report

### Output

One `.xlsx` file with columns:

| Name (Qualtrics) | Name (Zoom) | Match Status | Late Join (min) | Early Leave (min) | Gaps (min) | Rejected CE Types | Reason |
|------------------|-------------|--------------|-----------------|-------------------|------------|-------------------|--------|

### Inclusion criteria

A person appears in the report if:
- They are in Qualtrics but not found in Zoom attendance → Reason: "Not found in attendance"
- They are matched but fail attendance validation → Reason: specific failure
- Name matching was ambiguous → Reason: "Ambiguous name match — manual review required"

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.12+ | Requested by user; strong Excel/PDF/docx ecosystem |
| Excel parsing | `openpyxl` | Native `.xlsx` support, no Excel dependency |
| Word template manipulation | `python-docx` | De facto standard for .docx in Python |
| DOCX → PDF conversion | LibreOffice headless (`soffice --headless --convert-to pdf`) | Reliable, free, maintains formatting. Fallback: `docx2pdf` (which wraps Word on Windows/Mac) |
| PDF generation (alternative) | `reportlab` or `fpdf2` | If templates can't be preserved through docx→pdf, build PDFs programmatically from a layout spec |
| CLI framework | `argparse` (stdlib) or `click` | Keep dependencies minimal; `click` if complex subcommands emerge |
| Name matching | Custom normalization + token-set | No heavy NLP dependency; good enough for this domain |
| Config | JSON or YAML | Template mappings, CE type field mappings, override lists |

---

## Project Structure

```
psych-cert-gen/
├── certgen.py              # CLI entry point
├── config.yaml             # Default config (template mappings, CE field mappings)
├── templates/              # Word .docx templates (one per CE type)
│   ├── apa_certificate.docx
│   ├── nasp_certificate.docx
│   └── bcba_certificate.docx
├── input/                  # Place input files here (gitignored)
├── output/                 # Generated PDFs and reports (gitignored)
├── src/
│   ├── __init__.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── zoom.py         # Zoom attendance parsing & normalization
│   │   └── qualtrics.py    # Qualtrics export parsing & normalization
│   ├── matcher/
│   │   ├── __init__.py
│   │   └── name_matcher.py # Name normalization + matching logic
│   ├── validator/
│   │   ├── __init__.py
│   │   └── attendance.py   # Attendance validation rules
│   ├── generator/
│   │   ├── __init__.py
│   │   ├── certificate.py  # .docx → .pdf generation
│   │   └── report.py       # Ineligibility summary report
│   └── models/
│       ├── __init__.py
│       ├── training.py     # Training metadata model
│       ├── participant.py  # Participant & attendance data model
│       └── certificate.py  # CE request & certificate model
├── tests/
│   ├── test_zoom_parser.py
│   ├── test_qualtrics_parser.py
│   ├── test_name_matcher.py
│   ├── test_attendance_validator.py
│   └── fixtures/
│       ├── sample_zoom.xlsx
│       └── sample_qualtrics.xlsx
├── pyproject.toml
└── PLAN.md                  # This file
```

---

## Dependency List

```toml
[project]
dependencies = [
    "openpyxl>=3.1",       # Excel read/write
    "python-docx>=1.1",    # Word document manipulation
    "click>=8.1",          # CLI framework
    "pyyaml>=6.0",         # YAML config parsing
    "pydantic>=2.0",       # Data validation / models
]
```

---

## Open Items & Questions for Stakeholder

### Blocking (must resolve before implementation)

1. **Word templates needed.** Request `.docx` files for each CE type. Identify all placeholder fields (name, date, title, instructor, license #, etc.) per template.

2. **Qualtrics revamp — CE multi-select format.** Once the new survey is deployed, provide a sample export with at least one multi-CE response so the parser can be built to the correct column structure.

3. **Attendance criteria clarification.** Confirm the exact rule:
   - (A) "No single gap exceeds 15 minutes" vs. (B) "Total missed time ≤ 15 minutes"
   - From conversation: seems to be (B) — cumulative absence ≤ 15 minutes. The late-join and early-leave checks are special cases of this. Confirm.

### Advisory (nice to resolve)

4. **License/certificate numbers on certificates?** Some templates may require printing the attendee's license number. Confirm which CE types need this.

5. **Issue date vs. training date.** Confirm: is the issue date the date of generation, or a fixed date?

6. **Name matching ambiguity policy.** How should ambiguous matches be handled? Manual review list in the summary report, or a prompt for user input during processing?

7. **Host/presenter exclusion.** Should the host/presenter (identifiable in Zoom as "Host") be automatically excluded from certificate generation?

8. **Output delivery format.** Individual PDFs per person-CE pair as planned, or should they be grouped/zipped?

---

## Implementation Phases

| Phase | Scope | Deliverable |
|-------|-------|-------------|
| **0 — Research** | Resolve open items with stakeholder; obtain templates and final Qualtrics format | Confirmed requirements doc |
| **1 — Core Models** | Pydantic models for all data structures; config schema | `src/models/` complete |
| **2 — Parsers** | Zoom parser, Qualtrics parser with auto-detect | Parse both sample files correctly |
| **3 — Name Matcher** | Normalization + multi-strategy matching | Match Zoom↔Qualtrics for sample data |
| **4 — Validator** | Attendance validation logic | Correct eligibility determination for sample |
| **5 — Generator** | Template substitution + docx→pdf pipeline | Generate PDF for the sample eligible person |
| **6 — Report** | Ineligibility summary Excel output | Report for sample data |
| **7 — Integration** | CLI wiring, end-to-end run on sample data | Full pipeline functional |
| **8 — Testing** | Unit tests with sample fixtures; edge case handling | Test suite passing |
| **9 — Documentation** | README with usage instructions for department staff | User-facing docs |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Qualtrics format changes frequently | Parser breaks | Auto-detect column mapping by header keywords; configurable override |
| Name matching failures on edge cases | Wrong people get/are denied certificates | Manual override file; summary report flags ambiguous matches for human review |
| docx→pdf fidelity loss in LibreOffice | Ugly certificates | Test early with real templates; fall back to programmatic PDF generation if needed |
| Zoom timezone handling | Incorrect attendance calculations | Assume local time unless Zoom provides timezone offset; document assumption |
| Multiple CE types per person managed incorrectly | Missing certificates | Comprehensive test cases for multi-CE scenarios |
