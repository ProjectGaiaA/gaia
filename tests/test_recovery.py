"""Tests for recovery state management and 404/redirect detection."""

import json
from unittest.mock import patch

import requests as requests_lib
import responses

from scrapers.recovery import (
    FetchResult,
    load_recovery,
    save_recovery,
    record_broken,
    record_redirect_candidate,
    get_confirmed_candidates,
    get_pending_candidates,
    set_verdict,
    mark_applied,
    mark_confirmation_failed,
    extract_handle_from_url,
)
from scrapers.shopify import ShopifyScraper, load_handle_maps, save_handle_map_entry
from tests.conftest import load_fixture


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


def test_fetch_result_with_data():
    """FetchResult stores data, status_code, and redirect_url."""
    r = FetchResult(data={"product": {}}, status_code=200, redirect_url=None)
    assert r.data == {"product": {}}
    assert r.status_code == 200
    assert r.redirect_url is None


def test_fetch_result_with_redirect():
    """FetchResult stores redirect URL on 301."""
    r = FetchResult(data=None, status_code=301, redirect_url="https://shop.com/products/new-handle.json")
    assert r.status_code == 301
    assert r.redirect_url == "https://shop.com/products/new-handle.json"
    assert r.data is None


def test_fetch_result_on_failure():
    """FetchResult can represent a total failure (no response)."""
    r = FetchResult(data=None, status_code=None, redirect_url=None)
    assert r.data is None
    assert r.status_code is None


# ---------------------------------------------------------------------------
# extract_handle_from_url
# ---------------------------------------------------------------------------


def test_extract_handle_from_full_url():
    assert extract_handle_from_url("https://shop.com/products/new-handle.json") == "new-handle"


def test_extract_handle_from_url_no_json():
    assert extract_handle_from_url("https://shop.com/products/new-handle") == "new-handle"


def test_extract_handle_from_relative_url():
    assert extract_handle_from_url("/products/new-handle.json") == "new-handle"


def test_extract_handle_no_products_path():
    assert extract_handle_from_url("https://shop.com/collections/all") is None


def test_extract_handle_with_query_params():
    assert extract_handle_from_url("https://shop.com/products/new-handle?variant=123") == "new-handle"


# ---------------------------------------------------------------------------
# load_recovery / save_recovery
# ---------------------------------------------------------------------------


def test_load_recovery_no_file(tmp_path):
    """Returns empty structure when file doesn't exist."""
    with patch("scrapers.recovery.RECOVERY_PATH", tmp_path / "recovery.json"):
        state = load_recovery()
    assert state == {"entries": {}}


def test_load_recovery_malformed_json(tmp_path):
    """Returns empty structure when file contains invalid JSON."""
    bad_file = tmp_path / "recovery.json"
    bad_file.write_text("not json", encoding="utf-8")
    with patch("scrapers.recovery.RECOVERY_PATH", bad_file):
        state = load_recovery()
    assert state == {"entries": {}}


def test_save_and_load_roundtrip(tmp_path):
    """save_recovery then load_recovery returns the same data."""
    path = tmp_path / "recovery.json"
    state = {"entries": {"nature-hills:limelight": {"status": "broken"}}}
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        loaded = load_recovery()
    assert loaded == state


# ---------------------------------------------------------------------------
# record_broken
# ---------------------------------------------------------------------------


def test_record_broken_creates_entry(tmp_path):
    """record_broken creates a recovery.json entry with status 'broken'."""
    path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        record_broken("nature-hills", "limelight-hydrangea", "hydrangea-lime-light")
        state = load_recovery()

    key = "nature-hills:limelight-hydrangea"
    assert key in state["entries"]
    entry = state["entries"][key]
    assert entry["status"] == "broken"
    assert entry["old_handle"] == "hydrangea-lime-light"
    assert entry["retailer_id"] == "nature-hills"
    assert entry["plant_id"] == "limelight-hydrangea"
    assert entry["candidate_handle"] is None
    assert entry["attempts"] == 0


