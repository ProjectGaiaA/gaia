"""Regression tests for FGT size -> price pairing on the HTML fallback path.

Background. fastgrowingtrees.com blocks the Shopify JSON endpoints, so every FGT
price comes from _scrape_product_html(). That method used to pair sizes with
prices POSITIONALLY: it scraped a list of size-button labels in DOM order,
scraped the schema.org Offers separately, sorted those by price, and zipped the
two lists together. Any size the button regex failed to capture shifted every
later price by one. On pink-lemonade-blueberry it reported 1 gallon = $33.95 when
the page said $45.95 ($33.95 is the 4 inch pot, which the button regex missed).

The fix reads the price out of the same aria-label that carries the size name, so
the two cannot drift apart. These tests lock that in.

All HTTP is mocked. Fixtures are trimmed but verbatim excerpts of real product
pages captured 2026-08-11; the expected values below are the ones a shopper saw
on those pages (recorded independently in fgt_ground_truth.json at the repo root).
"""

import logging

import pytest
import responses

from tests.conftest import load_fixture
from scrapers.shopify import ShopifyScraper

BASE = "https://www.fgt.com"
# A JSON-path retailer. FGT blocks the JSON endpoints, so the bundle filter on
# that path can only be exercised against one of the other six.
SH = "https://www.springhillnursery.com"


def _register(handle, html):
    """JSON endpoint 404s (as FGT's does) so the HTML fallback runs."""
    responses.add(responses.GET, f"{BASE}/products/{handle}.json", status=404)
    responses.add(responses.GET, f"{BASE}/products/{handle}", body=html, status=200)


def _scrape(handle, html):
    _register(handle, html)
    return ShopifyScraper("fast-growing-trees", BASE).scrape_product(handle)


# --- The reported bug -------------------------------------------------------


@responses.activate
def test_each_size_gets_its_own_price(no_sleep):
    """Live page: 4 inch $33.95, 1 quart $30.95 (was $35.95), 1 gallon $45.95."""
    result = _scrape(
        "pink-lemonade-blueberry",
        load_fixture("fgt", "pink-lemonade-blueberry-page.html"),
    )

    sizes = result["sizes"]
    assert sizes["4inch"]["price"] == 33.95
    assert sizes["quart"]["price"] == 30.95
    assert sizes["quart"]["was_price"] == 35.95
    # The regression: 1 gallon used to inherit the 4 inch price.
    assert sizes["1gal"]["price"] == 45.95
    assert sizes["1gal"]["was_price"] is None
    assert [v["raw_size"] for v in sizes.values()] == ["4 inch", "1 quart", "1 gallon"]


@responses.activate
def test_sizes_are_exactly_the_buttons_on_the_page(no_sleep):
    """No extra tiers. Hidden sold-out variants must not become a size row.

    The old code assigned every unmatched schema.org Offer the name
    "variant-<id>", which _normalize_size mapped to the "default" tier — so a
    $97.95 variant that the page never offers landed in the price history as
    'Best Available'.
    """
    result = _scrape(
        "pink-lemonade-blueberry",
        load_fixture("fgt", "pink-lemonade-blueberry-page.html"),
    )

    assert set(result["sizes"]) == {"4inch", "quart", "1gal"}
    assert "default" not in result["sizes"]
    for tier in result["sizes"].values():
        assert not tier["raw_size"].startswith("variant-")


@responses.activate
def test_quantity_buttons_are_not_sizes(no_sleep):
    """'Single' and '10-Pack' live in a second button group with the same
    aria-label format. A 10-pack price is not a per-plant price."""
    result = _scrape(
        "pink-lemonade-blueberry",
        load_fixture("fgt", "pink-lemonade-blueberry-page.html"),
    )

    prices = [v["price"] for v in result["sizes"].values()]
    assert 305.55 not in prices  # 10-Pack sale price
    assert 339.50 not in prices  # 10-Pack list price
    for tier in result["sizes"].values():
        assert "pack" not in tier["raw_size"].lower()
        assert "single" not in tier["raw_size"].lower()


# --- Size labels that collide ----------------------------------------------


