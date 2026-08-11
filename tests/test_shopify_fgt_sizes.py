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

import responses

from tests.conftest import load_fixture
from scrapers.shopify import ShopifyScraper

BASE = "https://www.fgt.com"


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
    result = _scrape("thuja-green-giant", load_fixture("fgt", "thuja-green-giant-page.html"))

    assert {t: v["price"] for t, v in result["sizes"].items()} == {
        "1-2ft": 19.95,
        "2-3ft": 57.95,
        "3-4ft": 70.95,
        "4-5ft": 123.95,
        "5-6ft": 218.95,
        "6-7ft": 372.95,
        "6-7ft-jumbo": 503.95,
    }


@responses.activate
def test_bigger_size_is_not_assumed_to_cost_more(no_sleep):
    """coral-bark-japanese-maple prices are NOT monotonic in size: 6-7 feet
    ($175.95) is cheaper than both 5-6 feet ($224.95) and 4-5 feet ($182.95).

    The old code sorted the offers by price and zipped them onto the buttons in
    DOM order, on the stated assumption that buttons run "smallest->largest, and
    cheapest->most expensive". This page breaks that assumption, and the result
    was a three-way rotation: 4-5ft got $175.95, 5-6ft got $182.95, 6-7ft got
    $224.95. Sorting must never decide which price belongs to which size.
    """
    result = _scrape(
        "coral-bark-japanese-maple",
        load_fixture("fgt", "coral-bark-japanese-maple-page.html"),
    )

    assert {t: v["price"] for t, v in result["sizes"].items()} == {
        "3-4ft": 84.95,
        "4-5ft": 182.95,
        "5-6ft": 224.95,
        "6-7ft": 175.95,
    }
    assert result["sizes"]["6-7ft"]["was_price"] == 276.95


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
        '<button aria-label="2-3 feet - Price $57.95 - Buy 1, Get 1">2-3 feet</button>'
        '<button aria-label="1 quart - Original price $35.95, sale price $30.95 - 14% OFF">q</button>'
        '<button aria-label="7 gallon - Original price $1,318.00, sale price $638.40 - 52% OFF">7g</button>'
        '</section>'
    )
    assert scraper._extract_aria_size_offers(html) == [
        ("1 gallon", 45.95, None),
        ("2-3 feet", 57.95, None),
        ("1 quart", 30.95, 35.95),
        ("7 gallon", 638.40, 1318.00),
    ]


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
def test_duplicate_tier_keeps_the_first_button(no_sleep):
    """Two labels collapsing to one tier must not let the later, pricier one
    overwrite the earlier. Buttons render smallest-first."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        '<h2>Select size</h2>'
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        '<button aria-label="1 Gallon Pot - Price $99.99">1 Gallon Pot</button>'
        "</section></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["price"] == 24.99
    assert result["sizes"]["1gal"]["raw_size"] == "1 gallon"
