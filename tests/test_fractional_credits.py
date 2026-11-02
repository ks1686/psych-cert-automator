"""CE credits may be fractional in quarter-credit steps (e.g. 1.5)."""

from __future__ import annotations

import math
from datetime import date, time
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError
from src.backends.main import _SessionRequest
from src.backends.routes import GenerateRequest, PreviewRequest
from src.generator.templates import TemplateRenderContext, build_replacements
from src.models.credits import format_ce_credits, parse_ce_credits
from src.models.training import TrainingConfigError, TrainingMetadata

import certgen


@pytest.mark.parametrize(
    ("value", "shown"),
    [(1.5, "1.5"), (3, "3"), (3.0, "3"), (0.25, "0.25"), (2.75, "2.75"), ("1.50", "1.5")],
)
def test_credits_print_without_trailing_zero(value: float | str, shown: str) -> None:
    assert format_ce_credits(parse_ce_credits(value)) == shown


@pytest.mark.parametrize("bad", [0, -1, 1.3, 0.1, math.nan, math.inf, "abc", 1000])
def test_invalid_credits_are_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="CE credits"):
        parse_ce_credits(bad)


def _ctx(credits: float) -> TemplateRenderContext:
    return TemplateRenderContext(
        full_name="Ada Lovelace",
        training_title="Ethics",
        instructor_name="Dr. Grace Hopper",
        ce_credits=credits,
        license_number=None,
        date_display="November 2, 2026",
        time_display="9:00 AM - 12:00 PM",
        is_virtual=True,
        location=None,
    )


def test_templates_print_fractional_and_whole_credits() -> None:
    assert build_replacements("apa", _ctx(1.5))["CE CREDITS:"] == "CE CREDITS: 1.5"
    assert build_replacements("apa", _ctx(3.0))["CE CREDITS:"] == "CE CREDITS: 3"
    nasp = build_replacements("nasp", _ctx(1.5))
    assert nasp["X continuing education"] == "1.5 continuing education"


def test_training_metadata_accepts_fractional_credits() -> None:
    meta = TrainingMetadata.from_config(
        {
            "title": "Ethics",
            "date": "2026-11-02",
            "instructor_name": "Dr. Grace Hopper",
            "ce_credits": 1.5,
            "ce_types_offered": ["APA"],
            "session_start": "09:00",
            "session_end": "12:00",
        },
    )
    assert meta.ce_credits == 1.5


def test_training_metadata_rejects_off_step_credits() -> None:
    with pytest.raises(TrainingConfigError):
        TrainingMetadata.from_config(
            {
                "title": "Ethics",
                "date": "2026-11-02",
                "instructor_name": "Dr. Grace Hopper",
                "ce_credits": 1.3,
                "ce_types_offered": ["APA"],
                "session_start": "09:00",
                "session_end": "12:00",
            },
        )


def _generate_body(credits: object) -> dict[str, object]:
    return {
        "zoom_path": "z.xlsx",
        "qualtrics_path": "q.xlsx",
        "title": "Ethics",
        "training_date": date(2026, 11, 2),
        "instructor": "Dr. Grace Hopper",
        "ce_credits": credits,
        "ce_types": ["APA"],
        "start_time": time(9),
        "end_time": time(12),
    }


def test_api_models_accept_quarter_steps_and_reject_others() -> None:
    assert GenerateRequest.model_validate(_generate_body(1.5)).ce_credits == 1.5
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(_generate_body(1.3))
    with pytest.raises(ValidationError):
        PreviewRequest.model_validate(
            {
                "full_name": "Ada Lovelace",
                "ce_type": "APA",
                "ce_credits": 0,
                "training_title": "Ethics",
                "training_date": "2026-11-02",
                "instructor_name": "Dr. Grace Hopper",
            },
        )
    session = _SessionRequest.model_validate(
        {
            "title": "Ethics",
            "date": "2026-11-02",
            "instructor": "Dr. Grace Hopper",
            "ce_credits": 1.5,
            "ce_types": "APA",
            "start_time": "09:00",
            "end_time": "12:00",
        },
    )
    assert session.ce_credits == 1.5


def test_cli_rejects_off_step_credits(tmp_path: Path) -> None:
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"")
    result = CliRunner().invoke(
        certgen.main,
        [
            "--title", "Ethics",
            "--date", "2026-11-02",
            "--instructor", "Dr. Grace Hopper",
            "--ce-credits", "1.3",
            "--ce-types", "APA",
            "--start-time", "09:00",
            "--end-time", "12:00",
            "--zoom-report", str(report),
            "--qualtrics-report", str(report),
        ],
    )
    assert result.exit_code != 0
    assert "CE credits" in result.output
