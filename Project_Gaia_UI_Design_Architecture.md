# Project Gaia — UI/UX Research & Site Design

## What the Best Price Trackers Share

Analyzed: CamelCamelCamel, Keepa, BrickEconomy, Brickfall, SpoolPrices, Skinflint/Geizhals

### Universal Features (Must-Have)

**1. Price History Charts**
The signature feature of every successful tracker. Visual line graphs showing price over time. Users love seeing trends — "is this a good price right now?" Only answerable with historical context. CamelCamelCamel and Keepa built entire businesses on this single feature.

**2. Price Drop Alerts**
Email notification when a product hits a user-defined price threshold. This is the RETENTION mechanism — it's what brings users back. CamelCamelCamel's Chrome extension has 1M+ active users largely because of alerts. Without alerts, users visit once and leave.

**3. Cross-Retailer Price Table**
Side-by-side pricing from multiple retailers on one page. This is the core value proposition — "where is this cheapest right now?" BrickEconomy and Skinflint do this best. Clean table: Retailer | Price | In Stock | Link.

**4. Simple Search**
Enter a product name, get results instantly. No friction. CamelCamelCamel accepts Amazon URLs directly. For plants, search by cultivar name ("Limelight Hydrangea") or browse by category.

**5. Programmatic Product Pages**
Every product gets its own auto-generated page. Each page targets a long-tail SEO query: "[Product Name] price history" or "[Product Name] best price." BrickEconomy has thousands of these pages — each one ranks for its LEGO set number.

**6. Free to Use**
No paywall. Revenue from affiliate links on outbound clicks to retailers. Every "Buy at [Retailer]" button is an affiliate link.

### What They ALL Lack

**1. No editorial content** — Pure data tools with no buying guides. Limits SEO to people who already know the product name. Misses the "best hydrangeas for shade" searcher entirely.

**2. No discovery pathway** — You must know what you want. No "browse trending," no "what's on sale this week," no category exploration for newcomers.

**3. No domain-specific intelligence** — CamelCamelCamel doesn't know what a product IS, just its price. A plant tracker should know growing zones, sun requirements, mature size — things that matter to the buyer.

**4. Poor mobile experience** — Most are desktop-first. CamelCamelCamel on mobile is painful.

**5. No community signals** — No reviews, no "X people are watching this," no social proof.

---

## Plant Price Tracker — Design Architecture

### Page Types (4 types total)

#### Type 1: Product Comparison Page (auto-generated, ~500+ pages)
**URL pattern:** /plants/limelight-hydrangea
**SEO target:** "buy limelight hydrangea" / "limelight hydrangea price" / "limelight hydrangea for sale"
**Content:**

```
[Hero Image — plant photo]
[Plant Name] — Price Comparison

QUICK FACTS CARD:
├── Zones: 3-9
├── Sun: Full sun to part shade
├── Mature Size: 6-8' × 6-8'
├── Bloom Time: Mid-summer to fall
├── Type: Deciduous shrub
└── Botanical: Hydrangea paniculata 'Limelight'

PRICE COMPARISON TABLE:
┌─────────────────────┬──────────┬───────┬──────────┬────────────┐
│ Retailer            │ 1 Quart  │ 1 Gal │ 3 Gal    │ In Stock?  │
├─────────────────────┼──────────┼───────┼──────────┼────────────┤
│ Fast Growing Trees  │ $30.95   │ $31.95│ $57.95   │ ✓          │
│ Proven Winners      │ $17.84   │ $33.99│ —        │ ✓          │
│ Brighter Blooms     │ $22.99   │ $35.99│ $85.99   │ Qt only    │
│ Nature Hills        │ —        │ $34.99│ $59.99   │ ✓          │
└─────────────────────┴──────────┴───────┴──────────┴────────────┘
Best Price: $17.84 (Proven Winners, 1 Qt)
Savings vs highest: 36%

[PRICE HISTORY CHART — line graph showing price over time per retailer]

[SET PRICE ALERT BUTTON — email when price drops below $X]

[CARE GUIDE — 200 words on how to grow this plant]
[SIMILAR PLANTS — links to Little Lime, Fire Light, Pinky Winky]
```

#### Type 2: Category Page (auto-generated, ~30-50 pages)
**URL pattern:** /category/hydrangeas or /category/fruit-trees
**SEO target:** "buy hydrangeas online" / "fruit trees for sale"
**Content:**
- Grid of plant cards with thumbnail, name, price range, and best current deal
- Filters: growing zone, price range, sun/shade, size at maturity
- Sort by: lowest price, biggest discount, newest, most watched

#### Type 3: Editorial/Guide Page (manually written, 10-20 pages)
**URL pattern:** /guides/best-hydrangeas-for-shade or /guides/cheapest-fruit-trees
**SEO target:** High-volume informational queries
**Content:**
- 1,500-2,000 word buying guide
- Embedded product cards linking to Type 1 pages
- Written once, updated seasonally

