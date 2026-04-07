"""Page generation integration tests for build.py.

Runs build_site() once against synthetic fixtures, then verifies
the generated HTML files for correctness.
"""

import os
import shutil

import pytest
from bs4 import BeautifulSoup

from tests.conftest import BUILD_FIXTURES_DIR

# ---------------------------------------------------------------------------
# Session-scoped build fixture — one build, many assertions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def built_site(tmp_path_factory):
    """Run build_site() against synthetic fixture data and return the output dir.

    Monkeypatches build.py module-level path constants to redirect:
    - DATA_DIR → temp dir with plants.json, retailers.json, feedback.json
    - PRICES_DIR → temp dir with price JSONL files
    - SITE_DIR → temp output dir
    - ARTICLES_DIR → temp dir with guide markdown
    - TEMPLATE_DIR stays pointed at real templates (templates are code)
    """
    import build

    tmp = tmp_path_factory.mktemp("build_site")

    # Set up data directory
    data_dir = tmp / "data"
    data_dir.mkdir()
    prices_dir = data_dir / "prices"
    prices_dir.mkdir()

    # Copy fixture files into temp data dir
    shutil.copy(BUILD_FIXTURES_DIR / "plants.json", data_dir / "plants.json")
    shutil.copy(BUILD_FIXTURES_DIR / "retailers.json", data_dir / "retailers.json")
    shutil.copy(BUILD_FIXTURES_DIR / "feedback.json", data_dir / "feedback.json")

    # Copy price JSONL files
    fixture_prices = BUILD_FIXTURES_DIR / "prices"
    for f in fixture_prices.iterdir():
        shutil.copy(f, prices_dir / f.name)

    # Set up articles directory with guide markdown
    articles_dir = tmp / "articles"
    articles_dir.mkdir()
    shutil.copy(
        BUILD_FIXTURES_DIR / "01-test-guide.md",
        articles_dir / "01-test-guide.md",
    )

    # Output directory
    site_dir = tmp / "site"
    site_dir.mkdir()

    # Save originals
    orig_data = build.DATA_DIR
    orig_prices = build.PRICES_DIR
    orig_site = build.SITE_DIR
    orig_articles = build.ARTICLES_DIR

    # Monkeypatch module-level constants
    build.DATA_DIR = str(data_dir)
    build.PRICES_DIR = str(prices_dir)
    build.SITE_DIR = str(site_dir)
    build.ARTICLES_DIR = str(articles_dir)

    try:
        build.build_site()
    finally:
        # Restore originals so other tests aren't affected
        build.DATA_DIR = orig_data
        build.PRICES_DIR = orig_prices
        build.SITE_DIR = orig_site
        build.ARTICLES_DIR = orig_articles

    return site_dir


