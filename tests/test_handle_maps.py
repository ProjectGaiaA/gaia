"""Tests for handle map loading from data/handle_maps.json."""

import json
from unittest.mock import patch

from scrapers.shopify import load_handle_maps, get_handles_for_retailer, _HANDLE_MAPS_PATH


def setup_function():
    """Clear the handle maps cache before each test."""
    import scrapers.shopify as mod
    mod._handle_maps_cache = None


# --- load_handle_maps ---


def test_load_handle_maps_reads_json_file():
    """load_handle_maps() returns the contents of data/handle_maps.json."""
    maps = load_handle_maps()
    assert isinstance(maps, dict)
    assert "nature-hills" in maps
    assert "fast-growing-trees" in maps


def test_load_handle_maps_has_expected_retailers():
    """All 7 retailers from the original HANDLE_MAPS are present."""
    maps = load_handle_maps()
    expected = [
        "fast-growing-trees",
        "proven-winners-direct",
        "nature-hills",
        "spring-hill",
        "planting-tree",
        "great-garden-plants",
        "brighter-blooms",
    ]
    for retailer in expected:
        assert retailer in maps, f"Missing retailer: {retailer}"


def test_load_handle_maps_spot_check_handles():
    """Spot-check known handle mappings survive extraction."""
    maps = load_handle_maps()
    assert maps["nature-hills"]["limelight-hydrangea"] == "hydrangea-lime-light"
    assert maps["fast-growing-trees"]["limelight-hydrangea"] == "limelight-hydrangea-shrub"
    assert maps["brighter-blooms"]["honeycrisp-apple-tree"] == "honeycrisp-apple"
    assert maps["planting-tree"]["bing-cherry-tree"] == "bing-cherry-tree"


def test_load_handle_maps_caches_result():
    """Second call returns the same object without re-reading the file."""
    maps1 = load_handle_maps()
    maps2 = load_handle_maps()
    assert maps1 is maps2


def test_load_handle_maps_from_tmp_file(tmp_path):
    """load_handle_maps() reads from the path pointed to by _HANDLE_MAPS_PATH."""
    fake_maps = {"test-retailer": {"plant-a": "handle-a"}}
    fake_path = tmp_path / "handle_maps.json"
    fake_path.write_text(json.dumps(fake_maps), encoding="utf-8")

    with patch("scrapers.shopify._HANDLE_MAPS_PATH", fake_path):
        import scrapers.shopify as mod
        mod._handle_maps_cache = None
        result = load_handle_maps()

    assert result == fake_maps


# --- get_handles_for_retailer ---


def test_get_handles_returns_mapped_plants():
    """get_handles_for_retailer filters to plants in the handle map."""
    result = get_handles_for_retailer(
        "nature-hills",
        ["limelight-hydrangea", "nonexistent-plant", "bloodgood-japanese-maple"],
    )
    assert "limelight-hydrangea" in result
    assert "bloodgood-japanese-maple" in result
    assert "nonexistent-plant" not in result


def test_get_handles_unknown_retailer_returns_empty():
    """Unknown retailer returns an empty dict."""
    result = get_handles_for_retailer("unknown-retailer", ["limelight-hydrangea"])
    assert result == {}


def test_get_handles_empty_plant_list():
    """Empty plant list returns empty dict."""
    result = get_handles_for_retailer("nature-hills", [])
    assert result == {}


# --- JSON file integrity ---


def test_handle_maps_json_is_valid():
    """data/handle_maps.json parses as valid JSON with expected structure."""
    with open(_HANDLE_MAPS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    for retailer_id, mapping in data.items():
        assert isinstance(retailer_id, str)
        assert isinstance(mapping, dict)
        for plant_id, handle in mapping.items():
            assert isinstance(plant_id, str)
            assert isinstance(handle, str)
            assert len(handle) > 0, f"Empty handle for {retailer_id}/{plant_id}"


def test_handle_maps_json_total_count():
    """Total handle count matches expected after catalog expansion discovery."""
    with open(_HANDLE_MAPS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    total = sum(len(v) for v in data.values())
    assert total >= 186, f"Expected at least 186 handles, got {total}"
