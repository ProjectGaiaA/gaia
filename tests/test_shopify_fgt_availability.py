"""FGT availability: read it, do not default it.

THE DEFECT. Fast Growing Trees had never recorded a single sold-out size.
Measured across the whole price history: 34,896 cells `available: True`, 2
`None`, and zero `False` — ever. Every "In Stock" the site published for FGT
was a hardcoded default rather than a reading.

THE MECHANISM. `_availability_by_price` sourced its Offers from
`_SCHEMA_OFFER_RE`, which requires a flat `"price"` key inside the Offer
object. FGT does not emit one: it nests prices in `priceSpecification`, and
emits TWO entries for a discounted variant (the payable price, and the
strikethrough it was reduced from). So the regex matched 0 of 644 Offers
across the 66 cached FGT pages, `_availability_by_price` returned `{}` for
every page, and the caller's "this page carries no stock data at all" fallback
fired for every size button:

    if available is None and not avail_by_price:
        available = True

The module already knew. `_offers_from_ld_json`'s docstring has said
"0-for-172 on real FGT Offers, which nest price inside priceSpecification"
since it was written — but only the sold-out branch ever called it.

MEASURED EFFECT OF THE FIX, on the 66 cached pages, against the
`availableForSale` flags in the page's own turbo-stream loader payload (a
different serializer, and the one that greys out the button in the shopper's
browser): agreement went from 139/303 (45.9%) to 301/301 (100%). 170 of 319
published cells flip to sold out.

Every fixture below is FGT's real Offer shape, not the flat-`"price"` shape.
The pre-existing tests in test_shopify_fgt_sizes.py all use the flat shape,
which is why a retailer with a 100%-broken availability path had a green
suite: they exercised a format FGT does not emit.
"""

import json
import logging

import responses

from scrapers.shopify import ShopifyScraper, _offer_payable_price
from tests.conftest import load_fixture

BASE = "https://www.fgt.com"


def _scrape(handle, html):
    responses.add(responses.GET, f"{BASE}/products/{handle}.json", status=404)
    responses.add(responses.GET, f"{BASE}/products/{handle}", body=html, status=200)
    return ShopifyScraper("fast-growing-trees", BASE).scrape_product(handle)


def _page(offers, buttons):
    """A page in FGT's real shape: @graph-wrapped ld+json, aria-label buttons."""
    ld = {"@context": "https://schema.org",
          "@graph": [{"@type": "Product", "name": "T", "offers": offers}]}
    b = "".join(
        f'<button type="button" aria-label="{lab}">{lab.split(" - ")[0]}</button>'
        for lab in buttons)
    return (
        "<html><head><title>Test Plant | FGT</title>"
        f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        "</head><body><section><h2>Select size</h2>"
        f"{b}</section></body></html>"
    )


def _spec(price, was=None):
    """FGT's priceSpecification: payable entry first, strikethrough second."""
    out = [{"@type": "UnitPriceSpecification", "price": price, "priceCurrency": "USD"}]
    if was is not None:
        out.append({"@type": "UnitPriceSpecification", "price": was,
                    "priceCurrency": "USD",
                    "priceType": "https://schema.org/StrikethroughPrice"})
    return out


# ---------------------------------------------------------------------------
# 1. The defect itself. This test FAILS on the shipped code.
# ---------------------------------------------------------------------------


