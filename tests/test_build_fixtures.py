"""Smoke tests: verify all build fixture files load and parse correctly."""

from tests.conftest import load_build_fixture


class TestBuildFixturesLoad:
    """Each fixture file loads without error and has the expected shape."""

    def test_plants_json_loads(self):
        plants = load_build_fixture("plants.json")
        assert isinstance(plants, list)
        assert len(plants) == 5

    def test_plants_have_required_fields(self):
        plants = load_build_fixture("plants.json")
        required = {"id", "common_name", "category", "active"}
        for plant in plants:
            assert required.issubset(plant.keys()), f"{plant['id']} missing fields"

    def test_active_inactive_split(self):
        plants = load_build_fixture("plants.json")
        active = [p for p in plants if p.get("active", True)]
        inactive = [p for p in plants if not p.get("active", True)]
        assert len(active) == 4
        assert len(inactive) == 1
        assert inactive[0]["id"] == "test-inactive"

    def test_retailers_json_loads(self):
        retailers = load_build_fixture("retailers.json")
        assert isinstance(retailers, list)
        assert len(retailers) == 2

    def test_retailers_have_required_fields(self):
        retailers = load_build_fixture("retailers.json")
        required = {"id", "name", "active", "affiliate"}
        for r in retailers:
            assert required.issubset(r.keys()), f"{r['id']} missing fields"

    def test_hydrangea_prices_load(self):
        entries = load_build_fixture("prices/test-hydrangea.jsonl")
        assert isinstance(entries, list)
        assert len(entries) == 4
        for entry in entries:
            assert "retailer_id" in entry
            assert "timestamp" in entry
            assert "sizes" in entry

    def test_maple_prices_load(self):
        entries = load_build_fixture("prices/test-maple.jsonl")
        assert isinstance(entries, list)
        assert len(entries) == 2

    def test_apple_prices_load(self):
        entries = load_build_fixture("prices/test-apple.jsonl")
        assert isinstance(entries, list)
        assert len(entries) == 2

    def test_stale_plant_prices_load(self):
        entries = load_build_fixture("prices/test-stale-plant.jsonl")
        assert isinstance(entries, list)
        assert len(entries) == 1
        # Timestamp should be old (>30 days from any reasonable run date)
        assert "2026-02-15" in entries[0]["timestamp"]

    def test_feedback_json_loads(self):
        feedback = load_build_fixture("feedback.json")
        assert isinstance(feedback, list)
        assert len(feedback) == 1
        assert feedback[0]["id"] == "test-fb-001"
        assert "response" in feedback[0]

    def test_guide_markdown_loads(self):
        text = load_build_fixture("01-test-guide.md")
        assert isinstance(text, str)
        assert text.startswith("# Best Test Plants to Buy Online")
        assert "/plants/test-hydrangea" in text

    def test_beautifulsoup4_importable(self):
        from bs4 import BeautifulSoup  # noqa: F401