@responses.activate
def test_jumbo_height_variant_does_not_overwrite_plain_height(no_sleep):
    """thuja-green-giant sells both "6-7 feet" ($372.95) and "6-7 feet Jumbo"
    ($503.95). Both used to normalize to 6-7ft, so the row showed $503.95."""
    result = _scrape("thuja-green-giant", load_fixture("fgt", "thuja-green-giant-page.html"))

    assert result["sizes"]["6-7ft"]["price"] == 372.95
    assert result["sizes"]["6-7ft-jumbo"]["price"] == 503.95
    assert result["sizes"]["6-7ft"]["raw_size"] == "6-7 feet"


@responses.activate
def test_all_thuja_heights_pair_correctly(no_sleep):
    """2-3ft is ABSENT, and that is the point.

    This page's 2-3 feet button reads
        "2-3 feet - Price $57.95 - Buy 1, Get 1"
    so $57.95 buys TWO arborvitae. It used to be published in the 2-3ft column
    beside other nurseries' single trees, which made Fast Growing Trees look
    half price on a size where it is not. The single-tree price is not on the
    page, so the tier is withheld rather than guessed at.
    """
    result = _scrape("thuja-green-giant", load_fixture("fgt", "thuja-green-giant-page.html"))

    assert {t: v["price"] for t, v in result["sizes"].items()} == {
        "1-2ft": 19.95,
        "3-4ft": 70.95,
        "4-5ft": 123.95,
        "5-6ft": 218.95,
        "6-7ft": 372.95,
        "6-7ft-jumbo": 503.95,
    }
    assert "2-3ft" not in result["sizes"]


@responses.activate
def test_bigger_size_is_not_assumed_to_cost_more(no_sleep):
    """coral-bark-japanese-maple prices are NOT monotonic in size: 6-7 feet
    ($175.95) is cheaper than both 5-6 feet ($224.95) and 4-5 feet ($182.95).

    The old code sorted the offers by price and zipped them onto the buttons in
    DOM order, on the stated assumption that buttons run "smallest->largest, and
    cheapest->most expensive". This page breaks that assumption, and the result
    was a three-way rotation: 4-5ft got $175.95, 5-6ft got $182.95, 6-7ft got
    $224.95. Sorting must never decide which price belongs to which size.

    THE NON-MONOTONICITY IS NOW EXPLAINED, and it was never evidence of a
    mapping bug. Both of the prices that made this page look "backwards" are
    two-for-one offers:
        "4-5 feet - Price $182.95 - Buy 1, Get 1"
        "5-6 feet - Price $224.95 - Buy 1, Get 1"
    Withhold those and what is left -- 3-4ft $84.95, 6-7ft $175.95 -- rises
    with size like every other page. A review once reported "20 of 195
    adjacent height pairs have a taller tree priced at or below the shorter
    one" as proof the site served rotated size/price pairs. It is not
    rotation. MONOTONICITY IS AN INVALID TEST ON A PAGE CARRYING BUNDLES.
    """
    result = _scrape(
        "coral-bark-japanese-maple",
        load_fixture("fgt", "coral-bark-japanese-maple-page.html"),
    )

    assert {t: v["price"] for t, v in result["sizes"].items()} == {
        "3-4ft": 84.95,
        "6-7ft": 175.95,
    }
    assert result["sizes"]["6-7ft"]["was_price"] == 276.95
    # The bundle tiers are gone, not repriced. Halving $182.95 would invent a
    # single-tree price the retailer never published.
    assert "4-5ft" not in result["sizes"]
    assert "5-6ft" not in result["sizes"]


def test_normalize_size_keeps_jumbo_distinct():
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    assert scraper._normalize_size("6-7 feet") == "6-7ft"
    assert scraper._normalize_size("6-7 feet Jumbo") == "6-7ft-jumbo"
    # Spring Hill's bare-root JUMBO tier has no height and must not change.
    assert scraper._normalize_size("JUMBO / 1 Plant(s)") == "jumbo-bareroot"