@responses.activate
def test_sold_out_size_is_read_from_nested_pricespecification(no_sleep):
    """THE REGRESSION TEST. Real FGT Offer shape, one size genuinely sold out.

    Shipped code: _SCHEMA_OFFER_RE matches neither Offer, the availability map
    is empty, the "no stock data" fallback fires, and BOTH sizes report
    available=True. Asserting False here is what the shipped code cannot do.
    """
    html = _page(
        offers=[
            {"@type": "Offer", "sku": "111",
             "priceSpecification": _spec("24.99"),
             "availability": "https://schema.org/InStock"},
            {"@type": "Offer", "sku": "222",
             "priceSpecification": _spec("49.99", "59.99"),
             "availability": "https://schema.org/OutOfStock"},
        ],
        buttons=["1 gallon - Price $24.99",
                 "3 gallon - Original price $59.99, sale price $49.99 - 16% OFF"],
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True
    assert result["sizes"]["3gal"]["available"] is False, (
        "a priceSpecification-nested OutOfStock Offer was reported in stock — "
        "this is the defect: the availability map never saw FGT's Offers")
    assert result["in_stock"] is True  # one size still buyable


@responses.activate
def test_real_cached_fgt_page_reports_two_of_three_sizes_sold_out(no_sleep):
    """Verbatim ld+json Offers and size buttons from the cached
    chocolate-chip-ajuga page (2026-08-11).

    Ground truth from the same page's turbo-stream loader payload, which is a
    different serializer and is what disables the button in the browser:
        3.5 Inch Pot $35.95  availableForSale false   (hidden, no button)
        4 Inch       $19.95  availableForSale false
        1 Quart      $35.95  availableForSale true
        1 Gallon     $43.95  availableForSale false

    The shipped code published all three buttons as In Stock. Two of them
    were not buyable.
    """
    result = _scrape("chocolate-chip-ajuga-plant",
                     load_fixture("fgt", "ajuga-pricespec-page.html"))

    assert result["sizes"]["4inch"]["price"] == 19.95
    assert result["sizes"]["4inch"]["available"] is False
    assert result["sizes"]["1gal"]["price"] == 43.95
    assert result["sizes"]["1gal"]["available"] is False
    # $35.95 is claimed by BOTH the sold-out hidden "3.5 Inch Pot" variant and
    # the in-stock "1 Quart" one. Price alone cannot tell them apart, so this
    # cell stays unknown rather than guessing either way.
    assert result["sizes"]["quart"]["available"] is None
    # Row aggregate: UNKNOWN, not sold out. The quart really is buyable -- the
    # live page reports 584 units -- and we simply cannot prove which variant
    # owns the $35.95. Reporting the row sold out would grey out every cell and
    # withdraw a working affiliate link over a cell we could not read.
    #
    # This assertion previously read `is False`, pinning that exact bug as
    # correct. An unknown size must block a sold-out verdict; only a size we
    # positively read as unavailable may contribute to one.
    assert result["in_stock"] is None


# ---------------------------------------------------------------------------
# 2. priceType selection. Kills the "take priceSpecification[0]" mutant.
# ---------------------------------------------------------------------------


def test_payable_price_is_chosen_by_priceType_not_by_position():
    """KILLS THE POSITION MUTANT.

    On every one of FGT's 430 two-entry Offers the payable entry happens to be
    index 0 today, so `spec[0]` and "the entry whose priceType is not a
    reference price" produce identical price maps on live data. A test that
    asserts on the resulting prices cannot tell them apart — mutation testing
    confirmed `spec[0]` survives every such assertion.

    They are NOT the same rule. schema.org does not order priceSpecification.
    Assert the rule, on input where the two disagree.
    """
    reversed_order = {
        "@type": "Offer", "sku": "13940811038772",
        "priceSpecification": [
            {"@type": "UnitPriceSpecification", "price": "100.95",
             "priceCurrency": "USD",
             "priceType": "https://schema.org/StrikethroughPrice"},
            {"@type": "UnitPriceSpecification", "price": "69.95",
             "priceCurrency": "USD"},
        ],
        "availability": "https://schema.org/InStock",
    }
    assert _offer_payable_price(reversed_order) == "69.95", (
        "took the FIRST priceSpecification entry — that is the strikethrough "
        "price here, and keying stock state on it points at a price no button "
        "carries")

    # And the same Offer in FGT's live order still reads correctly, so the
    # rule is genuinely priceType-driven and not "take the last one".
    fgt_order = dict(reversed_order,
                     priceSpecification=list(reversed(
                         reversed_order["priceSpecification"])))
    assert _offer_payable_price(fgt_order) == "69.95"


def test_payable_price_is_not_the_cheapest_entry():
    """KILLS THE MIN MUTANT. `min(entries)` also matches live FGT data,
    because a discount makes the strikethrough the larger number. It breaks on
    a PRICE RISE, where the old price is the smaller one — and a nursery
    raising a price mid-season is ordinary."""
    price_rise = {
        "@type": "Offer", "sku": "999",
        "priceSpecification": [
            {"@type": "UnitPriceSpecification", "price": "89.95",
             "priceCurrency": "USD"},
            {"@type": "UnitPriceSpecification", "price": "49.95",
             "priceCurrency": "USD",
             "priceType": "https://schema.org/StrikethroughPrice"},
        ],
        "availability": "https://schema.org/InStock",
    }
    assert _offer_payable_price(price_rise) == "89.95", (
        "took the cheapest entry — that is last season's price, not what a "
        "shopper pays")


def test_reference_price_types_never_become_the_payable_price():
    """Every reference priceType, not just StrikethroughPrice. An Offer whose
    only entries are reference prices has NO payable price, and must return
    None (no signal) rather than volunteering one of them."""
    for ptype in ("https://schema.org/StrikethroughPrice",
                  "https://schema.org/ListPrice",
                  "https://schema.org/MSRP",
                  "https://schema.org/MinimumAdvertisedPrice",
                  "https://schema.org/InvoicePrice"):
        offer = {"@type": "Offer", "sku": "1", "priceSpecification": [
            {"@type": "UnitPriceSpecification", "price": "11.11",
             "priceCurrency": "USD", "priceType": ptype}]}
        assert _offer_payable_price(offer) is None, (
            f"{ptype} was treated as the price a shopper pays")

    # SalePrice is stated explicitly by some themes and IS payable.
    assert _offer_payable_price(
        {"@type": "Offer", "priceSpecification": [
            {"price": "12.34", "priceType": "https://schema.org/SalePrice"}]}
    ) == "12.34"


def test_ambiguous_offer_supplies_no_availability_signal():
    """Two entries both claiming to be payable, or an unrecognised priceType
    on the only entry: we cannot say what it costs. Withhold rather than
    guess — a map entry keyed on a guessed price attaches stock state to the
    wrong button."""
    two_payable = {"@type": "Offer", "sku": "1", "priceSpecification": [
        {"price": "10.00"}, {"price": "20.00"}]}
    assert _offer_payable_price(two_payable) is None

    unknown_type = {"@type": "Offer", "sku": "1", "priceSpecification": [
        {"price": "10.00", "priceType": "https://schema.org/SomethingNew"}]}
    assert _offer_payable_price(unknown_type) is None


def test_unrecognised_priceType_is_logged_as_drift(caplog):
    """The allowlist's failure mode is silent: if FGT renamed the payable
    entry, every Offer would be skipped, the map would empty, and the caller's
    "no stock data on this page" fallback would restore available=True for
    everything — the original defect, back, looking exactly like a page with
    no Offers. It must be noisy instead."""
    offer = {"@type": "Offer", "sku": "555", "priceSpecification": [
        {"price": "10.00", "priceType": "https://schema.org/SomethingNew"}]}
    with caplog.at_level(logging.WARNING, logger="scrapers.shopify"):
        assert _offer_payable_price(offer) is None
    assert "unrecognised schema.org priceType" in caplog.text
    assert "555" in caplog.text

    # And the types we DO know must stay quiet, or the alarm is worthless.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scrapers.shopify"):
        _offer_payable_price({"@type": "Offer", "sku": "1",
                              "priceSpecification": _spec("69.95", "100.95")})
    assert caplog.text == ""


@responses.activate
def test_strikethrough_price_does_not_key_the_availability_map(no_sleep):
    """End-to-end form of the position rule. The sold-out variant's WAS price
    ($59.99) coincides with another size's payable price. If the strikethrough
    entry ever reached the map, the $59.99 button would inherit "sold out"
    from a variant it has nothing to do with."""
    html = _page(
        offers=[
            {"@type": "Offer", "sku": "111",
             "priceSpecification": _spec("49.99", "59.99"),
             "availability": "https://schema.org/OutOfStock"},
            {"@type": "Offer", "sku": "222",
             "priceSpecification": _spec("59.99"),
             "availability": "https://schema.org/InStock"},
        ],
        buttons=["1 gallon - Original price $59.99, sale price $49.99 - 16% OFF",
                 "3 gallon - Price $59.99"],
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is False
    assert result["sizes"]["3gal"]["available"] is True, (
        "the sold-out variant's strikethrough price leaked into the "
        "availability map and marked an in-stock size as gone")


# ---------------------------------------------------------------------------
# 2b. A missing field is not a fact. Found by adversarial probe, not by review.
# ---------------------------------------------------------------------------


@responses.activate
def test_offer_without_an_availability_field_is_unknown_not_sold_out(no_sleep):
    """REGRESSION THE FIX ITSELF INTRODUCED, caught before shipping.

    _SCHEMA_OFFER_RE could only ever match an Offer that HAD an `availability`
    value, so the old map never saw Offers that omit it. Parsing the JSON
    newly admits them — and read through `_is_orderable` alone, an absent key
    scores False and publishes "Sold Out" against a size on the strength of
    nothing. The probe measured exactly that: {"sku":"1","price":"9.99"} came
    back {9.99: False}.

    Absence is not a reading. It must stay unknown.
    """
    html = _page(
        offers=[{"@type": "Offer", "sku": "111",
                 "priceSpecification": _spec("24.99")}],  # no availability key
        buttons=["1 gallon - Price $24.99"],
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is None, (
        "an Offer with no availability field was published as SOLD OUT")
    assert result["in_stock"] is None


@responses.activate
def test_unrecognised_availability_value_is_unknown_not_sold_out(no_sleep):
    """Same rule for a value we do not recognise.

    The module keeps two allowlists on purpose — `_ORDERABLE_AVAILABILITY`
    (positively buyable) and `_DEFINITELY_UNAVAILABLE` (positively not) — and
    a value on neither list is genuinely unknown. `PreSale` is the documented
    example: it is NOT on the orderable list, and the existing suite already
    pins that it must not count as sold out either. Unknown is the only
    answer left, and it is the right one.
    """
    html = _page(
        offers=[
            {"@type": "Offer", "sku": "111", "priceSpecification": _spec("24.99"),
             "availability": "https://schema.org/BackOrder"},
            {"@type": "Offer", "sku": "222", "priceSpecification": _spec("39.99"),
             "availability": "https://schema.org/PreSale"},
            {"@type": "Offer", "sku": "333", "priceSpecification": _spec("59.99"),
             "availability": "wat"},
            {"@type": "Offer", "sku": "444", "priceSpecification": _spec("79.99"),
             "availability": "https://schema.org/SoldOut"},
        ],
        buttons=["1 gallon - Price $24.99", "2 gallon - Price $39.99",
                 "3 gallon - Price $59.99", "5 gallon - Price $79.99"],
    )
    result = _scrape("test-plant", html)

    # On the orderable allowlist: a shopper can place the order.
    assert result["sizes"]["1gal"]["available"] is True
    # On neither allowlist -> withhold the claim rather than invent one.
    assert result["sizes"]["2gal"]["available"] is None
    assert result["sizes"]["3gal"]["available"] is None
    # Positively unavailable -> and only this one may say so.
    assert result["sizes"]["5gal"]["available"] is False


# ---------------------------------------------------------------------------
# 3. The all_gone control must still fire, on FGT's real Offer shape.
# ---------------------------------------------------------------------------


@responses.activate
def test_all_gone_control_still_fires_on_nested_pricespecification(no_sleep):
    """THE CONTROL. When FGT sells out of every size it strips the size
    selector entirely, leaving Offers but no readable buttons. That page must
    publish a loud sold-out row (in_stock False, sizes {}, no_sizes_readable
    True) rather than being withheld as markup drift.

    Asserted on FGT's REAL Offer shape. The shipped test for this branch uses
    flat-`"price"` Offers, so it could not have noticed if the change to the
    availability path had disturbed it.
    """
    html = (
        "<html><head><title>Russian Sage | FGT</title>"
        '<script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@graph": [
            {"@type": "Product", "name": "Russian Sage", "offers": [
                {"@type": "Offer", "sku": "111",
                 "priceSpecification": _spec("24.95", "31.95"),
                 "availability": "https://schema.org/OutOfStock"},
                {"@type": "Offer", "sku": "222",
                 "priceSpecification": _spec("38.95"),
                 "availability": "https://schema.org/OutOfStock"},
                {"@type": "Offer", "sku": "222-4PACK",
                 "priceSpecification": _spec("140.95"),
                 "availability": "https://schema.org/OutOfStock"}]}]})
        + "</script></head><body><h2>Select size</h2>"
        "<p>Currently unavailable</p></body></html>"
    )
    result = _scrape("russian-sage", html)

    assert result is not None, "a genuinely sold-out product was withheld as drift"
    assert result["in_stock"] is False
    assert result["sizes"] == {}, "no size may be fabricated from an Offer SKU"
    assert result["no_sizes_readable"] is True, (
        "the drift alarm was silenced — runner.py needs this flag to keep "
        "counting an empty row separately from a successful price read")


