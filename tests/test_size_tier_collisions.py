"""A size tier is a claim that two rows are the SAME PRODUCT at the SAME SIZE.

These tests lock down the day that claim was false on the live site.

The site owner spotted it by eye: plantpricetracker.com showed PlantingTree's
Nellie Stevens Holly "Quart" as $13.95 SOLD OUT. PlantingTree's own
/products/nellie-stevens-holly.js listed twelve variants, among them

    "1 Quart"  $21.95  available   <- dropped
    "2 Quart"  $13.95  sold out    <- published, as `quart`

Both titles normalised to `quart`, the tier write was last-write-wins, and the
later variant took the column. The published price was not merely stale; it was
a different product's price, and the one a visitor could actually pay was never
published at all.

Everything here runs offline against committed fixtures.
"""

import json
import logging

import pytest
import responses

from tests.conftest import load_fixture
from scrapers.shopify import ShopifyScraper, _record_size

PT = "https://www.plantingtree.com"
FGT = "https://www.fgt.com"


def _scrape_planting_tree(handle="nellie-stevens-holly"):
    """Wire both live endpoints: .json carries prices, .js carries stock."""
    responses.add(
        responses.GET, f"{PT}/products/{handle}.json",
        json=load_fixture("planting-tree", "nellie-stevens-holly-product.json"),
        status=200,
    )
    responses.add(
        responses.GET, f"{PT}/products/{handle}.js",
        json=load_fixture("planting-tree", "nellie-stevens-holly-availability.json"),
        status=200,
    )
    return ShopifyScraper("planting-tree", PT).scrape_product(handle)


# --- The reported defect ----------------------------------------------------


@responses.activate
def test_nellie_quart_publishes_the_live_price_not_the_sold_out_one(no_sleep):
    """THE bug, on the real 12-variant payload.

    Pre-fix this asserts $13.95/sold out, because "2 Quart" overwrote
    "1 Quart". Verified against c9b30b78: `sizes["quart"]` was
    {'price': 13.95, 'available': False, 'raw_size': '2 Quart'} and there was
    no `2quart` key at all.
    """
    result = _scrape_planting_tree()

    quart = result["sizes"]["quart"]
    assert quart["price"] == 21.95
    assert quart["available"] is True
    assert quart["raw_size"] == "1 Quart"

    # The 2-quart pot is a real product and is still published — under its own
    # label, with its own true stock. Nothing is thrown away, only re-labelled.
    two = result["sizes"]["2quart"]
    assert two["price"] == 13.95
    assert two["available"] is False
    assert two["raw_size"] == "2 Quart"

    # ...and no tier was lost in the process: 12 variants, 12 tiers.
    assert len(result["sizes"]) == 12
    assert result["size_collisions"] == 0


@responses.activate
def test_nellie_every_other_size_is_untouched(no_sleep):
    """The split must not disturb the eleven variants that were already right."""
    result = _scrape_planting_tree()
    expected = {
        "1gal": (20.95, True), "3gal": (38.95, False), "5gal": (80.95, True),
        "7gal": (124.95, True), "1-2ft": (36.95, False), "2-3ft": (84.95, False),
        "3-4ft": (99.95, False), "4-5ft": (104.95, False), "5-6ft": (204.95, False),
        "6-7ft": (224.95, False),
    }
    for tier, (price, available) in expected.items():
        assert result["sizes"][tier]["price"] == price, tier
        assert result["sizes"][tier]["available"] is available, tier


# --- The 3.37x case: FGT crape myrtle --------------------------------------


def _scrape_fgt(handle, fixture):
    responses.add(responses.GET, f"{FGT}/products/{handle}.json", status=404)
    responses.add(
        responses.GET, f"{FGT}/products/{handle}",
        body=load_fixture("fgt", fixture), status=200,
    )
    return ShopifyScraper("fast-growing-trees", FGT).scrape_product(handle)


