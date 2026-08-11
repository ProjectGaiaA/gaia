"""A size that is sold out must never be presented as one you can buy.

The scraper learned to read real per-variant stock (see test_shopify.py).
This module covers the other half: what the SITE does with that fact.

Before these tests, build_price_table() dropped the `available` flag on the
floor while copying scraped variants into the template's size dicts. Every
downstream consumer was therefore blind to it — the size column linked
sold-out variants, the green best-price highlight could land on one, the
mobile view could show one as the single price for its size, and the
homepage "save N%" hero could be computed from a price nobody can pay.

The bug that started this: a visitor clicked a listed size, landed on the
retailer, and found only "Notify me when available".
"""

import json
from datetime import date
from unittest.mock import patch

import jinja2
from bs4 import BeautifulSoup

from tests.conftest import load_build_fixture

import build

_retailers_by_id = {r["id"]: r for r in load_build_fixture("retailers.json")}
_PLANT = {"id": "test-hydrangea", "common_name": "Test Hydrangea"}

# Both fixture retailers carry an affiliate block, so rows render identically
# apart from the stock facts under test.
_A = "test-nursery-a"
_B = "test-nursery-b"


def _entry(retailer_id, sizes, in_stock=True):
    return {
        "retailer_id": retailer_id,
        "retailer_name": _retailers_by_id[retailer_id]["name"],
        "timestamp": "2026-04-05T12:00:00Z",
        "url": f"https://example.com/{retailer_id}/product",
        "in_stock": in_stock,
        "sizes": sizes,
    }


def _size(price, available, variant_id="111", raw_size="1 Gallon"):
    return {
        "price": price,
        "was_price": None,
        "available": available,
        "variant_id": variant_id,
        "raw_size": raw_size,
    }


def _table(entries):
    latest = build.get_latest_prices(entries, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 6)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _PLANT, latest, _retailers_by_id, price_entries=entries,
        )


# The scenario every assertion below shares: nursery A has the CHEAPER
# 1-gallon but it is sold out; nursery B's is dearer and in stock. Anything
# that picks "the price to show" must pick B's.
def _cheaper_but_sold_out():
    return [
        _entry(_A, {"1gal": _size(19.99, False, variant_id="AAA")}),
        _entry(_B, {"1gal": _size(29.99, True, variant_id="BBB")}),
    ]


class TestSoldOutSizeIsNotAnOffer:
    def test_sold_out_size_does_not_win_best_price(self):
        t = _table(_cheaper_but_sold_out())
        assert t["prices"][_A]["sizes"]["1gal"]["is_best"] is False
        assert t["prices"][_B]["sizes"]["1gal"]["is_best"] is True

    def test_mobile_shows_the_buyable_price_not_the_cheaper_dead_one(self):
        """Mobile renders ONE row per size. A wrong pick here is the whole page."""
        mt = {m["tier"]: m for m in _table(_cheaper_but_sold_out())["mobile_tiers"]}
        assert mt["1gal"]["price"] == 29.99
        assert mt["1gal"]["retailer_name"] == _retailers_by_id[_B]["name"]

    def test_savings_claim_is_not_built_on_a_sold_out_price(self):
        """One buyable price left in the tier means there is no spread to claim."""
        t = _table(_cheaper_but_sold_out())
        assert t["same_tier_savings"] == 0

    def test_headline_range_excludes_the_sold_out_price(self):
        t = _table(_cheaper_but_sold_out())
        assert t["lowest_price"] == 29.99

    def test_buy_button_does_not_deep_link_a_sold_out_variant(self):
        t = _table(_cheaper_but_sold_out())
        assert t["prices"][_A]["default_variant_id"] != "AAA"

    def test_buy_button_picks_the_cheapest_variant_that_is_actually_buyable(self):
        entries = [
            _entry(_A, {
                "1gal": _size(19.99, False, variant_id="DEAD"),
                "3gal": _size(24.99, True, variant_id="LIVE", raw_size="3 Gallon"),
            }),
        ]
        assert _table(entries)["prices"][_A]["default_variant_id"] == "LIVE"

    def test_offer_count_does_not_count_a_sold_out_only_retailer(self):
        entries = [
            _entry(_A, {"1gal": _size(19.99, False)}),
            _entry(_B, {"1gal": _size(29.99, True)}),
        ]
        assert _table(entries)["offer_count"] == 1

    def test_retailer_with_nothing_buyable_does_not_sort_above_one_with_stock(self):
        t = _table(_cheaper_but_sold_out())
        assert list(t["prices"].keys())[0] == _B

    def test_schema_availability_is_false_when_every_variant_is_gone(self):
        entries = [_entry(_A, {"1gal": _size(19.99, False)})]
        assert _table(entries)["any_in_stock"] is False

    def test_schema_availability_survives_one_live_variant(self):
        assert _table(_cheaper_but_sold_out())["any_in_stock"] is True


