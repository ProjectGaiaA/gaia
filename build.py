"""
Project Gaia — Static Site Generator

Reads plant data, price data, and article markdown files.
Renders Jinja2 templates to static HTML in site/ directory.

Usage:
    python build.py              # Full build
    python build.py --guides     # Only rebuild guide pages
    python build.py --products   # Only rebuild product pages
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, date

import jinja2
import markdown

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
SITE_DIR = os.path.join(BASE_DIR, "site")
ARTICLES_DIR = BASE_DIR  # Article .md files are in project root
PRICES_DIR = os.path.join(DATA_DIR, "prices")


# ---------------------------------------------------------------------------
# Size tier normalization
# ---------------------------------------------------------------------------
# Different retailers label the same physical size differently.
# This map normalizes raw_size strings (and scraper tier keys) to canonical
# display labels so comparison tables group correctly.
#
# Key   = canonical tier ID (what the scraper already emits, or should emit)
# Value = human-readable label shown in the comparison table
#
SIZE_TIER_LABELS = {
    # Container / gallon sizes
    "quart":   "Quart",
    "1gal":    "1 Gallon",
    "2gal":    "2 Gallon",
    "3gal":    "3 Gallon",
    "5gal":    "5 Gallon",
    "7gal":    "7 Gallon",
    "10gal":   "10 Gallon",
    "15gal":   "15 Gallon",
    # Bare-root / dormant
    "bareroot":          "Bare Root",
    "jumbo-bareroot":    "Jumbo Bare Root",
    "premium-bareroot":  "Premium Bare Root",
    # Height tiers (trees)
    "1-2ft":  "1-2 ft",
    "2-3ft":  "2-3 ft",
    "3-4ft":  "3-4 ft",
    "4-5ft":  "4-5 ft",
    "5-6ft":  "5-6 ft",
    "6-7ft":  "6-7 ft",
    "7-8ft":  "7-8 ft",
    "8-9ft":  "8-9 ft",
    # Stark Bros rootstock tiers
    "dwarf":             "Dwarf",
    "semi-dwarf":        "Semi-Dwarf",
    "supreme":           "Supreme",
    "ultra-supreme":     "Ultra Supreme",
    "standard":          "Standard",
    "dwarf-bareroot":    "Dwarf (Bare Root)",
    "semi-dwarf-bareroot": "Semi-Dwarf (Bare Root)",
    "supreme-bareroot":  "Supreme (Bare Root)",
    "dwarf-potted":      "Dwarf (Potted)",
    "semi-dwarf-potted": "Semi-Dwarf (Potted)",
    "potted":            "Potted",
    # EZ Start variants
    "dwarf-ez-start":      "Dwarf EZ Start",
    "semi-dwarf-ez-start": "Semi-Dwarf EZ Start",
    "supreme-ez-start":    "Supreme EZ Start",
    # Bulb / specialty
    "bulb":    "Bulb",
    "default": "Best Available",
    # Inch pot
    "3inch":   "3\" Pot",
    "4inch":   "4\" Pot",
    "6inch":   "6\" Pot",
    # Field-grown inch sizes (Spring Hill FIELD variants)
    "12-18in": "12-18\"",
    "18-24in": "18-24\"",
    "24-36in": "24-36\"",
    "36-48in": "36-48\"",
    "48-54in": "48-54\"",
}

# Aliases: raw variant strings → canonical tier IDs.
# Used when a retailer's scraper emits a non-canonical tier key
# (e.g. "1-gallon-pot", "#1-container") that slipped through _normalize_size.
_SIZE_ALIASES = {
    # Common misspellings / alternative phrasings that may appear as tier keys
    "1-gallon": "1gal",
    "1-gallon-pot": "1gal",
    "1gal-pot": "1gal",
    "1-gal": "1gal",
    "1gallon": "1gal",
    "#1": "1gal",
    "#1-container": "1gal",
    "1-container": "1gal",
    "2-gallon": "2gal",
    "2-gallon-pot": "2gal",
    "2-gal": "2gal",
    "2gallon": "2gal",
    "#2": "2gal",
    "#2-container": "2gal",
    "3-gallon": "3gal",
    "3-gallon-pot": "3gal",
    "3-gal": "3gal",
    "3gallon": "3gal",
    "#3": "3gal",
    "#3-container": "3gal",
    "5-gallon": "5gal",
    "5-gallon-pot": "5gal",
    "5-gal": "5gal",
    "5gallon": "5gal",
    "#5": "5gal",
    "#5-container": "5gal",
    "qt": "quart",
    "quart-container": "quart",
    "bare-root": "bareroot",
    "bare root": "bareroot",
    "dormant": "bareroot",
    # Typos and alternate spellings observed in scraped data
    "1-galllon": "1gal",        # triple-l typo
    "2-gallons": "2gal",        # plural form
    "3-gallons": "3gal",
    "5-gallons": "5gal",
    "3-pot": "3inch",           # Spring Hill "3\" POT" variant
    "6-inch-pot": "6inch",
    "trade-gallon": "1gal",
}


def normalize_size_tier(tier: str) -> str:
    """Normalize a size tier key to its canonical form.

    Handles aliases that slip through the scraper's _normalize_size() —
    e.g. "#1-container", "2-gallon-pot", "bare-root".
    Returns the canonical tier ID (e.g. "1gal", "bareroot").
    """
    t = tier.strip().lower()
    return _SIZE_ALIASES.get(t, tier)


def get_size_label(tier: str) -> str:
    """Return the human-readable label for a canonical size tier."""
    canonical = normalize_size_tier(tier)
    return SIZE_TIER_LABELS.get(canonical, canonical.replace("-", " ").title())


def load_json(path):
    """Load a JSON file, return empty list/dict on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  Warning: Could not load {path}: {e}")
        return []


