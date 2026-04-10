"""
Targeted Handle Discovery for Catalog Expansion Candidates

Task 3 helper — finds Shopify product handles for 37 candidate plants
(35 new + 2 reactivation) across all active Shopify retailers.

Uses retailer sitemaps for fast, low-impact discovery:
- 1-2 HTTP requests per retailer (sitemap index + product sitemap)
- Matches candidate names against product handles and image titles
- Uses polite.py for request etiquette

Usage:
    python -m scrapers._discover_candidates
    python -m scrapers._discover_candidates --retailer nature-hills
"""

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scrapers.polite import make_polite_session, polite_delay, is_allowed_by_robots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

# ──────────────────────────────────────────────────────────────
# 37 candidates: 35 new + 2 reactivation
# ──────────────────────────────────────────────────────────────
CANDIDATES = [
    # Batch 1: Groundcovers (6)
    {"id": "big-blue-liriope", "name": "Big Blue Liriope", "botanical": "Liriope muscari 'Big Blue'"},
    {"id": "ajuga-chocolate-chip", "name": "Ajuga Chocolate Chip", "botanical": "Ajuga reptans 'Chocolate Chip'"},
    {"id": "creeping-thyme", "name": "Creeping Thyme", "botanical": "Thymus serpyllum"},
    {"id": "sedum-angelina", "name": "Sedum Angelina", "botanical": "Sedum rupestre 'Angelina'"},
    {"id": "blue-rug-juniper", "name": "Blue Rug Juniper", "botanical": "Juniperus horizontalis 'Wiltonii'"},
    {"id": "mondo-grass", "name": "Mondo Grass", "botanical": "Ophiopogon japonicus"},
    # Batch 1: Grasses (5)
    {"id": "pink-muhly-grass", "name": "Pink Muhly Grass", "botanical": "Muhlenbergia capillaris"},
    {"id": "purple-fountain-grass", "name": "Purple Fountain Grass", "botanical": "Pennisetum setaceum 'Rubrum'"},
    {"id": "hameln-dwarf-fountain-grass", "name": "Hameln Dwarf Fountain Grass", "botanical": "Pennisetum alopecuroides 'Hameln'"},
    {"id": "blue-fescue-elijah-blue", "name": "Blue Fescue Elijah Blue", "botanical": "Festuca glauca 'Elijah Blue'"},
    {"id": "pampas-grass", "name": "Pampas Grass", "botanical": "Cortaderia selloana"},
    # Batch 2: Perennials (8)
    {"id": "astilbe", "name": "Astilbe", "botanical": "Astilbe"},
    {"id": "heuchera-coral-bells", "name": "Heuchera Coral Bells", "botanical": "Heuchera"},
    {"id": "bleeding-heart", "name": "Bleeding Heart", "botanical": "Lamprocapnos spectabilis"},
    {"id": "purple-coneflower", "name": "Purple Coneflower", "botanical": "Echinacea purpurea"},
    {"id": "happy-returns-daylily", "name": "Happy Returns Daylily", "botanical": "Hemerocallis 'Happy Returns'"},
    {"id": "bee-balm", "name": "Bee Balm", "botanical": "Monarda"},
    {"id": "catmint-walkers-low", "name": "Catmint Walkers Low", "botanical": "Nepeta x faassenii 'Walker's Low'"},
    {"id": "russian-sage", "name": "Russian Sage", "botanical": "Perovskia atriplicifolia"},
    # Batch 3: Shade Trees (5)
    {"id": "october-glory-maple", "name": "October Glory Maple", "botanical": "Acer rubrum 'October Glory'"},
    {"id": "heritage-river-birch", "name": "Heritage River Birch", "botanical": "Betula nigra 'Heritage'"},
    {"id": "red-sunset-maple", "name": "Red Sunset Maple", "botanical": "Acer rubrum 'Red Sunset'"},
    {"id": "sweetbay-magnolia", "name": "Sweetbay Magnolia", "botanical": "Magnolia virginiana"},
    {"id": "bald-cypress", "name": "Bald Cypress", "botanical": "Taxodium distichum"},
    # Batch 3: Flowering Trees/Shrubs (4)
    {"id": "rose-of-sharon", "name": "Rose of Sharon", "botanical": "Hibiscus syriacus"},
    {"id": "wine-and-roses-weigela", "name": "Wine and Roses Weigela", "botanical": "Weigela florida 'Wine & Roses'"},
    {"id": "spirea-goldflame", "name": "Spirea Goldflame", "botanical": "Spiraea japonica 'Goldflame'"},
    {"id": "gardenia-frost-proof", "name": "Gardenia Frost Proof", "botanical": "Gardenia jasminoides 'Frost Proof'"},
    # Batch 3: Privacy Trees (1)
    {"id": "dwarf-alberta-spruce", "name": "Dwarf Alberta Spruce", "botanical": "Picea glauca 'Conica'"},
    # Batch 4: Azaleas (3)
    {"id": "autumn-royalty-encore-azalea", "name": "Autumn Royalty Encore Azalea", "botanical": "Rhododendron 'Conlep' (Encore)"},
    {"id": "autumn-twist-encore-azalea", "name": "Autumn Twist Encore Azalea", "botanical": "Rhododendron 'Conleb' (Encore)"},
    {"id": "autumn-angel-encore-azalea", "name": "Autumn Angel Encore Azalea", "botanical": "Rhododendron 'Conleu' (Encore)"},
    # Batch 4: Privacy Trees (1)
    {"id": "nandina-heavenly-bamboo", "name": "Nandina Heavenly Bamboo", "botanical": "Nandina domestica"},
    # Batch 4: Fruit Trees (2)
    {"id": "santa-rosa-plum", "name": "Santa Rosa Plum", "botanical": "Prunus salicina 'Santa Rosa'"},
    {"id": "dwarf-cavendish-banana", "name": "Dwarf Cavendish Banana", "botanical": "Musa acuminata 'Dwarf Cavendish'"},
    # Reactivation candidates
    {"id": "vinca-minor", "name": "Vinca Minor", "botanical": "Vinca minor"},
    {"id": "echinacea-powwow-wild-berry", "name": "Echinacea PowWow Wild Berry", "botanical": "Echinacea purpurea 'PowWow Wild Berry'"},
]