def test_normalize_size_tolerates_retailer_typo():
    """FGT's duke-blueberry page labels the pot '1 galllon' (three l's)."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    assert scraper._normalize_size("1 galllon") == "1gal"
    assert scraper._normalize_size("1 gallon") == "1gal"
    assert scraper._normalize_size("1 gal") == "1gal"
    # Must not swallow unrelated words that merely start with "gal".
    assert scraper._normalize_size("Gala Apple") == "gala-apple"


# --- aria-label formats -----------------------------------------------------


def test_parses_every_aria_label_format_fgt_uses():
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = (
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $45.95">1 gallon</button>'
        '<button aria-label="1 quart - Original price $35.95, sale price $30.95 - 14% OFF">q</button>'
        '<button aria-label="7 gallon - Original price $1,318.00, sale price $638.40 - 52% OFF">7g</button>'
        '</section>'
    )
    assert scraper._extract_aria_size_offers(html) == [
        ("1 gallon", 45.95, None),
        ("1 quart", 30.95, 35.95),
        ("7 gallon", 638.40, 1318.00),
    ]


def test_a_bundle_marker_withholds_the_size_whatever_the_price_format():
    """The marker trails the PRICE, so it survives none of the name captures.

    This test used to assert the opposite -- it carried
    "2-3 feet - Price $57.95 - Buy 1, Get 1" in a list of formats the scraper
    must parse, and asserted ("2-3 feet", 57.95, None) came back. That pinned
    the defect as correct behaviour, which is why the bundle prices reached
    the live site.

    Checked on all three aria formats, because the bundle suffix can ride on
    any of them, and on the neighbouring single-plant button to prove the
    filter takes the bundle rather than the whole section.
    """
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = (
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $45.95">keep me</button>'
        '<button aria-label="2-3 feet - Price $57.95 - Buy 1, Get 1">bundle</button>'
        '<button aria-label="3-4 feet - Original price $99.95, sale price $79.95 - Buy 1, Get 1">bundle</button>'
        '<button aria-label="4-5 feet - Sale price: 39.99 - List price: $49.99 - BOGO">bundle</button>'
        '</section>'
    )
    assert scraper._extract_aria_size_offers(html) == [("1 gallon", 45.95, None)]


@pytest.mark.parametrize(
    "text,is_bundle",
    [
        # Real FGT vocabulary, verified 2026-08-14 over 66 cached pages:
        # a trailing "- Buy 1, Get 1" is the only form FGT writes.
        ("1-2 feet - Price $94.95 - Buy 1, Get 1", True),
        ("1-2 feet Multi-stem - Price $282.95 - Buy 1, Get 1", True),
        # Recorded on spring-hill, which is why this is not an FGT-only guard.
        ("3-4' BOGO", True),
        ("BOGO / 2 Plant(s)", True),
        ("Buy One Get One Free", True),
        ("B1G1", True),
        ("2 for 1", True),
        ("3 for $30", True),
        # Single plants. "1 Plant(s)" is on EVERY spring-hill variant it sells,
        # so treating a plant count as a bundle marker would empty a retailer.
        ("1 gallon - Price $45.95", False),
        ("1-2 feet - Price $94.95", False),
        ("1 GALLON / 1 Plant(s) | Ships in Fall", False),
        ("PREMIUM / 1 Plant(s) | Ships in Spring", False),
        ('2.5" POT / 1 Plant(s) | Ships in Spring', False),
        ("6-7 feet Jumbo - Original price $766.95, sale price $503.95 - 34% OFF", False),
        ("1 quart - Original price $35.95, sale price $30.95 - 14% OFF", False),
        ("4-5 feet Single-stem", False),
        ("Forget Me Not", False),
    ],
)
def test_is_bundle_offer(text, is_bundle):
    assert ShopifyScraper._is_bundle_offer(text) is is_bundle


@responses.activate
def test_json_path_withholds_bundle_variants_too(no_sleep):
    """The OTHER six retailers go through the JSON path, and it had the same hole.

    This test exists because a mutation run caught its absence. Reverting the
    JSON path to its old `'bogo' in variant_title.lower()` check left the whole
    suite green -- every assertion about bundles lived on the aria path, which
    only Fast Growing Trees uses. The predicate was shared; the coverage was
    not.

    "1 Plant(s)" is the control: Spring Hill writes it on every variant it
    sells, so if a plant COUNT were ever mistaken for a bundle marker this
    retailer would go dark. It must survive.
    """
    payload = {"product": {
        "id": 1, "title": "T", "handle": "h",
        "variants": [
            {"id": 1, "title": "1 GALLON / 1 Plant(s)", "price": "29.99", "compare_at_price": None},
            {"id": 2, "title": "2 GALLON / 1 Plant(s)", "price": "39.99", "compare_at_price": None},
            {"id": 3, "title": "3-4' BOGO", "price": "119.99", "compare_at_price": None},
            {"id": 4, "title": "5-6 FT - Buy 1, Get 1", "price": "199.99", "compare_at_price": None},
            {"id": 5, "title": "12-18 IN Buy One Get One Free", "price": "49.99", "compare_at_price": None},
        ],
    }}
    responses.add(responses.GET, f"{SH}/products/h.json", json=payload, status=200)
    responses.add(responses.GET, f"{SH}/products/h.js", json={"variants": []}, status=200)
    result = ShopifyScraper("spring-hill", SH).scrape_product("h")

    prices = {t: v["price"] for t, v in result["sizes"].items()}
    # Both single-plant variants survive; all three bundles are withheld.
    assert sorted(prices.values()) == [29.99, 39.99]
    assert 119.99 not in prices.values()
    assert 199.99 not in prices.values()
    assert 49.99 not in prices.values()


def test_legacy_aria_format_still_parsed():
    """The previous FGT theme used 'Sale price: X - List price: $Y'. Keep it
    working — a theme rollback must not silently zero out the retailer."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = '<button aria-label="1 Gallon - Sale price: 39.99 - List price: $49.99">1 Gallon</button>'
    assert scraper._extract_aria_size_offers(html) == [("1 Gallon", 39.99, 49.99)]


