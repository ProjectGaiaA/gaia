"""
Botanical Data Extractor

Fetches Shopify product pages and extracts botanical data (zones, sun,
mature size, bloom time, plant type) from body_html descriptions.
Reconciles data across multiple retailers using configurable LLM function.

Usage:
    from scrapers.extract_plant_data import (
        fetch_product_page, parse_body_html,
        reconcile_fields, generate_plant_entry,
    )

    # Fetch product data from a retailer
    page = fetch_product_page("https://www.naturehills.com", "pink-muhly-grass")

    # Parse body_html separately
    parsed = parse_body_html(html_string)

    # Reconcile across retailers
    reconciled = reconcile_fields([page1, page2, page3], "Pink Muhly Grass", llm_fn=my_llm)

    # Generate a draft plants.json entry
    entry = generate_plant_entry("pink-muhly-grass", "Pink Muhly Grass", ...)

Does NOT pull prices or write JSONL — the existing scraper pipeline
handles that on the next scheduled run after activation.
"""

import argparse
import json
import logging
import re
import sys
from collections import Counter

import requests
from bs4 import BeautifulSoup

from scrapers.polite import (
    is_allowed_by_robots,
    make_polite_session,
    polite_delay,
    log_request,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Size tier templates (from ADDING_PLANTS.md)
# ---------------------------------------------------------------------------

SIZE_TIERS_SHRUB_PERENNIAL = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
}

SIZE_TIERS_TREE = {
    "quart": ["1 quart", "qt", "4.5 inch", "4.5 in"],
    "1gal": ["1 gallon", "1 gal", "#1 container", "1g", "trade gallon"],
    "2gal": ["2 gallon", "2 gal", "#2 container"],
    "3gal": ["3 gallon", "3 gal", "#3 container"],
    "5gal": ["5 gallon", "5 gal", "#5 container"],
    "bareroot": ["bare root", "bare-root"],
}

# Categories that use tree-style size tiers
TREE_CATEGORIES = {"shade-trees", "flowering-trees", "privacy-trees", "fruit-trees"}


# ---------------------------------------------------------------------------
# body_html parsing
# ---------------------------------------------------------------------------

# Zone patterns — ordered from most specific to least
_ZONE_PATTERNS = [
    # "Zones: 6, 7, 8, 9, 10, 11" or "Zones 6, 7, 8, 9"
    re.compile(
        r"(?:hardiness\s+)?zones?\s*:?\s*((?:\d{1,2}\s*,\s*)+\d{1,2})",
        re.IGNORECASE,
    ),
    # "Zones: 6-11" or "Hardiness Zone: 7-10" or "Growing Zones: 6-11" or "Zones 4-8"
    re.compile(
        r"(?:hardiness|growing|usda)?\s*zones?\s*:?\s*(\d{1,2})\s*[-–to]+\s*(\d{1,2})",
        re.IGNORECASE,
    ),
]

# Sun patterns
_SUN_PATTERNS = [
    re.compile(
        r"(?:sun\s*(?:exposure|requirements?)?|light\s*(?:needs?|requirements?))\s*:?\s*"
        r"(full\s+sun(?:\s+to\s+part\s+shade)?|"
        r"part\s+shade(?:\s+to\s+full\s+(?:sun|shade))?|"
        r"full\s+shade|"
        r"full\s+sun\s+to\s+full\s+shade)",
        re.IGNORECASE,
    ),
]

# Mature size patterns — height
_HEIGHT_PATTERNS = [
    re.compile(
        r"(?:mature\s+)?height\s*:?\s*(\d+(?:\s*[-–to]+\s*\d+)?\s*(?:ft\.?|feet|'))",
        re.IGNORECASE,
    ),
]

# Mature size patterns — width/spread
_WIDTH_PATTERNS = [
    re.compile(
        r"(?:mature\s+)?(?:width|spread)\s*:?\s*(\d+(?:\s*[-–to]+\s*\d+)?\s*(?:ft\.?|feet|'))",
        re.IGNORECASE,
    ),
]

# Bloom time patterns
_BLOOM_PATTERNS = [
    re.compile(
        r"(?:bloom\s*(?:time|season|period)?|flowering\s*(?:time|season)?)\s*:?\s*"
        r"([A-Za-z][A-Za-z\s,\-–]+?)(?=<|$|\n)",
        re.IGNORECASE,
    ),
]