# Active Shopify retailers (from retailers.json where scraper_type=shopify and active=true)
SHOPIFY_RETAILERS = {
    "nature-hills": "https://naturehills.com",
    "spring-hill": "https://springhillnursery.com",
    "planting-tree": "https://www.plantingtree.com",
    "fast-growing-trees": "https://www.fast-growing-trees.com",
    "proven-winners-direct": "https://provenwinnersdirect.com",
    "brecks": "https://www.brecks.com",
    "plant-addicts": "https://www.plantaddicts.com",
    "bloomscape": "https://www.bloomscape.com",
}

SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
IMG_NS = {"image": "http://www.google.com/schemas/sitemap-image/1.1"}


def normalize(text):
    """Normalize text for fuzzy matching."""
    text = text.lower().strip()
    text = re.sub(r"[®™©''']", "", text)
    text = re.sub(r"[&]", "and", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def word_overlap_score(name, target):
    """Score based on word overlap. 0-1."""
    name_words = set(normalize(name).split())
    target_words = set(normalize(target).split())
    noise = {"the", "a", "an", "of", "for", "and", "or", "in", "at", "to", "by",
             "tree", "shrub", "bush", "plant", "buy", "sale", "online", "live"}
    name_words -= noise
    target_words -= noise
    if not name_words:
        return 0.0
    overlap = name_words & target_words
    return len(overlap) / len(name_words)


def fetch_sitemap_index(base_url, session):
    """Fetch and parse the sitemap index. Returns list of product sitemap URLs."""
    sitemap_url = f"{base_url}/sitemap.xml"
    if not is_allowed_by_robots(sitemap_url):
        logger.warning("  robots.txt disallows sitemap — skipping")
        return []

    try:
        resp = session.get(sitemap_url, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"  sitemap.xml returned {resp.status_code}")
            return []

        root = ET.fromstring(resp.content)
        product_urls = []
        for loc in root.findall(".//sm:sitemap/sm:loc", SM_NS):
            url = loc.text
            if url and "product" in url.lower():
                product_urls.append(url)

        if not product_urls:
            # Try common Shopify sitemap URL directly
            product_urls = [f"{base_url}/sitemap_products_1.xml"]

        return product_urls

    except Exception as e:
        logger.error(f"  Error fetching sitemap index: {e}")
        return []


def fetch_product_sitemap(url, session):
    """Fetch a product sitemap and extract handle + title pairs."""
    products = []
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"  Product sitemap {url} returned {resp.status_code}")
            return products

        root = ET.fromstring(resp.content)
        for url_elem in root.findall(".//sm:url", SM_NS):
            loc = url_elem.find("sm:loc", SM_NS)
            if loc is None or loc.text is None:
                continue

            loc_text = loc.text
            handle_match = re.search(r"/products/([^/?#]+)", loc_text)
            if not handle_match:
                continue

            handle = handle_match.group(1)

            # Try to get image title (often = product title)
            title = ""
            img_title = url_elem.find(".//image:title", IMG_NS)
            if img_title is not None and img_title.text:
                title = img_title.text.strip()

            products.append({"handle": handle, "title": title, "url": loc_text})

    except Exception as e:
        logger.error(f"  Error parsing product sitemap: {e}")

    return products