**Priority guide topics (trees/shrubs focus for high AOV):**
1. "Best Fruit Trees to Buy Online" ($30-$100 AOV)
2. "Best Japanese Maple Varieties" ($40-$200 AOV)
3. "Best Privacy Trees for Your Yard" ($30-$80 AOV)
4. "Best Hydrangeas for Beginners" ($20-$60 AOV)
5. "When Is the Best Time to Buy Plants Online?" (seasonal authority piece)
6. "Best Flowering Trees for Small Yards"
7. "Cheapest Places to Buy Trees Online" (direct comparison content)
8. "Best Shade Trees for Fast Growth"
9. "Best Rose Bushes for Beginners"
10. "Best Blueberry Bushes to Grow at Home"

#### Type 4: Deals/Alert Page (auto-generated, updated daily)
**URL pattern:** /deals or /deals/this-week
**SEO target:** "plant deals this week" / "nursery sales"
**Content:**
- Auto-generated from price drops detected by scraper
- Shows biggest % drops in last 7 days
- Email digest option (weekly "best plant deals" newsletter)

---

## Plant-Specific Differentiators (What No Generic Tracker Has)

### 1. Growing Zone Filter
Enter your zip code → see only plants that grow in your zone. This is the #1 filter for plant buyers and no comparison site offers it. Zones 3-9 for most plants, but being able to filter out zone-incompatible results is immediately useful.

### 2. Size Normalization
The hardest technical problem: comparing "1 Gallon" at Store A to "#1 Container" at Store B to "Quart" at Store C. Must normalize to standard sizes so price comparison is apples-to-apples. Display price per size tier in columns.

### 3. Stock Status
Show real-time stock availability. A great price on a sold-out plant is worthless. Scrape stock indicators from each retailer.

### 4. Seasonal Intelligence (after 6+ months of data)
"Prices for Limelight Hydrangea are typically 15% lower in September." This becomes possible once you have 6-12 months of price history. It's the "best time to buy" content that no one else can generate because no one else is collecting this data.

### 5. Plant Care Card
Every product page includes a quick-reference care card (zones, sun, water, size). This keeps users on-page longer (good for SEO) and differentiates from a raw price list.

---

## Technical Stack (Keep It Simple)

### For a side project with 1 hr/week maintenance:

**Static site generator** (Hugo or Astro) — generates all product and category pages from JSON data files. No server to maintain. Host on Netlify/Vercel for free.

**Scraper** (Python) — runs daily via GitHub Actions or cron job. Scrapes 4-5 retailers, writes product data to JSON files, triggers site rebuild.

**Price history** — append-only JSON or SQLite file. Each scrape run adds a timestamp + price entry per product per retailer.

**Price alerts** — simple email service (Buttondown or Mailchimp free tier). User enters email + product + threshold. Daily cron checks if any thresholds met, sends email.

**Search** — client-side search via Pagefind or Lunr.js. No backend needed for 500 products.

**Charts** — Chart.js or Recharts. Renders price history from JSON data on page load.

### Build Order:
1. Scraper for Fast Growing Trees + Proven Winners (confirmed scrapable)
2. JSON data schema for products
3. Static site with 10 test product pages
4. Price comparison table component
5. Category pages with filters
6. Price history chart (after 2+ weeks of data)
7. Price alert email system
8. 2-3 editorial guide pages
9. Deploy + submit to Google Search Console
10. Expand to Brighter Blooms + Nature Hills

---

## SEO Strategy

### Phase 1 (Months 1-3): Foundation
- Launch with 50-100 product pages (top cultivars)
- 3-5 editorial guides targeting highest-volume queries
- Submit sitemap to Google Search Console
- Build 5-10 backlinks (gardening forums, Reddit, plant blogs)

### Phase 2 (Months 3-6): Expand
- Scale to 300+ product pages
- Weekly "deals" digest page (auto-generated)
- 5 more editorial guides
- Start collecting price history for seasonal analysis

### Phase 3 (Months 6-12): Authority
- 500+ product pages
- "Best time to buy" content powered by your own price data
- Email newsletter with weekly deals
- Target 10K-20K monthly organic visitors

### Phase 4 (Month 12+): Monetize
- Apply to affiliate programs (Nature Hills, Stark Bros first)
- Add price alert conversion flow
- Optimize top-performing pages for CTR

---

## Competitive Moat

The longer you run, the stronger the moat:
1. **Price history data** — nobody else is collecting this. After 12 months, you have data nobody can replicate without waiting 12 months.
2. **Seasonal intelligence** — "best time to buy" content is locked behind historical data you've collected.
3. **500+ programmatic pages** — each ranking for long-tail queries. A new competitor would need months to build equivalent coverage.
4. **Email subscriber list** — direct relationship with buyers, not dependent on Google.
