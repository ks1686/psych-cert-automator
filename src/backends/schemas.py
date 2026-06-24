"""FastAPI request/response schemas — wire format for all API endpoints.

These Pydantic v2 models define the JSON shapes that cross the HTTP boundary.
They are separate from the internal frozen dataclass models in ``src/models/``.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Intermediate / component schemas ──────────────────────────────────────────


class ParticipantSummary(BaseModel):
    """Wire summary of one Zoom participant's aggregated attendance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str = Field(
        ..., description="Original name as reported by Zoom"
    )
    first_join: str = Field(
        ...,
        description="ISO 8601 datetime of earliest join (e.g., '2026-03-20T08:47:00')",
    )
    last_leave: str = Field(
        ...,
        description="ISO 8601 datetime of latest leave (e.g., '2026-03-20T12:11:00')",
    )
    total_attended_minutes: int = Field(
        ..., description="Sum of Zoom-reported segment durations in minutes"
    )
    segments_count: int = Field(
        ..., description="Number of non-waiting-room attendance segments"
    )


class CERequestSummary(BaseModel):
    """Wire summary of one Qualtrics CE credit request."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name_on_certificate: str = Field(
        ..., description="Name as the person typed it (e.g., 'Jessica Benas')"
    )
    email: str | None = Field(None, description="Preferred email address")
    ce_type: str = Field(
        ..., description="CE type short code requested (e.g., 'APA', 'NASP', 'BCBA')"
    )
    license_number: str | None = Field(
        None,
        description="License or certificate number, required by some CE types",
    )


class AttendanceWire(BaseModel):
    """Wire representation of attendance validation outcome for one participant.

    All float fields are rounded to one decimal place. ``total_attended`` is an
    integer (sum of segment durations from Zoom's own reporting).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    is_eligible: bool = Field(
        ..., description="Whether the participant qualifies for CE credit"
    )
    late_join: float = Field(
        ...,
        description="Minutes between session start and first join (0.0 if on time)",
    )
    early_leave: float = Field(
        ...,
        description="Minutes between last leave and session end (0.0 if stayed to end)",
    )
    gaps: float = Field(
        ...,
        description="Sum of mid-session gap minutes between consecutive leave/join pairs",
    )
    total_missed: float = Field(
        ...,
        description="Sum of late_join + early_leave + gaps (rounded to 1 decimal)",
    )
    total_attended: int = Field(
        ..., description="Sum of Zoom-reported segment durations in minutes"
    )
    failure_reason: str | None = Field(
        None,
        description="Human-readable explanation of which rule(s) failed, or None if eligible",
    )


# ── Match entry (discriminated union) ────────────────────────────────────────


class MatchEntryWire(BaseModel):
    """Wire representation of a name-matching outcome for one Qualtrics name.

    Uses a ``kind`` discriminator field to tag which variant is represented:

    - ``"success"``: one unambiguous Zoom match (``zoom_name``, ``confidence``,
      ``attendance`` populated)
    - ``"ambiguous"``: multiple candidate Zoom names (``candidates`` populated)
    - ``"not_found"``: no Zoom record matched (all optional fields are ``None``)
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    kind: Literal["success", "ambiguous", "not_found"] = Field(
        ..., description="Discriminator: 'success', 'ambiguous', or 'not_found'"
    )
    qualtrics_name: str = Field(
        ..., description="Name as it appeared in the Qualtrics export"
    )
    zoom_name: str | None = Field(
        None, description="Matched Zoom name (only for kind='success')"
    )
    confidence: Annotated[
        float | None,
        Field(
            ge=0.0,
            le=1.0,
            description="Confidence score between 0.0 and 1.0 (only for kind='success')",
        ),
    ] = None
    candidates: list[str] | None = Field(
        None, description="All candidate Zoom names (only for kind='ambiguous')"
    )
    attendance: AttendanceWire | None = Field(
        None,
        description="Attendance validation outcome (only for kind='success' when eligible)",
    )


# ── Session metadata ─────────────────────────────────────────────────────────


class SessionListItem(BaseModel):
    """Metadata for one saved session listed in the session index."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str = Field(..., description="Human-readable session name")
    saved_at: str = Field(
        ..., description="ISO 8601 datetime when the session was saved"
    )
    path: str = Field(..., description="Filesystem path to the saved session file")