def test_record_broken_does_not_overwrite_candidate(tmp_path):
    """If entry already has a candidate, record_broken does not overwrite it."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "nature-hills:limelight-hydrangea": {
                "status": "redirect_candidate",
                "candidate_handle": "new-handle",
                "old_handle": "old-handle",
                "created_at": "2026-04-01T00:00:00Z",
                "attempts": 0,
            }
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        record_broken("nature-hills", "limelight-hydrangea", "old-handle")
        loaded = load_recovery()

    # Should NOT have been overwritten
    assert loaded["entries"]["nature-hills:limelight-hydrangea"]["status"] == "redirect_candidate"
    assert loaded["entries"]["nature-hills:limelight-hydrangea"]["candidate_handle"] == "new-handle"


# ---------------------------------------------------------------------------
# record_redirect_candidate
# ---------------------------------------------------------------------------


def test_record_redirect_candidate_creates_entry(tmp_path):
    """301 redirect creates entry with status 'redirect_candidate'."""
    path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        record_redirect_candidate(
            "nature-hills",
            "limelight-hydrangea",
            "old-handle",
            "new-handle",
            "https://shop.com/products/new-handle.json",
        )
        state = load_recovery()

    key = "nature-hills:limelight-hydrangea"
    assert key in state["entries"]
    entry = state["entries"][key]
    assert entry["status"] == "redirect_candidate"
    assert entry["old_handle"] == "old-handle"
    assert entry["candidate_handle"] == "new-handle"
    assert entry["redirect_url"] == "https://shop.com/products/new-handle.json"


# ---------------------------------------------------------------------------
# get_confirmed_candidates / mark_applied / mark_confirmation_failed
# ---------------------------------------------------------------------------


def test_get_confirmed_candidates_filters(tmp_path):
    """Only entries with status 'confirmed' are returned."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "confirmed", "candidate_handle": "h1", "retailer_id": "r1", "plant_id": "p1"},
            "r2:p2": {"status": "broken", "candidate_handle": None, "retailer_id": "r2", "plant_id": "p2"},
            "r3:p3": {"status": "confirmed", "candidate_handle": "h3", "retailer_id": "r3", "plant_id": "p3"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        candidates = get_confirmed_candidates()

    assert len(candidates) == 2
    handles = {c["candidate_handle"] for c in candidates}
    assert handles == {"h1", "h3"}


def test_get_confirmed_returns_empty_when_none(tmp_path):
    """Returns empty list when no confirmed candidates exist."""
    path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        candidates = get_confirmed_candidates()
    assert candidates == []


def test_mark_applied_removes_entry(tmp_path):
    """mark_applied removes the entry from recovery.json."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "confirmed", "candidate_handle": "h1"},
            "r2:p2": {"status": "broken"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        mark_applied("r1", "p1")
        loaded = load_recovery()

    assert "r1:p1" not in loaded["entries"]
    assert "r2:p2" in loaded["entries"]


def test_mark_confirmation_failed_flags_entry(tmp_path):
    """mark_confirmation_failed changes status and adds reason."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {
                "status": "confirmed",
                "candidate_handle": "h1",
                "updated_at": "2026-04-01T00:00:00Z",
            }
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        mark_confirmation_failed("r1", "p1")
        loaded = load_recovery()

    entry = loaded["entries"]["r1:p1"]
    assert entry["status"] == "confirmation_failed"
    assert "404" in entry["reason"]


# ---------------------------------------------------------------------------
# _get_json returns FetchResult
# ---------------------------------------------------------------------------


