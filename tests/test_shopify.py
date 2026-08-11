"""Tests for the Shopify scraper (scrapers/shopify.py)."""

import responses

from tests.conftest import load_fixture
from scrapers.shopify import ShopifyScraper


ROBOTS_ALLOW = "User-agent: *\nAllow: /"


def _add_robots(base_url):
    """Register a permissive robots.txt for a base URL."""
    responses.add(
        responses.GET,
        f"{base_url}/robots.txt",
        body=ROBOTS_ALLOW,
        status=200,
    )


@responses.activate
def test_json_product_parsing_returns_correct_structure(no_sleep):
    """Scraping a product via JSON endpoint returns all expected fields
    with correct values parsed from the Shopify product data."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://www.naturehills.com")

    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper.scrape_product("hydrangea-lime-light")

    assert result is not None
    assert result["retailer_id"] == "nature-hills"
    assert result["handle"] == "hydrangea-lime-light"
    assert result["title"] == "Limelight Hydrangea"
    assert "sizes" in result
    assert len(result["sizes"]) == 3

    # #1 Container → 1gal tier
    assert "1gal" in result["sizes"]
    assert result["sizes"]["1gal"]["price"] == 39.99
    assert result["sizes"]["1gal"]["was_price"] == 49.99

    # #3 Container 3-4 Feet → 3gal (container pattern wins over height)
    assert "3gal" in result["sizes"]
    assert result["sizes"]["3gal"]["price"] == 69.99
    assert result["sizes"]["3gal"]["was_price"] is None

    # #5 Container → 5gal tier
    assert "5gal" in result["sizes"]
    assert result["sizes"]["5gal"]["price"] == 99.99

    # Stock should be None (Nature Hills doesn't provide availability)
    assert result["in_stock"] is None

    # URL should include variant parameter for deep linking
    assert "variant=" in result["url"]
    assert result["url"].startswith("https://www.naturehills.com/products/")


# --- Size normalization tests ---


class TestSizeNormalization:
    """Test _normalize_size across all retailer naming conventions."""

    def setup_method(self):
        self.scraper = ShopifyScraper("test", "http://test.com")

    def test_gallon_containers(self):
        assert self.scraper._normalize_size("1 Gallon") == "1gal"
        assert self.scraper._normalize_size("2 Gallon") == "2gal"
        assert self.scraper._normalize_size("3 Gallon") == "3gal"
        assert self.scraper._normalize_size("5 Gallon") == "5gal"
        assert self.scraper._normalize_size("7 Gallon") == "7gal"
        assert self.scraper._normalize_size("10 Gallon") == "10gal"
        assert self.scraper._normalize_size("15 Gallon") == "15gal"

    def test_nature_hills_container_format(self):
        assert self.scraper._normalize_size("#1 Container") == "1gal"
        assert self.scraper._normalize_size("#2 Container") == "2gal"
        assert self.scraper._normalize_size("#3 Container") == "3gal"
        assert self.scraper._normalize_size("#5 Container") == "5gal"
        assert self.scraper._normalize_size("#7 Container") == "7gal"

    def test_nature_hills_container_with_height(self):
        # Container pattern should win over height
        assert self.scraper._normalize_size("#3 Container 3-4 Feet") == "3gal"

    def test_quart_variants(self):
        assert self.scraper._normalize_size("Quart") == "quart"
        assert self.scraper._normalize_size("1 quart") == "quart"
        assert self.scraper._normalize_size("One Quart") == "quart"
        assert self.scraper._normalize_size("Quart Container") == "quart"
        assert self.scraper._normalize_size("Qt") == "quart"

    def test_height_based_sizing(self):
        assert self.scraper._normalize_size("3-4 feet") == "3-4ft"
        assert self.scraper._normalize_size("5-6 ft") == "5-6ft"
        assert self.scraper._normalize_size("2-3 Feet") == "2-3ft"
        assert self.scraper._normalize_size("4-5 foot") == "4-5ft"

    def test_spring_hill_format(self):
        result = self.scraper._normalize_size("PREMIUM / 1 Plant(s) | Ships in Spring")
        assert result == "premium-bareroot"

        result = self.scraper._normalize_size("JUMBO / 1 Plant(s) | Ships in Spring")
        assert result == "jumbo-bareroot"

    def test_spring_hill_gallon_format(self):
        result = self.scraper._normalize_size("1 GALLON - 2-4 FT / 1 Plant(s) | Ships in Spring")
        assert result == "1gal"

    def test_bareroot_variants(self):
        assert self.scraper._normalize_size("Bare Root") == "bareroot"
        assert self.scraper._normalize_size("Dormant") == "bareroot"

    def test_stark_bros_rootstock(self):
        assert self.scraper._normalize_size("Semi-Dwarf") == "semi-dwarf"
        assert self.scraper._normalize_size("Dwarf") == "dwarf"
        assert self.scraper._normalize_size("Standard") == "standard"
        assert self.scraper._normalize_size("Supreme") == "supreme"
        assert self.scraper._normalize_size("Ultra Supreme") == "ultra-supreme"

    def test_default_title_returns_default(self):
        assert self.scraper._normalize_size("Default Title") == "default"
        assert self.scraper._normalize_size("") == "default"

    def test_variant_id_returns_default(self):
        assert self.scraper._normalize_size("variant-44912345678901") == "default"

    def test_small_pots(self):
        assert self.scraper._normalize_size("4 inch") == "4inch"
        assert self.scraper._normalize_size('4"') == "4inch"
        assert self.scraper._normalize_size("6 inch pot") == "6inch"

    def test_bulb(self):
        assert self.scraper._normalize_size("3 Bulbs") == "bulb"
        assert self.scraper._normalize_size("Bulb") == "bulb"

    def test_pwd_ship_week_stripped(self):
        result = self.scraper._normalize_size("1 Gallon / Ship Week 23 (June 1st – June 5th)")
        assert result == "1gal"

    def test_ggp_format(self):
        assert self.scraper._normalize_size("One Gallon") == "1gal"
        assert self.scraper._normalize_size("One Quart") == "quart"


# --- Pack filtering tests ---


@responses.activate
def test_pack_variants_filtered_out(no_sleep):
    """Multi-plant packs (3-pack, 10-pack, BOGO) should be excluded from results."""
    fixture = load_fixture("nature-hills", "pack-variant-product.json")
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light-bundle.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://www.naturehills.com")

    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper.scrape_product("hydrangea-lime-light-bundle")

    assert result is not None
    # Only the 1 Gallon single survives. "3 Plant(s)", "10-Pack", and "BOGO / 2 Plant(s)" all filtered.
    assert len(result["sizes"]) == 1
    assert "1gal" in result["sizes"]


# --- Availability handling ---


@responses.activate
def test_mixed_availability_reports_in_stock(no_sleep):
    """When some variants are in stock and others are not, in_stock should be True."""
    fixture = load_fixture("nature-hills", "mixed-availability-product.json")
    responses.add(
        responses.GET,
        "https://test-retailer.com/products/bloodgood-japanese-maple.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://test-retailer.com")

    scraper = ShopifyScraper("test-retailer", "https://test-retailer.com")
    result = scraper.scrape_product("bloodgood-japanese-maple")

    assert result is not None
    assert result["in_stock"] is True
    # 5gal should be marked unavailable
    assert result["sizes"]["5gal"]["available"] is False
    # 3gal and 7gal should be available
    assert result["sizes"]["3gal"]["available"] is True
    assert result["sizes"]["7gal"]["available"] is True


@responses.activate
def test_null_availability_reports_unknown_stock(no_sleep):
    """When all variants have null availability (Nature Hills), in_stock is None."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://www.naturehills.com")

    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper.scrape_product("hydrangea-lime-light")

    assert result["in_stock"] is None


