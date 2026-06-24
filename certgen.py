"""certgen.py — CLI entry point wrapping the pipeline from ``src.pipeline``."""

from __future__ import annotations

import sys
from datetime import date, time

import click
from src.pipeline import PipelineResult, run_pipeline


@click.command()
@click.option("--title", required=True, help="Training title")
@click.option("--date", "training_date_str", required=True, help="Training date (YYYY-MM-DD)")
@click.option("--instructor", required=True, help="Instructor name")
@click.option("--ce-credits", type=int, required=True, help="Number of CE credits")
@click.option(
    "--ce-types",
    required=True,
    help="Comma-separated CE types offered (e.g. APA,NASP,BCBA)",
)
@click.option("--start-time", required=True, help="Session start time (HH:MM)")
@click.option("--end-time", required=True, help="Session end time (HH:MM)")
@click.option("--zoom-report", type=click.Path(exists=True), required=True)
@click.option("--qualtrics-report", type=click.Path(exists=True), required=True)
@click.option("--output-dir", type=click.Path(), default="./output")
@click.option(
    "--manual-overrides",
    type=click.Path(exists=True),
    help="CSV of Qualtrics name → Zoom name overrides",
)
def main(  # noqa: PLR0913
    title: str,
    training_date_str: str,
    instructor: str,
    ce_credits: int,
    ce_types: str,
    start_time: str,
    end_time: str,
    zoom_report: str,
    qualtrics_report: str,
    output_dir: str,
    manual_overrides: str | None,
) -> None:
    """Generate CE certificates from Zoom attendance and Qualtrics survey data.

    Full pipeline: parse → match → validate → generate → report.
    """
    # ── Parse boundary inputs ──────────────────────────────────────────────
    try:
        training_date = date.fromisoformat(training_date_str)
        parsed_start = time.fromisoformat(start_time)
        parsed_end = time.fromisoformat(end_time)
    except ValueError as exc:
        click.echo(f"Error: invalid date/time format — {exc}", err=True)
        sys.exit(1)

    ce_type_codes = [t.strip() for t in ce_types.split(",") if t.strip()]
    if not ce_type_codes:
        click.echo("Error: --ce-types must not be empty", err=True)
        sys.exit(1)

    # ── Run pipeline ───────────────────────────────────────────────────────
    result: PipelineResult = run_pipeline(
        zoom_path=zoom_report,
        qualtrics_path=qualtrics_report,
        title=title,
        training_date=training_date,
        instructor=instructor,
        ce_credits=ce_credits,
        ce_types=ce_type_codes,
        start_time=parsed_start,
        end_time=parsed_end,
        overrides_path=manual_overrides,
        output_dir=output_dir,
    )

    # ── Handle errors ──────────────────────────────────────────────────────
    if result.errors:
        for err in result.errors:
            click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    # ── Handle empty ───────────────────────────────────────────────────────
    if result.total_requests == 0:
        click.echo("No CE requests found in Qualtrics report.")
        sys.exit(0)

    # ── Print summary ──────────────────────────────────────────────────────
    pdf_count = len(result.eligible)
    click.echo(f"Total CE requests: {result.total_requests}")
    click.echo(f"Eligible: {len(result.eligible)}")
    click.echo(f"Ineligible: {len(result.ineligible)}")
    click.echo(f"Certificates generated: {pdf_count}")


if __name__ == "__main__":
    main()
