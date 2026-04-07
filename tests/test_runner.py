"""Tests for the scraper runner (scrapers/runner.py)."""

import json
from unittest.mock import patch

from scrapers.runner import check_price_anomaly, append_price


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
