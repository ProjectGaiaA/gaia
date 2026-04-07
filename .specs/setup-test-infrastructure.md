# Spec: setup-test-infrastructure

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
- [x] Final verification passed

---

## Problem

PlantPriceTracker has zero tests. The scraper system pulls prices from
8 online nurseries and generates a live comparison site — if a scraper
breaks or parses prices wrong, bad data goes live to users with no
safety net. There is no pytest configuration, no test directory, no
conftest, and no fixtures. Before any new features can follow the
spec-driven ritual (which requires TDD), the test foundation must exist.

## Scope Decisions

- **Scrapers first, not build pipeline.** The scrapers are where bugs
  cost the most — wrong prices, missed products, broken pages go live.
  Build pipeline tests are a future spec.
- **All HTTP calls mocked.** Tests never hit real nursery sites. Mocking
  at the `requests` boundary — faster, deterministic, no risk of IP bans.
- **Real response snapshots as fixtures.** Capture actual JSON and HTML
  responses from retailers and save as test fixture files. Most realistic
  coverage of real-world edge cases.
- **Full scraper coverage.** Test every scraper method that touches
  external data across all 6 scraper files. Target: 20-30+ tests covering
  all critical paths. Not "just enough to prove pytest works."
- **Testable behaviors, in priority order:**
  1. Size normalization (the most complex parsing logic, many edge cases)
  2. JSON product parsing (Shopify standard format)
  3. HTML fallback parsing (FGT/Brighter Blooms path)
  4. Stark Bros dataLayer/JSON-LD parsing
  5. Price anomaly detection (>50% swing flagging)
  6. JSONL append recording
  7. Promo code extraction
  8. Robots.txt compliance (fail-open behavior)
  9. Handle discovery fuzzy matching
  10. Verify.py price comparison with 2% tolerance

## Out of Scope

- Build pipeline tests (`build.py`, templates, site generation)
- End-to-end integration tests that hit live retailer sites
- CI/CD pipeline changes (GitHub Actions test step)
- Performance testing or load testing
- UI/visual regression testing
- Changing any existing scraper code (tests wrap existing behavior)

---

## Technical Approach

**Mocking strategy:** Use the `responses` library to mock all HTTP calls
at the `requests` boundary. This is purpose-built for mocking the
requests library — register URL patterns with canned responses, no
boilerplate per test. Added to requirements.txt as a dev dependency.

**Fixture organization:** `tests/fixtures/` with per-retailer subdirectories
(`nature-hills/`, `fgt/`, `starkbros/`, etc.). Each fixture is a real
response snapshot captured from the actual retailer — JSON for Shopify
endpoints, HTML for fallback pages. Naming convention:
`{handle}-product.json`, `{handle}-page.html`.

**Sleep mocking:** `time.sleep` patched to no-op via `unittest.mock.patch`
in individual tests that exercise code paths calling `polite_delay()`.
This keeps tests running in milliseconds instead of minutes.

**Test structure:** One test file per scraper module. Tests verify
behavior through public interfaces (not internal methods). Each test
loads a real fixture, registers it with `responses`, calls the public
method, and asserts on the returned data structure.

**Tradeoffs considered:**
- `pytest-httpserver` (local HTTP server) rejected — heavier, binds real
  ports, unnecessary when `responses` does the job.
- `unittest.mock.patch` alone rejected — too much boilerplate per test
  for URL-based mocking. `responses` is cleaner for HTTP-specific mocks.
- Synthetic test data rejected — real snapshots catch edge cases that
  synthetic data would miss (weird variant names, missing fields, etc.).

## Files Likely Touched

- `tests/conftest.py` — shared fixtures, sleep mock
- `tests/test_shopify.py` — Shopify scraper tests (JSON + HTML)
- `tests/test_starkbros.py` — Stark Bros scraper tests
- `tests/test_runner.py` — runner orchestration tests (anomaly, JSONL, manifest)
- `tests/test_polite.py` — robots.txt, delays, headers
- `tests/test_verify.py` — price comparison verification tests
- `tests/test_discover.py` — handle discovery fuzzy matching tests
- `tests/fixtures/nature-hills/` — Nature Hills JSON snapshots
- `tests/fixtures/fgt/` — FGT HTML snapshots (JSON blocked)
- `tests/fixtures/starkbros/` — Stark Bros HTML with dataLayer
- `requirements.txt` — add `responses` and `pytest` as dev deps
- `pyproject.toml` — pytest configuration (testpaths, markers)

---

## Task List

### Task 1: Foundation — pytest config, conftest, first fixture, first test

