"""
Handle Discovery — Finds product handles for unmapped plants at each retailer.

For Shopify stores with working JSON endpoints, uses /products.json bulk listing
to find all plant products, then fuzzy-matches against our canonical plant names.

For stores without bulk JSON, uses site-specific web search to find handles.

Usage:
    python -m scrapers.discover_handles                    # Discover all gaps
    python -m scrapers.discover_handles --retailer nature-hills  # Single retailer
    python -m scrapers.discover_handles --dry-run          # Show matches without saving
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from scrapers.shopify import HANDLE_MAPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"


def load_plants():
    with open(DATA_DIR / "plants.json", encoding="utf-8") as f:
        return json.load(f)


def load_retailers():
    with open(DATA_DIR / "retailers.json", encoding="utf-8") as f:
        return json.load(f)


def fetch_all_products(base_url: str, max_pages: int = 20) -> list[dict]:
    """Fetch all products from a Shopify store's bulk JSON endpoint."""
    all_products = []
    page = 1

    while page <= max_pages:
        url = f"{base_url}/products.json?limit=250&page={page}"
        try:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }, timeout=20)

            if resp.status_code != 200:
                logger.warning(f"  Page {page}: HTTP {resp.status_code}")
                break

            data = resp.json()
            products = data.get("products", [])
            if not products:
                break

            all_products.extend(products)
            logger.info(f"  Page {page}: {len(products)} products (total: {len(all_products)})")

            if len(products) < 250:
                break  # Last page

            page += 1
            time.sleep(3)  # Polite delay between pages

        except Exception as e:
            logger.error(f"  Error fetching page {page}: {e}")
            break

    return all_products