@responses.activate
def test_get_json_returns_fetch_result_on_200(no_sleep):
    """_get_json returns FetchResult with data on success."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/hydrangea-lime-light.json",
        json=fixture,
        status=200,
    )
    scraper = ShopifyScraper("nature-hills", "https://www.naturehills.com")
    result = scraper._get_json("https://www.naturehills.com/products/hydrangea-lime-light.json")

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    assert result.data is not None
    assert "product" in result.data
    assert result.redirect_url is None


@responses.activate
def test_get_json_returns_fetch_result_on_404(no_sleep):
    """_get_json returns FetchResult with status 404 and no data."""
    responses.add(
        responses.GET,
        "https://shop.com/products/gone.json",
        status=404,
    )
    scraper = ShopifyScraper("test", "https://shop.com")
    result = scraper._get_json("https://shop.com/products/gone.json")

    assert isinstance(result, FetchResult)
    assert result.status_code == 404
    assert result.data is None
    assert result.redirect_url is None


@responses.activate
def test_get_json_returns_fetch_result_on_301(no_sleep):
    """_get_json with allow_redirects=False returns redirect URL on 301."""
    responses.add(
        responses.GET,
        "https://shop.com/products/old-handle.json",
        status=301,
        headers={"Location": "https://shop.com/products/new-handle.json"},
    )
    scraper = ShopifyScraper("test", "https://shop.com")
    result = scraper._get_json(
        "https://shop.com/products/old-handle.json",
        allow_redirects=False,
    )

    assert isinstance(result, FetchResult)
    assert result.status_code == 301
    assert result.redirect_url == "https://shop.com/products/new-handle.json"
    assert result.data is None


@responses.activate
def test_get_json_returns_fetch_result_on_500(no_sleep):
    """_get_json returns FetchResult with status 500 and no data."""
    responses.add(
        responses.GET,
        "https://shop.com/products/error.json",
        status=500,
    )
    scraper = ShopifyScraper("test", "https://shop.com")
    result = scraper._get_json("https://shop.com/products/error.json")

    assert isinstance(result, FetchResult)
    assert result.status_code == 500
    assert result.data is None


@responses.activate
def test_get_json_returns_fetch_result_on_network_error(no_sleep):
    """_get_json returns FetchResult with None status on network failure."""
    responses.add(
        responses.GET,
        "https://shop.com/products/timeout.json",
        body=requests_lib.ConnectionError("Connection refused"),
    )
    scraper = ShopifyScraper("test", "https://shop.com")
    result = scraper._get_json("https://shop.com/products/timeout.json")

    assert isinstance(result, FetchResult)
    assert result.status_code is None
    assert result.data is None


# ---------------------------------------------------------------------------
# scrape_product: 404 records broken handle
# ---------------------------------------------------------------------------


@responses.activate
def test_scrape_product_404_records_broken(no_sleep, tmp_path):
    """When product returns 404, a broken entry appears in recovery.json."""
    # JSON 404
    responses.add(
        responses.GET,
        "https://shop.com/products/old-handle.json",
        status=404,
    )
    # HTML 404 (fallback also fails)
    responses.add(
        responses.GET,
        "https://shop.com/products/old-handle",
        status=404,
    )

    recovery_path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", recovery_path):
        scraper = ShopifyScraper("nature-hills", "https://shop.com")
        result = scraper.scrape_product("old-handle", plant_id="limelight-hydrangea")

    assert result is None

    state = json.loads(recovery_path.read_text(encoding="utf-8"))
    key = "nature-hills:limelight-hydrangea"
    assert key in state["entries"]
    assert state["entries"][key]["status"] == "broken"
    assert state["entries"][key]["old_handle"] == "old-handle"


@responses.activate
def test_scrape_product_404_without_plant_id_skips_recording(no_sleep, tmp_path):
    """When plant_id is None, 404 does not record to recovery.json."""
    responses.add(responses.GET, "https://shop.com/products/handle.json", status=404)
    responses.add(responses.GET, "https://shop.com/products/handle", status=404)

    recovery_path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", recovery_path):
        scraper = ShopifyScraper("test", "https://shop.com")
        scraper.scrape_product("handle")  # no plant_id

    assert not recovery_path.exists()


# ---------------------------------------------------------------------------
# scrape_product: 301 records redirect candidate
# ---------------------------------------------------------------------------


@responses.activate
def test_scrape_product_301_records_redirect(no_sleep, tmp_path):
    """When product returns 301, redirect candidate is recorded and data fetched."""
    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")

    # First request: 301 redirect
    responses.add(
        responses.GET,
        "https://shop.com/products/old-handle.json",
        status=301,
        headers={"Location": "https://shop.com/products/new-handle.json"},
    )
    # Follow-up request to new URL: 200 with data
    responses.add(
        responses.GET,
        "https://shop.com/products/new-handle.json",
        json=fixture,
        status=200,
    )

    recovery_path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", recovery_path):
        scraper = ShopifyScraper("nature-hills", "https://shop.com")
        result = scraper.scrape_product("old-handle", plant_id="limelight-hydrangea")

    # Data should still be returned for this run
    assert result is not None
    assert result["title"] == "Limelight Hydrangea"

    # Redirect candidate should be recorded
    state = json.loads(recovery_path.read_text(encoding="utf-8"))
    key = "nature-hills:limelight-hydrangea"
    assert key in state["entries"]
    assert state["entries"][key]["status"] == "redirect_candidate"
    assert state["entries"][key]["candidate_handle"] == "new-handle"


# ---------------------------------------------------------------------------
# scrape_product: 5xx skips silently (no recovery entry)
# ---------------------------------------------------------------------------


@responses.activate
def test_scrape_product_500_no_recovery_entry(no_sleep, tmp_path):
    """5xx errors don't create recovery entries — server problem, not handle change."""
    responses.add(responses.GET, "https://shop.com/products/handle.json", status=500)

    recovery_path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", recovery_path):
        scraper = ShopifyScraper("test", "https://shop.com")
        result = scraper.scrape_product("handle", plant_id="some-plant")

    assert result is None
    assert not recovery_path.exists()


