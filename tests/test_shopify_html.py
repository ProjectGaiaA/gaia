"""Tests for Shopify HTML fallback scraping and promo code detection."""

import requests as req_lib
import responses

from tests.conftest import load_fixture
from scrapers.shopify import ShopifyScraper


ROBOTS_ALLOW = "User-agent: *\nAllow: /"


def _add_robots(base_url):
    responses.add(
        responses.GET,
        f"{base_url}/robots.txt",
        body=ROBOTS_ALLOW,
        status=200,
    )


# --- Aria-label extraction (FGT primary path) ---


@responses.activate
def test_html_aria_label_extraction(no_sleep):
    """HTML fallback extracts prices from aria-label attributes."""
    html = load_fixture("fgt", "limelight-hydrangea-page.html")
    # JSON endpoint returns 404 → triggers HTML fallback
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea.json",
        status=404,
    )
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea",
        body=html,
        status=200,
    )
    _add_robots("https://www.fgt.com")

    scraper = ShopifyScraper("fgt", "https://www.fgt.com")
    result = scraper.scrape_product("limelight-hydrangea")

    assert result is not None
    assert result["retailer_id"] == "fgt"
    assert result["title"] == "Limelight Hydrangea"

    # Aria-label prices: quart, 1gal, 3gal (3-Pack filtered)
    assert "quart" in result["sizes"]
    assert result["sizes"]["quart"]["price"] == 24.99
    assert result["sizes"]["quart"]["was_price"] == 34.99

    assert "1gal" in result["sizes"]
    assert result["sizes"]["1gal"]["price"] == 39.99

    assert "3gal" in result["sizes"]
    assert result["sizes"]["3gal"]["price"] == 69.99


@responses.activate
def test_html_aria_label_filters_packs(no_sleep):
    """HTML fallback should filter out pack variants from aria-labels."""
    html = load_fixture("fgt", "limelight-hydrangea-page.html")
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea.json",
        status=404,
    )
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/limelight-hydrangea",
        body=html,
        status=200,
    )
    _add_robots("https://www.fgt.com")

    scraper = ShopifyScraper("fgt", "https://www.fgt.com")
    result = scraper.scrape_product("limelight-hydrangea")

    # 3-Pack should NOT appear in sizes
    for tier_data in result["sizes"].values():
        assert "pack" not in tier_data["raw_size"].lower()


@responses.activate
def test_html_aria_label_was_price(no_sleep):
    """HTML fallback correctly extracts was_price when list > sale."""
    html = load_fixture("fgt", "limelight-hydrangea-page.html")
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/test.json",
        status=404,
    )
    responses.add(
        responses.GET,
        "https://www.fgt.com/products/test",
        body=html,
        status=200,
    )
    _add_robots("https://www.fgt.com")

    scraper = ShopifyScraper("fgt", "https://www.fgt.com")
    result = scraper.scrape_product("test")

    assert result is not None
    # 1 Gallon: sale 39.99, list 49.99 → was_price = 49.99
    assert result["sizes"]["1gal"]["was_price"] == 49.99


# --- Promo code detection ---


@responses.activate
def test_promo_code_extraction(no_sleep):
    """Promo code scraper extracts valid codes from homepage announcement bars."""
    html = load_fixture("fgt", "homepage-with-promo.html")
    responses.add(
        responses.GET,
        "https://www.fgt.com",
        body=html,
        status=200,
    )

    scraper = ShopifyScraper("fgt", "https://www.fgt.com")
    promos = scraper.scrape_promo_codes()

    codes = [p["code"] for p in promos]
    assert "SPRING25" in codes


@responses.activate
def test_promo_code_rejects_false_positives(no_sleep):
    """Common words like FREE, SHIP, SALE should not be extracted as promo codes."""
    html = """<html><head><title>Test</title></head><body>
    <div class="announcement-bar">
        <p>FREE shipping on all orders! SALE ends today. Use code BLOOM30 for 30% off.</p>
    </div></body></html>"""
    responses.add(
        responses.GET,
        "https://test.com",
        body=html,
        status=200,
    )

    scraper = ShopifyScraper("test", "https://test.com")
    promos = scraper.scrape_promo_codes()

    codes = [p["code"] for p in promos]
    assert "BLOOM30" in codes
    assert "FREE" not in codes
    assert "SALE" not in codes
    assert "SHIP" not in codes


@responses.activate
def test_promo_code_empty_on_no_promos(no_sleep):
    """Returns empty list when homepage has no promo codes."""
    html = """<html><head><title>Test</title></head><body>
    <header><nav>Home</nav></header>
    <main><p>Welcome to our store.</p></main>
    </body></html>"""
    responses.add(
        responses.GET,
        "https://test.com",
        body=html,
        status=200,
    )

    scraper = ShopifyScraper("test", "https://test.com")
    promos = scraper.scrape_promo_codes()

    assert promos == []


@responses.activate
def test_promo_code_handles_request_failure(no_sleep):
    """Returns empty list when homepage request fails."""
    responses.add(
        responses.GET,
        "https://test.com",
        body=req_lib.ConnectionError("Connection refused"),
    )

    scraper = ShopifyScraper("test", "https://test.com")
    promos = scraper.scrape_promo_codes()

    assert promos == []
