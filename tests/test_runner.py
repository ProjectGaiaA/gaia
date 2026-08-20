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


# --- Dead retailer detection (2 consecutive zero-product runs) ---

from scrapers.runner import find_dead_retailers  # noqa: E402


def _zero_entry(retailer_id: str, expected: int = 7, found: int = 0) -> dict:
    return {
        "retailer_id": retailer_id,
        "status": "completed",
        "products_expected": expected,
        "products_found": found,
    }


def test_dead_after_two_consecutive_zero_runs():
    """Zero this run AND zero in the previous manifest -> dead."""
    prev = {"retailers": [_zero_entry("great-garden-plants")]}
    dead = find_dead_retailers([_zero_entry("great-garden-plants")], prev)
    assert dead == ["great-garden-plants"]


def test_single_zero_run_is_flaky_not_dead():
    """Stark Bros style all-or-nothing miss: previous run was fine."""
    prev = {"retailers": [_zero_entry("stark-bros", found=7)]}
    dead = find_dead_retailers([_zero_entry("stark-bros")], prev)
    assert dead == []


def test_first_ever_run_zero_is_not_dead():
    """No previous manifest entry: cannot be 'consecutive' yet."""
    dead = find_dead_retailers([_zero_entry("new-retailer")], {})
    assert dead == []


def test_healthy_run_never_dead():
    prev = {"retailers": [_zero_entry("nature-hills")]}
    dead = find_dead_retailers([_zero_entry("nature-hills", found=7)], prev)
    assert dead == []


def test_skipped_entries_ignored():
    prev = {"retailers": [_zero_entry("brecks")]}
    entries = [{"retailer_id": "brecks", "status": "skipped", "products_expected": 0}]
    assert find_dead_retailers(entries, prev) == []


def test_a_flagged_price_is_still_written(tmp_data_dir, monkeypatch):
    """A large price move must be RECORDED and flagged, never discarded.

    Drives the REAL scrape_retailer() with a stubbed scraper, then asserts the
    row landed on disk. The first version of this test hand-built the row dict
    and asserted append_price returned it — circular, and it passed with the
    old discard-on-anomaly guard fully restored, which is exactly the class of
    worthless test PRICE_AND_STOCK_AUDIT.md warns about.

    Why it matters: runner.py used to wrap the write in
    `if not anomaly_warnings:`, so a product that moved past the threshold was
    dropped and the site kept the old value. When the old value is the wrong
    one that freezes the defect permanently — every later run compares against
    the same stale number and raises the same anomaly. Measured on
    fastgrowingtrees.com's Delaware Valley White Azalea 3 gallon: the
    size->price bug entered as a 49% drop (under the 50% threshold) and the
    114% correction was refused for eight consecutive scrapes.
    """
    from scrapers import runner as runner_mod

    class _StubScraper:
        def __init__(self, retailer_id, url):
            pass

        def scrape_products(self, handles, plant_ids=None):
            return [{
                "retailer_name": "Fast Growing Trees",
                "timestamp": "2026-08-12T16:00:00+00:00",
                "url": "https://example.com/products/azalea",
                "sizes": {"3gal": {"price": 46.95, "available": True}},
                "in_stock": True,
            }]

    prices_dir = tmp_data_dir / "prices"
    monkeypatch.setattr(runner_mod, "ShopifyScraper", _StubScraper)
    monkeypatch.setattr(runner_mod, "PRICES_DIR", prices_dir)
    monkeypatch.setattr(runner_mod, "get_handles_for_retailer",
                        lambda rid, plant_ids: {"azalea": "azalea-handle"})

    retailer = {"id": "fast-growing-trees", "name": "Fast Growing Trees",
                "url": "https://example.com", "scraper_type": "shopify"}
    # Baseline 21.95 -> 46.95 is +114%, well past the 50% anomaly threshold.
    prev_manifest = {"prices": {"azalea:fast-growing-trees": {"3gal": 21.95}}}

    entry = runner_mod.scrape_retailer(retailer, ["azalea"], prev_manifest)

    assert entry["anomalies"], "a 114% rise should have been flagged"

    written = prices_dir / "azalea.jsonl"
    assert written.exists(), "the flagged row was discarded instead of written"
    row = json.loads(written.read_text(encoding="utf-8").strip())
    assert row["sizes"]["3gal"]["price"] == 46.95, "the correction was lost"
    assert row["price_anomaly"], "the row should carry its flag for review"