**What:** Create `tests/` directory, `pyproject.toml` with pytest config,
`conftest.py` with shared fixtures (sleep mock, tmp data dir), capture
one real Nature Hills JSON response as a fixture, write one test that
proves the Shopify scraper can parse it into the correct data structure.
Add `responses` and `pytest` to requirements.txt.
**Acceptance:** `pytest` runs, 1 test passes, fixture loads correctly,
`responses` mocks the HTTP call, `time.sleep` is patched out.
**Depends on:** none

### Task 2: Shopify scraper tests — JSON parsing + size normalization

**What:** Write tests for ShopifyScraper covering: JSON product parsing
(happy path with real fixture), size normalization across all tier types
(quart, gallon, height, bareroot, default), multi-plant pack filtering,
variant availability (True/False/None), deep link URL generation, 404
handling (should trigger HTML fallback path), 429 rate limit handling.
Capture additional fixtures as needed.
**Acceptance:** 8-12 tests passing. Size normalization covers at least
10 different input formats. Pack filtering rejects "2 Plant(s)" bundles.
**Depends on:** Task 1

### Task 3: Shopify HTML fallback + promo code tests

**What:** Capture a real FGT HTML page as a fixture. Write tests for
HTML fallback parsing: aria-label extraction, schema.org Offers parsing,
size button extraction. Write tests for promo code detection: valid
code patterns, banner extraction, false positive filtering (all-digit,
short codes, common words). Capture a homepage with announcement bar.
**Acceptance:** 5-8 tests passing. HTML parsing extracts correct prices
from aria-labels. Promo detection finds "SAVE20" but rejects "FREE".
**Depends on:** Task 1

### Task 4: Stark Bros scraper tests

**What:** Capture a real Stark Bros product page as fixture. Write tests
for: dataLayer parsing, JSON-LD fallback, variant normalization
(dwarf-bareroot, semi-dwarf-potted, etc.), price filtering (skip <= 0),
Stark Bros promo code detection.
**Acceptance:** 4-6 tests passing. dataLayer extraction returns correct
product structure. Variant normalization handles all Stark Bros patterns.
**Depends on:** Task 1

### Task 5: Runner, verify, discover, and polite tests

**What:** Write tests for: price anomaly detection (>50% swing = flagged,
normal change = not flagged, new plant = no anomaly), JSONL append
(correct format, creates directory), verify.py price comparison with
2% tolerance (match, mismatch, edge cases), discover_handles fuzzy
matching (exact match = 1.0, partial match, no match below threshold),
normalization stripping. Write tests for polite.py: robots.txt
compliance (allowed, disallowed, fail-open on unreachable).
**Acceptance:** 8-12 tests passing. Anomaly detection correctly flags
>50% swings. Fuzzy matching scores correctly. Robots.txt fails open.
**Depends on:** Task 1

---

## Acceptance Criteria (Whole Feature)

- [x] `pytest` runs from project root with zero configuration beyond pyproject.toml
- [x] 25+ tests pass covering all 6 scraper modules (71 tests)
- [x] All HTTP calls mocked — no test hits real nursery sites
- [x] Real response fixtures stored in tests/fixtures/ per-retailer dirs
- [x] `time.sleep` mocked — full suite runs in under 10 seconds (1.52s)
- [x] `ruff check` passes on all test files
- [x] No changes to existing scraper code (tests wrap current behavior)
- [x] `responses` library added to requirements.txt

## Manual Verification Steps

1. Run `pytest -v` from project root — confirm all tests listed and pass
2. Run `pytest` with network disconnected — confirm all tests still pass
   (proves no real HTTP calls)
3. Spot-check one fixture file against the actual retailer page it was
   captured from — confirm it's a real response, not synthetic
4. Run `ruff check tests/` — confirm clean

---

## Execution Log

<!-- Phase 3. Append-only. -->

- Task 1: 2026-04-06 — Foundation: pyproject.toml, conftest.py, Nature Hills fixture, 1 test passing
- Task 2: 2026-04-06 — Shopify JSON tests: 24 tests (size normalization ×16, pack filtering, availability, 404 fallback, 429 retry, deep linking, zero-price, Ships in Spring)
- Task 3: 2026-04-06 — HTML fallback + promo tests: 7 tests (aria-label extraction, pack filtering, was_price, promo code extraction, false positive rejection, empty promos, request failure)
- Task 4: 2026-04-06 — Stark Bros tests: 13 tests (dataLayer extraction, variant normalization ×9, was_price, JSON-LD fallback)
- Task 5: 2026-04-06 — Runner/verify/discover/polite tests: 27 tests (anomaly detection ×4, JSONL append ×2, stored prices ×3, tolerance checks ×2, fuzzy matching ×4, normalization ×4, robots.txt ×3, UA/headers/session ×5)
- Final verification: 2026-04-06 — 71 tests, 0 failures, 1.52s, ruff clean, no scraper code changes

Known issue found: Pack filter regex has a gap — "10-Pack" (hyphenated) leaks through because the regex requires a space before "pack". Documented for future fix.