def _read_html(site_dir, *path_parts):
    """Read an HTML file from the built site and return a BeautifulSoup object."""
    path = os.path.join(str(site_dir), *path_parts)
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def _read_text(site_dir, *path_parts):
    """Read a text file from the built site."""
    path = os.path.join(str(site_dir), *path_parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Product page existence tests
# ---------------------------------------------------------------------------


class TestProductPageExistence:
    """Verify which product pages exist and which do not."""

    def test_active_plants_get_pages(self, built_site):
        """Each active plant with prices gets a product page."""
        for plant_id in ["test-hydrangea", "test-maple", "test-apple"]:
            path = built_site / "plants" / f"{plant_id}.html"
            assert path.exists(), f"Missing product page for {plant_id}"

    def test_inactive_plant_has_no_page(self, built_site):
        """Inactive plant must not get a product page."""
        path = built_site / "plants" / "test-inactive.html"
        assert not path.exists(), "Inactive plant should not have a product page"

    def test_stale_plant_gets_page(self, built_site):
        """Stale plant (>30d old prices) still gets a product page."""
        path = built_site / "plants" / "test-stale-plant.html"
        assert path.exists(), "Stale plant should still get a product page"

    def test_correct_number_of_product_pages(self, built_site):
        """Exactly 4 active plants → 4 product pages."""
        product_dir = built_site / "plants"
        pages = list(product_dir.glob("*.html"))
        assert len(pages) == 4, f"Expected 4 product pages, got {len(pages)}: {[p.name for p in pages]}"


# ---------------------------------------------------------------------------
# Product page content tests
# ---------------------------------------------------------------------------


class TestProductPageContent:
    """Verify product page HTML contains correct data."""

    def test_hydrangea_has_title(self, built_site):
        """Product page shows the plant's common name."""
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        title = soup.find("title")
        assert title and "Test Hydrangea" in title.string

    def test_hydrangea_has_retailer_names(self, built_site):
        """Product page mentions both retailers."""
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        text = soup.get_text()
        assert "Test Nursery A" in text
        assert "Test Nursery B" in text

    def test_hydrangea_has_prices_in_page(self, built_site):
        """Product page contains expected prices from fixture data."""
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        text = soup.get_text()
        # Nursery A prices
        assert "15.99" in text, "Nursery A quart price missing"
        assert "29.99" in text, "Nursery A 1gal price missing"
        assert "54.99" in text, "Nursery A 3gal price missing"
        # Nursery B prices
        assert "39.99" in text, "Nursery B 1gal price missing"
        assert "69.99" in text, "Nursery B 3gal price missing"

    def test_hydrangea_was_price_shown(self, built_site):
        """Nursery B 1gal has was_price=49.99 — should appear on page."""
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        text = soup.get_text()
        assert "49.99" in text, "was_price should appear on product page"

    def test_stale_plant_page_has_no_prices(self, built_site):
        """Stale plant page exists but should have no price rows (>30d old)."""
        soup = _read_html(built_site, "plants", "test-stale-plant.html")
        text = soup.get_text()
        # The stale price is $24.99 from 2026-02-15 — should be excluded
        assert "24.99" not in text, "Stale price should not appear on product page"

    def test_hydrangea_botanical_name(self, built_site):
        """Product page shows botanical name."""
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        text = soup.get_text()
        assert "Hydrangea testensis" in text


# ---------------------------------------------------------------------------
# Category page tests
# ---------------------------------------------------------------------------


class TestCategoryPages:
    """Verify category pages list the correct plants."""

    def test_hydrangeas_category_exists(self, built_site):
        """Hydrangeas category page is generated."""
        path = built_site / "category" / "hydrangeas.html"
        assert path.exists()

    def test_hydrangeas_contains_active_plants(self, built_site):
        """Hydrangeas category lists test-hydrangea and test-stale-plant."""
        soup = _read_html(built_site, "category", "hydrangeas.html")
        text = soup.get_text()
        assert "Test Hydrangea" in text
        assert "Test Stale Plant" in text

    def test_hydrangeas_excludes_inactive(self, built_site):
        """Hydrangeas category must NOT list test-inactive."""
        soup = _read_html(built_site, "category", "hydrangeas.html")
        text = soup.get_text()
        assert "Test Inactive Plant" not in text

    def test_japanese_maples_category(self, built_site):
        """Japanese maples category lists test-maple."""
        soup = _read_html(built_site, "category", "japanese-maples.html")
        text = soup.get_text()
        assert "Test Japanese Maple" in text

    def test_fruit_trees_category(self, built_site):
        """Fruit trees category lists test-apple."""
        soup = _read_html(built_site, "category", "fruit-trees.html")
        text = soup.get_text()
        assert "Test Apple Tree" in text

    def test_correct_number_of_categories(self, built_site):
        """3 categories from active plants: hydrangeas, japanese-maples, fruit-trees."""
        cat_dir = built_site / "category"
        pages = list(cat_dir.glob("*.html"))
        assert len(pages) == 3, f"Expected 3 category pages, got {len(pages)}: {[p.name for p in pages]}"


# ---------------------------------------------------------------------------
# Sitemap tests
# ---------------------------------------------------------------------------


class TestSitemap:
    """Verify sitemap.xml lists correct URLs."""

    def test_sitemap_exists(self, built_site):
        path = built_site / "sitemap.xml"
        assert path.exists()

    def test_sitemap_contains_active_plants(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        for plant_id in ["test-hydrangea", "test-maple", "test-apple", "test-stale-plant"]:
            assert f"/plants/{plant_id}.html" in text, f"{plant_id} missing from sitemap"

    def test_sitemap_excludes_inactive(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        assert "test-inactive" not in text, "Inactive plant should not be in sitemap"

    def test_sitemap_contains_categories(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        for cat in ["hydrangeas", "japanese-maples", "fruit-trees"]:
            assert f"/category/{cat}.html" in text, f"Category {cat} missing from sitemap"

    def test_sitemap_contains_static_pages(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        for page in ["/", "/my-list.html", "/heat-map.html", "/improve.html"]:
            assert page in text, f"Static page {page} missing from sitemap"

    def test_sitemap_contains_guide(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        assert "/guides/test-guide.html" in text, "Guide page missing from sitemap"


# ---------------------------------------------------------------------------
# Homepage tests
# ---------------------------------------------------------------------------


class TestHomepage:
    """Verify homepage builds and has expected content."""

    def test_homepage_exists(self, built_site):
        path = built_site / "index.html"
        assert path.exists()

    def test_homepage_has_categories(self, built_site):
        """Homepage shows category names."""
        soup = _read_html(built_site, "index.html")
        text = soup.get_text()
        assert "Hydrangeas" in text

    def test_homepage_has_plant_count(self, built_site):
        """Homepage references the number of plants tracked."""
        soup = _read_html(built_site, "index.html")
        text = soup.get_text()
        # 4 active plants
        assert "4" in text


# ---------------------------------------------------------------------------
# Heat map tests
# ---------------------------------------------------------------------------


class TestHeatMap:
    """Verify heat map page exists and uses plant data."""

    def test_heatmap_exists(self, built_site):
        path = built_site / "heat-map.html"
        assert path.exists()

    def test_heatmap_contains_category_data(self, built_site):
        """Heat map should reference at least one category from our plants."""
        soup = _read_html(built_site, "heat-map.html")
        text = soup.get_text()
        # At least one of our categories should appear
        has_category = any(
            cat in text for cat in ["Hydrangeas", "Japanese Maples", "Fruit Trees"]
        )
        assert has_category, "Heat map should contain category data from plants"


# ---------------------------------------------------------------------------
# Guide page tests
# ---------------------------------------------------------------------------


class TestGuidePage:
    """Verify guide page is generated from markdown fixture."""

    def test_guide_page_exists(self, built_site):
        path = built_site / "guides" / "test-guide.html"
        assert path.exists()

    def test_guide_has_title(self, built_site):
        """Guide page title comes from the markdown H1."""
        soup = _read_html(built_site, "guides", "test-guide.html")
        title = soup.find("title")
        assert title and "Best Test Plants to Buy Online" in title.string

    def test_guide_index_exists(self, built_site):
        """Guides index page is generated."""
        path = built_site / "guides" / "index.html"
        assert path.exists()

    def test_guide_index_links_to_guide(self, built_site):
        """Guides index links to our test guide."""
        soup = _read_html(built_site, "guides", "index.html")
        links = [a.get("href", "") for a in soup.find_all("a")]
        assert any("test-guide" in href for href in links)


# ---------------------------------------------------------------------------
# Improve page tests
# ---------------------------------------------------------------------------


class TestImprovePage:
    """Verify improve page uses feedback fixture data."""

    def test_improve_page_exists(self, built_site):
        path = built_site / "improve.html"
        assert path.exists()

    def test_improve_has_feedback_title(self, built_site):
        """Improve page shows the feedback item title."""
        soup = _read_html(built_site, "improve.html")
        text = soup.get_text()
        assert "Add test plant variety" in text


# ---------------------------------------------------------------------------
# Inactive plant global exclusion
# ---------------------------------------------------------------------------


class TestInactiveExclusion:
    """Verify inactive plant appears on zero generated pages."""

    def test_inactive_absent_from_all_product_pages(self, built_site):
        """Inactive plant name must not appear on any product page."""
        product_dir = built_site / "plants"
        for page in product_dir.glob("*.html"):
            soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
            assert "Test Inactive Plant" not in soup.get_text(), (
                f"Inactive plant found on {page.name}"
            )

    def test_inactive_absent_from_all_category_pages(self, built_site):
        """Inactive plant must not appear on any category page."""
        cat_dir = built_site / "category"
        for page in cat_dir.glob("*.html"):
            soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
            assert "Test Inactive Plant" not in soup.get_text(), (
                f"Inactive plant found on {page.name}"
            )

    def test_inactive_absent_from_sitemap(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        assert "test-inactive" not in text

    def test_inactive_absent_from_homepage(self, built_site):
        soup = _read_html(built_site, "index.html")
        assert "Test Inactive Plant" not in soup.get_text()


# ---------------------------------------------------------------------------
# Robots.txt and wishlist
# ---------------------------------------------------------------------------


class TestAboutPage:
    """Verify about page is generated with expected content."""

    def test_about_page_exists(self, built_site):
        path = built_site / "about.html"
        assert path.exists()

    def test_about_has_title(self, built_site):
        soup = _read_html(built_site, "about.html")
        title = soup.find("title")
        assert title and "About" in title.string

    def test_about_has_canonical(self, built_site):
        soup = _read_html(built_site, "about.html")
        link = soup.find("link", rel="canonical")
        assert link and link["href"].endswith("/about.html")

    def test_about_has_content_sections(self, built_site):
        """About page has the key E-E-A-T content sections."""
        soup = _read_html(built_site, "about.html")
        text = soup.get_text()
        for heading in [
            "Who Runs PlantPriceTracker",
            "How We Track Plant Prices",
            "Editorial Standards",
            "Frequently Asked Questions",
            "Get in Touch",
        ]:
            assert heading in text, f"Missing section: {heading}"

    def test_about_has_faq_schema(self, built_site):
        """About page includes FAQPage structured data."""
        soup = _read_html(built_site, "about.html")
        scripts = soup.find_all("script", type="application/ld+json")
        faq_found = any("FAQPage" in s.string for s in scripts if s.string)
        assert faq_found, "FAQPage schema missing from about page"

    def test_about_has_aboutpage_schema(self, built_site):
        """About page includes AboutPage structured data."""
        soup = _read_html(built_site, "about.html")
        scripts = soup.find_all("script", type="application/ld+json")
        about_found = any("AboutPage" in s.string for s in scripts if s.string)
        assert about_found, "AboutPage schema missing from about page"

    def test_about_in_sitemap(self, built_site):
        text = _read_text(built_site, "sitemap.xml")
        assert "/about.html" in text, "About page missing from sitemap"

    def test_about_in_nav(self, built_site):
        """About link appears in the site nav on the homepage."""
        soup = _read_html(built_site, "index.html")
        nav = soup.find("nav")
        links = [a.get("href", "") for a in nav.find_all("a")] if nav else []
        assert "/about.html" in links, "About link missing from nav"

    def test_about_in_footer(self, built_site):
        """About link appears in the footer."""
        soup = _read_html(built_site, "index.html")
        footer = soup.find("footer")
        links = [a.get("href", "") for a in footer.find_all("a")] if footer else []
        assert "/about.html" in links, "About link missing from footer"


class TestMiscPages:
    """Verify robots.txt and wishlist page are generated."""

    def test_robots_txt_exists(self, built_site):
        path = built_site / "robots.txt"
        assert path.exists()

    def test_robots_txt_has_sitemap(self, built_site):
        text = _read_text(built_site, "robots.txt")
        assert "sitemap.xml" in text.lower()

    def test_wishlist_page_exists(self, built_site):
        path = built_site / "my-list.html"
        assert path.exists()