# ---------------------------------------------------------------------------
# save_handle_map_entry / startup candidate validation
# ---------------------------------------------------------------------------


def test_save_handle_map_entry(tmp_path):
    """save_handle_map_entry writes a new handle to handle_maps.json."""
    maps = {"nature-hills": {"plant-a": "old-handle"}}
    maps_path = tmp_path / "handle_maps.json"
    maps_path.write_text(json.dumps(maps), encoding="utf-8")

    import scrapers.shopify as mod
    mod._handle_maps_cache = None

    with patch("scrapers.shopify._HANDLE_MAPS_PATH", maps_path):
        save_handle_map_entry("nature-hills", "plant-a", "new-handle")

        # Verify file was updated
        updated = json.loads(maps_path.read_text(encoding="utf-8"))
        assert updated["nature-hills"]["plant-a"] == "new-handle"

        # Verify cache was invalidated and returns new data
        mod._handle_maps_cache = None
        reloaded = load_handle_maps()
        assert reloaded["nature-hills"]["plant-a"] == "new-handle"


def test_save_handle_map_entry_preserves_formatting(tmp_path):
    """save_handle_map_entry writes valid JSON with indent."""
    maps = {"r1": {"p1": "h1"}}
    maps_path = tmp_path / "handle_maps.json"
    maps_path.write_text(json.dumps(maps), encoding="utf-8")

    import scrapers.shopify as mod
    mod._handle_maps_cache = None

    with patch("scrapers.shopify._HANDLE_MAPS_PATH", maps_path):
        save_handle_map_entry("r1", "p1", "h2")

    raw = maps_path.read_text(encoding="utf-8")
    assert "\n" in raw  # indented
    parsed = json.loads(raw)
    assert parsed["r1"]["p1"] == "h2"


def test_save_handle_map_entry_new_retailer(tmp_path):
    """save_handle_map_entry creates retailer key if it doesn't exist."""
    maps = {"nature-hills": {"plant-a": "handle-a"}}
    maps_path = tmp_path / "handle_maps.json"
    maps_path.write_text(json.dumps(maps), encoding="utf-8")

    import scrapers.shopify as mod
    mod._handle_maps_cache = None

    with patch("scrapers.shopify._HANDLE_MAPS_PATH", maps_path):
        save_handle_map_entry("new-retailer", "plant-b", "handle-b")

        updated = json.loads(maps_path.read_text(encoding="utf-8"))
        assert updated["new-retailer"]["plant-b"] == "handle-b"
        # Original data preserved
        assert updated["nature-hills"]["plant-a"] == "handle-a"


# ---------------------------------------------------------------------------
# validate_confirmed_candidates (runner.py startup)
# ---------------------------------------------------------------------------