@responses.activate
def test_crape_myrtle_multistem_does_not_wear_the_single_stem_label(no_sleep):
    """FGT sells Multi-stem and Single-stem crape myrtle on ONE page.

    Pre-fix, two things happened at once and both were wrong:
      * every "... Single-stem" button was DISCARDED, because
        _is_quantity_label matched the bare substring "single" (which exists
        to drop the Single/10-Pack quantity buttons); and
      * every "... Multi-stem" button was published under the PLAIN height
        tier, so `4-5ft` carried the multi-stem price.

    The live corpus shows the result: crape-myrtle's 4-5ft row alternated
    between $193.95 and $653.95 — a 3.37x swing with no price change behind
    it, just a different label winning.
    """
    result = _scrape_fgt("natchez-crape-myrtle", "crape-myrtle-multistem-page.html")
    sizes = result["sizes"]

    # Multi-stem gets its own column...
    assert sizes["4-5ft-multistem"]["price"] == 149.95
    assert sizes["4-5ft-multistem"]["raw_size"] == "4-5 feet Multi-stem"
    assert sizes["6-7ft-multistem"]["price"] == 214.95
    assert sizes["6-7ft-multistem"]["raw_size"] == "6-7 feet Multi-stem"

    # ...and it is NOT published as the plain height, which is what a visitor
    # compares against other nurseries' plain "4-5 Feet".
    assert "4-5ft" not in sizes
    assert "6-7ft" not in sizes

    # Single-stem is the ordinary form and keeps the plain tier, so the
    # comparison against other retailers survives instead of vanishing.
    assert sizes["1-2ft"]["price"] == 19.95
    assert sizes["1-2ft"]["raw_size"] == "1-2 feet Single-stem"
    assert sizes["5-6ft"]["price"] == 775.95
    assert sizes["5-6ft"]["raw_size"] == "5-6 feet Single-stem"

    # 13 buttons on the page, 13 tiers out. Nothing dropped, nothing merged.
    assert len(sizes) == 13
    assert result["size_collisions"] == 0


@responses.activate
def test_crape_myrtle_quart_sizes_do_not_merge(no_sleep):
    """Same page, same defect in the quart dimension: "1 quart Multi-stem" at
    $108.95 and "2 quart Multi-stem" at $177.95 both reached `quart`."""
    sizes = _scrape_fgt("natchez-crape-myrtle", "crape-myrtle-multistem-page.html")["sizes"]
    assert sizes["quart-multistem"]["price"] == 108.95
    assert sizes["2quart-multistem"]["price"] == 177.95


# --- The normaliser, unit level --------------------------------------------


@pytest.mark.parametrize("raw,tier", [
    # Quantity-bearing quart. "1 Quart" IS a quart and keeps the shared tier so
    # Nature Hills' "Quart Container" and GGP's "One Quart" still compare.
    ("1 Quart", "quart"),
    ("Quart", "quart"),
    ("One Quart", "quart"),
    ("Quart Container", "quart"),
    ("4.5\" Quart / Ships Now", "quart"),
    ("2 Quart", "2quart"),
    ("3 Quart", "3quart"),
    ("2 quart Multi-stem", "2quart-multistem"),
    # Form qualifier, following the -jumbo precedent.
    ("4-5 feet Multi-stem", "4-5ft-multistem"),
    ("#3 Container 3-4 Feet Multi Stem", "3gal-multistem"),
    ("1 gallon Multi-stem", "1gal-multistem"),
    ("4-5 feet Single-stem", "4-5ft"),
    ("6-7 feet Jumbo", "6-7ft-jumbo"),
    # Promotional prefix is not a size. The first two already tiered correctly
    # by accident — the height/quart pattern matches whatever precedes it — so
    # the third is the one that can actually fail: an unrecognised size falls
    # through to the Step 9 fallback, which turns the whole title into the tier
    # and would open a "Flash-Sale-Starter-Plug" column beside "Starter-Plug".
    ("Flash Sale - 1-2 feet", "1-2ft"),
    ("Flash Sale - 1 quart", "quart"),
    ("Flash Sale - Starter Plug", "starter-plug"),
    # Dormant/bare-root dimensions must not collapse together.
    ("DORMANT 2.5\" POT / 1 Plant(s) | Ships in Spring", "2-5inch-bareroot"),
    ("DORMANT 3\" / 1 Plant(s) | Ships in Spring", "3inch-bareroot"),
    ("DORMANT 12-18\" / 1 Plant(s) | Ships in Spring", "12-18in-bareroot"),
    ("DORMANT 48-54\" / 1 Plant(s) | Ships in Spring", "48-54in-bareroot"),
    ("12-18 IN BAREROOT / 1 Plant(s) | Ships in Spring", "12-18in-bareroot"),
    ("#1 BAREROOT / 1 Plant(s) | Ships in Spring", "bareroot"),
    # ...while the graded bare-root tiers keep theirs. Checked because the
    # bare-root branch runs AFTER these and would otherwise swallow them.
    ("JUMBO BAREROOT / 1 Plant(s) | Ships in Spring", "jumbo-bareroot"),
    ("PREMIUM / 1 Plant(s) | Ships in Spring", "premium-bareroot"),
    # Unchanged behaviour that the deleted dead patterns used to "handle".
    ("3 Gallon Pot", "3gal"),
    ("3 gallon pot / 1 Plant(s)", "3gal"),
])
def test_normalize_size(raw, tier):
    assert ShopifyScraper("x", "http://x")._normalize_size(raw) == tier


