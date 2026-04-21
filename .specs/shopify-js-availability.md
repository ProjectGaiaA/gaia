# Shopify .js availability cross-check — PARKED

**Status:** Unfinished. Parked 2026-04-21.
**Patch:** `shopify-js-availability.patch` (apply with `git apply`)

## Problem

Shopify `.json` endpoint returns unreliable availability data:
- **PlantingTree** omits the `available` field entirely.
- **Spring Hill** reports `available: true` for sold-out items.

Result: site shows "In Stock" / cheapest-price for items the user can't buy.

## Proposed fix (what the patch does)

Add a second request to the Shopify `.js` endpoint (same product, different
extension) which returns accurate per-variant availability. Cross-check
`.json` size tiers against `.js` availability:
- If a variant is sold out per `.js`, delete that size tier from the listing.
- Recalculate `any_available` from the filtered set.
- Point product URL to the cheapest still-available variant.

New method `_check_js_availability(handle)` + post-processing block in
main fetch method. ~59 lines.

## Why it was parked

- **No tests** — method and new branch have zero direct coverage.
- **Retailer coverage unknown** — only PT and Spring Hill were the
  motivating cases; behavior on NH, SH, Brecks, PWD, FGT not validated.
- **Aggressive deletion** — removes size tiers permanently within a
  scrape cycle. If `.js` returns partial/rate-limited data, valid
  variants could silently disappear.

## To resume

1. Apply patch: `git apply .specs/shopify-js-availability.patch`
2. Add tests covering:
   - `.js` response parsing (fixture-based)
   - Size-tier filtering when a variant is sold out
   - Graceful fallback when `.js` returns None/404
   - All-variants-sold-out path (should mark whole product unavailable)
3. Dry-run against each active retailer before shipping — diff price
   output vs current bot output and eyeball for regressions.
4. Consider: should `.js` failures fall through silently (current
   behavior) or halt the scrape for that product?