def load_prices(plant_id):
    """Load JSONL price history for a plant. Returns list of dicts."""
    path = os.path.join(PRICES_DIR, f"{plant_id}.jsonl")
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def get_latest_prices(price_entries, retailers_by_id):
    """Get the most recent price per retailer per size tier from price history."""
    latest = {}
    for entry in reversed(price_entries):
        retailer_id = entry.get("retailer_id", "")
        if retailer_id not in latest:
            latest[retailer_id] = entry
    return latest


def build_price_table(plant, latest_prices, retailers_by_id, promos_by_retailer=None):
    """Build structured price data for the comparison table template."""
    prices = {}
    all_prices_flat = []
    active_tiers = set()
    has_non_affiliate = False
    any_in_stock = False

    for retailer_id, price_data in latest_prices.items():
        retailer = retailers_by_id.get(retailer_id)
        if not retailer:
            continue

        # Check staleness (>3 days old = suppress)
        timestamp = price_data.get("timestamp", "")
        if timestamp:
            try:
                scrape_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
                if (date.today() - scrape_date).days > 3:
                    continue  # Suppress stale data
            except (ValueError, TypeError):
                pass

        has_affiliate = retailer.get("affiliate") is not None and retailer.get("trust_builder") is not True
        if not has_affiliate:
            has_non_affiliate = True

        sizes = {}
        for raw_tier, price_info in price_data.get("sizes", {}).items():
            # Normalize the tier key so variants like "#1-container" → "1gal"
            tier = normalize_size_tier(raw_tier)
            if isinstance(price_info, dict):
                price = price_info.get("price")
                if price is not None and price > 0:
                    # If two raw tiers normalize to the same canonical tier, keep cheaper
                    if tier in sizes and sizes[tier]["price"] <= price:
                        continue
                    sizes[tier] = {
                        "price": price,
                        "was_price": price_info.get("was_price"),
                        "is_best": False,
                        "label": get_size_label(tier),
                    }
                    all_prices_flat.append(price)
                    active_tiers.add(tier)
            elif isinstance(price_info, (int, float)) and price_info > 0:
                if tier in sizes and sizes[tier]["price"] <= price_info:
                    continue
                sizes[tier] = {
                    "price": price_info,
                    "was_price": None,
                    "is_best": False,
                    "label": get_size_label(tier),
                }
                all_prices_flat.append(price_info)
                active_tiers.add(tier)

        in_stock = price_data.get("in_stock", None)
        if in_stock:
            any_in_stock = True

        # Detect "Ships in Spring/Fall" from variant raw_size text
        ships_season = None
        for tier_data in sizes.values():
            raw = tier_data.get("raw_size", "") if isinstance(tier_data, dict) else ""
            import re as _re
            season_match = _re.search(r'ships?\s+in\s+(spring|fall|summer|winter)', raw, _re.IGNORECASE)
            if season_match:
                ships_season = season_match.group(1).title()
                break

        # Attach promo data if available for this retailer
        promo_info = None
        if promos_by_retailer:
            raw_promo = promos_by_retailer.get(retailer_id, {})
            codes = raw_promo.get("codes", [])
            banners = raw_promo.get("banners", [])
            if codes or banners:
                promo_info = {"codes": codes, "banners": banners}

        prices[retailer_id] = {
            "retailer_name": retailer["name"],
            "sizes": sizes,
            "in_stock": in_stock,
            "has_affiliate": has_affiliate,
            "has_best_price": False,
            "buy_url": price_data.get("url", retailer.get("url", "#")),
            "shipping": retailer.get("shipping"),
            "ships_season": ships_season,
            "promo": promo_info,
        }

    # Mark best price per tier
    # Full canonical order — tiers not in this list sort to the end alphabetically
    tier_order = [
        "quart", "1gal", "2gal", "3gal", "5gal", "7gal", "10gal", "15gal",
        "bareroot", "jumbo-bareroot", "premium-bareroot",
        "1-2ft", "2-3ft", "3-4ft", "4-5ft", "5-6ft", "6-7ft", "7-8ft", "8-9ft",
        "dwarf", "dwarf-bareroot", "dwarf-ez-start", "dwarf-potted",
        "semi-dwarf", "semi-dwarf-bareroot", "semi-dwarf-ez-start", "semi-dwarf-potted",
        "supreme", "supreme-bareroot", "supreme-ez-start",
        "ultra-supreme", "standard", "potted",
        "bulb", "3inch", "4inch", "6inch", "default",
        "12-18in", "18-24in", "24-36in", "36-48in", "48-54in",
    ]
    known = set(tier_order)
    leftover = sorted(t for t in active_tiers if t not in known)
    active_tiers_sorted = [t for t in tier_order if t in active_tiers] + leftover

    for tier in active_tiers_sorted:
        best_price = float("inf")
        best_retailer = None
        for rid, rdata in prices.items():
            # Only consider in-stock or unknown-stock retailers for best price
            # Sold out (in_stock == False) should NOT win best price
            if rdata["in_stock"] is False:
                continue
            if tier in rdata["sizes"] and rdata["sizes"][tier]["price"] < best_price:
                best_price = rdata["sizes"][tier]["price"]
                best_retailer = rid
        if best_retailer:
            prices[best_retailer]["sizes"][tier]["is_best"] = True
            prices[best_retailer]["has_best_price"] = True

    # Sort retailers: in-stock cheapest first, no-price next, sold-out last
    def _retailer_sort_key(item):
        rid, rdata = item
        if rdata["in_stock"] is False:
            return (2, float("inf"))
        tier_prices = [
            s["price"] for s in rdata["sizes"].values()
            if isinstance(s, dict) and s.get("price")
        ]
        if not tier_prices:
            return (1, float("inf"))
        return (0, min(tier_prices))

    prices = dict(sorted(prices.items(), key=_retailer_sort_key))

    lowest = min(all_prices_flat) if all_prices_flat else None
    highest = max(all_prices_flat) if all_prices_flat else None
    savings_pct = round((1 - lowest / highest) * 100) if lowest and highest and highest > 0 else 0

    return {
        "prices": prices,
        "active_size_tiers": active_tiers_sorted,
        "lowest_price": lowest,
        "highest_price": highest,
        "savings_pct": savings_pct,
        "offer_count": len(prices),
        "any_in_stock": any_in_stock,
        "has_non_affiliate": has_non_affiliate,
    }


