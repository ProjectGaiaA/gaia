"""FGT `?variant=` deep links: the scraper must persist the Shopify variant id.

PROVENANCE OF THE FIXTURE -- read this before changing it.

`fgt/leyland-cypress-variant-ids.html` was MECHANICALLY EXTRACTED from the
real cached page `audit/html/leyland-cypress__fgt.html`: its schema.org Offer
objects and its size-button markup are copied verbatim, not retyped. That
matters because of the stark-bros lesson -- a hand-written fixture with a
plausible-looking but wrong key shape passes every test and fails on live
data. Here the shape is FGT's own: prices nested in a `priceSpecification`
LIST (never a flat `"price"` key), the sale entry untyped and the was-price
entry carrying `priceType: StrikethroughPrice`, and the variant id living in
the Offer's `sku`.

The 6-7 ft case is the one the owner verified BY HAND in a browser:
?variant=13940768374836 preselected 6-7 ft at $323.95 -- NOT FGT's default
1-2 ft. The selected size being the requested one rather than the default is
what proves the parameter survived the request and drove selection, so the
verification carries over to the canonical handle unchanged. That number is
an external fact, not a value this code produced.

HANDLE vs PLANT ID. FGT's real product handle is `leylandcypress` (the page's
own canonical link and og:url, and what handle_maps.json stores); the owner's
`leyland-cypress` spelling merely redirects to it. This file and the fixture
are NAMED for the plant id `leyland-cypress`, matching data/prices/ and the
cached corpus -- the two are different identifiers and both spellings here
are deliberate.
"""

import json

import responses

from scrapers.shopify import ShopifyScraper, _variant_id_from_sku
from tests.conftest import load_fixture


BASE = "https://www.fgt.com"


def _add_robots(base_url=BASE):
    responses.add(responses.GET, f"{base_url}/robots.txt",
                  body="User-agent: *\nAllow: /", status=200)


def _serve(handle, html):
    """JSON endpoint 404s -> the HTML path runs, exactly as it does for FGT."""
    responses.add(responses.GET, f"{BASE}/products/{handle}.json", status=404)
    responses.add(responses.GET, f"{BASE}/products/{handle}", body=html, status=200)
    _add_robots()


def _scrape(handle, html):
    _serve(handle, html)
    return ShopifyScraper("fgt", BASE).scrape_product(handle)


# --- 1. the id is persisted, and it is the RIGHT id -----------------------


@responses.activate
def test_aria_path_persists_variant_id(no_sleep):
    """Every readable size carries the variant id from its own Offer."""
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    result = _scrape("leyland-cypress", html)

    assert result is not None
    assert result["sizes"]["quart"]["variant_id"] == 39743443959870
    assert result["sizes"]["1-2ft"]["variant_id"] == 13940768145460
    assert result["sizes"]["2-3ft"]["variant_id"] == 13940768178228
    # Hand-verified in a browser by the owner: this id preselects 6-7 ft
    # at $323.95 on the live storefront.
    assert result["sizes"]["6-7ft"]["variant_id"] == 13940768374836
    assert result["sizes"]["6-7ft"]["price"] == 323.95


@responses.activate
def test_variant_id_is_int_matching_the_json_path(no_sleep):
    """Type parity with the five retailers already storing ids.

    All 150,961 historical cells that carry `variant_id` store an int (the
    JSON path writes Shopify's numeric `id` straight through). A str here
    would still render, so only a type assertion catches the drift.
    """
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    result = _scrape("leyland-cypress", html)
    for tier, size in result["sizes"].items():
        assert isinstance(size["variant_id"], int), (tier, size["variant_id"])
        assert not isinstance(size["variant_id"], bool)


# --- 2. a malformed sku stores NOTHING, never garbage --------------------


def test_variant_id_from_sku_rejects_non_digit_bases():
    """The guard is [0-9] only -- `str.isdigit()` is not good enough.

    Arabic-Indic digits and a superscript two both satisfy str.isdigit();
    int() accepts the first and RAISES on the second. Either would be a
    fabricated or a fatal variant id.
    """
    assert _variant_id_from_sku("13940768374836") == 13940768374836
    assert _variant_id_from_sku("13940768374836-10PACK") == 13940768374836
    # 43 of the 644 Offers on the cached FGT pages carry an EMPTY sku.
    assert _variant_id_from_sku("") is None
    assert _variant_id_from_sku(None) is None
    assert _variant_id_from_sku("ABC") is None
    assert _variant_id_from_sku("12ab") is None
    assert _variant_id_from_sku("12.5") is None
    assert _variant_id_from_sku(" 12 ") is None
    assert _variant_id_from_sku("٣٤") is None
    assert _variant_id_from_sku("²") is None


