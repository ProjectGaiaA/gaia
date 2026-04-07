"""Tests for the polite scraping module (scrapers/polite.py)."""

from urllib.robotparser import RobotFileParser

from scrapers.polite import (
    random_ua,
    polite_headers,
    is_allowed_by_robots,
    polite_delay,
    make_polite_session,
    USER_AGENTS,
    _robots_cache,
)


def test_random_ua_returns_string_from_list():
    ua = random_ua()
    assert ua in USER_AGENTS
    assert isinstance(ua, str)
    assert len(ua) > 20


def test_polite_headers_includes_required_fields():
    headers = polite_headers()
    assert "User-Agent" in headers
    assert "Accept" in headers
    assert "DNT" in headers
    assert headers["DNT"] == "1"


def test_polite_headers_accepts_custom_ua():
    headers = polite_headers(ua="CustomAgent/1.0")
    assert headers["User-Agent"] == "CustomAgent/1.0"


def _make_robots_parser(rules_text: str) -> RobotFileParser:
    """Create a RobotFileParser from a rules string without fetching."""
    rp = RobotFileParser()
    rp.parse(rules_text.splitlines())
    return rp


def test_robots_allows_when_permitted():
    """robots.txt allowing all should return True."""
    _robots_cache.clear()
    parser = _make_robots_parser("User-agent: *\nAllow: /")
    _robots_cache["example.com"] = parser

    result = is_allowed_by_robots("https://example.com/products/test")
    assert result is True


def test_robots_denies_when_disallowed():
    """robots.txt disallowing path should return False."""
    _robots_cache.clear()
    parser = _make_robots_parser("User-agent: *\nDisallow: /products/")
    _robots_cache["blocked.com"] = parser

    result = is_allowed_by_robots("https://blocked.com/products/test")
    assert result is False


def test_robots_fail_open_when_unreachable():
    """Unreachable robots.txt should fail-open (return True)."""
    _robots_cache.clear()
    # None in cache means fetch failed — triggers fail-open
    _robots_cache["down.com"] = None

    result = is_allowed_by_robots("https://down.com/products/test")
    assert result is True


def test_polite_delay_returns_value_in_range(no_sleep):
    """polite_delay should return a float between min and max."""
    result = polite_delay(5.0, 15.0)
    assert 5.0 <= result <= 15.0


def test_make_polite_session_sets_headers():
    session = make_polite_session()
    assert "User-Agent" in session.headers
    assert "Accept" in session.headers
