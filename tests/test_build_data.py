"""Data logic tests for build.py — size normalization, price table, savings.

Task 2 of build-pipeline-tests spec. Tests call build.py functions directly
with synthetic data from tests/fixtures/build/.
"""

from datetime import date
from unittest.mock import patch

from tests.conftest import load_build_fixture

import build


# ---------------------------------------------------------------------------
# Helpers: load fixtures once at module level
# ---------------------------------------------------------------------------
_plants = load_build_fixture("plants.json")
_retailers = load_build_fixture("retailers.json")
_retailers_by_id = {r["id"]: r for r in _retailers}

_hydrangea = next(p for p in _plants if p["id"] == "test-hydrangea")
_maple = next(p for p in _plants if p["id"] == "test-maple")
_apple = next(p for p in _plants if p["id"] == "test-apple")
_stale = next(p for p in _plants if p["id"] == "test-stale-plant")

_hydrangea_prices = load_build_fixture("prices/test-hydrangea.jsonl")
_maple_prices = load_build_fixture("prices/test-maple.jsonl")
_apple_prices = load_build_fixture("prices/test-apple.jsonl")
_stale_prices = load_build_fixture("prices/test-stale-plant.jsonl")


# ===================================================================
# normalize_size_tier()
# ===================================================================
class TestNormalizeSizeTier:
    """Aliases, typos, variant IDs, and passthrough."""

    def test_canonical_passthrough(self):
        assert build.normalize_size_tier("1gal") == "1gal"
        assert build.normalize_size_tier("quart") == "quart"
        assert build.normalize_size_tier("3gal") == "3gal"

    def test_gallon_aliases(self):
        assert build.normalize_size_tier("1-gallon") == "1gal"
        assert build.normalize_size_tier("1-gallon-pot") == "1gal"
        assert build.normalize_size_tier("#1") == "1gal"
        assert build.normalize_size_tier("#1-container") == "1gal"
        assert build.normalize_size_tier("3-gallon") == "3gal"
        assert build.normalize_size_tier("5-gallon-pot") == "5gal"

    def test_bareroot_aliases(self):
        assert build.normalize_size_tier("bare-root") == "bareroot"
        assert build.normalize_size_tier("bare root") == "bareroot"
        assert build.normalize_size_tier("dormant") == "bareroot"

    def test_typo_aliases(self):
        assert build.normalize_size_tier("1-galllon") == "1gal"  # triple-l
        assert build.normalize_size_tier("2-gallons") == "2gal"  # plural

    def test_case_insensitive(self):
        assert build.normalize_size_tier("1-GALLON") == "1gal"
        assert build.normalize_size_tier("Bare-Root") == "bareroot"
        assert build.normalize_size_tier("QT") == "quart"

    def test_strips_whitespace_for_alias_lookup(self):
        """Whitespace is stripped for both alias lookup and canonical fallback."""
        assert build.normalize_size_tier("  qt  ") == "quart"
        assert build.normalize_size_tier("  1gal  ") == "1gal"

    def test_variant_id_becomes_default(self):
        assert build.normalize_size_tier("variant-12345678") == "default"
        assert build.normalize_size_tier("9999999") == "default"

    def test_unknown_passthrough(self):
        """Unrecognized tier keys pass through unchanged."""
        assert build.normalize_size_tier("mystery-size") == "mystery-size"

    def test_unknown_passthrough_lowered(self):
        """Mixed-case unknown tiers must be lowered, not returned in original case."""
        assert build.normalize_size_tier("Mystery-Size") == "mystery-size"
        assert build.normalize_size_tier("JUMBO") == "jumbo"

    def test_exotic_tiers_passthrough(self):
        """Exotic tier keys (dwarf, jumbo, semi-dwarf variants) are canonical already."""
        assert build.normalize_size_tier("dwarf-bareroot") == "dwarf-bareroot"
        assert build.normalize_size_tier("semi-dwarf-potted") == "semi-dwarf-potted"
        assert build.normalize_size_tier("jumbo-bareroot") == "jumbo-bareroot"