class TestUnknownStockIsNotTreatedAsSoldOut:
    """Most retailers never report per-variant stock. Unknown must keep
    behaving as it always has, or the majority of the catalogue goes dark."""

    def test_unknown_still_wins_best_price(self):
        entries = [
            _entry(_A, {"1gal": _size(19.99, None)}),
            _entry(_B, {"1gal": _size(29.99, None)}),
        ]
        t = _table(entries)
        assert t["prices"][_A]["sizes"]["1gal"]["is_best"] is True

    def test_unknown_still_produces_a_savings_claim(self):
        entries = [
            _entry(_A, {"1gal": _size(19.99, None)}),
            _entry(_B, {"1gal": _size(29.99, None)}),
        ]
        assert _table(entries)["same_tier_savings"] == 33

    def test_unknown_still_appears_on_mobile(self):
        entries = [_entry(_A, {"1gal": _size(19.99, None)})]
        assert len(_table(entries)["mobile_tiers"]) == 1


class TestCollidingTiersPreferTheBuyableOne:
    """Two raw variants can normalize to one canonical tier. The old rule
    kept whichever was cheaper, even when that one was sold out."""

    def test_in_stock_beats_cheaper_sold_out(self):
        entries = [_entry(_A, {
            "1-gallon": _size(19.99, False, variant_id="DEAD"),
            "#1-container": _size(24.99, True, variant_id="LIVE"),
        })]
        s = _table(entries)["prices"][_A]["sizes"]["1gal"]
        assert s["price"] == 24.99
        assert s["variant_id"] == "LIVE"

    def test_cheaper_still_wins_when_both_are_buyable(self):
        entries = [_entry(_A, {
            "1-gallon": _size(19.99, True, variant_id="CHEAP"),
            "#1-container": _size(24.99, True, variant_id="DEAR"),
        })]
        assert _table(entries)["prices"][_A]["sizes"]["1gal"]["variant_id"] == "CHEAP"


class TestRenderedHtml:
    """The data can be right and the page still wrong. These assert on the
    HTML a visitor actually receives."""

    def _render(self, entries):
        table = _table(entries)
        # Same env build_site() constructs, against the real templates.
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(build.TEMPLATE_DIR),
            autoescape=False,
        )
        env.globals["current_year"] = 2026
        env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
        return BeautifulSoup(
            env.get_template("product.html").render(
                plant=_PLANT,
                page_title="t",
                prices=table["prices"],
                active_size_tiers=table["active_size_tiers"],
                mobile_tiers=table["mobile_tiers"],
                any_in_stock=table["any_in_stock"],
                lowest_price=table["lowest_price"],
                highest_price=table["highest_price"],
                savings_pct=table["savings_pct"],
                same_tier_savings=table["same_tier_savings"],
                same_tier_info=table["same_tier_info"],
                best_deal=table["best_deal"],
                runner_up_deals=table["runner_up_deals"],
                has_non_affiliate=table["has_non_affiliate"],
                offer_count=table["offer_count"],
            ),
            "html.parser",
        )

    def test_sold_out_price_is_rendered_but_not_as_a_link(self):
        soup = self._render(_cheaper_but_sold_out())
        cell = soup.select_one("span.price-soldout")
        assert cell is not None, "sold-out size did not render at all"
        assert "19.99" in cell.get_text()
        assert cell.find("a") is None, "sold-out price is still clickable"

    def test_sold_out_price_is_labelled_so_it_reads_as_unbuyable(self):
        soup = self._render(_cheaper_but_sold_out())
        assert "sold out" in soup.select_one("span.price-soldout").get_text().lower()

    def test_no_anchor_anywhere_on_the_page_targets_the_dead_variant(self):
        """The strongest form: whatever route the template takes, the
        sold-out variant id must not appear in any href."""
        soup = self._render(_cheaper_but_sold_out())
        for a in soup.find_all("a", href=True):
            assert "AAA" not in a["href"], f"dead variant reachable via {a['href']}"

    def test_buyable_price_at_the_same_size_is_still_a_link(self):
        """Guard against over-correcting into blanking the column."""
        soup = self._render(_cheaper_but_sold_out())
        hrefs = [a["href"] for a in soup.find_all("a", href=True)]
        assert any("BBB" in h for h in hrefs), "buyable variant lost its link"