# Plant type patterns
_TYPE_PATTERNS = [
    re.compile(
        r"(?:plant\s+)?type\s*:?\s*([A-Za-z][A-Za-z\s]+?)(?=<|$|\n)",
        re.IGNORECASE,
    ),
]


def parse_body_html(html: str) -> dict:
    """Extract botanical fields from a Shopify product body_html.

    Returns a dict with keys: zones, sun, mature_size, bloom_time, type.
    Missing fields are None.
    """
    if not html:
        return {"zones": None, "sun": None, "mature_size": None,
                "bloom_time": None, "type": None}

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n")

    # Also extract table data (PlantingTree uses tables)
    table_data = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True).lower()
            val = cells[1].get_text(strip=True)
            table_data[key] = val

    zones = _extract_zones(text, table_data)
    sun = _extract_sun(text, table_data)
    height, width = _extract_size(text, table_data)
    mature_size = _format_mature_size(height, width)
    bloom_time = _extract_bloom_time(text, table_data)
    plant_type = _extract_type(text, table_data)

    return {
        "zones": zones,
        "sun": sun,
        "mature_size": mature_size,
        "bloom_time": bloom_time,
        "type": plant_type,
    }


def _extract_zones(text: str, table_data: dict) -> list[int] | None:
    """Extract USDA hardiness zones as a sorted list of integers."""
    # Check table first
    for key in ("zones", "zone", "hardiness zones", "hardiness zone",
                "growing zones", "usda zones"):
        if key in table_data:
            return _parse_zone_string(table_data[key])

    # Try regex patterns on full text
    for pattern in _ZONE_PATTERNS:
        m = pattern.search(text)
        if m:
            if m.lastindex == 1 and "," in m.group(1):
                # Comma-separated: "6, 7, 8, 9, 10, 11"
                nums = [int(x.strip()) for x in m.group(1).split(",") if x.strip().isdigit()]
                if nums:
                    return sorted(nums)
            elif m.lastindex >= 2:
                # Range: "6-11"
                low, high = int(m.group(1)), int(m.group(2))
                if 1 <= low <= 13 and 1 <= high <= 13 and low <= high:
                    return list(range(low, high + 1))
            elif m.lastindex == 1:
                # Range inside group 1: "6-11"
                return _parse_zone_string(m.group(1))

    return None


def _parse_zone_string(s: str) -> list[int] | None:
    """Parse zone string like '6-11' or '6, 7, 8, 9, 10, 11'."""
    s = s.strip()
    # Comma-separated
    if "," in s:
        nums = [int(x.strip()) for x in s.split(",") if x.strip().isdigit()]
        if nums:
            return sorted(nums)
    # Range with dash
    m = re.match(r"(\d{1,2})\s*[-–to]+\s*(\d{1,2})", s)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        if 1 <= low <= 13 and 1 <= high <= 13 and low <= high:
            return list(range(low, high + 1))
    # Single zone
    if s.isdigit() and 1 <= int(s) <= 13:
        return [int(s)]
    return None


def _extract_sun(text: str, table_data: dict) -> str | None:
    """Extract sun/light requirements."""
    # Check table
    for key in ("sun", "light", "sun exposure", "light needs",
                "sun requirements", "light requirements"):
        if key in table_data:
            return table_data[key].strip()

    # Regex
    for pattern in _SUN_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()

    return None


def _extract_size(text: str, table_data: dict) -> tuple[str | None, str | None]:
    """Extract height and width strings."""
    height = None
    width = None

    # Table
    for key in ("height", "mature height"):
        if key in table_data:
            height = table_data[key].strip()
    for key in ("width", "mature width", "spread", "mature spread"):
        if key in table_data:
            width = table_data[key].strip()

    # Regex fallback for height
    if not height:
        for pattern in _HEIGHT_PATTERNS:
            m = pattern.search(text)
            if m:
                height = m.group(1).strip()
                break

    # Regex fallback for width
    if not width:
        for pattern in _WIDTH_PATTERNS:
            m = pattern.search(text)
            if m:
                width = m.group(1).strip()
                break

    return height, width


