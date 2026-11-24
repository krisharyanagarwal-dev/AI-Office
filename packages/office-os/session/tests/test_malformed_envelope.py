"""Requirement 9: malformed input is refused explicitly.

No upstream error response has ever been observed from `list_chat_sessions`, so
this suite asserts *our* rejection reasons and deliberately asserts the absence
of any invented error envelope. Treating `{"error": ...}` as "the API's error
shape" would be a fabrication wearing a plausible face.
"""

import pytest

from fixtures_synthetic import KIND, FIXTURE_NOW_MS, page, row

from qoder_session_floor import EnvelopeMalformed, parse_envelope


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "envelope_type"),
        ("sessions", "envelope_type"),
        ([], "envelope_type"),
        ({}, "envelope_missing_kind"),
        ({"kind": "qoder.chatSessions.listed"}, "envelope_missing_sessions"),
        ({"kind": "other.thing", "sessions": [], "nextCursor": None}, "envelope_kind_unknown"),
        ({"kind": KIND, "sessions": {}, "nextCursor": None}, "envelope_sessions_type"),
        ({"kind": KIND, "sessions": "no", "nextCursor": None}, "envelope_sessions_type"),
        ({"kind": KIND, "sessions": [[]], "nextCursor": None}, "row_type"),
        ({"kind": KIND, "sessions": [{"sessionId": "x"}], "nextCursor": None}, "row_missing_field"),
        ({"kind": KIND, "sessions": [dict(row("fx-a"), title=None)], "nextCursor": None}, "row_type"),
        ({"kind": KIND, "sessions": [dict(row("fx-a"), unread="false")], "nextCursor": None}, "row_type"),
        ({"kind": KIND, "sessions": [dict(row("fx-a"), pendingInteractionCount=True)], "nextCursor": None}, "row_type"),
        ({"kind": KIND, "sessions": [dict(row("fx-a"), sessionId="")], "nextCursor": None}, "row_identity"),
        ({"kind": KIND, "sessions": []}, "envelope_missing_cursor"),
        ({"kind": KIND, "sessions": [], "nextCursor": "01"}, "cursor_format"),
        ({"kind": KIND, "sessions": [], "nextCursor": 2}, "cursor_type"),
    ],
)
def test_malformed_envelopes_are_rejected_with_a_reason(raw, reason):
    with pytest.raises(EnvelopeMalformed) as caught:
        parse_envelope(raw)
    assert caught.value.reason == reason


def test_a_row_missing_one_required_field_is_rejected_not_guessed():
    """Every one of the eight observed fields is load-bearing."""
    for missing in ("sessionId", "title", "cwd", "updatedAt", "runtimeState", "pendingInteractionCount", "unread", "archived"):
        broken = {k: v for k, v in row("fx-a").items() if k != missing}
        with pytest.raises(EnvelopeMalformed) as caught:
            parse_envelope({"kind": KIND, "sessions": [broken], "nextCursor": None})
        assert caught.value.reason == "row_missing_field", missing


def test_an_empty_session_id_is_rejected_because_dedup_needs_an_identity():
    with pytest.raises(EnvelopeMalformed) as caught:
        parse_envelope({"kind": KIND, "sessions": [{"sessionId": "", "title": "t", "cwd": "/c", "updatedAt": 1, "runtimeState": "cold", "pendingInteractionCount": 0, "unread": False, "archived": False}], "nextCursor": None})
    assert caught.value.reason == "row_identity"


def test_unknown_keys_are_preserved_and_reported_rather_than_dropped():
    """Upstream adding a field must surface as evidence, not vanish silently."""
    envelope = parse_envelope(
        {
            "kind": KIND,
            "sessions": [dict(row("fx-a"), modelTier="fx-tier-9")],
            "nextCursor": None,
            "serverRevision": "fx",
        }
    )
    assert envelope.unexpected_row_fields == ("modelTier",)
    assert envelope.unexpected_envelope_fields == ("serverRevision",)
    assert envelope.items[0]["modelTier"] == "fx-tier-9"


def test_error_looking_payload_is_not_treated_as_a_known_error_shape():
    with pytest.raises(EnvelopeMalformed) as caught:
        parse_envelope({"error": "rate limited", "message": "try later"})
    assert caught.value.reason == "envelope_missing_kind"


def test_valid_input_is_accepted_and_typed():
    envelope = parse_envelope(page([row("fx-a", "ready")], None), now_ms=FIXTURE_NOW_MS)
    assert envelope.emitted == 1
    assert envelope.is_terminal is True
    assert envelope.items[0]["runtimeState"] == "ready"