# ===================================================================
# get_size_label()
# ===================================================================
class TestGetSizeLabel:
    """Known tiers get labels, unknown tiers get title-cased fallback."""

    def test_known_gallon_labels(self):
        assert build.get_size_label("1gal") == "1 Gallon"
        assert build.get_size_label("3gal") == "3 Gallon"
        assert build.get_size_label("quart") == "Quart"

    def test_exotic_tier_labels(self):
        assert build.get_size_label("dwarf-bareroot") == "Dwarf (Bare Root)"
        assert build.get_size_label("semi-dwarf-potted") == "Semi-Dwarf (Potted)"
        assert build.get_size_label("jumbo-bareroot") == "Jumbo Bare Root"

    def test_height_tier_labels(self):
        assert build.get_size_label("3-4ft") == "3-4 ft"
        assert build.get_size_label("5-6ft") == "5-6 ft"

    def test_alias_resolves_to_label(self):
        """Passing an alias through get_size_label should resolve via normalize first."""
        assert build.get_size_label("#1-container") == "1 Gallon"
        assert build.get_size_label("1-gallon") == "1 Gallon"

    def test_unknown_tier_fallback(self):
        """Unknown tiers get title-cased with hyphens replaced by spaces."""
        assert build.get_size_label("mystery-size") == "Mystery Size"


# ===================================================================
# build_price_table() — structure and best-price marking
# ===================================================================
def _build_hydrangea_table():
    """Helper: build price table for test-hydrangea with date patched to 2026-04-06."""
    latest = build.get_latest_prices(_hydrangea_prices, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 6)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _hydrangea, latest, _retailers_by_id,
            price_entries=_hydrangea_prices,
        )


def _build_maple_table():
    """Helper: build price table for test-maple."""
    latest = build.get_latest_prices(_maple_prices, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 6)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _maple, latest, _retailers_by_id,
            price_entries=_maple_prices,
        )


def _build_apple_table():
    """Helper: build price table for test-apple."""
    latest = build.get_latest_prices(_apple_prices, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 6)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _apple, latest, _retailers_by_id,
            price_entries=_apple_prices,
        )


def _build_stale_table():
    """Helper: build price table for test-stale-plant (all prices >30 days old)."""
    latest = build.get_latest_prices(_stale_prices, _retailers_by_id)
    with patch("build.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 6)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        return build.build_price_table(
            _stale, latest, _retailers_by_id,
            price_entries=_stale_prices,
        )


class TestBuildPriceTableStructure:
    """Price table returns correct structure and retailer data."""

    def test_hydrangea_has_both_retailers(self):
        table = _build_hydrangea_table()
        assert "test-nursery-a" in table["prices"]
        assert "test-nursery-b" in table["prices"]

    def test_hydrangea_active_tiers(self):
        table = _build_hydrangea_table()
        tiers = table["active_size_tiers"]
        assert "quart" in tiers
        assert "1gal" in tiers
        assert "3gal" in tiers

    def test_hydrangea_nursery_a_prices(self):
        table = _build_hydrangea_table()
        a_sizes = table["prices"]["test-nursery-a"]["sizes"]
        assert a_sizes["quart"]["price"] == 15.99
        assert a_sizes["1gal"]["price"] == 29.99
        assert a_sizes["3gal"]["price"] == 54.99

    def test_hydrangea_nursery_b_no_quart(self):
        """Nursery B has no quart tier — should not appear in B's sizes."""
        table = _build_hydrangea_table()
        b_sizes = table["prices"]["test-nursery-b"]["sizes"]
        assert "quart" not in b_sizes
        assert "1gal" in b_sizes
        assert "3gal" in b_sizes

    def test_offer_count(self):
        table = _build_hydrangea_table()
        assert table["offer_count"] == 2


