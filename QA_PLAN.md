# Project Gaia — Quality Assurance Plan

## Phase 1: Data Integrity (Before UI Review)

### Test 1: Link Verification
Every product URL in our price data must return HTTP 200 and land on the correct product page.

**How it works:**
1. For each entry in `data/prices/*.jsonl`, extract the `url` field
2. Send HTTP HEAD request to the URL
3. Verify HTTP 200 response (not 301 redirect to homepage, not 404)
4. For Shopify stores: verify the response URL still contains `/products/`
5. Flag any URL that returns non-200 or redirects to a non-product page

**Script:** `scrapers/verify.py --links`
**Frequency:** After every scrape (2x daily)
**Failure action:** Suppress that retailer's entry from the comparison table until handle is fixed

### Test 2: Price Accuracy
Scraped prices must match what the retailer actually shows on their website.

**How it works:**
1. Pick 10 random products from the price database
2. For each, pick a random retailer that has a stored price
3. Re-scrape that single product from the retailer
4. Compare stored price vs fresh price
5. Flag any mismatch > 2% (allows for rounding)

**Script:** `scrapers/verify.py --prices --count 10`
**Frequency:** After every scrape (2x daily)
**Failure action:** If >20% of checks fail, halt the build pipeline and alert

### Test 3: Product-to-Link Match
The plant shown on the retailer's page must actually BE the plant we think it is.

**How it works:**
1. For each retailer entry, fetch the product page
2. Extract the product title from the HTML (`<title>` tag or `og:title` meta)
3. Fuzzy-match the extracted title against our canonical plant name
4. Flag any match score below 0.5 (likely wrong product)

**Example catches:**
- Our "Limelight Hydrangea" linking to a "Limelight Prime Hydrangea" (different cultivar)
- Our "Endless Summer" linking to "Summer Crush" (different variety)
- Our "Knock Out Rose" linking to "Easy Bee-zy Knock Out Rose" (different color)

**Script:** `scrapers/verify.py --product-match`
**Frequency:** Weekly (more expensive — fetches every URL)
**Failure action:** Flag mismatched product for manual review

### Test 4: Internal Site Links
Every link on our generated website must point to a page that exists.

**How it works:**
1. Crawl every HTML file in `site/`
2. Extract all `href` attributes
3. For internal links (`/plants/...`, `/category/...`, `/guides/...`), verify the target file exists
4. For external links (retailer URLs), verify via HTTP HEAD

**Script:** `scrapers/verify.py --site-links`
**Frequency:** After every build
**Failure action:** Build fails if any internal link is broken

### Test 5: Price Sanity Check
No scraped price should be obviously wrong.

**How it works:**
1. Check every price in the database
2. Flag: price > $500 for shrubs/perennials (likely a pack price)
3. Flag: price > $1000 for any product (almost certainly wrong)
4. Flag: price < $3 for any product (suspiciously low)
5. Flag: was_price <= current price (bad discount data)
6. Flag: variant-XXXXX tier names (unresolved variants)

**Script:** `scrapers/verify.py --sanity`
**Frequency:** After every scrape
**Failure action:** Strip bad entries before build

### Test 6: Stock Status Honesty
Don't show "Sold Out" unless we're confident. Don't show "In Stock" unless confirmed.

**How it works:**
1. For retailers that DON'T include `available` in their JSON (PlantingTree, GGP, Nature Hills, PWD): show "Check Site"
2. For retailers that DO include `available` (FGT, Spring Hill, Stark Bros): trust the field
3. For "Ships in Spring/Fall" variants: show "In Stock (Ships Fall)" not just "In Stock"

**Verification:** Spot-check 5 random "Sold Out" entries by visiting the retailer site manually

---

## Automated QA Pipeline (GitHub Actions)

```yaml
# .github/workflows/qa.yml
# Runs after every scrape

name: QA Pipeline
on:
  workflow_run:
    workflows: ["Daily Scrape"]
    types: [completed]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Price Sanity Check
        run: python -m scrapers.verify --sanity

      - name: Price Accuracy (10 random)
        run: python -m scrapers.verify --prices --count 10

      - name: Link Verification
        run: python -m scrapers.verify --links

      - name: Build Site
        if: success()
        run: python build.py

      - name: Internal Link Check
        run: python -m scrapers.verify --site-links

      - name: Deploy
        if: success()
        run: vercel deploy --prod
```

**If ANY verification step fails, the build and deploy are skipped.** Bad data never goes live.

---

## Phase 2: UI Review (After Data is Locked)

### Prerequisites
- [ ] All product photos sourced (Wikimedia Commons / public domain)
- [ ] All 78 plants have 3+ retailer coverage
- [ ] All links verified working
- [ ] All prices verified accurate
- [ ] Mobile responsive verified
- [ ] Disclosure + privacy pages complete

### 5-Expert UI Critique
Run 5 expert perspectives on the live site:

1. **E-Commerce UX Specialist** — conversion flow, CTA placement, trust signals, comparison table usability
2. **SEO Specialist** — page structure, schema markup, internal linking, content quality
3. **Mobile UX Designer** — responsive layout, touch targets, table scrolling on small screens
4. **Accessibility Expert** — color contrast, screen reader compatibility, keyboard navigation, ARIA labels
5. **Consumer Trust Analyst** — does the site feel trustworthy? Would you enter your email? Would you click an affiliate link?

Each expert reviews:
- Homepage
- 3 product comparison pages (one with lots of data, one sparse, one sold-out)
- 1 category page
- 1 guide article
- Mobile view of all above

---

## Phase 3: Ongoing Monitoring

### Daily Automated Checks
- Price accuracy spot-check (10 random)
- Link verification (all URLs)
- Price sanity check (thresholds)
- Build + deploy only if all pass

### Weekly Manual Checks
- Product-to-link match verification (all URLs)
- Review scraper error logs for silent failures
- Check for new products at retailers (handle discovery for new additions)
- Check affiliate program status (any terminated?)

### Monthly
- Full price audit (compare ALL stored prices vs live sites)
- Review coverage report (any plants dropping below 3 retailers?)
- Check Google Search Console for crawl errors
- Review analytics for user behavior patterns
