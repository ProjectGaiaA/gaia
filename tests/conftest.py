"""Shared test fixtures for PlantPriceTracker scraper tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BUILD_FIXTURES_DIR = FIXTURES_DIR / "build"


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


def load_fixture(retailer: str, filename: str) -> str | dict:
    """Load a fixture file by retailer and filename.

    Returns parsed JSON for .json files, raw string for .html files.
    """
    path = FIXTURES_DIR / retailer / filename
    text = path.read_text(encoding="utf-8")
    if filename.endswith(".json"):
        return json.loads(text)
    return text


def load_build_fixture(filename: str) -> str | dict | list:
    """Load a build fixture file by filename.

    Returns parsed JSON for .json files, list of parsed dicts for .jsonl files,
    raw string for .md and other files.
    """
    path = BUILD_FIXTURES_DIR / filename
    text = path.read_text(encoding="utf-8")
    if filename.endswith(".json"):
        return json.loads(text)
    if filename.endswith(".jsonl"):
        return [json.loads(line) for line in text.strip().splitlines() if line.strip()]
    return text


@pytest.fixture
def build_fixtures_dir():
    """Return the path to the build test fixtures directory."""
    return BUILD_FIXTURES_DIR


@pytest.fixture
def no_sleep():
    """Patch time.sleep to no-op so tests don't actually wait."""
    with patch("time.sleep"):
        yield


@pytest.fixture(autouse=True)
def stub_robots():
    """Stub is_allowed_by_robots to always return True in scraper modules.

    RobotFileParser uses urllib (not requests), so the `responses`
    library can't mock it. This patches the function where it's imported
    in scraper modules, preventing any real network call to fetch robots.txt.
    Tests in test_polite.py test the real function using _robots_cache directly.
    """
    with (
        patch("scrapers.shopify.is_allowed_by_robots", return_value=True),
        patch("scrapers.starkbros.is_allowed_by_robots", return_value=True),
    ):
        yield


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for tests that write files."""
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    return tmp_path
