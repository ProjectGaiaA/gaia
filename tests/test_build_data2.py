"""Data logic tests for build.py — price history, heatmap, utilities.

Task 3 of build-pipeline-tests spec. Tests call build.py functions directly
with synthetic data from tests/fixtures/build/.
"""

import json
from unittest.mock import patch

from tests.conftest import BUILD_FIXTURES_DIR, load_build_fixture

import build


# ---------------------------------------------------------------------------
# Helpers: load fixtures once at module level
# ---------------------------------------------------------------------------
_plants = load_build_fixture("plants.json")
_retailers = load_build_fixture("retailers.json")
_retailers_by_id = {r["id"]: r for r in _retailers}

_hydrangea_prices = load_build_fixture("prices/test-hydrangea.jsonl")
_maple_prices = load_build_fixture("prices/test-maple.jsonl")
_apple_prices = load_build_fixture("prices/test-apple.jsonl")
_stale_prices = load_build_fixture("prices/test-stale-plant.jsonl")


# ===================================================================
# get_latest_prices()
# ===================================================================
class TestGetLatestPrices:
    """Picks most recent entry per retailer from price history."""

    def test_picks_latest_per_retailer(self):
        """Hydrangea has 2 entries per retailer (Apr 1 and Apr 3). Should pick Apr 3."""
        latest = build.get_latest_prices(_hydrangea_prices, _retailers_by_id)
        assert "test-nursery-a" in latest
        assert "test-nursery-b" in latest
        assert "2026-04-03" in latest["test-nursery-a"]["timestamp"]
        assert "2026-04-03" in latest["test-nursery-b"]["timestamp"]

    def test_single_entry_per_retailer(self):
        """Maple has 1 entry per retailer. Should return that entry."""
        latest = build.get_latest_prices(_maple_prices, _retailers_by_id)
        assert len(latest) == 2
        assert latest["test-nursery-a"]["sizes"]["3-4ft"]["price"] == 45.99

    def test_empty_input(self):
        """No entries → empty dict."""
        latest = build.get_latest_prices([], _retailers_by_id)
        assert latest == {}

    def test_preserves_all_size_data(self):
        """Latest entry should carry all size tiers from that entry."""
        latest = build.get_latest_prices(_apple_prices, _retailers_by_id)
        a_sizes = latest["test-nursery-a"]["sizes"]
        assert "dwarf-bareroot" in a_sizes
        assert "semi-dwarf-bareroot" in a_sizes


