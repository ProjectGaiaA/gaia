"""R6 held for one retailer out of seven.

`7aca354f` states the guarantee: "a retailer that put its catalogue on BOGO
must not score a healthy hit rate while the site shows none of its prices".
It is true on the aria path — and only fast-growing-trees reaches the aria
path. The other six retailers (nature-hills, planting-tree, spring-hill,
proven-winners-direct, great-garden-plants, and FGT's own JSON fallback) come
through `_scrape_product_json`, where an all-bundle product returned:

    sizes: {}   in_stock: None   no_sizes_readable: <ABSENT>
                                 all_offers_bundled: <ABSENT>

because `no_sizes_readable` was gated on `if not sizes and collisions:` and
collisions is empty when every variant was withheld as a bundle. runner.py
computes `products_priced = products_found - products_no_sizes`, so the row
counted as a SUCCESSFUL PRICE READ. Six of seven retailers could empty their
entire column and still report a 100% hit rate.

The published prices were never wrong — the cells do clear correctly. What
was wrong is the health signal that is supposed to tell anyone it happened,
and the missing provenance that tells "every size sold out" apart from "every
size is a two-for-one" in the price history.

All HTTP is mocked. No live retailer is reached.
"""

import json
import logging

import responses

from scrapers.shopify import ShopifyScraper

SH = "https://www.springhillnursery.com"


def _variant(vid, title, price):
    return {"id": vid, "title": title, "price": price, "compare_at_price": None}


def _register(handle, variants, availability=None):
    responses.add(
        responses.GET, f"{SH}/products/{handle}.json",
        json={"product": {"id": 1, "title": "Limelight Hydrangea",
                          "handle": handle, "variants": variants}},
        status=200,
    )
    responses.add(responses.GET, f"{SH}/products/{handle}.js",
                  json={"variants": availability or []}, status=200)


def _scrape(handle, variants, retailer="spring-hill"):
    _register(handle, variants)
    return ShopifyScraper(retailer, SH).scrape_product(handle)


ALL_BUNDLE = [
    _variant(1, "3-4' BOGO", "119.99"),
    _variant(2, "5-6 FT - Buy 1, Get 1", "199.99"),
    _variant(3, "12-18 IN Buy One Get One Free", "49.99"),
]

MIXED = [
    _variant(9, "1 GALLON / 1 Plant(s)", "29.99"),
    *ALL_BUNDLE,
]


# --------------------------------------------------------------------------
# the row itself — unchanged behaviour, pinned so the fix cannot regress it
# --------------------------------------------------------------------------

@responses.activate
def test_an_all_bundle_product_still_publishes_an_empty_row(no_sleep):
    """A row is the only thing that withdraws a previously published price.
    Silence lets build.py's newest-row-wins keep serving the stale one."""
    result = _scrape("h", ALL_BUNDLE)
    assert result is not None
    assert result["sizes"] == {}


@responses.activate
def test_the_empty_row_makes_no_stock_claim(no_sleep):
    """NOT False — "Sold Out" is a false claim, the plant is on sale as a
    pair. NOT True — that renders "In Stock" beside a row of dashes."""
    assert _scrape("h", ALL_BUNDLE)["in_stock"] is None


@responses.activate
def test_the_empty_row_carries_no_bundle_price_and_no_halved_price(no_sleep):
    published = json.dumps(_scrape("h", ALL_BUNDLE))
    for price in ("119.99", "199.99", "49.99", "59.99", "99.99", "24.99"):
        assert price not in published, (
            f"{price} reached the row; a bundle price and half a bundle price "
            f"are both prices the retailer never listed")


# --------------------------------------------------------------------------
# F4 — the health signal
# --------------------------------------------------------------------------

@responses.activate
def test_an_all_bundle_product_does_not_score_as_a_successful_price_read(no_sleep):
    """The defect. Without this key runner.py counts the product in
    products_priced and a retailer with zero published prices reports 100%."""
    result = _scrape("h", ALL_BUNDLE)
    assert result.get("no_sizes_readable") is True, (
        "an all-bundle product on the JSON path scored as a priced product; "
        "six of seven retailers could empty their column at 100% health")


@responses.activate
def test_the_empty_row_says_why_it_is_empty(no_sleep):
    """Provenance. Without it the history holds two empty rows of identical
    shape — "every size sold out" and "every size is a two-for-one" — and no
    reader can tell them apart."""
    assert _scrape("h", ALL_BUNDLE).get("all_offers_bundled") is True


@responses.activate
def test_the_json_path_row_matches_the_aria_path_row_key_for_key(no_sleep):
    """The two paths answer the same question and must answer it the same
    way, or the next reader has to know which retailer they are looking at."""
    row = _scrape("h", ALL_BUNDLE)
    assert (row["sizes"], row["in_stock"], row.get("no_sizes_readable"),
            row.get("all_offers_bundled")) == ({}, None, True, True)


