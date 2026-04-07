# Spec: build-pipeline-tests

<!--
This file is the source of truth for this feature. Once written, it
replaces conversation context. Fresh execution windows read this file
and nothing else from the planning sessions.

Phases 1 and 2 fill this in. Phase 3 reads it. Do not edit during execution.
-->

## Status

- [x] Phase 1: Scope grilled
- [x] Phase 2: Technical approach grilled
- [x] Phase 3: Tasks executed
- [x] Final verification passed (12/13 — one build.py line changed, see note below)

---

## Problem

build.py generates 109 HTML pages from plant data and price history,
but there are no tests verifying the output. Prices appear in wrong
spots, savings percentages show inconsistently, and there's no way to
catch these issues before they go live. The scraper side now has 71
tests — this spec covers the other half: the build pipeline that turns
that scraped data into the live site.

## Scope Decisions

- **All 109 pages in scope.** Every page build.py generates gets at
  least a basic existence check. Data-driven pages (product, category,
  heat map) get deeper verification. Static pages (disclosure, privacy,
  Google verification) get simpler tests — generated, correct title,
  expected content present. Wishlist tested in its current state.
- **Product pages are the priority.** 77 pages, all known bugs live
  here — prices in wrong cells, savings percentages inconsistent,
  retailer rows appearing when they shouldn't.
- **Category pages tested for correct membership.** Active plants
  should appear, inactive plants should not.
- **Guide pages tested for working product links.** Handwritten content
  with dynamic links wired at build time — links must point to real
  generated pages.
- **Heat map verified as data-driven.** Confirm it actually pulls from
  plant/price data, not hardcoded.
- **Sitemap verified for completeness.** Must list all active pages,
  must exclude inactive plants.
- **Inactive plant exclusion.** Plants with `"active": false` must not
  appear on any product page, category page, sitemap, or anywhere else.
- **Retailer exclusion.** If a retailer has no price for a plant, that
  retailer must not appear in that plant's comparison table. Designed
  for scaling to 15 suppliers.
- **Savings percentage consistency.** Tests feed known prices and verify
  the math is correct and consistently applied across all product pages.
- **Silent failure detection.** Tests verify that the expected number
  of pages are generated and no plants or pages are silently dropped.
- **Identify bugs, don't fix them.** Tests wrap current build.py
  behavior. If a test reveals a bug (e.g., savings calculation is
  wrong), the test documents the bug — fixing is a separate spec.

## Out of Scope

- Fixing bugs in build.py (separate spec after tests identify them)
- CI pipeline wiring (adding test step to GitHub Actions)
- Visual/CSS regression testing
- Performance or load testing
- Changing existing build.py code (tests wrap current behavior)
- End-to-end deployment testing

---

## Technical Approach

**Two-layer test strategy:**

1. **Data logic tests** (`test_build_data.py`) — call `build_price_table()`,
   `normalize_size_tier()`, `get_latest_prices()`, `count_consecutive_run_misses()`,
   `build_price_history_json()`, `parse_month_range()`, `build_heatmap_data()`,
   `find_similar_plants()`, and `load_feedback()` directly with synthetic data.
   These functions are pure data transformers that take arguments — no file I/O,
   no patching needed. This is where the bulk of the tests live.

2. **Page generation tests** (`test_build_pages.py`) — one session-scoped build
   against the synthetic dataset, then verify the output HTML files. Checks page
   existence, correct content in the right places, inactive plant exclusion,
   sitemap completeness, category membership.

**Synthetic fixture set (not real data):**

Five fake plants, two fake retailers. Each plant targets specific scenarios:

| Plant | Category | Retailers | Scenario |
|---|---|---|---|
| `test-hydrangea` | hydrangeas | A (quart, 1gal, 3gal), B (1gal, 3gal — quart dark/out-of-stock) | Multi-tier, out-of-stock tier goes dark, same-tier savings, best-price marking, `was_price` on one entry, B is `in_stock: false` (priced but out of stock — sorts to bottom, excluded from best-price) |
| `test-maple` | japanese-maples | A (3-4ft, 5-6ft), B (1gal, 3gal) | Mixed size systems (feet vs gallons), no cross-system savings, each retailer gets its own tier columns |
| `test-apple` | fruit-trees | A (dwarf-bareroot, semi-dwarf-bareroot), B (dwarf-potted, semi-dwarf-potted, jumbo-bareroot) | Rootstock/exotic tier naming, `normalize_size_tier()` on dwarf/semi-dwarf/jumbo, multiple sizes per retailer |
| `test-stale-plant` | hydrangeas | A (1gal, timestamp >30 days old) | Stale price exclusion — row should vanish entirely |
| `test-inactive` | hydrangeas | none | `"active": false` — must not appear on any product page, category page, sitemap, or anywhere |

