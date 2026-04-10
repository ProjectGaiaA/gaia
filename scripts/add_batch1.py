"""Add Batch 1 plants (Groundcovers + Grasses) to plants.json as inactive.

One-time script for catalog expansion Task 4.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANTS_FILE = ROOT / "data" / "plants.json"

# Standard size tiers for shrubs/perennials/groundcovers/grasses
SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

# Planting seasons by zone (for hardy perennials/groundcovers/grasses)
SEASON_BY_ZONE = {
    "3":  {"spring": "May-Jun",  "fall": "Sep"},
    "4":  {"spring": "Apr-May",  "fall": "Sep-Oct"},
    "5":  {"spring": "Apr-May",  "fall": "Sep-Oct"},
    "6":  {"spring": "Mar-May",  "fall": "Sep-Nov"},
    "7":  {"spring": "Mar-Apr",  "fall": "Oct-Nov"},
    "8":  {"spring": "Feb-Apr",  "fall": "Oct-Dec"},
    "9":  {"spring": "Feb-Mar",  "fall": "Nov-Dec"},
    "10": {"spring": "Jan-Mar",  "fall": "Nov-Dec"},
    "11": {"spring": "Jan-Feb",  "fall": "Nov-Dec"},
}


def seasons(zones):
    return {str(z): SEASON_BY_ZONE[str(z)] for z in zones if str(z) in SEASON_BY_ZONE}


BATCH1 = [
    # ── GROUNDCOVERS ──────────────────────────────────────────────
    {
        "id": "big-blue-liriope",
        "common_name": "Big Blue Liriope",
        "botanical_name": "Liriope muscari 'Big Blue'",
        "aliases": ["Monkey Grass", "Lilyturf", "Big Blue Lilyturf"],
        "category": "groundcovers",
        "zones": [5, 6, 7, 8, 9, 10],
        "sun": "Full sun to full shade",
        "mature_size": "12-18 in tall x 12-18 in wide",
        "bloom_time": "Mid-summer to fall",
        "type": "Evergreen perennial groundcover",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([5, 6, 7, 8, 9, 10]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings as nurseries clear summer inventory.",
            "tip": "Buy in fall for the best deals. Liriope is extremely tough and establishes quickly even when planted in autumn.",
        },
        "active": False,
    },
    {
        "id": "ajuga-chocolate-chip",
        "common_name": "Ajuga Chocolate Chip",
        "botanical_name": "Ajuga reptans 'Valfredda'",
        "aliases": ["Chocolate Chip Bugleweed", "Carpet Bugle"],
        "category": "groundcovers",
        "zones": [3, 4, 5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "2-4 in tall x 6-12 in wide",
        "bloom_time": "Late spring to early summer",
        "type": "Evergreen perennial groundcover",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([3, 4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings. Ajuga is often available in flats for better per-plant pricing.",
            "tip": "Buy in fall or look for flat pricing in spring. Ajuga spreads aggressively, so fewer plants cover more ground than you might expect.",
        },
        "active": False,
    },
    {
        "id": "creeping-thyme",
        "common_name": "Creeping Thyme",
        "botanical_name": "Thymus serpyllum",
        "aliases": ["Wild Thyme", "Mother of Thyme", "Elfin Thyme"],
        "category": "groundcovers",
        "zones": [4, 5, 6, 7, 8, 9],
        "sun": "Full sun",
        "mature_size": "1-3 in tall x 12-18 in wide",
        "bloom_time": "Early to mid-summer",
        "type": "Herbaceous perennial groundcover",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers savings, though selection may be limited for smaller groundcover varieties.",
            "tip": "Buy in spring for best selection or fall for clearance pricing. Creeping thyme is drought-tolerant once established and makes an excellent lawn alternative.",
        },
        "active": False,
    },
    {
        "id": "sedum-angelina",
        "common_name": "Sedum Angelina",
        "botanical_name": "Sedum rupestre 'Angelina'",
        "aliases": ["Angelina Stonecrop"],
        "category": "groundcovers",
        "zones": [5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "3-6 in tall x 12-24 in wide",
        "bloom_time": "Mid to late summer",
        "type": "Herbaceous perennial groundcover",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings. Sedum divisions and plugs offer more affordable coverage for large areas.",
            "tip": "Buy in fall for the best deals. Sedum is extremely drought-tolerant and nearly indestructible once established.",
        },
        "active": False,
    },
    {
        "id": "blue-rug-juniper",
        "common_name": "Blue Rug Juniper",
        "botanical_name": "Juniperus horizontalis 'Wiltonii'",
        "aliases": ["Wilton Carpet Juniper", "Blue Creeping Juniper"],
        "category": "groundcovers",
        "zones": [3, 4, 5, 6, 7, 8, 9],
        "sun": "Full sun",
        "mature_size": "4-6 in tall x 6-8 ft wide",
        "bloom_time": "Non-flowering",
        "type": "Evergreen shrub groundcover",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([3, 4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": [2, 2, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when landscaping demand surges. Fall is the best time to buy evergreens as nurseries clear inventory before winter.",
            "tip": "Buy in fall for clearance pricing and ideal planting conditions. Evergreen junipers establish best when planted before the ground freezes.",
        },
        "active": False,
    },

    # ── GRASSES ────────────────────────────────────────────────────
    {
        "id": "pink-muhly-grass",
        "common_name": "Pink Muhly Grass",
        "botanical_name": "Muhlenbergia capillaris",
        "aliases": ["Gulf Muhly", "Cotton Candy Grass", "Pink Hair Grass"],
        "category": "grasses",
        "zones": [5, 6, 7, 8, 9, 10, 11],
        "sun": "Full sun",
        "mature_size": "3-4 ft tall x 3-4 ft wide",
        "bloom_time": "Late summer to fall",
        "type": "Ornamental grass",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([5, 6, 7, 8, 9, 10, 11]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall is an excellent time to buy as the dramatic pink plumes are on full display and nurseries offer clearance pricing.",
            "tip": "Buy in early fall when the pink plumes are visible so you can see the quality. Fall planting gives roots time to establish before winter dormancy.",
        },
        "active": False,
    },
    {
        "id": "purple-fountain-grass",
        "common_name": "Purple Fountain Grass",
        "botanical_name": "Pennisetum setaceum 'Rubrum'",
        "aliases": ["Red Fountain Grass", "Rubrum Grass"],
        "category": "grasses",
        "zones": [9, 10, 11],
        "sun": "Full sun",
        "mature_size": "3-5 ft tall x 2-4 ft wide",
        "bloom_time": "Mid-summer to fall",
        "type": "Ornamental grass",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([9, 10, 11]),
        "price_seasonality": {
            "monthly_index": [1, 2, 4, 5, 5, 4, 3, 2, 1, 1, 1, 1],
            "best_buy": "September-November",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when warm-season grasses break dormancy and demand surges. Fall clearance offers the best deals. Often sold as an annual in colder zones, which keeps prices competitive.",
            "tip": "In zones 9-11 where it is perennial, buy in early spring for the full growing season. In colder zones, treat as a seasonal annual and look for late-spring deals.",
        },
        "active": False,
    },
    {
        "id": "hameln-dwarf-fountain-grass",
        "common_name": "Hameln Dwarf Fountain Grass",
        "botanical_name": "Pennisetum alopecuroides 'Hameln'",
        "aliases": ["Hameln Fountain Grass", "Dwarf Fountain Grass"],
        "category": "grasses",
        "zones": [5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "2-3 ft tall x 2-3 ft wide",
        "bloom_time": "Mid-summer to fall",
        "type": "Ornamental grass",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers 15-30% savings. Hameln is one of the most popular fountain grass cultivars, so availability is usually good.",
            "tip": "Buy in fall for the best deals. Fall-planted fountain grass establishes stronger root systems over winter and fills out faster the following spring.",
        },
        "active": False,
    },
    {
        "id": "blue-fescue-elijah-blue",
        "common_name": "Blue Fescue (Elijah Blue)",
        "botanical_name": "Festuca glauca 'Elijah Blue'",
        "aliases": ["Elijah Blue Fescue", "Blue Fescue Grass"],
        "category": "grasses",
        "zones": [4, 5, 6, 7, 8],
        "sun": "Full sun",
        "mature_size": "8-12 in tall x 8-12 in wide",
        "bloom_time": "Late spring to early summer",
        "type": "Evergreen ornamental grass",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([4, 5, 6, 7, 8]),
        "price_seasonality": {
            "monthly_index": [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2],
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand is highest. Fall clearance offers savings. Blue Fescue is often sold in multi-packs for better per-plant pricing on mass plantings.",
            "tip": "Buy in fall for clearance pricing. Blue Fescue is a cool-season grass that actually prefers fall planting, establishing best before summer heat arrives.",
        },
        "active": False,
    },
    {
        "id": "pampas-grass",
        "common_name": "Pampas Grass",
        "botanical_name": "Cortaderia selloana",
        "aliases": ["White Pampas Grass"],
        "category": "grasses",
        "zones": [7, 8, 9, 10, 11],
        "sun": "Full sun",
        "mature_size": "8-12 ft tall x 6-8 ft wide",
        "bloom_time": "Late summer to fall",
        "type": "Ornamental grass",
        "size_tiers": dict(SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": seasons([7, 8, 9, 10, 11]),
        "price_seasonality": {
            "monthly_index": [1, 2, 4, 5, 5, 4, 3, 2, 1, 1, 1, 1],
            "best_buy": "September-November",
            "worst_buy": "April-May",
            "note": "Prices peak in spring when demand surges. Fall is the best time to buy as nurseries clear large-container inventory. Pampas Grass commands higher prices due to its dramatic size.",
            "tip": "Buy in fall for clearance pricing. Spring planting is ideal in zones 7-8 where winters are cooler, giving the plant a full season to establish before its first winter.",
        },
        "active": False,
    },
]


def main():
    with open(PLANTS_FILE, "r", encoding="utf-8") as f:
        plants = json.load(f)

    existing_ids = {p["id"] for p in plants}
    new_ids = [p["id"] for p in BATCH1]
    conflicts = [pid for pid in new_ids if pid in existing_ids]
    if conflicts:
        print(f"ERROR: IDs already exist: {conflicts}", file=sys.stderr)
        sys.exit(1)

    plants.extend(BATCH1)

    with open(PLANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(plants, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Added {len(BATCH1)} plants. New total: {len(plants)}")
    for p in BATCH1:
        z = p["zones"]
        print(f"  {p['id']}: {p['common_name']} | {p['category']} | zones {z[0]}-{z[-1]}")


if __name__ == "__main__":
    main()