def _format_mature_size(height: str | None, width: str | None) -> str | None:
    """Combine height and width into 'H ft tall x W ft wide' format."""
    if not height and not width:
        return None

    def _normalize(s):
        """Normalize a size string to use 'ft' consistently."""
        s = s.strip().rstrip(".")
        s = re.sub(r"\s*feet\b", " ft", s, flags=re.IGNORECASE)
        s = re.sub(r"(\d)'", r"\1 ft", s)
        s = re.sub(r"ft\.", "ft", s)
        # Normalize separators: "3 to 4" → "3-4"
        s = re.sub(r"(\d+)\s+to\s+(\d+)", r"\1-\2", s, flags=re.IGNORECASE)
        s = re.sub(r"(\d+)\s*–\s*(\d+)", r"\1-\2", s)
        return s

    if height and width:
        h = _normalize(height)
        w = _normalize(width)
        # Remove "tall"/"wide" if already present, we'll add them
        h = re.sub(r"\s*tall\b", "", h, flags=re.IGNORECASE).strip()
        w = re.sub(r"\s*wide\b", "", w, flags=re.IGNORECASE).strip()
        # Ensure "ft" is present
        if "ft" not in h.lower():
            h += " ft"
        if "ft" not in w.lower():
            w += " ft"
        return f"{h} tall x {w} wide"
    elif height:
        h = _normalize(height)
        return h
    else:
        w = _normalize(width)
        return w


def _extract_bloom_time(text: str, table_data: dict) -> str | None:
    """Extract bloom time/season."""
    for key in ("bloom time", "bloom season", "bloom period",
                "flowering time", "flowering season"):
        if key in table_data:
            return table_data[key].strip()

    for pattern in _BLOOM_PATTERNS:
        m = pattern.search(text)
        if m:
            val = m.group(1).strip().rstrip(",.")
            # Skip if it's just a label fragment
            if len(val) > 2:
                return val

    return None


def _extract_type(text: str, table_data: dict) -> str | None:
    """Extract plant type."""
    for key in ("type", "plant type"):
        if key in table_data:
            return table_data[key].strip()

    for pattern in _TYPE_PATTERNS:
        m = pattern.search(text)
        if m:
            val = m.group(1).strip().rstrip(",.")
            if len(val) > 2:
                return val

    return None


# ---------------------------------------------------------------------------
# Product page fetching
# ---------------------------------------------------------------------------