# --- 404 / HTML fallback trigger ---


@responses.activate
def test_json_404_triggers_html_fallback(no_sleep):
    """When JSON endpoint returns 404, scraper should attempt HTML page."""
    # JSON endpoint returns 404
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea.json",
        status=404,
    )
    # HTML page also returns 404 (no product exists)
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea",
        status=404,
    )
    _add_robots("https://www.fgt.com")

    scraper = ShopifyScraper("fgt", "https://www.fgt.com")
    result = scraper.scrape_product("limelight-hydrangea")

    # Both endpoints failed — should return None
    assert result is None
    # Verify both endpoints were called (JSON first, then HTML fallback)
    urls_called = [c.request.url for c in responses.calls]
    json_urls = [u for u in urls_called if u.endswith(".json") and "robots" not in u]
    html_urls = [u for u in urls_called if not u.endswith(".json") and "robots" not in u]
    assert len(json_urls) >= 1, "JSON endpoint should be tried first"
    assert len(html_urls) >= 1, "HTML fallback should be tried after JSON 404"


# --- 429 rate limit handling ---


@responses.activate
def test_429_rate_limit_retries_after_delay(no_sleep):
    """When server returns 429, scraper should wait and retry."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")
    # First request: 429 with Retry-After header
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        status=429,
        headers={"Retry-After": "5"},
    )
    # Retry succeeds
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://www.naturehills.com")

    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper.scrape_product("hydrangea-lime-light")

    assert result is not None
    assert result["title"] == "Limelight Hydrangea"


# --- Deep linking ---


@responses.activate
def test_deep_link_points_to_cheapest_variant(no_sleep):
    """Product URL should deep-link to the cheapest available variant."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://www.naturehills.com")

    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper.scrape_product("hydrangea-lime-light")

    # Cheapest variant is #1 Container at $39.99 with variant ID 43210987654321
    assert "variant=43210987654321" in result["url"]


# --- Zero-price variants ---


