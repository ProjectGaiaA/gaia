# Spec: Auto-Heal — Detect and Recover Broken Product URLs

<!--
This file is the source of truth for this feature. Once written, it
replaces conversation context. Fresh execution windows read this file
and nothing else from the planning sessions.

Phases 1 and 2 fill this in. Phase 3 reads it. Do not edit during execution.
-->

## Status

- [x] Phase 1: Scope grilled
- [x] Phase 2: Technical approach grilled
- [ ] Phase 3: Tasks executed
- [ ] Final verification passed

---

## Problem

When a retailer changes a product URL slug — due to renaming, catalog
restructuring, or platform migration — the scraper starts getting 404s
on that product. Currently this fails silently: no new price gets
appended, and after 30 days the product ages off the site. Nobody
notices until a visitor reports stale data or the operator manually
audits. Meanwhile, a CI step ("Remove broken retailer links")
attempts to catch this by HEAD-requesting every retailer URL after
each scrape. This is the wrong approach — it hammers retailers with
~500 rapid-fire requests using a bot user-agent, risks IP bans, burns
GitHub Actions minutes, and still doesn't fix anything. It just
deletes data faster.

## Scope Decisions

- **All URL changes require confirmation before going live.** Whether
  found via redirect or catalog discovery, no new handle is used by
  the scraper until Opus (via scheduled task) or the operator confirms
  it. Products stay "Currently Unavailable" until confirmation. Bad
  links are worse than missing links — site trust is the priority.

- **Redirect detection is the first recovery step.** Most retailers
  set up 301 redirects when they rename products. Checking for a
  redirect is free (no extra requests beyond what the scraper already
  makes). Only if there is no redirect does the system escalate to
  catalog discovery.

- **Discovery must be extra polite.** When catalog discovery runs, it
  is crawling pages the scraper wouldn't normally touch. It must use
  UA rotation, robots.txt checking, and longer delays than normal
  scraping. This is the highest ban-risk operation in the pipeline.

- **Recovery phase is skipped entirely when nothing is broken.** If
  zero products need recovery, no time is spent — no catalog fetching,
  no extra requests, nothing.

- **Time-budgeted recovery.** Recovery gets whatever time remains from
  the 90-minute CI timeout after the scrape completes, minus a
  10-minute buffer for post-scrape steps (build, commit, deploy). The
  remaining time is split evenly across all products needing recovery.
  One product gets the full budget; ten products each get 1/10th.

- **Retry limit: 7 attempts over ~4 days.** After 7 failed recovery
  attempts, the product is flagged as unrecoverable and surfaced in
  the weekly email. The 2x/daily scrape cadence means 7 attempts
  spans roughly 3.5 days.

- **Same product retried at most once per day.** If discovery fails
  for a product, don't re-crawl the same retailer's catalog again 12
  hours later. Wait until the next day. This halves catalog crawling
  for persistent failures.

- **Weekly email notification.** Unresolved recovery failures and
  Opus rejections are emailed to brandon.william.hall@gmail.com once
  per week. This is the only notification channel — the operator does
  not check GitHub or Proton email regularly.

- **Opus reviews candidates as a scheduled task.** Opus runs
  automatically to review pending handle candidates. No operator
  approval needed for Opus to run. If Opus can't confirm the match,
  it rejects and the failure goes to the weekly email.

- **Staleness window unchanged.** Products that genuinely disappear
  (seasonal, delisted) age off naturally via the existing 30-day
  window. No handle map entries are removed — seasonal products come
  back on their own and discovery can re-find them.

- **Link checker CI step removed.** The "Remove broken retailer
  links" step in scrape.yml is deleted as part of this feature. It is
  replaced entirely by the auto-heal recovery flow.

## Out of Scope

- **Stark Bros recovery.** Stark Bros is not Shopify, has no bulk
  catalog endpoint, and products are mapped via a manual dictionary.
  Auto-recovery for Stark Bros is a separate feature to be specced
  independently.

- **Image or body-text verification.** Verifying recovered URLs by
  comparing product images or body paragraphs was discussed but adds
  substantial complexity. Opus review using botanical names, common
  names, and product metadata is the verification mechanism for this
  feature.

- **Variant-level recovery.** Recovery finds the correct product page.
  Variant/size selection is handled by the existing scraper logic
  after landing on the page. (To be verified during testing that
  this works correctly.)