@pytest.mark.parametrize("label,is_quantity", [
    # Quantity buttons FGT renders next to the size buttons, in the same
    # aria-label format. A pack price is not a per-plant price.
    ("Single", True),
    ("10-Pack", True),
    ("6 Plants ( 4 Inch Pot)", True),
    ("4 Plants", True),
    # ...but "Single-stem" is a FORM. Matching bare "single" discarded every
    # Single-stem size FGT lists, which left the Multi-stem price alone on the
    # plain height tier.
    ("1-2 feet Single-stem", False),
    ("2-3 feet Single-Stem", False),
    ("6-7 ft. Single Stem", False),
    ("Single Stem Tree / #1 Container | 2-4 ft", False),
    # Spring Hill writes "1 Plant(s)" on every variant it sells; that is one
    # plant, i.e. a size, and must not be read as a pack.
    ("1 GALLON / 1 Plant(s) | Ships in Spring", False),
    ("1 quart", False),
])
def test_is_quantity_label(label, is_quantity):
    assert ShopifyScraper("x", "http://x")._is_quantity_label(label) is is_quantity


def test_deleted_patterns_were_unreachable_on_the_whole_corpus():
    """The two shadowed patterns removed from the gallon table —
    (r'3\\s*gallon\\s*pot', '3gal') and (r'one\\s+quart', 'quart') — were dead
    code: an earlier alternative matched the same strings, to the same tier.

    Proved rather than asserted: every distinct raw_size the corpus has ever
    carried is re-checked against a table with the two entries restored. R10 —
    the denominator is printed by the assertion message.
    """
    import os
    import re

    scraper = ShopifyScraper("x", "http://x")
    prices_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prices"
    )
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

    assert len(raws) > 150, f"corpus too small to prove anything: {len(raws)} raws"
    shadowed = [(re.compile(r'3\s*gallon\s*pot'), '3gal'), (re.compile(r'one\s+quart'), 'quart')]
    # A restored pattern could only change an answer for a raw it matches.
    hits = [r for r in raws if any(p.search(r.lower()) for p, _ in shadowed)]
    for raw in hits:
        for pattern, tier in shadowed:
            if pattern.search(raw.lower()):
                assert scraper._normalize_size(raw) == tier, (
                    f"{raw!r} would have differed; {len(hits)} of {len(raws)} raws checked"
                )


# --- The collision guard ----------------------------------------------------


