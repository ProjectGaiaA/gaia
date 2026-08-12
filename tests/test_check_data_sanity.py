"""Tests for scripts/check_data_sanity.py — quarantine vs systemic block.

The gate's contract: a bad ROW is stripped and publishing continues (so one
bad price can never wedge the pipeline), while a SYSTEMIC failure blocks the
publish entirely (so a scraper regression can never ship sitewide).
"""

import json
from datetime import datetime, timedelta, timezone

from scripts.check_data_sanity import (
    EXIT_BLOCK,
    EXIT_OK,
    EXIT_QUARANTINED,
    MAX_SANE_PRICE,
    scan,
    systemic_checks,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _setup(tmp_path, entries, retailers=None, manifest=None):
    data = tmp_path / "data"
    prices = data / "prices"
    prices.mkdir(parents=True)
    retailers = retailers or [{"id": "nursery-a", "active": True}]
    (data / "retailers.json").write_text(json.dumps(retailers), encoding="utf-8")
    if manifest is not None:
        # prev_manifest.json, NOT last_manifest.json. The gate deliberately
        # refuses to read last_manifest: the scrapers overwrite it with the
        # current run's prices before the gate executes, so reading it made
        # the check compare the run against itself and report a flawless 0%
        # movement over corrupt data. CI snapshots this file before scraping.
        (data / "prev_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with open(prices / "plant.jsonl", "w", encoding="utf-8") as f:
        for e in entries:
            f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")
    return str(data)


def _entry(price=29.99, ts=None, rid="nursery-a", tier="1gal", **info):
    return {
        "retailer_id": rid,
        "timestamp": ts or (NOW - timedelta(hours=2)).isoformat(),
        "sizes": {tier: {"price": price, **info}},
    }


def _verdict(data_dir):
    """Mirror main()'s decision without touching argv."""
    problems, stats, fresh, by_key = scan(data_dir, now=NOW, quarantine=True)
    fatal, extra = systemic_checks(data_dir, stats, fresh, by_key, problems)
    stats.update(extra)
    if fatal:
        return EXIT_BLOCK, problems, fatal, stats
    if problems:
        return EXIT_QUARANTINED, problems, fatal, stats
    return EXIT_OK, problems, fatal, stats


# --- clean data ---

def test_clean_data_passes(tmp_path):
    code, problems, fatal, _ = _verdict(_setup(tmp_path, [_entry()]))
    assert code == EXIT_OK and not problems and not fatal


def test_null_price_is_not_a_problem(tmp_path):
    """price: null means 'not scraped', which is normal."""
    code, problems, _, _ = _verdict(_setup(tmp_path, [_entry(price=None)]))
    assert code == EXIT_OK and not problems


# --- row-level problems are QUARANTINED, never blocking ---

def test_zero_price_row_is_quarantined_not_blocking(tmp_path):
    """The exact defect that wedged publishing: one price:0 among good rows."""
    good = [_entry(price=10 + i, tier=f"t{i}") for i in range(30)]
    data = _setup(tmp_path, good + [_entry(price=0)])
    code, problems, fatal, _ = _verdict(data)
    assert code == EXIT_QUARANTINED
    assert not fatal
    assert len(problems) == 1 and "<= 0" in problems[0]["reason"]


def test_quarantine_is_idempotent_no_wedge(tmp_path):
    """After quarantining, a re-run is clean — the pipeline self-heals."""
    good = [_entry(price=10 + i, tier=f"t{i}") for i in range(30)]
    data = _setup(tmp_path, good + [_entry(price=0)])
    assert _verdict(data)[0] == EXIT_QUARANTINED
    assert _verdict(data)[0] == EXIT_OK, "second run must be clean, not wedged"


def test_bad_rows_actually_removed_from_disk(tmp_path):
    data = _setup(tmp_path, [_entry(), _entry(price=-5), _entry(price=12.5)])
    _verdict(data)
    remaining = [
        json.loads(x)
        for x in open(f"{data}/prices/plant.jsonl", encoding="utf-8")
        if x.strip()
    ]
    assert len(remaining) == 2
    assert all(
        s["price"] > 0 for e in remaining for s in e["sizes"].values()
    )


def test_unparseable_line_quarantined(tmp_path):
    code, problems, _, _ = _verdict(_setup(tmp_path, [_entry(), "{not json"]))
    assert code == EXIT_QUARANTINED
    assert any("unparseable" in p["reason"] for p in problems)


def test_naive_timestamp_quarantined(tmp_path):
    code, problems, _, _ = _verdict(
        _setup(tmp_path, [_entry(ts="2026-08-10T10:00:00")])
    )
    assert code == EXIT_QUARANTINED
    assert any("naive" in p["reason"] for p in problems)


def test_absurd_and_non_finite_prices_quarantined(tmp_path):
    data = _setup(tmp_path, [_entry(price=MAX_SANE_PRICE + 1), _entry(price=float("nan"))])
    code, problems, _, _ = _verdict(data)
    assert code == EXIT_QUARANTINED
    assert len(problems) == 2
    assert any("non-finite" in p["reason"] for p in problems)


def test_recent_inactive_retailer_quarantined(tmp_path):
    code, problems, _, _ = _verdict(_setup(tmp_path, [_entry(rid="ghost")]))
    assert code == EXIT_QUARANTINED
    assert any("unknown/inactive" in p["reason"] for p in problems)


def test_old_row_from_deactivated_retailer_is_fine(tmp_path):
    """Deactivating a retailer must not brick the gate on its history."""
    old = (NOW - timedelta(days=10)).isoformat()
    code, problems, _, _ = _verdict(
        _setup(tmp_path, [_entry(ts=old, rid="retired")])
    )
    assert code == EXIT_OK and not problems


# --- systemic failures BLOCK ---

def test_sitewide_price_collapse_blocks(tmp_path):
    """The regression that shipped green before: every price becomes $9.99."""
    entries = [_entry(price=9.99, tier=f"t{i}") for i in range(40)]
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries))
    assert code == EXIT_BLOCK
    assert any("9.99" in f for f in fatal)


