"""Page generation integration tests for build.py.

Runs build_site() once against synthetic fixtures, then verifies
the generated HTML files for correctness.
"""

import os
import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from tests.conftest import BUILD_FIXTURES_DIR

# The real site/assets tree. Templates reference these files by URL, so a page
# can advertise an image the repo does not ship; tests resolve the URL back to
# a file to prove it exists.
SITE_ASSETS_DIR = Path(__file__).resolve().parents[1] / "site" / "assets"

# ---------------------------------------------------------------------------
# Session-scoped build fixture — one build, many assertions
# ---------------------------------------------------------------------------


def _build_fixture_site(tmp, affiliate_programs_active=None):
    """Run build_site() against synthetic fixture data and return the output dir.

    Monkeypatches build.py module-level path constants to redirect:
    - DATA_DIR → temp dir with plants.json, retailers.json, affiliate_overrides.json
    - PRICES_DIR → temp dir with price JSONL files
    - SITE_DIR → temp output dir
    - ARTICLES_DIR → temp dir with guide markdown
    - TEMPLATE_DIR stays pointed at real templates (templates are code)

    affiliate_programs_active overrides build.AFFILIATE_PROGRAMS_ACTIVE for the
    duration of the build; None uses whatever the repo currently ships.
    """
    import build

    # Set up data directory
    data_dir = tmp / "data"
    data_dir.mkdir()
    prices_dir = data_dir / "prices"
    prices_dir.mkdir()

    # Copy fixture files into temp data dir
    shutil.copy(BUILD_FIXTURES_DIR / "plants.json", data_dir / "plants.json")
    shutil.copy(BUILD_FIXTURES_DIR / "retailers.json", data_dir / "retailers.json")
    # Exactly one plant in this fixture carries a real affiliate link and the
    # others carry none. That asymmetry is what makes "only the affiliate link
    # is marked" distinguishable from "every retailer is marked" — without it
    # both assertions would pass on the same output.
    shutil.copy(
        BUILD_FIXTURES_DIR / "affiliate_overrides.json",
        data_dir / "affiliate_overrides.json",
    )

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
    orig_affiliate = build.AFFILIATE_PROGRAMS_ACTIVE

    # Monkeypatch module-level constants
    build.DATA_DIR = str(data_dir)
    build.PRICES_DIR = str(prices_dir)
    build.SITE_DIR = str(site_dir)
    build.ARTICLES_DIR = str(articles_dir)
    if affiliate_programs_active is not None:
        build.AFFILIATE_PROGRAMS_ACTIVE = affiliate_programs_active

    try:
        # Fixture JSONL timestamps are fixed in early April 2026. Freeze the
        # clock to match (same pattern as test_build_data.py) so the 30-day
        # staleness cutoff in build_price_table() sees fresh fixtures as
        # fresh and the 2026-02-15 stale-plant fixture as stale — forever,
        # instead of only for the 30 days after the fixtures were authored.
        with patch("build.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            build.build_site()
    finally:
        # Restore originals so other tests aren't affected
        build.DATA_DIR = orig_data
        build.PRICES_DIR = orig_prices
        build.SITE_DIR = orig_site
        build.ARTICLES_DIR = orig_articles
        build.AFFILIATE_PROGRAMS_ACTIVE = orig_affiliate

    return site_dir


@pytest.fixture(scope="session")
def built_site(tmp_path_factory):
    """Site built exactly as the repo currently ships it."""
    return _build_fixture_site(tmp_path_factory.mktemp("build_site"))


@pytest.fixture(scope="session")
def built_site_affiliates_on(tmp_path_factory):
    """Same fixtures, built with AFFILIATE_PROGRAMS_ACTIVE forced True.

    Proves the flag actually flips every claim, so approval day really is a
    one-line change and the "programs on" wording never rots unexercised.
    """
    return _build_fixture_site(
        tmp_path_factory.mktemp("build_site_aff_on"), affiliate_programs_active=True
    )


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
        for plant_id in ["test-hydrangea", "test-maple", "test-apple"]:
            assert f"/plants/{plant_id}.html" in text, f"{plant_id} missing from sitemap"

    def test_sitemap_excludes_zero_offer_plants(self, built_site):
        """A plant whose only prices aged out has zero offers: its page is
        noindexed, so the sitemap must not point Google at it."""
        text = _read_text(built_site, "sitemap.xml")
        assert "test-stale-plant" not in text

    def test_zero_offer_page_is_noindexed(self, built_site):
        soup = _read_html(built_site, "plants", "test-stale-plant.html")
        robots = soup.find("meta", attrs={"name": "robots"})
        assert robots is not None and "noindex" in robots.get("content", "")

    def test_normal_page_is_not_noindexed(self, built_site):
        soup = _read_html(built_site, "plants", "test-hydrangea.html")
        assert soup.find("meta", attrs={"name": "robots"}) is None

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

    def test_guide_index_has_google_verification(self, built_site):
        """Guides index must include google-site-verification meta tag from base.html."""
        soup = _read_html(built_site, "guides", "index.html")
        meta = soup.find("meta", attrs={"name": "google-site-verification"})
        assert meta, "google-site-verification meta tag missing from guides index"

    def test_guide_index_has_canonical(self, built_site):
        """Guides index must have a canonical link tag."""
        soup = _read_html(built_site, "guides", "index.html")
        link = soup.find("link", rel="canonical")
        assert link and link["href"].endswith("/guides/index.html")

    def test_guide_index_has_og_url(self, built_site):
        """Guides index must have og:url meta tag."""
        soup = _read_html(built_site, "guides", "index.html")
        meta = soup.find("meta", attrs={"property": "og:url"})
        assert meta and meta["content"].endswith("/guides/index.html")

    def test_guide_index_has_about_in_nav(self, built_site):
        """Guides index nav must include About link (from base.html)."""
        soup = _read_html(built_site, "guides", "index.html")
        nav = soup.find("nav")
        links = [a.get("href", "") for a in nav.find_all("a")] if nav else []
        assert "/about.html" in links, "About link missing from guides index nav"

    def test_guide_index_has_about_in_footer(self, built_site):
        """Guides index footer must include About link (from base.html)."""
        soup = _read_html(built_site, "guides", "index.html")
        footer = soup.find("footer")
        links = [a.get("href", "") for a in footer.find_all("a")] if footer else []
        assert "/about.html" in links, "About link missing from guides index footer"

    def test_guide_index_has_guide_title(self, built_site):
        """Guides index must show the test guide's title."""
        soup = _read_html(built_site, "guides", "index.html")
        text = soup.get_text()
        assert "Best Test Plants to Buy Online" in text


# ---------------------------------------------------------------------------
# Improve page tests
# ---------------------------------------------------------------------------


class TestImprovePage:
    """The improve page must never imply community activity that never happened.

    It used to render data/feedback.json: eight suggestions with upvote counts,
    submission dates and published replies, none of which any visitor had sent.
    The votes were localStorage-only, so they never left the browser either.
    """

    def test_improve_page_exists(self, built_site):
        path = built_site / "improve.html"
        assert path.exists()

    def test_improve_has_no_vote_or_submission_ui(self, built_site):
        html = _read_text(built_site, "improve.html").lower()
        for token in ("upvote", "submissions", "awaiting response", "formspree",
                      "feedback-card", "most upvoted"):
            assert token not in html, f"improve page still shows {token!r}"

    def test_improve_has_a_working_contact_route(self, built_site):
        soup = _read_html(built_site, "improve.html")
        mailtos = [a["href"] for a in soup.select("a[href^='mailto:']")]
        assert any("ProjectGaiaA@proton.me" in m for m in mailtos), mailtos

    def test_improve_has_no_form(self, built_site):
        """A form on a static site has nowhere to POST. Better none at all."""
        soup = _read_html(built_site, "improve.html")
        assert soup.find("form") is None


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


class TestPriceCrossConsistency:
    """Every price shown anywhere on a page must agree with that page's schema.

    Phase 1 fixed the headline price in one of four places that decide which
    prices count. The other three kept publishing the old number: sibling
    "Similar Plants" widgets, the price-history chart, and offer_count. This
    class asserts the invariant directly on built HTML so the four can never
    silently diverge again.
    """

    @staticmethod
    def _schema_range(soup):
        import json as _json
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(tag.string or "{}")
            except ValueError:
                continue
            offers = data.get("offers") or {}
            if offers.get("lowPrice") is not None:
                return float(offers["lowPrice"]), float(offers["highPrice"]), offers
        return None, None, None

    def _plant_pages(self, site_dir):
        import glob as _glob
        import os as _os
        return sorted(_glob.glob(_os.path.join(str(site_dir), "plants", "*.html")))

    def test_chart_prices_within_schema_range(self, built_site):
        """The price-history chart must never plot a current price below the
        page's own advertised lowPrice."""
        import json as _json
        import re as _re
        violations = []
        for path in self._plant_pages(built_site):
            html = open(path, encoding="utf-8").read()
            soup = BeautifulSoup(html, "html.parser")
            low, high, _ = self._schema_range(soup)
            if low is None:
                continue
            m = _re.search(r"priceHistoryData\s*=\s*(\{.*?\});", html, _re.S)
            if not m:
                continue
            data = _json.loads(m.group(1))
            for series in data.get("datasets", []):
                pts = [p for p in series.get("data", []) if p is not None]
                if pts and min(pts) < low - 0.01:
                    violations.append(
                        f"{os.path.basename(path)}: chart {series.get('label')} "
                        f"min ${min(pts)} < lowPrice ${low}"
                    )
        assert not violations, "Chart contradicts schema:\n" + "\n".join(violations)

    def test_offer_count_matches_rendered_prices(self, built_site):
        """schema offerCount must equal the retailers actually showing a price."""
        violations = []
        for path in self._plant_pages(built_site):
            soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
            low, _, offers = self._schema_range(soup)
            if offers is None:
                continue
            count = offers.get("offerCount")
            priced_rows = 0
            for row in soup.select("tbody tr"):
                if row.select("a.price-link") or row.select(".price-cell a"):
                    priced_rows += 1
            if count is not None and priced_rows and int(count) > priced_rows:
                violations.append(
                    f"{os.path.basename(path)}: offerCount={count} but "
                    f"{priced_rows} rows show a price"
                )
        assert not violations, "offerCount overstates:\n" + "\n".join(violations)

    def test_no_page_claims_offers_without_a_price(self, built_site):
        """A page with no displayable price must be noindexed, not indexed
        as an N-Nursery commercial page."""
        violations = []
        for path in self._plant_pages(built_site):
            soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
            low, _, _ = self._schema_range(soup)
            has_price_link = bool(soup.select("a.price-link"))
            robots = soup.find("meta", attrs={"name": "robots"})
            noindexed = robots is not None and "noindex" in robots.get("content", "")
            if low is None and not has_price_link and not noindexed:
                violations.append(os.path.basename(path))
        assert not violations, (
            "Indexed pages with no price at all: " + ", ".join(violations)
        )


# ---------------------------------------------------------------------------
# Affiliate-claim consistency
# ---------------------------------------------------------------------------


def _fixture_retailers():
    """The retailers.json the built_site fixtures were generated from.

    build.DATA_DIR is restored once the build finishes, so tests must read the
    fixture directly rather than the live repo data.
    """
    import json

    with open(BUILD_FIXTURES_DIR / "retailers.json", encoding="utf-8") as f:
        return json.load(f)


def _all_html(site_dir):
    for root, _dirs, files in os.walk(str(site_dir)):
        for f in files:
            if f.endswith(".html"):
                yield os.path.join(root, f)


class TestAffiliateClaimConsistency:
    """Every money claim on the site must agree with AFFILIATE_PROGRAMS_ACTIVE.

    The site previously named five nurseries and three affiliate networks it
    was "currently" partnered with, and told every visitor in the footer of
    all 134 pages that it earned commissions — while containing zero affiliate
    links. One flag now drives the footer, the notice above each price table,
    the disclosure page and the About page copy; these tests fail if any of
    them drifts from it.
    """

    def test_no_commission_claim_while_programs_are_off(self, built_site):
        import build

        if build.AFFILIATE_PROGRAMS_ACTIVE:
            pytest.skip("programs are on; the commission claim is true")
        offenders = []
        for path in _all_html(built_site):
            text = BeautifulSoup(
                open(path, encoding="utf-8").read(), "html.parser"
            ).get_text(" ")
            for claim in (
                "We earn commissions",
                "We earn a commission on purchases",
                "Some links below are affiliate links",
                "earns affiliate commissions",
            ):
                if claim in text:
                    offenders.append(f"{os.path.basename(path)}: {claim!r}")
        assert not offenders, "False commission claims:\n" + "\n".join(offenders)

    def test_no_sponsored_rel_while_programs_are_off(self, built_site):
        """rel="sponsored" asserts paid placement. Nothing is paid yet."""
        import build

        if build.AFFILIATE_PROGRAMS_ACTIVE:
            pytest.skip("programs are on; sponsored links are legitimate")
        offenders = [
            os.path.basename(p)
            for p in _all_html(built_site)
            if "sponsored" in open(p, encoding="utf-8").read()
        ]
        assert not offenders, "rel=sponsored on: " + ", ".join(offenders[:10])

    def test_outbound_price_links_always_nofollow(self, built_site):
        """noopener + nofollow apply in both flag states."""
        bad = []
        for path in _all_html(built_site):
            soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
            for a in soup.select("a.price-link, a.bp-price-link"):
                rel = " ".join(a.get("rel", []))
                if "noopener" not in rel or "nofollow" not in rel:
                    bad.append(f"{os.path.basename(path)}: rel={rel!r}")
        assert not bad, "Outbound price links missing rel tokens:\n" + "\n".join(bad[:10])

    def test_flag_on_restores_the_affiliate_wording(self, built_site_affiliates_on):
        """Flipping the one flag must flip every claim, not just the footer."""
        footer = _read_html(built_site_affiliates_on, "index.html").select_one(
            ".footer-disclosure"
        )
        assert "Some links on this site are affiliate links" in footer.get_text(" ")

        disclosure = _read_html(
            built_site_affiliates_on, "disclosure.html"
        ).get_text(" ")
        assert "Some of the links on this site are affiliate links." in disclosure
        assert "not enrolled in any affiliate" not in disclosure

        about = _read_html(built_site_affiliates_on, "about.html").get_text(" ")
        assert "the retailer may pay us a commission" in about

    def test_no_page_claims_a_commission_has_been_earned(self, built_site):
        """The flag means "an affiliate link exists", not "money has arrived".

        Three program applications are pending and none has paid out, so a
        present-tense earnings claim is false in either flag state.
        """
        offenders = []
        for path in _all_html(built_site):
            text = BeautifulSoup(
                open(path, encoding="utf-8").read(), "html.parser"
            ).get_text(" ")
            for claim in (
                "We earn a commission on purchases",
                "earns affiliate commissions",
                "We earn affiliate commissions",
                "That revenue pays for",
            ):
                if claim in text:
                    offenders.append(f"{os.path.basename(path)}: {claim!r}")
        assert not offenders, "Present-tense earnings claims: " + "; ".join(offenders)

    def test_asterisk_marks_only_links_that_are_actually_affiliate_links(
        self, built_site_affiliates_on
    ):
        """The asterisk used to be driven by retailers.json "affiliate" blocks,
        which are research notes about programs that COULD be joined. It marked
        seven retailers as paying the site when none of them do. It is now
        driven by data/affiliate_overrides.json, so it appears only where a real
        affiliate link exists."""
        marked = [
            os.path.basename(p)
            for p in _all_html(built_site_affiliates_on)
            if "affiliate-marked" in open(p, encoding="utf-8").read()
        ]
        assert marked == ["test-hydrangea.html"], marked

    def test_sponsored_rel_appears_only_on_the_real_affiliate_link(
        self, built_site_affiliates_on
    ):
        """rel="sponsored" asserts a paid relationship for that specific link."""
        for path in _all_html(built_site_affiliates_on):
            soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
            for a in soup.select("a[rel~=sponsored]"):
                assert a["href"].startswith("https://example.test/affiliate/"), (
                    f"{os.path.basename(path)} marks {a['href']} as sponsored"
                )

    def test_asterisk_footnote_only_where_an_asterisk_exists(
        self, built_site_affiliates_on
    ):
        """A footnote explaining an asterisk that is not on the page is noise
        at best and a claim about a link that does not exist at worst."""
        for path in _all_html(built_site_affiliates_on):
            html = open(path, encoding="utf-8").read()
            if "table-footnote" in html:
                assert "affiliate-marked" in html, os.path.basename(path)

    def test_sponsored_returns_when_flag_is_on(self, built_site_affiliates_on):
        found = any(
            "sponsored" in open(p, encoding="utf-8").read()
            for p in _all_html(built_site_affiliates_on)
        )
        assert found, "flag on but no rel=sponsored anywhere"

    def test_disclosure_lists_exactly_the_active_retailers(self, built_site):
        """The tracked-nursery list is rendered from retailers.json, not prose,
        so it cannot claim a nursery the site does not actually check."""
        expected = [r["name"] for r in _fixture_retailers() if r.get("active")]

        soup = _read_html(built_site, "disclosure.html")
        listed = [li.get_text(strip=True) for li in soup.select("ul.tracked-retailers li")]
        assert listed == expected

    def test_disclosure_names_no_affiliate_network(self, built_site):
        """Naming networks in prose is what made this page false. Keep it out."""
        text = _read_html(built_site, "disclosure.html").get_text(" ").lower()
        for network in ("shareasale", "sovrn", "impact radius", "awin", "flexoffers"):
            assert network not in text, f"disclosure page names {network}"

    def test_no_page_names_an_inactive_retailer_as_tracked(self, built_site):
        """About/disclosure listed two nurseries with zero price records ever."""
        inactive = [r["name"] for r in _fixture_retailers() if not r.get("active")]
        assert inactive, "fixture must contain an inactive retailer to test this"

        offenders = []
        for page in ("about.html", "disclosure.html", "index.html"):
            text = _read_html(built_site, page).get_text(" ")
            for name in inactive:
                if name in text:
                    offenders.append(f"{page}: {name}")
        assert not offenders, "Inactive retailers presented as tracked: " + ", ".join(
            offenders
        )

    def test_nursery_counts_are_not_hardcoded(self, built_site):
        """"12+ nurseries" survived on 8 lines of about.html including its
        FAQ schema. Counts must come from the data."""
        count = sum(1 for r in _fixture_retailers() if r.get("active"))

        for page in ("about.html", "disclosure.html", "index.html"):
            text = _read_html(built_site, page).get_text(" ")
            for stale in ("12+ online nurseries", "10+ online nurseries",
                          "12+ nurseries", "10+ nurseries"):
                assert stale not in text, f"{page} hardcodes {stale!r}"
            if page == "about.html":
                assert f"{count} online nurseries" in text


# ---------------------------------------------------------------------------
# Reachability, link previews, and analytics honesty
# ---------------------------------------------------------------------------


def _content_pages(site_dir):
    """Every generated page, minus the search-console verification stub."""
    for p in _all_html(site_dir):
        if os.path.basename(p).startswith("google"):
            continue
        yield p


class TestContactRoute:
    """A price-comparison site has to be reachable, at a mailbox that works."""

    def test_contact_page_exists(self, built_site):
        assert (built_site / "contact.html").exists()

    def test_contact_page_is_in_the_sitemap(self, built_site):
        assert "/contact.html" in _read_text(built_site, "sitemap.xml")

    def test_contact_page_is_linked_from_every_page(self, built_site):
        missing = [
            os.path.basename(p)
            for p in _content_pages(built_site)
            if '"/contact.html"' not in open(p, encoding="utf-8").read()
        ]
        assert not missing, f"pages with no contact link: {missing[:5]}"

    def test_contact_page_offers_a_real_address(self, built_site):
        soup = _read_html(built_site, "contact.html")
        mailtos = [a["href"] for a in soup.select("a[href^='mailto:']")]
        assert any("ProjectGaiaA@proton.me" in m for m in mailtos), mailtos

    def test_no_page_prints_an_address_at_a_domain_with_no_mx_record(
        self, built_site
    ):
        """plantpricetracker.com resolves for web but publishes no MX record,
        so every address at it bounces. privacy@plantpricetracker.com was
        printed on the privacy policy as the way to reach us."""
        offenders = [
            os.path.basename(p)
            for p in _all_html(built_site)
            if "@plantpricetracker.com" in open(p, encoding="utf-8").read()
        ]
        assert not offenders, f"unreachable addresses on: {offenders}"

    def test_no_page_collects_an_email_address(self, built_site):
        """A static site cannot receive a form. Two of them used to take an
        email address, one storing it in localStorage while telling the visitor
        they were signed up for alerts that were never sent."""
        offenders = []
        for p in _content_pages(built_site):
            soup = BeautifulSoup(open(p, encoding="utf-8").read(), "html.parser")
            if soup.select("input[type=email]"):
                offenders.append(os.path.basename(p))
        assert not offenders, f"email capture on: {offenders}"


class TestOpenGraphTags:
    """Every page must produce a truthful link preview."""

    REQUIRED = [
        ("property", "og:title"),
        ("property", "og:description"),
        ("property", "og:url"),
        ("property", "og:type"),
        ("property", "og:site_name"),
        ("property", "og:image"),
        ("name", "twitter:card"),
    ]

    def test_every_page_has_the_full_tag_set(self, built_site):
        missing = {}
        for p in _content_pages(built_site):
            soup = BeautifulSoup(open(p, encoding="utf-8").read(), "html.parser")
            absent = [
                tag
                for attr, tag in self.REQUIRED
                if soup.find("meta", attrs={attr: tag}) is None
            ]
            if absent:
                missing[os.path.basename(p)] = absent
        assert not missing, f"pages missing OG tags: {list(missing.items())[:3]}"

    def test_og_title_and_description_match_the_page(self, built_site):
        """The preview must not be able to say something the page does not."""
        for name in ("index.html", "about.html", "contact.html", "disclosure.html"):
            soup = _read_html(built_site, name)
            og_title = soup.find("meta", attrs={"property": "og:title"})["content"]
            og_desc = soup.find("meta", attrs={"property": "og:description"})["content"]
            assert og_title == soup.title.string, name
            assert (
                og_desc == soup.find("meta", attrs={"name": "description"})["content"]
            ), name

    def test_og_image_is_a_file_that_exists(self, built_site):
        """A preview card pointing at a 404 is worse than no card. The site
        ships exactly one image."""
        soup = _read_html(built_site, "index.html")
        url = soup.find("meta", attrs={"property": "og:image"})["content"]
        assert url.startswith("https://")
        rel = url.split("/assets/", 1)[1]
        assert (SITE_ASSETS_DIR / rel).exists(), f"og:image 404s: {url}"

    def test_og_url_matches_canonical(self, built_site):
        for p in _content_pages(built_site):
            soup = BeautifulSoup(open(p, encoding="utf-8").read(), "html.parser")
            canonical = soup.find("link", attrs={"rel": ["canonical"]})
            og_url = soup.find("meta", attrs={"property": "og:url"})
            if canonical is not None:
                assert og_url["content"] == canonical["href"], os.path.basename(p)


class TestPrivacyPageMatchesReality:
    """The policy must describe the analytics the site actually loads."""

    def test_names_the_analytics_that_is_deployed(self, built_site):
        text = _read_html(built_site, "privacy.html").get_text(" ")
        assert "Vercel Web Analytics" in text
        assert "sets no cookies" in text

    def test_does_not_name_analytics_that_is_not_deployed(self, built_site):
        """The policy claimed Plausible or Fathom while base.html loaded the
        Vercel beacon and neither of the other two was ever installed."""
        text = _read_html(built_site, "privacy.html").get_text(" ").lower()
        for tool in ("plausible", "fathom", "matomo", "hotjar"):
            assert tool not in text, f"privacy policy names {tool}"

    def test_the_named_analytics_is_the_one_in_the_page_source(self, built_site):
        """Ties the claim to the markup: if the beacon changes, this fails."""
        html = _read_text(built_site, "privacy.html")
        assert "/_vercel/insights/script.js" in html

    def test_does_not_promise_a_mailing_list_that_does_not_exist(self, built_site):
        """The policy described a weekly deal newsletter, a price-alert list and
        an unsubscribe link in every email we send. None of the three exists,
        and there is nowhere on the site to sign up for any of them."""
        text = " ".join(
            _read_html(built_site, "privacy.html").get_text(" ").lower().split()
        )
        for claim in (
            "send our weekly deal roundup newsletter",
            "send price drop alerts",
            "if you sign up for price alerts",
            "unsubscribe from emails at any time",
            "the link in every email we send",
        ):
            assert claim not in text, f"privacy policy promises {claim!r}"
        # And it says so positively, so the absence above is deliberate.
        assert "there is no mailing list" in text