@responses.activate
def test_it_says_so_out_loud(no_sleep, caplog):
    with caplog.at_level(logging.WARNING):
        _scrape("h", ALL_BUNDLE)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "bundle offers" in msg and "spring-hill/h" in msg


@responses.activate
def test_runner_subtracts_it_from_products_priced(no_sleep):
    """End to end through the arithmetic that actually scores health:
    products_priced = products_found - products_no_sizes."""
    rows = [_scrape("h", ALL_BUNDLE)]
    products_found = len(rows)
    products_no_sizes = sum(1 for r in rows if r.get("no_sizes_readable"))
    assert products_found - products_no_sizes == 0, (
        "an all-bundle catalogue must score 0 priced products, not 1")


# --------------------------------------------------------------------------
# the inverse direction — the flag must not become a rubber stamp
# --------------------------------------------------------------------------

@responses.activate
def test_a_product_with_one_single_plant_size_is_untouched(no_sleep):
    """The shape almost every real product has. One readable single-plant
    size means the page was read; neither flag may appear."""
    result = _scrape("h", MIXED)
    assert [v["price"] for v in result["sizes"].values()] == [29.99]
    assert "no_sizes_readable" not in result
    assert "all_offers_bundled" not in result
    assert result["in_stock"] is None  # .js gave no availability


@responses.activate
def test_a_genuinely_priceless_product_is_still_left_alone(no_sleep):
    """Deliberate carve-out, inherited from the collisions gate: no variants,
    all zero-price, all filtered as multi-plant PACKS. That is a different
    fact with different handling, and this fix must not silently change how
    it is counted on six live retailers."""
    for variants in (
        [],
        [_variant(1, "1 Gallon", "0")],
        [_variant(1, "10-Pack", "199.99"), _variant(2, "4 Plants", "89.99")],
    ):
        responses.reset()
        result = _scrape("h", variants)
        assert result["sizes"] == {}
        assert "all_offers_bundled" not in result, variants


@responses.activate
def test_a_normal_catalogue_raises_no_flag(no_sleep):
    result = _scrape("h", [
        _variant(1, "1 GALLON / 1 Plant(s)", "29.99"),
        _variant(2, "2 GALLON / 1 Plant(s)", "39.99"),
    ])
    assert len(result["sizes"]) == 2
    assert "no_sizes_readable" not in result
    assert "all_offers_bundled" not in result


@responses.activate
def test_a_zero_price_bundle_does_not_vouch_for_a_readable_page(no_sleep):
    """The gate must not be satisfiable by the failure mode it is being told
    apart from (R5). `bundle_variants` is appended to only AFTER the price
    parsed to a positive number, so a page whose prices are all unparseable
    stays in the "could not read this" bucket, not the "read fine, withheld
    on purpose" one."""
    result = _scrape("h", [
        _variant(1, "3-4' BOGO", "0"),
        _variant(2, "5-6 FT - Buy 1, Get 1", "not-a-number"),
    ])
    assert result["sizes"] == {}
    assert "all_offers_bundled" not in result


@responses.activate
def test_a_collision_alongside_a_bundle_is_not_labelled_all_bundled(no_sleep):
    """Both routes to an empty row at once: one tier lost to a collision, the
    rest withheld as bundles.

    The health flag must still fire — not one price published, so the row must
    not score as a successful read. But "every offer buys more than one plant"
    is FALSE here: a single-plant offer existed, was read cleanly, and was
    withheld because two variants wanted the same tier. Labelling this row
    all-bundled writes a wrong explanation into the permanent price history,
    where the whole point of the key is to tell "every size sold out" apart
    from "every size is a two-for-one".
    """
    result = _scrape("h", [
        _variant(1, "1 Gallon", "29.99"),   # collides with...
        _variant(2, "1 Gallon", "34.99"),   # ...this — tier quarantined
        _variant(3, "3-4' BOGO", "119.99"),  # and the rest is a bundle
    ])
    assert result["sizes"] == {}
    assert result["size_collisions"] == 1
    assert result.get("no_sizes_readable") is True, (
        "a row that published nothing scored as a successful price read")
    assert "all_offers_bundled" not in result, (
        "a tier lost to a collision was reported as a multi-plant offer")


@responses.activate
def test_a_bundle_only_row_still_carries_the_reason(no_sleep):
    """The control on the test above: with no collision, the provenance key
    must still be written. A guard that never fires is not a guard."""
    result = _scrape("h", ALL_BUNDLE)
    assert result["sizes"] == {}
    assert result["size_collisions"] == 0
    assert result.get("all_offers_bundled") is True