# ── Request schemas ──────────────────────────────────────────────────────────


class ParseRequest(BaseModel):
    """Request to parse Zoom attendance and Qualtrics CE request files."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    zoom_path: str = Field(..., description="Path to Zoom attendance .xlsx file")
    qualtrics_path: str = Field(
        ..., description="Path to Qualtrics export .xlsx file"
    )


class MatchRequest(BaseModel):
    """Request to match Qualtrics CE requests against Zoom participants."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    zoom_participants: list[ParticipantSummary] = Field(
        ..., description="Parsed Zoom participant attendance summaries"
    )
    ce_requests: list[CERequestSummary] = Field(
        ..., description="Parsed Qualtrics CE credit requests"
    )
    overrides: dict[str, str] | None = Field(
        None,
        description="Manual name overrides mapping qualtrics_name to zoom_name",
    )


class PreviewRequest(BaseModel):
    """Request to preview a single certificate PDF before batch generation.

    Mirrors the fields of the internal ``CertificateOutput`` model.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    full_name: str = Field(
        ..., description="Name as it appears on the certificate"
    )
    ce_type: str = Field(
        ..., description="CE type short code (e.g., 'APA')"
    )
    ce_credits: int = Field(
        ..., description="Number of CE credits awarded"
    )
    training_title: str = Field(
        ..., description="Title of the training session"
    )
    training_date: str = Field(
        ...,
        description="ISO 8601 date the training occurred (e.g., '2026-03-20')",
    )
    instructor_name: str = Field(
        ..., description="Name of the instructor"
    )
    license_number: str | None = Field(
        None,
        description="License or certificate number printed on the certificate (if applicable)",
    )
    issue_date: str = Field(
        ...,
        description="ISO 8601 date the certificate was generated (e.g., '2026-03-20')",
    )


class GenerateRequest(BaseModel):
    """Request to batch-generate CE certificates for all eligible matches."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    matches: list[MatchEntryWire] = Field(
        ..., description="All match entries (eligible, ineligible, ambiguous)"
    )
    output_dir: str = Field(
        ..., description="Directory path where generated PDFs will be written"
    )
    title: str = Field(..., description="Title of the training session")
    training_date: str = Field(
        ...,
        description="ISO 8601 date the training occurred (e.g., '2026-03-20')",
    )
    instructor: str = Field(..., description="Name of the instructor")
    ce_credits: int = Field(
        ..., description="Number of CE credits awarded per certificate"
    )
    ce_types: list[str] = Field(
        ...,
        description="Short codes for CE types offered (e.g., ['APA', 'NASP', 'BCBA'])",
    )


class ZipRequest(BaseModel):
    """Request to bundle generated PDFs into a ZIP archive."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    pdf_paths: list[str] = Field(
        ..., description="Absolute or relative paths to PDF files to include in the ZIP"
    )


# ── Response schemas ─────────────────────────────────────────────────────────


class ParseResponse(BaseModel):
    """Response from the parse endpoint — extracted participant and CE request data."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    zoom_participants: list[ParticipantSummary] = Field(
        ..., description="Parsed Zoom participant attendance summaries"
    )
    ce_requests: list[CERequestSummary] = Field(
        ..., description="Parsed Qualtrics CE credit requests"
    )
    session_start: str = Field(
        ...,
        description="Earliest Zoom join time across all participants (ISO 8601)",
    )
    session_end: str = Field(
        ...,
        description="Latest Zoom leave time across all participants (ISO 8601)",
    )
    total_requests: int = Field(
        ..., description="Total number of CE credit requests found"
    )


class MatchResponse(BaseModel):
    """Response from the match endpoint — name-matching results."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    matches: list[MatchEntryWire] = Field(
        ..., description="Name-matching outcome for every Qualtrics CE request"
    )


class GenerateResponse(BaseModel):
    """Response from the generate endpoint — certificate generation summary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    eligible_count: int = Field(
        ..., description="Number of certificates successfully generated"
    )
    ineligible_count: int = Field(
        ..., description="Number of requests that could not be fulfilled"
    )
    pdf_paths: list[str] = Field(
        ..., description="Absolute paths to all generated PDF certificate files"
    )
    report_path: str | None = Field(
        None,
        description="Path to the ineligibility spreadsheet, or None if no ineligible entries",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors encountered during generation (e.g., file write failures)",
    )
