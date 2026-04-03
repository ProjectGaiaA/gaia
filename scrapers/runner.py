"""
Scraper Runner — Orchestrates daily price collection across all retailers.

Runs each retailer's scraper, writes results to JSONL price files,
generates a monitoring manifest, and flags anomalies.

Usage:
    python -m scrapers.runner                    # Scrape all active retailers
    python -m scrapers.runner --retailer fast-growing-trees  # Single retailer
    python -m scrapers.runner --dry-run          # Show what would be scraped
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.shopify import ShopifyScraper, get_handles_for_retailer
from scrapers.starkbros import StarkBrosScraper, STARK_BROS_PRODUCTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PRICES_DIR = DATA_DIR / "prices"
MANIFEST_PATH = DATA_DIR / "last_manifest.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_price(plant_id: str, price_entry: dict):
    """Append a price entry to the plant's JSONL file."""
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PRICES_DIR / f"{plant_id}.jsonl"
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(price_entry, ensure_ascii=False) + "\n")


def load_previous_manifest() -> dict:
    """Load the last scrape manifest for anomaly detection."""
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def check_price_anomaly(plant_id: str, retailer_id: str, new_prices: dict, prev_manifest: dict) -> list[str]:
    """Check for suspicious price changes (>50% swing)."""
    warnings = []
    prev_key = f"{plant_id}:{retailer_id}"
    prev_prices = prev_manifest.get("prices", {}).get(prev_key, {})

    for tier, new_data in new_prices.items():
        new_price = new_data.get("price", 0) if isinstance(new_data, dict) else 0
        old_price = prev_prices.get(tier, 0)

        if old_price > 0 and new_price > 0:
            change_pct = abs(new_price - old_price) / old_price * 100
            if change_pct > 50:
                warnings.append(
                    f"ANOMALY: {plant_id} at {retailer_id} tier={tier}: "
                    f"${old_price:.2f} -> ${new_price:.2f} ({change_pct:.0f}% change)"
                )
    return warnings


def scrape_retailer(retailer: dict, plant_ids: list[str], prev_manifest: dict, dry_run: bool = False) -> dict:
    """Scrape a single retailer for all mapped plants.

    Returns a manifest entry with stats.
    """
    retailer_id = retailer["id"]
    scraper_type = retailer.get("scraper_type", "")

    # Handle Stark Bros custom scraper
    if retailer_id == "stark-bros":
        products_to_scrape = [
            {"plant_id": pid, **info}
            for pid, info in STARK_BROS_PRODUCTS.items()
            if pid in plant_ids
        ]
        if not products_to_scrape:
            return {"retailer_id": retailer_id, "status": "skipped", "reason": "no products mapped"}

        logger.info(f"  Scraping {retailer_id}: {len(products_to_scrape)} products (custom scraper)")
        if dry_run:
            for item in products_to_scrape:
                logger.info(f"    [dry-run] {item['plant_id']} -> {item['slug']}")
            return {"retailer_id": retailer_id, "status": "dry_run", "products_mapped": len(products_to_scrape)}

        scraper = StarkBrosScraper()
        scraped = scraper.scrape_products(products_to_scrape)

        products_found = len(scraped)
        prices_collected = 0
        price_records = {}
        for plant_id, result in scraped:
            sizes = result.get("sizes", {})
            prices_collected += len(sizes)
            price_entry = {
                "retailer_id": retailer_id,
                "retailer_name": result.get("retailer_name", "Stark Bros"),
                "timestamp": result["timestamp"],
                "url": result.get("url", ""),
                "sizes": sizes,
                "in_stock": result.get("in_stock", None),
            }
            append_price(plant_id, price_entry)
            for tier, data in sizes.items():
                price_val = data.get("price", 0) if isinstance(data, dict) else 0
                price_records[f"{plant_id}:{retailer_id}"] = price_records.get(f"{plant_id}:{retailer_id}", {})
                price_records[f"{plant_id}:{retailer_id}"][tier] = price_val

        return {
            "retailer_id": retailer_id,
            "status": "completed",
            "products_expected": len(products_to_scrape),
            "products_found": products_found,
            "products_error": len(products_to_scrape) - products_found,
            "prices_collected": prices_collected,
            "anomalies": [],
            "price_records": price_records,
        }

    if scraper_type != "shopify":
        logger.info(f"  Skipping {retailer_id} — custom scraper not yet implemented")
        return {
            "retailer_id": retailer_id,
            "status": "skipped",
            "reason": "custom scraper not implemented",
        }

    # Get handle mappings for this retailer
    handle_map = get_handles_for_retailer(retailer_id, plant_ids)
    if not handle_map:
        logger.info(f"  Skipping {retailer_id} — no plant handle mappings defined")
        return {
            "retailer_id": retailer_id,
            "status": "skipped",
            "reason": "no handle mappings",
        }

    logger.info(f"  Scraping {retailer_id}: {len(handle_map)} products")

    if dry_run:
        for plant_id, handle in handle_map.items():
            logger.info(f"    [dry-run] {plant_id} -> {handle}")
        return {
            "retailer_id": retailer_id,
            "status": "dry_run",
            "products_mapped": len(handle_map),
        }

    # Create scraper and run
    scraper = ShopifyScraper(retailer_id, retailer["url"])
    handles_list = list(handle_map.values())
    plant_ids_list = list(handle_map.keys())

    results = scraper.scrape_products(handles_list)

    # Process results
    products_found = 0
    products_error = 0
    prices_collected = 0
    anomalies = []
    price_records = {}

    for i, result in enumerate(results):
        plant_id = plant_ids_list[i]

        if result.get("error"):
            products_error += 1
            logger.warning(f"    Error: {plant_id} — {result['error']}")
            continue

        products_found += 1
        sizes = result.get("sizes", {})
        prices_collected += len(sizes)

        # Check for anomalies
        anomaly_warnings = check_price_anomaly(plant_id, retailer_id, sizes, prev_manifest)
        anomalies.extend(anomaly_warnings)
        for w in anomaly_warnings:
            logger.warning(f"    {w}")

        # Write price entry to JSONL (skip if anomaly detected)
        if not anomaly_warnings:
            price_entry = {
                "retailer_id": retailer_id,
                "retailer_name": result.get("retailer_name", retailer["name"]),
                "timestamp": result["timestamp"],
                "url": result.get("url", ""),
                "sizes": sizes,
                "in_stock": result.get("in_stock", None),
            }
            append_price(plant_id, price_entry)

            # Record for manifest
            for tier, data in sizes.items():
                price_val = data.get("price", 0) if isinstance(data, dict) else 0
                price_records[f"{plant_id}:{retailer_id}"] = price_records.get(
                    f"{plant_id}:{retailer_id}", {}
                )
                price_records[f"{plant_id}:{retailer_id}"][tier] = price_val

    # Check if we got significantly fewer results than expected
    expected = len(handle_map)
    if products_found < expected * 0.8:
        logger.error(
            f"  {retailer_id}: Only found {products_found}/{expected} products "
            f"({products_found/expected*100:.0f}%). Possible scraper breakage!"
        )

    return {
        "retailer_id": retailer_id,
        "status": "completed",
        "products_expected": expected,
        "products_found": products_found,
        "products_error": products_error,
        "prices_collected": prices_collected,
        "anomalies": anomalies,
        "price_records": price_records,
    }


