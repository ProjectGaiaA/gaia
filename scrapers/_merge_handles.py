"""
Merge confirmed discovery handles into handle_maps.json.
Task 3 helper — one-time use.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# ──────────────────────────────────────────────────────────────
# Confirmed handles after human review of discovery output.
# False matches removed, variety mismatches verified.
# ──────────────────────────────────────────────────────────────

NEW_HANDLES = {
    "nature-hills": {
        "big-blue-liriope": "liriope-big-blue",
        "ajuga-chocolate-chip": "ajuga-chocolate-chip",
        "creeping-thyme": "elfin-creeping-thyme",
        "sedum-angelina": "sedum-angelina",
        "blue-rug-juniper": "juniper-blue-rug",
        "pink-muhly-grass": "pink-muhly-grass",
        "purple-fountain-grass": "dwarf-purple-fountain-grass",
        "hameln-dwarf-fountain-grass": "grass-dwarf-fountain",
        "blue-fescue-elijah-blue": "grass-elijah-blue-fescue",
        "pampas-grass": "grass-northern-pampas",
        "astilbe": "astilbe-montgomery",
        "heuchera-coral-bells": "coral-bells-midnight-rose",
        "bleeding-heart": "fringed-bleeding-heart",
        "purple-coneflower": "coneflower-magnus",
        "happy-returns-daylily": "daylily-happy-returns",
        "bee-balm": "beebalm-jacob-cline",
        "catmint-walkers-low": "catmint-walkers-low",
        "russian-sage": "russian-sage",
        "october-glory-maple": "red-maple-october-glory",
        "heritage-river-birch": "heritage-birch-tree",
        "red-sunset-maple": "red-maple-red-sunset",
        "sweetbay-magnolia": "moonglow-sweetbay-magnolia",
        "bald-cypress": "lindseys-skyward-baldcypress",
        "rose-of-sharon": "rose-of-sharon-lucy",
        "wine-and-roses-weigela": "weigela-wine-roses",
        "gardenia-frost-proof": "frost-proof-gardenia",
        "dwarf-alberta-spruce": "dwarf-alberta-spruce",
        "autumn-royalty-encore-azalea": "autumn-royalty-encore-azalea",
        "autumn-twist-encore-azalea": "autumn-twist-encore-azalea",
        "nandina-heavenly-bamboo": "heavenly-bamboo-firepower",
        "santa-rosa-plum": "plum-tree-santa-rosa",
        "echinacea-powwow-wild-berry": "pow-wow-wild-berry-coneflower",
    },
    "spring-hill": {
        "big-blue-liriope": "liriope",
        "pink-muhly-grass": "pink-muhly-grass",
        "blue-fescue-elijah-blue": "elijah-blue-fescue",
        "pampas-grass": "pink-pampas-grass",
        "astilbe": "astilbe-garden-mix",
        "heuchera-coral-bells": "electric-plum-heuchera",
        "bleeding-heart": "bleeding-heart-luxuriant",
        "purple-coneflower": "coneflower-purple-magnus",
        "happy-returns-daylily": "happy-returns-jumbo-daylily",
        "bee-balm": "bee-balm-mix",
        "russian-sage": "blue-jean-baby-russian-sage",
        "october-glory-maple": "october-glory-maple",
        "rose-of-sharon": "bluebird-hardy-hibiscus",
        "dwarf-alberta-spruce": "dwarf-alberta-spruce",
        "echinacea-powwow-wild-berry": "pow-wow-wild-berry-coneflower",
    },
    "planting-tree": {
        "big-blue-liriope": "big-blue-liriope",
        "ajuga-chocolate-chip": "ajuga-chocolate-chip",
        "sedum-angelina": "sedum-angelina",
        "blue-rug-juniper": "blue-rug-juniper",
        "pink-muhly-grass": "pink-muhly-grass",
        "pampas-grass": "pampas-grass",
        "heuchera-coral-bells": "heuchera-silver-scrolls",
        "catmint-walkers-low": "walkers-low-catmint",
        "october-glory-maple": "october-glory-maple",
        "heritage-river-birch": "heritage-river-birch",
        "red-sunset-maple": "red-sunset-maple-tree",
        "sweetbay-magnolia": "sweetbay-magnolia",
        "rose-of-sharon": "pink-chiffon-rose-of-sharon",
        "wine-and-roses-weigela": "wine-roses-weigela",
        "gardenia-frost-proof": "frost-proof-gardenia",
        "dwarf-alberta-spruce": "dwarf-alberta-spruce",
        "autumn-royalty-encore-azalea": "autumn-royalty-encore-azalea",
        "autumn-angel-encore-azalea": "autumn-angel-encore-azalea",
        "nandina-heavenly-bamboo": "heavenly-bamboo-nandina",
        "santa-rosa-plum": "santa-rosa-plum",
        "dwarf-cavendish-banana": "dwarf-cavendish-banana-tree",
    },
    "fast-growing-trees": {
        "big-blue-liriope": "big-blue-liriope-plant",
        "ajuga-chocolate-chip": "chocolate-chip-ajuga-plant",
        "sedum-angelina": "angelina-sedum-plant",
        "blue-rug-juniper": "blue-rug-juniper",
        "pink-muhly-grass": "pink-muhly-grass",
        "purple-fountain-grass": "purple-fountain-grass",
        "hameln-dwarf-fountain-grass": "dwarf-fountain-grass",
        "blue-fescue-elijah-blue": "blue-fescue-grass",
        "pampas-grass": "pampas-grass",
        "astilbe": "bridal-veil-astilbe-plant",
        "heuchera-coral-bells": "obsidian-coral-bells-heuchera",
        "happy-returns-daylily": "happy-returns-daylily",
        "catmint-walkers-low": "walkers-low-nepeta-catmint",
        "russian-sage": "russian-sage",
        "october-glory-maple": "octoberglory",
        "heritage-river-birch": "heritage-river-birch",
        "red-sunset-maple": "red-sunset-maple-tree",
        "sweetbay-magnolia": "sweetbaymagnolia",
        "rose-of-sharon": "lavender-rose-sharon-althea-tree",
        "wine-and-roses-weigela": "wine-roses-weigela-shrub",
        "gardenia-frost-proof": "frost-proof-gardenia",
        "dwarf-alberta-spruce": "dwarf-alberta-spruce",
        "autumn-royalty-encore-azalea": "autumnroyaltyencoreazalea",
        "autumn-twist-encore-azalea": "autumn-twist-encore-azalea",
        "autumn-angel-encore-azalea": "autumnangelencoreazalea",
        "nandina-heavenly-bamboo": "heavenly-bamboo-nandina-shrub",
        "santa-rosa-plum": "santarosaplum",
        "dwarf-cavendish-banana": "dwarf-cavendish-banana-tree",
        "vinca-minor": "vinca-minor-periwinkle-plant",
        "echinacea-powwow-wild-berry": "powwow-wild-berry-coneflower",
    },
    "proven-winners-direct": {
        "astilbe": "dark-side-of-the-moon-astilbe",
        "heuchera-coral-bells": "dolce-apple-twist-coral-bells",
        "bleeding-heart": "pink-diamonds-fern-leaved-bleeding-heart",
        "bee-balm": "leading-lady-amethyst-bee-balm",
        "russian-sage": "sage-advice-russian-sage",
        "rose-of-sharon": "azurri-blue-satin-rose-of-sharon",
        "wine-and-roses-weigela": "wine-and-roses-weigela",
    },
    "brecks": {
        "creeping-thyme": "red-creeping-thyme",
        "pink-muhly-grass": "cotton-candy-grass",
        "blue-fescue-elijah-blue": "elijah-blue-fescue",
        "astilbe": "astilbe-deutschland-white",
        "heuchera-coral-bells": "palace-purple-heuchera",
        "bleeding-heart": "bacchanal-bleeding-heart",
        "purple-coneflower": "purple-coneflower-super-sak",
        "happy-returns-daylily": "happy-returns-reblooming-daylily",
        "bee-balm": "balm-bee-mixture",
        "russian-sage": "lacey-blue-russian-sage",
        "dwarf-alberta-spruce": "dwarf-alberta-tree-spruce",
    },
}


def main():
    handle_maps_path = DATA_DIR / "handle_maps.json"
    with open(handle_maps_path, encoding="utf-8") as f:
        handle_maps = json.load(f)

    total_added = 0
    for retailer_id, new_entries in NEW_HANDLES.items():
        if retailer_id not in handle_maps:
            handle_maps[retailer_id] = {}
        existing = handle_maps[retailer_id]
        added = 0
        for plant_id, handle in new_entries.items():
            if plant_id not in existing:
                existing[plant_id] = handle
                added += 1
            else:
                print(f"  SKIP {retailer_id}/{plant_id}: already mapped to '{existing[plant_id]}'")
        total_added += added
        print(f"  {retailer_id}: +{added} new handles ({len(existing)} total)")

    with open(handle_maps_path, "w", encoding="utf-8") as f:
        json.dump(handle_maps, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nTotal: {total_added} new handles added to handle_maps.json")


if __name__ == "__main__":
    main()
