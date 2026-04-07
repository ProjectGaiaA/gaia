# Spec: Product Schema Markup Audit

<!--
This file is the source of truth for this feature. Once written, it
replaces conversation context. Fresh execution windows read this file
and nothing else from the planning sessions.
-->

## Status

- [x] Phase 1: Scope grilled
- [x] Phase 2: Technical approach grilled
- [x] Phase 3: Tasks executed
- [x] Final verification passed

---

## Problem

Plant product pages have JSON-LD Product schema markup, but it has
several issues that may prevent Google from showing rich snippets
(price range, availability in search results): the description field
describes the page rather than the product, image URLs are relative
instead of fully qualified, price values are strings instead of
numbers, and no guard prevents invalid schema from rendering on
zero-price plants.

## Scope Decisions

- Phase 1 scope pre-filled by Commander decision; scope grill skipped.
- 72 product pages only. Not category, guide, or other pages.
- This is an audit/fix of existing schema, not building from scratch.

## Out of Scope

- Organization schema
- BreadcrumbList schema (already exists and is fine)
- FAQ schema
- Review/AggregateRating schema
- Individual Offer nodes per retailer (may revisit later)
- Brand field (partial data coverage would look inconsistent)
- priceValidUntil (marginal benefit, risk if scraper goes down)
- Custom hand-written descriptions per plant (too much maintenance)

---

## Technical Approach

Four targeted fixes to the existing Product schema in
`templates/product.html`. All changes are template-level — no data
model changes, no build.py logic changes beyond what's already
available.

**1. Rewrite description to be product-focused.**
Current: `"Hydrangea paniculata - Deciduous shrub. Grows in zones 3, 4, 5, 6, 7, 8, 9."`
New: `"Limelight Hydrangea (Hydrangea paniculata) — deciduous flowering shrub, 6-8 ft tall. Full sun to part shade, zones 3-9. Blooms summer through fall."`
Auto-generated from existing plant fields: common_name, botanical_name,
type, mature_size, sun, zones, bloom_time. No new data needed.

**2. Guard: omit entire Product schema when no prices exist.**
Wrap the Product `<script>` block in `{% if lowest_price %}`. An
AggregateOffer with no prices is invalid schema. BreadcrumbList still
renders independently.

**3. Fully qualify image URL.**
Change `/assets/images/{{ plant.image }}` to
`{{ canonical_url|replace('/plants/' ~ plant.id ~ '.html', '') }}/assets/images/{{ plant.image }}`.
Or simpler: use the `BASE_URL` constant. Since `canonical_url` is
already passed to the template, derive the base from it or pass
`base_url` explicitly.

**4. Fix numeric types.**
Change `"{{ '%.2f'|format(lowest_price) }}"` (string) to
`{{ '%.2f'|format(lowest_price) }}` (unquoted number). Same for
highPrice and offerCount.

### Why this shape

These are the four changes that the SEO expert consensus (3 independent
evaluations) identified as the highest-impact fixes for rich snippet
eligibility. More complex changes (individual Offers per retailer,
brand field, priceValidUntil) were evaluated and rejected for
risk/complexity vs marginal benefit.

## Files Likely Touched

- `templates/product.html` — all 4 fixes are template changes (lines 6-23)
- `build.py` — may need to pass `base_url` to template context (one line)

---

## Task List

### Task 1: Fix Product schema markup in product template

**What:** Apply all four fixes to the Product JSON-LD block in
`templates/product.html`:

1. Rewrite `description` to auto-generate a product-focused string from
   plant fields (common_name, botanical_name, type, mature_size, sun,
   zones, bloom_time).
2. Wrap the entire Product `<script>` block in `{% if lowest_price %}`
   so it only renders when prices exist.
3. Change image URL from relative to fully qualified using base_url.
   If `base_url` is not in the template context, add it in build.py
   where the product template is rendered (search for
   `canonical_url=` near line 1096).
4. Remove quotes around lowPrice, highPrice, and offerCount values
   so they render as JSON numbers, not strings.

**Acceptance:**
- Build succeeds (`python -X utf8 build.py`)
- Pick 3 generated product pages in `site/plants/`, extract JSON-LD,
  validate that:
  - description is product-focused (contains botanical name, size, sun, zones)
  - description does NOT contain "compare" or "nurseries"
  - image URL starts with `https://`
  - lowPrice/highPrice are unquoted numbers
  - offerCount is an unquoted integer
- Pick 1 plant with no prices (if any exist), confirm no Product schema
  block in the HTML (BreadcrumbList should still be present)
- Paste the JSON-LD into https://validator.schema.org/ or run a
  JSON parse check to confirm valid JSON

**Depends on:** none

---

## Acceptance Criteria (Whole Feature)

- [x] All 72 product pages have valid Product JSON-LD when prices exist
- [x] Product description is product-focused, auto-generated from plant fields
- [x] Image URLs in schema are fully qualified (https://...) — template wired correctly; no plants have images yet so field is correctly omitted
- [x] Price values are JSON numbers, not strings
- [x] Zero-price plants have no Product schema block (BreadcrumbList still present)
- [x] Build passes with no errors
- [x] JSON-LD on at least 3 sample pages parses as valid JSON — all 150 blocks across 77 pages parse clean

## Manual Verification Steps

1. Run `python -X utf8 build.py` and serve locally
2. Open 3 different product pages in browser, view source, find JSON-LD
3. Paste each JSON-LD block into Google's Rich Results Test
   (https://search.google.com/test/rich-results) and confirm "Product"
   result with no errors
4. Check that the description reads naturally as a plant description
5. After deploying, monitor Google Search Console > Enhancements >
   Product for any new errors

---

## Execution Log

- Task 1: DONE — All 4 fixes applied (description rewrite, price guard, image URL, numeric types). Build passes. 68/72 pages have valid Product schema, 4 zero-price pages correctly omit it. All JSON-LD parses clean.
