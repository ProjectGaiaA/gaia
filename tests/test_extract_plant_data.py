"""Tests for scrapers/extract_plant_data.py — botanical data extractor."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses

from tests.conftest import FIXTURES_DIR

EXTRACT_FIXTURES = FIXTURES_DIR / "extract"


def _load(name: str) -> dict:
    """Load an extract fixture by filename."""
    return json.loads((EXTRACT_FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# body_html parsing
# ---------------------------------------------------------------------------

class TestParseBodyHtml:
    """Tests for parse_body_html — extracts botanical fields from HTML."""

    def test_extracts_zones_from_list_format(self):
        """Nature Hills style: <li><strong>Hardiness Zones:</strong> 6-11</li>"""
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("nature-hills-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["zones"] == [6, 7, 8, 9, 10, 11]

    def test_extracts_zones_from_table_format(self):
        """PlantingTree style: <tr><td>Zones</td><td>6, 7, 8, 9, 10, 11</td></tr>"""
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("planting-tree-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["zones"] == [6, 7, 8, 9, 10, 11]

    def test_extracts_zones_from_paragraph_format(self):
        """FGT style: <p><strong>Growing Zones:</strong> 6-11</p>"""
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("fgt-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["zones"] == [6, 7, 8, 9, 10, 11]

    def test_extracts_zones_from_plain_text(self):
        """Inline zones: 'Zones 4-8.' in a paragraph."""
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("minimal-body-product.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["zones"] == [4, 5, 6, 7, 8]

    def test_extracts_zones_from_narrow_range(self):
        """Spring Hill: 'Hardiness Zone: 7-10'"""
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("spring-hill-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["zones"] == [7, 8, 9, 10]

    def test_extracts_sun(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("nature-hills-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["sun"] == "Full Sun"

    def test_extracts_sun_from_table(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("planting-tree-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["sun"] == "Full Sun"

    def test_extracts_sun_with_part_shade(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("spring-hill-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert "part shade" in result["sun"].lower()

    def test_extracts_mature_size(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("nature-hills-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert "3" in result["mature_size"]
        assert "4" in result["mature_size"]
        assert "ft" in result["mature_size"].lower() or "'" in result["mature_size"]

    def test_extracts_bloom_time(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("nature-hills-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["bloom_time"] is not None
        lower = result["bloom_time"].lower()
        assert "summer" in lower or "fall" in lower

    def test_extracts_plant_type(self):
        from scrapers.extract_plant_data import parse_body_html

        fixture = _load("nature-hills-pink-muhly.json")
        result = parse_body_html(fixture["product"]["body_html"])
        assert result["type"] is not None
        assert "grass" in result["type"].lower()

    def test_missing_fields_are_none(self):
        """When body_html has no data for a field, it should be None."""
        from scrapers.extract_plant_data import parse_body_html

        result = parse_body_html("<p>A beautiful plant.</p>")
        assert result["sun"] is None
        assert result["mature_size"] is None
        assert result["bloom_time"] is None
        assert result["type"] is None
        # zones also None when no zone info present
        assert result["zones"] is None


# ---------------------------------------------------------------------------
# Product page fetching
# ---------------------------------------------------------------------------

class TestFetchProductPage:
    """Tests for fetch_product_page — fetches Shopify JSON and parses body_html."""

    @responses.activate
    def test_fetches_and_parses_product(self, no_sleep):
        fixture = _load("nature-hills-pink-muhly.json")
        responses.add(
            responses.GET,
            "https://www.naturehills.com/products/pink-muhly-grass.json",
            json=fixture,
            status=200,
        )

        from scrapers.extract_plant_data import fetch_product_page

        result = fetch_product_page(
            "https://www.naturehills.com", "pink-muhly-grass"
        )

        assert result is not None
        assert result["retailer_url"] == "https://www.naturehills.com"
        assert result["handle"] == "pink-muhly-grass"
        assert result["title"] == "Pink Muhly Grass"
        assert result["parsed"]["zones"] == [6, 7, 8, 9, 10, 11]
        assert result["parsed"]["sun"] == "Full Sun"

    @responses.activate
    def test_returns_none_on_404(self, no_sleep):
        responses.add(
            responses.GET,
            "https://www.naturehills.com/products/nonexistent.json",
            status=404,
        )

        from scrapers.extract_plant_data import fetch_product_page

        result = fetch_product_page(
            "https://www.naturehills.com", "nonexistent"
        )
        assert result is None

    @responses.activate
    def test_returns_none_on_network_error(self, no_sleep):
        responses.add(
            responses.GET,
            "https://www.naturehills.com/products/bad.json",
            body=ConnectionError("Connection refused"),
        )

        from scrapers.extract_plant_data import fetch_product_page

        result = fetch_product_page("https://www.naturehills.com", "bad")
        assert result is None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconciliation:
    """Tests for reconcile_fields — majority rule, tiebreak, fallback."""

    def _mock_llm(self, field, values, plant_name):
        """Deterministic mock LLM that picks the first value."""
        return values[0] if values else f"LLM-generated-{field}"

    def test_majority_rule_three_agree(self):
        """3 retailers agree on zones → majority wins, no LLM needed."""
        from scrapers.extract_plant_data import reconcile_fields

        retailer_data = [
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 ft tall x 3-4 ft wide",
                         "bloom_time": "Late Summer to Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 feet tall x 3-4 feet wide",
                         "bloom_time": "Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 ft. x 3-4 ft.",
                         "bloom_time": "Late Summer - Fall",
                         "type": None}},
        ]

        result = reconcile_fields(
            retailer_data, "Pink Muhly Grass", llm_fn=self._mock_llm
        )
        assert result["zones"]["value"] == [6, 7, 8, 9, 10, 11]
        assert result["zones"]["source"] == "majority"
        assert result["zones"]["flagged"] is False

        assert result["sun"]["value"] == "Full Sun"
        assert result["sun"]["source"] == "majority"

    def test_tiebreak_two_disagree(self):
        """2 retailers disagree on zones → LLM tiebreak."""
        from scrapers.extract_plant_data import reconcile_fields

        retailer_data = [
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 ft tall x 3-4 ft wide",
                         "bloom_time": "Late Summer to Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [7, 8, 9, 10], "sun": "Full sun to part shade",
                         "mature_size": "3 to 4 ft. x 3 to 4 ft.",
                         "bloom_time": "Late Summer, Fall",
                         "type": "Perennial Grass"}},
        ]

        result = reconcile_fields(
            retailer_data, "Pink Muhly Grass", llm_fn=self._mock_llm
        )
        assert result["zones"]["source"] == "llm_tiebreak"
        assert result["zones"]["flagged"] is False
        assert result["sun"]["source"] == "llm_tiebreak"

    def test_fallback_single_source(self):
        """1 retailer only → LLM validates, flagged for review."""
        from scrapers.extract_plant_data import reconcile_fields

        retailer_data = [
            {"parsed": {"zones": [4, 5, 6, 7, 8], "sun": None,
                         "mature_size": None, "bloom_time": None,
                         "type": None}},
        ]

        result = reconcile_fields(
            retailer_data, "Blue Fescue", llm_fn=self._mock_llm
        )
        # zones: 1 source → flagged
        assert result["zones"]["source"] == "llm_fallback"
        assert result["zones"]["flagged"] is True
        # sun: no data → LLM fills, flagged
        assert result["sun"]["source"] == "llm_fallback"
        assert result["sun"]["flagged"] is True

    def test_fallback_no_sources(self):
        """No retailer data at all → LLM fills everything, all flagged."""
        from scrapers.extract_plant_data import reconcile_fields

        retailer_data = [
            {"parsed": {"zones": None, "sun": None,
                         "mature_size": None, "bloom_time": None,
                         "type": None}},
        ]

        result = reconcile_fields(
            retailer_data, "Mystery Plant", llm_fn=self._mock_llm
        )
        for field in ["zones", "sun", "mature_size", "bloom_time", "type"]:
            assert result[field]["flagged"] is True
            assert result[field]["source"] == "llm_fallback"

    def test_majority_with_one_dissenter(self):
        """3 agree, 1 disagrees → majority wins."""
        from scrapers.extract_plant_data import reconcile_fields

        retailer_data = [
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 ft tall x 3-4 ft wide",
                         "bloom_time": "Late Summer to Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 feet tall x 3-4 feet wide",
                         "bloom_time": "Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [6, 7, 8, 9, 10, 11], "sun": "Full Sun",
                         "mature_size": "3-4 ft. x 3-4 ft.",
                         "bloom_time": "Late Summer - Fall",
                         "type": "Ornamental Grass"}},
            {"parsed": {"zones": [7, 8, 9, 10], "sun": "Full sun to part shade",
                         "mature_size": "3 to 4 ft. x 3 to 4 ft.",
                         "bloom_time": "Late Summer, Fall",
                         "type": "Perennial Grass"}},
        ]

        result = reconcile_fields(
            retailer_data, "Pink Muhly Grass", llm_fn=self._mock_llm
        )
        assert result["zones"]["value"] == [6, 7, 8, 9, 10, 11]
        assert result["zones"]["source"] == "majority"
        assert result["sun"]["value"] == "Full Sun"
        assert result["sun"]["source"] == "majority"


# ---------------------------------------------------------------------------
# Draft plant entry generation
# ---------------------------------------------------------------------------

class TestGeneratePlantEntry:
    """Tests for generate_plant_entry — builds a complete plants.json entry."""

    def _mock_llm(self, field, values, plant_name):
        if field == "zones":
            return [6, 7, 8, 9, 10, 11]
        if field == "sun":
            return "Full Sun"
        if field == "mature_size":
            return "3-4 ft tall x 3-4 ft wide"
        if field == "bloom_time":
            return "Late Summer to Fall"
        if field == "type":
            return "Ornamental grass"
        if field == "planting_seasons":
            return {
                "6": {"spring": "Apr-May", "fall": "Sep-Oct"},
                "7": {"spring": "Mar-Apr", "fall": "Oct-Nov"},
                "8": {"spring": "Feb-Apr", "fall": "Oct-Dec"},
                "9": {"spring": "Feb-Mar", "fall": "Nov-Dec"},
                "10": {"spring": "Jan-Mar", "fall": "Nov-Dec"},
                "11": {"spring": "Year-round", "fall": None},
            }
        if field == "price_seasonality":
            return {
                "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
                "best_buy": "September-October",
                "worst_buy": "April-May",
                "note": "Prices peak in spring.",
                "tip": "Buy in fall for best deals.",
            }
        return None

    def test_produces_valid_entry_with_all_fields(self):
        from scrapers.extract_plant_data import generate_plant_entry

        reconciled = {
            "zones": {"value": [6, 7, 8, 9, 10, 11], "source": "majority", "flagged": False},
            "sun": {"value": "Full Sun", "source": "majority", "flagged": False},
            "mature_size": {"value": "3-4 ft tall x 3-4 ft wide", "source": "majority", "flagged": False},
            "bloom_time": {"value": "Late Summer to Fall", "source": "majority", "flagged": False},
            "type": {"value": "Ornamental grass", "source": "majority", "flagged": False},
        }

        entry = generate_plant_entry(
            plant_id="pink-muhly-grass",
            common_name="Pink Muhly Grass",
            botanical_name="Muhlenbergia capillaris",
            category="grasses",
            reconciled=reconciled,
            llm_fn=self._mock_llm,
        )

        # All required fields present
        assert entry["id"] == "pink-muhly-grass"
        assert entry["common_name"] == "Pink Muhly Grass"
        assert entry["botanical_name"] == "Muhlenbergia capillaris"
        assert entry["category"] == "grasses"
        assert entry["zones"] == [6, 7, 8, 9, 10, 11]
        assert entry["sun"] == "Full Sun"
        assert entry["mature_size"] == "3-4 ft tall x 3-4 ft wide"
        assert entry["bloom_time"] == "Late Summer to Fall"
        assert entry["type"] == "Ornamental grass"
        assert "size_tiers" in entry
        assert "quart" in entry["size_tiers"]
        assert entry["price_range"] == ""
        assert entry["image"] == ""
        assert entry["image_credit"] == ""
        assert "planting_seasons" in entry
        assert "price_seasonality" in entry
        assert entry["active"] is False

    def test_entry_has_planting_seasons_from_llm(self):
        from scrapers.extract_plant_data import generate_plant_entry

        reconciled = {
            "zones": {"value": [6, 7, 8, 9, 10, 11], "source": "majority", "flagged": False},
            "sun": {"value": "Full Sun", "source": "majority", "flagged": False},
            "mature_size": {"value": "3-4 ft tall x 3-4 ft wide", "source": "majority", "flagged": False},
            "bloom_time": {"value": "Late Summer to Fall", "source": "majority", "flagged": False},
            "type": {"value": "Ornamental grass", "source": "majority", "flagged": False},
        }

        entry = generate_plant_entry(
            plant_id="pink-muhly-grass",
            common_name="Pink Muhly Grass",
            botanical_name="Muhlenbergia capillaris",
            category="grasses",
            reconciled=reconciled,
            llm_fn=self._mock_llm,
        )

        ps = entry["planting_seasons"]
        assert "6" in ps
        assert "11" in ps
        assert ps["6"]["spring"] == "Apr-May"

    def test_entry_has_price_seasonality_from_llm(self):
        from scrapers.extract_plant_data import generate_plant_entry

        reconciled = {
            "zones": {"value": [6, 7, 8, 9, 10, 11], "source": "majority", "flagged": False},
            "sun": {"value": "Full Sun", "source": "majority", "flagged": False},
            "mature_size": {"value": "3-4 ft tall x 3-4 ft wide", "source": "majority", "flagged": False},
            "bloom_time": {"value": "Late Summer to Fall", "source": "majority", "flagged": False},
            "type": {"value": "Ornamental grass", "source": "majority", "flagged": False},
        }

        entry = generate_plant_entry(
            plant_id="pink-muhly-grass",
            common_name="Pink Muhly Grass",
            botanical_name="Muhlenbergia capillaris",
            category="grasses",
            reconciled=reconciled,
            llm_fn=self._mock_llm,
        )

        ps = entry["price_seasonality"]
        assert len(ps["monthly_index"]) == 12
        assert all(1 <= v <= 5 for v in ps["monthly_index"])
        assert "best_buy" in ps
        assert "worst_buy" in ps
        assert "note" in ps
        assert "tip" in ps

    def test_flagged_fields_appear_in_metadata(self):
        """Fields from LLM fallback should be marked in _review_flags."""
        from scrapers.extract_plant_data import generate_plant_entry

        reconciled = {
            "zones": {"value": [4, 5, 6, 7, 8], "source": "llm_fallback", "flagged": True},
            "sun": {"value": "Full Sun", "source": "llm_fallback", "flagged": True},
            "mature_size": {"value": "8-12 in tall x 12-18 in wide", "source": "llm_fallback", "flagged": True},
            "bloom_time": {"value": "Summer", "source": "llm_fallback", "flagged": True},
            "type": {"value": "Ornamental grass", "source": "llm_fallback", "flagged": True},
        }

        entry = generate_plant_entry(
            plant_id="blue-fescue",
            common_name="Blue Fescue",
            botanical_name="Festuca glauca 'Elijah Blue'",
            category="grasses",
            reconciled=reconciled,
            llm_fn=self._mock_llm,
        )

        assert "_review_flags" in entry
        flags = entry["_review_flags"]
        assert "zones" in flags
        assert "sun" in flags
        assert "mature_size" in flags


# ---------------------------------------------------------------------------
# End-to-end with mocked HTTP + LLM
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Integration test: fetch multiple retailers, reconcile, produce entry."""

    def _mock_llm(self, field, values, plant_name):
        if field == "planting_seasons":
            return {
                "6": {"spring": "Apr-May", "fall": "Sep-Oct"},
                "7": {"spring": "Mar-Apr", "fall": "Oct-Nov"},
                "8": {"spring": "Feb-Apr", "fall": "Oct-Dec"},
                "9": {"spring": "Feb-Mar", "fall": "Nov-Dec"},
                "10": {"spring": "Jan-Mar", "fall": "Nov-Dec"},
                "11": {"spring": "Year-round", "fall": None},
            }
        if field == "price_seasonality":
            return {
                "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
                "best_buy": "September-October",
                "worst_buy": "April-May",
                "note": "Prices peak in spring.",
                "tip": "Buy in fall.",
            }
        if values:
            return values[0]
        return f"LLM-{field}"

    @responses.activate
    def test_full_pipeline_produces_valid_entry(self, no_sleep):
        """Fetch 3 retailers, reconcile, generate draft entry."""
        from scrapers.extract_plant_data import (
            fetch_product_page, reconcile_fields, generate_plant_entry,
        )

        # Register mock responses
        for url, fixture_name in [
            ("https://www.naturehills.com/products/pink-muhly-grass.json",
             "nature-hills-pink-muhly.json"),
            ("https://www.plantingtree.com/products/pink-muhly-grass-muhlenbergia.json",
             "planting-tree-pink-muhly.json"),
            ("https://www.fast-growing-trees.com/products/pink-muhly-grass-tree.json",
             "fgt-pink-muhly.json"),
        ]:
            responses.add(
                responses.GET, url,
                json=_load(fixture_name), status=200,
            )

        # Fetch from each retailer
        pages = []
        for base_url, handle in [
            ("https://www.naturehills.com", "pink-muhly-grass"),
            ("https://www.plantingtree.com", "pink-muhly-grass-muhlenbergia"),
            ("https://www.fast-growing-trees.com", "pink-muhly-grass-tree"),
        ]:
            page = fetch_product_page(base_url, handle)
            assert page is not None
            pages.append(page)

        # Reconcile
        reconciled = reconcile_fields(pages, "Pink Muhly Grass", llm_fn=self._mock_llm)

        # All 3 agree on zones 6-11 → majority
        assert reconciled["zones"]["value"] == [6, 7, 8, 9, 10, 11]
        assert reconciled["zones"]["source"] == "majority"

        # Generate entry
        entry = generate_plant_entry(
            plant_id="pink-muhly-grass",
            common_name="Pink Muhly Grass",
            botanical_name="Muhlenbergia capillaris",
            category="grasses",
            reconciled=reconciled,
            llm_fn=self._mock_llm,
        )

        assert entry["id"] == "pink-muhly-grass"
        assert entry["active"] is False
        assert entry["zones"] == [6, 7, 8, 9, 10, 11]
        assert "planting_seasons" in entry
        assert "price_seasonality" in entry