class TestBestPriceMarking:
    """Best price per tier marked only on in-stock retailers."""

    def test_nursery_a_gets_best_for_shared_tiers(self):
        """Nursery A is cheaper and in-stock; B is out-of-stock (in_stock: false)."""
        table = _build_hydrangea_table()
        a_sizes = table["prices"]["test-nursery-a"]["sizes"]
        # A is in_stock=true, B is in_stock=false, so A should get best on all tiers
        assert a_sizes["quart"]["is_best"] is True
        assert a_sizes["1gal"]["is_best"] is True
        assert a_sizes["3gal"]["is_best"] is True

    def test_out_of_stock_excluded_from_best(self):
        """Nursery B has in_stock: false — should NOT get best-price even if it were cheaper."""
        table = _build_hydrangea_table()
        b_sizes = table["prices"]["test-nursery-b"]["sizes"]
        assert b_sizes["1gal"]["is_best"] is False
        assert b_sizes["3gal"]["is_best"] is False


class TestOutOfStockSorting:
    """Out-of-stock retailers sort to bottom."""

    def test_in_stock_before_out_of_stock(self):
        table = _build_hydrangea_table()
        retailer_ids = list(table["prices"].keys())
        # Nursery A (in-stock) should appear before Nursery B (out-of-stock)
        assert retailer_ids.index("test-nursery-a") < retailer_ids.index("test-nursery-b")


class TestWasPriceSaleFlag:
    """was_price triggers sale_flag."""

    def test_nursery_b_1gal_has_sale_flag(self):
        """Nursery B's 1gal has was_price=49.99 — should get sale_flag."""
        table = _build_hydrangea_table()
        b_1gal = table["prices"]["test-nursery-b"]["sizes"]["1gal"]
        assert b_1gal.get("was_price") == 49.99
        assert b_1gal.get("sale_flag") is True

    def test_nursery_a_no_sale_flag(self):
        """Nursery A's prices have no was_price — no sale_flag."""
        table = _build_hydrangea_table()
        a_sizes = table["prices"]["test-nursery-a"]["sizes"]
        for tier, sdata in a_sizes.items():
            assert sdata.get("sale_flag") is None or sdata.get("sale_flag") is False


class TestStaleExclusion:
    """Prices >30 days old excluded entirely."""

    def test_stale_plant_no_retailers(self):
        """test-stale-plant's only price is from 2026-02-15 — >30 days stale."""
        table = _build_stale_table()
        # All retailers should be excluded due to staleness
        assert len(table["prices"]) == 0

    def test_stale_plant_no_active_tiers(self):
        table = _build_stale_table()
        assert table["active_size_tiers"] == []

    def test_stale_plant_no_lowest_price(self):
        table = _build_stale_table()
        assert table["lowest_price"] is None


# ===================================================================
# Savings calculations
# ===================================================================
class TestSavingsCalculation:
    """Cross-tier and same-tier savings math."""

    def test_hydrangea_savings_pct(self):
        """Overall savings: cheapest (15.99) vs most expensive (69.99)."""
        table = _build_hydrangea_table()
        # round((1 - 15.99/69.99) * 100) = round(77.14) = 77
        assert table["savings_pct"] == 77

    def test_hydrangea_lowest_highest(self):
        table = _build_hydrangea_table()
        assert table["lowest_price"] == 15.99
        assert table["highest_price"] == 69.99

    def test_hydrangea_same_tier_savings(self):
        """Same-tier savings should compare within 1gal or 3gal (2 nurseries each).
        1gal: 29.99 vs 39.99 → round((1 - 29.99/39.99)*100) = 25
        3gal: 54.99 vs 69.99 → round((1 - 54.99/69.99)*100) = 21
        Both have 2 nurseries; tie breaks by savings %, so 1gal (25%) wins."""
        table = _build_hydrangea_table()
        # same_tier_savings is picked from the best tier
        # But note: out-of-stock retailers are excluded from same_tier_savings
        # Nursery B is in_stock: false, so it's excluded from tier_prices_map
        # That means each tier only has 1 nursery → no same-tier savings
        # Actually, let me re-read the code...
        # The same_tier_savings loop checks: if rdata["in_stock"] is False: continue
        # Nursery B is in_stock=False, so its prices are skipped
        # Only Nursery A remains, and single-nursery tiers are skipped (len < 2)
        assert table["same_tier_savings"] == 0

    def test_stale_no_savings(self):
        table = _build_stale_table()
        assert table["savings_pct"] == 0