def test_size_section_scope_excludes_quantity_section():
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = (
        '<section><h2>Select size</h2>'
        '<button aria-label="1 quart - Price $33.95">1 quart</button>'
        '</section>'
        '<section><h2>Select quantity</h2>'
        '<button aria-label="2 gallon - Price $999.00">bogus</button>'
        '</section>'
    )
    # "2 gallon" is inside the quantity group, so it is not a size even though
    # its label looks exactly like one.
    assert scraper._extract_aria_size_offers(html) == [("1 quart", 33.95, None)]


# --- Availability -----------------------------------------------------------


@responses.activate
def test_availability_comes_from_schema_offers_not_assumed(no_sleep):
    """A size whose price matches an OutOfStock Offer is reported unavailable.
    The old aria path hardcoded available=True for every size it found."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        '<button aria-label="3 gallon - Price $49.99">3 gallon</button>'
        "</section>"
        '<script type="application/ld+json">'
        '{"@type":"Offer","sku":"111","price":"24.99","availability":"https://schema.org/InStock"}'
        '{"@type":"Offer","sku":"222","price":"49.99","availability":"https://schema.org/OutOfStock"}'
        "</script></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True
    assert result["sizes"]["3gal"]["available"] is False
    assert result["in_stock"] is True


@responses.activate
def test_all_sizes_out_of_stock_reports_not_in_stock(no_sleep):
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section>"
        '<script type="application/ld+json">'
        '{"@type":"Offer","sku":"111","price":"24.99","availability":"https://schema.org/OutOfStock"}'
        "</script></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is False
    assert result["in_stock"] is False


@responses.activate
def test_price_with_no_matching_offer_is_unknown_not_available(no_sleep):
    """The page carries stock data but says nothing about this price. Unknown
    must stay unknown — never coerced to in stock."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section>"
        '<script type="application/ld+json">'
        '{"@type":"Offer","sku":"999","price":"88.88","availability":"https://schema.org/InStock"}'
        "</script></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is None
    assert result["in_stock"] is None


@responses.activate
def test_conflicting_offers_at_same_price_are_unknown(no_sleep):
    """Two variants share a price and disagree on stock — we cannot tell which
    one the button refers to, so we do not claim to know."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section>"
        '<script type="application/ld+json">'
        '{"@type":"Offer","sku":"111","price":"24.99","availability":"https://schema.org/InStock"}'
        '{"@type":"Offer","sku":"222","price":"24.99","availability":"https://schema.org/OutOfStock"}'
        "</script></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is None


@responses.activate
def test_pack_offers_do_not_supply_availability(no_sleep):
    """A pack SKU that happens to match a single-plant price must be ignored."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section>"
        '<script type="application/ld+json">'
        '{"@type":"Offer","sku":"111-10PACK","price":"24.99","availability":"https://schema.org/OutOfStock"}'
        '{"@type":"Offer","sku":"111","price":"24.99","availability":"https://schema.org/InStock"}'
        "</script></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True


