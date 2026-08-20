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

import itertools
import json
from datetime import date
from unittest.mock import patch

import jinja2
import pytest
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


class TestShippingSeasonBadge:
    """The badge sits on the ROW but the fact is per-VARIANT.

    Regression cover: when raw_size first started reaching the detector it
    took the first match and stopped, so Emerald Green Arborvitae's row
    claimed "Ships Spring" on the strength of one $90.99 bare root while the
    $19.99 size shipped year-round and five others shipped in Fall.
    """

    def _season(self, raws):
        entries = [_entry(_A, {
            f"tier{i}": _size(10.0 + i, True, variant_id=str(i), raw_size=r)
            for i, r in enumerate(raws)
        })]
        return _table(entries)["prices"][_A]["ships_season"]

    def test_unanimous_season_is_claimed(self):
        assert self._season([
            "1 Gal / 1 Plant(s) | Ships in Spring",
            "3 Gal / 1 Plant(s) | Ships in Spring",
        ]) == "Spring"

    def test_disagreeing_sizes_claim_nothing(self):
        assert self._season([
            "DORMANT / 1 Plant(s) | Ships in Spring",
            "FIELD 12-18\" / 1 Plant(s) | Ships in Fall",
        ]) is None

    def test_one_seasonal_size_among_year_round_ones_claims_nothing(self):
        """The exact Emerald Green Arborvitae shape."""
        assert self._season([
            "1-2' / 1 Plant(s) | Ships Year-Round",
            "DORMANT 48-54\" / 1 Plant(s) | Ships in Spring",
            "FIELD 12-18\" / 1 Plant(s) | Ships in Fall",
        ]) is None

    def test_no_season_anywhere_claims_nothing(self):
        assert self._season(["1 Gallon", "3 Gallon"]) is None

    def test_badge_does_not_depend_on_variant_order(self):
        """Two scrape runs with identical data in a different order must not
        publish contradictory shipping claims."""
        raws = [
            "DORMANT / 1 Plant(s) | Ships in Spring",
            "FIELD 12-18\" / 1 Plant(s) | Ships in Fall",
            "1-2' / 1 Plant(s) | Ships Year-Round",
        ]
        results = {self._season(list(p)) for p in itertools.permutations(raws)}
        assert results == {None}, f"badge varies with input order: {results}"

    def test_unanimous_badge_also_order_independent(self):
        raws = ["A | Ships in Fall", "B | Ships in Fall", "C | Ships in Fall"]
        results = {self._season(list(p)) for p in itertools.permutations(raws)}
        assert results == {"Fall"}


class TestOneRuleForBuyability:
    """build.py and the template must not each decide this separately."""

    def test_non_bool_available_does_not_split_desktop_from_mobile(self):
        """Jinja's `==` treats 0 as False; `is False` does not. When the two
        copies of the rule disagreed, the desktop table said "Sold out" while
        mobile still offered the same variant as the best price."""
        entries = [_entry(_A, {"1gal": _size(19.99, 0, variant_id="Z")})]
        t = _table(entries)
        buyable = t["prices"][_A]["sizes"]["1gal"]["is_buyable"]
        on_mobile = any(m["tier"] == "1gal" for m in t["mobile_tiers"])
        assert buyable == on_mobile, "table and mobile disagree about the same size"

    def test_row_sold_out_makes_every_size_unbuyable(self):
        entries = [_entry(_A, {"1gal": _size(19.99, True)}, in_stock=False)]
        t = _table(entries)
        assert t["prices"][_A]["sizes"]["1gal"]["is_buyable"] is False

    def test_row_sold_out_prices_are_not_links(self):
        entries = [_entry(_A, {"1gal": _size(19.99, True, variant_id="ROWDEAD")})]
        entries[0]["in_stock"] = False
        soup = TestRenderedHtml()._render(entries)
        for a in soup.find_all("a", href=True):
            assert "ROWDEAD" not in a["href"], "sold-out row still links its prices"

    def test_buyable_size_on_a_live_row_is_still_buyable(self):
        entries = [_entry(_A, {"1gal": _size(19.99, True)})]
        assert _table(entries)["prices"][_A]["sizes"]["1gal"]["is_buyable"] is True


class TestCollisionLoserDoesNotSetHeadline:
    """A price that appears nowhere on the page must not set schema highPrice."""

    def test_overwritten_variant_is_excluded_from_the_range(self):
        entries = [_entry(_A, {
            "1-gallon": _size(9.0, None, variant_id="LOSER"),
            "#1-container": _size(4.0, True, variant_id="WINNER"),
        })]
        t = _table(entries)
        assert t["prices"][_A]["sizes"]["1gal"]["variant_id"] == "WINNER"
        assert t["highest_price"] == 4.0

    def test_range_is_the_same_whichever_order_they_arrive_in(self):
        a = {"1-gallon": _size(9.0, None, variant_id="L"),
             "#1-container": _size(4.0, True, variant_id="W")}
        b = {"#1-container": _size(4.0, True, variant_id="W"),
             "1-gallon": _size(9.0, None, variant_id="L")}
        ta, tb = _table([_entry(_A, a)]), _table([_entry(_A, b)])
        assert (ta["lowest_price"], ta["highest_price"]) == \
               (tb["lowest_price"], tb["highest_price"])


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
                # P8: product.html reads its column labels from here.
                tier_labels=table["tier_labels"],
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

    def test_stale_retailer_is_not_called_sold_out(self):
        """A retailer we have failed to reach for 3+ runs is UNCONFIRMED.
        Claiming "Sold out" there asserts a stock fact we never checked."""
        # 4 runs where nursery A is present and B is missing => B has 3+ misses
        entries = []
        for i, day in enumerate(("02", "03", "04", "05")):
            entries.append({
                "retailer_id": _A,
                "retailer_name": _retailers_by_id[_A]["name"],
                "timestamp": f"2026-04-{day}T12:00:00Z",
                "url": "https://example.com/a/product",
                "in_stock": True,
                "sizes": {"1gal": _size(19.99 + i, True)},
            })
        entries.insert(0, _entry(_B, {"1gal": _size(29.99, True)}))
        entries[0]["timestamp"] = "2026-04-01T12:00:00Z"
        t = _table(entries)
        if not t["prices"].get(_B, {}).get("unavailable"):
            pytest.skip("fixture did not produce a stale row")
        soup = self._render(entries)
        tag = soup.select_one("span.price-soldout .soldout-tag")
        assert tag is not None and "sold out" not in tag.get_text().lower()

    def test_buyable_price_at_the_same_size_is_still_a_link(self):
        """Guard against over-correcting into blanking the column."""
        soup = self._render(_cheaper_but_sold_out())
        hrefs = [a["href"] for a in soup.find_all("a", href=True)]
        assert any("BBB" in h for h in hrefs), "buyable variant lost its link"