def match_candidates(products, candidates):
    """Match candidate plants against discovered products. Returns dict of matches."""
    matches = {}

    for candidate in candidates:
        cid = candidate["id"]
        cname = candidate["name"]
        cbot = candidate.get("botanical", "")
        cid_words = cid.replace("-", " ")

        best = None
        best_score = 0.0

        for product in products:
            handle = product["handle"]
            title = product.get("title", "")
            handle_words = handle.replace("-", " ")

            # Score 1: candidate name vs product title
            s1 = word_overlap_score(cname, title) if title else 0.0

            # Score 2: candidate name vs handle
            s2 = word_overlap_score(cname, handle_words)

            # Score 3: candidate ID vs handle (direct slug match)
            s3 = word_overlap_score(cid_words, handle_words)

            # Score 4: botanical name vs title
            s4 = word_overlap_score(cbot, title) * 0.7 if (title and cbot) else 0.0

            # Score 5: exact substring match bonus
            s5 = 0.0
            norm_handle = normalize(handle_words)
            norm_cid = normalize(cid_words)
            if norm_cid in norm_handle or norm_handle in norm_cid:
                s5 = 0.9

            score = max(s1, s2, s3, s4, s5)

            if score > best_score:
                best_score = score
                best = {
                    "handle": handle,
                    "title": title,
                    "score": round(score, 3),
                    "url": product.get("url", ""),
                }

        if best and best_score >= 0.55:
            matches[cid] = best

    return matches


