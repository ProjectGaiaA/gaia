"""A page whose EVERY offer is a bundle must clear its cells, not go silent.

`306c0a4f` taught the scraper to withhold any offer whose text carries a
Buy-1-Get-1 marker: a bundle price buys two plants, and publishing it in a size
column beside another nursery's single plant is a false comparison. Withholding
is right. Halving it would be worse — it invents a price the retailer never
listed.

What `306c0a4f` did not consider is a page where EVERY size is a bundle. Every
offer was withheld, `_extract_aria_size_offers` returned empty, and that is
indistinguishable from "the aria-label format drifted and we could read
nothing". The drift guard fired, `scrape_product` returned None, and NO ROW WAS
WRITTEN — so build.py's `get_latest_prices`, which takes the newest row per
(plant, retailer), kept serving the last row written BEFORE the bundle filter
existed. fast-growing-trees/bloodgood-japanese-maple went on publishing six
Buy-1-Get-1 prices as the price of one tree, two of them wearing the green
best-price badge, for as long as the page stayed on offer.

    Silence does not withdraw a price. Only a row does.

The two states are told apart by whether any aria-label PARSED. A withheld
bundle offer carries a name and a numeric price, which is proof the format has
not drifted; under real drift nothing matches and the loud guard is untouched.
That is deliberate: the escape hatch must not be satisfiable by the failure
mode it is being told apart from (GAIA_FINAL_PLAN R5).

All HTTP is mocked. No live retailer is reached.
"""

import json
import logging
from datetime import date
from unittest.mock import patch

import jinja2
import responses
from bs4 import BeautifulSoup

import build
from scrapers.shopify import ShopifyScraper
from tests.conftest import load_build_fixture

BASE = "https://www.fgt.com"


def _register(handle, html):
    """JSON endpoint 404s (as FGT's does) so the HTML fallback runs."""
    responses.add(responses.GET, f"{BASE}/products/{handle}.json", status=404)
    responses.add(responses.GET, f"{BASE}/products/{handle}", body=html, status=200)


def _scrape(handle, html):
    _register(handle, html)
    return ShopifyScraper("fast-growing-trees", BASE).scrape_product(handle)


def _offer(sku, price, avail="InStock"):
    return (
        f'{{"@type":"Offer","sku":"{sku}","price":"{price}",'
        f'"availability":"https://schema.org/{avail}"}}'
    )


# bloodgood-japanese-maple as the live page reads: every height a two-for-one.
# The heights and prices are the ones the stale row still publishes today.
_ALL_BUNDLE = (
    "<html><head><title>Bloodgood Japanese Maple | FGT</title></head><body>"
    "<h2>Select size</h2>"
    '<button aria-label="1-2 feet - Price $94.95 - Buy 1, Get 1">a</button>'
    '<button aria-label="2-3 feet - Price $116.95 - Buy 1, Get 1">b</button>'
    '<button aria-label="3-4 feet - Price $143.95 - Buy 1, Get 1">c</button>'
    '<button aria-label="4-5 feet - Price $176.95 - Buy 1, Get 1">d</button>'
    '<button aria-label="5-6 feet - Price $226.95 - Buy 1, Get 1">e</button>'
    '<button aria-label="6-7 feet - Price $266.95 - Buy 1, Get 1">f</button>'
    "</section>"
    '<script type="application/ld+json">'
    + ",".join(
        _offer(sku, p)
        for sku, p in zip(
            "111 222 333 444 555 666".split(),
            ["94.95", "116.95", "143.95", "176.95", "226.95", "266.95"],
        )
    )
    + "</script></body></html>"
)

# The same page with ONE single-plant size added. Nothing about the bundle
# handling may change for this shape — it is what 64 of the 66 cached FGT
# pages look like, and it is what the 2026-08-11 snapshot of bloodgood itself
# looked like.
_MIXED = _ALL_BUNDLE.replace(
    "<h2>Select size</h2>",
    '<h2>Select size</h2><button aria-label="1 gallon - Price $137.95">g</button>',
).replace('"availability":"https://schema.org/InStock"}</script>',
          '"availability":"https://schema.org/InStock"},'
          + _offer("777", "137.95") + "</script>")


# --- the scraper half -------------------------------------------------------