- **Automatic handle map cleanup.** Delisted products are not removed
  from handle maps. Staleness handles display; dead entries waste one
  failed scrape attempt per run but cause no other harm.

- **Proactive URL monitoring.** This feature is reactive — it
  detects 404s when the scraper encounters them, not before. No
  separate link-checking pass exists.

---

## Technical Approach

### State Storage

Recovery state lives in a separate file `data/recovery.json`, not in the
manifest. The manifest gets fully rewritten every scrape run — a crash
mid-write could wipe recovery state if it lived there. `recovery.json`
is only modified by the recovery module and Opus, never overwritten
wholesale.

### Handle Map Extraction

`HANDLE_MAPS` moves out of `shopify.py` source code into
`data/handle_maps.json`. The scraper loads it at runtime. This turns
handle maps from code into data — the recovery system can write
confirmed handles to a JSON file without editing Python source. The
hardcoded dict is deleted from `shopify.py` entirely.

### 404 Detection

`_get_json()` in `shopify.py` currently returns `None` on 404, making
it impossible to distinguish "handle changed" from "server hiccup."
It gets changed to return a result object with the HTTP status code
and redirect URL (if any). Call sites update from `if data:` to
`if result.data:`.

The first request for each product uses `allow_redirects=False`:
- **301/302**: Extract new handle from `Location` header, log as
  redirect candidate in `recovery.json`. Make a second request to
  the new URL to get actual product data for this run.
- **404**: Write broken handle entry to `recovery.json`.
- **5xx / timeout**: Skip silently (server problem, not a handle change).

This costs one extra request only for redirected products (rare).

### Candidate Validation (Opus Never Touches the Live Map)

Opus writes its verdict (confirmed/rejected) to `recovery.json` only.
On the next scrape run, the scraper sees confirmed candidates, tries
the new handle, and only writes it to `handle_maps.json` if the handle
actually returns product data. If it 404s, the candidate stays in
recovery and gets flagged in the weekly email. This prevents Opus from
ever breaking the live site.

### Recovery Flow (Inline, Time-Budgeted)

After the scrape completes, the recovery module runs in the same CI
job using leftover time: `90 min CI timeout - elapsed scrape time -
10 min buffer for build/commit/deploy`. Budget is split evenly across
all products needing recovery.

For each broken handle (no redirect):
1. Check `last_discovery_attempt` timestamp — skip if < 20 hours ago.
2. Check `attempts` count — if >= 7, mark as unrecoverable, skip.
3. Fetch the retailer's Shopify catalog via `discover_handles.py`.
4. Fuzzy-match against the broken plant's common name.
5. If candidate found, store it in `recovery.json` with: plant common
   name, botanical name, retailer, old handle, candidate handle,
   candidate product title, match score, old sizes/prices (from last
   successful scrape), candidate sizes/prices (from catalog).
6. Increment `attempts`, update `last_discovery_attempt`.

Recovery phase is skipped entirely when `recovery.json` has zero
entries needing work.

### Polite Discovery

`discover_handles.py` currently uses raw `requests.get()` — it gets
wired through `polite.py`'s `make_polite_session()` for UA rotation,
`is_allowed_by_robots()` for robots.txt compliance, and `polite_delay()`
for rate limiting. Discovery uses longer delays than normal scraping
(10-20s vs 5-15s) since it crawls pages the scraper wouldn't normally
touch.

### Opus Review

A scheduled task runs Opus to review pending candidates. Opus receives
context from `recovery.json`: plant common name, botanical name,
retailer, old handle, candidate handle, candidate title, match score,
old sizes/prices, candidate sizes/prices. Opus judges on three
dimensions: name match, size match, and price plausibility. A name
match with wildly different sizes or a 3x price jump is a red flag.
Opus writes confirmed/rejected to `recovery.json`. It makes no HTTP
requests and touches no file other than `recovery.json`.

### Weekly Email

A separate GitHub Actions workflow on a weekly cron reads
`recovery.json` for unresolved failures (>= 7 attempts) and Opus
rejections. Sends a summary email to brandon.william.hall@gmail.com.
Keeps notification logic out of the scrape pipeline entirely.

### Link Checker Removal

