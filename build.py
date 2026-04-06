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

BASE_URL = "https://www.plantpricetracker.com"

# ---------------------------------------------------------------------------
# Guide SEO overrides — custom meta descriptions and FAQs per guide
# ---------------------------------------------------------------------------
GUIDE_META_DESCRIPTIONS = {
    "best-hydrangeas-to-buy-online": "Compare hydrangea prices across 10+ online nurseries. Incrediball, Limelight, Annabelle — find the best deal with prices checked daily.",
    "best-fruit-trees-to-buy-online": "Compare fruit tree prices online. Apple, peach, cherry, and pear trees from top nurseries — checked daily. Save 20–40% vs local garden centers.",
    "best-privacy-trees": "Find the cheapest privacy trees online. Compare Thuja Green Giant, Leyland Cypress, and arborvitae prices across 10+ nurseries — checked daily.",
    "cheapest-places-to-buy-online": "The cheapest places to buy plants online in 2026. We compared 10+ nurseries so you don't have to — see who wins by plant type.",
    "best-japanese-maple-varieties": "Compare Japanese maple prices online. Bloodgood, Crimson Queen, Emperor I — find the best deal across 10+ nurseries with prices checked daily.",
    "best-knock-out-roses": "Compare Knock Out rose prices across 10+ online nurseries. Double, Rainbow, and Petite varieties — find the lowest price, checked daily.",
    "best-blueberry-bushes": "Compare blueberry bush prices online. Bluecrop, Duke, Sunshine Blue — find the best deal across 10+ nurseries. Prices checked daily.",
    "best-flowering-trees-small-yards": "Compare small flowering tree prices online. Dogwood, Redbud, Cherry — find the lowest price across 10+ nurseries. Checked daily.",
    "best-azaleas-rhododendrons": "Compare azalea and rhododendron prices online. Find the best deals across 10+ nurseries with prices checked daily.",
    "best-time-to-buy-plants-online": "When is the cheapest time to buy plants online? See price seasonality data for trees, shrubs, and perennials — and exactly when to buy.",
    "why-same-plant-costs-20-or-60": "Plant pricing explained: container size, shipping, quality, branding, and seasonal timing all affect what you pay. Learn how to compare and avoid overpaying.",
}

