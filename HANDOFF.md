# Project Gaia — Session Handoff

## What This Is

PlantPriceTracker (www.plantpricetracker.com) — a plant price comparison website that scrapes prices from 8 online nurseries, generates static HTML comparison pages, and monetizes through affiliate links. Built from scratch in Claude Code across 2-3 sessions.

## Current State: LIVE but needs polish

The site is deployed and functional at **plantpricetracker.com** (Vercel + Cloudflare DNS). GitHub Actions CI/CD is configured but not yet tested in production (needs first automated run).

### Data
- **77 plants** across 13 categories (hydrangeas, japanese-maples, fruit-trees, roses, blueberries, privacy-trees, flowering-trees, azaleas-rhododendrons, perennials, houseplants, grasses, groundcovers, shade-trees)
- **1,200 prices** across 8 retailers
- **9 plants at 5+ retailers**, 35 at 3+, 5 at zero coverage
- 5 plants with zero price data: echinacea-powwow-wild-berry, golden-pothos, white-bird-of-paradise, rubber-plant-burgundy, vinca-minor
- Top retailers by price count: PlantingTree (488), Nature Hills (310), Fast Growing Trees (216), Spring Hill (102), Stark Bros (33), Brighter Blooms (27), Proven Winners Direct (16), Great Garden Plants (8)

### Site
- **109 HTML pages** (77 product, 13 category, 10 guide, 1 homepage, heat map, wishlist, improve, disclosure, privacy, guides index, sitemap, Google verification)
- 10 in-depth buying guide articles (V3 versions, 13K-25K bytes each)
- Seasonal pricing chart + zone planting calendar on every product page
- Shipping data per retailer in comparison tables
- Wishlist ("My Plant List") with localStorage persistence
- Heat map (price × planting window)
- Improve/feedback page
- FTC disclosure + privacy policy
- Mobile responsive (5 breakpoints, card layout at ≤600px)

### Infrastructure
- **Domain:** plantpricetracker.com (Cloudflare, ~$11/year)
- **Hosting:** Vercel free tier (gaia-pearl.vercel.app)
- **Repo:** github.com/ProjectGaiaA/gaia (public)
- **CI/CD:** `.github/workflows/scrape.yml` — daily at 7 AM + 5:30 PM ET with random 0-90 min delay
- **Google Search Console:** verified (HTML tag method)

---

## What's Done

### Core Infrastructure
- [x] Python + Jinja2 static site generator (`build.py`)
- [x] Shopify scraper with JSON + HTML fallback + aria-label extraction (`scrapers/shopify.py`)
- [x] Stark Bros custom scraper with dataLayer extraction (`scrapers/starkbros.py`)
- [x] Scraper runner with monitoring, anomaly detection, threshold alerts (`scrapers/runner.py`)
- [x] Polite scraping module — robots.txt checking, delays, logging (`scrapers/polite.py`)
- [x] Price verification script (`scrapers/verify.py`)
- [x] Handle discovery script for bulk handle mapping (`scrapers/discover_handles.py`)
- [x] Promo code scraping (banner + coupon detection)
- [x] Size normalization — 44/44 test cases pass, handles 7 retailer naming conventions
- [x] GitHub Actions workflows (scrape + deploy)
- [x] Vercel deployment with custom domain
- [x] Cloudflare DNS (A record + CNAME)

### Content
- [x] 77 plant database with botanical data, zones, seasons, price seasonality
- [x] 22 retailer configs with affiliate details, shipping, commission rates
- [x] 10 buying guide articles (V3, expanded versions)
- [x] Seasonal pricing intelligence (monthly price index per category)
- [x] Zone-specific planting calendars
- [x] FTC affiliate disclosure page
- [x] Privacy policy page
- [x] Guides index page

### QA Completed
- [x] Price sanity check — 0 bad tiers, 0 variant-XXXXX entries
- [x] Internal link audit — 1 remaining (`/alerts`, future feature)
- [x] Template rendering — 0 issues across 109 pages
- [x] Stock status — unknown retailers show "Check Site" (not false "Sold Out")
- [x] Retailer URL verification — 191 URLs checked, 0 broken, 2 redirects (Stark Bros Bing Cherry)
- [x] Mobile CSS audit — 5 breakpoints, responsive nav, card layout at 600px