The "Remove broken retailer links" step (lines 134-192 of
`scrape.yml`) is deleted. It was redundant with the new recovery
flow and impolite — HEAD-requesting every URL with a bot UA risked
IP bans.

### Tradeoffs Considered

- **Recovery state in manifest vs separate file**: Separate file chosen
  because the manifest is fully rewritten each run. Crash safety.
- **Handle maps in code vs JSON data file**: JSON chosen for clean
  data/code separation. Bigger refactor but recovery can write to
  a data file without editing Python source.
- **Override file vs full extraction**: Full extraction chosen over a
  layered override file. Overrides mean handles live in two places
  and need periodic manual merging. One source of truth is simpler.
- **Redirect detection — disable auto-redirect vs check history**:
  Disabled auto-redirect chosen for explicit control. One extra
  request per redirect, but redirects are rare (few times per year).
- **Opus fetches product page vs reviews locally**: Local review
  chosen. No HTTP requests from scheduled tasks = no ban risk.
  Catalog discovery already captures the metadata Opus needs.
- **Email in scrape pipeline vs separate workflow**: Separate workflow
  chosen. Scrape pipeline writes data, notification job reads it.

## Files Likely Touched

- `scrapers/shopify.py` — Remove `HANDLE_MAPS`, change `_get_json()` return type, add redirect detection, add confirmed-candidate validation on startup
- `scrapers/runner.py` — Call recovery module after scrape, pass time budget
- `scrapers/discover_handles.py` — Wire through `polite.py`, accept polite session, return structured results
- `scrapers/polite.py` — Possibly add discovery-specific delay preset (10-20s)
- `scrapers/recovery.py` — **New file.** Recovery orchestration: read `recovery.json`, try redirects, call discovery, respect budgets/limits
- `data/handle_maps.json` — **New file.** Extracted handle maps
- `data/recovery.json` — **New file.** Recovery state (created at runtime, committed to repo)
- `.github/workflows/scrape.yml` — Remove link checker step (lines 134-192), add recovery step
- `.github/workflows/weekly-recovery-email.yml` — **New file.** Weekly notification workflow
- Scheduled task definition for Opus review
- `tests/` — Tests for detection, recovery, validation, handle map loading

---

## Task List

### Task 1: Extract handle maps to `data/handle_maps.json`

**What:** Create `data/handle_maps.json` from the `HANDLE_MAPS` dict
in `shopify.py`. Update `shopify.py` to load maps from the JSON file
at runtime. Delete the hardcoded dict. Update `get_handles_for_retailer()`
and all internal references. Update any existing tests that reference
`HANDLE_MAPS`.

**Acceptance:**
- `data/handle_maps.json` exists with all current mappings.
- `shopify.py` no longer contains `HANDLE_MAPS` dict.
- `python -m scrapers.runner --retailer nature-hills --skip-promos` works
  identically (dry-run is fine for CI, or mock-test).
- `pytest` passes.
- `ruff check` passes.

**Depends on:** none

### Task 2: 404 detection, recovery state, and candidate validation

**What:** Change `_get_json()` to return a result object with `data`,
`status_code`, and `redirect_url`. Use `allow_redirects=False` on
product requests. Update all call sites. Create `recovery.json` schema
and read/write helper functions (in a new `scrapers/recovery.py` or
a shared utility). On 404: write broken handle entry. On 301/302:
write redirect candidate entry and make a follow-up request for data.
On scrape startup: check `recovery.json` for confirmed candidates,
validate them by requesting the new handle, and write to
`handle_maps.json` if valid.

**Acceptance:**
- `_get_json()` returns a result object, not raw data.
- A mocked 404 produces a `recovery.json` entry with status `"broken"`.
- A mocked 301 produces a `recovery.json` entry with status
  `"redirect_candidate"` and the new handle extracted from the
  redirect URL.
- A mocked confirmed candidate that returns valid data gets written
  to `handle_maps.json` and removed from `recovery.json`.
- A mocked confirmed candidate that 404s stays in `recovery.json`
  and is flagged.
- `pytest` passes. `ruff check` passes.

**Depends on:** Task 1

### Task 3: Wire `discover_handles.py` through `polite.py`

