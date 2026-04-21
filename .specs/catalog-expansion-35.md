# Spec: Catalog Expansion — 35 New Plants

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

The site has 72 active plants across 13 categories, but 5 categories are
too thin to provide real comparison value: groundcovers (1 plant), grasses
(2), shade trees (3), perennials (6), and azaleas-rhododendrons (5 with
weak retailer coverage). Users landing on these category pages see little
content and few price comparisons. Adding 35 popular plants with confirmed
multi-retailer availability would bring the catalog to ~107 active plants,
fill every category to 5+ entries, and increase the number of pages
generating affiliate traffic. Two currently inactive plants (Vinca Minor,
Echinacea PowWow Wild Berry) may also be reactivated if handle discovery
confirms 2+ retailers.

## Scope Decisions

- **Cut rule**: Any candidate plant that comes back from handle discovery with fewer than 2 retailer handles gets dropped. Price comparison with only 1 retailer has no value.
- **Reactivations**: Vinca Minor and Echinacea PowWow Wild Berry get reactivated if they pass the same 2-retailer cut rule. The 3 inactive houseplants stay inactive (retailer coverage problem).
- **Zone range**: Include warm-zone-only plants (Purple Fountain Grass zones 9-11, Pampas Grass zones 7-11) because they are high-search-volume. Popularity outweighs narrow zone coverage.
- **Houseplants excluded**: No new houseplants. The mapped retailers are outdoor nurseries. Houseplant expansion is blocked until Bloomscape (or similar) handles are discovered.
- **Staged rollout**: Plants are added in 3-4 batches grouped by category. Each batch gets a full build + scrape verification before the next batch goes in. Not all-or-nothing.
- **Handle discovery first**: Before any plants are added to plants.json, run discover_handles.py against all 35 candidates to confirm real Shopify handles on 2+ retailers. The final plant list depends on these results.

## Candidate Plant List (35, subject to handle discovery cut)

### Batch 1: Groundcovers + Grasses (11 plants)

**Groundcovers (6):**
1. Big Blue Liriope — confirmed NH, FGT, SH
2. Ajuga Chocolate Chip — confirmed NH, PT
3. Creeping Thyme — confirmed NH
4. Sedum Angelina — confirmed NH
5. Blue Rug Juniper — confirmed FGT
6. Mondo Grass — confirmed PT

**Grasses (5):**
7. Pink Muhly Grass — confirmed NH, PT, FGT, SH (strongest candidate)
8. Purple Fountain Grass — confirmed NH, FGT
9. Hameln Dwarf Fountain Grass — confirmed NH, FGT
10. Blue Fescue (Elijah Blue) — confirmed NH
11. Pampas Grass — confirmed FGT

### Batch 2: Perennials (8 plants)

