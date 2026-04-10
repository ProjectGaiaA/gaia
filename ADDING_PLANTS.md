# Adding Plants to PlantPriceTracker

Step-by-step process for adding a new plant to the catalog. Follow this
checklist in order. Every plant must pass through all stages before
activation.

---

## Stage 1: Handle Discovery

Before committing to any plant, confirm that at least 2 retailers carry
it. A price comparison site with 1 retailer has no comparison value.

### Run discovery

```bash
# All retailers at once
python -m scrapers.discover_handles

# Single retailer
python -m scrapers.discover_handles --retailer nature-hills

# Dry run (preview matches, don't save)
python -m scrapers.discover_handles --dry-run
```

The script fuzzy-matches the plant's `common_name` and `botanical_name`
against each Shopify store's product catalog. It uses polite scraping
(UA rotation, robots.txt, 10-20s delays between pages).

### Review output

For each candidate, the script reports matched product handles and
confidence scores. Manually verify the top match is actually the right
plant (not a different cultivar or a combo pack).

### The 2-retailer cut rule

If a plant has confirmed handles at fewer than 2 of these retailers, it
does not get added. Drop it or revisit later when more retailers are
mapped.

### Add confirmed handles to handle_maps.json

Structure: each retailer key maps plant IDs to Shopify product handles.

```json
{
  "nature-hills": {
    "pink-muhly-grass": "pink-muhly-grass"
  },
  "fast-growing-trees": {
    "pink-muhly-grass": "pink-muhly-grass-tree"
  }
}
```

**Retailers with handle maps** (Shopify-based, currently mapped):
- `nature-hills` (Nature Hills Nursery)
- `fast-growing-trees` (Fast Growing Trees)
- `spring-hill` (Spring Hill Nurseries)
- `planting-tree` (PlantingTree)
- `proven-winners-direct` (Proven Winners Direct)
- `great-garden-plants` (Great Garden Plants)
- `brighter-blooms` (Brighter Blooms — blocks via robots.txt, prices will age off)

**Retailers without handle maps** (not yet mapped, separate initiative):
- Brecks, Stark Bros, Plant Addicts, Bloomscape, Wayside Gardens, Gardeners Supply

---

## Stage 2: Botanical Data Sourcing

Gather plant attributes from retailer product pages. Multiple sources
reduce the chance of a single retailer's data error propagating into the
catalog.

### Data sources (in priority order)

1. **Retailer product pages** — fetch `/products/{handle}.json` from
   each confirmed retailer. Parse `body_html` for zones, sun, mature
   size, bloom time, and plant type.
2. **LLM reconciliation** — compare values across retailers and resolve
   conflicts (see Reconciliation Rules below).
3. **LLM fallback** — when retailer data is missing or only 1 source
   exists, the LLM fills the value using horticultural knowledge.
   These values must be flagged for human review.

### Reconciliation rules

| Scenario | Rule | Flag for review? |
|---|---|---|
| 3+ retailers agree | Use that value (majority rule) | No |
| 2 retailers disagree | LLM decides based on horticultural knowledge | No |
| 1 retailer only | LLM validates or overrides | Yes |
| No retailer data | LLM fills from knowledge | Yes |

These rules apply to: `zones`, `sun`, `mature_size`, `bloom_time`, `type`.

They do NOT apply to: `planting_seasons` and `price_seasonality`. Those
are researched per-plant by the LLM since retailers rarely provide
zone-by-zone planting windows or monthly price indices.

---

## Stage 3: Author the plants.json Entry

Every plant entry follows the schema below. All fields are required
unless marked optional.

### Field Reference

