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

Matching is per CE request (name plus email). After individual matching, a
Zoom attendee claimed by two or more different people is reclassified as
ambiguous, unless exactly one of them has the Zoom attendee's email.
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
            confirmed = _only([c for c in candidates if zoom_email_keys.get(c) == q_email])
        case MatchSuccess(matched_name=matched, confidence=conf):
            same_email = zoom_email_keys.get(matched) == q_email
            confirmed = matched if conf < CONFIRMED_CONFIDENCE and same_email else None
        case None:
            same = _only([raw for raw, key in zoom_email_keys.items() if key == q_email])
            if same is None:
                return None
            return MatchSuccess(matched_name=same, confidence=EMAIL_ONLY_CONFIDENCE)
        case _:
            assert_never(outcome)
    if confirmed is None:
        return outcome
    return MatchSuccess(matched_name=confirmed, confidence=CONFIRMED_CONFIDENCE)


def _only(names: list[str]) -> str | None:
    """The single name in ``names``, or ``None`` when there are 0 or 2+."""
    return names[0] if len(names) == 1 else None


# ── Post-processing ───────────────────────────────────────────────────────────


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

    Name-keyed convenience wrapper around ``match_requests``: each distinct
    Qualtrics name is matched once, with its email (if any) as a tiebreaker.
    Use ``match_requests`` when two different people can share a name.

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
    unique = list(dict.fromkeys(qualtrics_names))
    emails = qualtrics_emails or {}
    results = match_requests(
        zoom_names,
        [(name, emails.get(name)) for name in unique],
        manual_overrides,
        zoom_emails=zoom_emails,
    )
    return dict(zip(unique, results, strict=True))


def person_groups(requests: list[tuple[str, str | None]]) -> list[int]:
    """Assign a person id to each ``(name, email)`` request.

    Two requests belong to the same person when their normalized names are
    equal and their emails do not conflict (one is missing, or both match
    case-insensitively). Same name with different emails, or different
    names with a shared email, are different people.

    Returns:
        A list with one person id per request, in request order.
    """
    people: list[tuple[str, str | None]] = []
    ids: list[int] = []
    for name, email in requests:
        norm = normalize_name(name)
        key = _email_key(email)
        found = None
        for pid, (p_norm, p_email) in enumerate(people):
            if p_norm == norm and (p_email is None or key is None or p_email == key):
                found = pid
                if p_email is None and key is not None:
                    people[pid] = (p_norm, key)
                break
        if found is None:
            people.append((norm, key))
            found = len(people) - 1
        ids.append(found)
    return ids


def match_requests(
    zoom_names: list[str],
    requests: list[tuple[str, str | None]],
    manual_overrides: dict[str, str] | None = None,
    *,
    zoom_emails: dict[str, str | None] | None = None,
) -> list[MatchResult]:
    """Match each ``(name, email)`` CE request to a Zoom attendance name.

    Results are per request, so two different people who share a name (or
    an email) never share a match. Requests from the same person (see
    ``person_groups``) may share a Zoom attendee; different people may not:
    when two people land on one Zoom attendee, the one whose email equals the
    Zoom email keeps it and the others become ambiguous; with no email
    winner, all of them become ambiguous.

    Args:
        zoom_names: Unique Zoom participant labels.
        requests: ``(name_on_certificate, email)`` per CE request.
        manual_overrides: Optional ``{qualtrics_name: zoom_name}`` mapping.
        zoom_emails: Optional ``{zoom_name: email}`` used as a tiebreaker.

    Returns:
        One ``MatchResult`` per request, in request order.
    """
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
    results: list[MatchResult] = []

    for q_raw, q_email_raw in requests:
        q_norm = normalize_name(q_raw)
        q_tokens = extract_name_tokens(q_norm)
        q_first = q_norm.split()[0] if q_norm else ""
        q_email = _email_key(q_email_raw)
        match_outcome: MatchAmbiguous | MatchSuccess | None = _match_manual_override(
            q_raw, overrides,
        )
        if match_outcome is not None:
            match_outcome = _apply_email(
                _override_target(match_outcome.matched_name, norm_to_zoom),
                q_email,
                zoom_email_keys,
            )
        else:
            match_outcome = _apply_email(
                _match_by_name(
                    q_norm, q_tokens, q_first, norm_to_zoom, zoom_entries, single_token_zooms
                ),
                q_email,
                zoom_email_keys,
            )
        results.append(match_outcome if match_outcome is not None else MatchNotFound())

    _resolve_shared_people(
        results,
        person_groups(requests),
        [_email_key(email) for _name, email in requests],
        zoom_email_keys,
    )
    return results


def _override_target(
    zoom_name: str,
    norm_to_zoom: dict[str, list[str]],
) -> MatchSuccess | MatchAmbiguous:
    """Resolve a manual override that names a Zoom display name.

    When several Zoom attendees share that display name (they are labelled
    ``"Name (email)"``), the override is ambiguous until the email picks one.
    """
    if any(zoom_name in raws for raws in norm_to_zoom.values()):
        return MatchSuccess(matched_name=zoom_name, confidence=1.0)
    same = norm_to_zoom.get(normalize_name(zoom_name), [])
    if len(same) > 1:
        return MatchAmbiguous(candidates=tuple(same))
    if len(same) == 1:
        return MatchSuccess(matched_name=same[0], confidence=1.0)
    return MatchSuccess(matched_name=zoom_name, confidence=1.0)


def _resolve_shared_people(
    results: list[MatchResult],
    person_ids: list[int],
    request_emails: list[str | None],
    zoom_email_keys: dict[str, str | None],
) -> None:
    """Flag Zoom attendees claimed by two or more different people (in place)."""
    claims: dict[str, dict[int, list[int]]] = {}
    for i, result in enumerate(results):
        match result:
            case MatchSuccess(matched_name=matched):
                claims.setdefault(matched, {}).setdefault(person_ids[i], []).append(i)
            case MatchAmbiguous() | MatchNotFound():
                pass
            case _:
                assert_never(result)

    for zoom_name, by_person in claims.items():
        if len(by_person) < 2:  # noqa: PLR2004
            continue
        zoom_email = zoom_email_keys.get(zoom_name)
        winners = [
            pid
            for pid, idxs in by_person.items()
            if zoom_email is not None
            and any(request_emails[i] == zoom_email for i in idxs)
        ]
        keep = winners[0] if len(winners) == 1 else None
        for pid, idxs in by_person.items():
            if pid == keep:
                continue
            for i in idxs:
                results[i] = MatchAmbiguous(candidates=(zoom_name,))


def batch_match(
    zoom_participants: list[ParticipantAttendance],
    ce_requests: list[CERequest],
    manual_overrides: dict[str, str] | None = None,
) -> list[tuple[CERequest, ParticipantAttendance | None, MatchResult]]:
    """Convenience wrapper that works directly with typed model objects.

    Matches each CE request on its own (name plus email), so two people who
    share a name or an email are never merged.

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

    match_results = match_requests(
        list(zoom_lookup.keys()),
        [(r.name_on_certificate, r.email) for r in ce_requests],
        manual_overrides,
        zoom_emails={name: p.email for name, p in zoom_lookup.items()},
    )

    output: list[tuple[CERequest, ParticipantAttendance | None, MatchResult]] = []
    for request, result in zip(ce_requests, match_results, strict=True):
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