@responses.activate
def test_all_gone_control_does_not_fire_when_one_size_is_still_buyable(no_sleep):
    """The control's boundary, also on the real shape. One orderable Offer
    among the sold-out ones means a price exists that we cannot attribute to
    a size. That is drift: withhold and alarm, never publish a sold-out row."""
    html = (
        "<html><head><title>Drifted | FGT</title>"
        '<script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@graph": [
            {"@type": "Product", "name": "Drifted", "offers": [
                {"@type": "Offer", "sku": "111",
                 "priceSpecification": _spec("24.95"),
                 "availability": "https://schema.org/OutOfStock"},
                {"@type": "Offer", "sku": "222",
                 "priceSpecification": _spec("38.95"),
                 "availability": "https://schema.org/InStock"}]}]})
        + "</script></head><body><h2>Select size</h2>"
        "<p>nothing readable</p></body></html>"
    )
    assert _scrape("drifted-product", html) is None


# ---------------------------------------------------------------------------
# 4. Do not break the retailers that were never broken.
# ---------------------------------------------------------------------------


@responses.activate
def test_flat_price_offers_still_supply_availability(no_sleep):
    """Every other Shopify theme in the corpus emits a flat `"price"`, and 43
    of FGT's own Offers do too.

    Note this ALSO fails on the shipped code, for a second reason worth
    recording: the ld+json here is pretty-printed (`"sku": "111"`), and
    _SCHEMA_OFFER_RE demands `"sku":"111"` with no space. So the shipped
    availability path was blind to any Offer a theme chose to indent, nested
    price or not. Parsing the JSON removes that whole class of dependence on
    whitespace and key order.
    """
    html = _page(
        offers=[
            {"@type": "Offer", "sku": "111", "price": "24.99",
             "availability": "https://schema.org/InStock"},
            {"@type": "Offer", "sku": "222", "price": "49.99",
             "availability": "https://schema.org/OutOfStock"},
        ],
        buttons=["1 gallon - Price $24.99", "3 gallon - Price $49.99"],
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True
    assert result["sizes"]["3gal"]["available"] is False


@responses.activate
def test_pack_offers_still_excluded_when_price_is_nested(no_sleep):
    """The pack filter reads the SKU suffix, which is unaffected by where the
    price lives — but a pack Offer sharing a single-plant price would poison
    the map, so prove it on the nested shape too.

    Honest note: this one PASSES on the shipped code too, vacuously — there
    the map is empty and the fallback returns True for the wrong reason. It
    earns its place only as a guard against a future change that drops the
    pack filter, not as evidence of the defect.
    """
    html = _page(
        offers=[
            {"@type": "Offer", "sku": "111-10PACK",
             "priceSpecification": _spec("24.99"),
             "availability": "https://schema.org/OutOfStock"},
            {"@type": "Offer", "sku": "111",
             "priceSpecification": _spec("24.99"),
             "availability": "https://schema.org/InStock"},
        ],
        buttons=["1 gallon - Price $24.99"],
    )
    assert _scrape("test-plant", html)["sizes"]["1gal"]["available"] is True


@responses.activate
def test_unparseable_ld_json_falls_back_to_the_regex(no_sleep):
    """Two Offer objects concatenated inside one <script> is not valid JSON.
    The regex is kept as a fallback for exactly that, so such a page still
    yields stock data instead of silently losing it."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        "<h2>Select size</h2>"
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


@responses.activate
def test_page_with_no_offers_at_all_keeps_the_legacy_assumption(no_sleep):
    """No stock data from either source: no signal either way, so a priced,
    rendered size button stays available. Unchanged behaviour — but it is the
    fallback the defect was hiding behind, so it is pinned here."""
    html = (
        "<html><head><title>Test Plant | FGT</title></head><body>"
        "<h2>Select size</h2>"
        '<button aria-label="1 gallon - Price $24.99">1 gallon</button>'
        "</section></body></html>"
    )
    result = _scrape("test-plant", html)

    assert result["sizes"]["1gal"]["available"] is True
    assert result["in_stock"] is True
