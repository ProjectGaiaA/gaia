"""
Shopify Product Scraper

Most online nurseries use Shopify, which exposes structured JSON endpoints:
  - /products/{handle}.json — single product with variants, prices, availability
  - /products.json?limit=250 — paginated product listing

This scraper uses the JSON endpoints instead of HTML scraping:
  - More robust (won't break on theme changes)
  - Less likely to trigger bot detection
  - Structured data, no parsing needed

Usage:
    from scrapers.shopify import ShopifyScraper
    scraper = ShopifyScraper("fast-growing-trees", "https://www.fast-growing-trees.com")
    results = scraper.scrape_products(["limelight-hydrangea-shrub", "knockout-rose-bush"])
"""

import json
import logging
import random
import re
import time
from datetime import datetime, timezone

import requests

from scrapers.polite import (
    USER_AGENTS, polite_delay,
    log_request, is_allowed_by_robots, make_polite_session,
)

logger = logging.getLogger(__name__)


class ShopifyScraper:
    """Scrape product data from Shopify-based nursery stores."""

    def __init__(self, retailer_id: str, base_url: str, delay_range: tuple = (5, 15)):
        """Initialize scraper with conservative defaults.

        delay_range is 5-15 seconds between requests by default.
        This is intentionally slow to be respectful — we're scraping
        once daily, not building a real-time feed. Being polite to
        retailer servers is both ethical and keeps us from getting blocked.
        """
        self.retailer_id = retailer_id
        self.base_url = base_url.rstrip("/")
        self.delay_range = delay_range
        self.session = make_polite_session()

    def _delay(self):
        """Random 5-15s delay between requests. Intentionally slow to be polite."""
        delay = polite_delay(self.delay_range[0], self.delay_range[1])
        return delay

    def _get_json(self, url: str) -> dict | None:
        """Fetch JSON from URL with error handling and robots.txt compliance."""
        if not is_allowed_by_robots(url):
            return None
        try:
            resp = self.session.get(url, timeout=20)
            log_request(url, status_code=resp.status_code)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                logger.warning(f"Rate limited by {self.retailer_id}, waiting {retry_after}s")
                time.sleep(retry_after)
                resp = self.session.get(url, timeout=20)
                log_request(url, status_code=resp.status_code)
            if resp.status_code == 404:
                logger.info(f"Product not found: {url}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {url}: {e}")
            return None

    def scrape_product(self, handle: str) -> dict | None:
        """Scrape a single product by its Shopify handle.

        Tries JSON endpoint first (fastest, most structured).
        Falls back to HTML scraping if JSON endpoint returns 404 (some stores disable it).

        Args:
            handle: The Shopify product handle (URL slug), e.g. "limelight-hydrangea-shrub"

        Returns:
            Structured dict with price data, or None on failure.
        """
        # Try JSON endpoint first
        json_url = f"{self.base_url}/products/{handle}.json"
        data = self._get_json(json_url)
        if data and "product" in data:
            return self._parse_product(data["product"])

        # Fall back to HTML scraping
        logger.info(f"  JSON endpoint unavailable, trying HTML for {handle}")
        return self._scrape_product_html(handle)

    def scrape_products(self, handles: list[str]) -> list[dict]:
        """Scrape multiple products by handle. Returns list of result dicts."""
        results = []
        for i, handle in enumerate(handles):
            logger.info(f"  [{i+1}/{len(handles)}] {self.retailer_id}: {handle}")
            result = self.scrape_product(handle)
            if result:
                results.append(result)
            else:
                results.append({
                    "retailer_id": self.retailer_id,
                    "handle": handle,
                    "error": "Product not found or request failed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            if i < len(handles) - 1:
                self._delay()
        return results

    def _parse_product(self, product: dict) -> dict:
        """Parse a Shopify product JSON into our canonical format."""
        title = product.get("title", "")
        handle = product.get("handle", "")
        variants = product.get("variants", [])

        # Extract prices by size variant
        sizes = {}
        any_available = False

        for variant in variants:
            variant_title = variant.get("title", "").strip()
            price_str = variant.get("price", "0")
            compare_price_str = variant.get("compare_at_price")
            # If 'available' field is missing, set to None (unknown — display as "Check site")
            # If present, use the actual value
            available = variant.get("available")
            if available is None:
                available = None  # Unknown — don't assume in stock or out of stock

            try:
                price = float(price_str)
            except (ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Skip multi-plant packs and bundles
            # Matches: "3 Plant(s)", "10 Plant(s)", "10-Pack", "4-Pack", "BOGO / 2 Plant(s)"
            if re.search(r'(?:[2-9]|1\d)[\s-]*(?:plant|pack)', variant_title, re.IGNORECASE):
                continue
            if 'bogo' in variant_title.lower():
                continue
            if 'single' in variant_title.lower() and 'pack' in variant_title.lower():
                continue

            # If variant says "Ships in Spring/Fall", treat as available for order
            if available is None and re.search(r'ships?\s+in\s+(?:spring|fall|summer|winter)', variant_title, re.IGNORECASE):
                available = True

            was_price = None
            if compare_price_str:
                try:
                    was_price = float(compare_price_str)
                    if was_price <= price:
                        was_price = None  # Not actually a discount
                except (ValueError, TypeError):
                    pass

            # Normalize the variant title to a size tier
            size_tier = self._normalize_size(variant_title)

            if available is True:
                any_available = True

            variant_id = variant.get("id", "")
            sizes[size_tier] = {
                "price": price,
                "was_price": was_price,
                "available": available,
                "raw_size": variant_title,
                "variant_id": variant_id,
            }

        # Product URL — use variant ID of the first/cheapest size for deep linking
        product_url = f"{self.base_url}/products/{handle}"
        if sizes:
            # Find cheapest available variant for the default link
            cheapest = min(sizes.values(), key=lambda x: x["price"])
            if cheapest.get("variant_id"):
                product_url = f"{self.base_url}/products/{handle}?variant={cheapest['variant_id']}"

        # If NO variant had an explicit available field, stock is unknown.
        # Nature Hills returns null for both in-stock AND sold-out products,
        # so we can't assume either way.
        has_any_explicit_availability = any(
            v.get("available") is not None for v in sizes.values()
        )
        if not has_any_explicit_availability:
            any_available = None  # Unknown — show dash

        return {
            "retailer_id": self.retailer_id,
            "retailer_name": self.retailer_id.replace("-", " ").title(),
            "handle": handle,
            "title": title,
            "url": product_url,
            "sizes": sizes,
            "in_stock": any_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _scrape_product_html(self, handle: str) -> dict | None:
        """Scrape product data from HTML page when JSON endpoint is disabled.

        Extracts data from:
        1. Schema.org Offer objects embedded in the React stream
        2. Shopify variant ID → size name mappings in inline JS
        """
        url = f"{self.base_url}/products/{handle}"
        if not is_allowed_by_robots(url):
            return None
        try:
            resp = self.session.get(url, timeout=20)
            log_request(url, status_code=resp.status_code)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"HTML request failed for {url}: {e}")
            return None

        text = resp.text

        # Extract variant ID → size name mapping from inline JS.
        # Multiple patterns because Shopify stores vary structure across themes.
        variant_names = {}
        _size_keywords = [
            'quart', 'gal', 'gallon', 'ft', 'foot', 'feet', 'pack',
            'bare', 'bulb', 'root', 'inch', 'qt', 'container',
        ]

        def _is_size_name(name):
            nl = name.lower()
            return (
                any(kw in nl for kw in _size_keywords)
                or re.match(r'^\d+-\d+\s*(ft|feet|foot)', nl)
            )

        # Pattern 1: "gid://shopify/ProductVariant/XXXXX","1 Gallon"
        for match in re.finditer(
            r'ProductVariant/(\d+)\"?,\"([^\"]+?)\"', text
        ):
            vid, name = match.group(1), match.group(2)
            if _is_size_name(name):
                variant_names[vid] = name

        # Pattern 2: FGT / newer Shopify themes use selectedOptions or optionValues
        # e.g. "id":"gid://shopify/ProductVariant/XXXXX",...,"selectedOptions":[{"name":"Size","value":"1 Gallon"}]
        if not variant_names:
            for match in re.finditer(
                r'ProductVariant/(\d+)\".*?\"selectedOptions\"\s*:\s*\[([^\]]+)\]',
                text, re.DOTALL
            ):
                vid = match.group(1)
                opts_block = match.group(2)
                val_match = re.search(r'"value"\s*:\s*"([^"]+)"', opts_block)
                if val_match and _is_size_name(val_match.group(1)):
                    variant_names[vid] = val_match.group(1)

        # Pattern 2b: Newer Shopify Hydrogen / 2024+ themes use "optionValues"
        # e.g. "id":"gid://shopify/ProductVariant/XXXXX",...,"optionValues":[{"name":"1 Gallon"}]
        if not variant_names:
            for match in re.finditer(
                r'ProductVariant/(\d+)\"(?:(?!ProductVariant/).)*?\"optionValues\"\s*:\s*\[([^\]]*)\]',
                text, re.DOTALL
            ):
                vid = match.group(1)
                opts_block = match.group(2)
                val_match = re.search(r'"name"\s*:\s*"([^"]+)"', opts_block)
                if val_match and _is_size_name(val_match.group(1)):
                    variant_names[vid] = val_match.group(1)

        # Pattern 3: "option1":"1 Gallon" near variant ID
        if not variant_names:
            for match in re.finditer(
                r'"id"\s*:\s*(\d{10,})\b[^}]*?"option1"\s*:\s*"([^"]+)"',
                text
            ):
                vid, name = match.group(1), match.group(2)
                if _is_size_name(name):
                    variant_names[vid] = name

        # Pattern 4: Shopify product JSON "variants":[{"id":XXXX,"title":"1 Gallon",...}]
        if not variant_names:
            for match in re.finditer(
                r'"id"\s*:\s*(\d{10,})\s*,\s*"title"\s*:\s*"([^"]+)"',
                text
            ):
                vid, name = match.group(1), match.group(2)
                if name.lower() != 'default title' and _is_size_name(name):
                    variant_names[vid] = name

        # Pattern 5: Embedded product JSON blob — many Shopify themes include a
        # full product object in a <script> tag or JS variable. Extract variant
        # data from it: {"variants":[{"id":XXXX,"option1":"1 Gallon",...}]}
        if not variant_names:
            # Look for a JSON blob containing "variants" array
            json_blobs = re.findall(
                r'"variants"\s*:\s*\[(\{[^\]]{20,})\]',
                text, re.DOTALL
            )
            for blob in json_blobs[:3]:  # Limit to first 3 matches for performance
                # Parse individual variant objects from the array
                for vm in re.finditer(
                    r'"id"\s*:\s*(\d{10,})\b[^}]*?"option1"\s*:\s*"([^"]*)"',
                    blob
                ):
                    vid, name = vm.group(1), vm.group(2)
                    if name.lower() not in ('default title', '') and _is_size_name(name):
                        variant_names[vid] = name
                if variant_names:
                    break  # Found what we need

        # Pattern 6: FGT-style variant buttons with data attributes
        # e.g. data-variant-id="XXXX" ... >1 Gallon</button>
        if not variant_names:
            for match in re.finditer(
                r'data-variant-id=["\'](\d{10,})["\'][^>]*>([^<]{2,40})<',
                text
            ):
                vid, name = match.group(1), match.group(2).strip()
                if _is_size_name(name):
                    variant_names[vid] = name

        # Extract offer data: SKU → price + availability
        # Exclude pack variants (e.g., SKU "12345-4PACK") — these are multi-plant
        # bundles with inflated prices that don't represent single-plant pricing.
        all_offers = re.findall(
            r'\{\"@type\":\"Offer\",\"sku\":\"(\d+(?:-\w+)?)\".*?'
            r'\"price\":\"([\d.]+)\".*?'
            r'\"availability\":\"([^\"]+)\"',
            text
        )
        offers = [(sku, p, a) for sku, p, a in all_offers
                  if 'pack' not in sku.lower()]

        # Also try to find strikethrough prices per SKU
        was_prices = {}
        for match in re.finditer(
            r'\"sku\":\"(\d+)\".*?\"StrikethroughPrice\".*?\"price\":\"([\d.]+)\"',
            text[:50000]  # Limit search scope for performance
        ):
            was_prices[match.group(1)] = float(match.group(2))

        # Strategy: Use aria-label prices ALWAYS when they exist and have size names.
        # They are the most reliable source — directly from the rendered page with
        # human-readable size names and correct single-plant prices.
        # Schema.org Offers are a fallback ONLY when no aria-labels found.
        aria_offers = re.findall(
            r'aria-label=\"([^\"]*?)\s*-\s*Sale price:\s*([\d.]+)\s*-\s*List price:\s*\$?([\d.]+)',
            text
        )
        # Filter out packs, singles, and quantity options — keep only size names
        aria_offers = [(n, s, lp) for n, s, lp in aria_offers
                       if 'pack' not in n.lower()
                       and 'single' not in n.lower()
                       and not re.match(r'^\d+-(?:pack|pk)', n.lower())]

        # Use aria-labels if we got ANY valid size-named results
        if aria_offers:
            sizes = {}
            any_available = True
            for size_name, sale_price, list_price in aria_offers:
                tier = self._normalize_size(size_name)
                sizes[tier] = {
                    "price": float(sale_price),
                    "was_price": float(list_price) if float(list_price) > float(sale_price) else None,
                    "available": True,
                    "raw_size": size_name,
                }
            if sizes:
                title_match = re.search(r'<title>([^<]+)</title>', text)
                title = title_match.group(1).split("|")[0].strip() if title_match else handle.replace("-", " ").title()
                return {
                    "retailer_id": self.retailer_id,
                    "retailer_name": self.retailer_id.replace("-", " ").title(),
                    "handle": handle,
                    "title": title,
                    "url": url,
                    "sizes": sizes,
                    "in_stock": any_available,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        if not offers:
            # Last resort: try matching size buttons to schema.org Offers by position
            # Some products have plain buttons (e.g., "3-4 feet") without price in aria-label
            size_buttons = re.findall(
                r'aria-(?:label|pressed)=\"[^\"]*\"[^>]*>(\d+-\d+\s*(?:ft|feet|foot))',
                text, re.IGNORECASE
            )
            if not size_buttons:
                # Try plain button text
                size_buttons = re.findall(r'>(\d+-\d+\s*(?:ft|feet))\s*<', text, re.IGNORECASE)
                # Deduplicate while preserving order
                seen = set()
                deduped = []
                for s in size_buttons:
                    if s.lower() not in seen:
                        seen.add(s.lower())
                        deduped.append(s)
                size_buttons = deduped

            # Get schema.org offers (without pack variants)
            schema_offers = re.findall(
                r'\{\"@type\":\"Offer\",\"sku\":\"(\d+)\".*?\"price\":\"([\d.]+)\".*?\"availability\":\"([^\"]+)\"',
                text
            )
            non_pack_offers = [(s, p, a) for s, p, a in schema_offers if 'PACK' not in s.upper()]

            if size_buttons and non_pack_offers:
                sizes = {}
                any_available = False
                # When offer count > button count, hidden out-of-stock variants
                # cause position mismatch. Filter to InStock offers first.
                matching_offers = non_pack_offers
                if len(non_pack_offers) > len(size_buttons):
                    in_stock_offers = [(s, p, a) for s, p, a in non_pack_offers if "InStock" in a]
                    if len(in_stock_offers) == len(size_buttons):
                        matching_offers = in_stock_offers
                    elif len(in_stock_offers) > len(size_buttons):
                        # Still too many — take the last N (largest/most expensive)
                        matching_offers = in_stock_offers[-len(size_buttons):]
                    else:
                        # Fewer in-stock than buttons — take last N from all offers
                        matching_offers = non_pack_offers[-len(size_buttons):]
                for i, (sku, price_str, avail) in enumerate(matching_offers):
                    size_name = size_buttons[i] if i < len(size_buttons) else f"Size {i+1}"
                    tier = self._normalize_size(size_name)
                    in_stock = "InStock" in avail
                    if in_stock:
                        any_available = True
                    sizes[tier] = {
                        "price": float(price_str),
                        "was_price": None,
                        "available": in_stock,
                        "raw_size": size_name,
                    }

                if sizes:
                    title_match = re.search(r'<title>([^<]+)</title>', text)
                    title = title_match.group(1).split("|")[0].strip() if title_match else handle.replace("-", " ").title()
                    return {
                        "retailer_id": self.retailer_id,
                        "retailer_name": self.retailer_id.replace("-", " ").title(),
                        "handle": handle,
                        "title": title,
                        "url": url,
                        "sizes": sizes,
                        "in_stock": any_available,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

            return None

        # If variant_names mapping is empty, try size buttons as fallback
        if not variant_names:
            size_buttons = re.findall(
                r'aria-(?:label|pressed)=\"[^\"]*\"[^>]*>(\d+-\d+\s*(?:ft|feet|foot))',
                text, re.IGNORECASE
            )
            if not size_buttons:
                raw_buttons = re.findall(r'>(\d+-\d+\s*(?:ft|feet))\s*<', text, re.IGNORECASE)
                seen = set()
                for s in raw_buttons:
                    if s.lower() not in seen:
                        seen.add(s.lower())
                        size_buttons.append(s)
            # Also look for gallon-based buttons
            if not size_buttons:
                size_buttons = re.findall(
                    r'aria-(?:label|pressed)=\"[^\"]*\"[^>]*>(\d+\s*(?:gallon|gal|quart|qt))',
                    text, re.IGNORECASE
                )

            # Map by price order: sort offers by price ascending, match to buttons in order
            # Buttons are always displayed smallest→largest, and cheapest→most expensive
            # IMPORTANT: when offer count > button count, hidden out-of-stock variants
            # cause position mismatch. Filter to InStock offers when counts don't match.
            non_pack_offers = [(s, p, a) for s, p, a in offers if "PACK" not in s.upper()]
            sorted_offers = sorted(non_pack_offers, key=lambda x: float(x[1]))
            if size_buttons and len(sorted_offers) > len(size_buttons):
                in_stock_sorted = [o for o in sorted_offers if "InStock" in o[2]]
                if len(in_stock_sorted) >= len(size_buttons):
                    sorted_offers = in_stock_sorted
            if size_buttons and len(sorted_offers) > 0:
                for i, (sku_raw, _, _) in enumerate(sorted_offers):
                    sku = sku_raw.split("-")[0]
                    if i < len(size_buttons):
                        variant_names[sku] = size_buttons[i]

        # Build sizes dict from offers + variant names
        sizes = {}
        any_available = False

        for sku_raw, price_str, availability in offers:
            # Skip bulk packs
            sku = sku_raw.split("-")[0]  # Strip -10PACK suffix
            if "PACK" in sku_raw.upper():
                continue

            price = float(price_str)
            if price <= 0:
                continue

            in_stock = "InStock" in availability
            if in_stock:
                any_available = True

            # Map SKU to size name
            size_name = variant_names.get(sku, f"variant-{sku}")
            tier = self._normalize_size(size_name)
            was = was_prices.get(sku)

            sizes[tier] = {
                "price": price,
                "was_price": was if was and was > price else None,
                "available": in_stock,
                "raw_size": size_name,
            }

        if not sizes:
            return None

        # Try to extract product title
        title_match = re.search(r'<title>([^<]+)</title>', text)
        title = title_match.group(1).split("|")[0].strip() if title_match else handle.replace("-", " ").title()

        return {
            "retailer_id": self.retailer_id,
            "retailer_name": self.retailer_id.replace("-", " ").title(),
            "handle": handle,
            "title": title,
            "url": url,
            "sizes": sizes,
            "in_stock": any_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _normalize_size(self, variant_title: str) -> str:
        """Map a variant title to a canonical size tier.

        Handles all retailer naming conventions:
        - FGT: "1 quart", "1 gallon", "3-4 feet"
        - Nature Hills: "#1 Container", "#3 Container 3-4 Feet", "Quart Container"
        - Spring Hill: "PREMIUM / 1 Plant(s) | Ships in Spring", "JUMBO / ...", "1 GALLON - 2-4 FT / ..."
        - PlantingTree: "1 Gallon", "2-3 Feet"
        - GGP: "One Quart", "One Gallon", "3 Feet (One Gallon)"
        - PWD: "1 Gallon / Ship Week 23 (June 1st – June 5th)"
        - Stark Bros: "Honeycrisp Apple Dwarf", "Semi-Dwarf", "Supreme"
        """
        raw = variant_title.strip()
        title_lower = raw.lower()

        # Step 1: Strip metadata that isn't size info
        # Remove "/ 1 Plant(s)", "/ 3 Plant(s)", etc.
        title_lower = re.sub(r'/\s*\d+\s*plant\(s\)', '', title_lower)
        # Remove "| Ships in Spring/Fall/Year-round"
        title_lower = re.sub(r'\|\s*ships?\s+in\s+\S+', '', title_lower)
        # Remove "/ Ship Week NN (dates)"
        title_lower = re.sub(r'/\s*ship\s+week\s+\d+\s*\([^)]*\)', '', title_lower)
        # Remove "Ships Now"
        title_lower = re.sub(r'/?\s*ships?\s+now', '', title_lower)
        title_lower = title_lower.strip().strip('/').strip()

        # Step 2: Container/gallon patterns (most universal — check first)
        gallon_patterns = [
            # Explicit gallon — gal / gallon / gallons (all plural forms)
            (r'\b1[\s-]?gal(?:lon)?s?\b', '1gal'),
            (r'one\s+gallon', '1gal'),
            (r'#1\s*container', '1gal'),
            (r'trade\s+gallon', '1gal'),
            (r'\b2[\s-]?gal(?:lon)?s?\b', '2gal'),
            (r'#2\s*container', '2gal'),
            (r'\b3[\s-]?gal(?:lon)?s?\b', '3gal'),
            (r'3\s*gallon\s*pot', '3gal'),
            (r'#3\s*container', '3gal'),
            (r'\b5[\s-]?gal(?:lon)?s?\b', '5gal'),
            (r'#5\s*container', '5gal'),
            (r'\b7[\s-]?gal(?:lon)?s?\b', '7gal'),
            (r'#7\s*container', '7gal'),
            (r'\b10[\s-]?gal(?:lon)?s?\b', '10gal'),
            (r'\b15[\s-]?gal(?:lon)?s?\b', '15gal'),
            # Quart
            (r'\bquart\b', 'quart'),
            (r'\bqt\b', 'quart'),
            (r'one\s+quart', 'quart'),
            (r'4\.5[\s-]?(?:in|")', 'quart'),
            # Small pots
            (r'\b3[\s-]?(?:inch|in|")\s*pot', '3inch'),
            (r'\b4[\s-]?inch', '4inch'),
            (r'\b4[\s-]?"', '4inch'),
            (r'\b6[\s-]?inch\s*pot', '6inch'),
        ]

        for pattern, tier in gallon_patterns:
            if re.search(pattern, title_lower):
                return tier

        # Step 3: Bare root / dormant / field (check BEFORE height matching)
        if 'dormant' in title_lower:
            return 'bareroot'
        if 'field' in title_lower:
            inch_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*"', title_lower)
            if inch_match:
                return f'{inch_match.group(1)}-{inch_match.group(2)}in'
            return 'field'

        # Step 4: Height-based sizing (trees)
        # Match "X-Y feet/ft/'" patterns — use ACTUAL numbers, don't bucket
        # Do NOT match " (double quote = inches, not feet)
        height_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:ft|feet|foot|\')', title_lower)
        if height_match:
            low, high = int(height_match.group(1)), int(height_match.group(2))
            return f"{low}-{high}ft"

        # Match "X'" or "X ft" single height
        single_height = re.search(r'\b(\d+)\s*(?:ft|feet|foot|\')\b', title_lower)
        if single_height and not re.search(r'gal|container|quart', title_lower):
            h = int(single_height.group(1))
            return f"{h}ft"

        # Step 5: Spring Hill specialty tiers
        if 'jumbo' in title_lower:
            return 'jumbo-bareroot'
        if 'premium' in title_lower:
            return 'premium-bareroot'
        if re.search(r'bare[\s-]?root', title_lower):
            return 'bareroot'

        # Step 6: Stark Bros rootstock variants
        if 'ultra supreme' in title_lower or 'ultra-supreme' in title_lower:
            return 'ultra-supreme'
        if 'supreme' in title_lower:
            return 'supreme'
        if 'semi-dwarf' in title_lower or 'semi dwarf' in title_lower:
            return 'semi-dwarf'
        if 'dwarf' in title_lower:
            return 'dwarf'
        if 'standard' in title_lower:
            return 'standard'

        # Step 7: Bulb
        if re.search(r'\bbulbs?\b', title_lower):
            return 'bulb'

        # Step 8: "Default Title", empty, or raw variant IDs — return generic
        if not title_lower or title_lower == 'default title':
            return 'default'
        # Catch raw Shopify variant IDs that slipped through (e.g. "variant-44912345678")
        if re.match(r'^variant-\d{7,}$', title_lower):
            return 'default'

        # Step 9: Unrecognized — return cleaned version
        cleaned = re.sub(r'[^a-z0-9]+', '-', title_lower).strip('-')
        # If the cleaned result is just a long number, it's a variant ID — treat as default
        if re.match(r'^\d{7,}$', cleaned):
            return 'default'
        return cleaned

    def scrape_promo_codes(self) -> list[dict]:
        """Check the retailer's homepage for promo codes or discount banners.

        Hits the homepage once per run (not per product) and scans for:
        - Shopify announcement bars (class-based)
        - Text patterns: "use code X", "promo code X", "save X% with X"
        - Discount code patterns: standalone uppercase alphanumeric codes

        Returns list of dicts like:
            [{"code": "SAVE20", "description": "Save 20% sitewide", "source": "announcement-bar"}]
        """
        try:
            resp = self.session.get(self.base_url, timeout=20, headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html",
            })
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Promo check failed for {self.retailer_id}: {e}")
            return []

        text = resp.text
        promos = []
        seen_codes = set()

        # Extract announcement bar / header banner text
        # Shopify uses various class names for the top announcement bar
        bar_patterns = [
            r'class="[^"]*announcement[^"]*"[^>]*>(.*?)</[a-z]+>',
            r'class="[^"]*header-banner[^"]*"[^>]*>(.*?)</[a-z]+>',
            r'class="[^"]*promo-bar[^"]*"[^>]*>(.*?)</[a-z]+>',
            r'class="[^"]*top-bar[^"]*"[^>]*>(.*?)</[a-z]+>',
            r'class="[^"]*site-wide[^"]*"[^>]*>(.*?)</[a-z]+>',
            r'class="[^"]*marquee[^"]*"[^>]*>(.*?)</[a-z]+>',
        ]
        bar_texts = []
        for pattern in bar_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
                # Strip HTML tags
                raw = re.sub(r'<[^>]+>', ' ', m.group(1))
                raw = re.sub(r'\s+', ' ', raw).strip()
                if raw and len(raw) < 300:
                    bar_texts.append(raw)

        # Also pull text from <header> and first ~5000 chars (banner usually at top)
        header_match = re.search(r'<header[^>]*>(.*?)</header>', text, re.DOTALL | re.IGNORECASE)
        if header_match:
            raw = re.sub(r'<[^>]+>', ' ', header_match.group(1))
            bar_texts.append(re.sub(r'\s+', ' ', raw).strip()[:500])
        bar_texts.append(re.sub(r'<[^>]+>', ' ', text[:5000]))

        search_text = ' '.join(bar_texts)

        # Pattern 1: "use code XXXX" / "enter code XXXX" / "promo code: XXXX"
        explicit_patterns = [
            r'(?:use|enter|apply)\s+(?:code\s+)?([A-Z][A-Z0-9]{2,19})\b',
            r'promo(?:\s+code)?[:\s]+([A-Z][A-Z0-9]{2,19})\b',
            r'coupon(?:\s+code)?[:\s]+([A-Z][A-Z0-9]{2,19})\b',
            r'discount(?:\s+code)?[:\s]+([A-Z][A-Z0-9]{2,19})\b',
            r'code[:\s]+([A-Z][A-Z0-9]{2,19})\b',
        ]
        for pat in explicit_patterns:
            for m in re.finditer(pat, search_text, re.IGNORECASE):
                code = m.group(1).upper()
                if code in seen_codes or len(code) < 3:
                    continue
                # Exclude common false positives
                if code in {'HTTP', 'HTML', 'FREE', 'SHIP', 'SALE', 'BEST', 'MORE', 'SHOP', 'VIEW'}:
                    continue
                # Extract surrounding context as description (up to 100 chars)
                start = max(0, m.start() - 20)
                end = min(len(search_text), m.end() + 60)
                description = re.sub(r'\s+', ' ', search_text[start:end]).strip()
                promos.append({"code": code, "description": description, "source": "text-pattern"})
                seen_codes.add(code)

        # Pattern 2: Savings percentage mentions (e.g. "20% off", "save $10")
        # These aren't codes but are worth capturing as discount info
        savings_match = re.search(
            r'(?:save|get)\s+(?:up\s+to\s+)?(\d+%|\$\d+)\s+(?:off|on)',
            search_text, re.IGNORECASE
        )
        if savings_match and not promos:
            start = max(0, savings_match.start() - 10)
            end = min(len(search_text), savings_match.end() + 80)
            description = re.sub(r'\s+', ' ', search_text[start:end]).strip()
            promos.append({"code": None, "description": description[:200], "source": "savings-banner"})

        if promos:
            logger.info(f"  {self.retailer_id}: found {len(promos)} promo(s)")
        else:
            logger.debug(f"  {self.retailer_id}: no promos detected")

        return promos

    def discover_products(self, collection: str = None, limit: int = 250) -> list[str]:
        """Discover product handles from a collection or full catalog.

        Args:
            collection: Collection handle (e.g., "hydrangeas"). None = all products.
            limit: Max products per page (Shopify max is 250).

        Returns:
            List of product handles.
        """
        handles = []
        page = 1

        while True:
            if collection:
                url = f"{self.base_url}/collections/{collection}/products.json?limit={limit}&page={page}"
            else:
                url = f"{self.base_url}/products.json?limit={limit}&page={page}"

            data = self._get_json(url)
            if not data or "products" not in data:
                break

            products = data["products"]
            if not products:
                break

            for p in products:
                handles.append(p.get("handle", ""))

            if len(products) < limit:
                break  # Last page

            page += 1
            self._delay()

        return [h for h in handles if h]


# ---------------------------------------------------------------------------
# Handle mapping: maps canonical plant IDs to Shopify product handles
# per retailer. This is the entity resolution layer.
# ---------------------------------------------------------------------------

HANDLE_MAPS = {
    "fast-growing-trees": {
        # Hydrangeas (verified from /collections/hydrangea-shrubs)
        "limelight-hydrangea": "limelight-hydrangea-shrub",
        "endless-summer-hydrangea": "endless-summer-hydrangea",
        "nikko-blue-hydrangea": "hydrangeanikko",
        "incrediball-hydrangea": "incrediball-hydrangea",
        "little-lime-hydrangea": "little-lime-hydrangea-shrub",
        "bloomstruck-hydrangea": "bloomstruck-hydrangea-shrub",
        "summer-crush-hydrangea": "summer-crush-hydrangea",
        # Pinky Winky and Fire Light NOT on FGT — skip
        # Japanese Maples (verified from /collections/japanese-maple-trees)
        "bloodgood-japanese-maple": "bloodgood-japanese-maple",
        "coral-bark-japanese-maple": "coral-bark-japanese-maple",
        "crimson-queen-japanese-maple": "crimson-queen-japanese-maple",
        "emperor-japanese-maple": "emperor-japanese-maple-tree",
        "tamukeyama-japanese-maple": "tamukeyama-japanese-maple",
        # Privacy Trees (verified)
        "emerald-green-arborvitae": "emerald-green-arborvitae",
        "green-giant-arborvitae": "thuja-green-giant",
        "leyland-cypress": "leylandcypress",
        "skip-laurel": "cherry-skip-laurel",
        # Fruit Trees (verified from /collections/fruit-trees)
        "honeycrisp-apple-tree": "honeycrisp-apple-tree",
        "bing-cherry-tree": "bingcherry",
        # Roses (verified from search results)
        "double-knock-out-rose": "red-double-knockout-roses",
        "sunny-knock-out-rose": "sunny-knockout-roses",
        "coral-knock-out-rose": "coral-knock-out-rose",
        # Blueberries
        "pink-lemonade-blueberry": "pink-lemonade-blueberry",
        # Newly verified handles for POOR coverage plants
        "fuji-apple-tree": "low-chill-fuji-apple-tree",
        "stella-cherry-tree": "stella-cherry-tree-ca",
        "nellie-stevens-holly": "nelliestevensholly",
        "duke-blueberry": "duke-blueberry-bush-or",
        "sunshine-blue-blueberry": "sunshine-blue-blueberry-bush-ca",
        "eastern-redbud": "eastern-redbud-tree-form-ca",
        "forest-pansy-redbud": "forest-pansy-redbud",
        "white-knock-out-rose": "white-out-roses",
        "kousa-dogwood": "kousa-dogwood",
        "pjm-rhododendron": "pjm-elite-rhododendron",
        "delaware-valley-white-azalea": "delaware-valley-white-azalea",
        "meyer-lemon-tree": "meyer-lemon-tree",
        "encore-azalea": "azalea-encore-autumn-kiss-shrub",
        "dogwood-tree": "cherokee-princess-dogwood",
        "crape-myrtle": "natchez-crape-myrtle",
        "saucer-magnolia": "saucer-magnolia",
    },
    "proven-winners-direct": {
        # Verified from /collections/hydrangeas (JSON endpoint works!)
        "limelight-hydrangea": "limelight-panicle-hydrangea",
        "incrediball-hydrangea": "incrediball-smooth-hydrangea",
        "little-lime-hydrangea": "little-lime-panicle-hydrangea",
        "fire-light-hydrangea": "fire-light-panicle-hydrangea",
        "bobo-hydrangea": "bobo-panicle-hydrangea",
        # PWD only carries Proven Winners branded plants — no roses, maples, fruit trees
    },
    "nature-hills": {
        # Handles verified/updated 2026-04-05 — 15 products discontinued, 4 handles updated
        # Hydrangeas
        "limelight-hydrangea": "hydrangea-lime-light",
        "endless-summer-hydrangea": "the-original-endless-summer-hydrangea",
        # nikko-blue-hydrangea: discontinued by Nature Hills (2026-04)
        "little-lime-hydrangea": "little-lime-hydrangea",
        "incrediball-hydrangea": "hydrangea-incrediball",
        "fire-light-hydrangea": "fire-light-hydrangea",
        "bloomstruck-hydrangea": "endless-summer-bloomstruck-hydrangea",
        "pinky-winky-hydrangea": "pinky-winky-hydrangea",
        "summer-crush-hydrangea": "summer-crush-endless-summer-hydrangea",
        # Japanese Maples
        "bloodgood-japanese-maple": "bloodgood-japanese-maple",
        "coral-bark-japanese-maple": "coral-bark-japanese-maple",
        # crimson-queen-japanese-maple: discontinued by Nature Hills (2026-04)
        "emperor-japanese-maple": "japanese-maple-emperor-one",
        "tamukeyama-japanese-maple": "tamukeyama-japanese-maple-tree",
        # Fruit Trees
        "honeycrisp-apple-tree": "honeycrisp-apple-tree",
        "fuji-apple-tree": "fuji-apple-tree",
        # bing-cherry-tree: discontinued by Nature Hills (2026-04)
        # stella-cherry-tree: discontinued by Nature Hills (2026-04)
        # elberta-peach-tree: discontinued by Nature Hills (2026-04)
        # Privacy Trees
        "emerald-green-arborvitae": "arborvitae-emerald",
        "green-giant-arborvitae": "arborvitae-green-giant",
        # leyland-cypress: discontinued by Nature Hills (2026-04)
        # nellie-stevens-holly: discontinued by Nature Hills (2026-04)
        # skip-laurel: discontinued by Nature Hills (2026-04)
        # Roses
        "double-knock-out-rose": "red-double-knock-out-rose",
        "knock-out-rose": "the-original-knock-out-rose",
        "white-knock-out-rose": "white-knock-out-rose",
        "pink-knock-out-rose": "rose-pink-knock-out-shrub",
        "sunny-knock-out-rose": "rose-sunny-knock-out-shrub",
        "coral-knock-out-rose": "coral-knock-out-rose",
        # Blueberries
        "duke-blueberry": "blueberry-duke",
        "bluecrop-blueberry": "blueberry-bluecrop",
        "patriot-blueberry": "blueberry-patriot",
        "pink-lemonade-blueberry": "blueberry-pink-lemonade",
        # sunshine-blue-blueberry: discontinued by Nature Hills (2026-04)
        # Flowering Trees
        "eastern-redbud": "eastern-redbud",
        "forest-pansy-redbud": "forest-pansy-redbud",
        "yoshino-cherry": "yoshino-flowering-cherry",
        # saucer-magnolia: discontinued by Nature Hills (2026-04)
        # Azaleas & Rhododendrons
        "pjm-rhododendron": "elite-pmj-rhododendron",
        "nova-zembla-rhododendron": "rhododendron-nova-zembla",
        "gibraltar-azalea": "gibraltar-azalea",
        # New plants (verified 2026-04-03)
        "stella-de-oro-daylily": "daylily-stella-de-oro",
        "hosta-sum-and-substance": "hosta-sum-and-substance",
        "lavender-phenomenal": "phenomenal-french-lavender",
        "black-eyed-susan-goldsturm": "black-eyed-susan-goldsturm",
        "peony-sarah-bernhardt": "sarah-bernhardt-peony",
        "clematis-jackmanii": "clematis-jackmanii",
        "green-mountain-boxwood": "green-mountain-boxwood",
        # wax-leaf-privet: discontinued by Nature Hills (2026-04)
        "chicago-hardy-fig": "fig-tree-chicago-hardy",
        "arbequina-olive": "arbequina-olive-tree",
        # hass-avocado: not carried by Nature Hills (2026-04)
        # zz-plant: not carried by Nature Hills (2026-04)
        # money-tree: not carried by Nature Hills (2026-04)
        # fiddle-leaf-fig: not carried by Nature Hills (2026-04)
        "karl-foerster-grass": "grass-feather-reed",
        "creeping-phlox": "phlox-emerald-pink",
        "butterfly-bush-miss-molly": "butterfly-bush-miss-molly",
        "forsythia-lynwood-gold": "forsythia-lynwood-gold",
        "miss-kim-lilac": "lilac-miss-kim",
        "tulip-poplar": "tulip-poplar",
        "weeping-willow": "golden-weeping-willow",
        "autumn-blaze-maple": "autumn-blaze-red-maple",
    },
    "spring-hill": {
        # 25 handles verified via JSON 2026-04-03
        # Hydrangeas
        "limelight-hydrangea": "limelight-hydrangea",
        "endless-summer-hydrangea": "endless-summer-hydrangea",
        "nikko-blue-hydrangea": "nikko-blue-hydrangea",
        "bloomstruck-hydrangea": "endless-summer-bloomstruck-hydrangea",
        "summer-crush-hydrangea": "summer-crush-hydrangea",
        "incrediball-hydrangea": "incrediball_hydrangea-hydrangea_arborenscens_abetwo",
        # Japanese Maples
        "bloodgood-japanese-maple": "bloodgood-japanese-maple",
        "coral-bark-japanese-maple": "coral-bark-japanese-maple",
        "crimson-queen-japanese-maple": "crimson-queen-japanese-maple",
        "tamukeyama-japanese-maple": "tamukeyama-japanese-maple",
        # Fruit Trees
        "honeycrisp-apple-tree": "honeycrisp-apple",
        "bartlett-pear-tree": "pear-bartlett-semi-dwarf",
        # Privacy Trees
        "emerald-green-arborvitae": "emerald-green-arborvitae",
        "green-giant-arborvitae": "green-giant-thuja",
        "leyland-cypress": "leyland-cypress",
        # Roses
        "double-knock-out-rose": "double-knock-out-rose",
        "pink-knock-out-rose": "rose-knock-out-pink-double",
        "sunny-knock-out-rose": "rose-knock-out-sunny-yellow",
        # Blueberries
        "duke-blueberry": "duke-blueberry",
        "bluecrop-blueberry": "bluecrop-blueberry",
        "patriot-blueberry": "patriot-blueberry",
        "pink-lemonade-blueberry": "pink-lemonade-blueberry-39858",
        "sunshine-blue-blueberry": "blueberry-sunshine-blue",
        # Flowering Trees
        "yoshino-cherry": "yoshino-flowering-cherry",
        # Azaleas
        "gibraltar-azalea": "gibraltar-azalea",
    },
    "planting-tree": {
        # All 36 handles verified via JSON endpoint 2026-04-03
        # Hydrangeas
        "limelight-hydrangea": "limelight-hydrangea",
        "endless-summer-hydrangea": "endless-summer-hydrangea",
        "nikko-blue-hydrangea": "nikko-blue-hydrangea",
        "bloomstruck-hydrangea": "bloomstruck-hydrangea",
        "summer-crush-hydrangea": "summer-crush-hydrangea",
        "little-lime-hydrangea": "little-lime-hydrangea",
        "pinky-winky-hydrangea": "pinky-winky-hydrangea-tree",
        "fire-light-hydrangea": "firelight-hydrangea",
        # Japanese Maples
        "bloodgood-japanese-maple": "bloodgood-japanese-maple",
        "coral-bark-japanese-maple": "coral-bark-japanese-maple",
        "crimson-queen-japanese-maple": "crimson-queen-japanese-maple-tree",
        "tamukeyama-japanese-maple": "weeping-tamukeyama-japanese-maple",
        "emperor-japanese-maple": "emperor-japanese-maple",
        # Fruit Trees
        "honeycrisp-apple-tree": "honeycrisp-apple-tree",
        "fuji-apple-tree": "fuji-apple-tree",
        "bing-cherry-tree": "bing-cherry-tree",
        "stella-cherry-tree": "stella-cherry-tree",
        "elberta-peach-tree": "elberta-peach-tree",
        "bartlett-pear-tree": "bartlett-pear-tree",
        # Privacy Trees
        "emerald-green-arborvitae": "emerald-green-arborvitae",
        "green-giant-arborvitae": "thuja-green-giant",
        "leyland-cypress": "leyland-cypress",
        "skip-laurel": "skip-laurel",
        "nellie-stevens-holly": "nellie-stevens-holly",
        # Roses
        "double-knock-out-rose": "double-knock-out-rose",
        "pink-knock-out-rose": "pink-double-knock-out-rose",
        "sunny-knock-out-rose": "sunny-knock-out-rose",
        "coral-knock-out-rose": "coral-knock-out-rose-shrub",
        # Blueberries
        "bluecrop-blueberry": "bluecrop-blueberry-bush",
        "pink-lemonade-blueberry": "pink-lemonade-blueberry-bush",
        # Flowering Trees
        "kousa-dogwood": "white-kousa-dogwood-tree",
        "eastern-redbud": "eastern-redbud",
        "forest-pansy-redbud": "forest-pansy-redbud",
        "yoshino-cherry": "weeping-yoshino-cherry-tree",
        # Azaleas
        "delaware-valley-white-azalea": "delaware-valley-white-azalea",
        "encore-azalea": "autumn-royalty-encore-azalea",
        # New plants (verified 2026-04-03)
        "stella-de-oro-daylily": "stella-de-oro-daylily",
        "lavender-phenomenal": "phenomenal-lavender-plant",
        "green-mountain-boxwood": "green-mountain-boxwood",
        "chicago-hardy-fig": "chicago-hardy-fig",
        "arbequina-olive": "arbequina-olive-tree",
        "hass-avocado": "hass-avocado-tree",
        "money-tree": "money-tree",
        "peace-lily": "peace-lily-gift-plant",
        "fiddle-leaf-fig": "fiddle-leaf-fig",
        "miscanthus-morning-light": "morning-light-miscanthus-maiden-grass",
        "creeping-phlox": "red-creeping-phlox",
        "butterfly-bush-miss-molly": "miss-molly-butterfly-bush",
        "forsythia-lynwood-gold": "lynwood-gold-forsythia",
        "miss-kim-lilac": "miss-kim-lilac",
        "tulip-poplar": "tulip-poplar",
        "weeping-willow": "weeping-willow",
        "autumn-blaze-maple": "autumn-blaze-maple",
        "karl-foerster-grass": "karl-foerster-grass",
    },
    "great-garden-plants": {
        # JSON endpoint works! greatgardenplants.com/products/{handle}.json
        # No fruit trees or Japanese maples carried
        "limelight-hydrangea": "limelight-panicle-hydrangea",
        "double-knock-out-rose": "double-knock-out-rose",
        "emerald-green-arborvitae": "emerald-green-arborvitae-aka-smaragd",
        "endless-summer-hydrangea": "endless-summer-original-bigleaf-hydrangea",
        "little-lime-hydrangea": "little-lime-panicle-hydrangea",
        "fire-light-hydrangea": "fire-light-panicle-hydrangea",
        "incrediball-hydrangea": "incrediball-smooth-hydrangea",
    },
    "brighter-blooms": {
        # JSON endpoint disabled — uses HTML fallback
        # Handles verified 2026-04-03 against brighterblooms.com/products.json (976 products)
        # NOTE: BB sells KO roses only as tree standards, not shrubs — knock-out-rose removed
        "limelight-hydrangea": "limelight-hydrangea",
        "endless-summer-hydrangea": "endless-summer-hydrangea",
        "double-knock-out-rose": "double-red-knockout-rose",      # was: double-knockout-rose (404)
        "bloodgood-japanese-maple": "bloodgood-japanese-maple",
        "emerald-green-arborvitae": "emerald-green-thuja",        # was: emerald-green-arborvitae (404)
        "leyland-cypress": "leyland-cypress-tree",
        "green-giant-arborvitae": "thuja-green-giant",
        "honeycrisp-apple-tree": "honeycrisp-apple",              # was: honeycrisp-apple-tree (404)
    },
}


def get_handles_for_retailer(retailer_id: str, plant_ids: list[str]) -> dict[str, str]:
    """Get the Shopify handle mapping for a retailer.

    Returns dict of {plant_id: shopify_handle} for plants this retailer carries.
    """
    mapping = HANDLE_MAPS.get(retailer_id, {})
    return {pid: mapping[pid] for pid in plant_ids if pid in mapping}
