"""Tests for the scraper runner (scrapers/runner.py)."""

import json
from unittest.mock import patch

from scrapers.runner import check_price_anomaly, append_price, merge_manifest


# --- Price anomaly detection ---


def test_anomaly_detects_large_price_swing():
    """Price change > 50% should be flagged as anomaly."""
    prev_manifest = {
        "prices": {
            "limelight-hydrangea:nature-hills": {
                "1gal": 40.00,
            }
        }
    }
    new_prices = {"1gal": {"price": 80.00}}  # 100% increase

    warnings = check_price_anomaly(
        "limelight-hydrangea", "nature-hills", new_prices, prev_manifest
    )
    assert len(warnings) > 0
    assert any("ANOMALY" in w for w in warnings)


def test_anomaly_ignores_normal_price_change():
    """Price change <= 50% should NOT be flagged."""
    prev_manifest = {
        "prices": {
            "limelight-hydrangea:nature-hills": {
                "1gal": 40.00,
            }
        }
    }
    new_prices = {"1gal": {"price": 45.00}}  # 12.5% increase

    warnings = check_price_anomaly(
        "limelight-hydrangea", "nature-hills", new_prices, prev_manifest
    )
    assert len(warnings) == 0


def test_anomaly_skips_new_plant():
    """New plant with no previous data should not trigger anomaly."""
    prev_manifest = {"prices": {}}
    new_prices = {"1gal": {"price": 40.00}}

    warnings = check_price_anomaly(
        "new-plant", "nature-hills", new_prices, prev_manifest
    )
    assert len(warnings) == 0


def test_anomaly_exact_50_pct_not_flagged():
    """Exactly 50% change is at the boundary — should NOT be flagged (> 50 required)."""
    prev_manifest = {
        "prices": {
            "test:test": {"1gal": 40.00}
        }
    }
    new_prices = {"1gal": {"price": 60.00}}  # exactly 50%

    warnings = check_price_anomaly("test", "test", new_prices, prev_manifest)
    assert len(warnings) == 0


# --- JSONL append ---


def test_append_price_creates_file(tmp_data_dir):
    """append_price should create JSONL file and append entry."""
    price_entry = {
        "retailer_id": "nature-hills",
        "timestamp": "2026-04-06T12:00:00Z",
        "sizes": {"1gal": {"price": 39.99}},
    }

    prices_dir = tmp_data_dir / "prices"
    with patch("scrapers.runner.PRICES_DIR", prices_dir):
        append_price("limelight-hydrangea", price_entry)

    jsonl_path = prices_dir / "limelight-hydrangea.jsonl"
    assert jsonl_path.exists()

    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["retailer_id"] == "nature-hills"


def test_append_price_appends_to_existing(tmp_data_dir):
    """append_price should append, not overwrite."""
    prices_dir = tmp_data_dir / "prices"
    jsonl_path = prices_dir / "test-plant.jsonl"
    jsonl_path.write_text('{"existing": true}\n', encoding="utf-8")

    entry = {"retailer_id": "test", "new": True}
    with patch("scrapers.runner.PRICES_DIR", prices_dir):
        append_price("test-plant", entry)

    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["existing"] is True
    assert json.loads(lines[1])["new"] is True


# --- Manifest merge (regression: partial single-retailer runs must not overwrite) ---


def _entry(retailer_id: str, prices: dict) -> dict:
    """Build a minimal manifest entry for a retailer with given price records."""
    return {
        "retailer_id": retailer_id,
        "status": "completed",
        "products_expected": len(prices),
        "products_found": len(prices),
        "products_error": 0,
        "prices_collected": sum(len(p) for p in prices.values()),
        "anomalies": [],
        "price_records": prices,
    }


def test_merge_manifest_preserves_other_retailers():
    """A single-retailer run must not wipe out other retailers' entries.

    Regression: CI invokes `scrapers.runner --retailer X` once per retailer and
    the previous implementation overwrote last_manifest.json on every run, so
    only the last retailer ever survived. This caused the top-level totals and
    retailer list to be a lie.
    """
    prev = {
        "timestamp": "2026-04-09T00:00:00+00:00",
        "retailers": [
            _entry("nature-hills", {"limelight:nature-hills": {"1gal": 39.99}}),
            _entry("planting-tree", {"limelight:planting-tree": {"3gal": 49.99}}),
        ],
        "total_prices_collected": 2,
        "total_anomalies": 0,
        "anomalies": [],
        "prices": {
            "limelight:nature-hills": {"1gal": 39.99},
            "limelight:planting-tree": {"3gal": 49.99},
        },
    }
    # Simulate a --retailer stark-bros run: only stark-bros is in new_entries
    new_entries = [
        _entry("stark-bros", {"honeycrisp:stark-bros": {"semi-dwarf": 26.99}}),
    ]

    merged = merge_manifest(prev, new_entries)

    retailer_ids = {e["retailer_id"] for e in merged["retailers"]}
    assert retailer_ids == {"nature-hills", "planting-tree", "stark-bros"}
    # Price records for all three retailers must be present
    assert "limelight:nature-hills" in merged["prices"]
    assert "limelight:planting-tree" in merged["prices"]
    assert "honeycrisp:stark-bros" in merged["prices"]
    # Top-level totals reflect the merged state, not just this run
    assert merged["total_prices_collected"] == 3


def test_merge_manifest_replaces_same_retailer_entry():
    """Re-scraping the same retailer replaces its entry and drops stale prices."""
    prev = {
        "retailers": [
            _entry("nature-hills", {"limelight:nature-hills": {"1gal": 39.99}}),
        ],
        "prices": {"limelight:nature-hills": {"1gal": 39.99, "3gal": 59.99}},
    }
    # New run: only 1gal this time (3gal dropped)
    new_entries = [
        _entry("nature-hills", {"limelight:nature-hills": {"1gal": 42.99}}),
    ]

    merged = merge_manifest(prev, new_entries)

    # Only one nature-hills entry — not duplicated
    nh = [e for e in merged["retailers"] if e["retailer_id"] == "nature-hills"]
    assert len(nh) == 1
    # Prices reflect the new run, stale 3gal is gone
    assert merged["prices"]["limelight:nature-hills"] == {"1gal": 42.99}


def test_merge_manifest_full_run_replaces_everything():
    """A full run (all retailers in new_entries) effectively replaces the manifest."""
    prev = {
        "retailers": [_entry("old-retailer", {"plant:old-retailer": {"1gal": 10}})],
        "prices": {"plant:old-retailer": {"1gal": 10}},
    }
    new_entries = [
        _entry("nature-hills", {"plant:nature-hills": {"1gal": 20}}),
        _entry("stark-bros", {"plant:stark-bros": {"semi-dwarf": 30}}),
    ]

    merged = merge_manifest(prev, new_entries)

    # old-retailer should still be there (not scraped this run)
    retailer_ids = {e["retailer_id"] for e in merged["retailers"]}
    assert retailer_ids == {"old-retailer", "nature-hills", "stark-bros"}
    # Stale old-retailer prices preserved because we didn't re-scrape it
    assert merged["prices"]["plant:old-retailer"] == {"1gal": 10}
