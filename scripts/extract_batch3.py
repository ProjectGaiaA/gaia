"""Fetch Batch 3 Shopify product pages and dump title/tags/body_html/vendor
for each handle so we can reconcile botanical data across retailers.

FGT JSON endpoints 404 — skip them.
"""
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scrapers.polite import is_allowed_by_robots, make_polite_session, polite_delay

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDLE_MAPS = PROJECT_ROOT / "data" / "handle_maps.json"
OUT_FILE = PROJECT_ROOT / "data" / "batch3_extraction_results.json"

RETAILER_URLS = {
    "nature-hills": "https://naturehills.com",
    "planting-tree": "https://www.plantingtree.com",
    "spring-hill": "https://springhillnursery.com",
    "proven-winners-direct": "https://provenwinnersdirect.com",
    "brecks": "https://www.brecks.com",
}
# Skip FGT — blocked on JSON endpoints (404)

BATCH3_IDS = [
    "october-glory-maple",
    "heritage-river-birch",
    "red-sunset-maple",
    "sweetbay-magnolia",
    "rose-of-sharon",
    "wine-and-roses-weigela",
    "gardenia-frost-proof",
    "dwarf-alberta-spruce",
]


def fetch_raw(retailer_url: str, handle: str) -> dict | None:
    url = f"{retailer_url.rstrip('/')}/products/{handle}.json"
    if not is_allowed_by_robots(url):
        return {"error": "blocked by robots.txt", "url": url}
    session = make_polite_session()
    try:
        polite_delay(5.0, 12.0)
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "url": url}
        data = resp.json()
        p = data.get("product", {})
        return {
            "url": url,
            "title": p.get("title", ""),
            "vendor": p.get("vendor", ""),
            "product_type": p.get("product_type", ""),
            "tags": p.get("tags", []),
            "body_html": p.get("body_html", ""),
            "variants_count": len(p.get("variants", [])),
        }
    except Exception as e:
        return {"error": str(e), "url": url}


def main():
    with open(HANDLE_MAPS) as f:
        hmap = json.load(f)

    results = {}
    for plant_id in BATCH3_IDS:
        print(f"\n=== {plant_id} ===")
        results[plant_id] = {}
        for retailer_id, base_url in RETAILER_URLS.items():
            handle = hmap.get(retailer_id, {}).get(plant_id)
            if not handle:
                continue
            print(f"  Fetching {retailer_id}: {handle}")
            result = fetch_raw(base_url, handle)
            results[plant_id][retailer_id] = result
            if result and not result.get("error"):
                print(f"    OK: '{result['title']}'")
            else:
                print(f"    ERR: {result.get('error') if result else 'None'}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {OUT_FILE}")


if __name__ == "__main__":
    main()
