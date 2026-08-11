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


def _setup(tmp_path, entries, retailers=None, manifest=None, stale_manifest=None):
    """`manifest` is the PREVIOUS cycle's snapshot, which is what the gate reads.

    `stale_manifest` writes last_manifest.json instead — the file the scrapers
    overwrite mid-run. The gate must ignore it entirely; tests use it to prove
    the same-cycle comparison can never come back.
    """
    data = tmp_path / "data"
    prices = data / "prices"
    prices.mkdir(parents=True)
    retailers = retailers or [{"id": "nursery-a", "active": True}]
    (data / "retailers.json").write_text(json.dumps(retailers), encoding="utf-8")
    if manifest is not None:
        (data / "prev_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if stale_manifest is not None:
        (data / "last_manifest.json").write_text(
            json.dumps(stale_manifest), encoding="utf-8"
        )
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


def _warnings_for(data_dir):
    """systemic_checks output including warnings, for skip-path assertions."""
    problems, stats, fresh, by_key = scan(data_dir, now=NOW, quarantine=True)
    return systemic_checks(data_dir, stats, fresh, by_key, problems)


def _verdict(data_dir):
    """Mirror main()'s decision without touching argv."""
    problems, stats, fresh, by_key = scan(data_dir, now=NOW, quarantine=True)
    fatal, warns, extra = systemic_checks(data_dir, stats, fresh, by_key, problems)
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


def test_normal_price_movement_does_not_block(tmp_path):
    """Ordinary day-to-day movement must not trip the systemic check."""
    entries = [_entry(price=50.0 + i * 0.5, tier=f"t{i}") for i in range(40)]
    manifest = {"prices": {"plant:nursery-a": {f"t{i}": 50.0 for i in range(40)}}}
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries, manifest=manifest))
    assert code == EXIT_OK, f"unexpected fatal: {fatal}"


# --- the baseline must be the PREVIOUS cycle, never this one ---

def test_same_cycle_manifest_is_ignored(tmp_path):
    """The defect that made three systemic checks decorative for months.

    runner.py rewrites last_manifest.json with this run's prices while scraping,
    and every scraper runs before this gate. Reading that file compares the run
    to itself: measured on the real corpus, 771/771 keys identical on every
    historical run, and halving every price scored 0% moved and published clean.
    Only prev_manifest.json may be used as a baseline.
    """
    # Distinct values so this isolates the delta check; identical values would
    # trip the separate sitewide-collapse detector instead.
    entries = [_entry(price=1.0 + i * 0.01, tier=f"t{i}") for i in range(40)]
    # Exactly what production had: last_manifest already holds THIS run's prices.
    same_cycle = {
        "prices": {"plant:nursery-a": {f"t{i}": 1.0 + i * 0.01 for i in range(40)}}
    }
    real_prev = {"prices": {"plant:nursery-a": {f"t{i}": 50.0 + i for i in range(40)}}}

    # With only the same-cycle file present, the gate must NOT be reassured by it.
    data = _setup(tmp_path, entries, stale_manifest=same_cycle)
    code, _, fatal, stats = _verdict(data)
    assert stats["prices_compared"] == 0, "last_manifest.json must never be a baseline"
    assert code != EXIT_BLOCK

    # Given a genuine previous cycle, the same corruption is caught.
    data2 = _setup(tmp_path / "b", entries, manifest=real_prev, stale_manifest=same_cycle)
    code2, _, fatal2, _ = _verdict(data2)
    assert code2 == EXIT_BLOCK, "drastic move vs previous cycle must block"
    assert any("moved more than" in f or "moved" in f for f in fatal2)


def test_missing_baseline_warns_rather_than_reporting_all_clear(tmp_path):
    """No baseline must be reported as skipped, not as '0 prices moved'."""
    entries = [_entry(price=10.0 + i, tier=f"t{i}") for i in range(40)]
    _, warns, extra = _warnings_for(_setup(tmp_path, entries))
    assert extra["prices_compared"] == 0
    assert any("SKIPPED" in w for w in warns), warns


def test_sitewide_halving_blocks_with_real_baseline(tmp_path):
    """The headline attack: every price on the site halved."""
    prev = {"prices": {"plant:nursery-a": {f"t{i}": 100.0 for i in range(40)}}}
    entries = [_entry(price=50.0, tier=f"t{i}") for i in range(40)]
    code, _, fatal, _ = _verdict(_setup(tmp_path, entries, manifest=prev))
    assert code == EXIT_BLOCK, f"halving must block; fatal={fatal}"


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