**What:** Replace raw `requests.get()` calls in `discover_handles.py`
with `make_polite_session()` from `polite.py`. Use `polite_delay()`
with longer intervals (10-20s) instead of `time.sleep(3)`. Add
`is_allowed_by_robots()` check before fetching catalog pages. Refactor
`fetch_all_products()` to accept an optional session parameter (for
testability). Optionally add a `discovery_delay()` helper to
`polite.py` with 10-20s range.

**Acceptance:**
- `discover_handles.py` has zero direct `requests.get()` calls.
- All catalog requests go through a polite session with UA rotation.
- `is_allowed_by_robots()` is checked before each catalog page fetch.
- Delays between catalog pages are 10-20s (not the old 3s).
- `pytest` passes. `ruff check` passes.

**Depends on:** none

### Task 4: Recovery module — time-budgeted discovery after scrape

**What:** Create `scrapers/recovery.py` with the main recovery
orchestration logic. After the scrape loop in `runner.py`, call
`recovery.run()` with the remaining time budget. Recovery reads
`recovery.json`, filters to handles that need work (not on cooldown,
under attempt limit), splits budget evenly, and calls
`discover_handles.py` for each. Stores candidates with full context:
plant common name, botanical name, retailer, old handle, candidate
handle, candidate title, match score, old sizes/prices (from last
manifest before the 404), candidate sizes/prices (from catalog).
Respects 20-hour cooldown and 7-attempt limit. Marks handles with
>= 7 failed attempts as `"unrecoverable"`.

**Acceptance:**
- Recovery runs after scrape in `runner.py`.
- Time budget = `90*60 - elapsed - 10*60` seconds (configurable).
- Handles on cooldown (< 20h since last attempt) are skipped.
- Handles at >= 7 attempts are marked `"unrecoverable"`.
- Discovery results written to `recovery.json` with all context fields.
- Recovery does nothing and exits immediately when `recovery.json`
  has zero actionable entries.
- `pytest` passes. `ruff check` passes.

**Depends on:** Task 2, Task 3

### Task 5: Opus review scheduled task

**What:** Create a scheduled task that Opus runs to review pending
candidates in `recovery.json`. The task reads all entries with status
`"redirect_candidate"` or `"discovery_candidate"`. For each, Opus
evaluates whether the candidate is the same product using: plant
common name, botanical name, retailer, old handle, candidate handle,
candidate product title, fuzzy match score, old sizes/prices, and
candidate sizes/prices. Opus writes `"confirmed"` or `"rejected"`
status with a brief reason. The task prompt must instruct Opus to
reject when names suggest a different cultivar/form (e.g., "tree form"
vs "shrub"), when sizes are wildly different, or when prices differ
by more than ~3x.

**Acceptance:**
- Scheduled task definition exists and can be invoked.
- Task reads `recovery.json`, filters to pending candidates.
- Task writes confirmed/rejected verdicts with reasons.
- Task does nothing when no candidates are pending.
- Task makes zero HTTP requests.

**Depends on:** Task 2

### Task 6: Remove link checker from CI

**What:** Delete lines 134-192 of `.github/workflows/scrape.yml`
(the "Remove broken retailer links" step). Verify no other steps
reference its output or depend on it having run.

**Acceptance:**
- The link checker step is gone from `scrape.yml`.
- The workflow YAML is valid (no syntax errors).
- No other step references the removed step's ID or outputs.

**Depends on:** none

### Task 7: Weekly email workflow

**What:** Create `.github/workflows/weekly-recovery-email.yml` on a
weekly cron schedule (Sunday morning). The workflow reads
`data/recovery.json`, collects entries with status `"unrecoverable"`
or `"rejected"`, and sends a summary email to
brandon.william.hall@gmail.com. Use a GitHub Actions email action
or simple SMTP step with credentials stored as GitHub secrets.
Email should list each problem product with: plant name, retailer,
what went wrong (unrecoverable after 7 attempts, or Opus rejected
with reason), and the candidate handle if one was found. Skip
sending if there are zero items to report.

**Acceptance:**
- Workflow file exists and has valid YAML syntax.
- Cron schedule fires weekly.
- Email is sent only when there are items to report.
- Email contains all relevant fields for each problem product.
- No email sent when `recovery.json` has zero reportable entries.

**Depends on:** Task 2

---

## Acceptance Criteria (Whole Feature)