def run(retailer_filter: str = None, dry_run: bool = False):
    """Main scraper orchestrator."""
    logger.info("=" * 60)
    logger.info("PlantPriceTracker — Scraper Run")
    logger.info(f"Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    # Load data
    plants = load_json(DATA_DIR / "plants.json")
    retailers = load_json(DATA_DIR / "retailers.json")
    plant_ids = [p["id"] for p in plants]

    # Filter to active retailers (or specific retailer)
    if retailer_filter:
        active_retailers = [r for r in retailers if r["id"] == retailer_filter]
        if not active_retailers:
            logger.error(f"Retailer '{retailer_filter}' not found in retailers.json")
            sys.exit(1)
    else:
        active_retailers = [r for r in retailers if r.get("active", False)]

    logger.info(f"\n{len(plants)} plants, {len(active_retailers)} retailers to scrape\n")

    # Load previous manifest for anomaly detection
    prev_manifest = load_previous_manifest()

    # Scrape each retailer
    manifest_entries = []
    all_anomalies = []
    total_prices = 0

    for retailer in active_retailers:
        entry = scrape_retailer(retailer, plant_ids, prev_manifest, dry_run)
        manifest_entries.append(entry)
        all_anomalies.extend(entry.get("anomalies", []))
        total_prices += entry.get("prices_collected", 0)

    # Save manifest
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retailers": manifest_entries,
        "total_prices_collected": total_prices,
        "total_anomalies": len(all_anomalies),
        "anomalies": all_anomalies,
        "prices": {},
    }
    # Merge price records from all retailers
    for entry in manifest_entries:
        for key, val in entry.get("price_records", {}).items():
            manifest["prices"][key] = val

    if not dry_run:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logger.info(f"\nManifest saved to {MANIFEST_PATH}")

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info("SCRAPE SUMMARY")
    logger.info(f"{'=' * 60}")
    for entry in manifest_entries:
        status = entry.get("status", "unknown")
        rid = entry["retailer_id"]
        if status == "completed":
            found = entry.get("products_found", 0)
            expected = entry.get("products_expected", 0)
            prices = entry.get("prices_collected", 0)
            errors = entry.get("products_error", 0)
            pct = (found / expected * 100) if expected else 0
            flag = " !!!" if pct < 80 else ""
            logger.info(f"  {rid}: {found}/{expected} products ({pct:.0f}%), {prices} prices, {errors} errors{flag}")
        elif status == "skipped":
            logger.info(f"  {rid}: SKIPPED — {entry.get('reason', '')}")
        elif status == "dry_run":
            logger.info(f"  {rid}: DRY RUN — {entry.get('products_mapped', 0)} mapped")

    if all_anomalies:
        logger.warning(f"\n{len(all_anomalies)} PRICE ANOMALIES DETECTED:")
        for a in all_anomalies:
            logger.warning(f"  {a}")

    logger.info(f"\nTotal prices collected: {total_prices}")

    # Exit with error if any retailer had <80% success rate
    for entry in manifest_entries:
        if entry.get("status") == "completed":
            found = entry.get("products_found", 0)
            expected = entry.get("products_expected", 1)
            if found / expected < 0.8:
                logger.error("PIPELINE FAILURE: One or more retailers below 80% threshold")
                sys.exit(1)

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run plant price scrapers")
    parser.add_argument("--retailer", type=str, help="Scrape a specific retailer only")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be scraped without scraping")
    args = parser.parse_args()

    run(retailer_filter=args.retailer, dry_run=args.dry_run)