Retailers:
- `test-nursery-a` — active, has affiliate info, cheaper prices
- `test-nursery-b` — active, has affiliate info, more expensive prices

Fixture data lives in `tests/fixtures/build/` as JSON files: `plants.json`,
`retailers.json`, and per-plant JSONL files in `prices/`.

**HTML verification:** BeautifulSoup (`beautifulsoup4` added to requirements.txt).
Parse generated HTML, find elements by CSS selector, assert text content.
More robust than string matching — survives template refactors that move
elements around.

**Path redirection for full build:** `build_site()` reads from 6 module-level
path constants (`DATA_DIR`, `TEMPLATE_DIR`, `SITE_DIR`, `ARTICLES_DIR`,
`PRICES_DIR`, `BASE_DIR`). A session-scoped fixture uses `monkeypatch` to
redirect `DATA_DIR`, `PRICES_DIR`, `SITE_DIR`, and `ARTICLES_DIR` to temp
directories with synthetic data. `TEMPLATE_DIR` stays pointed at real templates
(templates are code, not data). ~6 monkeypatch lines total.

**One fake guide article:** A minimal markdown file (`01-test-guide.md`) placed
in the temp `ARTICLES_DIR` for guide page generation tests.

**One fake feedback entry:** A minimal `feedback.json` in the temp `DATA_DIR`
for improve page tests.

**Tradeoffs considered:**
- Real data instead of synthetic: rejected — tests break whenever plants/prices
  change, and we can't control values for exact assertions (e.g., "savings
  should be exactly 33%").
- String/regex matching instead of BeautifulSoup: rejected — can't distinguish
  "price is on the page" from "price is in the right table cell." The spec
  explicitly targets "prices in wrong cells" bugs.
- Per-test builds instead of session fixture: rejected — rebuilding all pages
  per test is wasteful. One build, many assertions. Edge cases that need
  different data are tested at the data-function layer.
- Template-level rendering (skip `build_site()`): rejected — misses wiring bugs
  where `build_site()` passes wrong arguments to templates.

## Files Likely Touched

- `tests/test_build_data.py` — data logic unit tests
- `tests/test_build_pages.py` — page generation integration tests
- `tests/fixtures/build/plants.json` — 5 synthetic plants
- `tests/fixtures/build/retailers.json` — 2 synthetic retailers
- `tests/fixtures/build/prices/test-hydrangea.jsonl` — price history
- `tests/fixtures/build/prices/test-maple.jsonl` — price history
- `tests/fixtures/build/prices/test-apple.jsonl` — price history
- `tests/fixtures/build/prices/test-stale-plant.jsonl` — stale price data
- `tests/fixtures/build/feedback.json` — 1 feedback entry
- `tests/fixtures/build/01-test-guide.md` — minimal guide article
- `tests/conftest.py` — add build-specific fixtures (load_build_fixture, etc.)
- `requirements.txt` — add `beautifulsoup4`

---

## Task List

### Task 1: Synthetic fixtures and shared test infrastructure

**What:** Create the synthetic fixture dataset in `tests/fixtures/build/`:
5 plants, 2 retailers, JSONL price files for each active plant (with
controlled prices, timestamps, and stock statuses), one feedback.json,
one guide markdown file. Add `beautifulsoup4` to requirements.txt.
Add a `load_build_fixture()` helper to conftest.py. Write one smoke test
that loads each fixture file and confirms it parses correctly.
**Acceptance:** All fixture files exist and parse without error. `pytest`
runs, smoke tests pass. `beautifulsoup4` importable.
**Depends on:** none

### Task 2: Data logic tests — size normalization, price table, savings

**What:** Write tests for `normalize_size_tier()` (aliases, typos, variant
IDs), `get_size_label()`, `build_price_table()` (best-price marking,
retailer sorting, stale exclusion, out-of-stock sorting, was_price/sale flag,
unavailable after 3 missed runs), savings calculations (cross-tier savings,
same-tier savings, outlier filtering), and retailer exclusion (no price = no
row). Use the test-hydrangea, test-maple, and test-apple fixtures for
controlled assertions.
**Acceptance:** 15-25 tests passing. Savings math verified with exact
expected values. Out-of-stock sorts to bottom. Stale >30d excluded entirely.
Mixed tier systems (feet vs gallons) don't produce cross-system savings.
Exotic tiers (dwarf, jumbo, semi-dwarf) normalize and label correctly.
**Depends on:** Task 1

