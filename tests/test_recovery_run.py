"""Tests for recovery orchestration — time-budgeted discovery after scrape."""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from scrapers.recovery import load_recovery


def _write_recovery(tmp_path, entries: dict) -> None:
    """Helper to write recovery.json in tmp_path."""
    path = tmp_path / "recovery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f)


def _read_recovery(tmp_path) -> dict:
    """Helper to read recovery.json from tmp_path."""
    path = tmp_path / "recovery.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_broken_entry(
    retailer_id: str,
    plant_id: str,
    old_handle: str,
    attempts: int = 0,
    last_discovery_attempt: str | None = None,
) -> dict:
    """Create a broken recovery entry for testing."""
    return {
        "retailer_id": retailer_id,
        "plant_id": plant_id,
        "old_handle": old_handle,
        "status": "broken",
        "candidate_handle": None,
        "redirect_url": None,
        "attempts": attempts,
        "last_discovery_attempt": last_discovery_attempt,
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
        "plant_common_name": None,
        "botanical_name": None,
        "candidate_title": None,
        "match_score": None,
        "old_sizes_prices": {},
        "candidate_sizes_prices": {},
        "reason": None,
    }


def _write_plants(tmp_path, plants: list[dict]) -> None:
    """Write a minimal plants.json."""
    path = tmp_path / "plants.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plants, f)


def _write_retailers(tmp_path, retailers: list[dict]) -> None:
    """Write a minimal retailers.json."""
    path = tmp_path / "retailers.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(retailers, f)


def _write_manifest(tmp_path, manifest: dict) -> None:
    """Write a minimal last_manifest.json."""
    path = tmp_path / "last_manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)


# ---------------------------------------------------------------------------
# get_actionable_entries
# ---------------------------------------------------------------------------


class TestGetActionableEntries:
    """Tests for filtering recovery entries that need work."""

    def test_returns_broken_entries(self, tmp_path):
        """Broken entries with no cooldown and low attempts are actionable."""
        from scrapers.recovery import get_actionable_entries

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle"
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert len(result) == 1
        assert result[0]["plant_id"] == "limelight-hydrangea"

    def test_skips_entries_on_cooldown(self, tmp_path):
        """Entries with last_discovery_attempt < 20 hours ago are skipped."""
        from scrapers.recovery import get_actionable_entries

        recent = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
                attempts=1, last_discovery_attempt=recent,
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert len(result) == 0

    def test_includes_entries_past_cooldown(self, tmp_path):
        """Entries with last_discovery_attempt > 20 hours ago are included."""
        from scrapers.recovery import get_actionable_entries

        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
                attempts=3, last_discovery_attempt=old,
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert len(result) == 1

    def test_skips_entries_at_attempt_limit(self, tmp_path):
        """Entries with >= 7 attempts are not actionable (should be marked unrecoverable)."""
        from scrapers.recovery import get_actionable_entries

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
                attempts=7,
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert len(result) == 0

    def test_skips_non_broken_statuses(self, tmp_path):
        """Only 'broken' entries are actionable — candidates, confirmed, etc. are not."""
        from scrapers.recovery import get_actionable_entries

        entries = {
            "r1:p1": {**_make_broken_entry("r1", "p1", "h1"), "status": "redirect_candidate"},
            "r2:p2": {**_make_broken_entry("r2", "p2", "h2"), "status": "confirmed"},
            "r3:p3": {**_make_broken_entry("r3", "p3", "h3"), "status": "unrecoverable"},
            "r4:p4": {**_make_broken_entry("r4", "p4", "h4"), "status": "discovery_candidate"},
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert len(result) == 0

    def test_returns_empty_when_no_entries(self, tmp_path):
        """Returns empty list when recovery.json has no entries."""
        from scrapers.recovery import get_actionable_entries

        _write_recovery(tmp_path, {})

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = get_actionable_entries()

        assert result == []


# ---------------------------------------------------------------------------
# mark_unrecoverable
# ---------------------------------------------------------------------------


class TestMarkUnrecoverable:
    """Tests for marking entries as unrecoverable after 7 attempts."""

    def test_marks_entry_as_unrecoverable(self, tmp_path):
        from scrapers.recovery import mark_unrecoverable

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle", attempts=7,
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            mark_unrecoverable("nature-hills", "limelight-hydrangea")
            state = load_recovery()

        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        assert entry["status"] == "unrecoverable"
        assert "7 attempts" in entry["reason"]


# ---------------------------------------------------------------------------
# record_discovery_candidate
# ---------------------------------------------------------------------------


class TestRecordDiscoveryCandidate:
    """Tests for storing discovery candidates with full context."""

    def test_writes_candidate_with_all_context(self, tmp_path):
        from scrapers.recovery import record_discovery_candidate

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle", attempts=2,
            ),
        }
        _write_recovery(tmp_path, entries)

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            record_discovery_candidate(
                retailer_id="nature-hills",
                plant_id="limelight-hydrangea",
                candidate_handle="hydrangea-limelight-new",
                candidate_title="Limelight Hydrangea Tree",
                match_score=0.85,
                plant_common_name="Limelight Hydrangea",
                botanical_name="Hydrangea paniculata 'Limelight'",
                old_sizes_prices={"1gal": 29.99, "3gal": 49.99},
                candidate_sizes_prices={"1gal": 31.99, "3gal": 51.99},
            )
            state = load_recovery()

        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        assert entry["status"] == "discovery_candidate"
        assert entry["candidate_handle"] == "hydrangea-limelight-new"
        assert entry["candidate_title"] == "Limelight Hydrangea Tree"
        assert entry["match_score"] == 0.85
        assert entry["plant_common_name"] == "Limelight Hydrangea"
        assert entry["botanical_name"] == "Hydrangea paniculata 'Limelight'"
        assert entry["old_sizes_prices"] == {"1gal": 29.99, "3gal": 49.99}
        assert entry["candidate_sizes_prices"] == {"1gal": 31.99, "3gal": 51.99}
        assert entry["attempts"] == 3  # incremented from 2
        assert entry["last_discovery_attempt"] is not None


