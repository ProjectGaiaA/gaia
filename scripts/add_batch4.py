"""
Batch 4: Add 6 plants (Azaleas + Nandina + Fruit Trees) to plants.json (inactive).

Categories:
  - azaleas-rhododendrons (3): Autumn Royalty, Autumn Twist, Autumn Angel
  - privacy-trees (1): Nandina (Heavenly Bamboo)
  - fruit-trees (2): Santa Rosa Plum, Dwarf Cavendish Banana

Botanical data cross-referenced against:
  - NCSU Extension Plant Toolbox (https://plants.ces.ncsu.edu/plants/)
  - Missouri Botanical Garden Plant Finder
  - PlantingTree comma-delimited Shopify tags (for retailer triangulation)

Notes:
  - All 3 Encore Azaleas share zones 6-9 per Robert E. Lee breeder specs
    and NH retailer text. NCSU Encore group range is 6a-9a (10a for a few
    cultivars); picking 6-9 as the conservative breeder-authored range.
  - Nandina kept at species level (Nandina domestica, 3-8 ft). NH handle
    heavenly-bamboo-firepower is the dwarf 'Firepower' cultivar (2-3 ft,
    nearly fruitless) and is dropped from the handle map in a separate step
    - same precedent as Batch 1 Pampas Grass cultivar-mismatch removal.
  - Santa Rosa Plum uses tree size tiers WITH bareroot (temperate deciduous
    fruit, matches existing Honeycrisp/Fuji/Bing pattern).
  - Dwarf Cavendish Banana uses shrub tiers (no bareroot - tropical
    herbaceous perennial, matches Meyer Lemon tropical fruit pattern).
    Zones 9-11 (root-hardy in 9 where it dies back and resprouts).
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLANTS_FILE = PROJECT_ROOT / "data" / "plants.json"

# ---------------------------------------------------------------------------
# Size tier templates
# ---------------------------------------------------------------------------

# Shrub-style containers (no bareroot) - used for azaleas and nandina
SHRUB_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

# Temperate deciduous fruit tree tiers (WITH bareroot)
FRUIT_TREE_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
    "bareroot": ["bare root", "bare-root", "bareroot"],
}

# Tropical fruit tiers (NO bareroot) - matches Meyer Lemon pattern
TROPICAL_FRUIT_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

# Shrub planting seasons by zone (spring/fall balanced - from add_batch3.py)
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

# Tree planting seasons by zone (fall-dominant - from add_batch3.py)
TREE_SEASON_BY_ZONE = {
    "3":  {"spring": "May",      "fall": None},
    "4":  {"spring": "Apr-May",  "fall": "Oct"},
    "5":  {"spring": "Apr-May",  "fall": "Oct"},
    "6":  {"spring": "Mar-Apr",  "fall": "Oct-Nov"},
    "7":  {"spring": "Feb-Apr",  "fall": "Nov"},
    "8":  {"spring": "Jan-Mar",  "fall": "Nov-Dec"},
    "9":  {"spring": "Jan-Feb",  "fall": "Dec"},
    "10": {"spring": "Jan-Feb",  "fall": "Dec"},
    "11": {"spring": "Dec-Jan",  "fall": "Dec"},
}


def shrub_seasons(zones):
    return {str(z): SHRUB_SEASON_BY_ZONE[str(z)] for z in zones if str(z) in SHRUB_SEASON_BY_ZONE}


def tree_seasons(zones):
    return {str(z): TREE_SEASON_BY_ZONE[str(z)] for z in zones if str(z) in TREE_SEASON_BY_ZONE}


# Monthly price indices
SHRUB_MONTHLY_INDEX      = [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2]   # Apr-May peak
FRUIT_TREE_MONTHLY_INDEX = [3, 4, 5, 4, 3, 2, 2, 2, 2, 1, 1, 2]   # bareroot-heavy: Jan-Mar peak
TROPICAL_MONTHLY_INDEX   = [2, 3, 4, 5, 5, 4, 3, 3, 2, 2, 2, 2]   # spring peak, less seasonal


# ---------------------------------------------------------------------------
# Batch 4 plant definitions
# ---------------------------------------------------------------------------

BATCH4 = [
    # ── AZALEAS-RHODODENDRONS ─────────────────────────────────────
    {
        "id": "autumn-royalty-encore-azalea",
        "common_name": "Autumn Royalty Encore Azalea",
        "botanical_name": "Rhododendron 'Conlec'",
        "aliases": [
            "Encore Autumn Royalty",
            "Autumn Royalty Azalea",
            "Rhododendron Autumn Royalty",
        ],
        "category": "azaleas-rhododendrons",
        "zones": [6, 7, 8, 9],
        "sun": "Part shade (morning sun, afternoon shade)",
        "mature_size": "4-5 ft tall x 3-4 ft wide",
        "bloom_time": "Spring, summer, and fall (reblooming)",
        "type": "Evergreen shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "March-April",
            "note": "Autumn Royalty is the largest of the Encore series and won Rhododendron of the Year from the American Rhododendron Society. Deep lavender-purple reblooming flowers make it the most asked-for Encore cultivar - prices stay firm in spring demand. Fall clearance offers the best deals.",
            "tip": "Buy in fall for price and planting conditions. Plant with afternoon shade in zones 8-9 to protect reblooming flower buds from heat stress.",
        },
        "active": False,
    },
    {
        "id": "autumn-twist-encore-azalea",
        "common_name": "Autumn Twist Encore Azalea",
        "botanical_name": "Rhododendron 'Conlep'",
        "aliases": [
            "Encore Autumn Twist",
            "Autumn Twist Azalea",
        ],
        "category": "azaleas-rhododendrons",
        "zones": [6, 7, 8, 9],
        "sun": "Part shade (morning sun, afternoon shade)",
        "mature_size": "4-5 ft tall x 3-4 ft wide",
        "bloom_time": "Spring, summer, and fall (reblooming)",
        "type": "Evergreen shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "March-April",
            "note": "Autumn Twist is prized for its bi-color white-and-purple-striped blooms (each flower is unique). Same mid-size growth habit as Autumn Royalty but with showier flowers. Spring is peak demand and peak price; fall clearance offers 15-30% savings.",
            "tip": "The striped flower pattern varies plant to plant - if you care about the look, buy in person or from a retailer with return policies. Fall planting establishes roots before the spring bloom flush.",
        },
        "active": False,
    },
    {
        "id": "autumn-angel-encore-azalea",
        "common_name": "Autumn Angel Encore Azalea",
        "botanical_name": "Rhododendron 'Robleg'",
        "aliases": [
            "Encore Autumn Angel",
            "Autumn Angel Azalea",
        ],
        "category": "azaleas-rhododendrons",
        "zones": [6, 7, 8, 9],
        "sun": "Part shade (morning sun, afternoon shade)",
        "mature_size": "2-3 ft tall x 2-3 ft wide",
        "bloom_time": "Spring, summer, and fall (reblooming)",
        "type": "Evergreen shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "March-April",
            "note": "Autumn Angel is the dwarf white-flowered Encore - only 2-3 ft mature, much smaller than Royalty or Twist. Ideal for small-space foundation plantings or low hedges. Patented PP15227 so prices stay firm at retail; fall clearance is the best time to buy.",
            "tip": "Because of its compact size, Autumn Angel is sold mostly in 1-gal and 3-gal containers. Plant in groups of 3-5 for hedge effect. Fall planting is ideal.",
        },
        "active": False,
    },

    # ── PRIVACY TREES (Nandina) ───────────────────────────────────
    {
        "id": "nandina-heavenly-bamboo",
        "common_name": "Nandina (Heavenly Bamboo)",
        "botanical_name": "Nandina domestica",
        "aliases": [
            "Heavenly Bamboo",
            "Sacred Bamboo",
            "Chinese Sacred Bamboo",
        ],
        "category": "privacy-trees",
        "zones": [6, 7, 8, 9],
        "sun": "Full sun to part shade",
        "mature_size": "3-8 ft tall x 2-5 ft wide",
        "bloom_time": "Late spring (followed by red berries)",
        "type": "Evergreen shrub",
        "size_tiers": dict(SHRUB_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": shrub_seasons([6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(SHRUB_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Nandina is a tough evergreen shrub with year-round foliage color (green in summer, red in fall/winter) and red berries. Cultivars range from dwarf 'Firepower' (2-3 ft, nearly fruitless) to standard species (5-8 ft with berries). Flagged as invasive in some southern states - check local regulations. Fall clearance offers 20-30% savings.",
            "tip": "For a low-maintenance colorful hedge, standard Nandina is hard to beat. If you live in the deep South, consider sterile dwarf cultivars instead of the fruiting species to avoid volunteer seedlings.",
        },
        "active": False,
    },

    # ── FRUIT TREES ────────────────────────────────────────────────
    {
        "id": "santa-rosa-plum",
        "common_name": "Santa Rosa Plum Tree",
        "botanical_name": "Prunus salicina 'Santa Rosa'",
        "aliases": [
            "Santa Rosa Japanese Plum",
            "Santa Rosa Plum",
        ],
        "category": "fruit-trees",
        "zones": [5, 6, 7, 8, 9],
        "sun": "Full sun",
        "mature_size": "15-20 ft tall x 15-20 ft wide",
        "bloom_time": "Early spring (white flowers)",
        "type": "Deciduous fruit tree",
        "size_tiers": dict(FRUIT_TREE_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([5, 6, 7, 8, 9]),
        "price_seasonality": {
            "monthly_index": list(FRUIT_TREE_MONTHLY_INDEX),
            "best_buy": "October-November",
            "worst_buy": "March",
            "note": "Santa Rosa is the classic self-pollinating Japanese plum introduced by Luther Burbank in 1906 - still a home-orchard favorite for its crimson skin, amber flesh, and heavy crops. Bare-root trees (January-March) run 30-50% cheaper than potted. Requires 300-500 chill hours so it struggles in the deep South zone 9 without a cold winter.",
            "tip": "Order bare-root in January for best price and selection. Self-fertile so one tree is enough, but planting a second Japanese plum increases yields. Needs full sun and well-drained soil.",
        },
        "active": False,
    },
    {
        "id": "dwarf-cavendish-banana",
        "common_name": "Dwarf Cavendish Banana",
        "botanical_name": "Musa acuminata 'Dwarf Cavendish'",
        "aliases": [
            "Dwarf Cavendish Banana Tree",
            "Dwarf Banana",
            "Dwarf Cavendish",
        ],
        "category": "fruit-trees",
        "zones": [9, 10, 11],
        "sun": "Full sun to part shade",
        "mature_size": "6-10 ft tall x 6-10 ft wide",
        "bloom_time": "Summer (on 2-3 year old plants)",
        "type": "Tropical herbaceous perennial",
        "size_tiers": dict(TROPICAL_FRUIT_SIZE_TIERS),
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": tree_seasons([9, 10, 11]),
        "price_seasonality": {
            "monthly_index": list(TROPICAL_MONTHLY_INDEX),
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": "Dwarf Cavendish is the most common edible banana worldwide, bred for container growing and small-space yards. Tropical - outdoor year-round only in zones 10-11; in zone 9 it dies back in winter and resprouts from the corm. Can be grown indoors in containers in colder zones. Spring demand drives prices up; fall clearance is the best deal window.",
            "tip": "Buy in fall for clearance, but plant in spring after last frost (zone 9) or anytime (zone 10-11). Plants take 2-3 years to fruit. A potted Dwarf Cavendish can be brought indoors for winter in zone 8 or colder.",
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
    conflicts = [p["id"] for p in BATCH4 if p["id"] in existing_ids]
    if conflicts:
        print(f"  ERROR: IDs already exist: {conflicts}", file=sys.stderr)
        sys.exit(1)

    plants.extend(BATCH4)

    with open(PLANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(plants, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  Wrote {len(plants)} plants to {PLANTS_FILE}")
    for p in BATCH4:
        z = p["zones"]
        print(f"    Added: {p['id']:<32} | {p['category']:<22} | zones {z[0]}-{z[-1]}")


if __name__ == "__main__":
    main()