@responses.activate
def test_all_bundle_page_publishes_an_empty_row_instead_of_nothing(no_sleep):
    """The fix. A row must be written, because a row is the only thing that
    can displace the stale one."""
    result = _scrape("bloodgood-japanese-maple", _ALL_BUNDLE)
    assert result is not None, (
        "returned None — no row is appended, so build.py keeps publishing the "
        "last row written before the bundle filter existed"
    )
    assert result["sizes"] == {}
    assert result["all_offers_bundled"] is True


@responses.activate
def test_the_empty_row_never_carries_a_bundle_or_halved_price(no_sleep):
    """Withheld, not adjusted, and not smuggled in under another key."""
    result = _scrape("bloodgood-japanese-maple", _ALL_BUNDLE)
    blob = json.dumps(result)
    for bundle_price in (94.95, 116.95, 143.95, 176.95, 226.95, 266.95):
        assert str(bundle_price) not in blob, f"published the bundle price {bundle_price}"
        assert str(round(bundle_price / 2, 2)) not in blob, (
            f"invented a single-plant price by halving {bundle_price}"
        )


@responses.activate
def test_the_empty_row_makes_no_stock_claim(no_sleep):
    """`False` renders "Sold Out", which is untrue — the plant is on sale, as
    a pair. `True` renders "In Stock" beside a row of dashes, which reads as a
    fetch failure. We have no single-plant offer to make a claim about."""
    result = _scrape("bloodgood-japanese-maple", _ALL_BUNDLE)
    assert result["in_stock"] is None


@responses.activate
def test_the_empty_row_does_not_score_as_a_successful_price_read(no_sleep):
    """R6: publishing a fact must not silence a signal. runner.py subtracts
    `no_sizes_readable` rows from products_priced, which is the health input.
    Without this flag a retailer that put its whole catalogue on BOGO would
    report a perfect hit rate while the site showed not one of its prices."""
    result = _scrape("bloodgood-japanese-maple", _ALL_BUNDLE)
    assert result["no_sizes_readable"] is True


@responses.activate
def test_a_page_with_one_single_plant_size_still_publishes_that_size(no_sleep):
    """Zero collateral change. The empty-row branch is reachable only when
    NOTHING single-plant was readable."""
    result = _scrape("bloodgood-japanese-maple", _MIXED)
    assert {t: v["price"] for t, v in result["sizes"].items()} == {"1gal": 137.95}
    assert "all_offers_bundled" not in result
    assert "no_sizes_readable" not in result


# --- the guard that must NOT be weakened (R2) -------------------------------


@responses.activate
def test_real_drift_still_publishes_nothing_and_still_alarms(no_sleep, caplog):
    """The exact scenario the original guard handles: the aria format changes
    so nothing parses. There is then no evidence the page was read, so the
    empty-row branch must NOT fire — a wrong price is invisible, a gap is not.
    """
    drifted = _ALL_BUNDLE.replace(" - Price $", " – Price $")
    assert drifted != _ALL_BUNDLE
    with caplog.at_level(logging.ERROR):
        result = _scrape("bloodgood-japanese-maple", drifted)
    assert result is None, "drift published a row; the drift guard was weakened"
    assert any(
        "not one could be read" in r.message for r in caplog.records
        if r.levelno >= logging.ERROR
    ), "drift did not raise the loud alarm"


def test_drift_leaves_no_readable_bundle_offers_to_escape_on():
    """Asserted directly on the signal, so an unrelated parsing change cannot
    make the test above quietly vacuous. Under drift the withheld list is
    empty — the escape hatch is not satisfiable by the failure mode it is
    told apart from (R5)."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    drifted = _ALL_BUNDLE.replace(" - Price $", " – Price $")
    withheld = []
    assert scraper._extract_aria_size_offers(drifted, withheld_bundles=withheld) == []
    assert withheld == []


def test_the_withheld_list_reports_what_was_read_and_dropped():
    """The positive case of the same signal, with the sizes and prices the
    page really carries."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    withheld = []
    assert scraper._extract_aria_size_offers(_ALL_BUNDLE, withheld_bundles=withheld) == []
    assert withheld == [
        ("1-2 feet", 94.95, None),
        ("2-3 feet", 116.95, None),
        ("3-4 feet", 143.95, None),
        ("4-5 feet", 176.95, None),
        ("5-6 feet", 226.95, None),
        ("6-7 feet", 266.95, None),
    ]