GUIDE_FAQS = {
    "best-hydrangeas-to-buy-online": [
        {"q": "What are the best hydrangeas to buy online?", "a": "Incrediball, Limelight, Annabelle, and Endless Summer are consistently the best value — widely available from online nurseries at 20–40% below local garden center prices."},
        {"q": "When is the best time to buy hydrangeas online?", "a": "Late spring (May–June) for immediate planting, or fall (September–October) when nurseries discount to clear stock before winter."},
        {"q": "What size hydrangea should I order?", "a": "A 1-gallon plant establishes quickly and costs the least per plant. 3-gallon gives faster results if you need coverage sooner."},
        {"q": "How much do hydrangeas cost online vs local stores?", "a": "Online prices range from $18–$65 depending on size. Local garden centers typically charge $35–$80 for the same varieties."},
        {"q": "Do online nurseries ship healthy hydrangeas?", "a": "Yes — top-rated nurseries ship dormant or bare-root stock that establishes well. Look for guarantees on arrival condition."},
    ],
    "best-fruit-trees-to-buy-online": [
        {"q": "What fruit trees can you buy online and ship to your home?", "a": "Apples, pears, plums, cherries, peaches, and citrus are all available. Bare-root trees ship best in late winter when dormant."},
        {"q": "Are online fruit trees as healthy as local nursery trees?", "a": "Yes — online nurseries often offer more variety and younger certified stock. Look for USDA certified disease-free designations."},
        {"q": "How much does a fruit tree cost online?", "a": "Bare-root trees start around $25–$40. Container trees range from $45–$120 depending on variety and size."},
        {"q": "Do I need two fruit trees for pollination?", "a": "Most apples, pears, and sweet cherries require a second compatible variety for pollination. Peaches, sour cherries, and figs are typically self-fertile."},
        {"q": "When should I plant a bare-root fruit tree?", "a": "Plant as soon as the ground is workable in early spring, before new growth begins. Fall planting works in zones 6+."},
    ],
    "best-privacy-trees": [
        {"q": "What is the fastest growing privacy tree you can buy online?", "a": "Thuja Green Giant and Leyland Cypress are the fastest — growing 3–5 feet per year under good conditions."},
        {"q": "How many privacy trees do I need per foot of fence line?", "a": "Space Thuja Green Giant 5–6 feet apart; Leyland Cypress 6–8 feet apart for a dense hedge at maturity."},
        {"q": "What are the cheapest privacy trees to buy online?", "a": "Arborvitae and Leyland Cypress in 1-gallon sizes start around $15–$25 online — significantly cheaper than 3-gallon local nursery stock."},
        {"q": "Do privacy trees need full sun?", "a": "Most fast-growing options (Thuja, Leyland Cypress) prefer full sun. Emerald Green Arborvitae and Nellie Stevens Holly tolerate partial shade."},
        {"q": "When is the best time to plant privacy trees?", "a": "Fall is ideal — soil is warm, air is cool, and trees establish root systems before summer heat stress."},
    ],
    "cheapest-places-to-buy-online": [
        {"q": "Where is the cheapest place to buy plants online?", "a": "Nature Hills, Fast Growing Trees, and Walmart Garden often have the lowest prices, but comparing across nurseries for your specific plant always finds the best deal."},
        {"q": "Are cheap online plants worth it?", "a": "Yes, if you buy during sales and choose appropriate sizes. A 1-gallon plant at $15 from a reputable nursery performs the same as a $45 3-gallon from a local store."},
        {"q": "When do online nurseries have the biggest plant sales?", "a": "End of summer (August–September) and late spring (late May–June) are when nurseries discount heavily to move inventory before the off-season."},
        {"q": "Do online nurseries charge a lot for shipping?", "a": "Shipping typically runs $15–$30 per order regardless of plant count. Ordering 3+ plants makes the shipping cost much more efficient."},
        {"q": "Is it safe to buy plants from Amazon or Walmart online?", "a": "Third-party sellers vary widely in quality. For best results, buy directly from the nursery's own website or use a dedicated plant comparison tool."},
    ],
    "best-japanese-maple-varieties": [
        {"q": "What is the best Japanese maple to buy online?", "a": "Bloodgood, Emperor I, and Crimson Queen are the most available and competitively priced online — compare across nurseries for the best deal."},
        {"q": "How much does a Japanese maple cost online?", "a": "Small 1-gallon plants start around $20–$35. Named varieties in 3-gallon containers typically run $45–$95 online vs $75–$150 at local nurseries."},
        {"q": "Are Japanese maples slow-growing?", "a": "Most grow 1–2 feet per year. Upright varieties like Bloodgood grow faster than weeping laceleaf varieties."},
        {"q": "What hardiness zones can Japanese maples grow in?", "a": "Most Japanese maples grow in zones 5–8. Some tolerate zone 4 with protection; laceleaf weeping types prefer zone 6+."},
        {"q": "When is the best time to buy a Japanese maple online?", "a": "Fall — prices drop at the end of the season and cooler weather helps newly planted trees establish before winter."},
    ],
    "best-knock-out-roses": [
        {"q": "What makes Knock Out roses different from other roses?", "a": "They're disease-resistant, repeat-blooming from spring through frost, and don't need deadheading — the easiest rose to grow for most gardeners."},
        {"q": "How much do Knock Out roses cost online?", "a": "Prices range from $18–$55 depending on size and retailer. Comparing across nurseries typically saves $15–$25 per plant."},
        {"q": "How far apart should I plant Knock Out roses?", "a": "Space them 3–4 feet apart for a dense hedge. A single plant can spread 3–4 feet wide at maturity."},
        {"q": "What is the best Knock Out rose variety?", "a": "Double Knock Out has the fullest blooms. Rainbow Knock Out offers the most color variety. Petite Knock Out stays compact at about 18 inches tall."},
        {"q": "Can Knock Out roses grow in pots?", "a": "Yes — a 5-gallon or larger container works well. Use well-draining potting mix and water regularly during hot weather."},
    ],
    "best-blueberry-bushes": [
        {"q": "What blueberry varieties are best for home gardens?", "a": "Bluecrop and Duke are the most popular northern highbush varieties. Sunshine Blue and Misty perform best in warmer zones (7–10)."},
        {"q": "Do blueberries need acidic soil?", "a": "Yes — blueberries require soil pH of 4.5–5.5. Test your soil before planting and amend with sulfur if needed."},
        {"q": "Do I need two blueberry plants?", "a": "Blueberries produce much larger yields with cross-pollination. Plant at least two different compatible varieties for best fruit production."},
        {"q": "How much do blueberry bushes cost online?", "a": "1-gallon plants start around $12–$18. 3-gallon established bushes range from $25–$45. Ordering 3–5 at once usually qualifies for free shipping."},
        {"q": "How long until blueberry bushes produce fruit?", "a": "Most produce some fruit in year 2–3 after planting, with full production by year 4–5."},
    ],
    "best-flowering-trees-small-yards": [
        {"q": "What is the best small flowering tree for a backyard?", "a": "Dogwood, Redbud, and Serviceberry are top picks — all under 25 feet, with multi-season interest and available from online nurseries at competitive prices."},
        {"q": "How much do flowering trees cost online?", "a": "Prices range from $35–$120 for most varieties. Comparing nurseries can save $30–$60 per tree compared to local garden centers."},
        {"q": "Do flowering trees need full sun?", "a": "Most (Redbud, Serviceberry, Cherry) prefer full sun. Dogwood is one of the few flowering trees that blooms well in partial shade."},
        {"q": "When do flowering trees bloom?", "a": "Redbud blooms earliest (late March–April), followed by Dogwood and Cherry (April–May), then Crape Myrtle in summer."},
        {"q": "What is the fastest growing small flowering tree?", "a": "Crape Myrtle grows 3–5 feet per year in warm climates. Most ornamental cherries and dogwoods grow 1–2 feet per year."},
    ],
    "best-azaleas-rhododendrons": [
        {"q": "What is the difference between azaleas and rhododendrons?", "a": "Azaleas are smaller with smaller leaves and more flower colors. Rhododendrons are larger with bigger, waxy leaves and showy flower clusters. Botanically, all azaleas are rhododendrons."},
        {"q": "How much do azaleas cost online?", "a": "Small 1-quart plants start around $10–$15. 1-gallon established plants run $18–$35. Larger 3-gallon shrubs range $35–$65 online."},
        {"q": "Do azaleas and rhododendrons prefer sun or shade?", "a": "Both prefer dappled shade or morning sun with afternoon shade in zones 6+. In cooler climates (zones 4–5) they tolerate more sun."},
        {"q": "What soil pH do azaleas need?", "a": "Acidic soil between pH 4.5–6.0, similar to blueberries. Amend with sulfur if your soil is neutral or alkaline."},
        {"q": "When is the best time to plant azaleas?", "a": "Fall or early spring. Avoid planting in summer heat — azaleas establish poorly in dry, hot conditions."},
    ],
    "best-time-to-buy-plants-online": [
        {"q": "When is the cheapest time to buy plants online?", "a": "Late summer (August–September) and late spring (late May–June) are when online nurseries discount most heavily to clear inventory before the off-season."},
        {"q": "Is it safe to buy plants online in summer?", "a": "Yes, but plant immediately upon arrival, water well, and provide temporary shade for sun-sensitive species during their first week."},
        {"q": "Do online plant prices change seasonally?", "a": "Yes, significantly. The same Limelight Hydrangea that costs $65 in April can drop to $35 in September as nurseries clear stock."},
        {"q": "Is spring the best time to plant trees and shrubs?", "a": "Spring and fall are both excellent. Fall planting is often better because cooler temperatures reduce transplant stress and trees establish roots before summer."},
        {"q": "What month should I order plants to be safe?", "a": "Order in early to mid-spring (2 weeks after your last frost date), or in September for fall planting in most zones."},
    ],
    "why-same-plant-costs-20-or-60": [
        {"q": "Why do plant prices vary so much between nurseries?", "a": "Container size, wholesale cost, retail markup, shipping policy, plant quality, seasonal timing, and brand licensing all contribute. A 2-4x price difference on the same plant is common."},
        {"q": "Is it cheaper to buy plants at Home Depot or a local nursery?", "a": "Big-box stores are typically cheaper on sticker price, averaging 27-39% below average in some surveys. But consumer surveys consistently show lower plant quality ratings at big-box stores."},
        {"q": "What is a fair markup on plants?", "a": "Industry trade publications report retail markups typically range from 2x to 2.8x wholesale cost."},
        {"q": "Does buying a bigger pot size save money in the long run?", "a": "For fast-growing shrubs, usually not. A quart-size plant can close the gap with a one-gallon within one or two growing seasons."},
        {"q": "When are plants cheapest?", "a": "Fall, when nurseries discount remaining inventory to clear stock before winter. Late summer sales (August-September) offer the biggest discounts."},
    ],
}

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
    canonical = _SIZE_ALIASES.get(t, tier)
    # Catch raw variant IDs that slipped through the scraper
    if re.match(r'^(?:variant-)?\d{7,}$', canonical):
        return 'default'
    return canonical


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