@responses.activate
def test_malformed_sku_yields_no_variant_id_key(no_sleep):
    """A page whose Offer sku is not an id still publishes its price, without one.

    The cell must fall back to the bare product URL rather than deep link to
    something invented.
    """
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    broken = html.replace('"sku":"13940768374836"', '"sku":"NOT-AN-ID"')
    assert broken != html
    result = _scrape("leyland-cypress", broken)

    assert result["sizes"]["6-7ft"]["price"] == 323.95      # price still read
    assert "variant_id" not in result["sizes"]["6-7ft"]     # but no id
    # its neighbours are unaffected
    assert result["sizes"]["2-3ft"]["variant_id"] == 13940768178228


@responses.activate
def test_ambiguous_price_withholds_the_id(no_sleep):
    """Two variants at one price cannot identify either -- publish no link.

    Real case: ajuga-chocolate-chip lists a retired 3.5-inch pot and a live
    1-quart both payable at $35.95. Guessing would deep link a shopper to a
    variant they cannot buy.
    """
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    # give a second, different variant the same payable price as 2-3 feet
    collided = html.replace('"sku":"13940768374836"', '"sku":"99999999999999"')
    collided = collided.replace('"price":"323.95"', '"price":"43.95"')
    result = _scrape("leyland-cypress", collided)

    assert "variant_id" not in result["sizes"]["2-3ft"]
    assert result["sizes"]["2-3ft"]["price"] == 43.95
    assert result["sizes"]["1-2ft"]["variant_id"] == 13940768145460


# --- 3. packs and bundles never attach an id to a published size ---------


@responses.activate
def test_pack_offer_never_supplies_a_variant_id(no_sleep):
    """The -10PACK Offer in the fixture must not become anyone's deep link."""
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    assert "39743443959870-10PACK" in html   # the fixture really carries one
    result = _scrape("leyland-cypress", html)

    prices = {s["price"] for s in result["sizes"].values()}
    # the pack's own price never became a published size...
    assert 239.60 not in prices
    # ...and every published id is a real int from a single-plant Offer.
    for size in result["sizes"].values():
        assert isinstance(size.get("variant_id"), int)


@responses.activate
def test_pack_offer_sharing_a_price_does_not_poison_the_cell(no_sleep):
    """A pack whose price collides with a real size must not disturb its id.

    Pack SKUs are skipped BEFORE their price is bucketed. Without that skip
    the collision would make $43.95 ambiguous and silently drop a working
    deep link -- and on a page whose single-plant Offer carries an empty sku
    (43 of the 644 real Offers do) the pack's own id would be attached to a
    single-plant cell instead, deep linking the shopper to a 10-pack.

    This is the only test that fails when the pack skip is removed.
    """
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    # make the 10-PACK payable price equal the 2-3 feet single-plant price
    collide = html.replace(
        '"sku":"39743443959870-10PACK","priceSpecification":'
        '[{"@type":"UnitPriceSpecification","price":"239.60"',
        '"sku":"39743443959870-10PACK","priceSpecification":'
        '[{"@type":"UnitPriceSpecification","price":"43.95"',
    )
    assert collide != html
    result = _scrape("leyland-cypress", collide)

    # the single-plant variant keeps its own id, unpoisoned by the pack
    assert result["sizes"]["2-3ft"]["variant_id"] == 13940768178228
    assert result["sizes"]["2-3ft"]["price"] == 43.95


@responses.activate
def test_all_bundle_page_publishes_no_sizes_and_no_ids(no_sleep):
    """A page whose every readable size is a bundle publishes an EMPTY row.

    The merged bundle handling withholds those sizes; this pins that no
    variant id sneaks back in through the empty-row branch.
    """
    html = load_fixture("fgt", "leyland-cypress-variant-ids.html")
    bogo = html.replace(" - 44% OFF", " - Buy 1, Get 1 Free")
    bogo = bogo.replace(" - 31% OFF", " - Buy 1, Get 1 Free")
    bogo = bogo.replace(" - 1% OFF", " - Buy 1, Get 1 Free")
    bogo = bogo.replace("1 quart - Price $29.95",
                        "1 quart - Buy 1, Get 1 Free - Price $29.95")
    result = _scrape("leyland-cypress", bogo)

    assert result is not None
    assert result["sizes"] == {}
    assert result["all_offers_bundled"] is True
    assert result["no_sizes_readable"] is True
    assert "?variant=" not in result["url"]


# --- 4. the JSON path (the other five retailers) is untouched ------------


