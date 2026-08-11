"""Tests for scripts/check_liveness.py.

The contract: this is the ONLY check that sees what a visitor sees, so it must
fire on a stalled deploy and must NOT fire on a slow-but-working morning. Both
directions are tested, because a check that cannot fail is worthless and a check
that fires on healthy days gets muted.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
import responses

from scripts.check_liveness import check, fetch, parse_generated_at

NOW = datetime(2026, 8, 11, 14, 0, tzinfo=timezone.utc)
BASE = "https://example-ppt.test"


def _health(hours_old, now=NOW, price_hours_old=None):
    ts = now - timedelta(hours=hours_old)
    payload = {"generated_at": ts.isoformat(), "commit": "abc1234"}
    if price_hours_old is not None:
        payload["newest_price_at"] = (now - timedelta(hours=price_hours_old)).isoformat()
    return json.dumps(payload)


def _register(health_body=None, health_status=200, home_status=200):
    responses.add(responses.GET, BASE + "/", body="<html>ok</html>", status=home_status)
    if health_body is not None or health_status != 200:
        responses.add(
            responses.GET,
            BASE + "/health.json",
            body=health_body if health_body is not None else "",
            status=health_status,
        )


def _check(**kw):
    # sleep is stubbed out so retry paths don't add real seconds to the suite.
    return check(base=BASE, now=NOW, sleep=lambda _s: None, **kw)


# --- healthy ---

@responses.activate
def test_fresh_site_passes():
    _register(_health(3))
    ok, lines = _check()
    assert ok, lines


@responses.activate
def test_slow_but_legitimate_morning_does_not_alarm():
    """21h old is the measured worst case for a legitimate run. Must stay green."""
    _register(_health(21))
    ok, lines = _check()
    assert ok, f"false alarm on a legitimate slow day: {lines}"


# --- the failures this exists to catch ---

@responses.activate
def test_stale_content_fails():
    """The 25h publishing outage: site up, content frozen."""
    _register(_health(30))
    ok, lines = _check()
    assert not ok
    assert any("30.0h old" in ln for ln in lines)


@responses.activate
def test_site_down_fails():
    _register(_health(2), home_status=503)
    ok, lines = _check()
    assert not ok
    assert any("DOWN" in ln for ln in lines)


@responses.activate
def test_missing_health_json_fails():
    """A deploy that predates the heartbeat, or a broken publish."""
    _register(health_status=404)
    ok, lines = _check()
    assert not ok
    assert any("health.json unreachable" in ln for ln in lines)


@responses.activate
def test_unparseable_health_json_fails():
    _register("<!doctype html>not json")
    ok, lines = _check()
    assert not ok
    assert any("not valid JSON" in ln for ln in lines)


@responses.activate
def test_health_json_without_generated_at_fails():
    _register(json.dumps({"commit": "abc1234"}))
    ok, lines = _check()
    assert not ok
    assert any("no generated_at" in ln for ln in lines)


@responses.activate
def test_future_timestamp_fails_rather_than_passing():
    """Clock skew must not be able to buy a passing grade."""
    _register(_health(-10))
    ok, lines = _check()
    assert not ok
    assert any("FUTURE" in ln for ln in lines)


@responses.activate
def test_naive_timestamp_rejected():
    body = json.dumps({"generated_at": "2026-08-11T12:00:00"})
    _register(body)
    ok, lines = _check()
    assert not ok
    assert any("no timezone" in ln for ln in lines)


# --- retry behaviour: a blip is not an outage ---

@responses.activate
def test_transient_error_then_success_is_not_an_alarm():
    responses.add(responses.GET, BASE + "/", status=502)
    responses.add(responses.GET, BASE + "/", body="<html>ok</html>", status=200)
    responses.add(responses.GET, BASE + "/health.json", body=_health(2), status=200)
    ok, lines = _check()
    assert ok, lines


@responses.activate
def test_fetch_retries_then_gives_up():
    responses.add(responses.GET, BASE + "/x", status=500)
    responses.add(responses.GET, BASE + "/x", status=500)
    responses.add(responses.GET, BASE + "/x", status=500)
    resp, err = fetch(BASE + "/x", sleep=lambda _s: None)
    assert resp is None and "500" in err


# --- unit ---

@pytest.mark.parametrize("raw", ["", None, "not-a-date", "2026-13-45T00:00:00Z"])
def test_bad_generated_at_values_rejected(raw):
    ts, err = parse_generated_at(json.dumps({"generated_at": raw}))
    assert ts is None and err


def test_json_array_rejected():
    ts, err = parse_generated_at("[]")
    assert ts is None and "not a JSON object" in err


# --- the pipeline-green-but-data-frozen case ---

@responses.activate
def test_frozen_prices_fail_even_though_pipeline_is_fresh():
    """Pipeline runs on schedule, every scraper silently returns nothing.

    generated_at stays perfectly fresh forever; only newest_price_at exposes it.
    """
    _register(_health(2, price_hours_old=72))
    ok, lines = _check()
    assert not ok
    assert any("frozen prices" in ln for ln in lines)


@responses.activate
def test_prices_lagging_one_cycle_is_tolerated():
    """A single missed scrape must not page anyone."""
    _register(_health(2, price_hours_old=26))
    ok, lines = _check()
    assert ok, lines


@responses.activate
def test_health_json_without_newest_price_at_still_passes():
    """Older deploys predate the field; absent is tolerated, malformed is not."""
    _register(_health(2))
    assert _check()[0]


@responses.activate
def test_malformed_newest_price_at_fails():
    body = json.dumps({
        "generated_at": (NOW - timedelta(hours=2)).isoformat(),
        "newest_price_at": "sometime last tuesday",
    })
    _register(body)
    ok, lines = _check()
    assert not ok
    assert any("newest_price_at" in ln for ln in lines)


@responses.activate
def test_threshold_is_configurable():
    _register(_health(25))
    assert _check(stale_after=30)[0]
    assert not _check(stale_after=22)[0]
