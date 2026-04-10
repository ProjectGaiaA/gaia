"""Batch extraction: fetch product pages for all Batch 1 plants and parse botanical data.

Runs extract_plant_data.py functions against all non-FGT retailers.
Outputs raw parsed data per retailer + reconciled results per plant.
"""
import json
import sys
from pathlib import Path

# Add project root to path so we can import scrapers
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.extract_plant_data import fetch_product_page, reconcile_fields  # noqa: E402

PLANTS_FILE = ROOT / "data" / "plants.json"
HANDLE_MAPS_FILE = ROOT / "data" / "handle_maps.json"
RETAILERS_FILE = ROOT / "data" / "retailers.json"

# FGT blocks JSON endpoints — skip
SKIP_RETAILERS = {"fast-growing-trees"}

BATCH1 = [
    "big-blue-liriope",
    "ajuga-chocolate-chip",
    "creeping-thyme",
    "sedum-angelina",
    "blue-rug-juniper",
    "pink-muhly-grass",
    "purple-fountain-grass",
    "hameln-dwarf-fountain-grass",
    "blue-fescue-elijah-blue",
    "pampas-grass",
]


def main():
    with open(HANDLE_MAPS_FILE, "r", encoding="utf-8") as f:
        handle_maps = json.load(f)
    with open(RETAILERS_FILE, "r", encoding="utf-8") as f:
        retailers = {r["id"]: r["url"] for r in json.load(f)}
    with open(PLANTS_FILE, "r", encoding="utf-8") as f:
        plants = json.load(f)
    plant_lookup = {p["id"]: p for p in plants}

    results = {}

    for plant_id in BATCH1:
        plant = plant_lookup.get(plant_id)
        if not plant:
            print(f"SKIP {plant_id}: not found in plants.json")
            continue

        common_name = plant["common_name"]
        print(f"\n{'='*60}")
        print(f"EXTRACTING: {common_name} ({plant_id})")
        print(f"{'='*60}")

        # Gather retailer handles
        retailer_pages = []
        for retailer_id, handles in handle_maps.items():
            if plant_id not in handles:
                continue
            if retailer_id in SKIP_RETAILERS:
                print(f"  SKIP {retailer_id} (JSON blocked)")
                continue
            base_url = retailers.get(retailer_id)
            if not base_url:
                print(f"  SKIP {retailer_id} (no URL)")
                continue

            handle = handles[plant_id]
            print(f"  Fetching {retailer_id}: {handle} ... ", end="", flush=True)
            page = fetch_product_page(base_url, handle)
            if page:
                print(f"OK — title: {page['title']}")
                print(f"    parsed: {page['parsed']}")
                retailer_pages.append(page)
            else:
                print("FAILED")

        if not retailer_pages:
            print(f"  NO DATA for {plant_id}")
            results[plant_id] = {"error": "no pages fetched"}
            continue

        # Reconcile
        reconciled = reconcile_fields(retailer_pages, common_name)
        print("\n  RECONCILED:")
        for field, info in reconciled.items():
            flag = " [REVIEW]" if info["flagged"] else ""
            print(f"    {field}: {info['value']} (source: {info['source']}){flag}")

        # Compare against current plants.json entry
        print("\n  CURRENT vs EXTRACTED:")
        for field in ["zones", "sun", "mature_size", "bloom_time", "type"]:
            current = plant.get(field)
            extracted = reconciled[field]["value"]
            match = "MATCH" if str(current) == str(extracted) else "DIFF"
            if match == "DIFF":
                print(f"    {field}: CURRENT={current} | EXTRACTED={extracted} <<<")
            else:
                print(f"    {field}: {current} ✓")

        results[plant_id] = {
            "retailer_count": len(retailer_pages),
            "reconciled": {k: v for k, v in reconciled.items()},
            "current": {f: plant.get(f) for f in ["zones", "sun", "mature_size", "bloom_time", "type"]},
        }

    # Save raw results
    output_file = ROOT / "data" / "batch1_extraction_results.json"
    # Convert for JSON serialization
    serializable = {}
    for pid, data in results.items():
        serializable[pid] = data
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