| Field | Type | Description | Example |
|---|---|---|---|
| `id` | string | Unique kebab-case identifier. Used in URLs (`/plants/{id}.html`), JSONL filenames, handle maps. | `"pink-muhly-grass"` |
| `common_name` | string | Human-readable display name. Title case. | `"Pink Muhly Grass"` |
| `botanical_name` | string | Scientific binomial with cultivar in single quotes. | `"Muhlenbergia capillaris"` |
| `aliases` | string[] | Alternative names shoppers might search for. Can be empty array. | `["Cotton Candy Grass", "Gulf Muhly"]` |
| `category` | string | Must match an existing category slug. See Category List below. | `"grasses"` |
| `zones` | int[] | USDA hardiness zones as integers. Sorted ascending. | `[6, 7, 8, 9, 10, 11]` |
| `sun` | string | Light requirements. Use standard phrases. | `"Full sun"` |
| `mature_size` | string | Height x width at maturity. Use "ft" not "feet". | `"3-4 ft tall x 3-4 ft wide"` |
| `bloom_time` | string | Flowering or display period. Or note if non-flowering. | `"Late summer to fall"` |
| `type` | string | Botanical classification. | `"Ornamental grass"` |
| `size_tiers` | object | Maps canonical tier names to arrays of retailer aliases. See Size Tier Templates below. | *(see below)* |
| `price_range` | string | Approximate price range across retailers and sizes. | `"$15-$45"` |
| `image` | string | Image URL or empty string. New plants launch with `""`. | `""` |
| `image_credit` | string | Attribution or empty string. | `""` |
| `planting_seasons` | object | Zone-keyed planting windows. See Planting Seasons below. | *(see below)* |
| `price_seasonality` | object | Monthly pricing patterns. See Price Seasonality below. | *(see below)* |
| `active` | bool (optional) | Omit for active plants (defaults to `true`). Set `false` to keep in data but exclude from build. | `false` |

### Standard sun values

Common values (prefer these for consistency):

- `"Full sun"`
- `"Full sun to part shade"`
- `"Part shade to full sun"`
- `"Part shade"`
- `"Part shade to full shade"`
- `"Full shade"`

Other values exist in the catalog for specific cases (e.g.
`"Part shade (morning sun, afternoon shade)"` for some Japanese maples).
Use the common values above unless the plant's needs don't fit any of
them.

### Standard type values

Common values used in the catalog:

- `"Deciduous shrub"`
- `"Evergreen shrub"`
- `"Deciduous tree"`
- `"Evergreen tree"`
- `"Ornamental grass"`
- `"Herbaceous perennial"`
- `"Herbaceous perennial groundcover"`
- `"Evergreen groundcover"`
- `"Semi-evergreen groundcover"`
- `"Fruit tree"`

### Category list

These are the existing categories. All new plants must fit one:

| Slug | Display Name |
|---|---|
| `hydrangeas` | Hydrangeas |
| `japanese-maples` | Japanese Maples |
| `fruit-trees` | Fruit Trees |
| `roses` | Roses |
| `blueberries` | Blueberries |
| `flowering-trees` | Flowering Trees |
| `privacy-trees` | Privacy Trees |
| `azaleas-rhododendrons` | Azaleas & Rhododendrons |
| `perennials` | Perennials |
| `houseplants` | Houseplants |
| `grasses` | Grasses |
| `groundcovers` | Groundcovers |
| `shade-trees` | Shade Trees |

Adding a new category requires updating the nav bar in
`templates/base.html` (currently hardcoded to 4 categories), the
`GUIDE_SLUG_TO_CATEGORY` mapping in `build.py`, and optionally authoring
a guide article. The build itself dynamically generates category pages
from whatever categories appear in `plants.json`, so no build.py changes
are needed for the page itself.

---

## Size Tier Templates

Start with the template for the plant's type. Adjust based on what
retailers actually sell — if no retailer offers a 5gal version, leave
that tier out. The build's normalizer handles any tier that comes
through, so there is no harm in including tiers that some retailers
don't carry.

### Shrubs, perennials, groundcovers, grasses

```json
"size_tiers": {
  "quart":  ["1 quart", "qt", "4.5 inch", "4.5 in"],
  "1gal":   ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
  "2gal":   ["2 gallon", "2 gal", "#2 container"],
  "3gal":   ["3 gallon", "3 gal", "#3 container"],
  "5gal":   ["5 gallon", "5 gal", "#5 container"]
}
```

### Trees (shade, flowering, privacy)

```json
"size_tiers": {
  "quart":    ["1 quart", "qt", "4.5 inch", "4.5 in"],
  "1gal":     ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
  "2gal":     ["2 gallon", "2 gal", "#2 container"],
  "3gal":     ["3 gallon", "3 gal", "#3 container"],
  "5gal":     ["5 gallon", "5 gal", "#5 container"],
  "bareroot": ["bare root", "bare-root"]
}
```

### Fruit trees

