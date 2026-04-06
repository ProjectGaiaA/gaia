"""
Price Verification — Spot-checks scraped prices against live retailer sites.

Picks a random sample of products, re-scrapes them individually,
and compares against stored prices. Flags any mismatches.

Run after every scrape to confirm data accuracy.

Usage:
    python -m scrapers.verify                    # Check 5 random products
    python -m scrapers.verify --count 10         # Check 10
    python -m scrapers.verify --plant limelight-hydrangea  # Check specific plant
"""

import argparse
import glob
import json
import logging
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.shopify import ShopifyScraper, get_handles_for_retailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PRICES_DIR = DATA_DIR / "prices"

PRICE_TOLERANCE = 0.02  # 2% tolerance for rounding differences


def load_stored_prices(plant_id: str) -> dict:
    """Load the most recent stored price per retailer for a plant."""
    path = PRICES_DIR / f"{plant_id}.jsonl"
    if not path.exists():
        return {}

    # Get latest entry per retailer
    latest = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            rid = entry.get("retailer_id", "")
            latest[rid] = entry
    return latest


def verify_plant(plant_id: str, retailers: list[dict]) -> dict:
    """Re-scrape one plant from one random retailer and compare."""
    stored = load_stored_prices(plant_id)
    if not stored:
        return {"plant_id": plant_id, "status": "no_data", "message": "No stored prices"}

    # Pick a random retailer that has stored data AND is Shopify
    shopify_retailers = {
        rid: r for r in retailers for rid in [r["id"]]
        if rid in stored and r.get("scraper_type") == "shopify"
    }

    if not shopify_retailers:
        return {"plant_id": plant_id, "status": "skip", "message": "No Shopify retailers with stored data"}

    rid = random.choice(list(shopify_retailers.keys()))
    retailer = shopify_retailers[rid]
    stored_entry = stored[rid]
    stored_sizes = stored_entry.get("sizes", {})

    # Get the handle for this plant at this retailer
    all_plant_ids = [plant_id]
    handle_map = get_handles_for_retailer(rid, all_plant_ids)
    if plant_id not in handle_map:
        return {"plant_id": plant_id, "status": "skip", "message": f"No handle for {rid}"}

    handle = handle_map[plant_id]

    # Re-scrape
    scraper = ShopifyScraper(rid, retailer["url"])
    fresh = scraper.scrape_product(handle)

    if not fresh:
        return {
            "plant_id": plant_id,
            "retailer": rid,
            "status": "error",
            "message": f"Re-scrape failed for {handle} at {rid}",
        }

    fresh_sizes = fresh.get("sizes", {})

    # Compare prices
    mismatches = []
    matches = 0

    for tier, stored_data in stored_sizes.items():
        stored_price = stored_data.get("price", 0) if isinstance(stored_data, dict) else 0
        if stored_price <= 0:
            continue

        if tier in fresh_sizes:
            fresh_price = fresh_sizes[tier].get("price", 0) if isinstance(fresh_sizes[tier], dict) else 0
            if fresh_price <= 0:
                continue

            diff_pct = abs(fresh_price - stored_price) / stored_price
            if diff_pct > PRICE_TOLERANCE:
                mismatches.append({
                    "tier": tier,
                    "stored": stored_price,
                    "fresh": fresh_price,
                    "diff_pct": round(diff_pct * 100, 1),
                })
            else:
                matches += 1
        # If tier is in stored but not in fresh, could be a sold-out size — not a mismatch

    status = "PASS" if not mismatches else "MISMATCH"

    return {
        "plant_id": plant_id,
        "retailer": rid,
        "status": status,
        "matches": matches,
        "mismatches": mismatches,
        "stored_tiers": len(stored_sizes),
        "fresh_tiers": len(fresh_sizes),
    }


def main():
    parser = argparse.ArgumentParser(description="Verify scraped prices against live sites")
    parser.add_argument("--count", type=int, default=5, help="Number of random products to verify")
    parser.add_argument("--plant", type=str, help="Verify a specific plant ID")
    args = parser.parse_args()

    retailers = json.loads((DATA_DIR / "retailers.json").read_text(encoding="utf-8"))
    active_retailers = [r for r in retailers if r.get("active")]

    if args.plant:
        plant_ids = [args.plant]
    else:
        # Pick random plants that have price data
        plants_with_data = []
        for f in glob.glob(str(PRICES_DIR / "*.jsonl")):
            plant_id = os.path.basename(f).replace(".jsonl", "")
            if os.path.getsize(f) > 10:
                plants_with_data.append(plant_id)
        plant_ids = random.sample(plants_with_data, min(args.count, len(plants_with_data)))

    logger.info(f"Verifying {len(plant_ids)} products against live retailer sites...\n")

    results = []
    passed = 0
    failed = 0
    errors = 0

    for plant_id in plant_ids:
        result = verify_plant(plant_id, active_retailers)
        results.append(result)

        status = result["status"]
        rid = result.get("retailer", "?")

        if status == "PASS":
            passed += 1
            matches = result.get("matches", 0)
            logger.info(f"  PASS  {plant_id} @ {rid} — {matches} prices verified")
        elif status == "MISMATCH":
            failed += 1
            for m in result.get("mismatches", []):
                logger.warning(
                    f"  FAIL  {plant_id} @ {rid} — {m['tier']}: "
                    f"stored ${m['stored']:.2f} vs live ${m['fresh']:.2f} ({m['diff_pct']}% diff)"
                )
        elif status == "error":
            errors += 1
            logger.error(f"  ERR   {plant_id} — {result.get('message', '')}")
        else:
            logger.info(f"  SKIP  {plant_id} — {result.get('message', '')}")

    logger.info(f"\n{'='*50}")
    logger.info("VERIFICATION SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"  Checked: {len(plant_ids)}")
    logger.info(f"  Passed:  {passed}")
    logger.info(f"  Failed:  {failed}")
    logger.info(f"  Errors:  {errors}")

    if failed > 0:
        logger.warning(f"\n{failed} price mismatches detected — data may be stale!")
        sys.exit(1)
    else:
        logger.info("\nAll verified prices match. Data is accurate.")


if __name__ == "__main__":
    main()