# ---------------------------------------------------------------------------
# run() — main orchestration
# ---------------------------------------------------------------------------


class TestRecoveryRun:
    """Tests for the main recovery.run() orchestration function."""

    def test_exits_immediately_with_no_actionable_entries(self, tmp_path, no_sleep):
        """Recovery does nothing when recovery.json has zero actionable entries."""
        from scrapers.recovery import run as recovery_run

        _write_recovery(tmp_path, {})

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = recovery_run(
                time_budget_seconds=3600,
                data_dir=tmp_path,
            )

        assert result["entries_processed"] == 0
        assert result["candidates_found"] == 0

    def test_marks_entries_at_attempt_limit_as_unrecoverable(self, tmp_path, no_sleep):
        """Entries with >= 7 attempts are marked unrecoverable before discovery."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle", attempts=7,
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [])
        _write_retailers(tmp_path, [])
        _write_manifest(tmp_path, {"prices": {}})

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        state = _read_recovery(tmp_path)
        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        assert entry["status"] == "unrecoverable"
        assert result["entries_marked_unrecoverable"] == 1

    def test_skips_entries_on_cooldown(self, tmp_path, no_sleep):
        """Entries last attempted < 20 hours ago are skipped."""
        from scrapers.recovery import run as recovery_run

        recent = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
                attempts=2, last_discovery_attempt=recent,
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [])
        _write_retailers(tmp_path, [])
        _write_manifest(tmp_path, {"prices": {}})

        with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        assert result["entries_processed"] == 0

    def test_discovery_finds_candidate(self, tmp_path, no_sleep):
        """When discovery returns a match, candidate is stored with full context."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "hydrangea-lime-light",
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {
                "id": "limelight-hydrangea",
                "common_name": "Limelight Hydrangea",
                "botanical_name": "Hydrangea paniculata 'Limelight'",
            },
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {
            "prices": {
                "limelight-hydrangea:nature-hills": {"1gal": 29.99, "3gal": 49.99},
            },
        })

        # Mock fetch_all_products to return a catalog with a matching product
        mock_catalog = [
            {
                "title": "Limelight Hydrangea",
                "handle": "limelight-hydrangea-new",
                "variants": [
                    {"title": "1 Gallon", "price": "31.99"},
                    {"title": "3 Gallon", "price": "52.99"},
                ],
            },
            {
                "title": "Endless Summer Hydrangea",
                "handle": "endless-summer",
                "variants": [{"title": "1 Gallon", "price": "24.99"}],
            },
        ]

        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products", return_value=mock_catalog),
        ):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        assert result["candidates_found"] == 1

        state = _read_recovery(tmp_path)
        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        assert entry["status"] == "discovery_candidate"
        assert entry["candidate_handle"] == "limelight-hydrangea-new"
        assert entry["candidate_title"] == "Limelight Hydrangea"
        assert entry["plant_common_name"] == "Limelight Hydrangea"
        assert entry["botanical_name"] == "Hydrangea paniculata 'Limelight'"
        assert entry["match_score"] > 0.5
        assert entry["old_sizes_prices"] == {"1gal": 29.99, "3gal": 49.99}
        assert entry["candidate_sizes_prices"]["1 Gallon"] == 31.99
        assert entry["attempts"] == 1

    def test_discovery_no_match_increments_attempts(self, tmp_path, no_sleep):
        """When discovery finds no match, attempts is still incremented."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "hydrangea-lime-light",
                attempts=3,
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": "limelight-hydrangea", "common_name": "Limelight Hydrangea",
             "botanical_name": "Hydrangea paniculata 'Limelight'"},
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        # Empty catalog — no matches possible
        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products", return_value=[]),
        ):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        assert result["candidates_found"] == 0

        state = _read_recovery(tmp_path)
        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        assert entry["status"] == "broken"  # still broken, no candidate
        assert entry["attempts"] == 4  # incremented from 3
        assert entry["last_discovery_attempt"] is not None

    def test_respects_time_budget(self, tmp_path, no_sleep):
        """Recovery stops processing when time budget is exhausted."""
        from scrapers.recovery import run as recovery_run

        # Create 3 broken entries
        entries = {}
        for i in range(3):
            key = f"nature-hills:plant-{i}"
            entries[key] = _make_broken_entry(
                "nature-hills", f"plant-{i}", f"handle-{i}",
            )
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": f"plant-{i}", "common_name": f"Plant {i}", "botanical_name": f"Botanical {i}"}
            for i in range(3)
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        # Give zero time budget — nothing should be processed
        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products", return_value=[]),
        ):
            result = recovery_run(time_budget_seconds=0, data_dir=tmp_path)

        assert result["entries_processed"] == 0

    def test_groups_by_retailer_fetches_catalog_once(self, tmp_path, no_sleep):
        """Multiple broken handles at same retailer share one catalog fetch."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:plant-a": _make_broken_entry(
                "nature-hills", "plant-a", "handle-a",
            ),
            "nature-hills:plant-b": _make_broken_entry(
                "nature-hills", "plant-b", "handle-b",
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": "plant-a", "common_name": "Plant A", "botanical_name": "Botanical A"},
            {"id": "plant-b", "common_name": "Plant B", "botanical_name": "Botanical B"},
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        mock_fetch = MagicMock(return_value=[])

        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products", mock_fetch),
        ):
            recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        # fetch_all_products called exactly once for nature-hills
        assert mock_fetch.call_count == 1

    def test_skips_non_shopify_retailers(self, tmp_path, no_sleep):
        """Entries for non-Shopify retailers are skipped (no catalog endpoint)."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "stark-bros:plant-a": _make_broken_entry(
                "stark-bros", "plant-a", "handle-a",
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": "plant-a", "common_name": "Plant A", "botanical_name": "Botanical A"},
        ])
        _write_retailers(tmp_path, [
            {"id": "stark-bros", "url": "https://www.starkbros.com",
             "scraper_type": "custom", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products") as mock_fetch,
        ):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        mock_fetch.assert_not_called()
        assert result["entries_processed"] == 0

    def test_extracts_candidate_prices_from_variants(self, tmp_path, no_sleep):
        """Candidate sizes/prices are extracted from Shopify variant data."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": "limelight-hydrangea", "common_name": "Limelight Hydrangea",
             "botanical_name": "Hydrangea paniculata 'Limelight'"},
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        mock_catalog = [{
            "title": "Limelight Hydrangea",
            "handle": "limelight-new",
            "variants": [
                {"title": "1 Gallon", "price": "29.99"},
                {"title": "3 Gallon", "price": "49.99"},
                {"title": "5 Gallon", "price": "79.99"},
            ],
        }]

        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch("scrapers.discover_handles.fetch_all_products", return_value=mock_catalog),
        ):
            recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        state = _read_recovery(tmp_path)
        entry = state["entries"]["nature-hills:limelight-hydrangea"]
        prices = entry["candidate_sizes_prices"]
        assert prices == {"1 Gallon": 29.99, "3 Gallon": 49.99, "5 Gallon": 79.99}

    def test_catalog_fetch_failure_does_not_crash(self, tmp_path, no_sleep):
        """If fetch_all_products raises, recovery continues without crashing."""
        from scrapers.recovery import run as recovery_run

        entries = {
            "nature-hills:limelight-hydrangea": _make_broken_entry(
                "nature-hills", "limelight-hydrangea", "old-handle",
            ),
        }
        _write_recovery(tmp_path, entries)
        _write_plants(tmp_path, [
            {"id": "limelight-hydrangea", "common_name": "Limelight Hydrangea",
             "botanical_name": "Hydrangea paniculata 'Limelight'"},
        ])
        _write_retailers(tmp_path, [
            {"id": "nature-hills", "url": "https://www.naturehills.com",
             "scraper_type": "shopify", "active": True},
        ])
        _write_manifest(tmp_path, {"prices": {}})

        with (
            patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"),
            patch(
                "scrapers.discover_handles.fetch_all_products",
                side_effect=Exception("Connection refused"),
            ),
        ):
            result = recovery_run(time_budget_seconds=3600, data_dir=tmp_path)

        # Should not crash — treats as empty catalog (no match)
        assert result["candidates_found"] == 0
        assert result["entries_processed"] == 1
