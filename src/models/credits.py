"""CE credit amounts: positive, at most 100, in quarter-credit steps."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator

MAX_CE_CREDITS = Decimal(100)
_STEPS_PER_CREDIT = 4


def parse_ce_credits(value: object) -> float:
    """Validate a CE credit amount and return it as a float.

    Accepts numbers or numeric strings such as ``3``, ``"1.5"`` or ``2.75``.
    Quarter steps are exact in binary floating point, so the float is lossless.

    Raises:
        ValueError: If the value is not a number, is not positive, is above
            100, or is not a multiple of 0.25.
    """
    if isinstance(value, bool):
        msg = "CE credits must be a number"
        raise ValueError(msg)
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        msg = f"CE credits must be a number, got {value!r}"
        raise ValueError(msg) from None
    if not amount.is_finite() or amount <= 0 or amount > MAX_CE_CREDITS:
        msg = f"CE credits must be greater than 0 and at most {MAX_CE_CREDITS}"
        raise ValueError(msg)
    steps = amount * _STEPS_PER_CREDIT
    if steps != steps.to_integral_value():
        msg = "CE credits must be in steps of 0.25 (for example 1, 1.5, or 2.75)"
        raise ValueError(msg)
    return float(amount)


def format_ce_credits(value: float) -> str:
    """Format credits for a certificate: ``3`` not ``3.0``, ``1.5`` stays ``1.5``."""
    amount = Decimal(str(value)).quantize(Decimal("0.01")).normalize()
    return format(amount, "f")


CECredits = Annotated[float, BeforeValidator(parse_ce_credits)]
"""Pydantic field type for a validated CE credit amount."""
