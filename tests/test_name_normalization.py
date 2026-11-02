"""Unicode, accent, and apostrophe variants of a name normalize the same way."""

from __future__ import annotations

import unicodedata

import pytest
from src.matcher.name_matcher import match_participants
from src.models.certificate import MatchSuccess
from src.models.participant import normalize_name


@pytest.mark.parametrize(
    ("zoom", "qualtrics"),
    [
        ("  FRANK   o'neil ", "Frank O\u2019Neil"),
        ("Jos\u00e9 N\u00fa\u00f1ez", "Jose Nunez"),
        (unicodedata.normalize("NFD", "Zo\u00eb Kraus"), "Zo\u00eb Kraus"),
        ("\uff2b\uff49\uff4d Lee", "Kim Lee"),  # full-width letters (NFKC)
    ],
)
def test_variants_are_exact_matches(zoom: str, qualtrics: str) -> None:
    assert normalize_name(zoom) == normalize_name(qualtrics)
    result = match_participants([zoom], [qualtrics])[qualtrics]
    assert result == MatchSuccess(matched_name=zoom, confidence=1.0)