12. Astilbe — confirmed NH, SH
13. Heuchera (Coral Bells) — confirmed NH, SH
14. Bleeding Heart — confirmed NH, SH
15. Purple Coneflower — confirmed NH, SH
16. Happy Returns Daylily — confirmed NH
17. Bee Balm — confirmed NH, SH
18. Catmint (Walker's Low) — confirmed FGT, NH
19. Russian Sage — confirmed NH

*Plus reactivations if handles confirm:*
- Echinacea PowWow Wild Berry (currently inactive)
- Vinca Minor (currently inactive, goes in Batch 1)

### Batch 3: Trees (10 plants)

**Shade Trees (5):**
20. October Glory Maple — confirmed NH, PT, FGT
21. Heritage River Birch — confirmed FGT
22. Red Sunset Maple — confirmed NH
23. Sweetbay Magnolia — confirmed FGT
24. Bald Cypress — confirmed NH

**Flowering Trees/Shrubs (4):**
25. Rose of Sharon — confirmed NH, FGT
26. Wine & Roses Weigela — confirmed FGT, NH
27. Spirea (Goldflame) — confirmed NH
28. Gardenia (Frost Proof) — confirmed NH, PT

**Privacy Trees (1):**
29. Dwarf Alberta Spruce — confirmed NH, FGT, PT

### Batch 4: Azaleas + Remaining (6 plants)

**Azaleas-Rhododendrons (3):**
30. Autumn Royalty Encore Azalea — confirmed FGT, NH
31. Autumn Twist Encore Azalea — confirmed NH
32. Autumn Angel Encore Azalea — confirmed NH

**Privacy Trees (1):**
33. Nandina (Heavenly Bamboo) — confirmed PT, FGT

**Fruit Trees (2):**
34. Santa Rosa Plum — confirmed NH, FGT
35. Dwarf Cavendish Banana — confirmed FGT

## Out of Scope

- **Houseplant expansion** — blocked on Bloomscape handle discovery; separate feature later
- **New categories** — all 35 plants fit existing categories; no new category pages
- **Retailer handle map expansion for existing plants** — the 6 active retailers with zero handle maps (Brecks, Stark Bros, Plant Addicts, Bloomscape, Wayside Gardens, Gardeners Supply) are a separate initiative
- **Image sourcing** — new plants will launch with empty image fields, same as many existing plants
- **Content/guide pages** — no new care guides, planting guides, or SEO content for the new plants in this feature
- **Scraper changes** — no modifications to scraper logic; only data file additions
- **Size tier customization** — new plants get standard size tier mappings; retailer-specific overrides are a follow-up if needed

---

## Technical Approach

### Process Document

A reusable `ADDING_PLANTS.md` guide lives in the project root. Defines the
step-by-step process for adding any plant to the catalog in the future.
No automation script for plant authoring — just a documented checklist with
reference tables for size tiers by plant type, field descriptions, and
the reconciliation rules.

### New Script: `scrapers/extract_plant_data.py`

A standalone script (new file, no modifications to existing scrapers) that:
1. Takes a plant name + list of confirmed retailer handles as input.
2. Fetches each Shopify product page via `/products/{handle}.json` (using
   `scrapers/polite.py` for delays and user-agents).
3. Parses the `body_html` description field to extract: zones, sun,
   mature size, bloom time, plant type.
4. Outputs a structured JSON block per retailer with what it found.
5. LLM reconciliation step: compares across retailers, applies majority
   rule (3+ sources agree → use that value), LLM tiebreak (2 sources
   disagree → LLM decides), LLM fallback (1 source or no sources →
   LLM fills, flagged for human review).
6. Outputs a draft `plants.json` entry ready for human review.

Does NOT pull prices or write JSONL — the existing scraper pipeline
handles that on the next scheduled run after activation.

### Workflow for the 35-Plant Expansion

1. **Handle discovery** — run `discover_handles.py` across all retailers
   (one pass over catalog pages). Produces candidate handle lists.
2. **Human confirms handles** — review discovery output, add confirmed
   handles to `data/handle_maps.json`.
3. **Botanical data extraction** — run `extract_plant_data.py` for each
   plant with its confirmed handles (one pass over product pages only).
   LLM reconciles conflicts, outputs draft plant entries.
4. **Human reviews** draft entries for accuracy.
5. **Add to `plants.json` as inactive** — in 4 batches matching the spec's
   batch groupings. One commit per batch (~8-11 plants each).
6. **Opus verification pass** per batch — checks all entries for
   consistency, missing fields, zone range sanity, category validity.
7. **Activate passing plants** — flip `active` to true (or remove the
   field, since true is default). Apply 2-retailer cut rule: plants with
   <2 handles in `handle_maps.json` stay inactive.
8. **Build + verify** each batch — `python -X utf8 build.py`, check
   product pages render, category pages update, sitemap includes new
   entries, no build errors.
9. **Prices appear** on next scheduled scraper run (2x/day via GitHub
   Actions). Manual scraper run optional if faster turnaround needed.

### Reactivation Candidates

Vinca Minor and Echinacea PowWow Wild Berry go through the full process:
discovery, botanical data extraction, human review, Opus verification.
Their existing `plants.json` entries get updated with fresh data from
retailer pages, not trusted as-is. Activated only if 2+ retailer handles
confirm.

### Size Tier Strategy

Process doc defines standard size tier templates per plant type as a
starting point:
- Shrubs/perennials/groundcovers/grasses: quart, 1gal, 2gal, 3gal, 5gal
- Trees (shade/flowering/privacy): 1gal, 3gal, 5gal, 7gal + height tiers
- Fruit trees: dwarf, semi-dwarf, standard + bareroot variants

Templates are starting points, not constraints. Actual tiers adjusted
based on what retailers sell. The build's normalizer handles anything
that comes through regardless.

### Botanical Data Reconciliation Rules

- **3+ retailers agree on a value** → use that value (majority rule).
- **2 retailers disagree** → LLM decides based on horticultural knowledge.
- **1 retailer or no data** → LLM fills the value, flagged in output for
  human review.
- Applies to: zones, sun, mature size, bloom time, plant type.
- Does NOT apply to: planting_seasons and price_seasonality (these are
  researched per plant by the LLM, since retailers rarely provide
  zone-by-zone planting windows or monthly price indices).

### What Doesn't Change

- No modifications to `discover_handles.py`, `shopify.py`, `runner.py`,
  or `build.py`.
- No new categories — all 35 plants fit existing categories.
- Nav bar in `base.html` stays as-is (hardcoded 4 categories still valid).
- No new guide pages.
- GitHub Actions workflows unchanged — fully dynamic from `plants.json`.

## Files Likely Touched

- `ADDING_PLANTS.md` — **new file**, reusable process documentation
- `scrapers/extract_plant_data.py` — **new file**, botanical data extractor
- `data/plants.json` — 35 new entries (inactive), then activated in batches
- `data/handle_maps.json` — new handle mappings per retailer per plant

---

## Task List

### Task 1: Write the ADDING_PLANTS.md process document

**What:** Create `ADDING_PLANTS.md` in the project root. Covers the full
process for adding a plant: field-by-field schema reference, standard
size tier templates per plant type, botanical data sourcing rules
(retailer pages first, LLM fallback), reconciliation rules (majority /
LLM tiebreak / LLM fallback with flag), handle discovery steps,
activation checklist, and notes on things to check (nav bar, guide
mapping) for future category expansions.

**Acceptance:** Document exists, covers all fields in `plants.json` with
descriptions and examples, includes size tier templates, reconciliation
rules, and the end-to-end workflow. A new contributor could follow it
to add a plant without asking questions.

**Depends on:** none

### Task 2: Build `scrapers/extract_plant_data.py`

**What:** New standalone script that takes plant name + confirmed handles,
fetches Shopify product pages, parses botanical data from `body_html`,
runs LLM reconciliation across retailers, and outputs a draft
`plants.json` entry. Uses `scrapers/polite.py` for request etiquette.
Includes tests (mocked HTTP, no live retailer requests).

**Acceptance:** Script runs against mocked product pages and produces a
valid `plants.json` entry with all required fields. LLM reconciliation
correctly applies majority rule, tiebreak, and fallback-with-flag.
Fields that came from LLM fallback are marked in the output.

**Depends on:** Task 1 (process doc defines the field schema and
reconciliation rules the script implements)

### Task 3: Run handle discovery for all 35 candidates

**What:** Run `discover_handles.py` across all active Shopify retailers.
Review output, confirm matches for all 35 candidates + 2 reactivation
candidates. Record confirmed handles. Add to `data/handle_maps.json`.
Apply the 2-retailer cut rule — any plant with <2 confirmed handles is
flagged for potential removal from the candidate list.

**Acceptance:** `handle_maps.json` updated with confirmed handles for all
passing candidates. A list of any plants that failed the 2-retailer cut
is documented in the Execution Log. Discovery output saved for reference.

**Depends on:** none (can run in parallel with Tasks 1-2, but handles are
needed before Task 4)

### Task 4: Extract botanical data and author Batch 1 (Groundcovers + Grasses, ~11 plants)

**What:** Run `extract_plant_data.py` for Batch 1 plants using confirmed
handles from Task 3. Review LLM-reconciled output. Author complete
`plants.json` entries. Add to `plants.json` as inactive. Include the
2 reactivation candidates if they passed the cut (Vinca Minor goes in
Batch 1). Commit.

**Acceptance:** Batch 1 plants in `plants.json` as inactive with all
required fields. Opus verification pass confirms: no missing fields,
zone ranges sane, categories valid, size tiers appropriate. Build
succeeds with no errors.

**Depends on:** Tasks 2, 3

### Task 5: Extract botanical data and author Batch 2 (Perennials, ~8 plants)

**What:** Same as Task 4 for Batch 2 plants. Includes Echinacea PowWow
Wild Berry reactivation if it passed the cut.

**Acceptance:** Same as Task 4 for Batch 2. Opus verification passes.
Build succeeds.

**Depends on:** Tasks 2, 3

### Task 6: Extract botanical data and author Batch 3 (Trees, ~10 plants)

**What:** Same as Task 4 for Batch 3 plants (shade trees, flowering
trees/shrubs, privacy trees).

**Acceptance:** Same as Task 4 for Batch 3. Opus verification passes.
Build succeeds.

**Depends on:** Tasks 2, 3

### Task 7: Extract botanical data and author Batch 4 (Azaleas + Remaining, ~6 plants)

**What:** Same as Task 4 for Batch 4 plants (azaleas, nandina, fruit
trees).

**Acceptance:** Same as Task 4 for Batch 4. Opus verification passes.
Build succeeds.

**Depends on:** Tasks 2, 3

### Task 8: Activate all passing plants and final build verification

**What:** For each batch, flip passing plants from inactive to active
(remove `"active": false` or set to true). Run full build. Verify
product pages render, category pages update with new plant counts,
sitemap includes all new entries, no broken links. Verify handle
maps are complete for all active plants.

**Acceptance:** All passing plants active. `python -X utf8 build.py`
succeeds. Every new plant has a product page at
`site/plants/{plant-id}.html`. Category pages show updated plant
counts. Sitemap includes all new URLs. No build warnings or errors.

**Depends on:** Tasks 4, 5, 6, 7

---

## Acceptance Criteria (Whole Feature)

- [x] `ADDING_PLANTS.md` exists and documents the full process
- [x] `scrapers/extract_plant_data.py` exists with tests, produces valid plant entries
- [x] All candidates that passed the 2-retailer cut are active in `plants.json`
- [x] All candidates that failed the cut are documented and remain inactive (or removed)
- [x] Reactivation candidates (Vinca Minor, Echinacea PowWow) activated if 2+ handles confirmed, otherwise remain inactive
- [x] `handle_maps.json` has entries for every active new plant × every retailer that carries it
- [x] `python -X utf8 build.py` succeeds with zero errors
- [x] Every new active plant has a rendered product page in `site/plants/`
- [x] Every affected category page shows updated plant counts
- [x] `site/sitemap.xml` includes all new product page URLs
- [x] No existing plant pages or functionality broken by the additions
- [ ] Prices appear for new plants after next scheduled scraper run (or manual run)

## Manual Verification Steps

1. Open 3 random new product pages in a browser — confirm price table placeholder renders, botanical info is present and plausible, breadcrumbs link to correct category, wishlist button works.
2. Open each affected category page (groundcovers, grasses, perennials, shade-trees, flowering-trees, azaleas-rhododendrons, privacy-trees, fruit-trees) — confirm new plants appear, counts are correct, zone filters work.
3. Check `site/sitemap.xml` — confirm it contains URLs for all new product pages.
4. After the next scraper run, revisit 3 product pages — confirm prices are populated with real retailer data, affiliate links resolve to correct products.
5. Run `python -X utf8 -m scrapers.verify --count 5` after prices populate — confirm scraped prices match live retailer pages.

---

## Execution Log

<!-- Phase 3. Append-only. -->

- **Task 1** (2026-04-09): Created `ADDING_PLANTS.md` (470 lines). Covers all 17 fields with descriptions/examples, 3 size tier templates, reconciliation rules table, 6-stage workflow (discovery → sourcing → authoring → add inactive → verification → activation), reactivation process, and future category expansion checklist. Verification agent: PASS.
- **Task 2** (2026-04-09): Created `scrapers/extract_plant_data.py` + 25 tests + 5 fixtures. Parses body_html (zones, sun, mature_size, bloom_time, type) from 4 HTML formats (list, table, paragraph, inline). Reconciliation: majority/tiebreak/fallback with flagging. Generates complete plants.json entries with all 17 fields. CLI interface for standalone use. 335/335 tests pass. Build: 103 pages, 0 errors. Verification agent: PASS. Note: lxml should be added to requirements.txt before distribution.
- **Task 3** (2026-04-09): Handle discovery for 37 candidates (35 new + 2 reactivation). Fetched sitemaps from 8 active Shopify retailers (Plant Addicts 404, Bloomscape blocked by robots.txt). 116 confirmed handles added to `handle_maps.json` across 6 retailers (NH 32, FGT 30, PT 21, SH 15, Brecks 11, PWD 7). **2-retailer cut results — 33 PASS, 4 FAIL:** (1) Mondo Grass: 0 retailers — all matches were Black Mondo Grass (different species O. planiscapus vs O. japonicus); (2) Bald Cypress: 1 retailer (NH only) — not carried by FGT, PT, or SH; (3) Spirea Goldflame: 0 retailers — discontinued at NH, not carried by FGT or PT; (4) Vinca Minor (reactivation): 1 retailer (FGT only) — NH has cultivar only (Bowles), not at PT or SH. **Echinacea PowWow Wild Berry (reactivation): PASS — 3 retailers (NH, SH, FGT).** Discovery output saved to `data/discovery_candidates_output.json`. **Action for Tasks 4-7:** ~6 genus-level candidates (Astilbe, Heuchera, Bleeding Heart, Bee Balm, Rose of Sharon, and possibly Pampas Grass) need cultivar-specific replacements — find a specific cultivar carried by 2+ retailers and remap handles. Decision: pick specific cultivars for apples-to-apples price comparison.
- **Task 4** (2026-04-09): Authored 10 Batch 1 plants (5 groundcovers + 5 grasses) in `plants.json` as inactive. Fetched product pages from NH, PT, SH, Brecks to extract/verify botanical data. **Cultivar resolutions:** (1) Pampas Grass: removed NH handle `grass-northern-pampas` — confirmed Tripidium ravennae (Ravennae Grass), different species from Cortaderia selloana; kept FGT+SH+PT (3 retailers). (2) Creeping Thyme: NH sells Elfin (T. serpyllum), Brecks sells Red (T. praecox) — kept genus-level, both are creeping thyme groundcovers with comparable pricing. (3) Purple Fountain Grass: NH sells dwarf 'Cupreum', FGT likely standard 'Rubrum' — kept genus-level. FGT JSON endpoints blocked (404 on all tested handles); scraper uses HTML fallback for prices. All 10 entries pass field/zone/category/size-tier/handle-coverage verification. 335/335 tests pass. Build: 103 pages, 0 errors (87 total plants, 72 active, 15 inactive). Script `scripts/add_batch1.py` created for reproducibility.
- **Task 5** (2026-04-09): Authored 8 Batch 2 perennials in `plants.json` as inactive + updated Echinacea PowWow Wild Berry (zones 3-8→3-9, added zone 9 planting_seasons). Fetched product pages from NH for all 9 plants; cross-referenced Brecks for Happy Returns, Russian Sage, Astilbe. **Genus-level resolutions (4 of 4 Batch 2 candidates resolved):** (1) Astilbe: kept genus-level — 5 retailers carry 5 different cultivars (Montgomery, Bridal Veil, Deutschland, Dark Side of the Moon, Garden Mix), no single cultivar overlap, all comparable garden Astilbe. (2) Heuchera: kept genus-level — 6 retailers carry 6 different cultivars, all Heuchera hybrids with same care profile. (3) Bleeding Heart: kept genus-level, botanical name D. eximia — 3 of 4 retailers carry D. eximia varieties (Fringed, Luxuriant, Pink Diamonds). (4) Bee Balm: kept genus-level — retailers carry Jacob Cline, mixes, Leading Lady Amethyst, all Monarda didyma. **Purple Coneflower aligned on Magnus** (NH + SH both carry Magnus). **Echinacea PowWow reactivation:** 3 retailers confirmed (NH, SH, FGT), entry updated with fresh NH data, kept inactive for Task 8 activation. All 9 entries pass field/zone/category/size-tier/handle-coverage verification (0 errors, 0 warnings). 335/335 tests pass. Build: 103 pages, 0 errors (95 total plants, 72 active, 23 inactive). Script `scripts/add_batch2.py` created for reproducibility. **Remaining genus-level candidate:** Rose of Sharon (Batch 3).
- **Task 6** (2026-04-10): Authored 8 Batch 3 trees in `plants.json` as inactive. Two candidates removed per Task 3's 2-retailer cut: Bald Cypress (1 retailer) and Spirea Goldflame (0 retailers). **Final Batch 3 (8 plants):** (a) shade-trees (4) — October Glory Maple, Heritage River Birch, Red Sunset Maple, Sweetbay Magnolia; (b) flowering-trees (3) — Rose of Sharon, Wine & Roses Weigela, Frost Proof Gardenia; (c) privacy-trees (1) — Dwarf Alberta Spruce. **Rose of Sharon cultivar resolution:** kept at genus level (`Hibiscus syriacus`) — 5 retailers carry 5 different H. syriacus cultivars (NH Lucy, PT Pink Chiffon, SH Blue Bird, PWD Azurri Blue Satin, FGT Lavender), no single cultivar overlap; same reconciliation pattern as Batch 2 Astilbe/Heuchera/Bleeding Heart/Bee Balm. Spring Hill's misleading handle `bluebird-hardy-hibiscus` verified via live product.json fetch — title is "Blue Bird Rose of Sharon", confirmed *Hibiscus syriacus* not *H. moscheutos*. **Botanical data sourcing:** fetched 22 product pages across NH, PT, SH, PWD, Brecks with polite delays; FGT skipped (JSON endpoints 404). NH body_html is marketing copy with no specs; PT provides structured Shopify tags (comma-delimited string with `Grows in Zones_N`, `Mature Height_*`, `Mature Width_*`, `Sunlight_*` prefixes). Authoritative zone/sun/size/bloom/type values cross-referenced against **NCSU Extension Plant Toolbox** and **Missouri Botanical Garden Plant Finder** for all 8 plants; PT tags used for retailer triangulation. **Noteworthy data decisions:** Dwarf Alberta Spruce zones 3-6 per NCSU/MBG (PT's 3-8 rejected — MBG explicitly "not south of zone 6", heat-sensitive); Sweetbay Magnolia kept at species level (ignored Moonglow cultivar since spec lists as generic); Frost Proof Gardenia 7-11 (cultivar is more cold-hardy than species). Verification pass: 0 errors / 0 warnings across all 8 plants (17-field schema, zones/planting_seasons alignment, valid categories, size-tier structure, 2-retailer cut). Em-dash style consistency fix: replaced 9 U+2014 characters with ASCII hyphens in Batch 3 note/tip fields to match Batches 1-2. Build: 100 pages, 0 errors (103 total plants, 72 active, 31 inactive). 341/341 tests pass. Lint: `ruff check` clean on new scripts. Scripts `scripts/add_batch3.py` and `scripts/extract_batch3.py` created for reproducibility. Raw retailer data saved to `data/batch3_extraction_results.json`. Verification agent: **PASS** (all 12 checks including adversarial probe of flipping Rose of Sharon active and confirming product page renders with correct botanical name and encoding). **Note:** plants.json Batch 1+2 state was recovered from `stash@{0}` ("catalog-expansion-35 WIP / auto-stashed during scraper-hygiene cleanup") at session start before Batch 3 authoring began.
- **Task 7** (2026-04-13): Authored 6 Batch 4 plants in `plants.json` as inactive via `scripts/add_batch4.py`. **Batch 4 (6 plants):** (a) azaleas-rhododendrons (3) — Autumn Royalty, Autumn Twist, Autumn Angel Encore Azaleas; (b) privacy-trees (1) — Nandina (Heavenly Bamboo); (c) fruit-trees (2) — Santa Rosa Plum, Dwarf Cavendish Banana. All 6 pass 2-retailer cut (2-3 retailers each). 341/341 tests pass. Build: 100 pages, 0 errors (109 total, 69 active, 40 inactive). Committed as `f7a6d13`.
- **Task 8** (2026-04-13): Activated 33 plants — 32 new (Batches 1-4) + 1 reactivation (Echinacea PowWow Wild Berry, 3 retailers). Removed `"active": false` from all passing plants. 7 remain inactive: saucer-magnolia, wax-leaf-privet, vinca-minor (1 retailer), 4 houseplants. **Final verification:** Build: 133 pages (102 product, 13 category, 11 guide), 0 errors. 341/341 tests pass. `ruff check` clean. All 102 active plants have product pages. All 33 new plants in sitemap.xml. All 8 affected category pages render with correct plant counts: groundcovers 6, grasses 7, perennials 15, shade-trees 7, flowering-trees 12, azaleas-rhododendrons 8, privacy-trees 8, fruit-trees 12. Handle maps confirmed: all 33 activated plants have 2+ retailers. Existing plant pages verified intact. Adversarial probes: Rose of Sharon (genus-level, encoding-sensitive botanical name) renders correctly; Dwarf Cavendish Banana (narrowest zones 9-11) renders with correct zone data. Committed as `e4525d9`. **Remaining:** prices appear after next scraper run (2x/day CI), manual verification steps deferred to user.