def count_consecutive_run_misses(price_entries):
    """
    Cluster scrape entries into runs (>12h gap = new run) and return how many
    consecutive most-recent runs each retailer has been absent from.
    Returns dict: retailer_id -> int miss count.
    """
    if not price_entries:
        return {}

    ts_pairs = []
    for entry in price_entries:
        ts_str = entry.get("timestamp", "")
        rid = entry.get("retailer_id", "")
        if ts_str and rid:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    continue  # Skip naive timestamps — can't compare with aware
                ts_pairs.append((ts, rid))
            except (ValueError, TypeError):
                pass

    if not ts_pairs:
        return {}

    ts_pairs.sort(key=lambda x: x[0])

    # Cluster: new run if >12h gap from previous entry
    runs = []
    current_retailers = set()
    last_ts = None
    for ts, rid in ts_pairs:
        if last_ts is None or (ts - last_ts).total_seconds() > 12 * 3600:
            if current_retailers:
                runs.append(frozenset(current_retailers))
            current_retailers = set()
        current_retailers.add(rid)
        last_ts = ts
    if current_retailers:
        runs.append(frozenset(current_retailers))

    if not runs:
        return {}

    all_retailers = set()
    for run in runs:
        all_retailers |= run

    misses = {}
    for rid in all_retailers:
        count = 0
        for run in reversed(runs):
            if rid in run:
                break
            count += 1
        misses[rid] = count

    return misses