@responses.activate
def test_page_without_stock_data_keeps_legacy_assumption(no_sleep):
    """No schema.org Offers anywhere: no signal either way, so a priced,
    rendered size button stays available (what this path always did)."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True
    assert result["in_stock"] is True


# --- Guards -----------------------------------------------------------------


@responses.activate
def test_zero_price_size_is_dropped(no_sleep):
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $0.00">1 gallon</button>'
        '<button aria-label="3 gallon - Price $49.99">3 gallon</button>'
        "</section></body></html>"
    )
    result = _scrape("test-plant", html)

    assert "1gal" not in result["sizes"]
    assert result["sizes"]["3gal"]["price"] == 49.99


@responses.activate
def test_duplicate_tier_is_withheld_not_resolved_by_button_order(no_sleep, caplog):
    """REPLACES test_duplicate_tier_keeps_the_first_button.

    The old rule kept the FIRST button, justified by "buttons render
    smallest-first". That justification is false on the real page: on the
    cached crape-myrtle page the first `quart` button is "1 quart Multi-stem"
    and the second is "2 quart Multi-stem", a BIGGER pot. Keeping the first is
    still picking a winner between two products by list order, which is the
    defect class rather than a fix for it.
    """
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        '<button aria-label="1 Gallon Pot - Price $99.99">1 Gallon Pot</button>'
        '<button aria-label="3 gallon - Price $49.99">3 gallon</button>'
        "</section></body></html>"
    )
    with caplog.at_level(logging.ERROR, logger="scrapers.shopify"):
        result = _scrape("test-plant", html)

    # The contested tier is published by NEITHER product...
    assert "1gal" not in result["sizes"]
    # ...and the uncontested one is untouched: one bad tier never costs a product.
    assert result["sizes"]["3gal"]["price"] == 49.99
    assert result["size_collisions"] == 1
    assert "claimed by two different products" in caplog.text


@responses.activate
def test_identical_duplicate_button_is_not_a_collision(no_sleep):
    """FGT renders the same size button twice on 2 of 65 cached pages, at the
    same price. That is one product listed twice, not two products, and must
    not trip the guard or cost the tier."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 quart - Price $35.95">1 quart</button>'
        '<button aria-label="1 quart - Price $35.95">1 quart</button>'
        "</section></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["quart"]["price"] == 35.95
    assert result["size_collisions"] == 0


@responses.activate
def test_every_tier_quarantined_withholds_rather_than_pairing_by_position(no_sleep):
    """A page whose every size button is contested must NOT fall through to
    the positional size<->price pairing below the aria path.

    The page below is built so the fall-through is VISIBLE rather than merely
    unreachable: it carries a schema.org Offer and a loose "3-4 feet" string
    outside the size selector. Without the guard the scraper returns
    3-4ft = $24.99 — a size that was never on a size button, wearing a price
    paired to it by position, from a page whose only two real buttons we just
    admitted we could not tell apart.
    """
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        '<button aria-label="1 Gallon Pot - Price $99.99">1 Gallon Pot</button>'
        "</section>"
        "<span>3-4 feet</span>"
        '<script type="application/ld+json">{"@type":"Offer","sku":"111",'
        '"price":"24.99","availability":"https://schema.org/InStock"}</script>'
        "</body></html>"
    )
    assert _scrape("test-plant", html) is None


# --- Drift guard ------------------------------------------------------------
# Everything above proves the parser is right TODAY. These prove what happens
# when FGT changes its markup again, which it has already done once.


