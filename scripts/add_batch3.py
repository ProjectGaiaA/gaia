"""
Batch 3: Add 8 Trees to plants.json (inactive).

Categories:
  - shade-trees (4): October Glory Maple, Heritage River Birch, Red Sunset Maple,
    Sweetbay Magnolia
  - flowering-trees (3): Rose of Sharon, Wine & Roses Weigela, Frost Proof Gardenia
  - privacy-trees (1): Dwarf Alberta Spruce

Excluded from original spec (Task 3 handle discovery cut):
  - Bald Cypress (1 retailer only - NH)
  - Spirea Goldflame (0 retailers)

Botanical data cross-referenced against:
  - NCSU Extension Plant Toolbox (https://plants.ces.ncsu.edu/plants/)
  - Missouri Botanical Garden Plant Finder
  - PlantingTree comma-delimited Shopify tags (where present) for retailer triangulation

Rose of Sharon: kept at genus level (Hibiscus syriacus). 5 retailers carry 5
different H. syriacus cultivars (Lucy, Pink Chiffon, Blue Bird, Azurri Blue
Satin, Lavender) - no single cultivar overlap. Same reconciliation pattern
as Batch 2 Astilbe/Heuchera/Bleeding Heart/Bee Balm.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLANTS_FILE = PROJECT_ROOT / "data" / "plants.json"

# ---------------------------------------------------------------------------
# Size tier templates
# ---------------------------------------------------------------------------

# Trees (shade + privacy) include bareroot for larger nursery stock
TREE_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
    "7gal": ["7 gallon", "7 gal", "#7 container"],
    "bareroot": ["bare root", "bare-root", "bareroot"],
}

# Flowering shrubs sold as "flowering trees" use shrub-style containers (no bareroot)
SHRUB_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

# Tree planting seasons by zone (fall-dominant - trees establish best in autumn)
TREE_SEASON_BY_ZONE = {
    "3": {"spring": "May",      "fall": None},
    "4": {"spring": "Apr-May",  "fall": "Oct"},
    "5": {"spring": "Apr-May",  "fall": "Oct"},
    "6": {"spring": "Mar-Apr",  "fall": "Oct-Nov"},
    "7": {"spring": "Feb-Apr",  "fall": "Nov"},
    "8": {"spring": "Jan-Mar",  "fall": "Nov-Dec"},
    "9": {"spring": "Jan-Feb",  "fall": "Dec"},
    "10": {"spring": "Jan-Feb", "fall": "Dec"},
    "11": {"spring": "Dec-Jan", "fall": "Dec"},
}

# Shrub planting seasons by zone (spring/fall balanced)
SHRUB_SEASON_BY_ZONE = {
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


def tree_seasons(zones):
    return {str(z): TREE_SEASON_BY_ZONE[str(z)] for z in zones if str(z) in TREE_SEASON_BY_ZONE}


def shrub_seasons(zones):
    return {str(z): SHRUB_SEASON_BY_ZONE[str(z)] for z in zones if str(z) in SHRUB_SEASON_BY_ZONE}


# Monthly price indices
TREE_MONTHLY_INDEX  = [3, 4, 5, 4, 3, 2, 2, 2, 2, 1, 1, 2]   # bareroot-heavy: Jan-Mar peak
SHRUB_MONTHLY_INDEX = [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2]   # Apr-May peak


# ---------------------------------------------------------------------------
# Batch 3 plant definitions
# ---------------------------------------------------------------------------

BATCH3 = [
    # ── SHADE TREES ────────────────────────────────────────────────
    {
        "id": "october-glory-maple",
        "common_name": "October Glory Maple",
        "botanical_name": "Acer rubrum 'October Glory'",
        "aliases": ["October Glory Red Maple"],
        "category": "shade-trees",
        "zones": [4, 5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "40-50 ft tall x 25-35 ft wide",
        "bloom_time": "Early spring (inconspicuous)",
        "type": "Deciduous tree",
        "size_tiers": dict(TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(TREE_MONTHLY_INDEX),
            "best_buy": "October-November",
            "worst_buy": "March-April",
            "note": "October Glory is a popular, reliably colorful Red Maple cultivar. Bare-root availability is limited - most retailers sell containerized. Fall clearance offers the best deals on potted trees.",
            "tip": "Buy in fall when inventory is clearing and planting conditions are ideal. Mature October Glorys can reach 50 ft, so site placement matters more than price.",
        },
        "active": False,
    },
    {
        "id": "heritage-river-birch",
        "common_name": "Heritage River Birch",
        "botanical_name": "Betula nigra 'Cully'",
        "aliases": ["Heritage Birch", "Cully River Birch"],
        "category": "shade-trees",
        "zones": [4, 5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "40-70 ft tall x 40-60 ft wide",
        "bloom_time": "Early spring (catkins)",
        "type": "Deciduous tree",
        "size_tiers": dict(TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(TREE_MONTHLY_INDEX),
            "best_buy": "October-November",
            "worst_buy": "March-April",
            "note": "Heritage is the most popular River Birch cultivar thanks to its heat tolerance and resistance to bronze birch borer. Often sold as single-trunk or clump form - clump form is typically 20-30% more expensive.",
            "tip": "Decide on single-trunk vs clump form before shopping - prices vary significantly. Fall planting is ideal for this moisture-loving tree.",
        },
        "active": False,
    },
    {
        "id": "red-sunset-maple",
        "common_name": "Red Sunset Maple",
        "botanical_name": "Acer rubrum 'Franksred'",
        "aliases": ["Red Sunset", "Franksred Maple"],
        "category": "shade-trees",
        "zones": [4, 5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "40-60 ft tall x 30-40 ft wide",
        "bloom_time": "Early spring (inconspicuous)",
        "type": "Deciduous tree",
        "size_tiers": dict(TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([4, 5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(TREE_MONTHLY_INDEX),
            "best_buy": "October-November",
            "worst_buy": "March-April",
            "note": "Red Sunset is widely considered the best Red Maple cultivar for fall color reliability. Often priced slightly higher than October Glory due to demand. Fall clearance is the best time to buy.",
            "tip": "Buy in fall when inventory is clearing. Red Sunset colors up earlier than most Red Maples, so you get a longer fall display.",
        },
        "active": False,
    },
    {
        "id": "sweetbay-magnolia",
        "common_name": "Sweetbay Magnolia",
        "botanical_name": "Magnolia virginiana",
        "aliases": ["Swamp Magnolia", "Laurel Magnolia", "White Bay"],
        "category": "shade-trees",
        "zones": [5, 6, 7, 8, 9, 10],
        "sun": "Full sun to part shade",
        "mature_size": "15-35 ft tall x 10-25 ft wide",
        "bloom_time": "Late spring to summer (sporadic)",
        "type": "Deciduous to semi-evergreen tree",
        "size_tiers": dict(TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([5, 6, 7, 8, 9, 10]),
        "price_seasonality": {
            "monthly_index": list(TREE_MONTHLY_INDEX),
            "best_buy": "October-November",
            "worst_buy": "March-April",
            "note": "Sweetbay tolerates wet soils that kill most trees, making it a niche-but-valuable option. It is semi-evergreen in the South (zones 8-10) and deciduous in the North. Fall clearance offers the best deals.",
            "tip": "Fall is the best time to plant - the fragrant lemony blooms appear the following spring. Choose sweetbay for wet sites where other magnolias would fail.",
        },
        "active": False,
    },

    # ── FLOWERING TREES (shrubs marketed as flowering trees) ───────
    {
        "id": "rose-of-sharon",
        "common_name": "Rose of Sharon",
        "botanical_name": "Hibiscus syriacus",
        "aliases": ["Hardy Hibiscus (shrub form)", "Shrub Althea", "Althea"],
        "category": "flowering-trees",
        "zones": [5, 6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "8-12 ft tall x 6-10 ft wide",
        "bloom_time": "Early summer to fall",
        "type": "Deciduous shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Rose of Sharon is sold under many cultivar names - Lucy, Pink Chiffon, Blue Bird, Azurri Blue Satin, Lavender. Prices vary widely by cultivar, with newer patented varieties commanding premium pricing. Fall clearance offers 15-30% savings.",
            "tip": "Buy in fall for clearance. Standard cultivars (Lucy, Blue Bird) are cheaper than newer patented series like Chiffon or Satin. All bloom prolifically in late summer when few other shrubs do.",
        },
        "active": False,
    },
    {
        "id": "wine-and-roses-weigela",
        "common_name": "Wine & Roses Weigela",
        "botanical_name": "Weigela florida 'Alexandra'",
        "aliases": ["Wine and Roses Weigela", "Alexandra Weigela"],
        "category": "flowering-trees",
        "zones": [4, 5, 6, 7, 8],
        "sun": "Full sun",
        "mature_size": "4-5 ft tall x 4-5 ft wide",
        "bloom_time": "Mid to late spring (repeat in summer)",
        "type": "Deciduous shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([4, 5, 6, 7, 8]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Wine & Roses is a Proven Winners patented cultivar, so prices stay firm at retail. The dark burgundy foliage is the main selling point - it holds color all season. Fall clearance offers the best deals.",
            "tip": "Buy in fall for clearance pricing. Full sun produces the darkest, richest foliage color - partial shade causes the burgundy to fade toward green.",
        },
        "active": False,
    },
    {
        "id": "gardenia-frost-proof",
        "common_name": "Frost Proof Gardenia",
        "botanical_name": "Gardenia jasminoides 'Frost Proof'",
        "aliases": ["Frost Proof", "Cold Hardy Gardenia"],
        "category": "flowering-trees",
        "zones": [7, 8, 9, 10, 11],
        "sun": "Full sun to part shade",
        "mature_size": "4-5 ft tall x 4-5 ft wide",
        "bloom_time": "Late spring to summer",
        "type": "Evergreen shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([7, 8, 9, 10, 11]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Frost Proof is the most cold-hardy Gardenia cultivar, extending the range into zone 7 where most gardenias fail. Prices peak in spring when fragrant-shrub demand is highest. Fall clearance offers 15-30% savings.",
            "tip": "Buy in fall for clearance, but plant in spring in zone 7 so the shrub can establish before winter. Afternoon shade in zones 9-11 prevents leaf scorch.",
        },
        "active": False,
    },

    # ── PRIVACY TREES ──────────────────────────────────────────────
    {
        "id": "dwarf-alberta-spruce",
        "common_name": "Dwarf Alberta Spruce",
        "botanical_name": "Picea glauca 'Conica'",
        "aliases": ["Conica Spruce", "Dwarf White Spruce"],
        "category": "privacy-trees",
        "zones": [3, 4, 5, 6],
        "sun": "Full sun to part shade",
        "mature_size": "10-13 ft tall x 7-10 ft wide (slow-growing)",
        "bloom_time": "Non-flowering",
        "type": "Evergreen conifer",
        "size_tiers": dict(TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([3, 4, 5, 6]),
        "price_seasonality": {
            "monthly_index": [3, 3, 4, 5, 5, 4, 3, 2, 2, 1, 2, 3],  # spring peak + winter holiday bump
            "best_buy": "September-October",
            "worst_buy": "April-May and December",
            "note": "Dwarf Alberta Spruce has a distinct December price bump because landscapers use potted specimens as living Christmas trees. Spring is the main buying season when containers are freshly stocked. Heat-sensitive - not recommended south of zone 6.",
            "tip": "Buy in fall for the best deals and ideal planting weather. Avoid hot, dry sites - this conifer dislikes summer heat above zone 6. Watch for spider mites in warm climates.",
        },
        "active": False,
    },
]


def main():
    print(f"Loading {PLANTS_FILE}")
    with open(PLANTS_FILE, "r", encoding="utf-8") as f:
        plants = json.load(f)
    print(f"  Loaded {len(plants)} plants")

    existing_ids = {p["id"] for p in plants}
    conflicts = [p["id"] for p in BATCH3 if p["id"] in existing_ids]
    if conflicts:
        print(f"  ERROR: IDs already exist: {conflicts}", file=sys.stderr)
        sys.exit(1)

    plants.extend(BATCH3)

    with open(PLANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(plants, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  Wrote {len(plants)} plants to {PLANTS_FILE}")
    for p in BATCH3:
        z = p["zones"]
        print(f"    Added: {p['id']:<30} | {p['category']:<16} | zones {z[0]}-{z[-1]}")


if __name__ == "__main__":
    main()
