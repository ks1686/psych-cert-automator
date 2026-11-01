"""Multi-strategy name matching between Zoom attendance and Qualtrics CE requests.

Implements a four-strategy matching pipeline, stopping at the first
unambiguous match:

1. Manual override (human-provided mappings)
2. Exact normalized match (confidence 1.0)
3. Token-set match — one name's tokens are a subset of the other's (confidence 0.9)
4. First-name partial match — Qualtrics first name matches a single-token Zoom entry
   (confidence 0.7)

When both sides carry an email, an identical (case-insensitive) email breaks
ties between same-named attendees and confirms a partial name match
(confidence 1.0). With no name relation at all, a unique email match is
offered at confidence 0.8.

Anything below 1.0 is a suggestion only: callers must treat it as
"needs review" and require an explicit confirmation (a manual override)
before issuing a certificate.

After individual matching, shared Zoom matches (multiple Qualtrics names
resolving to the same Zoom attendee) are reclassified as ambiguous.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from src.models.certificate import CERequest, MatchResult
    from src.models.participant import ParticipantAttendance

from src.models.certificate import MatchAmbiguous, MatchNotFound, MatchSuccess
from src.models.participant import extract_name_tokens, normalize_name

# ── Strategy helpers ──────────────────────────────────────────────────────────


def _match_manual_override(
    qualtrics_name: str,
    manual_overrides: dict[str, str],
) -> MatchSuccess | None:
    """Strategy 1: Look up a manual override for *qualtrics_name*.

    Args:
        qualtrics_name: Raw name as it appears in the Qualtrics export.
        manual_overrides: Mapping from Qualtrics name → Zoom name.

    Returns:
        ``MatchSuccess(confidence=1.0)`` if an override exists, or ``None``.
    """
    if qualtrics_name in manual_overrides:
        return MatchSuccess(
            matched_name=manual_overrides[qualtrics_name],
            confidence=1.0,
        )
    return None


def _match_exact_normalized(
    qualtrics_norm: str,
    norm_to_zoom: dict[str, list[str]],
) -> MatchSuccess | MatchAmbiguous | None:
    """Strategy 2: Exact match on normalized name.

    Args:
        qualtrics_norm: Normalized (lowercased, stripped) Qualtrics name.
        norm_to_zoom: Map from normalized name to its raw Zoom name(s).

    Returns:
        ``MatchSuccess(confidence=1.0)`` for a single match,
        ``MatchAmbiguous`` if multiple raw Zoom names normalise the same way,
        or ``None`` if no candidate.
    """
    candidates = norm_to_zoom.get(qualtrics_norm, [])
    if len(candidates) == 1:
        return MatchSuccess(matched_name=candidates[0], confidence=1.0)
    if len(candidates) > 1:
        return MatchAmbiguous(candidates=tuple(candidates))
    return None


def _match_token_set(
    qualtrics_tokens: frozenset[str],
    zoom_entries: list[tuple[str, frozenset[str]]],
) -> MatchSuccess | MatchAmbiguous | None:
    """Strategy 3: Token-set subset match.

    Two names match when one token set is a subset of the other.
    This handles middle initials and first/last name order swaps.

    Args:
        qualtrics_tokens: Token set of the normalised Qualtrics name.
        zoom_entries: ``(raw_name, token_set)`` for every Zoom name.

    Returns:
        ``MatchSuccess(confidence=0.9)`` for a single match,
        ``MatchAmbiguous`` for multiple, or ``None``.
    """
    candidates = [
        raw
        for raw, tokens in zoom_entries
        if qualtrics_tokens.issubset(tokens) or tokens.issubset(qualtrics_tokens)
    ]
    if len(candidates) == 1:
        return MatchSuccess(matched_name=candidates[0], confidence=0.9)
    if len(candidates) > 1:
        return MatchAmbiguous(candidates=tuple(candidates))
    return None


def _match_first_name_partial(
    qualtrics_first: str,
    single_token_zooms: dict[str, str],
) -> MatchSuccess | MatchAmbiguous | None:
    """Strategy 4: Match Qualtrics first name against single-token Zoom entries.

    A Zoom name consisting of a single word token (e.g. ``"Emmett"``,
    ``"Sheryl"``) is treated as a first-name-only entry.  Qualtrics names
    whose first word token matches are paired to it.

    Args:
        qualtrics_first: First word token of the normalised Qualtrics name.
        single_token_zooms: Map from raw Zoom name → its single normalised token.

    Returns:
        ``MatchSuccess(confidence=0.7)`` for a single match,
        ``MatchAmbiguous`` for multiple, or ``None``.
    """
    candidates = [
        raw
        for raw, token in single_token_zooms.items()
        if token == qualtrics_first
    ]
    if len(candidates) == 1:
        return MatchSuccess(matched_name=candidates[0], confidence=0.7)
    if len(candidates) > 1:
        return MatchAmbiguous(candidates=tuple(candidates))
    return None


EMAIL_ONLY_CONFIDENCE = 0.8
"""Confidence for an email-only match (names unrelated)."""

CONFIRMED_CONFIDENCE = 1.0
"""Confidence at or above which a match needs no human review."""


def _email_key(email: str | None) -> str | None:
    if email is None:
        return None
    key = email.strip().casefold()
    return key or None


def _apply_email(
    outcome: MatchSuccess | MatchAmbiguous | None,
    q_email: str | None,
    zoom_email_keys: dict[str, str | None],
) -> MatchSuccess | MatchAmbiguous | None:
    """Use the Qualtrics email to break ties and confirm partial name matches."""
    if q_email is None:
        return outcome
    match outcome:
        case MatchAmbiguous(candidates=candidates):
            same = [c for c in candidates if zoom_email_keys.get(c) == q_email]
            if len(same) == 1:
                return MatchSuccess(matched_name=same[0], confidence=CONFIRMED_CONFIDENCE)
            return outcome
        case MatchSuccess(matched_name=matched, confidence=conf):
            if conf < CONFIRMED_CONFIDENCE and zoom_email_keys.get(matched) == q_email:
                return MatchSuccess(matched_name=matched, confidence=CONFIRMED_CONFIDENCE)
            return outcome
        case None:
            same = [raw for raw, key in zoom_email_keys.items() if key == q_email]
            if len(same) == 1:
                return MatchSuccess(matched_name=same[0], confidence=EMAIL_ONLY_CONFIDENCE)
            return None
        case _:
            assert_never(outcome)


# ── Post-processing ───────────────────────────────────────────────────────────


def _resolve_shared_matches(results: dict[str, MatchResult]) -> None:
    """Reclassify Qualtrics names that all resolved to the same Zoom attendee.

    When two or more Qualtrics names produced ``MatchSuccess`` pointing at
    the identical Zoom name, every such Qualtrics entry is upgraded to
    ``MatchAmbiguous`` — a human must disambiguate.

    Args:
        results: Mapping mutated in-place.
    """
    zoom_to_qualtrics: dict[str, list[str]] = {}
    for q_name, result in results.items():
        match result:
            case MatchSuccess(matched_name=matched):
                zoom_to_qualtrics.setdefault(matched, []).append(q_name)
            case MatchAmbiguous():
                pass
            case MatchNotFound():
                pass
            case _:
                assert_never(result)

    for zoom_name, q_names in zoom_to_qualtrics.items():
        if len(q_names) > 1:
            for q_name in q_names:
                results[q_name] = MatchAmbiguous(candidates=(zoom_name,))


def _match_by_name(  # noqa: PLR0913
    q_norm: str,
    q_tokens: frozenset[str],
    q_first: str,
    norm_to_zoom: dict[str, list[str]],
    zoom_entries: list[tuple[str, frozenset[str]]],
    single_token_zooms: dict[str, str],
) -> MatchSuccess | MatchAmbiguous | None:
    """Run strategies 2-4 in order and return the first outcome."""
    if not q_norm:
        return None
    outcome = _match_exact_normalized(q_norm, norm_to_zoom)
    if outcome is None:
        outcome = _match_token_set(q_tokens, zoom_entries)
    if outcome is None:
        outcome = _match_first_name_partial(q_first, single_token_zooms)
    return outcome


# ── Public API ────────────────────────────────────────────────────────────────


def match_participants(
    zoom_names: list[str],
    qualtrics_names: list[str],
    manual_overrides: dict[str, str] | None = None,
    *,
    zoom_emails: dict[str, str | None] | None = None,
    qualtrics_emails: dict[str, str | None] | None = None,
) -> dict[str, MatchResult]:
    """Match every Qualtrics CE-request name to a Zoom attendance name.

    Runs the four-strategy pipeline for each Qualtrics name, stopping at the
    first unambiguous match.  After per-name matching, shared Zoom matches
    are flagged as ambiguous.

    Args:
        zoom_names: Raw Zoom participant names (from attendance export).
        qualtrics_names: Raw Qualtrics name-on-certificate strings.
        manual_overrides: Optional ``{qualtrics_name: zoom_name}`` mapping
            for known edge cases.
        zoom_emails: Optional ``{zoom_name: email}`` used as a tiebreaker.
        qualtrics_emails: Optional ``{qualtrics_name: email}``.

    Returns:
        Dictionary keyed by each Qualtrics name → its ``MatchResult``.
    """
    # ── Precompute normalised forms ──
    norm_to_zoom: dict[str, list[str]] = {}
    zoom_entries: list[tuple[str, frozenset[str]]] = []
    single_token_zooms: dict[str, str] = {}

    for raw in zoom_names:
        norm = normalize_name(raw)
        tokens = extract_name_tokens(norm)
        norm_to_zoom.setdefault(norm, []).append(raw)
        zoom_entries.append((raw, tokens))
        token_list = norm.split()
        if len(token_list) == 1:
            single_token_zooms[raw] = token_list[0]

    overrides = manual_overrides if manual_overrides is not None else {}
    zoom_email_keys = {
        raw: _email_key((zoom_emails or {}).get(raw)) for raw in zoom_names
    }
    q_email_keys = {
        raw: _email_key(email) for raw, email in (qualtrics_emails or {}).items()
    }
    results: dict[str, MatchResult] = {}

    for q_raw in qualtrics_names:
        q_norm = normalize_name(q_raw)
        q_tokens = extract_name_tokens(q_norm)
        q_first = q_norm.split()[0] if q_norm else ""
        match_outcome: MatchAmbiguous | MatchSuccess | None = None

        match_outcome = _match_manual_override(q_raw, overrides)

        if match_outcome is None:
            q_email = q_email_keys.get(q_raw)
            match_outcome = _apply_email(
                _match_by_name(q_norm, q_tokens, q_first, norm_to_zoom, zoom_entries, single_token_zooms),
                q_email,
                zoom_email_keys,
            )

        results[q_raw] = (
            match_outcome if match_outcome is not None else MatchNotFound()
        )

    _resolve_shared_matches(results)
    return results


def batch_match(
    zoom_participants: list[ParticipantAttendance],
    ce_requests: list[CERequest],
    manual_overrides: dict[str, str] | None = None,
) -> list[tuple[CERequest, ParticipantAttendance | None, MatchResult]]:
    """Convenience wrapper that works directly with typed model objects.

    Extracts raw names from *zoom_participants* and *ce_requests*, runs
    ``match_participants``, and returns a triple for each CE request.

    Args:
        zoom_participants: Aggregated Zoom attendance records.
        ce_requests: Qualtrics CE credit requests.
        manual_overrides: Optional manual name mapping.

    Returns:
        List of ``(CERequest, ParticipantAttendance | None, MatchResult)``
        triples.  The ``ParticipantAttendance`` is ``None`` when the match
        result is ``MatchAmbiguous`` or ``MatchNotFound``.
    """
    zoom_lookup: dict[str, ParticipantAttendance] = {}
    for p in zoom_participants:
        if p.name_raw not in zoom_lookup:
            zoom_lookup[p.name_raw] = p

    zoom_names = list(zoom_lookup.keys())
    qualtrics_names = [r.name_on_certificate for r in ce_requests]
    qualtrics_emails: dict[str, str | None] = {}
    for r in ce_requests:
        if r.email and not qualtrics_emails.get(r.name_on_certificate):
            qualtrics_emails[r.name_on_certificate] = r.email
    match_results = match_participants(
        zoom_names,
        qualtrics_names,
        manual_overrides,
        zoom_emails={name: p.email for name, p in zoom_lookup.items()},
        qualtrics_emails=qualtrics_emails,
    )

    output: list[tuple[CERequest, ParticipantAttendance | None, MatchResult]] = []
    for request in ce_requests:
        result = match_results[request.name_on_certificate]
        participant: ParticipantAttendance | None = None
        match result:
            case MatchSuccess(matched_name=matched):
                participant = zoom_lookup.get(matched)
            case MatchAmbiguous():
                pass
            case MatchNotFound():
                pass
            case _:
                assert_never(result)
        output.append((request, participant, result))

    return output
