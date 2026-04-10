"""
Batch 2: Add 8 Perennials to plants.json (inactive) + update Echinacea PowWow Wild Berry.

Genus-level resolutions:
  - Astilbe: kept genus-level (retailers carry Montgomery, Bridal Veil, Deutschland,
    Dark Side of the Moon, Garden Mix — no single cultivar overlap)
  - Heuchera: kept genus-level (retailers carry Midnight Rose, Obsidian, Electric Plum,
    Silver Scrolls, Palace Purple, Apple Twist — no overlap)
  - Bleeding Heart: kept genus-level, botanical name D. eximia (3 of 4 retailers carry
    D. eximia varieties: Fringed, Luxuriant, Pink Diamonds)
  - Bee Balm: kept genus-level (retailers carry Jacob Cline, mixes, Leading Lady Amethyst)
  - Purple Coneflower: aligned on 'Magnus' (NH + SH both carry Magnus)

Echinacea PowWow Wild Berry update:
  - zones expanded 3-8 -> 3-9 (NH fresh data confirms zone 9)
  - zone 9 planting_seasons entry added
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLANTS_FILE = PROJECT_ROOT / "data" / "plants.json"

# Standard size tiers for perennials (quart through 5gal)
PERENNIAL_SIZE_TIERS = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

# Standard planting seasons by zone
PLANTING_SEASONS = {
    "3": {"spring": "May-Jun", "fall": "Sep"},
    "4": {"spring": "Apr-May", "fall": "Sep-Oct"},
    "5": {"spring": "Apr-May", "fall": "Sep-Oct"},
    "6": {"spring": "Mar-May", "fall": "Sep-Nov"},
    "7": {"spring": "Mar-Apr", "fall": "Oct-Nov"},
    "8": {"spring": "Feb-Apr", "fall": "Oct-Dec"},
    "9": {"spring": "Feb-Mar", "fall": "Nov-Dec"},
}

# Standard perennial price seasonality
PERENNIAL_MONTHLY_INDEX = [2, 3, 4, 5, 5, 4, 3, 2, 1, 1, 2, 2]


def make_planting_seasons(zones):
    """Return planting_seasons dict for the given zone list."""
    return {str(z): PLANTING_SEASONS[str(z)] for z in zones}


def make_entry(
    id_, common_name, botanical_name, aliases, zones, sun, mature_size,
    bloom_time, type_, note, tip,
):
    """Build a complete plants.json entry dict."""
    return {
        "id": id_,
        "common_name": common_name,
        "botanical_name": botanical_name,
        "aliases": aliases,
        "category": "perennials",
        "zones": zones,
        "sun": sun,
        "mature_size": mature_size,
        "bloom_time": bloom_time,
        "type": type_,
        "size_tiers": PERENNIAL_SIZE_TIERS,
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": make_planting_seasons(zones),
        "price_seasonality": {
            "monthly_index": PERENNIAL_MONTHLY_INDEX,
            "best_buy": "September-October",
            "worst_buy": "April-May",
            "note": note,
            "tip": tip,
        },
        "active": False,
    }


# ── 8 new Batch 2 perennials ────────────────────────────────────────────

BATCH2_PLANTS = [
    make_entry(
        id_="astilbe",
        common_name="Astilbe",
        botanical_name="Astilbe spp.",
        aliases=["False Goat's Beard", "False Spirea"],
        zones=[4, 5, 6, 7, 8, 9],
        sun="Part shade to full shade",
        mature_size="18-24 in tall x 18-24 in wide",
        bloom_time="Early to mid-summer",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Astilbe is a shade garden staple with steady demand. Fall clearance offers 15-30% savings as nurseries clear inventory.",
        tip="Buy in fall for the best deals. Astilbe establishes well when fall-planted and rewards with blooms the following summer. Bareroot divisions are the most economical option.",
    ),
    make_entry(
        id_="heuchera-coral-bells",
        common_name="Heuchera (Coral Bells)",
        botanical_name="Heuchera spp.",
        aliases=["Coral Bells", "Alumroot"],
        zones=[4, 5, 6, 7, 8, 9],
        sun="Part shade to full shade",
        mature_size="10-18 in tall x 12-24 in wide",
        bloom_time="Late spring to summer",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Heuchera's colorful foliage drives premium pricing for newer cultivars. Fall clearance offers 15-30% savings.",
        tip="Buy in fall when nurseries discount foliage plants. Heuchera is semi-evergreen in mild climates, so fall planting gives roots time to establish before winter.",
    ),
    make_entry(
        id_="bleeding-heart",
        common_name="Bleeding Heart",
        botanical_name="Dicentra eximia",
        aliases=["Fringed Bleeding Heart", "Wild Bleeding Heart"],
        zones=[3, 4, 5, 6, 7, 8, 9],
        sun="Part shade to full shade",
        mature_size="12-18 in tall x 12-18 in wide",
        bloom_time="Mid-spring to fall",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Fringed bleeding heart (D. eximia) reblooms through fall unlike common bleeding heart. Fall clearance offers 15-30% savings.",
        tip="Buy in fall for clearance pricing. Fringed bleeding heart is more heat-tolerant than common bleeding heart and blooms much longer, making it the better value.",
    ),
    make_entry(
        id_="purple-coneflower",
        common_name="Purple Coneflower",
        botanical_name="Echinacea purpurea 'Magnus'",
        aliases=["Magnus Coneflower", "Eastern Purple Coneflower"],
        zones=[3, 4, 5, 6, 7, 8],
        sun="Full sun",
        mature_size="2-4 ft tall x 18-24 in wide",
        bloom_time="Summer to fall",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Magnus is the most widely grown purple coneflower cultivar. Fall clearance offers 15-30% savings.",
        tip="Buy in fall, plant in fall. Fall-planted coneflowers establish stronger root systems and bloom prolifically the following summer. Seeds from spent flowers attract goldfinches.",
    ),
    make_entry(
        id_="happy-returns-daylily",
        common_name="Happy Returns Daylily",
        botanical_name="Hemerocallis 'Happy Returns'",
        aliases=["Happy Returns", "Yellow Reblooming Daylily"],
        zones=[3, 4, 5, 6, 7, 8, 9],
        sun="Full sun to part shade",
        mature_size="18 in tall x 18-24 in wide",
        bloom_time="Late spring to fall",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Happy Returns is one of the most popular reblooming daylilies. Fall clearance offers 15-30% savings. Bareroot fans offer the best per-plant value.",
        tip="Buy bareroot fans in late winter or containerized plants in fall for the best pricing. Happy Returns reblooms all season, so you get more bloom time per dollar than single-flush daylilies.",
    ),
    make_entry(
        id_="bee-balm",
        common_name="Bee Balm",
        botanical_name="Monarda didyma",
        aliases=["Bergamot", "Oswego Tea"],
        zones=[4, 5, 6, 7, 8, 9],
        sun="Full sun to part shade",
        mature_size="3-4 ft tall x 18-24 in wide",
        bloom_time="Mid-summer to late summer",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Bee balm spreads readily, so fewer plants cover more ground than expected. Fall clearance offers 15-30% savings.",
        tip="Buy in fall or start with fewer plants than you think you need. Bee balm colonizes quickly via underground runners. Divide every 3 years to maintain vigor and share with friends.",
    ),
    make_entry(
        id_="catmint-walkers-low",
        common_name="Catmint (Walker's Low)",
        botanical_name="Nepeta x faassenii 'Walker's Low'",
        aliases=["Walker's Low Nepeta", "Walker's Low Catmint"],
        zones=[4, 5, 6, 7, 8, 9],
        sun="Full sun to part shade",
        mature_size="2-3 ft tall x 2-3 ft wide",
        bloom_time="Early summer to fall",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Walker's Low is the 2007 Perennial Plant of the Year, so it commands steady demand. Fall clearance offers 15-30% savings.",
        tip="Buy in fall for clearance pricing. Shear plants after the first flush of blooms for a strong rebloom in late summer. One of the lowest-maintenance perennials available.",
    ),
    make_entry(
        id_="russian-sage",
        common_name="Russian Sage",
        botanical_name="Salvia yangii",
        aliases=["Perovskia", "Russian Lavender"],
        zones=[4, 5, 6, 7, 8, 9],
        sun="Full sun",
        mature_size="3-5 ft tall x 2-4 ft wide",
        bloom_time="Mid-summer to fall",
        type_="Herbaceous perennial",
        note="Prices peak in spring when demand is highest. Russian sage is sometimes priced as a small shrub due to its woody base and large size. Fall clearance offers 15-30% savings.",
        tip="Buy in fall for the best deals. Russian sage thrives in poor, dry soil, so skip the expensive amended beds. One of the most drought-tolerant perennials available.",
    ),
]


def update_echinacea(plants):
    """Update Echinacea PowWow Wild Berry: zones 3-8 -> 3-9, add zone 9 planting_seasons."""
    for p in plants:
        if p["id"] == "echinacea-powwow-wild-berry":
            if 9 not in p["zones"]:
                p["zones"].append(9)
            if "9" not in p["planting_seasons"]:
                p["planting_seasons"]["9"] = PLANTING_SEASONS["9"]
            print(f"  Updated echinacea-powwow-wild-berry: zones now {p['zones']}")
            return True
    return False


def main():
    print(f"Loading {PLANTS_FILE}")
    with open(PLANTS_FILE, "r", encoding="utf-8") as f:
        plants = json.load(f)
    print(f"  Loaded {len(plants)} plants")

    # Check for duplicates
    existing_ids = {p["id"] for p in plants}
    for entry in BATCH2_PLANTS:
        if entry["id"] in existing_ids:
            print(f"  ERROR: {entry['id']} already exists in plants.json")
            sys.exit(1)

    # Update echinacea
    if not update_echinacea(plants):
        print("  WARNING: echinacea-powwow-wild-berry not found")

    # Append batch 2
    for entry in BATCH2_PLANTS:
        plants.append(entry)
        print(f"  Added: {entry['id']}")

    # Write back
    with open(PLANTS_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(plants, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Wrote {len(plants)} plants to {PLANTS_FILE}")
    print("Done.")


if __name__ == "__main__":
    main()