def build_price_history_json(price_entries):
    """Build Chart.js-compatible price history data."""
    if len(price_entries) < 2:
        return None

    # Group by date and retailer
    by_date = defaultdict(dict)
    retailer_names = {}
    for entry in price_entries:
        ts = entry.get("timestamp", "")[:10]
        rid = entry.get("retailer_id", "")
        rname = entry.get("retailer_name", rid)
        retailer_names[rid] = rname
        # Use the lowest price across all size tiers for the chart
        sizes = entry.get("sizes", {})
        prices_list = []
        for v in sizes.values():
            if isinstance(v, dict) and v.get("price"):
                prices_list.append(v["price"])
            elif isinstance(v, (int, float)) and v > 0:
                prices_list.append(v)
        if prices_list:
            by_date[ts][rid] = min(prices_list)

    dates = sorted(by_date.keys())
    retailers = sorted(retailer_names.keys())

    return json.dumps({
        "dates": dates,
        "retailers": [
            {
                "name": retailer_names[rid],
                "prices": [by_date[d].get(rid) for d in dates],
            }
            for rid in retailers
        ],
    })


# ---------------------------------------------------------------------------
# Heat map helpers
# ---------------------------------------------------------------------------
_MONTH_ABBR = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

def parse_month_range(s):
    """Parse 'May-Jun', 'Sep', 'Mar-May' → list of month numbers (1-12)."""
    if not s:
        return []
    parts = re.split(r'[-\u2013]', s.strip())
    parsed = [_MONTH_ABBR.get(p.strip().lower()[:3]) for p in parts]
    parsed = [m for m in parsed if m]
    if len(parsed) == 1:
        return parsed
    if len(parsed) >= 2:
        start, end = parsed[0], parsed[1]
        if start <= end:
            return list(range(start, end + 1))
        # Wraps year-end (e.g. Nov-Jan)
        return list(range(start, 13)) + list(range(1, end + 1))
    return []


