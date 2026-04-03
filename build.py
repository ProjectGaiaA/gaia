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


def build_price_table(plant, latest_prices, retailers_by_id):
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
        for tier, price_info in price_data.get("sizes", {}).items():
            if isinstance(price_info, dict):
                price = price_info.get("price")
                if price is not None and price > 0:
                    sizes[tier] = {
                        "price": price,
                        "was_price": price_info.get("was_price"),
                        "is_best": False,
                    }
                    all_prices_flat.append(price)
                    active_tiers.add(tier)
            elif isinstance(price_info, (int, float)) and price_info > 0:
                sizes[tier] = {"price": price_info, "was_price": None, "is_best": False}
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

        prices[retailer_id] = {
            "retailer_name": retailer["name"],
            "sizes": sizes,
            "in_stock": in_stock,
            "has_affiliate": has_affiliate,
            "has_best_price": False,
            "buy_url": price_data.get("url", retailer.get("url", "#")),
            "shipping": retailer.get("shipping"),
            "ships_season": ships_season,
        }

    # Mark best price per tier
    tier_order = ["quart", "1gal", "2gal", "3gal", "5gal", "bareroot", "bulb"]
    active_tiers_sorted = [t for t in tier_order if t in active_tiers]

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

    print(f"  {len(plants)} plants")
    print(f"  {len(retailers)} retailers")

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
            price_table = build_price_table(plant, latest_prices, retailers_by_id)
            price_history_json = build_price_history_json(price_entries)
            similar = find_similar_plants(plant, plants)

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

    # Hero example (use first plant with price data)
    hero_example = None
    for plant in plants:
        pr = plant.get("price_range", "")
        if "-" in pr:
            parts = pr.replace("$", "").split("-")
            try:
                low, high = float(parts[0]), float(parts[1])
                if low < high:
                    hero_example = {
                        "id": plant["id"],
                        "name": plant["common_name"],
                        "low": low,
                        "high": high,
                        "savings_pct": round((1 - low / high) * 100),
                        "retailer_count": 4,
                    }
                    break
            except (ValueError, IndexError):
                pass

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
    # Build sitemap.xml
    # -----------------------------------------------------------------------
    print("\nBuilding sitemap.xml...")
    sitemap_urls = ["/"]
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
    total_pages = len(plants) + len(categories_map) + len(article_files) + 1
    print(f"\n{'=' * 60}")
    print(f"Build complete: {total_pages} pages generated")
    print(f"  {len(plants)} product pages")
    print(f"  {len(categories_map)} category pages")
    print(f"  {len(article_files)} guide pages")
    print(f"  1 homepage")
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