def fetch_product_page(retailer_url: str, handle: str) -> dict | None:
    """Fetch a Shopify product page and parse botanical data from body_html.

    Args:
        retailer_url: Base URL of the retailer (e.g. "https://www.naturehills.com").
        handle: Shopify product handle.

    Returns:
        Dict with keys: retailer_url, handle, title, product_type, parsed.
        Returns None on error (404, network failure, etc.).
    """
    url = f"{retailer_url.rstrip('/')}/products/{handle}.json"

    if not is_allowed_by_robots(url):
        logger.warning(f"Blocked by robots.txt: {url}")
        return None

    session = make_polite_session()
    try:
        polite_delay(5.0, 15.0)
        resp = session.get(url, timeout=20)
        log_request(url, status_code=resp.status_code)

        if resp.status_code == 404:
            logger.warning(f"Product not found: {url}")
            return None
        if resp.status_code != 200:
            logger.warning(f"Unexpected status {resp.status_code}: {url}")
            return None

        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError, ConnectionError) as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    product = data.get("product", {})
    body_html = product.get("body_html", "")
    parsed = parse_body_html(body_html)

    return {
        "retailer_url": retailer_url.rstrip("/"),
        "handle": handle,
        "title": product.get("title", ""),
        "product_type": product.get("product_type", ""),
        "parsed": parsed,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

RECONCILE_FIELDS = ["zones", "sun", "mature_size", "bloom_time", "type"]


def reconcile_fields(
    retailer_data: list[dict],
    plant_name: str,
    llm_fn=None,
) -> dict:
    """Reconcile botanical fields across multiple retailer sources.

    Applies the reconciliation rules from ADDING_PLANTS.md:
    - 3+ agree → majority rule (no flag)
    - 2 disagree → LLM tiebreak (no flag)
    - 1 source or 0 sources → LLM fallback (flagged)

    Args:
        retailer_data: List of dicts, each with a "parsed" key containing
            the output of parse_body_html.
        plant_name: Common name for LLM context.
        llm_fn: Callable(field, values, plant_name) -> resolved_value.
            If None, uses a no-op that picks the first value.

    Returns:
        Dict keyed by field name, each value is:
        {"value": ..., "source": "majority"|"llm_tiebreak"|"llm_fallback",
         "flagged": bool}
    """
    if llm_fn is None:
        llm_fn = _default_llm

    result = {}
    for field in RECONCILE_FIELDS:
        values = []
        for rd in retailer_data:
            v = rd["parsed"].get(field)
            if v is not None:
                values.append(v)

        if not values:
            # No data from any retailer → LLM fallback, flagged
            resolved = llm_fn(field, [], plant_name)
            result[field] = {
                "value": resolved,
                "source": "llm_fallback",
                "flagged": True,
            }
        elif len(values) == 1:
            # Single source → LLM validates, flagged
            resolved = llm_fn(field, values, plant_name)
            result[field] = {
                "value": resolved,
                "source": "llm_fallback",
                "flagged": True,
            }
        else:
            # Multiple sources — check for majority
            majority_value = _find_majority(field, values)
            if majority_value is not None:
                result[field] = {
                    "value": majority_value,
                    "source": "majority",
                    "flagged": False,
                }
            else:
                # No majority — LLM tiebreak
                resolved = llm_fn(field, values, plant_name)
                result[field] = {
                    "value": resolved,
                    "source": "llm_tiebreak",
                    "flagged": False,
                }

    return result


def _find_majority(field: str, values: list) -> object | None:
    """Find a majority value (appears in 3+ sources, or >50% if fewer sources).

    For zones, compares lists directly.
    For strings, normalizes before comparing.
    Returns the majority value or None if no clear majority.
    """
    if not values:
        return None

    if field == "zones":
        # Compare as tuples for hashability
        normalized = [tuple(v) for v in values]
        counter = Counter(normalized)
        most_common_val, most_common_count = counter.most_common(1)[0]
        # Majority: appears in 3+ sources, OR is the only value everyone agrees on
        if most_common_count >= 3 or (most_common_count == len(values) and len(values) >= 2):
            return list(most_common_val)
        return None
    else:
        # String fields — normalize for comparison
        def _norm(s):
            return re.sub(r"\s+", " ", s.strip().lower())

        normalized = [_norm(v) for v in values]
        counter = Counter(normalized)
        most_common_norm, most_common_count = counter.most_common(1)[0]

        if most_common_count >= 3 or (most_common_count == len(values) and len(values) >= 2):
            # Return the original (non-normalized) value that matches
            for v, n in zip(values, normalized):
                if n == most_common_norm:
                    return v
        return None


def _default_llm(field, values, plant_name):
    """Default no-op LLM that returns the first value or a placeholder."""
    if values:
        return values[0]
    return None


# ---------------------------------------------------------------------------
# Draft plant entry generation
# ---------------------------------------------------------------------------

def generate_plant_entry(
    plant_id: str,
    common_name: str,
    botanical_name: str,
    category: str,
    reconciled: dict,
    llm_fn=None,
    aliases: list[str] | None = None,
) -> dict:
    """Generate a complete draft plants.json entry.

    Args:
        plant_id: Kebab-case identifier.
        common_name: Human-readable name.
        botanical_name: Scientific name.
        category: Category slug.
        reconciled: Output of reconcile_fields.
        llm_fn: LLM function for planting_seasons and price_seasonality.
        aliases: Optional list of alternative names.

    Returns:
        Complete plants.json entry dict, ready for human review.
    """
    if llm_fn is None:
        llm_fn = _default_llm

    zones = reconciled["zones"]["value"]
    plant_type = reconciled["type"]["value"]

    # Select size tier template based on category
    if category in TREE_CATEGORIES:
        size_tiers = dict(SIZE_TIERS_TREE)
    else:
        size_tiers = dict(SIZE_TIERS_SHRUB_PERENNIAL)

    # Get planting_seasons and price_seasonality from LLM
    planting_seasons = llm_fn("planting_seasons", [], common_name)
    price_seasonality = llm_fn("price_seasonality", [], common_name)

    entry = {
        "id": plant_id,
        "common_name": common_name,
        "botanical_name": botanical_name,
        "aliases": aliases or [],
        "category": category,
        "zones": zones,
        "sun": reconciled["sun"]["value"],
        "mature_size": reconciled["mature_size"]["value"],
        "bloom_time": reconciled["bloom_time"]["value"],
        "type": reconciled["type"]["value"],
        "size_tiers": size_tiers,
        "price_range": "",
        "image": "",
        "image_credit": "",
        "planting_seasons": planting_seasons or {},
        "price_seasonality": price_seasonality or {},
        "active": False,
    }

    # Add review flags for fields that need human review
    flagged = [f for f in RECONCILE_FIELDS if reconciled[f]["flagged"]]
    if flagged:
        entry["_review_flags"] = flagged

    return entry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for extracting botanical data from retailer pages.

    Usage:
        python -m scrapers.extract_plant_data \\
            --plant "Pink Muhly Grass" \\
            --handles nature-hills:pink-muhly-grass \\
                      fast-growing-trees:pink-muhly-grass-tree \\
                      planting-tree:pink-muhly-grass-muhlenbergia \\
            --id pink-muhly-grass \\
            --botanical "Muhlenbergia capillaris" \\
            --category grasses

    Output: JSON draft of a plants.json entry to stdout.
    """
    parser = argparse.ArgumentParser(
        description="Extract botanical data from Shopify product pages."
    )
    parser.add_argument(
        "--plant", required=True,
        help="Common plant name (e.g. 'Pink Muhly Grass').",
    )
    parser.add_argument(
        "--handles", nargs="+", required=True,
        help="Retailer:handle pairs (e.g. nature-hills:pink-muhly-grass).",
    )
    parser.add_argument("--id", required=True, help="Plant ID (kebab-case).")
    parser.add_argument(
        "--botanical", required=True,
        help="Botanical name (e.g. 'Muhlenbergia capillaris').",
    )
    parser.add_argument(
        "--category", required=True,
        help="Category slug (e.g. 'grasses').",
    )
    parser.add_argument(
        "--aliases", nargs="*", default=[],
        help="Alternative names.",
    )
    parser.add_argument(
        "--retailers-file", default="data/retailers.json",
        help="Path to retailers.json for base URL lookup.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load retailer URLs
    try:
        with open(args.retailers_file, encoding="utf-8") as f:
            retailers = {r["id"]: r["url"] for r in json.load(f)}
    except FileNotFoundError:
        logger.error(f"Retailers file not found: {args.retailers_file}")
        sys.exit(1)

    # Parse retailer:handle pairs
    handle_pairs = []
    for pair in args.handles:
        if ":" not in pair:
            logger.error(f"Invalid handle pair (expected retailer:handle): {pair}")
            sys.exit(1)
        retailer_id, handle = pair.split(":", 1)
        if retailer_id not in retailers:
            logger.error(f"Unknown retailer: {retailer_id}")
            sys.exit(1)
        handle_pairs.append((retailers[retailer_id], handle))

    # Fetch product pages
    pages = []
    for base_url, handle in handle_pairs:
        logger.info(f"Fetching {base_url}/products/{handle}.json ...")
        page = fetch_product_page(base_url, handle)
        if page:
            pages.append(page)
            logger.info(f"  OK — parsed: {page['parsed']}")
        else:
            logger.warning(f"  FAILED — skipping")

    if not pages:
        logger.error("No product pages fetched successfully. Aborting.")
        sys.exit(1)

    logger.info(f"Reconciling data from {len(pages)} retailer(s) ...")

    # Reconcile (using default no-LLM for CLI — LLM is pluggable)
    reconciled = reconcile_fields(pages, args.plant)

    # Report reconciliation results
    for field, info in reconciled.items():
        flag = " [REVIEW]" if info["flagged"] else ""
        logger.info(f"  {field}: {info['value']} (source: {info['source']}){flag}")

    # Generate entry
    entry = generate_plant_entry(
        plant_id=args.id,
        common_name=args.plant,
        botanical_name=args.botanical,
        category=args.category,
        reconciled=reconciled,
        aliases=args.aliases,
    )

    # Output JSON
    print(json.dumps(entry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