def test_the_withheld_list_comes_from_the_pass_that_decided_the_outcome():
    """`_extract_aria_size_offers` reads the "Select size" section first and
    only falls through to the whole document if that yields nothing. A bundle
    button OUTSIDE the size selector must not make an unrelated page look
    deliberately withheld."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = (
        "<h2>Select size</h2>"
        '<button aria-label="1 gallon - Price $45.95">g</button>'
        "</section>"
        '<button aria-label="3-4 feet - Price $99.95 - Buy 1, Get 1">promo</button>'
    )
    withheld = []
    assert scraper._extract_aria_size_offers(html, withheld_bundles=withheld) == [
        ("1 gallon", 45.95, None)
    ]
    assert withheld == []


@responses.activate
def test_a_promo_outside_the_size_selector_cannot_vouch_for_a_drifted_one(no_sleep):
    """The nastiest shape: the size selector HAS drifted, and a "Buy 1, Get 1"
    promo button elsewhere on the page still parses. If the withheld list were
    collected from the whole document, that promo would be read as "we read the
    sizes and withheld them all" and the empty-row branch would publish
    instead of alarming — the drift guard silently switched off by a banner.
    """
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = _ALL_BUNDLE.replace(" - Price $", " – Price $").replace(
        "</section>",
        '</section><button aria-label="3-4 feet - Price $99.95 - Buy 1, Get 1">promo</button>',
    )
    withheld = []
    assert scraper._extract_aria_size_offers(html, withheld_bundles=withheld) == []
    assert withheld == [], "a promo outside the size selector leaked in as evidence"

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, f"{BASE}/products/drifted-with-promo.json", status=404)
        rsps.add(responses.GET, f"{BASE}/products/drifted-with-promo", body=html, status=200)
        result = ShopifyScraper("fast-growing-trees", BASE).scrape_product(
            "drifted-with-promo")
    assert result is None, "a promo banner talked the drift guard out of alarming"


def test_a_quantity_button_is_not_a_bundle_offer():
    """A "10-Pack" is filtered as a QUANTITY, upstream of the bundle test, and
    must not license an empty row. That is a different defect (a pack-only
    page still goes silent) and fixing it is not this change."""
    scraper = ShopifyScraper("fast-growing-trees", BASE)
    html = (
        "<h2>Select size</h2>"
        '<button aria-label="10-Pack - Price $199.95">p</button>'
        "</section>"
    )
    withheld = []
    assert scraper._extract_aria_size_offers(html, withheld_bundles=withheld) == []
    assert withheld == []


@responses.activate
def test_all_sold_out_still_wins_over_the_bundle_branch(no_sleep):
    """A page that is both all-bundle and fully sold out is more usefully
    reported as sold out: that is a true fact about the retailer, and it
    clears the cells just the same. The sold-out branch is checked first and
    this change must not have reordered them.

    The stock verdict is read from a REAL JSON parse of the ld+json block, so
    the block here is the well-formed Product shape that branch requires.
    """
    sold_out = _ALL_BUNDLE.replace(
        '<script type="application/ld+json">', '<script type="application/ld+json">'
        '{"@type":"Product","offers":['
    ).replace(
        "</script></body>", "]}</script></body>"
    ).replace("schema.org/InStock", "schema.org/OutOfStock")
    result = _scrape("bloodgood-japanese-maple", sold_out)
    assert result["sizes"] == {}
    assert result["in_stock"] is False, "the sold-out branch no longer runs first"
    assert result["no_sizes_readable"] is True
    assert "all_offers_bundled" not in result


# --- the build half: does the empty row actually clear the cells? -----------

_retailers_by_id = {r["id"]: r for r in load_build_fixture("retailers.json")}
_PLANT = {"id": "bloodgood-japanese-maple", "common_name": "Bloodgood Japanese Maple"}
_FGT = "test-nursery-a"
_OTHER = "test-nursery-b"

# The six cells the site published, priced for two trees.
_STALE_BUNDLE_SIZES = {
    "1-2ft": {"price": 94.95, "was_price": None, "available": True,
              "variant_id": "B1", "raw_size": "1-2 feet"},
    "2-3ft": {"price": 116.95, "was_price": None, "available": True,
              "variant_id": "B2", "raw_size": "2-3 feet"},
}


def _row(retailer_id, sizes, ts, in_stock=True, **extra):
    return {
        "retailer_id": retailer_id,
        "retailer_name": _retailers_by_id[retailer_id]["name"],
        "timestamp": ts,
        "url": f"https://example.com/{retailer_id}/bloodgood",
        "in_stock": in_stock,
        "sizes": sizes,
        **extra,
    }


def _table(entries):
    latest = build.get_latest_prices(entries, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 8, 14)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _PLANT, latest, _retailers_by_id, price_entries=entries,
        )


def _history(with_empty_row):
    """The real shape: a stale bundle-priced row, then either nothing (today's
    behaviour) or the empty row this change writes."""
    entries = [
        _row(_FGT, _STALE_BUNDLE_SIZES, "2026-08-13T23:18:42+00:00"),
        _row(_OTHER, {"1-2ft": {"price": 129.99, "was_price": None,
                                "available": True, "variant_id": "X",
                                "raw_size": "1-2 feet"}},
             "2026-08-14T12:00:00+00:00"),
    ]
    if with_empty_row:
        entries.append(_row(
            _FGT, {}, "2026-08-14T13:00:00+00:00", in_stock=None,
            no_sizes_readable=True, all_offers_bundled=True,
        ))
    return entries


def test_without_the_empty_row_the_stale_bundle_prices_are_still_published():
    """The defect, asserted. If this ever stops failing to clear, the test
    below is measuring nothing."""
    t = _table(_history(with_empty_row=False))
    assert t["prices"][_FGT]["sizes"]["1-2ft"]["price"] == 94.95


def test_the_empty_row_is_what_get_latest_prices_returns():
    """build.py takes the newest row per retailer. That is the whole mechanism
    the stale prices survived on."""
    latest = build.get_latest_prices(_history(with_empty_row=True), _retailers_by_id)
    assert latest[_FGT]["sizes"] == {}
    assert latest[_FGT]["all_offers_bundled"] is True


def test_the_empty_row_clears_every_cell():
    t = _table(_history(with_empty_row=True))
    assert _FGT in t["prices"], "the retailer lost its row entirely"
    assert t["prices"][_FGT]["sizes"] == {}


def test_the_empty_row_withdraws_the_best_price_badge_and_the_savings_claim():
    """Two of bloodgood's six bundle cells carried `best-price`, and the
    headline "save 40%" was computed against a price for two trees."""
    before = _table(_history(with_empty_row=False))
    after = _table(_history(with_empty_row=True))
    assert before["prices"][_FGT]["sizes"]["1-2ft"]["is_best"] is True
    assert after["prices"][_FGT]["sizes"] == {}
    assert before["lowest_price"] == 94.95
    assert after["lowest_price"] == 129.99
    assert before["same_tier_savings"] > 0
    assert after["same_tier_savings"] == 0


def test_the_rendered_page_shows_dashes_not_dollars():
    """The data can be right and the page still wrong."""
    t = _table(_history(with_empty_row=True))
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(build.TEMPLATE_DIR), autoescape=False,
    )
    env.globals["current_year"] = 2026
    env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
    soup = BeautifulSoup(
        env.get_template("product.html").render(
            plant=_PLANT, page_title="t", prices=t["prices"],
            active_size_tiers=t["active_size_tiers"],
            # P8: product.html reads its column labels from here.
            tier_labels=t["tier_labels"],
            mobile_tiers=t["mobile_tiers"], any_in_stock=t["any_in_stock"],
            lowest_price=t["lowest_price"], highest_price=t["highest_price"],
            savings_pct=t["savings_pct"],
            same_tier_savings=t["same_tier_savings"],
            same_tier_info=t["same_tier_info"], best_deal=t["best_deal"],
            runner_up_deals=t["runner_up_deals"],
            has_non_affiliate=t["has_non_affiliate"],
            offer_count=t["offer_count"],
        ),
        "html.parser",
    )
    rows = [
        tr for tr in soup.find_all("tr")
        if tr.select_one("td.retailer-name")
        and _retailers_by_id[_FGT]["name"] in tr.select_one("td.retailer-name").get_text()
    ]
    assert rows, "the retailer lost its row in the rendered page"
    cells = rows[0].select("td.price-cell")
    assert cells, "row rendered without the size columns"
    for cell in cells:
        assert "$" not in cell.get_text(), f"a price survived: {cell.get_text()}"
    assert not rows[0].select(".best-price"), "a best-price badge survived"
    # And no bundle price anywhere else on the page either.
    page = soup.get_text()
    for bundle_price in ("94.95", "116.95"):
        assert bundle_price not in page, f"${bundle_price} still on the page"
