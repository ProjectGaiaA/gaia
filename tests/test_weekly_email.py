"""Tests for weekly recovery email helpers: get_reportable_entries and format_recovery_email."""

from unittest.mock import patch

from scrapers.recovery import (
    get_reportable_entries,
    format_recovery_email,
    save_recovery,
)


# ---------------------------------------------------------------------------
# get_reportable_entries
# ---------------------------------------------------------------------------


def test_reportable_returns_unrecoverable_and_rejected(tmp_path):
    """Only entries with status 'unrecoverable' or 'rejected' are returned."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "unrecoverable", "retailer_id": "r1", "plant_id": "p1"},
            "r2:p2": {"status": "rejected", "retailer_id": "r2", "plant_id": "p2"},
            "r3:p3": {"status": "broken", "retailer_id": "r3", "plant_id": "p3"},
            "r4:p4": {"status": "confirmed", "retailer_id": "r4", "plant_id": "p4"},
            "r5:p5": {"status": "redirect_candidate", "retailer_id": "r5", "plant_id": "p5"},
            "r6:p6": {"status": "discovery_candidate", "retailer_id": "r6", "plant_id": "p6"},
            "r7:p7": {"status": "confirmation_failed", "retailer_id": "r7", "plant_id": "p7"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        entries = get_reportable_entries()

    assert len(entries) == 2
    statuses = {e["status"] for e in entries}
    assert statuses == {"unrecoverable", "rejected"}


def test_reportable_returns_empty_when_no_issues(tmp_path):
    """Returns empty list when all entries are non-reportable."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "broken"},
            "r2:p2": {"status": "confirmed", "candidate_handle": "h2"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        entries = get_reportable_entries()

    assert entries == []


def test_reportable_returns_empty_when_no_file(tmp_path):
    """Returns empty list when recovery.json doesn't exist."""
    path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        entries = get_reportable_entries()
    assert entries == []


def test_reportable_returns_empty_when_no_entries(tmp_path):
    """Returns empty list when recovery.json has zero entries."""
    path = tmp_path / "recovery.json"
    state = {"entries": {}}
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        entries = get_reportable_entries()
    assert entries == []


# ---------------------------------------------------------------------------
# format_recovery_email
# ---------------------------------------------------------------------------


def test_format_email_empty_entries():
    """Returns empty string when no entries to report."""
    assert format_recovery_email([]) == ""


def test_format_email_unrecoverable_only():
    """Email body lists unrecoverable entries with all fields."""
    entries = [
        {
            "status": "unrecoverable",
            "plant_common_name": "Limelight Hydrangea",
            "plant_id": "limelight-hydrangea",
            "retailer_id": "nature-hills",
            "old_handle": "hydrangea-lime-light",
            "attempts": 7,
            "reason": "No candidate found after 7 attempts",
            "candidate_handle": None,
        },
    ]
    body = format_recovery_email(entries)

    assert "UNRECOVERABLE (1)" in body
    assert "Limelight Hydrangea @ nature-hills" in body
    assert "Old handle: hydrangea-lime-light" in body
    assert "Attempts: 7" in body
    assert "No candidate found after 7 attempts" in body
    assert "REJECTED" not in body


def test_format_email_rejected_only():
    """Email body lists rejected entries with candidate handle."""
    entries = [
        {
            "status": "rejected",
            "plant_common_name": "Endless Summer Hydrangea",
            "plant_id": "endless-summer",
            "retailer_id": "planting-tree",
            "old_handle": "endless-summer-hydrangea",
            "candidate_handle": "endless-summer-tree-form",
            "reason": "Different cultivar: tree form vs shrub",
        },
    ]
    body = format_recovery_email(entries)

    assert "REJECTED BY REVIEW (1)" in body
    assert "Endless Summer Hydrangea @ planting-tree" in body
    assert "Candidate: endless-summer-tree-form" in body
    assert "Different cultivar" in body
    assert "UNRECOVERABLE" not in body


def test_format_email_mixed_statuses():
    """Email body groups unrecoverable and rejected separately."""
    entries = [
        {
            "status": "unrecoverable",
            "plant_common_name": "Limelight Hydrangea",
            "retailer_id": "nature-hills",
            "old_handle": "old-1",
            "attempts": 7,
            "reason": "No candidate found after 7 attempts",
        },
        {
            "status": "rejected",
            "plant_common_name": "Blue Spruce",
            "retailer_id": "fast-growing-trees",
            "old_handle": "old-2",
            "candidate_handle": "blue-spruce-new",
            "reason": "Price 3x higher than expected",
        },
    ]
    body = format_recovery_email(entries)

    assert "2 product(s) need attention" in body
    assert "UNRECOVERABLE (1)" in body
    assert "REJECTED BY REVIEW (1)" in body
    # Unrecoverable appears before rejected
    assert body.index("UNRECOVERABLE") < body.index("REJECTED")


def test_format_email_falls_back_to_plant_id():
    """When plant_common_name is None, falls back to plant_id."""
    entries = [
        {
            "status": "unrecoverable",
            "plant_common_name": None,
            "plant_id": "limelight-hydrangea",
            "retailer_id": "nature-hills",
            "old_handle": "old-handle",
            "attempts": 7,
            "reason": "No candidate found after 7 attempts",
        },
    ]
    body = format_recovery_email(entries)
    assert "limelight-hydrangea @ nature-hills" in body


def test_format_email_no_reason():
    """Entry without a reason still formats cleanly."""
    entries = [
        {
            "status": "unrecoverable",
            "plant_common_name": "Test Plant",
            "retailer_id": "test-retailer",
            "old_handle": "test-handle",
            "attempts": 7,
            "reason": None,
        },
    ]
    body = format_recovery_email(entries)
    assert "Test Plant @ test-retailer" in body
    assert "Reason:" not in body