@responses.activate
def test_json_path_variant_ids_unchanged(no_sleep):
    """The five retailers' path must keep behaving exactly as before."""
    product = {
        "product": {
            "title": "Limelight Hydrangea",
            "handle": "limelight-hydrangea",
            "variants": [
                {"id": 40508853223486, "title": "1 Quart", "price": "33.95",
                 "compare_at_price": None, "available": True},
                {"id": 39729259282494, "title": "1 Gallon", "price": "46.95",
                 "compare_at_price": "56.95", "available": False},
                {"id": 11111111111111, "title": "3 Plant(s)", "price": "99.95",
                 "compare_at_price": None, "available": True},
            ],
        }
    }
    responses.add(responses.GET, f"{BASE}/products/limelight-hydrangea.json",
                  body=json.dumps(product), status=200)
    responses.add(responses.GET, f"{BASE}/products/limelight-hydrangea.js",
                  status=404)
    _add_robots()
    result = ShopifyScraper("fgt", BASE).scrape_product("limelight-hydrangea")

    assert result["sizes"]["quart"]["variant_id"] == 40508853223486
    assert result["sizes"]["1gal"]["variant_id"] == 39729259282494
    # multi-plant pack filtered out entirely -- no tier, so no id
    assert not any(s.get("variant_id") == 11111111111111
                   for s in result["sizes"].values())
    # the JSON path still deep links the product URL to the cheapest variant
    assert result["url"].endswith("?variant=40508853223486")


# --- 5. a MERCHANT sku must never be minted into a variant id ------------


def test_merchant_sku_is_not_a_variant_id():
    """Digits alone are not enough -- magnitude separates the two id spaces.

    `_scrape_product_html` is the generic `.json`-404 fallback for EVERY
    Shopify retailer, not an FGT-only path, and the other stores put a short
    MERCHANT sku in the Offer where FGT puts the variant id. "15449" and
    "13861" are real examples, read off FGT's own catalog API next to variant
    ids 40508853223486 and 39729259282494.

    Measured floor: all 150,961 historical variant ids across the five
    retailers that store them are 11-14 digits (11:7713, 12:2136, 13:15119,
    14:125993), and all 601 non-empty FGT Offer sku bases are 14. So an
    11-digit minimum rejects nothing real. The module's own variant_names
    patterns use `\\d{10,}`; 11 is the measured floor and the extra digit is
    deliberate slack, not a conflict.
    """
    assert _variant_id_from_sku("15449") is None
    assert _variant_id_from_sku("13861") is None
    # The docstring has always promised "not 0". Before the magnitude guard
    # this returned the integer 0 -- falsy, so it rendered a bare URL by luck
    # rather than by rule.
    assert _variant_id_from_sku("0") is None
    assert _variant_id_from_sku("1234567890") is None            # 10 digits
    assert _variant_id_from_sku("12345678901") == 12345678901    # 11, accepted
    assert _variant_id_from_sku("40508853223486") == 40508853223486


@responses.activate
def test_non_fgt_shaped_page_mints_no_variant_id(no_sleep):
    """A non-FGT Shopify page must yield a price and NO deep link.

    HONEST PROVENANCE: this page is synthetic. No non-FGT retailer HTML is
    cached in the corpus, so it cannot be extracted the way the FGT fixture
    was. It is shaped from two facts the repo does hold: `_offer_payable_price`
    documents that every non-FGT Shopify theme in the corpus emits a FLAT
    `"price"` key, and the merchant skus are real values from FGT's catalog
    API. The guard under test is magnitude, which does not depend on which
    retailer served the page.

    Before the magnitude guard this minted
    `greatgardenplants.com/products/coneflower?variant=15449` -- a merchant
    sku in a `?variant=` parameter, which selects nothing.
    """
    page = (
        '<html><head><title>Coneflower | Great Garden Plants</title>'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","name":"Coneflower",'
        '"offers":[{"@type":"Offer","sku":"15449","price":"33.95",'
        '"availability":"https://schema.org/InStock"}]}'
        '</script></head><body>'
        '<button data-variant-id="15449">1 Gallon</button>'
        '</body></html>'
    )
    base = "https://www.greatgardenplants.com"
    responses.add(responses.GET, f"{base}/products/coneflower.json", status=404)
    responses.add(responses.GET, f"{base}/products/coneflower", body=page, status=200)
    _add_robots(base)

    scraper = ShopifyScraper("great-garden-plants", base)
    result = scraper.scrape_product("coneflower")

    assert result is not None
    # the price is still read and published...
    assert any(s["price"] == 33.95 for s in result["sizes"].values())
    # ...and not one cell carries a fabricated id
    for tier, size in result["sizes"].items():
        assert "variant_id" not in size, (tier, size)
    assert "?variant=" not in result["url"]