---

## What's NOT Done

### High Priority (before considering it "ready")
- [ ] **Sort comparison table by best value** — currently unsorted. Should order by cheapest available price per size tier.
- [ ] **Email signup wall** for seasonal pricing intelligence — the seasonal chart is the most unique content and should gate behind email capture.
- [ ] **Plant photos** — every product page needs a photo. Source from Wikimedia Commons (CC licensed). No retailer images (copyright).
- [ ] **About page** — who we are, mission, why we built this. Brandon wants 25% of profits to land conservation.
- [ ] **Search bar** — Pagefind (client-side search). Critical for 77+ plants.
- [ ] **Fix 2 pages missing viewport meta** — sunny-knock-out-rose.html, sunshine-blue-blueberry.html
- [ ] **Add 3 missing plants to database** — chandler-blueberry, serviceberry, bobo-hydrangea (referenced in articles)
- [ ] **5-expert UI critique** — run after photos are added. Perspectives: e-commerce UX, SEO, mobile, accessibility, consumer trust.

### Medium Priority
- [ ] **Price history charts** — need accumulated data (Chart.js is wired, just no multi-day data yet)
- [ ] **Per-zone best-time-to-buy** — heat map showing intersection of price + planting viability per zone
- [ ] **Expand to 16 more plants** from Brandon's list (Fiddle Leaf Fig, Monstera, Autumn Blaze Maple, Miss Kim Lilac, Dwarf Alberta Spruce, etc.)
- [ ] **Add The Tree Center + Wilson Bros Gardens** as retailers (both need custom scrapers — WooCommerce and custom platform)
- [ ] **Formspree integration** for Improve page (needs signup + form ID)
- [ ] **Canonical tags** on all pages (template supports it, build.py needs to pass URLs)
- [ ] **www vs non-www canonical** — pick one, set up 301 redirect in Vercel

### Low Priority
- [ ] **Apply to affiliate programs** — ShareASale (Nature Hills 10%), Stark Bros (Impact 10%), Spring Hill (Sovrn 15%)
- [ ] **Google Trends integration** for trending plants
- [ ] **Historical pricing via Wayback Machine** — Burpee has 500 snapshots, Nature Hills has 860. Sparse but possible for "best time to buy" seeding.
- [ ] **Browser extension** — price overlay on retailer pages
- [ ] **Weekly "Plant Deal Roundup" email**

---

## Key Decisions Made

### Business
1. **Plants won over 41 other niches** — espresso equipment scored highest on paper but MAP pricing kills the value proposition. Plants work because nurseries price independently (24% verified spread).
2. **Affiliate revenue model** — Nature Hills 10%, Stark Bros 10%, Spring Hill 15%, PlantingTree 7%, FGT 6%. DoMyOwn 6% with 90-day cookie for garden supplies cross-sell.
3. **Include non-affiliate retailers** for trust — Brighter Blooms, Great Garden Plants, Proven Winners Direct shown even though they don't pay us. Brandon: "deliver value, not just focus on money."
4. **Realistic revenue expectations** — $30-50/mo at month 12, $200-300/mo at month 24. This is a data moat investment, not quick money.
5. **Domain:** plantpricetracker.com ($11/yr Cloudflare). Covers plants, bulbs, seeds, supplies — not limiting.

### Technical
1. **Python + Jinja2** over Astro/Hugo/Next.js — Brandon knows Python, no new toolchain, static HTML output.
2. **JSONL price files** (not SQLite) — append-only, git-friendly, human-readable.
3. **Aria-labels preferred over schema.org Offers** for FGT — schema.org includes pack prices under same SKU. Aria-labels clearly separate singles from packs.
4. **Shopify JSON endpoints tried first**, HTML fallback if 404 — most stores work with JSON (Nature Hills, PlantingTree, Spring Hill, PWD, GGP). FGT blocks JSON.
5. **`?variant=ID` deep links** — prevents retailers defaulting to 3-pack or jumbo view.
6. **Stock status: `None` for unknown** — retailers without `available` field in JSON show "Check Site" not "Sold Out."
7. **Public GitHub repo** with generic name (`gaia`) — code isn't the moat, data is.
8. **Scrape max 2x/day** — 7 AM + 5:30 PM ET. Random 0-90 min delay per run. During development, test on ONE product, not full catalog.