# --- Health must not be satisfiable by the failure mode (plan rule R5) ------

def test_hit_rate_excludes_products_with_no_readable_sizes():
    """A product published with no readable sizes is not a successful read.

    Counting it let a completely broken retailer report perfect health:
    driving all 68 FGT products through a drifted-and-sold-out page produced
    products_found=68, prices_collected=0, hit_rate 100%, health "healthy".
    Review found two mutants reverting this that survived all 474 tests,
    because the logic was inline in run() and unreachable from a test.
    """
    from scrapers.runner import retailer_hit_rate

    broken = {"products_expected": 68, "products_found": 68,
              "products_no_sizes": 68, "products_priced": 0}
    found, expected, rate = retailer_hit_rate(broken)
    assert found == 0, "a page we cannot read is not a hit"
    assert rate == 0.0 and rate < 0.8, "a fully unreadable retailer must be degraded"


def test_hit_rate_counts_genuinely_priced_products():
    from scrapers.runner import retailer_hit_rate

    healthy = {"products_expected": 68, "products_found": 68,
               "products_no_sizes": 0, "products_priced": 68}
    found, _, rate = retailer_hit_rate(healthy)
    assert found == 68 and rate == 1.0


def test_hit_rate_partial_break_is_caught():
    """Half the catalogue unreadable must degrade, not average out to fine."""
    from scrapers.runner import retailer_hit_rate

    half = {"products_expected": 68, "products_found": 68,
            "products_no_sizes": 34, "products_priced": 34}
    _, _, rate = retailer_hit_rate(half)
    assert rate < 0.8, f"50% unreadable scored {rate:.0%} — should be degraded"


def test_hit_rate_falls_back_for_older_manifest_entries():
    """Entries written before products_priced existed, and stark-bros (which
    only ever appends products that produced a price), must still work."""
    from scrapers.runner import retailer_hit_rate

    legacy = {"products_expected": 10, "products_found": 9}
    found, _, rate = retailer_hit_rate(legacy)
    assert found == 9 and rate == 0.9


def test_scrape_retailer_computes_products_priced_from_results(tmp_data_dir, monkeypatch):
    """The COMPUTATION of products_priced, not just its use.

    A previous version of these tests built the manifest entry by hand, so a
    mutant replacing `products_priced = products_found - products_no_sizes`
    with `= products_found` survived the whole suite. This drives the real
    scrape_retailer with a scraper returning a mix of readable and
    unreadable-but-published products.
    """
    from scrapers import runner as runner_mod

    class _MixedScraper:
        def __init__(self, retailer_id, url):
            pass

        def scrape_products(self, handles, plant_ids=None):
            out = []
            for i, _ in enumerate(handles):
                if i < 2:                      # readable: a real price
                    out.append({
                        "retailer_name": "R", "timestamp": "2026-08-12T16:00:00+00:00",
                        "url": "https://example.com/p",
                        "sizes": {"1gal": {"price": 19.99, "available": True}},
                        "in_stock": True,
                    })
                else:                          # published, but no readable size
                    out.append({
                        "retailer_name": "R", "timestamp": "2026-08-12T16:00:00+00:00",
                        "url": "https://example.com/p",
                        "sizes": {}, "in_stock": False, "no_sizes_readable": True,
                    })
            return out

    handles = {f"plant{i}": f"h{i}" for i in range(5)}
    monkeypatch.setattr(runner_mod, "ShopifyScraper", _MixedScraper)
    monkeypatch.setattr(runner_mod, "PRICES_DIR", tmp_data_dir / "prices")
    monkeypatch.setattr(runner_mod, "get_handles_for_retailer",
                        lambda rid, pids: handles)

    entry = runner_mod.scrape_retailer(
        {"id": "r", "name": "R", "url": "https://e.com", "scraper_type": "shopify"},
        list(handles), {"prices": {}},
    )

    assert entry["products_found"] == 5, "all five were published"
    assert entry["products_no_sizes"] == 3
    assert entry["products_priced"] == 2, (
        "products_priced must exclude published-but-unreadable rows; got "
        f"{entry['products_priced']}"
    )
    _, _, rate = runner_mod.retailer_hit_rate(entry)
    assert rate < 0.8, "3 of 5 unreadable must degrade the retailer"


