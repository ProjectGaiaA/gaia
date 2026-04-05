"""
Wayback Machine CDX API — Historical Price Extractor

One-time historical backfill: queries the Wayback Machine CDX API for archived
snapshots of nursery product pages, fetches each archived page, and extracts
historical prices. Samples one snapshot per month (collapse=timestamp:6) to
keep the run time reasonable.

Targets:
    fast-growing-trees.com  (Shopify — JSON endpoint + HTML fallback)
    naturehills.com         (Shopify — JSON endpoint + HTML fallback)
    starkbros.com           (Apache Wicket — dataLayer extraction)

Usage:
    python -m scrapers.wayback_prices                   # Full backfill
    python -m scrapers.wayback_prices --nursery fast-growing-trees
    python -m scrapers.wayback_prices --plant limelight-hydrangea
    python -m scrapers.wayback_prices --test            # CDX probe: 1 plant × 1 nursery
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Bootstrap sys.path so this runs as a standalone module OR via -m
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.polite import (
    USER_AGENTS, random_ua, polite_headers, polite_delay,
    log_request, is_allowed_by_robots, make_polite_session,
)
from scrapers.shopify import ShopifyScraper, HANDLE_MAPS
from scrapers.starkbros import STARK_BROS_PRODUCTS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_PATH = DATA_DIR / "wayback_prices.json"
PROGRESS_PATH = DATA_DIR / "wayback_progress.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nursery configs — only the three targets in scope
# ---------------------------------------------------------------------------
NURSERY_CONFIGS = {
    "fast-growing-trees": {
        "base_url": "https://www.fast-growing-trees.com",
        "scraper_type": "shopify",
        "handle_map": HANDLE_MAPS.get("fast-growing-trees", {}),
    },
    "nature-hills": {
        "base_url": "https://naturehills.com",
        "scraper_type": "shopify",
        "handle_map": HANDLE_MAPS.get("nature-hills", {}),
    },
    "stark-bros": {
        "base_url": "https://www.starkbros.com",
        "scraper_type": "starkbros",
        "handle_map": {
            plant_id: cfg["slug"] for plant_id, cfg in STARK_BROS_PRODUCTS.items()
        },
        "category_map": STARK_BROS_PRODUCTS,
    },
}

# ---------------------------------------------------------------------------
# Rate limiting — Wayback Machine is polite-but-firmist about 429s
# Minimum 5s between requests, up to 15s for safety
# ---------------------------------------------------------------------------
MIN_DELAY = 5.0
MAX_DELAY = 15.0


def _polite_delay():
    """Random 5-15 second delay between Wayback requests."""
    polite_delay(MIN_DELAY, MAX_DELAY)


def _make_session() -> requests.Session:
    return make_polite_session()


# ---------------------------------------------------------------------------
# Progress tracking (resume support)
# ---------------------------------------------------------------------------

def load_progress() -> set:
    """Return set of already-processed keys: '{plant_slug}:{nursery}:{yyyymm}'."""
    if PROGRESS_PATH.exists():
        try:
            return set(json.loads(PROGRESS_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def save_progress(done: set):
    PROGRESS_PATH.write_text(
        json.dumps(sorted(done), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Output (append-safe)
# ---------------------------------------------------------------------------

def load_output() -> list:
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_output(records: list):
    OUTPUT_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CDX API
# ---------------------------------------------------------------------------

def query_cdx(session: requests.Session, product_url: str) -> list[dict]:
    """Query Wayback CDX API for archived snapshots of a URL.

    Uses collapse=timestamp:6 to return at most one snapshot per YYYYMM.
    Returns list of {timestamp, original} dicts for HTTP 200 responses only.
    """
    cdx_url = (
        "http://web.archive.org/cdx/search/cdx"
        f"?url={product_url}"
        "&output=json"
        "&fl=timestamp,original,statuscode"
        "&filter=statuscode:200"
        "&collapse=timestamp:6"
        "&limit=500"
    )
    for attempt in range(3):
        try:
            resp = session.get(cdx_url, timeout=30)
            log_request(cdx_url, status_code=resp.status_code)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"CDX rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            rows = resp.json()
            # First row is the header ["timestamp","original","statuscode"]
            if not rows or len(rows) < 2:
                return []
            return [
                {"timestamp": r[0], "original": r[1], "statuscode": r[2]}
                for r in rows[1:]
            ]
        except requests.RequestException as e:
            logger.error(f"CDX request failed ({attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(10)
    return []


def fetch_archived_page(session: requests.Session, timestamp: str, original_url: str) -> str | None:
    """Fetch the archived page HTML from Wayback Machine."""
    archive_url = f"https://web.archive.org/web/{timestamp}/{original_url}"
    for attempt in range(3):
        try:
            resp = session.get(archive_url, timeout=30)
            log_request(archive_url, status_code=resp.status_code)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Wayback rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code in (404, 403):
                return None
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"Archived page fetch failed ({attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(10)
    return None


def fetch_archived_json(session: requests.Session, timestamp: str, json_url: str) -> dict | None:
    """Fetch an archived Shopify product JSON endpoint."""
    archive_url = f"https://web.archive.org/web/{timestamp}/{json_url}"
    try:
        resp = session.get(archive_url, timeout=30)
        log_request(archive_url, status_code=resp.status_code)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            logger.warning(f"Wayback JSON rate limited — waiting {wait}s")
            time.sleep(wait)
            resp = session.get(archive_url, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if "product" in data else None
    except (requests.RequestException, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Price extraction helpers — reuse ShopifyScraper parsing logic
# ---------------------------------------------------------------------------

def _shopify_parser(retailer_id: str, base_url: str) -> ShopifyScraper:
    """Create a ShopifyScraper instance for parsing only (no network calls)."""
    return ShopifyScraper(retailer_id, base_url, delay_range=(0, 0))


def extract_shopify_prices(
    session: requests.Session,
    retailer_id: str,
    base_url: str,
    handle: str,
    timestamp: str,
    original_url: str,
) -> list[dict]:
    """Extract prices from an archived Shopify product page.

    Strategy:
    1. Try the archived Shopify JSON endpoint (cleanest data).
    2. Fall back to HTML parsing if JSON is not archived.

    Returns list of flat size records (one per size tier).
    """
    parser = _shopify_parser(retailer_id, base_url)
    archive_url = f"https://web.archive.org/web/{timestamp}/{original_url}"

    # --- Attempt 1: archived JSON endpoint ---
    json_endpoint = f"{base_url}/products/{handle}.json"
    json_data = fetch_archived_json(session, timestamp, json_endpoint)
    _polite_delay()

    if json_data:
        product = parser._parse_product(json_data["product"])
        if product and product.get("sizes"):
            return _flatten_sizes(product["sizes"], archive_url, confidence="high")

    # --- Attempt 2: archived HTML ---
    html = fetch_archived_page(session, timestamp, original_url)
    _polite_delay()

    if not html:
        return []

    product = _parse_shopify_html_text(parser, html, handle, base_url)
    if product and product.get("sizes"):
        return _flatten_sizes(product["sizes"], archive_url, confidence="medium")

    return []


def _parse_shopify_html_text(parser: ShopifyScraper, text: str, handle: str, base_url: str) -> dict | None:
    """Parse prices from already-fetched Shopify HTML (mirrors _scrape_product_html logic)."""
    url = f"{base_url}/products/{handle}"
    sizes = {}
    any_available = False

    # --- aria-label prices (most reliable) ---
    aria_offers = re.findall(
        r'aria-label=\"([^\"]*?)\s*-\s*Sale price:\s*([\d.]+)\s*-\s*List price:\s*\$?([\d.]+)',
        text
    )
    aria_offers = [(n, s, l) for n, s, l in aria_offers
                   if 'pack' not in n.lower()
                   and 'single' not in n.lower()
                   and not re.match(r'^\d+-(?:pack|pk)', n.lower())]

    if aria_offers:
        for size_name, sale_price, list_price in aria_offers:
            tier = parser._normalize_size(size_name)
            sizes[tier] = {
                "price": float(sale_price),
                "was_price": float(list_price) if float(list_price) > float(sale_price) else None,
                "available": True,
                "raw_size": size_name,
            }
        if sizes:
            return {"sizes": sizes, "in_stock": True}

    # --- Schema.org Offer objects ---
    variant_names = {}
    for match in re.finditer(r'ProductVariant/(\d+)\"?,\"([^\"]+?)\"', text):
        vid, name = match.group(1), match.group(2)
        if any(kw in name.lower() for kw in [
            'quart', 'gal', 'gallon', 'ft', 'foot', 'feet', 'pack',
            'bare', 'bulb', 'root', 'inch', 'qt', 'container'
        ]) or re.match(r'^\d+-\d+\s*(ft|feet|foot)', name.lower()):
            variant_names[vid] = name

    offers = re.findall(
        r'\{\"@type\":\"Offer\",\"sku\":\"(\d+)(?:-\w+)?\".*?'
        r'\"price\":\"([\d.]+)\".*?'
        r'\"availability\":\"([^\"]+)\"',
        text
    )

    for sku_raw, price_str, availability in offers:
        sku = sku_raw.split("-")[0]
        if "PACK" in sku_raw.upper():
            continue
        price = float(price_str)
        if price <= 0:
            continue
        in_stock = "InStock" in availability
        if in_stock:
            any_available = True
        size_name = variant_names.get(sku, f"variant-{sku}")
        tier = parser._normalize_size(size_name)
        sizes[tier] = {
            "price": price,
            "was_price": None,
            "available": in_stock,
            "raw_size": size_name,
        }

    if not sizes:
        return None
    return {"sizes": sizes, "in_stock": any_available}


def extract_starkbros_prices(
    session: requests.Session,
    slug: str,
    category: str,
    timestamp: str,
    original_url: str,
) -> list[dict]:
    """Extract prices from an archived Stark Bros product page (dataLayer)."""
    from scrapers.starkbros import StarkBrosScraper

    html = fetch_archived_page(session, timestamp, original_url)
    _polite_delay()

    if not html:
        return []

    archive_url = f"https://web.archive.org/web/{timestamp}/{original_url}"

    datalayer_match = re.search(
        r'dataLayer\.push\((\{"productFamilyList".*?\})\);',
        html, re.DOTALL
    )

    if not datalayer_match:
        # Try JSON-LD fallback
        sizes = _starkbros_jsonld(html)
        if sizes:
            return _flatten_sizes(sizes, archive_url, confidence="medium")
        return []

    try:
        data = json.loads(datalayer_match.group(1))
        family_list = data.get("productFamilyList", [])
        if not family_list:
            return []

        scraper_inst = StarkBrosScraper()
        family = family_list[0]
        sizes = {}
        for product in family.get("availableProducts", []):
            desc = product.get("productDescription", "")
            price = product.get("price", 0)
            if price <= 0:
                continue
            tier = scraper_inst._normalize_variant(desc)
            sizes[tier] = {
                "price": price,
                "was_price": None,
                "available": True,
                "raw_size": desc,
            }
        if sizes:
            return _flatten_sizes(sizes, archive_url, confidence="high")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"dataLayer parse failed for {slug}: {e}")

    return []


def _starkbros_jsonld(html: str) -> dict:
    """Extract pricing from JSON-LD when dataLayer is absent."""
    sizes = {}
    for pattern in [
        r'<script type="application/ld\+json">\s*(\{.*?"@type"\s*:\s*"Product".*?\})\s*</script>',
        r'<script type="application/ld\+json">\s*(\{.*?"@type"\s*:\s*"ItemPage".*?\})\s*</script>',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if not m:
            continue
        try:
            ld = json.loads(m.group(1))
            offers = ld.get("offers", ld.get("mainEntity", {}).get("offers", {}))
            low_price = offers.get("lowPrice")
            if low_price:
                sizes["default"] = {
                    "price": float(low_price),
                    "was_price": None,
                    "available": "InStock" in offers.get("availability", ""),
                    "raw_size": "Best available",
                }
                break
        except (json.JSONDecodeError, KeyError):
            pass
    return sizes


# ---------------------------------------------------------------------------
# Flatten sizes dict → list of flat records
# ---------------------------------------------------------------------------

def _flatten_sizes(sizes: dict, archive_url: str, confidence: str) -> list[dict]:
    """Convert sizes dict {tier: {price, was_price, ...}} to list of flat records."""
    records = []
    for tier, data in sizes.items():
        if tier.startswith("variant-"):
            continue  # Unresolved variant — skip
        price = data.get("price")
        if not price or price <= 0:
            continue
        records.append({
            "size": tier,
            "price": price,
            "regular_price": data.get("was_price"),
            "archive_url": archive_url,
            "confidence": confidence,
        })
    return records


# ---------------------------------------------------------------------------
# Product URL builder
# ---------------------------------------------------------------------------

def build_product_url(nursery_id: str, plant_id: str) -> str | None:
    """Construct the canonical product page URL for a plant at a nursery."""
    cfg = NURSERY_CONFIGS[nursery_id]
    base = cfg["base_url"]

    if nursery_id == "stark-bros":
        entry = STARK_BROS_PRODUCTS.get(plant_id)
        if not entry:
            return None
        return f"{base}/products/{entry['category']}/{entry['slug']}"

    handle = cfg["handle_map"].get(plant_id)
    if not handle:
        return None
    return f"{base}/products/{handle}"


# ---------------------------------------------------------------------------
# Core extraction loop for one (plant, nursery)
# ---------------------------------------------------------------------------

def process_plant_nursery(
    session: requests.Session,
    plant_id: str,
    nursery_id: str,
    done: set,
    all_records: list,
):
    """Fetch CDX snapshots and extract prices for one plant × nursery pair."""
    cfg = NURSERY_CONFIGS[nursery_id]
    product_url = build_product_url(nursery_id, plant_id)
    if not product_url:
        logger.debug(f"  No handle for {plant_id} at {nursery_id} — skipping")
        return

    logger.info(f"  CDX query: {nursery_id} / {plant_id}")
    snapshots = query_cdx(session, product_url)
    _polite_delay()

    if not snapshots:
        logger.info(f"    No archived snapshots found")
        return

    logger.info(f"    Found {len(snapshots)} monthly snapshots")
    new_count = 0

    for snap in snapshots:
        ts = snap["timestamp"]          # e.g. "20230515123456"
        yyyymm = ts[:6]                 # collapse key
        prog_key = f"{plant_id}:{nursery_id}:{yyyymm}"

        if prog_key in done:
            continue

        date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        logger.info(f"    Extracting {date_str}...")

        size_records: list[dict] = []

        if cfg["scraper_type"] == "shopify":
            handle = cfg["handle_map"].get(plant_id, "")
            size_records = extract_shopify_prices(
                session, nursery_id, cfg["base_url"],
                handle, ts, snap["original"]
            )
        elif cfg["scraper_type"] == "starkbros":
            entry = STARK_BROS_PRODUCTS.get(plant_id, {})
            size_records = extract_starkbros_prices(
                session, entry.get("slug", ""), entry.get("category", ""),
                ts, snap["original"]
            )

        for rec in size_records:
            all_records.append({
                "plant_slug": plant_id,
                "nursery": nursery_id,
                "date": date_str,
                **rec,
            })

        done.add(prog_key)
        new_count += 1

        # Persist after each snapshot so we can resume on interrupt
        save_progress(done)
        save_output(all_records)

        if new_count < len(snapshots):
            _polite_delay()

    logger.info(f"    Processed {new_count} new snapshots, extracted {len(size_records)} size records from last")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(nursery_filter: str | None = None, plant_filter: str | None = None):
    plants_path = DATA_DIR / "plants.json"
    plants = json.loads(plants_path.read_text(encoding="utf-8"))
    plant_ids = [p["id"] for p in plants]

    if plant_filter:
        plant_ids = [p for p in plant_ids if p == plant_filter]
        if not plant_ids:
            logger.error(f"Plant '{plant_filter}' not found in plants.json")
            sys.exit(1)

    nursery_ids = list(NURSERY_CONFIGS.keys())
    if nursery_filter:
        if nursery_filter not in NURSERY_CONFIGS:
            logger.error(f"Nursery '{nursery_filter}' not in scope. Choose from: {', '.join(nursery_ids)}")
            sys.exit(1)
        nursery_ids = [nursery_filter]

    done = load_progress()
    all_records = load_output()
    session = _make_session()

    logger.info(f"Starting Wayback backfill: {len(plant_ids)} plants × {len(nursery_ids)} nurseries")
    logger.info(f"Already processed: {len(done)} snapshots, {len(all_records)} records on disk")

    total_pairs = len(plant_ids) * len(nursery_ids)
    pair_num = 0

    for nursery_id in nursery_ids:
        for plant_id in plant_ids:
            pair_num += 1
            logger.info(f"[{pair_num}/{total_pairs}] {nursery_id} / {plant_id}")
            process_plant_nursery(session, plant_id, nursery_id, done, all_records)

    logger.info(f"Done. Total records: {len(all_records)}")
    save_output(all_records)
    save_progress(done)


def run_test():
    """Quick CDX probe: Limelight Hydrangea at fast-growing-trees.com."""
    session = _make_session()
    plant_id = "limelight-hydrangea"
    nursery_id = "fast-growing-trees"
    handle = HANDLE_MAPS["fast-growing-trees"]["limelight-hydrangea"]
    product_url = f"https://www.fast-growing-trees.com/products/{handle}"

    logger.info(f"TEST: CDX query for {product_url}")
    snapshots = query_cdx(session, product_url)

    if not snapshots:
        logger.warning("No snapshots found.")
        return

    logger.info(f"Found {len(snapshots)} monthly snapshots:")
    for snap in snapshots[:10]:  # Show first 10
        ts = snap["timestamp"]
        print(f"  {ts[:4]}-{ts[4:6]}-{ts[6:8]}  {snap['original']}")

    if len(snapshots) > 10:
        print(f"  ... and {len(snapshots) - 10} more")

    # Try extracting prices from the most recent archived snapshot
    # (prefer a 2023-2024 snapshot as very recent ones may not be fully archived yet)
    candidate = next(
        (s for s in reversed(snapshots) if s["timestamp"][:4] in ("2023", "2024")),
        snapshots[-1],
    )
    ts = candidate["timestamp"]
    logger.info(f"\nExtracting prices from snapshot ({ts[:4]}-{ts[4:6]}-{ts[6:8]})...")

    cfg = NURSERY_CONFIGS[nursery_id]
    size_records = extract_shopify_prices(
        session, nursery_id, cfg["base_url"],
        handle, ts, candidate["original"]
    )

    if size_records:
        logger.info(f"Extracted {len(size_records)} size records:")
        for rec in size_records:
            wp = f" (was ${rec['regular_price']})" if rec.get("regular_price") else ""
            print(f"  {rec['size']}: ${rec['price']}{wp}  [{rec['confidence']}]  {rec['archive_url']}")
    else:
        logger.warning("No prices extracted from snapshot.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wayback Machine historical price extractor")
    parser.add_argument("--nursery", help="Limit to one nursery (fast-growing-trees, nature-hills, stark-bros)")
    parser.add_argument("--plant", help="Limit to one plant ID (e.g. limelight-hydrangea)")
    parser.add_argument("--test", action="store_true", help="CDX probe test for Limelight Hydrangea at FGT")
    args = parser.parse_args()

    if args.test:
        run_test()
    else:
        run(nursery_filter=args.nursery, plant_filter=args.plant)
