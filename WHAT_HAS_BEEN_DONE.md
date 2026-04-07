# Build Pipeline Tests — What Has Been Done

Spec: `.specs/build-pipeline-tests.md`

## Summary

Added a comprehensive test suite for `build.py` — the static site generator that turns plant data and price history into 109 HTML pages. Before this work, the build pipeline had zero tests. Now it has 98 tests covering both data logic and full page generation.

## Tasks Completed

### Task 1: Synthetic Fixtures and Shared Test Infrastructure
- Created 8 fixture files in `tests/fixtures/build/`:
  - `plants.json` — 5 synthetic plants (3 normal, 1 stale-price, 1 inactive)
  - `retailers.json` — 2 synthetic retailers with affiliate info
  - `prices/test-hydrangea.jsonl` — multi-tier, out-of-stock, was_price scenarios
  - `prices/test-maple.jsonl` — mixed size systems (feet vs gallons)
  - `prices/test-apple.jsonl` — exotic tier names (dwarf, semi-dwarf, jumbo)
  - `prices/test-stale-plant.jsonl` — price from >30 days ago
  - `feedback.json` — 1 feedback entry
  - `01-test-guide.md` — minimal guide markdown
- Added `load_build_fixture()` helper to `tests/conftest.py`
- Added `beautifulsoup4` to `requirements.txt`
- 12 smoke tests in `tests/test_build_fixtures.py`

### Task 2: Data Logic Tests — Size Normalization, Price Table, Savings
- 42 tests in `tests/test_build_data.py` covering:
  - `normalize_size_tier()` — aliases, typos, case handling, variant IDs
  - `get_size_label()` — human-readable labels, unknown fallback
  - `build_price_table()` — best-price marking, out-of-stock sorting, was_price/sale flags, stale exclusion, unavailable after 3 missed runs
  - Savings calculations — same-tier, cross-tier, outlier filtering
  - Retailer exclusion — no price = no row

### Task 3: Data Logic Tests — Price History, Heatmap, Utilities
- 44 tests in `tests/test_build_data2.py` covering:
  - `get_latest_prices()` — picks most recent per retailer
  - `count_consecutive_run_misses()` — correct miss counts, edge cases
  - `build_price_history_json()` — Chart.js format, inactive retailer filtering
  - `parse_month_range()` — single month, range, year-wrap (Nov-Jan), empty
  - `build_heatmap_data()` — monthly index averaging, zone planting windows
  - `find_similar_plants()` — same category, excludes self, max n
  - `load_feedback()` — date enrichment, missing field handling

### Task 4: Page Generation Tests — Full Build Integration
- 40 tests in `tests/test_build_pages.py` covering:
  - Session-scoped fixture that monkeypatches build.py path constants and runs `build_site()` once against synthetic data
  - Product page existence — 4 active plants get pages, inactive does not
  - Product page content — retailer names, prices, was_price, botanical name, stale price exclusion
  - Category pages — correct plant membership per category, inactive excluded
  - Sitemap — all active pages listed, inactive excluded, categories and guides included
  - Homepage — exists, has category data, has plant count
  - Heat map — exists, contains category data from plants
  - Guide pages — generated from markdown, correct title, index page links to guide
  - Improve page — exists, shows feedback item title
  - Inactive plant exclusion — swept across ALL product pages, category pages, sitemap, homepage
  - Misc — robots.txt, wishlist page

## Test Counts

| File | Tests | Category |
|------|-------|----------|
| `tests/test_build_fixtures.py` | 12 | Fixture smoke tests |
| `tests/test_build_data.py` | 42 | Data logic (size, price table, savings) |
| `tests/test_build_data2.py` | 44 | Data logic (history, heatmap, utilities) |
| `tests/test_build_pages.py` | 40 | Page generation integration |
| **Build pipeline total** | **138** | |
| Existing scraper tests | 71 | Scraper unit tests |
| **Full suite total** | **209** | |

## Key Design Decisions

- **Synthetic data, not real data.** Tests use 5 fake plants and 2 fake retailers with controlled values. This allows exact assertions (e.g., "savings should be exactly 25%") and doesn't break when real plant data changes.
- **One build, many assertions.** The page generation tests run `build_site()` once in a session-scoped fixture, then 40 tests read the output HTML. This keeps the suite fast (~1.6s total).
- **BeautifulSoup for HTML parsing.** Tests parse generated HTML with BS4 and check content via `get_text()` and element selectors. More robust than string matching — survives template refactors.
- **No changes to build.py.** Tests wrap current behavior. If a test reveals a bug, the test documents it — fixing is a separate spec.

## What Is NOT Covered

- CSS/visual regression testing
- CI pipeline wiring (adding test step to GitHub Actions)
- Performance or load testing
- Table-cell-level price placement (tests confirm prices are on the page, but don't yet verify they're in the correct `<td>`)
- End-to-end deployment testing

## How to Run

```bash
# All tests
pytest -v

# Just build pipeline tests
pytest tests/test_build_fixtures.py tests/test_build_data.py tests/test_build_data2.py tests/test_build_pages.py -v

# Just page generation tests
pytest tests/test_build_pages.py -v

# Lint
ruff check tests/
```