def test_bundle_only_rows_reach_the_history_labelled(tmp_data_dir, monkeypatch):
    """The empty row a fully-bundled page produces must be WRITTEN, and must
    carry why it is empty.

    Written, because build.py takes the newest row per (plant, retailer): a row
    is the only thing that can withdraw a previously published price. Labelled,
    because the history otherwise holds two empty rows of identical shape —
    "every size sold out" and "every size is a two-for-one" — and no reader can
    tell them apart, which is the confusion this row exists to end.
    """
    from scrapers import runner as runner_mod

    class _BundleScraper:
        def __init__(self, retailer_id, url):
            pass

        def scrape_products(self, handles, plant_ids=None):
            return [{
                "retailer_name": "R", "timestamp": "2026-08-14T16:00:00+00:00",
                "url": "https://example.com/p", "sizes": {}, "in_stock": None,
                "no_sizes_readable": True, "all_offers_bundled": True,
            } for _ in handles]

    handles = {"bloodgood-japanese-maple": "bloodgood-japanese-maple"}
    monkeypatch.setattr(runner_mod, "ShopifyScraper", _BundleScraper)
    monkeypatch.setattr(runner_mod, "PRICES_DIR", tmp_data_dir / "prices")
    monkeypatch.setattr(runner_mod, "get_handles_for_retailer",
                        lambda rid, pids: handles)

    entry = runner_mod.scrape_retailer(
        {"id": "r", "name": "R", "url": "https://e.com", "scraper_type": "shopify"},
        list(handles), {"prices": {}},
    )
    assert entry["products_priced"] == 0, "an all-bundle row is not a price read"

    path = tmp_data_dir / "prices" / "bloodgood-japanese-maple.jsonl"
    rows = [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(rows) == 1, "no row was appended; the stale price would survive"
    assert rows[0]["sizes"] == {}
    assert rows[0]["in_stock"] is None
    assert rows[0]["all_offers_bundled"] is True


def _regional_run(tmp_data_dir, monkeypatch, results, handles):
    """Drive the REAL scrape_retailer() over stubbed scraper results."""
    from scrapers import runner as runner_mod

    class _Stub:
        def __init__(self, retailer_id, url):
            pass

        def scrape_products(self, hs, plant_ids=None):
            return results

    monkeypatch.setattr(runner_mod, "ShopifyScraper", _Stub)
    monkeypatch.setattr(runner_mod, "PRICES_DIR", tmp_data_dir / "prices")
    monkeypatch.setattr(runner_mod, "get_handles_for_retailer",
                        lambda rid, pids: handles)
    return runner_mod.scrape_retailer(
        {"id": "fast-growing-trees", "name": "FGT",
         "url": "https://e.com", "scraper_type": "shopify"},
        list(handles), {"prices": {}},
    )


def _row(**over):
    base = {
        "retailer_name": "FGT", "timestamp": "2026-08-20T12:25:00+00:00",
        "url": "https://example.com/p", "sizes": {}, "in_stock": None,
    }
    base.update(over)
    return base


def test_regional_render_key_survives_the_price_entry_whitelist(
    tmp_data_dir, monkeypatch,
):
    """The row written to data/prices must say WHY it is empty.

    scrape_retailer builds `price_entry` as an EXPLICIT WHITELIST — it copies
    named keys off the scraper's result and drops everything else. A key the
    scraper sets and that block does not name never reaches the corpus, so the
    provenance would be lost between the scraper and the history and
    scripts/audit_regional_render.py would have nothing to replay.

    Three causes now produce `sizes: {}` — sold out, all-bundled, and
    regional. Without this key the first and third are indistinguishable in
    the history.
    """
    handles = {"honeycrisp-apple-tree": "honeycrisp-apple-tree"}
    entry = _regional_run(
        tmp_data_dir, monkeypatch,
        [_row(no_sizes_readable=True, regional_render=True)], handles,
    )

    path = tmp_data_dir / "prices" / "honeycrisp-apple-tree.jsonl"
    rows = [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(rows) == 1, "no row appended; the stale regional price survives"
    assert rows[0]["sizes"] == {}
    assert rows[0]["in_stock"] is None
    assert rows[0]["regional_render"] is True
    assert rows[0].get("all_offers_bundled") is None, (
        "a regional row must not borrow the bundle cause"
    )
    assert entry["products_priced"] == 0, "a regional row is not a price read"


def test_manifest_counts_regional_renders_separately(tmp_data_dir, monkeypatch):
    """products_regional names the CAUSE of a degraded run.

    It is a BREAKDOWN of products_no_sizes, not a replacement: a regional row
    is one kind of no-sizes row, so it stays inside that count and stays
    subtracted from products_priced. Without the breakdown a flip run and a
    broken parser produce byte-identical manifests.
    """
    handles = {f"p{i}": f"h{i}" for i in range(5)}
    results = [
        _row(sizes={"1gal": {"price": 10.0}}),                     # priced
        _row(sizes={"2gal": {"price": 20.0}}),                     # priced
        _row(no_sizes_readable=True),                              # sold out
        _row(no_sizes_readable=True, regional_render=True),        # regional
        _row(no_sizes_readable=True, regional_render=True),        # regional
    ]
    entry = _regional_run(tmp_data_dir, monkeypatch, results, handles)

    assert entry["products_found"] == 5
    assert entry["products_no_sizes"] == 3
    assert entry["products_regional"] == 2
    assert entry["products_priced"] == 2, (
        "regional rows must be subtracted from the health input, not exempted"
    )


def test_regional_withhold_is_allowed_to_degrade_the_retailer(
    tmp_data_dir, monkeypatch,
):
    """THE HEALTH DECISION, PINNED. No floor adjustment, no exemption.

    On a flip run the retailer genuinely gave us nothing publishable as a
    national price, so a hit rate that still says "healthy" is exactly the lie
    products_priced was introduced to stop telling. The ONLY thing added is
    the count that names the cause.

    Sized to the measured 2026-08-20 flip: FGT expected 68, priced 56
    (0.82, healthy). Withholding the 5 regional products gives 51/68 = 0.75,
    which is below the 0.8 floor — degraded, and correctly so.
    """
    from scrapers import runner as runner_mod

    handles = {f"p{i}": f"h{i}" for i in range(68)}
    results = (
        [_row(sizes={"1gal": {"price": 10.0}}) for _ in range(51)]
        + [_row(no_sizes_readable=True, regional_render=True) for _ in range(5)]
        + [_row(no_sizes_readable=True) for _ in range(8)]
        + [{"error": "not found"} for _ in range(4)]
    )
    entry = _regional_run(tmp_data_dir, monkeypatch, results, handles)

    assert entry["products_priced"] == 51
    assert entry["products_regional"] == 5
    _, _, rate = runner_mod.retailer_hit_rate(entry)
    assert rate < 0.8, (
        f"a flip run must be allowed to degrade the retailer; got {rate:.4f}"
    )
    # And the count is what lets a reader tell this apart from a parser break.
    assert entry["products_regional"] > 0


def test_manifest_merge_carries_the_regional_count(tmp_data_dir, monkeypatch):
    """The count has to survive into data/last_manifest.json, not just the
    return value — CI merges per-retailer runs through merge_manifest()."""
    from scrapers import runner as runner_mod

    handles = {"honeycrisp-apple-tree": "honeycrisp-apple-tree"}
    entry = _regional_run(
        tmp_data_dir, monkeypatch,
        [_row(no_sizes_readable=True, regional_render=True)], handles,
    )
    merged = runner_mod.merge_manifest({"retailers": [], "prices": {}}, [entry])
    fgt = [
        e for e in merged["retailers"]
        if e["retailer_id"] == "fast-growing-trees"
    ]
    assert len(fgt) == 1
    assert fgt[0]["products_regional"] == 1