def build_price_table(plant, latest_prices, retailers_by_id, promos_by_retailer=None, price_entries=None):
    """Build structured price data for the comparison table template."""
    prices = {}
    all_prices_flat = []
    active_tiers = set()
    has_non_affiliate = False
    any_in_stock = False

    # Compute consecutive missed runs per retailer when full history is available
    run_misses = count_consecutive_run_misses(price_entries) if price_entries else {}

    for retailer_id, price_data in latest_prices.items():
        retailer = retailers_by_id.get(retailer_id)
        if not retailer:
            continue

        # Check staleness:
        #   >30 days since last seen → exclude row entirely
        #   ≥3 consecutive missed scrape runs → show as "Currently Unavailable"
        timestamp = price_data.get("timestamp", "")
        unavailable = False
        last_checked_str = None
        if timestamp:
            try:
                scrape_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
                days_old = (date.today() - scrape_date).days
                if days_old > 30:
                    continue  # Remove row entirely after 30 days missing
                missed_runs = run_misses.get(retailer_id, 0)
                if missed_runs >= 3:
                    unavailable = True  # Missing from 3+ consecutive scrape runs
                last_checked_str = scrape_date.strftime("%b %d").lstrip("0")
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
                        "variant_id": price_info.get("variant_id"),
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

        # Find cheapest variant_id for the default "Buy at" button
        default_variant = None
        if sizes:
            cheapest_size = min(
                (s for s in sizes.values() if s.get("price")),
                key=lambda s: s["price"],
                default=None,
            )
            if cheapest_size:
                default_variant = cheapest_size.get("variant_id")

        prices[retailer_id] = {
            "retailer_name": retailer["name"],
            "sizes": sizes,
            "in_stock": in_stock,
            "has_affiliate": has_affiliate,
            "has_best_price": False,
            "buy_url": price_data.get("url", retailer.get("url", "#")).split("?variant=")[0],
            "default_variant_id": default_variant,
            "shipping": retailer.get("shipping"),
            "ships_season": ships_season,
            "promo": promo_info,
            "unavailable": unavailable,
            "last_checked": last_checked_str,
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
    # Hide "default" tier from column display — it's a fallback when the scraper
    # can't identify a real size. Retailers with only "default" still appear as
    # rows with a "Buy at" link, just without prices in size columns.
    active_tiers.discard("default")
    known = set(tier_order)
    leftover = sorted(t for t in active_tiers if t not in known)
    active_tiers_sorted = [t for t in tier_order if t in active_tiers] + leftover

    for tier in active_tiers_sorted:
        best_price = float("inf")
        best_retailer = None
        for rid, rdata in prices.items():
            # Only consider in-stock or unknown-stock, available retailers for best price
            if rdata["in_stock"] is False or rdata.get("unavailable"):
                continue
            if tier in rdata["sizes"] and rdata["sizes"][tier]["price"] < best_price:
                best_price = rdata["sizes"][tier]["price"]
                best_retailer = rid
        if best_retailer:
            prices[best_retailer]["sizes"][tier]["is_best"] = True
            prices[best_retailer]["has_best_price"] = True

    # Price inversion detection: flag larger sizes that cost LESS than smaller sizes
    # from the same nursery (likely clearance / sale).
    tier_rank = {t: i for i, t in enumerate(tier_order)}
    for rid, rdata in prices.items():
        retailer_sizes = rdata["sizes"]
        # Collect (rank, price, tier) for tiers this retailer has
        ranked = []
        for tier, sdata in retailer_sizes.items():
            if isinstance(sdata, dict) and sdata.get("price"):
                rank = tier_rank.get(tier, 999)
                ranked.append((rank, sdata["price"], tier))
        ranked.sort()  # sort by canonical size order
        # If a larger tier (higher rank) is cheaper than any smaller tier, flag it
        for i in range(1, len(ranked)):
            bigger_rank, bigger_price, bigger_tier = ranked[i]
            for j in range(i):
                smaller_rank, smaller_price, smaller_tier = ranked[j]
                if bigger_price < smaller_price:
                    retailer_sizes[bigger_tier]["sale_flag"] = True
                    break

    # Sort retailers: cheapest first, no-price next, sold-out next, unavailable last
    def _retailer_sort_key(item):
        rid, rdata = item
        if rdata.get("unavailable"):
            return (3, float("inf"))
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

    # Same-tier savings: compare prices ONLY within the same size tier across nurseries.
    # Pick the tier that appears at the most nurseries, then compare cheapest vs most
    # expensive for THAT tier.  This avoids misleading cross-tier comparisons
    # (e.g. $9.99 bare root vs $393.93 large container).
    same_tier_savings = 0
    same_tier_info = None
    tier_prices_map = {}  # tier → list of (price, retailer_name)
    for rid, rdata in prices.items():
        if rdata["in_stock"] is False:
            continue
        for tier, sdata in rdata["sizes"].items():
            if isinstance(sdata, dict) and sdata.get("price"):
                tier_prices_map.setdefault(tier, []).append(
                    (sdata["price"], rdata["retailer_name"])
                )
    # Find the tier with the most nurseries, break ties by savings %
    # Filter outliers: if the highest price is 3x+ the second highest, drop it
    # (likely bad scraped data, e.g. FGT variant ID mis-parse)
    best_tier_key = None
    for tier, price_list in tier_prices_map.items():
        if len(price_list) < 2:
            continue
        sorted_prices = sorted(price_list, key=lambda x: x[0])
        # Remove outlier: if top price is 3x+ the second-highest, exclude it
        if len(sorted_prices) >= 3:
            second_hi = sorted_prices[-2][0]
            top_hi = sorted_prices[-1][0]
            if second_hi > 0 and top_hi / second_hi >= 3.0:
                sorted_prices = sorted_prices[:-1]
        lo = sorted_prices[0][0]
        hi = sorted_prices[-1][0]
        pct = round((1 - lo / hi) * 100) if hi > lo else 0
        nursery_count = len(sorted_prices)
        if best_tier_key is None or (nursery_count, pct) > (best_tier_key[0], best_tier_key[1]):
            best_tier_key = (nursery_count, pct, tier, lo, hi)
    if best_tier_key:
        same_tier_savings = best_tier_key[1]
        same_tier_info = {
            "tier": best_tier_key[2],
            "tier_label": get_size_label(best_tier_key[2]),
            "low": best_tier_key[3],
            "high": best_tier_key[4],
            "nursery_count": best_tier_key[0],
        }

    # Build mobile best-deal cards: cheapest price per size tier (one row per tier)
    mobile_tiers = []
    all_deals = []
    for tier in active_tiers_sorted:
        best_price = None
        best_entry = None
        for rid, rdata in prices.items():
            if rdata["in_stock"] is False:
                continue
            sdata = rdata["sizes"].get(tier)
            if not isinstance(sdata, dict) or not sdata.get("price"):
                continue
            buy_url_base = rdata["buy_url"]
            variant_url = buy_url_base
            if sdata.get("variant_id"):
                variant_url = f"{buy_url_base}?variant={sdata['variant_id']}"
            entry = {
                "price": sdata["price"],
                "retailer_name": rdata["retailer_name"],
                "size": tier,
                "url": variant_url,
                "has_affiliate": rdata["has_affiliate"],
                "shipping": rdata.get("shipping"),
                "sale_flag": sdata.get("sale_flag", False),
                "promo": rdata.get("promo"),
            }
            all_deals.append(entry)
            if best_price is None or sdata["price"] < best_price:
                best_price = sdata["price"]
                best_entry = entry
        if best_entry:
            # Skip tiers whose label looks like a raw variant ID
            label = get_size_label(tier)
            if re.search(r'\d{7,}', label):
                continue
            mobile_tiers.append({
                "tier": tier,
                "label": label,
                "price": best_entry["price"],
                "retailer_name": best_entry["retailer_name"],
                "url": best_entry["url"],
                "has_affiliate": best_entry["has_affiliate"],
                "shipping": best_entry.get("shipping"),
                "sale_flag": best_entry.get("sale_flag", False),
                "promo": best_entry.get("promo"),
            })
    all_deals.sort(key=lambda d: d["price"])
    best_deal = all_deals[0] if all_deals else None
    runner_up_deals = all_deals[1:3] if len(all_deals) > 1 else []

    return {
        "prices": prices,
        "active_size_tiers": active_tiers_sorted,
        "lowest_price": lowest,
        "highest_price": highest,
        "savings_pct": savings_pct,
        "same_tier_savings": same_tier_savings,
        "same_tier_info": same_tier_info,
        "offer_count": len(prices),
        "any_in_stock": any_in_stock,
        "has_non_affiliate": has_non_affiliate,
        "best_deal": best_deal,
        "runner_up_deals": runner_up_deals,
        "mobile_tiers": mobile_tiers,
    }


def build_price_history_json(price_entries, active_retailer_ids=None):
    """Build Chart.js-compatible price history data."""
    if len(price_entries) < 2:
        return None

    # Group by date and retailer
    by_date = defaultdict(dict)
    retailer_names = {}
    for entry in price_entries:
        rid = entry.get("retailer_id", "")
        if active_retailer_ids is not None and rid not in active_retailer_ids:
            continue
        ts = entry.get("timestamp", "")[:10]
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
        "why-same-plant-costs-20-or-60": None,  # All categories — pricing is cross-category
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
    all_plants = load_json(os.path.join(DATA_DIR, "plants.json"))
    plants = [p for p in all_plants if p.get("active", True)]
    retailers = load_json(os.path.join(DATA_DIR, "retailers.json"))
    retailers_by_id = {r["id"]: r for r in retailers if r.get("active", True)}

    # Load promo codes (written by runner.py scrape_promos — may not exist yet)
    promos_path = os.path.join(DATA_DIR, "promos.json")
    promos_by_retailer = load_json(promos_path) if os.path.exists(promos_path) else {}

    inactive = len(all_plants) - len(plants)
    print(f"  {len(plants)} plants" + (f" ({inactive} inactive, skipped)" if inactive else ""))
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
    env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)

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
            price_table = build_price_table(plant, latest_prices, retailers_by_id, promos_by_retailer, price_entries)
            price_history_json = build_price_history_json(price_entries, set(retailers_by_id.keys()))
            similar = find_similar_plants(plant, plants)

            # Enrich plant dict with live price summary so category pages can show prices
            plant["lowest_price"] = price_table["lowest_price"]
            plant["highest_price"] = price_table["highest_price"]
            plant["savings_pct"] = price_table["savings_pct"]
            plant["same_tier_info"] = price_table.get("same_tier_info")
            plant["retailer_count"] = price_table["offer_count"]

            html = product_tpl.render(
                plant=plant,
                last_updated=date.today().strftime("%B %d, %Y"),
                similar_plants=similar,
                price_history=bool(price_history_json),
                price_history_json=price_history_json or "{}",
                canonical_url=f"{BASE_URL}/plants/{plant['id']}.html",
                **price_table,
            )

            out_path = os.path.join(SITE_DIR, "plants", f"{plant['id']}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print("  Written to site/plants/")

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

            slug = article["slug"]
            guide_faqs = GUIDE_FAQS.get(slug, [])
            faq_mainentity = json.dumps([
                {
                    "@type": "Question",
                    "name": faq["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": faq["a"]},
                }
                for faq in guide_faqs
            ], ensure_ascii=False) if guide_faqs else None

            html = guide_tpl.render(
                title=article["title"],
                content=article["content"],
                toc=article["toc"],
                meta_description=GUIDE_META_DESCRIPTIONS.get(slug, article["meta_description"]),
                date_published="2026-04-02",
                date_modified=date.today().isoformat(),
                retailer_count=len([r for r in retailers if r.get("active")]),
                related_plants=related_plants,
                related_guides=related_guides[:5],
                canonical_url=f"{BASE_URL}/guides/{slug}.html",
                faq_mainentity=faq_mainentity,
                guide_faqs=guide_faqs,
            )

            out_path = os.path.join(SITE_DIR, "guides", f"{article['slug']}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print("  Written to site/guides/")

        # Guides index page — render from base.html so nav/footer stay consistent
        guides_index_content = '<h1>Plant Buying Guides</h1>\n'
        guides_index_content += '<p>Expert guides to help you find the best plants at the best prices.</p>\n'
        guides_index_content += '<div class="guides-grid" style="margin-top: 1.5rem;">\n'
        for fp in article_files:
            article = parse_article_md(fp)
            snippet = article["content"][:200].replace("<", "").replace(">", "").replace("&", "&amp;")
            guides_index_content += (
                f'<a href="/guides/{article["slug"]}.html" class="guide-card">\n'
                f'<h3>{article["title"]}</h3>\n'
                f'<p>{snippet}</p>\n'
                f'</a>\n'
            )
        guides_index_content += '</div>\n'
        base_tpl = env.get_template("base.html")
        guides_index_html = base_tpl.render(
            content=guides_index_content,
            canonical_url=f"{BASE_URL}/guides/index.html",
        )
        # Inject the content into the main block manually since base.html uses blocks
        # Simpler: write a minimal template string
        guides_index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plant Buying Guides | PlantPriceTracker</title>
    <meta name="description" content="Expert buying guides for trees, shrubs, and perennials. Compare prices and find the best deals.">
    <link rel="canonical" href="{BASE_URL}/guides/index.html" />
    <meta property="og:url" content="{BASE_URL}/guides/index.html" />
    <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
    <header class="site-header">
        <nav class="nav-container">
            <a href="/" class="site-logo">
                <span class="logo-icon">&#x1F331;</span>
                <span class="logo-text">PlantPriceTracker</span>
            </a>
            <ul class="nav-links">
                <li><a href="/category/hydrangeas.html">Hydrangeas</a></li>
                <li><a href="/category/japanese-maples.html">Japanese Maples</a></li>
                <li><a href="/category/fruit-trees.html">Fruit Trees</a></li>
                <li><a href="/category/roses.html">Roses</a></li>
                <li><a href="/guides/index.html">Guides</a></li>
                <li><a href="/heat-map.html">Heat Map</a></li>
                <li><a href="/my-list.html">&#x2661; My List<span class="wishlist-nav-count"></span></a></li>
                <li><a href="/improve.html">Improve</a></li>
            </ul>
        </nav>
    </header>
    <main class="main-content">
{guides_index_content}
    </main>
    <footer class="site-footer">
        <div class="footer-content">
            <div class="footer-disclosure">
                <p><strong>Affiliate Disclosure:</strong> We earn commissions from purchases made through links on this site. This does not affect our rankings or recommendations. <a href="/disclosure.html">Full disclosure</a>.</p>
            </div>
            <div class="footer-links">
                <a href="/disclosure.html">Disclosure</a>
                <a href="/privacy.html">Privacy Policy</a>
                <a href="/guides/index.html">Buying Guides</a>
                <a href="/improve.html">Improve This Site</a>
            </div>
            <p class="footer-copyright">&copy; {datetime.now().year} PlantPriceTracker. Prices checked daily. Not affiliated with any nursery.</p>
        </div>
    </footer>
    <script src="/assets/js/wishlist.js"></script>
</body>
</html>"""
        out_path = os.path.join(SITE_DIR, "guides", "index.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(guides_index_html)

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
                canonical_url=f"{BASE_URL}/category/{cat_id}.html",
            )

            out_path = os.path.join(SITE_DIR, "category", f"{cat_id}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)

        print("  Written to site/category/")

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

    # Hero example — pick the plant with the biggest SAME-TIER price spread.
    # This compares the same size (e.g. 1 Gallon vs 1 Gallon) across nurseries
    # to avoid misleading cross-tier comparisons (bare root vs large container).
    hero_example = None
    best_savings = 0
    for plant in plants:
        sti = plant.get("same_tier_info")
        if sti and sti.get("low") and sti.get("high") and sti["high"] > sti["low"]:
            pct = round((1 - sti["low"] / sti["high"]) * 100)
            if pct > best_savings:
                best_savings = pct
                hero_example = {
                    "id": plant["id"],
                    "name": plant["common_name"],
                    "low": sti["low"],
                    "high": sti["high"],
                    "savings_pct": pct,
                    "size_label": sti.get("tier_label", ""),
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
        canonical_url=f"{BASE_URL}/",
    )

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  Written to site/index.html")

    # -----------------------------------------------------------------------
    # Build wishlist page (My Plant List)
    # -----------------------------------------------------------------------
    print("\nBuilding wishlist page...")
    wishlist_tpl = env.get_template("wishlist.html")
    html = wishlist_tpl.render(canonical_url=f"{BASE_URL}/my-list.html")
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
        canonical_url=f"{BASE_URL}/heat-map.html",
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
        canonical_url=f"{BASE_URL}/improve.html",
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
    sitemap_urls = ["/", "/my-list.html", "/heat-map.html", "/improve.html", "/guides/index.html",
                    "/disclosure.html", "/privacy.html"]
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
    print("  1 homepage")
    print("  1 wishlist page (my-list.html)")
    print("  1 heat map page (heat-map.html)")
    print(f"  1 improve page (improve.html) — {total_submissions} submissions, {responded_count} responded")
    print("  1 sitemap.xml")
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