def test_record_size_quarantines_a_genuine_clash(caplog):
    sizes, quarantined, collisions = {}, set(), []
    args = dict(retailer_id="r", handle="h", collisions=collisions)
    _record_size(sizes, quarantined, "quart",
                 {"price": 21.95, "available": True, "raw_size": "A"}, **args)
    with caplog.at_level(logging.ERROR, logger="scrapers.shopify"):
        _record_size(sizes, quarantined, "quart",
                     {"price": 13.95, "available": False, "raw_size": "B"}, **args)

    assert "quart" not in sizes, "an arbitrary winner is exactly the defect"
    assert collisions == [("quart", "B", 13.95)]
    assert "claimed by two different products" in caplog.text


def test_record_size_poisons_the_tier_against_a_third_claimant():
    """Once quarantined, a tier stays withheld — otherwise a third variant
    would simply re-take the column the first two were denied."""
    sizes, quarantined, collisions = {}, set(), []
    args = dict(retailer_id="r", handle="h", collisions=collisions)
    for price in (21.95, 13.95, 99.95):
        _record_size(sizes, quarantined, "quart",
                     {"price": price, "available": True, "raw_size": str(price)}, **args)
    assert "quart" not in sizes
    assert len(collisions) == 2


def test_record_size_treats_an_identical_repeat_as_one_product():
    sizes, quarantined, collisions = {}, set(), []
    args = dict(retailer_id="r", handle="h", collisions=collisions)
    for _ in range(2):
        _record_size(sizes, quarantined, "quart",
                     {"price": 35.95, "available": True, "raw_size": "1 quart"}, **args)
    assert sizes["quart"]["price"] == 35.95
    assert collisions == []


def test_record_size_treats_a_price_only_difference_as_a_clash():
    """Same label, same stock, different price is still two answers to one
    question. dwarf-cavendish-banana renders "1 quart" twice, at $25.95 and
    $44.95; there is no rule that says which one a visitor gets."""
    sizes, quarantined, collisions = {}, set(), []
    args = dict(retailer_id="r", handle="h", collisions=collisions)
    _record_size(sizes, quarantined, "quart",
                 {"price": 25.95, "available": True, "raw_size": "1 quart"}, **args)
    _record_size(sizes, quarantined, "quart",
                 {"price": 44.95, "available": True, "raw_size": "1 quart"}, **args)
    assert "quart" not in sizes


def test_record_size_clash_costs_only_its_own_tier():
    sizes, quarantined, collisions = {}, set(), []
    args = dict(retailer_id="r", handle="h", collisions=collisions)
    _record_size(sizes, quarantined, "quart",
                 {"price": 1.0, "available": True, "raw_size": "A"}, **args)
    _record_size(sizes, quarantined, "quart",
                 {"price": 2.0, "available": True, "raw_size": "B"}, **args)
    _record_size(sizes, quarantined, "1gal",
                 {"price": 9.0, "available": True, "raw_size": "C"}, **args)
    assert sizes == {"1gal": {"price": 9.0, "available": True, "raw_size": "C"}}


@responses.activate
def test_json_path_quarantines_without_losing_the_product(no_sleep, caplog):
    """One unresolvable tier must not cost a whole product — the JSON path
    serves six retailers, and withholding the product would delete every other
    size it lists."""
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "1 Gallon", "price": "10.00", "compare_at_price": None},
            {"id": 2, "title": "1 Gal", "price": "99.00", "compare_at_price": None},
            {"id": 3, "title": "3 Gallon", "price": "30.00", "compare_at_price": None},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    with caplog.at_level(logging.ERROR, logger="scrapers.shopify"):
        result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert "1gal" not in result["sizes"]
    assert result["sizes"]["3gal"]["price"] == 30.0
    assert result["size_collisions"] == 1
    assert "claimed by two different products" in caplog.text
    # A collision alongside surviving prices is NOT a failed price read. Gating
    # the flag on the collision alone would mark this product unreadable while
    # it publishes a perfectly good 3gal price, and two retailers have less
    # than three products of headroom before that drops them under the 80%
    # health line. Review found this mutant alive: every other assertion here
    # passes with the gate widened to `if collisions:`.
    assert "no_sizes_readable" not in result