def normalize_for_matching(text: str) -> str:
    """Normalize a plant name for fuzzy matching."""
    text = text.lower().strip()
    # Remove common prefixes/suffixes
    for remove in ["proven winners", "proven winners®", "endless summer®",
                    "knock out®", "encore®", "for sale", "buy", "online",
                    "tree", "shrub", "bush", "plant", "bare root", "bareroot"]:
        text = text.replace(remove, "")
    # Remove trademark symbols
    text = re.sub(r'[®™©]', '', text)
    # Remove parenthetical botanical names
    text = re.sub(r'\([^)]*\)', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def match_score(plant_name: str, product_title: str) -> float:
    """Score how well a product title matches a canonical plant name. 0-1."""
    pn = normalize_for_matching(plant_name)
    pt = normalize_for_matching(product_title)

    if not pn or not pt:
        return 0.0

    # Exact match (after normalization)
    if pn == pt:
        return 1.0

    # Check if all significant words from plant name appear in product title
    pn_words = set(pn.split())
    pt_words = set(pt.split())

    # Remove very common/noise words
    noise = {"the", "a", "an", "of", "for", "and", "or", "in", "at", "to", "by"}
    pn_words -= noise
    pt_words -= noise

    if not pn_words:
        return 0.0

    # What fraction of plant name words appear in product title?
    overlap = pn_words & pt_words
    score = len(overlap) / len(pn_words)

    return score


def find_matches(plants: list[dict], products: list[dict], existing_handles: dict,
                 threshold: float = 0.6) -> list[dict]:
    """Find product matches for unmapped plants."""
    matches = []

    for plant in plants:
        pid = plant["id"]

        # Skip if already mapped
        if pid in existing_handles:
            continue

        plant_name = plant["common_name"]
        botanical = plant.get("botanical_name", "")

        best_match = None
        best_score = 0.0

        for product in products:
            title = product.get("title", "")
            handle = product.get("handle", "")

            # Score against common name
            score1 = match_score(plant_name, title)
            # Score against botanical name
            score2 = match_score(botanical, title) * 0.8  # Slightly lower weight

            score = max(score1, score2)

            # Also check handle similarity
            pid_normalized = pid.replace("-", " ")
            handle_normalized = handle.replace("-", " ")
            handle_score = match_score(pid_normalized, handle_normalized) * 0.9
            score = max(score, handle_score)

            if score > best_score:
                best_score = score
                best_match = {
                    "plant_id": pid,
                    "plant_name": plant_name,
                    "product_title": title,
                    "handle": handle,
                    "score": round(score, 2),
                }

        if best_match and best_score >= threshold:
            matches.append(best_match)

    return matches


def discover_for_retailer(retailer: dict, plants: list[dict], dry_run: bool = False) -> list[dict]:
    """Discover handles for one retailer."""
    rid = retailer["id"]
    base_url = retailer["url"]
    existing = HANDLE_MAPS.get(rid, {})

    unmapped = [p for p in plants if p["id"] not in existing]
    if not unmapped:
        logger.info(f"  {rid}: All plants already mapped!")
        return []

    logger.info(f"  {rid}: {len(unmapped)} unmapped plants. Fetching product catalog...")

    # Fetch all products
    products = fetch_all_products(base_url)
    if not products:
        logger.warning(f"  {rid}: Could not fetch product catalog")
        return []

    logger.info(f"  {rid}: {len(products)} products in catalog")

    # Find matches
    matches = find_matches(unmapped, products, existing)

    if matches:
        logger.info(f"  {rid}: Found {len(matches)} potential matches:")
        for m in sorted(matches, key=lambda x: -x["score"]):
            confidence = "HIGH" if m["score"] >= 0.8 else "MED" if m["score"] >= 0.6 else "LOW"
            logger.info(f"    [{confidence}] {m['plant_name']} -> {m['handle']} (score: {m['score']})")
    else:
        logger.info(f"  {rid}: No new matches found")

    return matches


def main():
    parser = argparse.ArgumentParser(description="Discover product handles for unmapped plants")
    parser.add_argument("--retailer", type=str, help="Discover for a specific retailer")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without saving")
    parser.add_argument("--threshold", type=float, default=0.6, help="Match score threshold (0-1)")
    args = parser.parse_args()

    plants = load_plants()
    retailers = load_retailers()

    # Only process Shopify retailers (they have bulk JSON endpoints)
    shopify_retailers = [r for r in retailers if r.get("scraper_type") == "shopify" and r.get("active")]

    if args.retailer:
        shopify_retailers = [r for r in shopify_retailers if r["id"] == args.retailer]
        if not shopify_retailers:
            logger.error(f"Retailer '{args.retailer}' not found or not Shopify")
            sys.exit(1)

    logger.info(f"Discovering handles for {len(plants)} plants across {len(shopify_retailers)} retailers\n")

    all_matches = {}
    for retailer in shopify_retailers:
        rid = retailer["id"]
        logger.info(f"\n{'='*50}")
        logger.info(f"Retailer: {rid}")
        logger.info(f"{'='*50}")

        matches = discover_for_retailer(retailer, plants, args.dry_run)
        if matches:
            all_matches[rid] = matches

        time.sleep(5)  # Polite delay between retailers

    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("DISCOVERY SUMMARY")
    logger.info(f"{'='*50}")

    total_new = sum(len(m) for m in all_matches.values())
    logger.info(f"Total new matches found: {total_new}")

    if total_new > 0 and not args.dry_run:
        # Output as a Python dict for manual review + copy-paste into shopify.py
        logger.info("\nAdd these to HANDLE_MAPS in shopify.py:")
        for rid, matches in all_matches.items():
            logger.info(f'\n    "{rid}": {{')
            for m in sorted(matches, key=lambda x: -x["score"]):
                logger.info(f'        "{m["plant_id"]}": "{m["handle"]}",  # {m["plant_name"]} -> {m["product_title"]} (score: {m["score"]})')
            logger.info("    },")

    logger.info("\nREVIEW BEFORE ADDING — verify each match is correct!")


if __name__ == "__main__":
    main()