def build_heatmap_data(plants):
    """
    Aggregate per-category price seasonality and zone planting windows.
    Returns (categories_list, hm_data_dict) for template + JS.
    """
    from collections import defaultdict

    cat_plants = defaultdict(list)
    for p in plants:
        if p.get('price_seasonality') or p.get('planting_seasons'):
            cat_plants[p.get('category', 'uncategorized')].append(p)

    all_zones = list(range(3, 10))  # 3–9
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    categories = []
    hm_data = {}  # keyed by cat id, used for JS zone-switching

    for cat_id, cat_plant_list in sorted(cat_plants.items()):
        # --- Average monthly price index across plants that have it ---
        index_lists = [
            p['price_seasonality']['monthly_index']
            for p in cat_plant_list
            if p.get('price_seasonality', {}).get('monthly_index')
            and len(p['price_seasonality']['monthly_index']) == 12
        ]
        if index_lists:
            avg_index = [
                round(sum(index_lists[r][m] for r in range(len(index_lists))) / len(index_lists))
                for m in range(12)
            ]
            # Clamp to 1–5
            avg_index = [max(1, min(5, v)) for v in avg_index]
        else:
            avg_index = [3] * 12  # default: all average

        # best_buy / worst_buy / tip from most representative plant
        best_buy = worst_buy = tip = ''
        for p in cat_plant_list:
            seas = p.get('price_seasonality', {})
            if seas.get('best_buy'):
                best_buy = seas['best_buy']
                worst_buy = seas.get('worst_buy', '')
                tip = seas.get('tip', '')
                break

        # --- Union planting windows per zone ---
        planting_by_zone = {}
        for z in all_zones:
            zk = str(z)
            plantable = [False] * 12
            for p in cat_plant_list:
                seasons = p.get('planting_seasons', {})
                if zk not in seasons:
                    continue
                z_seasons = seasons[zk]
                for season_type in ('spring', 'fall', 'summer'):
                    months = parse_month_range(z_seasons.get(season_type, ''))
                    for m in months:
                        if 1 <= m <= 12:
                            plantable[m - 1] = True
            planting_by_zone[zk] = plantable

        cat_entry = {
            'id': cat_id,
            'name': cat_id.replace('-', ' ').title(),
            'monthly_price_index': avg_index,
            'best_buy': best_buy or 'Fall',
            'worst_buy': worst_buy or 'Spring',
            'tip': tip,
            'planting_by_zone': planting_by_zone,
            'planting_zones_json': json.dumps(planting_by_zone),
        }
        categories.append(cat_entry)
        hm_data[cat_id] = {'planting_by_zone': planting_by_zone}

    return categories, hm_data, all_zones, month_names


