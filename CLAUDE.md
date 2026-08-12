# Project Gaia — PlantPriceTracker

## What This Is
Plant price comparison affiliate site. Scrapes 8 online nurseries 2x/day, builds static HTML, deploys to Vercel.
- **Live site**: https://www.plantpricetracker.com
- **GitHub**: https://github.com/ProjectGaiaA/gaia.git
- **72 active plants**, 13 categories, 8 retailers, 103 pages

## Health Check Protocol

**Run this at the start of every session before doing anything else.**

1. Pull latest: `git pull`
2. Read `data/last_manifest.json` — check:
   - `pipeline_status`: should be `"healthy"`. If `"degraded"`, report which retailers and why.
   - `degraded_retailers`: should be empty. If not, list them with context.
   - `timestamp`: should be within the last 36 hours. If older, the scraper pipeline may be down.
3. Check price freshness — pick 3 random JSONL files in `data/prices/`, read the last line of each, check the timestamp is within 3 days.
4. If ANY issues found, report them **before** doing anything else the user asked for. Format:

```
HEALTH CHECK:
- [OK/WARN/FAIL] Pipeline status: healthy|degraded
- [OK/WARN/FAIL] Last scrape: <timestamp> (<N> hours ago)
- [OK/WARN/FAIL] Price freshness: <details>
- [OK/WARN/FAIL] Degraded retailers: none|<list>
```

## Key Commands

```bash
# Build the site (from project root)
python -X utf8 build.py

# Scrape single retailer (for testing)
python -X utf8 -m scrapers.runner --retailer nature-hills --skip-promos

# Verify prices (spot-check against live sites)
python -X utf8 -m scrapers.verify --count 10

# Serve locally
cd site && python -m http.server 8151
```

## Architecture

- `build.py` — Static site generator. Loads plants.json + prices/ JSONL, renders Jinja2 templates to site/
- `scrapers/runner.py` — Orchestrator. Runs each retailer scraper, writes JSONL, saves manifest
- `scrapers/shopify.py` — Shopify JSON/HTML scraper (Nature Hills, PlantingTree, Spring Hill, FGT, PWD, GGP)
- `scrapers/starkbros.py` — Custom scraper for Stark Bros (dataLayer parsing)
- `scrapers/polite.py` — Shared utilities: user-agents, robots.txt, delays
- `scrapers/verify.py` — QA: spot-checks scraped prices against live retailer sites
- `data/plants.json` — Plant catalog (72 active, 5 inactive). `"active": false` = skip in build
- `data/retailers.json` — Retailer configs (URLs, affiliate info, scraper type)
- `data/prices/*.jsonl` — Append-only price history. One file per plant.
- `data/last_manifest.json` — Last scrape run health status (committed to repo)
- `templates/` — Jinja2 templates (base, product, category, guide, home, heat_map, wishlist, improve)
- `site/` — Generated output. Committed to git, and served verbatim (see below)
- `.github/workflows/scrape.yml` — 2x/day scrape + build + commit of `data/` and `site/`

## How a deploy actually happens

There is **no deploy workflow**. `.github/workflows/deploy.yml` was deleted in
`841f767e` ("Remove deploy.yml — failed all 44 runs"). The only workflows left
are `scrape.yml`, `wayback-extract.yml`, and `weekly-recovery-email.yml`.

Deploys are done by **Vercel's own Git integration**, which watches `main` and
publishes on every push. Vercel runs **no build step**: there is no root
`vercel.json` or `package.json` — the only `vercel.json` is inside `site/`,
which means Vercel's root directory is `site/` and it serves those files as-is.

What follows from that, in the order it tends to bite:

1. **The committed `site/` IS the live site.** Reverting a code change alone
   (`build.py`, `templates/`) changes nothing visitors see — the old HTML is
   still sitting in `site/`. A rollback must rebuild and commit `site/` too.
2. **Never hand-edit `site/`.** Regenerate with `python -X utf8 build.py`.
   `git status --short site/` must be empty after a build; if it is not, the
   committed site and the sources it claims to come from have diverged.
3. **The bot deploys twice a day on its own.** `scrape.yml` runs at 11:00 and
   21:30 UTC and commits `data/` **and** `site/`; that push is what triggers
   the next production deploy.
4. `site/vercel.json` caches HTML for 24h and `/assets/*` for 7 days, and asset
   filenames are not fingerprinted — verify a deploy with a cache-busting `?v=N`
   query string, never a plain reload.
5. **To undo a deploy**, the two levers are `git revert` on `main` followed by
   a rebuild+commit of `site/` (the real fix), or promoting the previous
   deployment in the Vercel dashboard (fast, but the next scheduled scrape
   re-publishes `main` over it).

## Best Practices

Maintained in `.claude/best-practices.md`. When you add or change anything related to SEO, scraping ethics, site quality, or CI/CD, update that file to keep the log current.

## Key Decisions
- Inactive plants (`"active": false` in plants.json) are excluded from product pages, sitemap, and category pages but kept in the data file for re-activation
- FGT blocks JSON endpoints — HTML fallback with aria-labels is the primary path
- Brighter Blooms blocks via robots.txt — scraper respects this, their prices will age off
- Price staleness: >30 days = row removed, 3+ consecutive missed scrape runs = "Currently Unavailable"
- Affiliate links use `rel="nofollow sponsored"` per Google guidelines
- Outlier filter: if highest price is 3x+ second-highest in same size tier, it's dropped from savings calculation (catches FGT pack price leaks)
