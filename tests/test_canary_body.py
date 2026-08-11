"""Tests for scripts/canary_body.py.

The canary's only job is proving the alert channel is alive. A crash sends no
email, which looks exactly like a dead pipeline — so the hard requirement tested
here is that build_body NEVER raises, whatever garbage it reads.
"""

import json
from datetime import datetime, timezone

import pytest

from scripts.canary_body import build_body, sequence_number

NOW = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return p


# --- sequence numbering: a gap must be visible ---

@pytest.mark.parametrize("y,m,expected", [
    (2026, 8, 1), (2026, 9, 2), (2026, 12, 5), (2027, 1, 6), (2027, 8, 13),
])
def test_sequence_counts_months_from_epoch(y, m, expected):
    assert sequence_number(datetime(y, m, 1, tzinfo=timezone.utc)) == expected


def test_sequence_is_strictly_increasing_across_a_year():
    seqs = [sequence_number(datetime(2026, 8, 1, tzinfo=timezone.utc).replace(
        year=2026 + (7 + i) // 12, month=(7 + i) % 12 + 1)) for i in range(18)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 18


# --- must never raise ---

def test_missing_files_still_produce_a_body(tmp_path):
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "canary #4" in body
    assert "unreadable, missing, or malformed" in body


def test_corrupt_json_still_produces_a_body(tmp_path):
    _write(tmp_path, "status.json", "{not json")
    _write(tmp_path, "retailers.json", "]][[")
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "canary #4" in body


def test_wrong_shaped_json_still_produces_a_body(tmp_path):
    _write(tmp_path, "status.json", {"gates": "not-a-dict-oops"})
    _write(tmp_path, "retailers.json", {"unexpected": "object not list"})
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "canary #4" in body


def test_garbage_timestamp_does_not_crash(tmp_path):
    _write(tmp_path, "status.json", {"generated_at": "yesterday-ish"})
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "unknown" in body


def test_naive_timestamp_reported_as_unknown_not_crash(tmp_path):
    _write(tmp_path, "status.json", {"generated_at": "2026-11-01T12:00:00"})
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "unknown" in body


# --- content ---

def test_reports_real_status(tmp_path):
    _write(tmp_path, "status.json", {
        "generated_at": (NOW.replace(hour=1)).isoformat(),
        "built_from_commit": "deadbee",
        "gates": {"data_sanity": "pass", "tests": "fail", "quarantined_rows": 4},
        "silent_retailers": ["great-garden-plants"],
    })
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "deadbee" in body
    assert "12.0h ago" in body
    assert "ZERO ROWS: great-garden-plants" in body
    assert "Quarantined rows:    4" in body


def test_flags_retailers_with_no_affiliate_link(tmp_path):
    _write(tmp_path, "retailers.json", [
        {"id": "a", "active": True, "affiliate_template": "https://x?u={url}"},
        {"id": "b", "active": True},
        {"id": "c", "active": False},
    ])
    body = build_body(now=NOW, data_dir=str(tmp_path))
    assert "1 active" not in body  # two are active
    assert "2 active, 1 deactivated" in body
    assert "NO AFFILIATE LINK (1): b" in body
    assert "deactivated: c" in body


def test_subject_relevant_line_carries_no_problem_words(tmp_path):
    """The backlog belongs in the body; the subject stays liveness-only.

    Guards the alarm-fatigue fix: the first line must not acquire status words
    that would make a subject built from it read PROBLEMS every single month.
    """
    _write(tmp_path, "retailers.json", [{"id": "b", "active": True}])
    first = build_body(now=NOW, data_dir=str(tmp_path)).splitlines()[0]
    for word in ("PROBLEM", "FAIL", "ERROR", "WARN", "NO AFFILIATE"):
        assert word not in first.upper()