### Content
1. **Editorial articles go first** for SEO — product pages added incrementally. Don't launch 500 pages day one.
2. **Seasonal intelligence is the email gate** — free: price table. Email required: seasonal chart, best time to buy, zone calendar.
3. **Trees and shrubs ($30-200) drive revenue** — not annuals ($3-5). Focus AOV on high-ticket items.

---

## Known Issues & Gotchas

### Scraper Issues
- **FGT blocks Shopify JSON endpoints** — must use HTML fallback (aria-labels or schema.org Offers)
- **FGT uses same SKU for singles and packs** — aria-labels must be preferred; schema.org grabs pack prices
- **Spring Hill has Size × Quantity × Season variant matrix** — filter to "1 Plant(s)" only; "Ships in Spring/Fall" = available for order
- **Nature Hills handle format is inconsistent** — some genus-first (`hydrangea-lime-light`), some common-name-first (`bloodgood-japanese-maple`). Verify every handle individually.
- **Shopify `available` field often missing** — PlantingTree, GGP, Nature Hills, PWD don't include it. Default to `None` (unknown), not `False` (sold out).
- **We over-scraped during development** (~10+ full runs in one day). Production limit: 2x/day max. Test changes on single products.

### Data Issues
- 5 plants have zero price data (mostly new houseplants — need handle discovery)
- Crape Myrtle $782 price was a pack price that leaked through (may recur with FGT's HTML extraction)
- Some FGT products still have unresolved variant tiers — stripped automatically during build

### Site Issues
- `/alerts` page referenced in one article but doesn't exist (future feature)
- 2 pages missing viewport meta tag (sunny-knock-out-rose, sunshine-blue-blueberry)
- Guides index page generated as one-off script, not integrated into build.py
- No canonical URLs set on pages yet (template supports it, build.py doesn't pass them)

---

## File Structure

```
project_gaia/
├── build.py                    # Static site generator (reads data → renders HTML)
├── data/
│   ├── plants.json             # 77 plant canonical database
│   ├── retailers.json          # 22 retailer configs (affiliates, shipping, scraper type)
│   ├── prices/                 # JSONL price history, one file per plant
│   ├── promos.json             # Scraped promo codes per retailer
│   ├── last_manifest.json      # Last scrape run stats
│   └── images/                 # Plant images (empty — need to source)
├── scrapers/
│   ├── shopify.py              # Shopify scraper (JSON + HTML fallback + handle maps)
│   ├── starkbros.py            # Stark Bros custom scraper (dataLayer extraction)
│   ├── runner.py               # Orchestrator with monitoring + promo scraping
│   ├── verify.py               # Price accuracy + link verification
│   ├── discover_handles.py     # Bulk handle discovery via /products.json
│   └── polite.py               # Polite scraping (delays, robots.txt, UA rotation)
├── templates/
│   ├── base.html               # Shared layout (nav, footer, disclosure, wishlist JS)
│   ├── product.html            # Product comparison page
│   ├── category.html           # Category listing with zone filter + sorting
│   ├── guide.html              # Editorial article with FAQ schema
│   ├── home.html               # Homepage (hero, categories, guides, heat map CTA)
│   ├── heat_map.html           # Price × planting timing heat map
│   └── wishlist.html           # My Plant List page
├── site/                       # Generated output (deployed to Vercel)
│   ├── index.html
│   ├── plants/*.html           # 77 product pages
│   ├── category/*.html         # 13 category pages
│   ├── guides/*.html           # 10 guide pages + index
│   ├── assets/css/style.css    # All CSS (16K+ bytes, 5 breakpoints)
│   ├── assets/js/wishlist.js   # Wishlist localStorage logic
│   ├── heat-map.html, my-list.html, improve.html
│   ├── disclosure.html, privacy.html
│   ├── sitemap.xml, robots.txt
│   └── vercel.json             # Vercel routing config
├── 01-10*.md                   # Article markdown source files (V3)
├── .github/workflows/
│   ├── scrape.yml              # Daily scrape + verify + build + commit
│   └── deploy.yml              # Auto-deploy on push to main
├── QA_PLAN.md                  # Quality assurance documentation
├── HANDOFF.md                  # This file
├── requirements.txt            # requests, jinja2, markdown
└── .gitignore
```

---

## Commands to Pick Up From

### Run the site locally
```bash
cd "C:\Users\BrandonHall\OneDrive - YA\Documents\CC\project_gaia\site"
python -m http.server 8151
# Visit http://localhost:8151
```

### Rebuild the site (after changing data or templates)
```bash
cd "C:\Users\BrandonHall\OneDrive - YA\Documents\CC\project_gaia"
python -X utf8 build.py
```

### Scrape a single retailer (for testing — ONE at a time during dev)
```bash
python -X utf8 -m scrapers.runner --retailer nature-hills
```

### Scrape a single product (safest for development)
```bash
python -X utf8 -c "
from scrapers.shopify import ShopifyScraper
s = ShopifyScraper('nature-hills', 'https://naturehills.com')
result = s.scrape_product('hydrangea-lime-light')
print(result)
"
```

### Run QA verification
```bash
python -X utf8 -m scrapers.verify --count 10     # Price spot-check
python -X utf8 -m scrapers.verify --plant limelight-hydrangea  # Specific plant
```

### Discover handles for unmapped plants
```bash
python -X utf8 -m scrapers.discover_handles --retailer nature-hills --dry-run
```

### Push changes to live site
```bash
cd "C:\Users\BrandonHall\OneDrive - YA\Documents\CC\project_gaia"
git add -A
git commit -m "description of changes"
git push
# Vercel auto-deploys from main branch
```

### Run the dashboard
```bash
cd "C:\Users\BrandonHall\OneDrive - YA\Documents\CC\dashboard"
python server.py
# Visit http://localhost:8150, select "Project Gaia"
```

---

## Best Practices File

All scraper lessons learned are documented in:
`C:\Users\BrandonHall\.claude\projects\C--Users-BrandonHall-OneDrive---YA-Documents-CC\memory\feedback_project_gaia.md`

Key rules:
- **Never scrape more than 2x/day** in production
- **Test scraper changes on ONE product**, not full catalog
- **Verify every handle via JSON endpoint** before adding to HANDLE_MAPS
- **Aria-labels preferred over schema.org** for FGT (pack price issue)
- **Default stock status to None (unknown)** when `available` field is missing
- **Polite delays: 5-12 seconds** between requests (Stark Bros: 6-15s per robots.txt)
- **Strip variant-XXXXX tiers** before building site
- **Best-price highlighting only for in-stock retailers**

---

## Affiliate Revenue Summary

| Retailer | Commission | Cookie | Status |
|----------|-----------|--------|--------|
| Spring Hill | 15% | ~30d | Not yet applied |
| Nature Hills | 10% | 30d | Not yet applied (ShareASale) |
| Stark Bros | 10% | 30d | Not yet applied (Impact) |
| Plant Addicts | 10% | ~30d | Not yet applied (Awin) |
| Wayside Gardens | 8-10% | ~30d | Not yet applied (Awin) |
| PlantingTree | 7% | 30d | Not yet applied (ShareASale) |
| Fast Growing Trees | 6% | 30d | Not yet applied (Impact) |
| DoMyOwn | 6% | 90d | Not yet applied (garden supplies cross-sell) |

**Apply AFTER the site has 10-15 good content pages and looks professional.** Nature Hills via ShareASale is the easiest approval. Hold Amazon for month 3-4 (3-sale requirement in 180 days).