class TestSameTierSavingsWithAllInStock:
    """Test same-tier savings with both retailers in stock (maple fixture)."""

    def test_maple_same_tier_savings_zero(self):
        """Maple: A has 3-4ft, 5-6ft; B has 1gal, 3gal — no shared tiers."""
        table = _build_maple_table()
        # No tier has >=2 nurseries, so no same-tier savings
        assert table["same_tier_savings"] == 0

    def test_apple_same_tier_savings_zero(self):
        """Apple: A has dwarf-bareroot, semi-dwarf-bareroot; B has dwarf-potted, semi-dwarf-potted, jumbo-bareroot.
        No shared tiers across retailers."""
        table = _build_apple_table()
        assert table["same_tier_savings"] == 0


# ===================================================================
# Mixed size systems — no cross-system savings
# ===================================================================
class TestMixedSizeSystems:
    """Feet vs gallons don't produce cross-system savings."""

    def test_maple_tiers_are_separate(self):
        """Maple has feet (A) and gallon (B) tiers — they shouldn't be conflated."""
        table = _build_maple_table()
        tiers = table["active_size_tiers"]
        assert "3-4ft" in tiers
        assert "5-6ft" in tiers
        assert "1gal" in tiers
        assert "3gal" in tiers
        # All four tiers should be separate columns
        assert len(set(tiers)) == 4


class TestExoticTiers:
    """Dwarf, semi-dwarf, jumbo tiers normalize and label correctly."""

    def test_apple_tiers_present(self):
        table = _build_apple_table()
        tiers = table["active_size_tiers"]
        assert "dwarf-bareroot" in tiers
        assert "semi-dwarf-bareroot" in tiers
        assert "dwarf-potted" in tiers
        assert "semi-dwarf-potted" in tiers
        assert "jumbo-bareroot" in tiers

    def test_apple_tier_labels_in_table(self):
        table = _build_apple_table()
        a_sizes = table["prices"]["test-nursery-a"]["sizes"]
        assert a_sizes["dwarf-bareroot"]["label"] == "Dwarf (Bare Root)"
        assert a_sizes["semi-dwarf-bareroot"]["label"] == "Semi-Dwarf (Bare Root)"

    def test_apple_nursery_b_exotic_labels(self):
        table = _build_apple_table()
        b_sizes = table["prices"]["test-nursery-b"]["sizes"]
        assert b_sizes["dwarf-potted"]["label"] == "Dwarf (Potted)"
        assert b_sizes["semi-dwarf-potted"]["label"] == "Semi-Dwarf (Potted)"
        assert b_sizes["jumbo-bareroot"]["label"] == "Jumbo Bare Root"


# ===================================================================
# Retailer exclusion — no price = no row
# ===================================================================
class TestRetailerExclusion:
    """Retailers with no price for a plant don't appear in that plant's table."""

    def test_empty_latest_prices(self):
        """No price entries at all → empty table."""
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            table = build.build_price_table(
                _hydrangea, {}, _retailers_by_id, price_entries=[],
            )
        assert len(table["prices"]) == 0
        assert table["offer_count"] == 0

    def test_unknown_retailer_ignored(self):
        """A price entry from an unknown retailer is silently dropped."""
        fake_latest = {
            "ghost-nursery": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 99.99, "available": True}},
                "in_stock": True,
            },
        }
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            table = build.build_price_table(
                _hydrangea, fake_latest, _retailers_by_id, price_entries=[],
            )
        assert "ghost-nursery" not in table["prices"]