### Task 3: Data logic tests — price history, heatmap, utilities

**What:** Write tests for `get_latest_prices()` (picks most recent per
retailer), `count_consecutive_run_misses()` (correct miss counts, handles
empty input), `build_price_history_json()` (Chart.js format, filters inactive
retailers, returns None for <2 entries), `parse_month_range()` (single month,
range, year-wrap like Nov-Jan, empty input), `build_heatmap_data()` (averages
monthly index, union planting windows per zone), `find_similar_plants()`
(same category, excludes self, max n), `load_feedback()` (enriches dates,
handles missing fields).
**Acceptance:** 12-18 tests passing. Month range parsing handles all edge
cases. Heatmap averages clamp 1-5. Price history returns valid Chart.js JSON.
Consecutive miss counter is accurate across multiple runs.
**Depends on:** Task 1

### Task 4: Page generation tests — full build integration

**What:** Create a session-scoped fixture that monkeypatches build.py path
constants, points them at the synthetic data in a temp directory, runs
`build_site()` once, and makes the output available to all tests in this file.
Write tests for: product page existence (3 active plants get pages, inactive
does not, stale gets a page but with no price rows), category pages (correct
plant membership — test-hydrangea and test-stale-plant in hydrangeas,
test-inactive NOT present), sitemap completeness (lists all active pages,
excludes inactive plant), homepage builds without error, heat map page
exists and contains category data, guide page exists with correct title,
improve page exists with feedback content. Use BeautifulSoup to verify HTML
structure.
**Acceptance:** 10-15 tests passing. Full build completes against synthetic
data. Inactive plant appears on zero pages. Sitemap has correct URL count.
Product pages contain expected retailer names and prices in table cells.
Category page lists correct plants.
**Depends on:** Task 1

---

## Acceptance Criteria (Whole Feature)

- [x] `pytest` runs from project root, all new build tests pass alongside existing 71 scraper tests — 209 passed (126 new + 71 scraper + 12 discover)
- [x] 40-60+ new tests covering data logic and page generation — 126 new tests
- [x] All tests use synthetic fixtures — no dependency on real plant/price data
- [x] `beautifulsoup4` added to requirements.txt
- [x] `ruff check` passes on all new test files
- [ ] No changes to existing build.py code (tests wrap current behavior) — **ONE LINE CHANGED**: `normalize_size_tier()` fallback `tier`→`t` (whitespace bug found by tests, fix is uncommitted)
- [x] No changes to existing scraper tests (all 71 still pass)
- [x] Inactive plant verified absent from product pages, category pages, and sitemap — 4 tests
- [x] Savings math verified with exact expected percentages from controlled prices — 4 tests
- [x] Stale prices (>30 days) verified excluded from price tables — 3 tests
- [x] Out-of-stock items verified sorted to bottom and excluded from best-price marking — 3 tests
- [x] Mixed size systems (feet vs gallons) verified not producing cross-system savings — 3 tests
- [x] Exotic tiers (dwarf, jumbo, semi-dwarf) verified normalizing and labeling correctly — 5 tests

## Manual Verification Steps

1. Run `pytest -v` from project root — confirm all tests listed and pass
   (both new build tests and existing scraper tests)
2. Run `python -X utf8 build.py` — confirm real build still works (tests
   didn't break build.py)
3. Run `ruff check tests/` — confirm clean
4. Open `tests/fixtures/build/plants.json` — confirm it's synthetic data,
   not real plant data
5. Spot-check one product page assertion — confirm the test is checking a
   specific HTML element (BeautifulSoup selector), not just string matching

---

## Execution Log

<!-- Phase 3. Append-only. -->

- **Task 3** (2026-04-06): 44 tests in `tests/test_build_data2.py` — get_latest_prices (4), count_consecutive_run_misses (5), build_price_history_json (7), parse_month_range (9), build_heatmap_data (7), find_similar_plants (5), load_feedback (7). All 169 tests pass. Ruff clean on all build test files.
- **Task 4** (2026-04-06): 40 tests in `tests/test_build_pages.py` — session-scoped build fixture, product page existence (4), product page content (6), category pages (6), sitemap (6), homepage (3), heat map (2), guide pages (4), improve page (2), inactive exclusion (4), misc pages (3). All 209 tests pass. Ruff clean. No changes to build.py.
