"""Tests for per-product affiliate link overrides in build.py.

Two properties matter more than the feature itself:

  1. A broken monetization file must NEVER stop the site building. Revenue
     plumbing failing closed on the whole site is a far worse outcome than a
     missing commission.
  2. An override must change the outbound URL and NOTHING else — not prices,
     not ranking, not which retailers appear. The moment monetization can move
     the comparison, the comparison is worthless.
"""

import json

import pytest

from build import affiliate_override, load_affiliate_overrides

OVERRIDES = {"ajuga-chocolate-chip": {"fast-growing-trees": "https://sovrn.co/1c61g6j"}}


def _write(tmp_path, payload):
    p = tmp_path / "affiliate_overrides.json"
    p.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )
    return str(p)


# --- lookup ---

def test_matching_plant_and_retailer_returns_url():
    assert affiliate_override(
        "ajuga-chocolate-chip", "fast-growing-trees", OVERRIDES
    ) == "https://sovrn.co/1c61g6j"


def test_other_retailer_on_same_plant_is_untouched():
    assert affiliate_override("ajuga-chocolate-chip", "nature-hills", OVERRIDES) is None


def test_same_retailer_on_other_plant_is_untouched():
    """One link means ONE link — it must not leak onto 101 other pages."""
    assert affiliate_override("limelight-hydrangea", "fast-growing-trees", OVERRIDES) is None


def test_unknown_plant_returns_none():
    assert affiliate_override("nonexistent", "fast-growing-trees", OVERRIDES) is None


def test_none_plant_id_does_not_crash():
    assert affiliate_override(None, "fast-growing-trees", OVERRIDES) is None


# --- only absolute http(s) URLs reach an href ---

@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "/relative/path",
    "data:text/html,<script>alert(1)</script>",
    "",
    None,
    123,
    ["https://example.com"],
])
def test_non_http_values_are_ignored(bad):
    assert affiliate_override("p", "r", {"p": {"r": bad}}) is None


def test_malformed_plant_entry_is_ignored():
    assert affiliate_override("p", "r", {"p": "not-a-dict"}) is None


# --- a broken file must not break the build ---

def test_missing_file_yields_no_overrides(tmp_path):
    assert load_affiliate_overrides(str(tmp_path / "nope.json")) == {}


def test_corrupt_json_yields_no_overrides(tmp_path):
    assert load_affiliate_overrides(_write(tmp_path, "{not json")) == {}


def test_wrong_shape_yields_no_overrides(tmp_path):
    assert load_affiliate_overrides(_write(tmp_path, {"overrides": "nope"})) == {}
    assert load_affiliate_overrides(_write(tmp_path, ["a", "b"])) == {}
    assert load_affiliate_overrides(_write(tmp_path, {})) == {}


def test_real_file_parses_and_contains_the_live_link():
    """Guards the shipped file itself, not just the loader."""
    table = load_affiliate_overrides("data/affiliate_overrides.json")
    assert affiliate_override(
        "ajuga-chocolate-chip", "fast-growing-trees", table
    ) == "https://sovrn.co/1c61g6j"


def test_shipped_file_has_exactly_one_override():
    """Deliberately narrow: the account is unapproved, so links earn nothing.

    Fails loudly if links get wired site-wide without a conscious decision.
    """
    table = load_affiliate_overrides("data/affiliate_overrides.json")
    total = sum(len(v) for v in table.values() if isinstance(v, dict))
    assert total == 1, f"expected 1 affiliate override, found {total}"