@responses.activate
def test_zero_price_variants_excluded(no_sleep):
    """Variants with price <= 0 should not appear in results."""
    fixture = {
        "product": {
            "id": 1,
            "title": "Test Plant",
            "handle": "test-plant",
            "variants": [
                {"id": 100, "title": "1 Gallon", "price": "0", "compare_at_price": None, "available": True},
                {"id": 101, "title": "3 Gallon", "price": "49.99", "compare_at_price": None, "available": True},
            ],
        }
    }
    responses.add(
        responses.GET,
        "https://test.com/products/test-plant.json",
        json=fixture,
        status=200,
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("test-plant")

    assert result is not None
    assert len(result["sizes"]) == 1
    assert "3gal" in result["sizes"]


# --- Ships in Spring availability ---


def _spring_hill_fixture():
    return {
        "product": {
            "id": 2,
            "title": "Spring Hill Rose",
            "handle": "spring-hill-rose",
            "variants": [
                {
                    "id": 200,
                    "title": "PREMIUM / 1 Plant(s) | Ships in Spring",
                    "price": "24.99",
                    "compare_at_price": None,
                    # Note: the real .json endpoint has no `available` key at
                    # all. Kept as None here to mirror what .get() returns.
                    "available": None,
                },
            ],
        }
    }


@responses.activate
def test_ships_in_spring_does_not_imply_available(no_sleep):
    """'Ships in Spring' says WHEN an order ships, not WHETHER one can be placed.

    This previously set available=True on a title match, fabricating stock.
    Spring Hill's Pink Lemonade Blueberry had every variant sold out at the
    retailer and rendered "In Stock" with the green best-price highlight,
    because the title contained the word "Spring". Measured against live data,
    spring-hill asserted availability and was wrong 48 times out of 52.

    With no .js availability to consult, the answer must be UNKNOWN — never a
    guess in the direction that flatters the listing.
    """
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.json",
        json=_spring_hill_fixture(),
        status=200,
    )
    responses.add(
        responses.GET, "https://test.com/products/spring-hill-rose.js", status=404
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("spring-hill-rose")

    assert result is not None
    tier = list(result["sizes"].values())[0]
    assert tier["available"] is None, "unknown stock must stay unknown"
    assert result["in_stock"] is None


@responses.activate
def test_js_availability_overrides_unknown(no_sleep):
    """The .js endpoint is the only source of truth for stock.

    /products/{handle}.json has NO `available` field, so every Shopify variant
    read through it was None forever — 170 rows in the corpus. Verified against
    plantingtree.com: the variants .js reports available are exactly the ones
    its own size selector offers.
    """
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.json",
        json=_spring_hill_fixture(),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.js",
        json={"variants": [{"id": 200, "available": False}]},
        status=200,
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("spring-hill-rose")

    tier = list(result["sizes"].values())[0]
    assert tier["available"] is False
    assert result["in_stock"] is False


@responses.activate
def test_js_failure_degrades_to_unknown_never_to_available(no_sleep):
    """A failed availability fetch must not be read as "in stock"."""
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.json",
        json=_spring_hill_fixture(),
        status=200,
    )
    responses.add(
        responses.GET, "https://test.com/products/spring-hill-rose.js", status=500
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("spring-hill-rose")
    assert list(result["sizes"].values())[0]["available"] is None


@responses.activate
def test_js_non_boolean_availability_is_ignored(no_sleep):
    """Only a real bool counts. A string or null must not become True."""
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.json",
        json=_spring_hill_fixture(),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.js",
        json={"variants": [{"id": 200, "available": "yes"}]},
        status=200,
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("spring-hill-rose")
    assert list(result["sizes"].values())[0]["available"] is None


@responses.activate
def test_availability_join_is_by_variant_id_not_position(no_sleep):
    """Guards against the positional-mapping class of bug.

    If the join were by order, reversing the .js variant list would flip which
    size is marked available. It must not.
    """
    fixture = {
        "product": {
            "id": 3,
            "title": "Two Size Shrub",
            "handle": "two-size",
            "variants": [
                {"id": 10, "title": "1 Gallon", "price": "34.95", "compare_at_price": None},
                {"id": 20, "title": "3 Gallon", "price": "79.95", "compare_at_price": None},
            ],
        }
    }
    responses.add(
        responses.GET, "https://test.com/products/two-size.json", json=fixture, status=200
    )
    responses.add(
        responses.GET,
        "https://test.com/products/two-size.js",
        # Deliberately reversed relative to the .json order.
        json={"variants": [{"id": 20, "available": True}, {"id": 10, "available": False}]},
        status=200,
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("two-size")

    assert result["sizes"]["1gal"]["available"] is False
    assert result["sizes"]["3gal"]["available"] is True


@responses.activate
def test_prices_are_not_read_from_the_js_endpoint(no_sleep):
    """.js returns price in CENTS; .json returns dollar strings.

    Taking price from .js would multiply every price on the site by 100. Only
    the boolean is read from there.
    """
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.json",
        json=_spring_hill_fixture(),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://test.com/products/spring-hill-rose.js",
        json={"variants": [{"id": 200, "available": True, "price": 2499}]},
        status=200,
    )
    _add_robots("https://test.com")

    scraper = ShopifyScraper("test", "https://test.com")
    result = scraper.scrape_product("spring-hill-rose")
    assert list(result["sizes"].values())[0]["price"] == 24.99