- [ ] Handle maps live in `data/handle_maps.json`, not hardcoded in `shopify.py`.
- [ ] A product 404 during scraping creates a `recovery.json` entry (not silent).
- [ ] A product redirect during scraping captures the new handle as a candidate.
- [ ] Recovery runs after scrape using leftover CI time and discovers candidates.
- [ ] Same product is not re-crawled within 20 hours of last attempt.
- [ ] Products with >= 7 failed attempts are marked unrecoverable.
- [ ] Recovery does nothing when there are zero broken handles.
- [ ] Opus reviews candidates using local data only (no HTTP requests).
- [ ] Confirmed candidates are validated by the scraper before writing to handle maps.
- [ ] A confirmed candidate that still 404s is NOT written to the handle map.
- [ ] `discover_handles.py` uses polite sessions, robots.txt, and 10-20s delays.
- [ ] Link checker step is removed from `scrape.yml`.
- [ ] Weekly email fires only when there are unresolved/rejected items.
- [ ] `pytest` passes. `ruff check` passes. `python -X utf8 build.py` succeeds.

## Manual Verification Steps

1. Manually change a handle in `data/handle_maps.json` to a bogus
   value (e.g., `"limelight-hydrangea-BROKEN"`). Run the scraper for
   that retailer. Confirm `recovery.json` gets a broken entry.
2. Run the scraper again (or trigger recovery manually). Confirm
   discovery finds the correct handle as a candidate.
3. Check `recovery.json` — the candidate should have plant name,
   botanical name, old/new handle, sizes, prices, and match score.
4. Manually set the candidate status to `"confirmed"` in
   `recovery.json`. Run the scraper again. Confirm `handle_maps.json`
   gets updated with the correct handle and the product scrapes
   successfully.
5. Restore the original handle in `handle_maps.json`. Confirm
   everything is back to normal.
6. Check the live site after a full CI run to make sure no products
   went missing or got wrong data.

---

## Execution Log

<!-- Phase 3. Append-only. After each task is verified, the execution
window adds a one-line entry here. Provides a trail of what happened
without polluting the spec body. -->

- Task 1: Done. Extracted 186 handles (7 retailers) to data/handle_maps.json. shopify.py loads via load_handle_maps() with caching. Updated discover_handles.py and wayback_prices.py. 10 new tests, 235 total pass. ruff clean. Build OK (103 pages).
- Task 2: Done. _get_json() returns FetchResult(data, status_code, redirect_url). scrape_product() detects 404→record_broken, 301→record_redirect_candidate, 5xx→skip. New scrapers/recovery.py with state management. save_handle_map_entry() writes confirmed handles. validate_confirmed_candidates() runs at startup. 32 new tests, 274 total pass. ruff clean. Build OK.
- Task 3: Done. Replaced raw requests.get() with make_polite_session() + is_allowed_by_robots() + discovery_delay(10-20s). Added session param for testability. Added discovery_delay() to polite.py. Updated conftest stub_robots. 7 new tests, 242 total pass. ruff clean. Build OK.
- Task 4: Done. Added recovery.run() with time-budgeted discovery: get_actionable_entries (20h cooldown, 7-attempt limit), mark_unrecoverable, record_discovery_candidate with full context, catalog-per-retailer caching, variant price extraction. Wired into runner.py after promo scraping with budget=90min-elapsed-10min. Catalog fetch failures handled gracefully. 18 new tests, 292 total pass. ruff clean. Build OK (103 pages).
- Task 5: Done. Added get_pending_candidates() and set_verdict() to recovery.py. Scheduled task opus-review-recovery-candidates runs every 12h — reads recovery.json, evaluates candidates on name/size/price, writes confirmed/rejected via set_verdict(). Zero HTTP requests. 8 new tests, 300 total pass. ruff clean. Build OK.
- Task 6: Done. Removed "Remove broken retailer links" step (60 lines) from scrape.yml. No step ID existed, no other steps referenced it. YAML valid. 300 tests pass. ruff clean.
- Task 7: Done. Added get_reportable_entries() and format_recovery_email() to recovery.py. Created .github/workflows/weekly-recovery-email.yml (Sunday 12:00 UTC cron, workflow_dispatch). Workflow checks recovery.json, skips email when zero reportable entries, sends via dawidd6/action-send-mail with SMTP secrets. 10 new tests, 310 total pass. ruff clean. Build OK.
