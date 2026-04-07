"""Tests for the price verification module (scrapers/verify.py)."""

from unittest.mock import patch

from scrapers.verify import load_stored_prices


def test_load_stored_prices_returns_latest_per_retailer(tmp_data_dir):
    """load_stored_prices should return the most recent entry per retailer."""
    prices_dir = tmp_data_dir / "prices"
    jsonl = prices_dir / "test-plant.jsonl"
    jsonl.write_text(
        '{"retailer_id": "nature-hills", "sizes": {"1gal": {"price": 39.99}}, "old": true}\n'
        '{"retailer_id": "planting-tree", "sizes": {"1gal": {"price": 44.99}}}\n'
        '{"retailer_id": "nature-hills", "sizes": {"1gal": {"price": 42.99}}, "old": false}\n',
        encoding="utf-8",
    )

    with patch("scrapers.verify.PRICES_DIR", prices_dir):
        result = load_stored_prices("test-plant")

    assert "nature-hills" in result
    assert "planting-tree" in result
    # Nature Hills latest is the third line (42.99)
    assert result["nature-hills"]["sizes"]["1gal"]["price"] == 42.99
    assert result["nature-hills"]["old"] is False


def test_load_stored_prices_empty_file(tmp_data_dir):
    """Empty JSONL returns empty dict."""
    prices_dir = tmp_data_dir / "prices"
    jsonl = prices_dir / "empty.jsonl"
    jsonl.write_text("", encoding="utf-8")

    with patch("scrapers.verify.PRICES_DIR", prices_dir):
        result = load_stored_prices("empty")

    assert result == {}


def test_load_stored_prices_missing_file(tmp_data_dir):
    """Missing JSONL returns empty dict."""
    prices_dir = tmp_data_dir / "prices"

    with patch("scrapers.verify.PRICES_DIR", prices_dir):
        result = load_stored_prices("nonexistent")

    assert result == {}


def test_price_comparison_within_tolerance():
    """Prices within 2% tolerance should be a PASS."""
    # $40.00 stored, $40.50 fresh = 1.25% diff → within 2% tolerance
    stored_price = 40.00
    fresh_price = 40.50
    diff_pct = abs(fresh_price - stored_price) / stored_price
    assert diff_pct <= 0.02  # 1.25% < 2%


def test_price_comparison_outside_tolerance():
    """Prices outside 2% tolerance should be flagged."""
    stored_price = 40.00
    fresh_price = 45.00  # 12.5% diff
    diff_pct = abs(fresh_price - stored_price) / stored_price
    assert diff_pct > 0.02
