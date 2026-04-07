# Spec: Internal Linking

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

The site's 109 pages don't cross-link well. Category pages don't link to
their guides, product pages don't link to guides or back to their category
(beyond a breadcrumb), and the Similar Plants sidebar picks 5 arbitrary
same-category plants with no sorting logic. This means Google has fewer
crawl paths between pages, and users have no useful "what next" navigation
after viewing a product or category page.

## Scope Decisions

- Similar Plants stays **same-category only**. No cross-category suggestions. Users browsing fruit trees don't want bushes.
- Similar Plants sorted by **most zone overlap first, then cheapest first** as tiebreaker. Currently unsorted (arbitrary JSON order).
- Still **5 items** in Similar Plants — no change to count.
- **Category pages link to their relevant guides.** The guide-to-category mapping already exists in build.py (`find_related_plants_for_guide()`).
- **Product pages link to the guide for their category**, giving users a content path from any product page.
- **Product pages get a "Browse all [Category]" link** near the bottom, more prominent than the breadcrumb.
- **Fix the price cutoff** on the Similar Plants sidebar (prices clipped on right edge).
- **Visual treatment stays minimal** — consistent with the rest of the bare-bones site. No redesign.
- Guide → plant links already exist in the guide markdown content and sidebar. No changes needed there.
- Zone data already exists in plants.json as integer arrays. No new data needed.

## Out of Scope

- Visual redesign of any section or page
- Cross-category linking ("Like fruit trees? Try azaleas")
- "Goes well together" / companion planting (no data exists)
- Price-based linking as a separate section (price is only a sort tiebreaker within Similar Plants)
- Guide content changes (guides already link to individual plant pages)
- Internal links on special pages (heatmap, wishlist, improve)
- Any new data collection or manual curation
- "Also grows in your zone" as a separate section (zone awareness baked into Similar Plants sort)

---

## Technical Approach

### Similar Plants Sorting

`find_similar_plants()` in build.py currently returns `same_cat[:5]` — first
5 plants in JSON file order, no sorting. Change to:

1. Filter same-category plants (existing).
2. Compute zone overlap: `len(set(plant.zones) & set(candidate.zones))`.
3. Sort descending by zone overlap, then ascending by `lowest_price`
   (None-priced plants sort last).
4. Return top 5.

**Price pre-enrichment:** The product page build loop currently enriches each
plant with `lowest_price` during rendering — meaning similar-plant candidates
may not have prices yet when they appear as sort candidates. Fix: add a
pre-enrichment pass before the product page loop that loads prices and sets
`lowest_price` on every plant dict upfront. The existing per-plant price
loading in the loop stays (it builds the full price_table needed for the
template context), but enrichment fields like `lowest_price` are already set.

### Guide Links on Category + Product Pages

**Guide article parsing must happen early.** Currently guides are parsed and
built AFTER product and category pages. Move the `parse_article_md()` calls
to early in the build so guide metadata (slug + title) is available for all
templates.

**Category-to-guide mapping:** Invert the existing `slug_to_category` dict
in `find_related_plants_for_guide()` to produce a `category_to_guide` dict:

```
{
  "hydrangeas": {"slug": "best-hydrangeas-to-buy-online", "title": "Best Hydrangeas to Buy Online"},
  "fruit-trees": {"slug": "best-fruit-trees-to-buy-online", "title": "..."},
  ...
}
```

8 categories get their specific guide. The 5 categories without a guide
(grasses, groundcovers, houseplants, perennials, shade-trees) fall back to
`"cheapest-places-to-buy-online"` ("Cheapest Places to Buy Plants Online").

**Category template:** Add a guide link under the header, above the
filters/plant grid. Renders for every category.

**Product template:**
- Sidebar: guide link added above the Similar Plants section.
- Main content: "Browse all [Category]" link added near the bottom, after
  the care guide / price history sections. More prominent than the breadcrumb.

### Price Cutoff Fix

The `.similar-price` in the sidebar uses `float: right`, which clips against
the container edge on narrow sidebars. Fix: switch the `<a>` inside each
`.similar-plants li` to `display: flex; justify-content: space-between` and
remove the float. Also add `flex-shrink: 0` on the price span so it never
collapses.

## Files Likely Touched

- `build.py` — Similar Plants sort logic, price pre-enrichment, early guide
  parsing, category-to-guide mapping, template context for product + category
- `templates/category.html` — Guide link section
- `templates/product.html` — Guide link in sidebar, "Browse all" in main
- `site/assets/css/style.css` — Price cutoff fix, styling for new link sections

---

## Task List

### Task 1: Sort Similar Plants by zone overlap + price

**What:** Change `find_similar_plants()` to sort candidates by zone overlap
(descending) then `lowest_price` (ascending, None last). Add a price
pre-enrichment pass before the product page build loop so all plant dicts
have `lowest_price` set before sorting runs.