def find_similar_plants(plant, all_plants, n=5):
    """Find similar plants in the same category."""
    same_cat = [p for p in all_plants if p["category"] == plant["category"] and p["id"] != plant["id"]]
    return same_cat[:n]


def parse_article_md(filepath):
    """Parse a markdown article file. Extract title from first H1, rest is content."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # Extract title from first # heading
    title_match = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1) if title_match else os.path.basename(filepath)

    # Extract excerpt (first paragraph after title)
    lines = text.split("\n")
    excerpt = ""
    in_content = False
    for line in lines:
        if line.startswith("# "):
            in_content = True
            continue
        if in_content and line.strip() and not line.startswith("*") and not line.startswith("#"):
            excerpt = line.strip()[:200]
            break

    # Convert markdown to HTML
    md = markdown.Markdown(extensions=["extra", "toc"])
    html = md.convert(text)

    # Strip the first <h1> — guide.html renders the title as its own H1 to avoid duplicate H1s
    html = re.sub(r'^<h1[^>]*>.*?</h1>\s*', '', html, count=1, flags=re.DOTALL)

    # Fix internal links: add .html extension to /plants/ and /category/ links
    html = re.sub(
        r'href="(/(?:plants|category|guides)/[^"]+?)(?<!\.html)"',
        r'href="\1.html"',
        html
    )

    # Build TOC from H2 headings
    toc = []
    for match in re.finditer(r"^##\s+(.+?)(?:\s*\(.*?\))?\s*$", text, re.MULTILINE):
        heading_text = match.group(1).strip()
        heading_id = re.sub(r"[^a-z0-9]+", "-", heading_text.lower()).strip("-")
        toc.append({"id": heading_id, "text": heading_text})

    # Generate slug from filename
    basename = os.path.basename(filepath)
    slug = re.sub(r"^\d+-", "", basename).replace(".md", "")

    # Extract meta description from first paragraph
    meta_desc = excerpt if excerpt else f"{title} - Compare prices across online nurseries."

    return {
        "title": title,
        "slug": slug,
        "content": html,
        "excerpt": excerpt,
        "toc": toc,
        "meta_description": meta_desc[:160],
    }


def find_related_plants_for_guide(guide_slug, all_plants):
    """Map guide articles to their related plant category."""
    slug_to_category = {
        "best-hydrangeas-to-buy-online": "hydrangeas",
        "best-fruit-trees-to-buy-online": "fruit-trees",
        "best-privacy-trees": "privacy-trees",
        "cheapest-places-to-buy-online": None,  # All categories
        "best-japanese-maple-varieties": "japanese-maples",
        "best-knock-out-roses": "roses",
        "best-blueberry-bushes": "blueberries",
        "best-flowering-trees-small-yards": "flowering-trees",
        "best-azaleas-rhododendrons": "azaleas-rhododendrons",
        "best-time-to-buy-plants-online": None,  # All categories
    }
    category = slug_to_category.get(guide_slug)
    if category is None:
        return all_plants[:10]
    return [p for p in all_plants if p.get("category") == category][:10]


_CATEGORY_LABELS = {
    "missing-plants":  "Missing Plants",
    "price-data":      "Price Data",
    "site-feature":    "Feature Request",
    "bug":             "Bug",
    "other":           "Other",
}

_STATUS_LABELS = {
    "reviewing":   "Under Review",
    "planned":     "Planned",
    "in-progress": "In Progress",
    "responded":   "Responded",
    "done":        "Done ✓",
}


def load_feedback():
    """Load and enrich feedback items from data/feedback.json."""
    path = os.path.join(DATA_DIR, "feedback.json")
    raw = load_json(path)
    if not isinstance(raw, list):
        return []

    items = []
    for entry in raw:
        submitted_raw = entry.get("submitted_at", "")
        try:
            submitted_dt = datetime.fromisoformat(submitted_raw.replace("Z", "+00:00"))
            submitted_date = submitted_dt.strftime("%B %d, %Y")
        except (ValueError, TypeError):
            submitted_date = ""

        response = entry.get("response")
        response_date = ""
        if response:
            responded_raw = response.get("responded_at", "")
            try:
                rd = datetime.fromisoformat(responded_raw.replace("Z", "+00:00"))
                response_date = rd.strftime("%B %d, %Y")
            except (ValueError, TypeError):
                response_date = ""

        items.append({
            "id":             entry.get("id", ""),
            "category":       entry.get("category", "other"),
            "category_label": _CATEGORY_LABELS.get(entry.get("category", ""), "Other"),
            "title":          entry.get("title", ""),
            "body":           entry.get("body", ""),
            "submitted_at":   submitted_raw,
            "submitted_date": submitted_date,
            "status":         entry.get("status", "reviewing"),
            "status_label":   _STATUS_LABELS.get(entry.get("status", "reviewing"), "Under Review"),
            "upvotes":        entry.get("upvotes", 0),
            "response":       response,
            "response_date":  response_date,
        })

    return items


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def build_site(build_guides=True, build_products=True):
    """Main build function."""
    print("=" * 60)
    print("PlantPriceTracker — Static Site Build")
    print("=" * 60)

    # Load data
    print("\nLoading data...")
    plants = load_json(os.path.join(DATA_DIR, "plants.json"))
    retailers = load_json(os.path.join(DATA_DIR, "retailers.json"))
    retailers_by_id = {r["id"]: r for r in retailers}

    # Load promo codes (written by runner.py scrape_promos — may not exist yet)
    promos_path = os.path.join(DATA_DIR, "promos.json")
    promos_by_retailer = load_json(promos_path) if os.path.exists(promos_path) else {}

    print(f"  {len(plants)} plants")
    print(f"  {len(retailers)} retailers")
    if promos_by_retailer:
        active_promo_count = sum(
            1 for v in promos_by_retailer.values()
            if isinstance(v, dict) and (v.get("codes") or v.get("banners"))
        )
        print(f"  {active_promo_count} retailers with active promos")

    # Set up Jinja2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
    )
    env.globals["current_year"] = datetime.now().year

    # Ensure output directories
    ensure_dir(os.path.join(SITE_DIR, "plants"))
    ensure_dir(os.path.join(SITE_DIR, "guides"))
    ensure_dir(os.path.join(SITE_DIR, "category"))

    # -----------------------------------------------------------------------
    # Build product pages
    # -----------------------------------------------------------------------
    if build_products and plants:
        print(f"\nBuilding {len(plants)} product pages...")
        product_tpl = env.get_template("product.html")

        for plant in plants:
            price_entries = load_prices(plant["id"])
            latest_prices = get_latest_prices(price_entries, retailers_by_id)
            price_table = build_price_table(plant, latest_prices, retailers_by_id, promos_by_retailer)
            price_history_json = build_price_history_json(price_entries)
            similar = find_similar_plants(plant, plants)

            # Enrich plant dict with live price summary so category pages can show prices
            plant["lowest_price"] = price_table["lowest_price"]
            plant["highest_price"] = price_table["highest_price"]
            plant["savings_pct"] = price_table["savings_pct"]
            plant["retailer_count"] = price_table["offer_count"]

            html = product_tpl.render(
                plant=plant,
                last_updated=date.today().strftime("%B %d, %Y"),
                similar_plants=similar,
                price_history=bool(price_history_json),
                price_history_json=price_history_json or "{}",
                **price_table,
            )

            out_path = os.path.join(SITE_DIR, "plants", f"{plant['id']}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print(f"  Written to site/plants/")

    # -----------------------------------------------------------------------
    # Build guide pages from article markdown files
    # -----------------------------------------------------------------------
    if build_guides:
        article_files = sorted(glob.glob(os.path.join(ARTICLES_DIR, "[0-9][0-9]-*.md")))
        print(f"\nBuilding {len(article_files)} guide pages...")
        guide_tpl = env.get_template("guide.html")

        all_guides = []
        for filepath in article_files:
            article = parse_article_md(filepath)
            all_guides.append(article)

        for article in all_guides:
            related_plants = find_related_plants_for_guide(article["slug"], plants)
            related_guides = [g for g in all_guides if g["slug"] != article["slug"]]

            html = guide_tpl.render(
                title=article["title"],
                content=article["content"],
                toc=article["toc"],
                meta_description=article["meta_description"],
                date_published="2026-04-02",
                date_modified=date.today().isoformat(),
                retailer_count=len([r for r in retailers if r.get("active")]),
                related_plants=related_plants,
                related_guides=related_guides[:5],
            )

            out_path = os.path.join(SITE_DIR, "guides", f"{article['slug']}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print(f"  Written to site/guides/")

        # Guides index page
        index_html = env.get_template("base.html")
        guides_index = index_html.render(content="")  # TODO: proper index template
        # For now, skip guide index — will add later

    # -----------------------------------------------------------------------
    # Build category pages
    # -----------------------------------------------------------------------
    if build_products and plants:
        categories = defaultdict(list)
        for plant in plants:
            cat = plant.get("category", "uncategorized")
            categories[cat].append(plant)

        print(f"\nBuilding {len(categories)} category pages...")
        cat_tpl = env.get_template("category.html")

        for cat_id, cat_plants in categories.items():
            cat_name = cat_id.replace("-", " ").title()

            html = cat_tpl.render(
                category_name=cat_name,
                plants=cat_plants,
                retailer_count=len([r for r in retailers if r.get("active")]),
            )

            out_path = os.path.join(SITE_DIR, "category", f"{cat_id}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print(f"  Written to site/category/")

    # -----------------------------------------------------------------------
    # Build homepage
    # -----------------------------------------------------------------------
    print("\nBuilding homepage...")
    home_tpl = env.get_template("home.html")

    # Build category summary for homepage
    cat_summary = []
    categories_map = defaultdict(list)
    for plant in plants:
        categories_map[plant.get("category", "uncategorized")].append(plant)
    for cat_id, cat_plants in sorted(categories_map.items()):
        cat_summary.append({
            "id": cat_id,
            "name": cat_id.replace("-", " ").title(),
            "plant_count": len(cat_plants),
            "price_range": f"${min(p.get('price_range', '$0').split('-')[0].replace('$','') or '0' for p in cat_plants)}-${max(p.get('price_range', '$0').split('-')[-1].replace('$','') or '0' for p in cat_plants)}" if cat_plants else "",
        })

    # Hero example — pick the plant with the biggest real price spread from live data
    hero_example = None
    best_savings = 0
    for plant in plants:
        low = plant.get("lowest_price")
        high = plant.get("highest_price")
        if low and high and high > low:
            pct = round((1 - low / high) * 100)
            if pct > best_savings:
                best_savings = pct
                hero_example = {
                    "id": plant["id"],
                    "name": plant["common_name"],
                    "low": low,
                    "high": high,
                    "savings_pct": pct,
                    "retailer_count": plant.get("retailer_count", 4),
                }

    # Guides list for homepage
    article_files = sorted(glob.glob(os.path.join(ARTICLES_DIR, "[0-9][0-9]-*.md")))
    guides_for_home = []
    for fp in article_files[:6]:
        article = parse_article_md(fp)
        guides_for_home.append(article)

    # Tracked retailers for homepage
    tracked = [r for r in retailers if r.get("active")]

    html = home_tpl.render(
        categories=cat_summary,
        hero_example=hero_example,
        price_drops=[],  # Empty until we have historical data
        guides=guides_for_home,
        retailer_count=len(tracked),
        plant_count=len(plants),
        tracked_retailers=tracked,
    )

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  Written to site/index.html")

    # -----------------------------------------------------------------------
    # Build wishlist page (My Plant List)
    # -----------------------------------------------------------------------
    print("\nBuilding wishlist page...")
    wishlist_tpl = env.get_template("wishlist.html")
    html = wishlist_tpl.render()
    with open(os.path.join(SITE_DIR, "my-list.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  Written to site/my-list.html")

    # -----------------------------------------------------------------------
    # Build heat map page
    # -----------------------------------------------------------------------
    print("\nBuilding heat map page...")
    hm_categories, hm_data, hm_zones, hm_month_names = build_heatmap_data(plants)
    heatmap_tpl = env.get_template("heat_map.html")
    html = heatmap_tpl.render(
        categories=hm_categories,
        hm_data_json=json.dumps(hm_data),
        zones=hm_zones,
        default_zone=6,
        month_names=hm_month_names,
        retailer_count=len([r for r in retailers if r.get("active")]),
    )
    with open(os.path.join(SITE_DIR, "heat-map.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  Written to site/heat-map.html")

    # -----------------------------------------------------------------------
    # Build Improve page (community feedback board)
    # -----------------------------------------------------------------------
    print("\nBuilding improve page...")
    feedback_items = load_feedback()
    total_submissions = len(feedback_items)
    responded_count = sum(1 for f in feedback_items if f.get("response"))
    done_count = sum(1 for f in feedback_items if f.get("status") == "done")

    improve_tpl = env.get_template("improve.html")
    html = improve_tpl.render(
        feedback_items=feedback_items,
        total_submissions=total_submissions,
        responded_count=responded_count,
        done_count=done_count,
        # Formspree endpoint — replace YOUR_FORM_ID with the actual Formspree form ID
        # Free tier: 50 submissions/month, no backend needed
        formspree_endpoint="https://formspree.io/f/YOUR_FORM_ID",
    )
    with open(os.path.join(SITE_DIR, "improve.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  Written to site/improve.html")

    # -----------------------------------------------------------------------
    # Generate robots.txt
    # -----------------------------------------------------------------------
    robots_txt = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Sitemap: https://www.plantpricetracker.com/sitemap.xml\n"
    )
    with open(os.path.join(SITE_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots_txt)
    print("\nWritten site/robots.txt")

    # -----------------------------------------------------------------------
    # Build sitemap.xml
    # -----------------------------------------------------------------------
    print("\nBuilding sitemap.xml...")
    sitemap_urls = ["/", "/my-list.html", "/heat-map.html", "/improve.html", "/guides/index.html"]
    for plant in plants:
        sitemap_urls.append(f"/plants/{plant['id']}.html")
    for cat_id in categories_map:
        sitemap_urls.append(f"/category/{cat_id}.html")
    for fp in article_files:
        article = parse_article_md(fp)
        sitemap_urls.append(f"/guides/{article['slug']}.html")

    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in sitemap_urls:
        sitemap_xml += f'  <url><loc>https://www.plantpricetracker.com{url}</loc>'
        sitemap_xml += f'<lastmod>{date.today().isoformat()}</lastmod></url>\n'
    sitemap_xml += '</urlset>'

    with open(os.path.join(SITE_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap_xml)
    print("  Written to site/sitemap.xml")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total_pages = len(plants) + len(categories_map) + len(article_files) + 4
    print(f"\n{'=' * 60}")
    print(f"Build complete: {total_pages} pages generated")
    print(f"  {len(plants)} product pages")
    print(f"  {len(categories_map)} category pages")
    print(f"  {len(article_files)} guide pages")
    print(f"  1 homepage")
    print(f"  1 wishlist page (my-list.html)")
    print(f"  1 heat map page (heat-map.html)")
    print(f"  1 improve page (improve.html) — {total_submissions} submissions, {responded_count} responded")
    print(f"  1 sitemap.xml")
    print(f"Output: {SITE_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build PlantPriceTracker static site")
    parser.add_argument("--guides", action="store_true", help="Only rebuild guide pages")
    parser.add_argument("--products", action="store_true", help="Only rebuild product pages")
    args = parser.parse_args()

    if args.guides:
        build_site(build_guides=True, build_products=False)
    elif args.products:
        build_site(build_guides=False, build_products=True)
    else:
        build_site()