@responses.activate
def test_validate_confirmed_candidate_applies_on_200(no_sleep, tmp_path):
    """Confirmed candidate returning valid product data gets written to handle_maps
    and removed from recovery.json."""
    from scrapers.runner import validate_confirmed_candidates

    fixture = load_fixture("nature-hills", "limelight-hydrangea-product.json")

    # Set up recovery.json with a confirmed candidate
    recovery_path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "nature-hills:limelight-hydrangea": {
                "retailer_id": "nature-hills",
                "plant_id": "limelight-hydrangea",
                "old_handle": "old-handle",
                "status": "confirmed",
                "candidate_handle": "new-handle",
            }
        }
    }
    save_recovery_to(recovery_path, state)

    # Set up handle_maps.json
    maps_path = tmp_path / "handle_maps.json"
    maps_path.write_text(json.dumps({"nature-hills": {"limelight-hydrangea": "old-handle"}}))

    # Set up retailers.json
    retailers_path = tmp_path / "retailers.json"
    retailers_path.write_text(json.dumps([
        {"id": "nature-hills", "url": "https://www.naturehills.com", "active": True, "scraper_type": "shopify"},
    ]))

    # Mock the validation request
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/new-handle.json",
        json=fixture,
        status=200,
    )

    import scrapers.shopify as mod
    mod._handle_maps_cache = None

    with (
        patch("scrapers.recovery.RECOVERY_PATH", recovery_path),
        patch("scrapers.shopify._HANDLE_MAPS_PATH", maps_path),
        patch("scrapers.runner.DATA_DIR", tmp_path),
    ):
        validate_confirmed_candidates()

    # handle_maps.json should have the new handle
    updated_maps = json.loads(maps_path.read_text(encoding="utf-8"))
    assert updated_maps["nature-hills"]["limelight-hydrangea"] == "new-handle"

    # recovery.json should no longer have the entry
    updated_recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert "nature-hills:limelight-hydrangea" not in updated_recovery["entries"]


@responses.activate
def test_validate_confirmed_candidate_flags_on_404(no_sleep, tmp_path):
    """Confirmed candidate that still 404s stays in recovery.json and is flagged."""
    from scrapers.runner import validate_confirmed_candidates

    recovery_path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "nature-hills:limelight-hydrangea": {
                "retailer_id": "nature-hills",
                "plant_id": "limelight-hydrangea",
                "old_handle": "old-handle",
                "status": "confirmed",
                "candidate_handle": "bad-handle",
                "updated_at": "2026-04-01T00:00:00Z",
            }
        }
    }
    save_recovery_to(recovery_path, state)

    retailers_path = tmp_path / "retailers.json"
    retailers_path.write_text(json.dumps([
        {"id": "nature-hills", "url": "https://www.naturehills.com", "active": True},
    ]))

    # The candidate handle still 404s
    responses.add(
        responses.GET,
        "https://www.naturehills.com/products/bad-handle.json",
        status=404,
    )

    with (
        patch("scrapers.recovery.RECOVERY_PATH", recovery_path),
        patch("scrapers.runner.DATA_DIR", tmp_path),
    ):
        validate_confirmed_candidates()

    # Entry should still exist, flagged
    updated = json.loads(recovery_path.read_text(encoding="utf-8"))
    entry = updated["entries"]["nature-hills:limelight-hydrangea"]
    assert entry["status"] == "confirmation_failed"
    assert "404" in entry["reason"]


# ---------------------------------------------------------------------------
# get_pending_candidates
# ---------------------------------------------------------------------------


