# CE Certificate Automator

**Turns your Zoom attendance and Qualtrics survey into individual CE certificates — automatically.**

Built for the GSAPP Psychology Department at Rutgers.

---

## What it does

You run one command. It:

1. Reads your Zoom attendance report (who showed up, when they joined/left)
2. Reads your Qualtrics CE request survey (who wants which CE credits)
3. Matches people across both files by name
4. Checks that each person attended the full session (no more than 15 minutes missed)
5. Generates a professional PDF certificate for each eligible person, per CE type
6. Produces a summary spreadsheet of anyone who was skipped and why

**What used to take hours of manual work now takes seconds.**

---

## What you need

| File | Where it comes from |
|------|-------------------|
| Zoom attendance report | Zoom → Reports → Usage → Meeting → Export as Excel |
| Qualtrics CE survey export | Qualtrics → Data & Analysis → Export → Excel |
| Training details | Title, date, instructor, CE types offered, session start/end time |

---

## Example output

### Certificate (PDF)
A landscape certificate with the recipient's name, CE type and credits, training title, date, instructor, and signature block.

Filename: `Benas_Jessica_APA_2026-03-20.pdf`

### Ineligibility Report (Excel)
A spreadsheet listing anyone who didn't get a certificate and why:
- Name not found in Zoom attendance
- Name matched multiple Zoom attendees (ambiguous)
- Didn't meet attendance requirements (late join, early leave, or excessive gaps)

---

## Getting started

### One-time setup (ask IT or a tech-savvy colleague)

1. Install Python 3.12+: https://www.python.org/downloads/
2. Open Terminal and run:
   ```
   pip install uv
   git clone https://github.com/ks1686/psych-cert-automator.git
   cd psych-cert-automator
   uv sync
   ```

### Every time you need certificates

```
uv run python certgen.py \
  --title "Training Title Here" \
  --date "2026-03-20" \
  --instructor "Dr. Jane Smith" \
  --ce-credits 3 \
  --ce-types "APA,NASP,BCBA" \
  --start-time "08:47" \
  --end-time "12:11" \
  --zoom-report "path/to/zoom_attendance.xlsx" \
  --qualtrics-report "path/to/qualtrics_export.xlsx" \
  --output-dir "./output"
```

Replace the values with your training's details. Certificates appear in the `output` folder.

---

## Questions?

For technical questions about how this works, see [PLAN.md](PLAN.md).
For department-specific questions (CE requirements, templates, etc.), ask your program coordinator.