class TestIndexingSurvivesASellOut:
    """De-index a page when we know NOTHING about the plant, not when it
    happens to be sold out everywhere this week.

    offer_count answers "how many nurseries can you order from" and is a
    claim, so it counts only buyable offers. Reusing it for the noindex rule
    made a page drop out of the sitemap whenever stock lapsed and reappear
    when it returned — index flapping on a routine seasonal state.
    """

    def test_sold_out_everywhere_still_has_priced_offers(self):
        entries = [
            _entry(_A, {"1gal": _size(19.99, False)}),
            _entry(_B, {"1gal": _size(29.99, False)}),
        ]
        t = _table(entries)
        assert t["offer_count"] == 0, "nothing is orderable, so nothing is an offer"
        assert t["priced_offer_count"] == 2, "but we still know both prices"

    def test_a_plant_with_no_prices_at_all_has_neither(self):
        t = _table([_entry(_A, {})])
        assert t["offer_count"] == 0
        assert t["priced_offer_count"] == 0

    def test_buyable_plant_counts_under_both(self):
        t = _table([_entry(_A, {"1gal": _size(19.99, True)})])
        assert t["offer_count"] == 1
        assert t["priced_offer_count"] == 1


class TestRowClassIsNotRederivedInTheTemplate:
    def test_row_sold_out_flag_is_exposed(self):
        t = _table([_entry(_A, {"1gal": _size(19.99, True)}, in_stock=False)])
        assert t["prices"][_A]["row_sold_out"] is True

    def test_non_bool_in_stock_does_not_count_as_sold_out(self):
        """Jinja's `==` made 0 and "" match False. `is False` does not, and the
        template now reads the precomputed flag rather than asking itself."""
        for weird in (0, 0.0, "", "false"):
            t = _table([_entry(_A, {"1gal": _size(19.99, True)}, in_stock=weird)])
            assert t["prices"][_A]["row_sold_out"] is False, f"in_stock={weird!r}"


class TestRowWithNoAttributablePrices:
    """`sizes: {}` — the shape a fully sold-out FGT page produces (f5b8d89e)
    and the shape left behind when strip_unresolved_variants.py removes a
    row's only tier. The row is kept, not deleted, so the page must render
    it as a retailer we checked and could not price — never invent one.
    """

    def test_row_survives_with_no_sizes(self):
        t = _table([
            _entry(_A, {}, in_stock=False),
            _entry(_B, {"1gal": _size(29.99, True)}),
        ])
        assert _A in t["prices"], "priceless row was dropped from the table"
        assert t["prices"][_A]["sizes"] == {}

    def test_empty_row_contributes_no_price_anywhere(self):
        t = _table([
            _entry(_A, {}, in_stock=False),
            _entry(_B, {"1gal": _size(29.99, True)}),
        ])
        assert t["lowest_price"] == 29.99 and t["highest_price"] == 29.99
        assert t["same_tier_savings"] == 0
        assert all(m["retailer_name"] != _retailers_by_id[_A]["name"]
                   for m in t["mobile_tiers"])
        assert t["prices"][_A]["default_variant_id"] is None

    def test_empty_row_does_not_claim_stock_it_cannot_show(self):
        """in_stock=True with nothing orderable inside must not set the
        page-level availability — that is the one row shape the strip
        leaves behind on a live product (endless-summer-hydrangea)."""
        t = _table([_entry(_A, {}, in_stock=True)])
        assert t["any_in_stock"] is False
        assert t["offer_count"] == 0 and t["priced_offer_count"] == 0

    def test_rendered_row_shows_no_price(self):
        soup = TestRenderedHtml()._render([
            _entry(_A, {}, in_stock=False),
            _entry(_B, {"1gal": _size(29.99, True)}),
        ])
        rows = [tr for tr in soup.find_all("tr")
                if tr.select_one("td.retailer-name")
                and _retailers_by_id[_A]["name"] in
                tr.select_one("td.retailer-name").get_text()]
        assert rows, "the priceless retailer lost its row in the rendered page"
        cells = rows[0].select("td.price-cell")
        assert cells, "row rendered without the size columns"
        for cell in cells:
            text = cell.get_text()
            assert "$" not in text, f"a price was fabricated for a priceless row: {text}"
        # ...and nothing in the row links a variant we cannot price.
        for a in rows[0].find_all("a", href=True):
            assert "?variant=" not in a["href"]