@responses.activate
def test_unreadable_size_selector_publishes_nothing_rather_than_guessing():
    """If a page clearly has a size selector but no size can be read out of
    it, the old code fell through to pairing labels and prices BY POSITION.

    That is how sizes came to wear their neighbour's price, and nothing
    noticed: runner.py scores health as products_found/products_expected, so
    a wrong-but-present product still counts as a hit and the run reports
    healthy. Withholding the product instead makes the gap visible.
    """
    html = load_fixture("fgt", "pink-lemonade-blueberry-page.html")
    # Only the aria-label TYPOGRAPHY changes. Prices, buttons and the
    # schema.org Offers are all untouched and still parseable.
    drifted = html.replace(" - Price $", " \u2013 Price $").replace(
        " - Original price $", " \u2013 Original price $")
    assert drifted != html, "fixture did not contain the expected label format"
    assert "Select size" in drifted or "select size" in drifted.lower()

    result = _scrape("pink-lemonade-blueberry", drifted)
    if result is not None:
        # Publishing is only acceptable if every size is genuinely right.
        for tier, s in result.get("sizes", {}).items():
            assert tier != "default", (
                f"published a phantom 'default' row at ${s['price']} rather than "
                f"withholding the product"
            )


def test_a_page_with_no_size_selector_is_unaffected_by_the_guard():
    """Single-size products legitimately have no size selector. The guard is
    scoped to pages that HAVE one, so it must never fire on those.

    Asserted on the guard's own condition rather than on a full scrape, so
    that unrelated parsing changes cannot make this test quietly vacuous.
    """
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = """<html><head><title>Solo Plant | FGT</title></head><body>
    <button>Add to cart</button></body></html>"""
    assert scraper._size_selector_scope(html) is None
    assert not scraper._extract_aria_size_offers(html)
    guard_fires = (
        not scraper._extract_aria_size_offers(html)
        and scraper._size_selector_scope(html)
    )
    assert not guard_fires, "guard would withhold a product with no size selector"


def test_the_guard_does_fire_when_a_size_selector_cannot_be_read():
    """The positive case, asserted on the same condition."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = load_fixture("fgt", "pink-lemonade-blueberry-page.html")
    drifted = html.replace(" - Price $", " – Price $").replace(
        " - Original price $", " – Original price $")
    assert scraper._size_selector_scope(drifted), "fixture has no size selector"
    assert not scraper._extract_aria_size_offers(drifted), (
        "drifted labels still parsed; pick a mutation the parser really cannot read")


@responses.activate
def test_guard_survives_a_heading_redesign():
    """The guard must not key on the "Select size" heading markup.

    A theme redesign changes the heading AND the aria format together, so
    keying on the heading meant the guard switched itself off in exactly the
    scenario it was written for. Measured: 5 of 6 heading variants published
    the Jumbo's $503.95 on the standard 6-7ft row (truth $372.95).

    It now decides "is this a multi-size product" from the schema.org Offer
    count, which comes from structured data and not from presentation.
    """
    import re as _re
    html = load_fixture("fgt", "thuja-green-giant-page.html")
    unreadable = html.replace(" - Price $", " – Price $").replace(
        " - Original price $", " – Original price $")

    variants = {
        "inner span": lambda s: _re.sub(r"(?i)select size</h2>",
                                        "<span>Select size</span></h2>", s),
        "h3":         lambda s: _re.sub(r"(?i)select size</h2>", "Select size</h3>", s),
        "div":        lambda s: _re.sub(r"(?i)select size</h2>", "Select size</div>", s),
        "reworded":   lambda s: _re.sub(r"(?i)select size</h2>", "Select a size</h2>", s),
        "shortened":  lambda s: _re.sub(r"(?i)select size</h2>", "Size</h2>", s),
    }
    for name, mutate in variants.items():
        responses.reset()
        result = _scrape("thuja-green-giant", mutate(unreadable))
        if result is None:
            continue                      # withheld, which is the point
        for tier, sdata in result.get("sizes", {}).items():
            assert tier != "default", f"{name}: published a phantom row"
            assert abs(sdata["price"] - 503.95) > 0.01, (
                f"{name}: published the Jumbo price ${sdata['price']} on {tier}")


@responses.activate
def test_fully_sold_out_page_records_out_of_stock_not_error():
    """FGT strips the size selector when every size is gone. That page state
    is indistinguishable from markup drift by structure alone — but not by
    the page's own Offers: all non-orderable means sold out, a true fact
    worth recording. Withholding it threw away the fact and pinned FGT
    below the health threshold every run (recurring false alarm).

    Shape taken from the live /products/russian-sage page 2026-08-12:
    HTTP 200, six Offers all OutOfStock, no size selector rendered."""
    html = """<html><head><title>Russian Sage | FGT</title></head><body>
    <script type="application/ld+json">{"@type":"Product","offers":[
      {"@type":"Offer","sku":"111","price":"24.95","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","sku":"222","price":"38.95","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","sku":"333","price":"52.95","availability":"https://schema.org/OutOfStock"}]}
    </script></body></html>"""
    result = _scrape("russian-sage", html)
    assert result is not None, "sold-out product was withheld as if it were drift"
    assert result["in_stock"] is False
    assert result["sizes"] == {}, "no sizes may be fabricated from Offer SKUs"


@responses.activate
def test_orderable_but_unreadable_is_still_withheld_as_drift():
    """The boundary: ONE orderable Offer among the sold-out ones means a
    price exists that we cannot attribute to a size. That is drift, and
    publishing anything would risk the neighbour's-price defect."""
    html = """<html><head><title>Drifted | FGT</title></head><body>
    <script type="application/ld+json">{"@type":"Product","offers":[
      {"@type":"Offer","sku":"111","price":"24.95","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","sku":"222","price":"38.95","availability":"https://schema.org/InStock"}]}
    </script></body></html>"""
    assert _scrape("drifted-product", html) is None


