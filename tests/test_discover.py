"""Tests for handle discovery fuzzy matching (scrapers/discover_handles.py)."""

import inspect
from unittest.mock import MagicMock, patch

from scrapers.discover_handles import (
    fetch_all_products,
    match_score,
    normalize_for_matching,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _products_response(products, status_code=200):
    """Create a mock response returning *products*."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"products": products}
    return resp


def _fake_products(n, start=0):
    """Generate *n* minimal Shopify product dicts."""
    return [{"id": start + i, "title": f"Plant {start + i}", "handle": f"plant-{start + i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# Task 3 — polite discovery wiring
# ---------------------------------------------------------------------------


class TestFetchUsesPoliteSession:
    """fetch_all_products must route through polite.py, never raw requests."""

    def test_uses_provided_session(self):
        session = MagicMock()
        session.get.return_value = _products_response(_fake_products(3))

        with patch("scrapers.discover_handles.discovery_delay"):
            with patch("scrapers.discover_handles.is_allowed_by_robots", return_value=True):
                result = fetch_all_products("https://example.com", session=session)

        assert len(result) == 3
        session.get.assert_called_once()
        assert "example.com" in session.get.call_args[0][0]

    def test_creates_polite_session_when_none_provided(self):
        mock_session = MagicMock()
        mock_session.get.return_value = _products_response(_fake_products(1))

        with patch("scrapers.discover_handles.make_polite_session", return_value=mock_session) as make_sess:
            with patch("scrapers.discover_handles.discovery_delay"):
                with patch("scrapers.discover_handles.is_allowed_by_robots", return_value=True):
                    fetch_all_products("https://example.com")

        make_sess.assert_called_once()
        mock_session.get.assert_called_once()

    def test_no_raw_requests_get_in_source(self):
        """The function source must not contain requests.get(...)."""
        source = inspect.getsource(fetch_all_products)
        assert "requests.get(" not in source


class TestFetchRobotsCheck:
    """fetch_all_products must honour robots.txt for every page."""

    def test_checked_before_each_page(self):
        page1 = _fake_products(250)
        page2 = _fake_products(2, start=250)
        session = MagicMock()
        session.get.side_effect = [
            _products_response(page1),
            _products_response(page2),
        ]

        with patch("scrapers.discover_handles.discovery_delay"):
            with patch("scrapers.discover_handles.is_allowed_by_robots", return_value=True) as robots:
                fetch_all_products("https://example.com", session=session)

        assert robots.call_count == 2
        urls = [c[0][0] for c in robots.call_args_list]
        assert "page=1" in urls[0]
        assert "page=2" in urls[1]

    def test_stops_when_robots_disallows(self):
        session = MagicMock()

        with patch("scrapers.discover_handles.discovery_delay"):
            with patch("scrapers.discover_handles.is_allowed_by_robots", return_value=False):
                result = fetch_all_products("https://example.com", session=session)

        session.get.assert_not_called()
        assert result == []


class TestFetchDiscoveryDelay:
    """Catalog fetching must use 10-20 s discovery delays, not time.sleep(3)."""

    def test_discovery_delay_called_between_pages(self):
        page1 = _fake_products(250)
        page2 = _fake_products(1, start=250)
        session = MagicMock()
        session.get.side_effect = [
            _products_response(page1),
            _products_response(page2),
        ]

        with patch("scrapers.discover_handles.discovery_delay") as delay:
            with patch("scrapers.discover_handles.is_allowed_by_robots", return_value=True):
                fetch_all_products("https://example.com", session=session)

        delay.assert_called_once()

    def test_no_time_sleep_in_source(self):
        source = inspect.getsource(fetch_all_products)
        assert "time.sleep" not in source


# --- Normalization ---


def test_normalize_removes_common_suffixes():
    assert "limelight hydrangea" == normalize_for_matching("Limelight Hydrangea Tree")
    assert "bloodgood japanese maple" == normalize_for_matching("Bloodgood Japanese Maple Shrub")


def test_normalize_removes_trademark_symbols():
    result = normalize_for_matching("Knock Out® Rose Bush")
    assert "®" not in result


def test_normalize_removes_botanical_parenthetical():
    result = normalize_for_matching("Limelight Hydrangea (Hydrangea paniculata)")
    assert "paniculata" not in result


def test_normalize_strips_proven_winners_prefix():
    result = normalize_for_matching("Proven Winners® Limelight Prime")
    assert "proven winners" not in result
    assert "limelight prime" in result


# --- Match scoring ---


def test_exact_match_after_normalization():
    """Exact name match (after normalization) should score 1.0."""
    score = match_score("Limelight Hydrangea", "Limelight Hydrangea Tree")
    assert score == 1.0


def test_partial_word_overlap():
    """Partial word overlap should score proportionally."""
    score = match_score("Honeycrisp Apple", "Honeycrisp Apple Tree for Sale")
    assert 0.5 < score <= 1.0


def test_no_match_scores_low():
    """Completely unrelated names should score near 0."""
    score = match_score("Limelight Hydrangea", "Red Knockout Rose")
    assert score < 0.5


def test_empty_strings_score_zero():
    assert match_score("", "Something") == 0.0
    assert match_score("Something", "") == 0.0
