"""Tests for scripts/check_data_sanity.py — the pre-build data gate."""

import json
from datetime import datetime, timedelta, timezone

from scripts.check_data_sanity import MAX_SANE_PRICE, scan

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _setup(tmp_path, entries, retailers=None):
    data = tmp_path / "data"
    prices = data / "prices"
    prices.mkdir(parents=True)
    if retailers is None:
        retailers = [{"id": "nursery-a", "active": True}]
    (data / "retailers.json").write_text(json.dumps(retailers), encoding="utf-8")
    with open(prices / "plant.jsonl", "w", encoding="utf-8") as f:
        for e in entries:
            f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")
    return str(data)


def _entry(price=29.99, ts=None, rid="nursery-a", **info):
    ts = ts or (NOW - timedelta(hours=2)).isoformat()
    return {
        "retailer_id": rid,
        "timestamp": ts,
        "sizes": {"1gal": {"price": price, **info}},
    }


def test_clean_data_passes(tmp_path):
    errors, stats = scan(_setup(tmp_path, [_entry()]), now=NOW)
    assert errors == []
    assert stats["fresh_points"] == 1
    assert stats["zero_offer_plants"] == 0


def test_zero_price_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, [_entry(price=0)]), now=NOW)
    assert any("<= 0" in e for e in errors)


def test_negative_price_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, [_entry(price=-4.5)]), now=NOW)
    assert any("<= 0" in e for e in errors)


def test_absurd_price_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, [_entry(price=MAX_SANE_PRICE + 1)]), now=NOW)
    assert any(str(MAX_SANE_PRICE) in e for e in errors)


def test_non_numeric_price_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, [_entry(price="29.99")]), now=NOW)
    assert any("non-numeric" in e for e in errors)


def test_naive_timestamp_fails(tmp_path):
    errors, _ = scan(
        _setup(tmp_path, [_entry(ts="2026-08-10T10:00:00")]), now=NOW
    )
    assert any("naive timestamp" in e for e in errors)


def test_unparseable_line_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, ["{not json"]), now=NOW)
    assert any("unparseable" in e for e in errors)


def test_recent_inactive_retailer_fails(tmp_path):
    errors, _ = scan(_setup(tmp_path, [_entry(rid="ghost")]), now=NOW)
    assert any("unknown/inactive retailer 'ghost'" in e for e in errors)


def test_old_row_from_inactive_retailer_ok(tmp_path):
    """Historical rows from a since-deactivated retailer must not fail the
    gate — otherwise deactivating a retailer bricks the pipeline."""
    old = (NOW - timedelta(days=10)).isoformat()
    errors, _ = scan(_setup(tmp_path, [_entry(ts=old, rid="retired")]), now=NOW)
    assert errors == []


def test_zero_offer_plant_counted(tmp_path):
    stale = (NOW - timedelta(days=45)).isoformat()
    _, stats = scan(_setup(tmp_path, [_entry(ts=stale)]), now=NOW)
    assert stats["zero_offer_plants"] == 1


def test_null_price_is_not_an_error(tmp_path):
    """price: null means 'no price scraped' — handled downstream, not a
    corruption signal."""
    errors, _ = scan(_setup(tmp_path, [_entry(price=None)]), now=NOW)
    assert errors == []