# --- Fail-closed vocabulary (kills mutant M3) -------------------------------

def test_unknown_availability_values_do_not_count_as_sold_out():
    """The sold-out branch publishes a row AND downgrades the drift alarm, so
    an unrecognised availability value must NOT land there.

    Review measured the original `not _is_orderable(...)` test publishing
    sold-out rows for OnlineOnly, PreSale and MadeToOrder — all orderable
    states. PreSale is the one that matters for a nursery: a spring pre-sale
    is exactly this case.
    """
    from scrapers.shopify import _is_definitely_unavailable as gone

    for value in ("OutOfStock", "SoldOut", "Discontinued", "InStoreOnly",
                  "https://schema.org/OutOfStock", "http://schema.org/SoldOut",
                  "out_of_stock", "OUTOFSTOCK"):
        assert gone(value), f"{value!r} should count as definitely unavailable"

    for value in ("InStock", "PreOrder", "BackOrder", "LimitedAvailability",
                  "OnlineOnly", "PreSale", "MadeToOrder",
                  "https://schema.org/PreSale", "", "  ", "wat"):
        assert not gone(value), (
            f"{value!r} is not a positive statement of unavailability and must "
            f"not silence the drift alarm")


@responses.activate
def test_one_presale_offer_among_sold_out_ones_is_treated_as_drift():
    html = """<html><head><title>PreSale | FGT</title></head><body>
    <script type="application/ld+json">{"@type":"Product","offers":[
      {"@type":"Offer","sku":"111","price":"24.95","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","sku":"222","price":"38.95","availability":"https://schema.org/PreSale"}]}
    </script></body></html>"""
    assert _scrape("presale-product", html) is None, (
        "a pre-sale offer is orderable — this page is drift, not sold out")


# --- Cannot-decide is drift (kills mutant M4) -------------------------------

@responses.activate
def test_unparseable_schema_block_withholds_rather_than_publishing():
    """all([]) is True, so an empty offer list made the WORST drift — a schema
    block that will not parse at all — publish a clean sold-out row."""
    html = """<html><head><title>Broken | FGT</title></head><body>
    <h2>Select size</h2>
    <script type="application/ld+json">{"@type":"Product","offers":[{ THIS IS NOT JSON </script>
    </body></html>"""
    assert _scrape("broken-schema", html) is None, (
        "no parseable offers means we cannot decide — that is drift, withhold")


@responses.activate
def test_sold_out_row_is_marked_as_having_no_readable_sizes():
    """The published row must carry the flag runner.py uses to keep the drift
    signal alive; without it a fully broken retailer reported 100% healthy."""
    html = """<html><head><title>Gone | FGT</title></head><body>
    <script type="application/ld+json">{"@type":"Product","offers":[
      {"@type":"Offer","sku":"111","price":"24.95","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","sku":"222","price":"38.95","availability":"https://schema.org/OutOfStock"}]}
    </script></body></html>"""
    result = _scrape("gone-product", html)
    assert result is not None and result["in_stock"] is False
    assert result.get("no_sizes_readable") is True