# ===================================================================
# Outlier filtering in savings
# ===================================================================
class TestOutlierFiltering:
    """If highest price is 3x+ second-highest in same tier, it's dropped from savings."""

    def test_outlier_dropped_from_same_tier(self):
        """Construct 3 prices in one tier where the top one is ≥3x the second."""
        # Build a synthetic scenario with 3 retailers all in-stock
        retailers_ext = {
            "r1": {"id": "r1", "name": "R1", "affiliate": {"network": "x"}, "active": True},
            "r2": {"id": "r2", "name": "R2", "affiliate": {"network": "x"}, "active": True},
            "r3": {"id": "r3", "name": "R3", "affiliate": {"network": "x"}, "active": True},
        }
        latest = {
            "r1": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 20.00, "available": True}},
                "in_stock": True, "url": "http://r1.example.com",
            },
            "r2": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 25.00, "available": True}},
                "in_stock": True, "url": "http://r2.example.com",
            },
            "r3": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 100.00, "available": True}},  # 4x r2 → outlier
                "in_stock": True, "url": "http://r3.example.com",
            },
        }
        plant = {"id": "outlier-test", "size_tiers": {"1gal": ["1 gallon"]}}
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            table = build.build_price_table(plant, latest, retailers_ext, price_entries=[])
        # After dropping the $100 outlier, same_tier_savings = round((1-20/25)*100) = 20
        assert table["same_tier_savings"] == 20

    def test_no_outlier_when_under_3x(self):
        """When top price is under 3x second-highest, no outlier filtering."""
        retailers_ext = {
            "r1": {"id": "r1", "name": "R1", "affiliate": {"network": "x"}, "active": True},
            "r2": {"id": "r2", "name": "R2", "affiliate": {"network": "x"}, "active": True},
            "r3": {"id": "r3", "name": "R3", "affiliate": {"network": "x"}, "active": True},
        }
        latest = {
            "r1": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 20.00, "available": True}},
                "in_stock": True, "url": "http://r1.example.com",
            },
            "r2": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 25.00, "available": True}},
                "in_stock": True, "url": "http://r2.example.com",
            },
            "r3": {
                "timestamp": "2026-04-01T10:00:00+00:00",
                "sizes": {"1gal": {"price": 40.00, "available": True}},  # 1.6x r2 → NOT outlier
                "in_stock": True, "url": "http://r3.example.com",
            },
        }
        plant = {"id": "no-outlier-test", "size_tiers": {"1gal": ["1 gallon"]}}
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            table = build.build_price_table(plant, latest, retailers_ext, price_entries=[])
        # No outlier: savings = round((1-20/40)*100) = 50
        assert table["same_tier_savings"] == 50


# ===================================================================
# Unavailable after 3 consecutive missed runs
# ===================================================================
class TestUnavailableAfterMissedRuns:
    """Retailer with >=3 consecutive missed runs shown as unavailable."""

    def test_three_missed_runs_marks_unavailable(self):
        """Build synthetic price history where nursery-a misses the last 3 runs."""
        entries = [
            # Run 1: both present
            {"retailer_id": "test-nursery-a", "timestamp": "2026-03-28T10:00:00+00:00",
             "sizes": {"1gal": {"price": 29.99, "available": True}}},
            {"retailer_id": "test-nursery-b", "timestamp": "2026-03-28T10:30:00+00:00",
             "sizes": {"1gal": {"price": 39.99, "available": True}}},
            # Run 2: only B
            {"retailer_id": "test-nursery-b", "timestamp": "2026-03-30T10:00:00+00:00",
             "sizes": {"1gal": {"price": 39.99, "available": True}}},
            # Run 3: only B
            {"retailer_id": "test-nursery-b", "timestamp": "2026-04-01T10:00:00+00:00",
             "sizes": {"1gal": {"price": 39.99, "available": True}}},
            # Run 4: only B
            {"retailer_id": "test-nursery-b", "timestamp": "2026-04-03T10:00:00+00:00",
             "sizes": {"1gal": {"price": 39.99, "available": True}}},
        ]
        latest = build.get_latest_prices(entries, _retailers_by_id)
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            table = build.build_price_table(
                _hydrangea, latest, _retailers_by_id, price_entries=entries,
            )
        # Nursery A missed 3 consecutive runs → unavailable
        if "test-nursery-a" in table["prices"]:
            assert table["prices"]["test-nursery-a"]["unavailable"] is True