def test_mass_price_move_vs_manifest_blocks(tmp_path):
    """Prices all move drastically vs the last manifest → parser regression."""
    entries = [_entry(price=1.99, tier=f"t{i}") for i in range(40)]
    manifest = {"prices": {"plant:nursery-a": {f"t{i}": 50.0 for i in range(40)}}}
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries, manifest=manifest))
    assert code == EXIT_BLOCK
    assert any("moved more than" in f for f in fatal)


def test_last_manifest_is_not_used_as_a_baseline(tmp_path):
    """The scrapers rewrite last_manifest.json before the gate runs, so using
    it compares the run against itself. Measured on the real corpus: 735
    prices compared, 735 exactly equal, and tripling every price still exited
    0 while corrupting 127 of 133 pages. Writing the baseline to the wrong
    filename must therefore NOT produce a pass — the check is skipped."""
    entries = [_entry(price=1.99, tier=f"t{i}") for i in range(40)]
    manifest = {"prices": {"plant:nursery-a": {f"t{i}": 50.0 for i in range(40)}}}
    data_dir = _setup(tmp_path, entries)
    import os
    # deliberately the WRONG file — what the scrapers leave behind
    with open(os.path.join(data_dir, "last_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    code, _, fatal, _ = _verdict(data_dir)
    assert not any("moved more than" in x for x in fatal), (
        "gate read last_manifest.json — that is the self-comparison this "
        "design exists to prevent"
    )


def test_normal_price_movement_does_not_block(tmp_path):
    """Ordinary day-to-day movement must not trip the systemic check."""
    entries = [_entry(price=50.0 + i * 0.5, tier=f"t{i}") for i in range(40)]
    manifest = {"prices": {"plant:nursery-a": {f"t{i}": 50.0 for i in range(40)}}}
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries, manifest=manifest))
    assert code == EXIT_OK, f"unexpected fatal: {fatal}"


def test_mass_quarantine_blocks(tmp_path):
    """If most rows are bad it's a broken scrape, not noise — block."""
    entries = [_entry(price=0, tier=f"t{i}") for i in range(30)]
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries))
    assert code == EXIT_BLOCK
    assert any("looks broken" in f for f in fatal)


def test_small_sample_never_called_systemic(tmp_path):
    """Two identical prices is not a sitewide collapse."""
    code, _, fatal, _ = _verdict(
        _setup(tmp_path, [_entry(price=9.99), _entry(price=9.99, tier="2gal")])
    )
    assert code == EXIT_OK and not fatal