def test_get_pending_candidates_returns_redirect_and_discovery(tmp_path):
    """get_pending_candidates returns redirect_candidate and discovery_candidate entries."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "redirect_candidate", "retailer_id": "r1", "plant_id": "p1", "candidate_handle": "h1"},
            "r2:p2": {"status": "discovery_candidate", "retailer_id": "r2", "plant_id": "p2", "candidate_handle": "h2"},
            "r3:p3": {"status": "broken", "retailer_id": "r3", "plant_id": "p3"},
            "r4:p4": {"status": "confirmed", "retailer_id": "r4", "plant_id": "p4", "candidate_handle": "h4"},
            "r5:p5": {"status": "rejected", "retailer_id": "r5", "plant_id": "p5"},
            "r6:p6": {"status": "unrecoverable", "retailer_id": "r6", "plant_id": "p6"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        pending = get_pending_candidates()

    assert len(pending) == 2
    statuses = {p["status"] for p in pending}
    assert statuses == {"redirect_candidate", "discovery_candidate"}
    handles = {p["candidate_handle"] for p in pending}
    assert handles == {"h1", "h2"}


def test_get_pending_candidates_empty_when_none(tmp_path):
    """Returns empty list when no pending candidates exist."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "broken"},
            "r2:p2": {"status": "confirmed", "candidate_handle": "h2"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        pending = get_pending_candidates()

    assert pending == []


def test_get_pending_candidates_empty_file(tmp_path):
    """Returns empty list when recovery.json doesn't exist."""
    path = tmp_path / "recovery.json"
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        pending = get_pending_candidates()
    assert pending == []


# ---------------------------------------------------------------------------
# set_verdict
# ---------------------------------------------------------------------------


def test_set_verdict_confirmed(tmp_path):
    """set_verdict('confirmed') updates status and adds reason."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {
                "status": "redirect_candidate",
                "retailer_id": "r1",
                "plant_id": "p1",
                "candidate_handle": "h1",
                "updated_at": "2026-04-01T00:00:00Z",
            }
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        set_verdict("r1", "p1", "confirmed", "Name and sizes match")
        loaded = load_recovery()

    entry = loaded["entries"]["r1:p1"]
    assert entry["status"] == "confirmed"
    assert entry["reason"] == "Name and sizes match"
    assert entry["updated_at"] != "2026-04-01T00:00:00Z"


def test_set_verdict_rejected(tmp_path):
    """set_verdict('rejected') updates status and adds reason."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {
                "status": "discovery_candidate",
                "retailer_id": "r1",
                "plant_id": "p1",
                "candidate_handle": "h1",
                "updated_at": "2026-04-01T00:00:00Z",
            }
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        set_verdict("r1", "p1", "rejected", "Different cultivar: tree form vs shrub")
        loaded = load_recovery()

    entry = loaded["entries"]["r1:p1"]
    assert entry["status"] == "rejected"
    assert "tree form" in entry["reason"]


def test_set_verdict_invalid_verdict_raises(tmp_path):
    """set_verdict raises ValueError for invalid verdict strings."""
    path = tmp_path / "recovery.json"
    state = {"entries": {"r1:p1": {"status": "redirect_candidate", "updated_at": "2026-04-01T00:00:00Z"}}}
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        try:
            set_verdict("r1", "p1", "maybe", "unsure")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "confirmed" in str(e)
            assert "rejected" in str(e)


def test_set_verdict_missing_entry_is_noop(tmp_path):
    """set_verdict on nonexistent entry does nothing."""
    path = tmp_path / "recovery.json"
    state = {"entries": {}}
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        set_verdict("r1", "p1", "confirmed", "test")
        loaded = load_recovery()

    assert loaded == {"entries": {}}


def test_set_verdict_preserves_other_entries(tmp_path):
    """set_verdict does not disturb unrelated entries."""
    path = tmp_path / "recovery.json"
    state = {
        "entries": {
            "r1:p1": {"status": "redirect_candidate", "candidate_handle": "h1", "updated_at": "2026-04-01T00:00:00Z"},
            "r2:p2": {"status": "broken", "old_handle": "oh2"},
        }
    }
    with patch("scrapers.recovery.RECOVERY_PATH", path):
        save_recovery(state)
        set_verdict("r1", "p1", "confirmed", "match confirmed")
        loaded = load_recovery()

    assert loaded["entries"]["r1:p1"]["status"] == "confirmed"
    assert loaded["entries"]["r2:p2"]["status"] == "broken"
    assert loaded["entries"]["r2:p2"]["old_handle"] == "oh2"


def save_recovery_to(path, state):
    """Helper: write recovery state to a specific path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