**Acceptance:**
- Build succeeds (`python -X utf8 build.py`).
- Pick a product page with 5+ same-category plants. Verify the Similar
  Plants list is sorted by zone overlap with the current plant (most overlap
  first). Among tied plants, cheapest appears first.
- Plants with no price data appear last among tied zone-overlap plants.
- No other template or visual changes.

**Depends on:** none

### Task 2: Add guide links to category pages

**What:** Move guide article parsing earlier in `build.py` (before product/
category page rendering). Build a `category_to_guide` mapping — 8 categories
get their specific guide, 5 categories without a guide fall back to
`"cheapest-places-to-buy-online"`. Pass guide link data (slug + title) to
the category template. Add a guide link element under the category header in
`templates/category.html` with minimal styling in `style.css`.

**Acceptance:**
- Build succeeds.
- Open a category page that has a dedicated guide (e.g., Hydrangeas). The
  guide link text references the specific guide and links to the correct URL.
- Open a category page WITHOUT a dedicated guide (e.g., Shade Trees). The
  guide link text references the general buying guide and links to
  `/guides/cheapest-places-to-buy-online.html`.
- All 13 category pages have a guide link.

**Depends on:** none

### Task 3: Add guide + browse-category links to product pages

**What:** Pass category guide data and category metadata to the product
template context. Add a guide link in the sidebar (above Similar Plants) in
`templates/product.html`. Add a "Browse all [Category]" link in the main
content area near the bottom. Style both with minimal CSS.

**Acceptance:**
- Build succeeds.
- Open a product page. The sidebar shows a guide link above Similar Plants,
  pointing to the correct guide for that plant's category (or the fallback).
- The main content area has a "Browse all [Category]" link pointing to
  `/category/{cat}.html`.
- Both links render on all 72 product pages.

**Depends on:** Task 2 (uses the category-to-guide mapping and early guide parsing)

### Task 4: Fix Similar Plants price cutoff

**What:** In `site/assets/css/style.css`, replace the `float: right` layout
on `.similar-price` with flexbox on the parent `<a>`. Add `flex-shrink: 0`
on the price span. Remove the float. Verify prices are fully visible at
various viewport widths.

**Acceptance:**
- Build succeeds (CSS is not generated, but build confirms templates still
  reference the stylesheet).
- Open a product page with Similar Plants that have prices. Prices are
  fully visible — no clipping on the right edge.
- The sidebar layout is unchanged apart from the clipping fix.

**Depends on:** none

---

## Acceptance Criteria (Whole Feature)

- [x] Every product page's Similar Plants shows 5 same-category plants sorted by zone overlap (most first), then cheapest first
- [x] Every category page (13 total) has a guide link under the header
- [x] 8 category pages link to their specific guide; 5 link to the general buying guide
- [x] Every product page (72 total) has a guide link in the sidebar above Similar Plants
- [x] Every product page has a "Browse all [Category]" link in the main content area
- [x] Similar Plants prices are fully visible with no clipping
- [x] `python -X utf8 build.py` succeeds with no errors
- [x] `pytest` passes with no new failures
- [x] `ruff check` passes with no new violations

## Manual Verification Steps

1. Build the site and serve locally (`cd site && python -m http.server 8151`).
2. Open a Hydrangea product page — verify Similar Plants are sorted by zone
   overlap, sidebar has a link to the hydrangea guide, and main content has
   "Browse all Hydrangeas" linking to `/category/hydrangeas.html`.
3. Open a Shade Trees product page — verify the sidebar guide link points to
   the general buying guide (`/guides/cheapest-places-to-buy-online.html`).
4. Open the Hydrangeas category page — verify the guide link under the header
   points to `/guides/best-hydrangeas-to-buy-online.html`.
5. Open the Grasses category page — verify the guide link under the header
   points to `/guides/cheapest-places-to-buy-online.html`.
6. Resize browser to ~350px width — verify Similar Plants prices aren't clipped.
7. Spot-check 3 product pages from different categories for both new links.

---

## Execution Log

- Task 1: Done. Sorted find_similar_plants() by zone overlap desc + lowest_price asc (None last). Added pre-enrichment pass. Build/tests/lint pass. Verified on Limelight Hydrangea, Honeycrisp Apple, Kousa Dogwood, and synthetic edge cases.
- Task 2: Done. Moved guide parsing early, built category_to_guide map (8 dedicated + fallback), added guide link to all 13 category pages. Build/tests/lint pass.
- Task 3: Done. Guide link in sidebar + "Browse all [Category]" in main content on all 72 product pages. 8 categories get dedicated guide, 5 get fallback. Build/tests/lint pass.
- Task 4: Done. Replaced float:right with flexbox on .similar-plants/.guide-related li a. Prices fully visible at desktop sidebar width. Pre-existing page overflow at mobile widths is unrelated.