# ===================================================================
# count_consecutive_run_misses()
# ===================================================================
class TestCountConsecutiveRunMisses:
    """Correct miss counts, handles empty input and edge cases."""

    def test_empty_input(self):
        assert build.count_consecutive_run_misses([]) == {}

    def test_no_misses_when_both_present(self):
        """Both retailers present in every run → 0 misses."""
        misses = build.count_consecutive_run_misses(_hydrangea_prices)
        assert misses.get("test-nursery-a", 0) == 0
        assert misses.get("test-nursery-b", 0) == 0

    def test_one_retailer_missing_last_run(self):
        """Build entries where retailer A is absent from the last run."""
        entries = [
            {"retailer_id": "r1", "timestamp": "2026-03-28T10:00:00+00:00",
             "sizes": {"1gal": {"price": 10.0}}},
            {"retailer_id": "r2", "timestamp": "2026-03-28T10:30:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
            # Run 2: only r2
            {"retailer_id": "r2", "timestamp": "2026-03-30T10:00:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
        ]
        misses = build.count_consecutive_run_misses(entries)
        assert misses["r1"] == 1
        assert misses["r2"] == 0

    def test_three_consecutive_misses(self):
        """Retailer absent from 3 consecutive latest runs."""
        entries = [
            {"retailer_id": "r1", "timestamp": "2026-03-25T10:00:00+00:00",
             "sizes": {"1gal": {"price": 10.0}}},
            {"retailer_id": "r2", "timestamp": "2026-03-25T10:30:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
            # Runs 2-4: only r2
            {"retailer_id": "r2", "timestamp": "2026-03-27T10:00:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
            {"retailer_id": "r2", "timestamp": "2026-03-29T10:00:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
            {"retailer_id": "r2", "timestamp": "2026-03-31T10:00:00+00:00",
             "sizes": {"1gal": {"price": 12.0}}},
        ]
        misses = build.count_consecutive_run_misses(entries)
        assert misses["r1"] == 3
        assert misses["r2"] == 0

    def test_invalid_timestamps_skipped(self):
        """Entries with invalid/missing timestamps are silently ignored."""
        entries = [
            {"retailer_id": "r1", "timestamp": "not-a-date", "sizes": {}},
            {"retailer_id": "r2", "timestamp": "", "sizes": {}},
        ]
        misses = build.count_consecutive_run_misses(entries)
        assert misses == {}


# ===================================================================
# build_price_history_json()
# ===================================================================
class TestBuildPriceHistoryJson:
    """Chart.js-compatible price history JSON."""

    def test_returns_valid_json(self):
        result = build.build_price_history_json(_hydrangea_prices)
        assert result is not None
        parsed = json.loads(result)
        assert "dates" in parsed
        assert "retailers" in parsed

    def test_returns_none_for_single_entry(self):
        """<2 entries → None."""
        result = build.build_price_history_json(_stale_prices)
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = build.build_price_history_json([])
        assert result is None

    def test_dates_sorted_ascending(self):
        result = build.build_price_history_json(_hydrangea_prices)
        parsed = json.loads(result)
        dates = parsed["dates"]
        assert dates == sorted(dates)

    def test_filters_inactive_retailers(self):
        """Only active retailers appear when active_retailer_ids is provided."""
        result = build.build_price_history_json(
            _hydrangea_prices,
            active_retailer_ids={"test-nursery-a"},
        )
        parsed = json.loads(result)
        retailer_names = [r["name"] for r in parsed["retailers"]]
        assert len(retailer_names) == 1
        assert "Test Nursery A" in retailer_names

    def test_uses_lowest_price_across_tiers(self):
        """Chart uses lowest price across all size tiers for each date."""
        result = build.build_price_history_json(_hydrangea_prices)
        parsed = json.loads(result)
        # Nursery A: quart=15.99, 1gal=29.99, 3gal=54.99 → lowest is 15.99
        a_data = next(r for r in parsed["retailers"] if r["name"] == "Test Nursery A")
        for price in a_data["prices"]:
            if price is not None:
                assert price == 15.99

    def test_retailer_missing_from_date_gets_none(self):
        """If a retailer has no entry for a date, its price should be None."""
        # Build entries where r1 only has one date, r2 has two
        entries = [
            {"retailer_id": "r1", "retailer_name": "R1",
             "timestamp": "2026-04-01T10:00:00+00:00",
             "sizes": {"1gal": {"price": 20.0}}},
            {"retailer_id": "r2", "retailer_name": "R2",
             "timestamp": "2026-04-01T10:30:00+00:00",
             "sizes": {"1gal": {"price": 25.0}}},
            {"retailer_id": "r2", "retailer_name": "R2",
             "timestamp": "2026-04-03T10:00:00+00:00",
             "sizes": {"1gal": {"price": 26.0}}},
        ]
        parsed = json.loads(build.build_price_history_json(entries))
        r1 = next(r for r in parsed["retailers"] if r["name"] == "R1")
        # R1 has price on 04-01, None on 04-03
        assert r1["prices"][0] == 20.0
        assert r1["prices"][1] is None


# ===================================================================
# parse_month_range()
# ===================================================================
class TestParseMonthRange:
    """Single month, range, year-wrap, empty input."""

    def test_single_month(self):
        assert build.parse_month_range("Sep") == [9]
        assert build.parse_month_range("May") == [5]

    def test_range_same_year(self):
        assert build.parse_month_range("Mar-May") == [3, 4, 5]
        assert build.parse_month_range("Apr-Jun") == [4, 5, 6]

    def test_year_wrap(self):
        """Nov-Jan wraps around year-end: [11, 12, 1]."""
        assert build.parse_month_range("Nov-Jan") == [11, 12, 1]

    def test_year_wrap_oct_feb(self):
        assert build.parse_month_range("Oct-Feb") == [10, 11, 12, 1, 2]

    def test_empty_string(self):
        assert build.parse_month_range("") == []

    def test_none_input(self):
        assert build.parse_month_range(None) == []

    def test_full_month_name(self):
        """First 3 chars are used, so 'September' → 'sep' → 9."""
        assert build.parse_month_range("September") == [9]

    def test_case_insensitive(self):
        assert build.parse_month_range("JAN-MAR") == [1, 2, 3]

    def test_en_dash_separator(self):
        """Supports en-dash (\u2013) as separator."""
        assert build.parse_month_range("May\u2013Jun") == [5, 6]


# ===================================================================
# build_heatmap_data()
# ===================================================================
class TestBuildHeatmapData:
    """Averages monthly index, union planting windows per zone."""

    def _active_plants(self):
        """Return only active plants from fixtures."""
        return [p for p in _plants if p.get("active", True)]

    def test_returns_tuple_of_four(self):
        categories, hm_data, all_zones, month_names = build.build_heatmap_data(
            self._active_plants()
        )
        assert isinstance(categories, list)
        assert isinstance(hm_data, dict)
        assert all_zones == list(range(3, 10))
        assert len(month_names) == 12

    def test_categories_based_on_seasonality_data(self):
        """Only plants with price_seasonality or planting_seasons appear."""
        categories, _, _, _ = build.build_heatmap_data(self._active_plants())
        cat_ids = [c["id"] for c in categories]
        # hydrangeas (hydrangea + stale-plant but stale has no seasonality → only hydrangea contributes)
        # japanese-maples (maple has seasonality)
        # fruit-trees (apple has seasonality)
        assert "hydrangeas" in cat_ids
        assert "japanese-maples" in cat_ids
        assert "fruit-trees" in cat_ids

    def test_monthly_index_averaged_and_clamped(self):
        """Hydrangeas category has 1 plant with seasonality → index equals that plant's."""
        categories, _, _, _ = build.build_heatmap_data(self._active_plants())
        hydrangea_cat = next(c for c in categories if c["id"] == "hydrangeas")
        expected = [3, 3, 4, 5, 4, 3, 2, 1, 1, 2, 3, 3]
        assert hydrangea_cat["monthly_price_index"] == expected
        # All values should be 1-5
        for v in hydrangea_cat["monthly_price_index"]:
            assert 1 <= v <= 5

    def test_planting_windows_union_per_zone(self):
        """Zone 5 planting for hydrangeas: spring May-Jun, fall Sep."""
        categories, _, _, _ = build.build_heatmap_data(self._active_plants())
        hydrangea_cat = next(c for c in categories if c["id"] == "hydrangeas")
        zone5 = hydrangea_cat["planting_by_zone"]["5"]
        # May=idx4, Jun=idx5, Sep=idx8 should be True
        assert zone5[4] is True   # May
        assert zone5[5] is True   # Jun
        assert zone5[8] is True   # Sep
        # Winter months should be False
        assert zone5[0] is False  # Jan
        assert zone5[11] is False  # Dec

    def test_planting_zones_json_is_valid(self):
        categories, _, _, _ = build.build_heatmap_data(self._active_plants())
        for cat in categories:
            parsed = json.loads(cat["planting_zones_json"])
            assert isinstance(parsed, dict)

    def test_best_buy_worst_buy_from_plant(self):
        categories, _, _, _ = build.build_heatmap_data(self._active_plants())
        hydrangea_cat = next(c for c in categories if c["id"] == "hydrangeas")
        assert hydrangea_cat["best_buy"] == "August-September"
        assert hydrangea_cat["worst_buy"] == "April"

    def test_empty_plants_returns_empty(self):
        categories, hm_data, _, _ = build.build_heatmap_data([])
        assert categories == []
        assert hm_data == {}


# ===================================================================
# find_similar_plants()
# ===================================================================
class TestFindSimilarPlants:
    """Same category, excludes self, max n."""

    def test_excludes_self(self):
        hydrangea = next(p for p in _plants if p["id"] == "test-hydrangea")
        similar = build.find_similar_plants(hydrangea, _plants)
        ids = [p["id"] for p in similar]
        assert "test-hydrangea" not in ids

    def test_same_category_only(self):
        hydrangea = next(p for p in _plants if p["id"] == "test-hydrangea")
        similar = build.find_similar_plants(hydrangea, _plants)
        for p in similar:
            assert p["category"] == "hydrangeas"

    def test_hydrangea_finds_stale_and_inactive(self):
        """Both test-stale-plant and test-inactive are in hydrangeas category."""
        hydrangea = next(p for p in _plants if p["id"] == "test-hydrangea")
        similar = build.find_similar_plants(hydrangea, _plants)
        ids = [p["id"] for p in similar]
        assert "test-stale-plant" in ids
        assert "test-inactive" in ids

    def test_max_n_limits_results(self):
        hydrangea = next(p for p in _plants if p["id"] == "test-hydrangea")
        similar = build.find_similar_plants(hydrangea, _plants, n=1)
        assert len(similar) <= 1

    def test_no_similar_when_alone_in_category(self):
        """Apple is the only plant in fruit-trees."""
        apple = next(p for p in _plants if p["id"] == "test-apple")
        similar = build.find_similar_plants(apple, _plants)
        assert similar == []


# ===================================================================
# load_feedback()
# ===================================================================
class TestLoadFeedback:
    """Enriches dates, handles missing fields."""

    def test_loads_from_fixture(self):
        """Load feedback.json from build fixtures directory."""
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            items = build.load_feedback()
        assert len(items) == 1

    def test_enriches_submitted_date(self):
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            items = build.load_feedback()
        item = items[0]
        assert item["submitted_date"] == "March 20, 2026"

    def test_enriches_response_date(self):
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            items = build.load_feedback()
        item = items[0]
        assert item["response_date"] == "March 21, 2026"

    def test_category_label_resolved(self):
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            items = build.load_feedback()
        item = items[0]
        assert item["category_label"] == "Missing Plants"

    def test_status_label_resolved(self):
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            items = build.load_feedback()
        item = items[0]
        assert item["status_label"] == "Planned"

    def test_missing_file_returns_empty(self):
        """Nonexistent feedback.json → empty list."""
        with patch("build.DATA_DIR", "/nonexistent/path"):
            items = build.load_feedback()
        assert items == []

    def test_handles_missing_response(self):
        """Entry without response field → response_date is empty string."""
        with patch("build.DATA_DIR", str(BUILD_FIXTURES_DIR)):
            with patch("build.load_json", return_value=[{
                "id": "fb-no-response",
                "category": "bug",
                "title": "No response",
                "body": "Test",
                "submitted_at": "2026-03-20T14:00:00+00:00",
                "status": "reviewing",
            }]):
                items = build.load_feedback()
        assert items[0]["response"] is None
        assert items[0]["response_date"] == ""
