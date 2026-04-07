# Best Practices Implemented

Updated: 2026-04-07

## SEO Foundation

- **Canonical tags** -- self-referencing on 108/109 pages. Prevents duplicate content penalties.
- **www redirect** -- 301 non-www to www. Single canonical domain for link equity.
- **robots.txt** -- allows all crawlers, points to sitemap.
- **XML sitemap** -- all pages listed, auto-regenerated on build.
- **Google Search Console** -- verified via HTML meta tag.
- **No noindex tags** -- audited, all pages indexable.
- **Title tag optimization** -- unique, keyword-rich titles under 60 chars on all 103 pages. Includes year for freshness.
- **Product schema (JSON-LD)** -- Product + AggregateOffer on 72 plant pages. Enables Google rich snippets (price range, availability). Validated in Rich Results Test.
- **Breadcrumb schema** -- BreadcrumbList on all product pages with fully qualified URLs. Zero warnings in Rich Results Test.
- **Sort by best value** -- price comparison tables sorted cheapest first. Sold-out retailers at bottom.
- **Internal linking** -- every product page links to its category, related guide, and 5 similar plants. Every category links to its guide. Guides mapped via centralized constant.
- **Similar Plants sort** -- zone overlap first, then cheapest price. Users see most relevant plants first.

## Scraping Ethics

- **robots.txt compliance** -- checked before every request, disallowed URLs skipped.
- **Polite delays** -- 5-15 sec random delay between requests. Never hammers a site.
- **Random start offset** -- 0-90 min jitter on CI runs. No fixed-time traffic spikes.
- **Real browser UAs** -- 10 rotating user-agent strings. Honest traffic pattern.
- **Retailer opt-out respected** -- Brighter Blooms blocks via robots.txt, scraper honors it.

## Site Quality

- **FTC disclosure** -- affiliate links use rel="nofollow sponsored". Disclosure page linked site-wide.
- **Broken link checker** -- runs in CI pipeline, removes stale retailer URLs automatically.
- **Price verification** -- 10 random spot checks per scrape run against live sites.
- **Outlier filter** -- prices 3x+ above second-highest in tier are dropped from savings calc.
- **Staleness cutoff** -- prices older than 30 days auto-removed. No stale data shown to users.
- **Mobile responsive** -- card layout at 600px breakpoint.
- **Privacy page** -- no cookies, no tracking, extends base template.
- **Contact form** -- Formspree (no backend), 50 submissions/month free tier.
- **Stale page cleanup** -- build.py removes orphan HTML pages from deactivated plants. No dead pages in site output.
- **Zero-price schema guard** -- plants with no prices omit Product schema entirely. No invalid structured data.

## CI/CD & Testing

- **210 automated tests** -- 138 build + 71 scraper + 1 discover.
- **2x daily scrape** -- GitHub Actions cron at 7AM + 5:30PM ET.
- **Auto-deploy** -- Vercel deploys on push to main.
- **Graceful degradation** -- individual scraper failures don't block build/deploy.
- **Internal link checker** -- verifies all hrefs resolve after build.