# --- Quarantine must not leak into the claims made ABOUT the tiers it kept ---
#
# Both of these were found by an independent review of the collision fix, not
# by the tests above, which asserted only on `sizes`. Quarantine removes a
# tier; it does not by itself remove that tier's influence on the row-level
# facts computed alongside it. Two of those facts were still being computed
# from the withheld variants.


@responses.activate
def test_stock_flag_ignores_variants_that_were_withheld(no_sleep):
    """A withheld variant must not vote on whether the row is in stock.

    The colliding pair is IN STOCK and is withheld. The only tier that
    survives to the page is SOLD OUT. Computing `in_stock` from the variants
    as they were read prints "In Stock" above the sold-out price — a claim
    backed by nothing the visitor can see or buy, which is the same class of
    error as publishing the wrong price under a size label.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "3 Gallon", "price": "10.00", "available": True},
            {"id": 2, "title": "3 Gallon Premium", "price": "20.00", "available": True},
            {"id": 3, "title": "1 Gallon", "price": "50.00", "available": False},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert result["size_collisions"] == 1
    assert sorted(result["sizes"]) == ["1gal"], "the in-stock pair must be withheld"
    assert result["in_stock"] is False, (
        "in_stock was computed from a variant that never reached the page"
    )


@responses.activate
def test_all_tiers_withheld_is_not_a_successful_price_read(no_sleep):
    """Every tier quarantined leaves an empty but freshly-timestamped row.

    runner.py counts that row as a product found and scores the retailer
    healthy, so a retailer publishing not one readable price can report a
    100% hit rate — defect F1, reached here by a new route the collision fix
    opened. The FGT HTML path already refuses to publish in this state; the
    JSON path keeps the row (the product does exist) but must flag it so the
    health metric cannot be satisfied by the failure mode.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "3 Gallon", "price": "10.00", "available": True},
            {"id": 2, "title": "3 Gallon Premium", "price": "20.00", "available": True},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert result["sizes"] == {}
    assert result["size_collisions"] == 1
    assert result.get("no_sizes_readable") is True


@responses.activate
def test_priceless_product_is_not_reported_as_unreadable(no_sleep):
    """`no_sizes_readable` is gated on a collision, not on emptiness.

    A product whose variants are all multi-plant packs has no sizes either,
    but nothing was withheld and nothing is unattributable. That is a
    different fact with its own handling, and conflating the two would put
    the flag on rows where no price was ever lost.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "3 Plant(s)", "price": "10.00", "available": True},
            {"id": 2, "title": "10-Pack", "price": "20.00", "available": True},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert result["sizes"] == {}
    assert result["size_collisions"] == 0
    assert "no_sizes_readable" not in result


@responses.activate
def test_all_null_availability_still_reads_unknown_not_sold_out(no_sleep):
    """Nature Hills returns null for in-stock AND sold-out products alike.

    Rewriting the aggregation must not turn "we don't know" into "sold out";
    the row shows a dash, and a dash is the honest answer.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "1 Gallon", "price": "10.00"},
            {"id": 2, "title": "3 Gallon", "price": "30.00"},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert sorted(result["sizes"]) == ["1gal", "3gal"]
    assert result["in_stock"] is None


@responses.activate
def test_non_boolean_availability_is_not_read_as_in_stock(no_sleep):
    """`available` must be a bool to vote. A string is not an answer.

    The aggregation asks `isinstance(v, bool)` rather than testing truthiness,
    and the difference is not academic: the string "false" is truthy in
    Python, so dropping the guard turns a sold-out variant into an In Stock
    badge. Neither live endpoint sends a string today -- `.json` omits the
    field and the `.js` lookup is itself isinstance-guarded -- which is
    exactly why this needs a test: review found the guard could be deleted
    with all 644 other tests still passing.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "1 Gallon", "price": "10.00", "available": "false"},
            {"id": 2, "title": "3 Gallon", "price": "30.00", "available": "false"},
        ],
    }}
    responses.add(responses.GET, f"{PT}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{PT}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("planting-tree", PT).scrape_product("h")

    assert sorted(result["sizes"]) == ["1gal", "3gal"]
    assert result["in_stock"] is None, "a string must not be counted as stock"