def discover_retailer(rid, base_url, session):
    """Discover handles for all candidates at one retailer via sitemap."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Retailer: {rid} ({base_url})")
    logger.info(f"{'=' * 60}")

    # Fetch sitemap index
    product_sitemap_urls = fetch_sitemap_index(base_url, session)
    if not product_sitemap_urls:
        logger.warning("  No product sitemaps found")
        return {}

    logger.info(f"  Found {len(product_sitemap_urls)} product sitemap(s)")

    # Fetch all product sitemaps
    all_products = []
    for i, psurl in enumerate(product_sitemap_urls):
        if i > 0:
            polite_delay(3.0, 6.0)
        products = fetch_product_sitemap(psurl, session)
        all_products.extend(products)
        logger.info(f"  Sitemap {i + 1}: {len(products)} products")

    logger.info(f"  Total products: {len(all_products)}")

    if not all_products:
        return {}

    # Match candidates
    matches = match_candidates(all_products, CANDIDATES)

    if matches:
        logger.info(f"  Found {len(matches)} candidate matches:")
        for cid, m in sorted(matches.items(), key=lambda x: -x[1]["score"]):
            conf = "HIGH" if m["score"] >= 0.8 else "MED" if m["score"] >= 0.6 else "LOW"
            logger.info(f"    [{conf}] {cid} -> {m['handle']} (score={m['score']}, title={m['title'][:60]})")
    else:
        logger.info("  No candidate matches found")

    return matches


def main():
    parser = argparse.ArgumentParser(description="Discover handles for catalog expansion candidates")
    parser.add_argument("--retailer", type=str, help="Single retailer to check")
    args = parser.parse_args()

    retailers = SHOPIFY_RETAILERS
    if args.retailer:
        if args.retailer not in retailers:
            logger.error(f"Unknown retailer: {args.retailer}")
            sys.exit(1)
        retailers = {args.retailer: retailers[args.retailer]}

    session = make_polite_session()
    all_results = {}

    for rid, base_url in retailers.items():
        matches = discover_retailer(rid, base_url, session)
        all_results[rid] = matches
        polite_delay(5.0, 10.0)  # Delay between retailers

    # ── Summary ──
    logger.info(f"\n{'=' * 60}")
    logger.info("DISCOVERY SUMMARY")
    logger.info(f"{'=' * 60}")

    # Per-candidate retailer count
    candidate_retailers = {}
    for candidate in CANDIDATES:
        cid = candidate["id"]
        found_at = []
        for rid, matches in all_results.items():
            if cid in matches:
                found_at.append(rid)
        candidate_retailers[cid] = found_at

    passing = []
    failing = []
    for candidate in CANDIDATES:
        cid = candidate["id"]
        retailers_found = candidate_retailers[cid]
        count = len(retailers_found)
        status = "PASS" if count >= 2 else "FAIL"
        line = f"  [{status}] {candidate['name']}: {count} retailers ({', '.join(retailers_found) or 'none'})"
        logger.info(line)
        if count >= 2:
            passing.append(candidate)
        else:
            failing.append(candidate)

    logger.info(f"\n  PASS: {len(passing)} plants (2+ retailers)")
    logger.info(f"  FAIL: {len(failing)} plants (<2 retailers)")

    # Save results
    output = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "retailers_checked": list(retailers.keys()),
        "candidates_total": len(CANDIDATES),
        "passing": len(passing),
        "failing": len(failing),
        "per_retailer": {},
        "per_candidate": {},
        "failing_plants": [{"id": c["id"], "name": c["name"], "retailers_found": candidate_retailers[c["id"]]} for c in failing],
    }

    for rid, matches in all_results.items():
        output["per_retailer"][rid] = {
            cid: {"handle": m["handle"], "title": m["title"], "score": m["score"]}
            for cid, m in matches.items()
        }

    for candidate in CANDIDATES:
        cid = candidate["id"]
        output["per_candidate"][cid] = {
            "name": candidate["name"],
            "retailers_found": len(candidate_retailers[cid]),
            "handles": {
                rid: all_results[rid][cid]["handle"]
                for rid in candidate_retailers[cid]
            },
        }

    output_path = DATA_DIR / "discovery_candidates_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    logger.info(f"\nResults saved to {output_path}")

    # Print handle_maps.json additions for easy copy
    logger.info(f"\n{'=' * 60}")
    logger.info("HANDLE MAP ADDITIONS (for handle_maps.json):")
    logger.info(f"{'=' * 60}")
    for rid, matches in sorted(all_results.items()):
        if not matches:
            continue
        logger.info(f'\n  "{rid}":')
        for cid in sorted(matches.keys()):
            m = matches[cid]
            logger.info(f'    "{cid}": "{m["handle"]}",')


if __name__ == "__main__":
    main()