```json
"size_tiers": {
  "quart":    ["1 quart", "qt", "4.5 inch", "4.5 in"],
  "1gal":     ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
  "2gal":     ["2 gallon", "2 gal", "#2 container"],
  "3gal":     ["3 gallon", "3 gal", "#3 container"],
  "5gal":     ["5 gallon", "5 gal", "#5 container"],
  "bareroot": ["bare root", "bare-root"]
}
```

> **Note:** These templates are starting points. If a retailer sells a
> 7gal or a 10gal, add those tiers. If a retailer uses "jumbo quart" or
> "6 inch pot", add those as aliases to the appropriate tier. The
> normalizer in build.py matches scraped size strings against these
> aliases to bucket prices into comparable tiers.

---

## Planting Seasons

Zone-keyed object. Include an entry for every zone in the plant's
`zones` array. Each zone has `spring` and `fall` keys with month ranges
(or `null` if that season doesn't apply).

### Structure

```json
"planting_seasons": {
  "6": { "spring": "Mar-May",  "fall": "Sep-Nov" },
  "7": { "spring": "Mar-Apr",  "fall": "Oct-Nov" },
  "8": { "spring": "Feb-Apr",  "fall": "Oct-Dec" },
  "9": { "spring": "Feb-Mar",  "fall": "Nov-Dec" }
}
```

### Rules

- Zone keys are strings (e.g. `"6"`, not `6`).
- Month ranges use 3-letter abbreviations: Jan, Feb, Mar, Apr, May,
  Jun, Jul, Aug, Sep, Oct, Nov, Dec.
- Single-month values are fine: `"spring": "May"`.
- Use `null` if planting is not recommended in that season for that zone.
- Colder zones have shorter windows; warmer zones have longer ones.
- The LLM researches these per-plant since retailers rarely provide
  zone-by-zone planting guidance.

---

## Price Seasonality

Monthly pricing pattern used by the heat map and buying guides.

### Structure

```json
"price_seasonality": {
  "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
  "best_buy": "September-October",
  "worst_buy": "April-May",
  "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings.",
  "tip": "Buy in fall, plant in fall. Fall-planted grasses establish stronger root systems."
}
```

### Field details

| Field | Description |
|---|---|
| `monthly_index` | Array of 12 integers (Jan-Dec). Scale: 1 = cheapest month, 5 = most expensive. Represents relative demand-driven pricing. |
| `best_buy` | Month or month range when prices are lowest. |
| `worst_buy` | Month or month range when prices are highest. |
| `note` | 1-2 sentences explaining the pricing pattern. |
| `tip` | Actionable buying advice for the shopper. |

### Typical patterns by plant type

- **Spring-blooming shrubs/perennials:** Peak Apr-May (5), lowest Sep-Oct (1).
- **Trees (shade, flowering, fruit):** Peak Mar-Apr (5), lowest Oct-Nov (1).
- **Evergreens (privacy trees, boxwood):** Peak Mar-May (4-5), lowest Nov-Jan (1-2).
- **Grasses/groundcovers:** Peak Apr-May (5), lowest Sep-Oct (1).

The LLM researches this per-plant. Use the patterns above as sanity
checks, not as copy-paste templates.

---

## Stage 4: Add to plants.json (Inactive)

1. Add the new entry to `data/plants.json` with `"active": false`.
2. Place it near other plants in the same category for readability.
3. Commit with a message like: `Add Pink Muhly Grass to catalog (inactive)`.

Adding as inactive first lets you verify the data without affecting the
live site.

---

## Stage 5: Verification

Before activating, run these checks:

### Data quality checks

- [ ] All required fields present (no nulls where strings expected)
- [ ] `id` is unique across the entire plants.json
- [ ] `id` is kebab-case, lowercase, no special characters
- [ ] `category` matches one of the 13 existing category slugs
- [ ] `zones` is a sorted array of integers within 1-13
- [ ] `zones` range is plausible for the plant (check against USDA data)
- [ ] `sun` uses one of the standard phrases
- [ ] `mature_size` uses "ft" format: `"X-Y ft tall x X-Y ft wide"`
- [ ] `size_tiers` uses the appropriate template for the plant type
- [ ] `planting_seasons` has an entry for every zone in `zones`
- [ ] `planting_seasons` zone keys are strings, not integers
- [ ] `price_seasonality.monthly_index` has exactly 12 integers
- [ ] `price_seasonality.monthly_index` values are 1-5
- [ ] `price_range` is a string like `"$15-$45"`

### Handle map checks

- [ ] Plant ID appears in `data/handle_maps.json` under at least 2 retailers
- [ ] Each handle resolves to a real product page (spot-check with
      `https://{retailer-domain}/products/{handle}`)

### Build check

```bash
python -X utf8 build.py
```

The build must succeed with zero errors. Inactive plants are skipped
by the build (`plants = [p for p in all_plants if p.get("active", True)]`),
so a build pass at this stage just confirms the JSON is valid.

---

## Stage 6: Activation

1. Remove the `"active": false` line (or set to `true`). When the field
   is absent, the build treats the plant as active.
2. Run the build again:
   ```bash
   python -X utf8 build.py
   ```
3. Verify:
   - [ ] Product page exists at `site/plants/{id}.html`
   - [ ] Category page at `site/category/{category}.html` includes the plant
   - [ ] `site/sitemap.xml` includes `/plants/{id}.html`
   - [ ] No build errors or warnings

### Prices

Prices appear after the next scheduled scraper run (2x/day via GitHub
Actions). For faster turnaround, trigger a manual scraper run:

```bash
python -X utf8 -m scrapers.runner --retailer nature-hills --skip-promos
```

Until prices are scraped, the product page renders with a placeholder
("Checking prices...") — this is normal and expected.

---

## Reactivating Inactive Plants

Some plants in `plants.json` are marked `"active": false` because they
previously failed the 2-retailer cut or had data issues.

To reactivate:

1. Run handle discovery to confirm current retailer coverage.
2. If 2+ handles confirm, run the full botanical data extraction.
3. **Update the existing entry** with fresh data — do not trust the old
   values as-is.
4. Remove `"active": false`.
5. Run through Stages 5-6 (verification and activation).

---

## Future Category Expansion Checklist

If a new plant doesn't fit any of the 13 existing categories, a new
category must be created. This is rare — check the list carefully before
deciding a new category is needed.

- [ ] Add new plants to `plants.json` with the new category slug
- [ ] The build auto-generates a category page at
      `site/category/{new-slug}.html` — no build.py changes needed
- [ ] Update nav bar in `templates/base.html` if the category should
      appear in top navigation (currently hardcoded to 4 categories +
      Guides + Heat Map + My List + Improve)
- [ ] Add a `GUIDE_SLUG_TO_CATEGORY` entry in `build.py` if a guide
      article will be written for the category
- [ ] Author a guide article in `articles/` if desired (not required)
- [ ] Sitemap updates are automatic (build generates from active plants)

---

## Quick Reference: Minimal Example Entry

```json
{
  "id": "pink-muhly-grass",
  "common_name": "Pink Muhly Grass",
  "botanical_name": "Muhlenbergia capillaris",
  "aliases": ["Cotton Candy Grass", "Gulf Muhly"],
  "category": "grasses",
  "zones": [6, 7, 8, 9, 10, 11],
  "sun": "Full sun",
  "mature_size": "3-4 ft tall x 3-4 ft wide",
  "bloom_time": "Late summer to fall",
  "type": "Ornamental grass",
  "size_tiers": {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal":  ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal":  ["2 gallon", "2 gal", "#2 container"],
    "3gal":  ["3 gallon", "3 gal", "#3 container"],
    "5gal":  ["5 gallon", "5 gal", "#5 container"]
  },
  "price_range": "$15-$45",
  "image": "",
  "image_credit": "",
  "planting_seasons": {
    "6": { "spring": "Apr-May",  "fall": "Sep-Oct" },
    "7": { "spring": "Mar-Apr",  "fall": "Oct-Nov" },
    "8": { "spring": "Feb-Apr",  "fall": "Oct-Dec" },
    "9": { "spring": "Feb-Mar",  "fall": "Nov-Dec" },
    "10": { "spring": "Jan-Mar", "fall": "Nov-Dec" },
    "11": { "spring": "Year-round", "fall": null }
  },
  "price_seasonality": {
    "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
    "best_buy": "September-October",
    "worst_buy": "April-May",
    "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings.",
    "tip": "Buy in fall, plant in fall. Fall-planted grasses establish root systems over winter and fill in faster the following year."
  },
  "active": false
}
```

Once verified, remove the `"active": false` line to go live.
