Read `.claude/CLAUDE.md` and run Phase 1 for this feature:

## Auto-Heal: Detect and Recover Broken Product URLs

### What happened
Our scrape pipeline runs 2x/day across 7 online plant nurseries (all Shopify except Stark Bros). When a retailer changes a product URL slug — which happens when they rename a product, restructure their catalog, or migrate platforms — our scraper starts getting 404s on that product. Currently this fails silently: no new price gets appended, and after 30 days the product ages off the site. Nobody notices until a visitor reports stale data or we manually audit.

We also have a CI step ("Remove broken retailer links") that tries to catch this by HEAD-requesting every retailer URL after each scrape. This is the wrong approach — it hammers retailers with ~500 rapid-fire requests using a bot user-agent, risks IP bans, burns GitHub Actions minutes, and still doesn't fix anything. It just deletes data faster.

### What we want instead
The scraper should detect when a previously-successful product starts 404ing and attempt to automatically find the new URL. We already have `scrapers/discover_handles.py` which searches a retailer's Shopify catalog by product name and returns matching handles with confidence scores. This logic needs to be wired into the scraper's error path so recovery happens inline, not as a separate post-processing step.

### Why this matters
- We're pre-affiliate — getting banned by a retailer before we have API access kills the business
- The link checker step is our highest ban risk (aggressive request pattern, bot UA)
- Manual monitoring doesn't scale — there's one operator (me) and I don't plan to check dashboards
- Stale or missing prices make the site look abandoned, which kills SEO and trust

### What success looks like
- A product URL change gets detected and corrected automatically within 1-2 scrape cycles
- The link checker CI step is removed entirely
- Zero additional HTTP requests beyond what the scraper already makes (no dedicated link-checking pass)
- When auto-recovery fails after N attempts, the system distinguishes "product delisted" from "scraper broken" in the health report
- The 30-day staleness window stays as-is for products that genuinely disappear

### Key context
- `scrapers/discover_handles.py` — existing handle discovery with `match_score` and `normalize_for_matching`
- `scrapers/runner.py` — scraper orchestrator, this is where 404 detection would live
- `scrapers/shopify.py` — Shopify scraper, handles the actual product fetches
- `scrapers/starkbros.py` — Stark Bros uses a different approach (dataLayer), handle discovery may not apply
- `data/last_manifest.json` — health status committed to repo
- `polite.py` — all HTTP must go through polite delays and UA rotation
