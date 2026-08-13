"""The scraper fix alone changes nothing a visitor sees.

`data/prices/*.jsonl` is append-only and every row carries the tier key that was
computed when it was written, so the LATEST row — the only one build.py renders
— keeps publishing the old claim until it is repaired or overwritten. A retailer
that drops a product never overwrites anything, so "wait for the next scrape" is
not a plan.

scripts/purge_colliding_sizes.py re-keys those rows from their own raw_size.
"""

import json
import os

from scripts.purge_colliding_sizes import repair_row, shopify_retailer_ids
from scrapers.shopify import ShopifyScraper

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORMALIZE = ShopifyScraper("x", "http://x")._normalize_size
SHOPIFY = {"planting-tree", "fast-growing-trees"}


def test_the_reported_row_is_repaired():
    """The exact shape of the live row that produced the complaint."""
    row = {"retailer_id": "planting-tree", "sizes": {
        "quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
        "1gal": {"price": 20.95, "available": True, "raw_size": "1 Gallon"},
    }}
    sizes, moved, dropped = repair_row(row, NORMALIZE, SHOPIFY)
    assert "quart" not in sizes, "the sold-out 2-quart must stop wearing the quart label"
    assert sizes["2quart"]["price"] == 13.95
    assert sizes["1gal"]["price"] == 20.95
    assert (moved, dropped) == (1, 0)


def test_nothing_is_invented_only_re_keyed():
    row = {"retailer_id": "planting-tree", "sizes": {
        "quart": {"price": 13.95, "was_price": None, "available": False,
                  "raw_size": "2 Quart", "variant_id": 41604617207855},
    }}
    sizes, _, _ = repair_row(row, NORMALIZE, SHOPIFY)
    assert sizes["2quart"] == row["sizes"]["quart"]


def test_custom_scraper_rows_are_left_alone():
    """Stark Bros has its own normaliser; _normalize_size mis-keys its titles
    ("Bartlett Pear Semi-Dwarf Supreme XL Potted" -> `supreme`, not
    `semi-dwarf-potted`), so re-keying them would create the defect."""
    row = {"retailer_id": "stark-bros", "sizes": {
        "semi-dwarf-potted": {"price": 1.0, "available": True,
                              "raw_size": "Bartlett Pear Semi-Dwarf Supreme XL Potted"},
    }}
    sizes, moved, dropped = repair_row(row, NORMALIZE, SHOPIFY)
    assert sizes == row["sizes"]
    assert (moved, dropped) == (0, 0)


def test_a_cell_with_no_raw_size_keeps_its_key():
    """Older rows predate raw_size. Guessing a tier for them would be exactly
    the invention this change exists to remove."""
    row = {"retailer_id": "planting-tree", "sizes": {"quart": {"price": 9.0}}}
    sizes, moved, dropped = repair_row(row, NORMALIZE, SHOPIFY)
    assert sizes == {"quart": {"price": 9.0}}
    assert (moved, dropped) == (0, 0)


def test_a_collision_created_by_the_move_is_quarantined_not_won():
    row = {"retailer_id": "planting-tree", "sizes": {
        "quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
        "2quart": {"price": 99.0, "available": True, "raw_size": "2 Quart"},
    }}
    sizes, moved, dropped = repair_row(row, NORMALIZE, SHOPIFY)
    assert "2quart" not in sizes
    assert dropped == 2


def test_an_identical_duplicate_is_merged_not_quarantined():
    row = {"retailer_id": "planting-tree", "sizes": {
        "quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
        "2quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
    }}
    sizes, _, dropped = repair_row(row, NORMALIZE, SHOPIFY)
    assert sizes["2quart"]["price"] == 13.95
    assert dropped == 1


def test_repair_is_idempotent():
    row = {"retailer_id": "planting-tree", "sizes": {
        "quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
    }}
    once, _, _ = repair_row(row, NORMALIZE, SHOPIFY)
    twice, moved, dropped = repair_row({"retailer_id": "planting-tree", "sizes": once},
                                       NORMALIZE, SHOPIFY)
    assert twice == once
    assert (moved, dropped) == (0, 0)


def test_the_committed_corpus_carries_no_stale_tier_key():
    """The purge actually ran, and stays run.

    This is the check that fails if the data is reverted, if the normaliser
    drifts from the keys on disk, or if a future scrape writes a key its own
    raw_size does not support. R10: the denominator is in the message.
    """
    prices_dir = os.path.join(REPO, "data", "prices")
    shopify_ids = shopify_retailer_ids()
    scanned = 0
    stale = []
    for fn in sorted(os.listdir(prices_dir)):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(prices_dir, fn), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("retailer_id") not in shopify_ids:
                    continue
                for tier, cell in (row.get("sizes") or {}).items():
                    if not isinstance(cell, dict) or cell.get("raw_size") is None:
                        continue
                    scanned += 1
                    if NORMALIZE(cell["raw_size"]) != tier:
                        stale.append((fn, row.get("retailer_id"), tier, cell["raw_size"]))
    assert scanned > 100_000, f"scan found only {scanned} cells; it checked nothing"
    assert not stale, f"{len(stale)} of {scanned} cells carry a stale tier: {stale[:5]}"
