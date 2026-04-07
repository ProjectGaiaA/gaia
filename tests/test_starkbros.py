"""Tests for the Stark Bros scraper (scrapers/starkbros.py)."""

import responses

from tests.conftest import load_fixture
from scrapers.starkbros import StarkBrosScraper


ROBOTS_ALLOW = "User-agent: *\nAllow: /\nCrawl-delay: 5"


def _add_robots():
    responses.add(
        responses.GET,
        "https://www.starkbros.com/robots.txt",
        body=ROBOTS_ALLOW,
        status=200,
    )


# --- dataLayer extraction ---


@responses.activate
def test_datalayer_extraction(no_sleep):
    """Stark Bros scraper extracts product data from dataLayer.push() JS."""
    html = load_fixture("starkbros", "honeycrisp-apple-page.html")
    responses.add(
        responses.GET,
        "https://www.starkbros.com/products/fruit-trees/apple-trees/honeycrisp-apple",
        body=html,
        status=200,
    )
    _add_robots()

    scraper = StarkBrosScraper()
    result = scraper.scrape_product("honeycrisp-apple", "fruit-trees/apple-trees")

    assert result is not None
    assert result["retailer_id"] == "stark-bros"
    assert result["title"] == "Honeycrisp Apple Tree"
    assert result["in_stock"] is True
    assert len(result["sizes"]) == 4


@responses.activate
def test_datalayer_variant_normalization(no_sleep):
    """Stark Bros variant descriptions normalize to canonical tiers."""
    html = load_fixture("starkbros", "honeycrisp-apple-page.html")
    responses.add(
        responses.GET,
        "https://www.starkbros.com/products/fruit-trees/apple-trees/honeycrisp-apple",
        body=html,
        status=200,
    )
    _add_robots()

    scraper = StarkBrosScraper()
    result = scraper.scrape_product("honeycrisp-apple", "fruit-trees/apple-trees")

    tiers = set(result["sizes"].keys())
    assert "dwarf" in tiers
    assert "semi-dwarf" in tiers
    assert "standard" in tiers
    assert "dwarf-potted" in tiers


@responses.activate
def test_datalayer_was_price(no_sleep):
    """Stark Bros sets was_price when lowestRegularPrice > lowestPrice."""
    html = load_fixture("starkbros", "honeycrisp-apple-page.html")
    responses.add(
        responses.GET,
        "https://www.starkbros.com/products/fruit-trees/apple-trees/honeycrisp-apple",
        body=html,
        status=200,
    )
    _add_robots()

    scraper = StarkBrosScraper()
    result = scraper.scrape_product("honeycrisp-apple", "fruit-trees/apple-trees")

    # Dwarf at $34.99 is the lowest price, regular was $44.99
    dwarf = result["sizes"]["dwarf"]
    assert dwarf["price"] == 34.99
    assert dwarf["was_price"] == 44.99


# --- JSON-LD fallback ---


@responses.activate
def test_jsonld_fallback(no_sleep):
    """When no dataLayer exists, Stark Bros falls back to JSON-LD."""
    html = load_fixture("starkbros", "jsonld-fallback-page.html")
    responses.add(
        responses.GET,
        "https://www.starkbros.com/products/fruit-trees/peach-trees/elberta-peach",
        body=html,
        status=200,
    )
    _add_robots()

    scraper = StarkBrosScraper()
    result = scraper.scrape_product("elberta-peach", "fruit-trees/peach-trees")

    assert result is not None
    assert "default" in result["sizes"]
    assert result["sizes"]["default"]["price"] == 29.99
    assert result["in_stock"] is True


# --- Variant normalization unit tests ---


class TestStarkBrosNormalization:
    """Test _normalize_variant for all Stark Bros patterns."""

    def setup_method(self):
        self.scraper = StarkBrosScraper()

    def test_dwarf_bareroot(self):
        assert self.scraper._normalize_variant("Honeycrisp Apple Dwarf") == "dwarf"

    def test_semi_dwarf(self):
        assert self.scraper._normalize_variant("Honeycrisp Apple Semi-Dwarf") == "semi-dwarf"

    def test_standard(self):
        assert self.scraper._normalize_variant("Honeycrisp Apple Standard") == "standard"

    def test_supreme(self):
        assert self.scraper._normalize_variant("Elberta Peach Supreme") == "supreme"

    def test_ultra_supreme(self):
        assert self.scraper._normalize_variant("Bartlett Pear Ultra Supreme") == "ultra-supreme"

    def test_potted_7gal(self):
        assert self.scraper._normalize_variant("Honeycrisp Apple Dwarf 7 Gal Potted") == "dwarf-potted"

    def test_semi_dwarf_potted(self):
        assert self.scraper._normalize_variant("Semi-Dwarf Potted") == "semi-dwarf-potted"

    def test_ez_start(self):
        assert self.scraper._normalize_variant("Honeycrisp Apple Dwarf EZ Start") == "dwarf-ez-start"

    def test_unrecognized_returns_default(self):
        assert self.scraper._normalize_variant("Patriot Blueberry") == "default"
