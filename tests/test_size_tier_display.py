"""Every tier the scraper can emit must reach a visitor with a readable label.

The failure this guards against is quiet: splitting a tier in the scraper and
forgetting the display layer leaves a column headed `4-5ft-multistem`, or a
mobile card whose label is the tier id, or a price that renders but cannot be
told apart from the one next to it. "6-7ft-jumbo" needed a hand-written
SIZE_TIER_LABELS entry for exactly this reason; the suffix rules make the open
set of qualified tiers behave without one.
"""

import json
import os
import re
from datetime import datetime, timezone

import pytest

import build
from scrapers.shopify import ShopifyScraper

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _corpus_raws():
    """Every distinct raw_size the price history has ever carried."""
    prices_dir = os.path.join(REPO, "data", "prices")
    raws = set()
    for fn in os.listdir(prices_dir):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(prices_dir, fn), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                for cell in (json.loads(line).get("sizes") or {}).values():
                    if isinstance(cell, dict) and cell.get("raw_size") is not None:
                        raws.add(cell["raw_size"])
    return raws


@pytest.mark.parametrize("tier,label", [
    ("2quart", "2 Quart"),
    ("3quart", "3 Quart"),
    ("4-5ft-multistem", "4-5 ft Multi-Stem"),
    ("quart-multistem", "Quart Multi-Stem"),
    ("3gal-multistem", "3 Gallon Multi-Stem"),
    ("2-5inch-bareroot", '2.5" Bare Root'),
    ("3inch-bareroot", '3" Bare Root'),
    ("12-18in-bareroot", '12-18" Bare Root'),
    ("48-54in-bareroot", '48-54" Bare Root'),
    # Unchanged, and checked because the suffix rule runs near them.
    ("bareroot", "Bare Root"),
    ("jumbo-bareroot", "Jumbo Bare Root"),
    ("premium-bareroot", "Premium Bare Root"),
    ("semi-dwarf-bareroot", "Semi-Dwarf (Bare Root)"),
    ("6-7ft-jumbo", "6-7 ft Jumbo"),
    ("quart", "Quart"),
])
def test_get_size_label(tier, label):
    assert build.get_size_label(tier) == label


def test_every_tier_the_scraper_can_emit_has_a_readable_label():
    """Whole-corpus sweep. R10: the denominator is in the failure message."""
    scraper = ShopifyScraper("x", "http://x")
    raws = _corpus_raws()
    assert len(raws) > 150, f"corpus too small to prove anything: {len(raws)}"
    tiers = {scraper._normalize_size(r) for r in raws}
    bad = []
    for tier in sorted(tiers):
        label = build.get_size_label(tier)
        # A label that is still the tier id, or that runs a number straight
        # into a word ("2quart", "12 18In"), has not been translated.
        if label == tier and not re.fullmatch(r"[A-Z][a-z]+", label):
            bad.append((tier, label))
        elif re.search(r"multistem|bareroot", label, re.I):
            bad.append((tier, label))
    assert not bad, f"{len(bad)} of {len(tiers)} emitted tiers render unlabelled: {bad}"


def test_new_tiers_sort_next_to_the_size_they_qualify():
    """A qualified tier belongs beside its base, not alphabetically at the far
    right of the table where a visitor cannot see them together."""
    plant = {"id": "p", "common_name": "P", "category": "c"}
    retailers_by_id = {
        "r1": {"id": "r1", "name": "R1", "url": "http://r1", "affiliate": None},
    }
    latest = {"r1": {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sizes": {
            "6-7ft": {"price": 10.0, "available": True, "raw_size": "6-7 feet"},
            "quart": {"price": 1.0, "available": True, "raw_size": "1 quart"},
            "4-5ft-multistem": {"price": 20.0, "available": True, "raw_size": "4-5 feet Multi-stem"},
            "2quart": {"price": 2.0, "available": True, "raw_size": "2 Quart"},
            "4-5ft": {"price": 5.0, "available": True, "raw_size": "4-5 feet"},
            "12-18in-bareroot": {"price": 3.0, "available": True, "raw_size": 'DORMANT 12-18"'},
            "12-18in": {"price": 4.0, "available": True, "raw_size": 'FIELD 12-18"'},
        },
        "in_stock": True,
    }}
    table = build.build_price_table(plant, latest, retailers_by_id)
    order = table["active_size_tiers"]
    assert order.index("quart") < order.index("2quart") < order.index("4-5ft")
    assert order.index("4-5ft") + 1 == order.index("4-5ft-multistem")
    assert order.index("4-5ft-multistem") < order.index("6-7ft")
    assert order.index("12-18in") + 1 == order.index("12-18in-bareroot")
    # Nothing is dropped on the way through.
    assert len(order) == 7


def test_a_new_tier_actually_renders_in_the_product_table(tmp_path):
    """End to end through the real template: the column exists, is headed with
    a human label, and carries the price."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(os.path.join(REPO, "templates")))
    tmpl = env.get_template("product.html")
    plant = {
        "id": "p", "common_name": "Test Plant", "botanical_name": "T t",
        "category": "shrubs", "zones": [5], "sun": "Full", "mature_size": "x",
        "bloom_time": "x", "type": "Shrub", "description": "d",
    }
    retailers_by_id = {"r1": {"id": "r1", "name": "R1", "url": "http://r1", "affiliate": None}}
    latest = {"r1": {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sizes": {
            "quart": {"price": 21.95, "available": True, "raw_size": "1 Quart"},
            "2quart": {"price": 13.95, "available": False, "raw_size": "2 Quart"},
            "4-5ft-multistem": {"price": 653.95, "available": True, "raw_size": "4-5 feet Multi-stem"},
            "12-18in-bareroot": {"price": 17.49, "available": False, "raw_size": 'DORMANT 12-18"'},
        },
        "in_stock": True,
    }}
    table = build.build_price_table(plant, latest, retailers_by_id)
    html = tmpl.render(
        plant=plant, url="/plants/p.html", page_title="t", meta_description="d",
        canonical_url="http://x/p.html", **table,
    )

    for header in ("Quart", "2 Quart"):
        assert f"<th>{header}</th>" in html, header
    # P8: these two used to read "4-5ft-Multistem" and "12-18in-Bare Root" —
    # output of the ad-hoc replace chain that used to live in product.html.
    # The template now renders get_size_label() for every column, so the
    # header is the same string the mobile card and the pinned vocabulary in
    # test_size_label_vocabulary.py already used. The strings below are copied
    # from that hand-written table, not recomputed here.
    assert "<th>4-5 ft Multi-Stem</th>" in html
    assert '<th>12-18" Bare Root</th>' in html
    # The inch mark must survive into the mobile data-label as an ESCAPED
    # quote — raw, it would close the attribute and destroy the cell.
    assert 'data-label="12-18&#34; Bare Root"' in html
    assert 'data-label="12-18" Bare Root"' not in html
    # ...and no column is headed with a bare, untranslated tier id.
    assert "<th>2quart</th>" not in html
    # Both quart prices reach the page, each under its own column.
    assert "$21.95" in html and "$13.95" in html
