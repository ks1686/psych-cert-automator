"""Certificate generation — pure-Python PDF generation (fpdf2) and ineligibility report output."""

from src.generator.certificate import generate_all, generate_certificate
from src.generator.report import generate_ineligibility_report

__all__ = [
    "generate_all",
    "generate_certificate",
    "generate_ineligibility_report",
]
