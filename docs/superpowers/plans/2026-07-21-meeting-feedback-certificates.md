# Meeting Feedback Certificates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Word-template certificate generation plus meeting-feedback UI/API (CE types, multi-day, virtual/in-person, host/straggler exclude, filename, regenerate-after-delete).

**Architecture:** Keep parse→match→validate; replace fpdf generation with `python-docx` fill of `templates/{apa,ny,nasp,attendance}.docx` and soft-fail PDF conversion. Extend metadata + match review + pipeline with delivery/span/exclusions without modifying `src/parser/`, `src/matcher/`, or `src/validator/`.

**Tech Stack:** Python 3.12, python-docx, existing FastAPI/React/Tauri stack, optional LibreOffice/Word for PDF.

## Global Constraints

- Do not modify `src/parser/`, `src/matcher/`, `src/validator/`
- No `as any` / `@ts-ignore` / `# type: ignore` / bare `except:`
- Existing Python tests must keep passing (update certificate/filename tests as needed)
- Use Bun for frontend, uv for Python
- Templates live under `templates/`

## File map

| File | Responsibility |
|------|----------------|
| `templates/*.docx` | Official CE templates |
| `src/generator/templates.py` | CE→template path, placeholder values, docx fill |
| `src/generator/convert.py` | Best-effort docx→PDF |
| `src/generator/certificate.py` | Orchestrate fill + convert + write |
| `src/generator/zoom_host.py` | Read Zoom host from C2 without touching zoom parser |
| `src/models/certificate.py` | Filename + extended CertificateOutput fields |
| `src/pipeline.py` | excluded_names, delivery/span fields, template CE mapping |
| `src/backends/routes.py` | API fields, regenerate tokens, host on parse |
| `ui/src/components/StepMetadata.tsx` | CE types + toggles |
| `ui/src/components/StepMatchReview.tsx` | Exclude + host pre-check |
| `ui/src/components/StepGenerate.tsx` | Pass new fields; allow re-generate |
| `ui/src/App.tsx` | Wire metadata → generate |

---

### Task 1: Template mapping + docx fill + PDF soft-fail

**Files:**
- Create: `src/generator/templates.py`
- Create: `src/generator/convert.py`
- Modify: `src/generator/certificate.py`
- Modify: `src/models/certificate.py`
- Modify: `pyproject.toml` (add `python-docx`)
- Test: `tests/test_certificate_templates.py`

**Interfaces:**
- Produces: `resolve_template_key(ce_type: str) -> Literal["apa","ny","nasp","attendance"]`
- Produces: `generate_certificate(output, output_dir, *, delivery, location, date_display, session_time_display) -> str` (path to pdf or docx)
- Produces: `output_filename` → `{Last}_CECertificate_{InstructorLast}_{Date}.pdf` (or `.docx` if no PDF)

- [ ] **Step 1: Add dependency and failing tests for mapping + filename**

```bash
cd /Users/ks1686/Documents/Repos/psych-cert-gen && uv add python-docx
```

```python
# tests/test_certificate_templates.py
from datetime import date
from src.generator.templates import resolve_template_key
from src.models.certificate import CertificateOutput
from src.models.training import CEType

def test_resolve_template_key_maps_known_types():
    assert resolve_template_key("Psychologist (APA)") == "apa"
    assert resolve_template_key("Psychologist (New York)") == "ny"
    assert resolve_template_key("NASP") == "nasp"
    assert resolve_template_key("BCBA") == "attendance"
    assert resolve_template_key("Something Else") == "attendance"

def test_output_filename_pattern():
    out = CertificateOutput(
        full_name="Jessica Benas",
        ce_type=CEType("APA"),
        ce_credits=3,
        training_title="T",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Jane Smith",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    assert out.output_filename.startswith("Benas_CECertificate_Smith_2026-03-20")
```

- [ ] **Step 2: Implement `resolve_template_key`, new filename, fill+convert, update `generate_certificate`**

Replace unsafe filename chars including `@`. Prefer PDF path in registry when conversion succeeds; otherwise `.docx`.

Virtual defaults: Location=`Virtual Event`, Format=`Live Webinar`, NASP phrase=`via Live Zoom Webinar`.  
In-person: Location=user text (default `Rutgers University in Piscataway, NJ`), Format=`In-Person`, NASP phrase=`at {location}`.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_certificate_templates.py tests/test_certificate_security.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock templates src/generator src/models/certificate.py tests/test_certificate_templates.py
git commit -m "feat: fill Word CE templates with soft-fail PDF conversion"
```

---

### Task 2: Pipeline exclusions + delivery metadata

**Files:**
- Create: `src/generator/zoom_host.py`
- Modify: `src/pipeline.py`
- Modify: `src/backends/routes.py` (`ParseResponse` host, `GenerateRequest` fields)
- Test: `tests/test_zoom_host.py`, extend backend contract tests if present

**Interfaces:**
- Produces: `extract_zoom_host(filepath: str) -> str | None`
- Extends: `run_pipeline(..., excluded_names: set[str] | None = None, is_virtual: bool = True, location: str | None = None, end_date: date | None = None)`

- [ ] **Step 1: Failing test for host extraction from sample Zoom file**

```python
def test_extract_zoom_host_from_sample():
    host = extract_zoom_host("input/Zoom Attendance Report Arnoff 3.20.26.xlsx")
    assert host is not None
    assert "Jessica Benas" in host
```

- [ ] **Step 2: Implement host reader (C2), pipeline skip for excluded Qualtrics names, date range display**

- [ ] **Step 3: Wire API generate/parse request/response fields**

- [ ] **Step 4: pytest + commit**

---

### Task 3: UI metadata + match exclude + regenerate

**Files:**
- Modify: `ui/src/components/StepMetadata.tsx`
- Modify: `ui/src/components/StepMatchReview.tsx`
- Modify: `ui/src/components/StepGenerate.tsx`
- Modify: `ui/src/App.tsx`
- Modify: related types

- [ ] **Step 1: Metadata — replace BCBA with NY; add single/multi-day + virtual/in-person + location**

- [ ] **Step 2: Match review — `excludedNames: Set/Record`; pre-check Zoom host; Exclude checkbox per row; pass to Next**

- [ ] **Step 3: Generate — send new fields; keep Generate button after complete; clear results and allow re-run; accept docx tokens if PDF missing**

- [ ] **Step 4: `bun run build` typecheck + commit**

---

### Task 4: Preview + ZIP + cleanup

**Files:**
- Modify: `src/backends/routes.py` preview to use template fill when possible
- Modify: download-zip to include generated docx/pdf
- Update: `AGENTS.md` tech stack line (docx templates, not fpdf-only)
- Verify: `uv run pytest` full suite

- [ ] **Step 1: Preview returns filled PDF or docx bytes**
- [ ] **Step 2: Full pytest + frontend build**
- [ ] **Step 3: Final commit**
