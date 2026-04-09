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
from pathlib import Path

import requests

from scrapers.polite import (
    USER_AGENTS, polite_delay,
    log_request, is_allowed_by_robots, make_polite_session,
)
from scrapers.recovery import FetchResult

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

    def _get_json(self, url: str, allow_redirects: bool = True) -> FetchResult:
        """Fetch JSON from URL with error handling and robots.txt compliance.

        Returns a FetchResult with data, status_code, and redirect_url.
        When allow_redirects=False, a 301/302 response returns the
        redirect URL without following it.
        """
        if not is_allowed_by_robots(url):
            return FetchResult(data=None, status_code=None, redirect_url=None)
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=allow_redirects)
            log_request(url, status_code=resp.status_code)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                logger.warning(f"Rate limited by {self.retailer_id}, waiting {retry_after}s")
                time.sleep(retry_after)
                resp = self.session.get(url, timeout=20, allow_redirects=allow_redirects)
                log_request(url, status_code=resp.status_code)
            if resp.status_code in (301, 302) and not allow_redirects:
                redirect_url = resp.headers.get("Location")
                return FetchResult(data=None, status_code=resp.status_code, redirect_url=redirect_url)
            if resp.status_code == 404:
                logger.info(f"Product not found: {url}")
                return FetchResult(data=None, status_code=404, redirect_url=None)
            if resp.status_code >= 500:
                logger.warning(f"Server error {resp.status_code} for {url}")
                return FetchResult(data=None, status_code=resp.status_code, redirect_url=None)
            resp.raise_for_status()
            return FetchResult(data=resp.json(), status_code=resp.status_code, redirect_url=None)
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return FetchResult(data=None, status_code=None, redirect_url=None)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {url}: {e}")
            return FetchResult(data=None, status_code=None, redirect_url=None)

    def scrape_product(self, handle: str, plant_id: str = None) -> dict | None:
        """Scrape a single product by its Shopify handle.

        Tries JSON endpoint first (fastest, most structured).
        Falls back to HTML scraping if JSON endpoint returns 404 (some stores disable it).

        On 301/302: records a redirect candidate and follows the redirect.
        On 404: records a broken handle entry (if plant_id provided).
        On 5xx: skips silently (server problem, not a handle change).

        Args:
            handle: The Shopify product handle (URL slug), e.g. "limelight-hydrangea-shrub"
            plant_id: Optional plant ID for recovery tracking.

        Returns:
            Structured dict with price data, or None on failure.
        """
        from scrapers.recovery import (
            record_broken,
            record_redirect_candidate,
            extract_handle_from_url,
        )

        # Try JSON endpoint first — with redirect detection
        json_url = f"{self.base_url}/products/{handle}.json"
        result = self._get_json(json_url, allow_redirects=False)

        # Handle redirect: record candidate and follow for data
        if result.status_code in (301, 302) and result.redirect_url:
            new_handle = extract_handle_from_url(result.redirect_url)
            if plant_id and new_handle:
                record_redirect_candidate(
                    self.retailer_id, plant_id, handle,
                    new_handle, result.redirect_url,
                )
            # Follow the redirect to get data for this run
            follow_result = self._get_json(result.redirect_url)
            if follow_result.data and "product" in follow_result.data:
                return self._parse_product(follow_result.data["product"])
            # JSON redirect didn't yield data — try HTML on new handle
            if new_handle:
                return self._scrape_product_html(new_handle)
            return None

        # Handle 5xx: skip silently — server problem, not a handle change
        if result.status_code is not None and result.status_code >= 500:
            return None

        # Handle 404: record broken handle and try HTML fallback
        if result.status_code == 404:
            if plant_id:
                record_broken(self.retailer_id, plant_id, handle)
            # Fall back to HTML scraping
            logger.info(f"  JSON endpoint unavailable, trying HTML for {handle}")
            return self._scrape_product_html(handle)

        # Normal success path
        if result.data and "product" in result.data:
            return self._parse_product(result.data["product"])

        # Fall back to HTML scraping
        logger.info(f"  JSON endpoint unavailable, trying HTML for {handle}")
        return self._scrape_product_html(handle)

    def scrape_products(self, handles: list[str], plant_ids: list[str] = None) -> list[dict]:
        """Scrape multiple products by handle. Returns list of result dicts.

        Args:
            handles: List of Shopify product handles to scrape.
            plant_ids: Optional parallel list of plant IDs for recovery tracking.
        """
        results = []
        for i, handle in enumerate(handles):
            pid = plant_ids[i] if plant_ids else None
            logger.info(f"  [{i+1}/{len(handles)}] {self.retailer_id}: {handle}")
            result = self.scrape_product(handle, plant_id=pid)
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

            result = self._get_json(url)
            if not result.data or "products" not in result.data:
                break

            products = result.data["products"]
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
# per retailer. Loaded from data/handle_maps.json at runtime.
# ---------------------------------------------------------------------------

_HANDLE_MAPS_PATH = Path(__file__).parent.parent / "data" / "handle_maps.json"
_handle_maps_cache: dict | None = None


def load_handle_maps() -> dict[str, dict[str, str]]:
    """Load handle maps from data/handle_maps.json. Cached after first call."""
    global _handle_maps_cache
    if _handle_maps_cache is None:
        with open(_HANDLE_MAPS_PATH, encoding="utf-8") as f:
            _handle_maps_cache = json.load(f)
    return _handle_maps_cache


def get_handles_for_retailer(retailer_id: str, plant_ids: list[str]) -> dict[str, str]:
    """Get the Shopify handle mapping for a retailer.

    Returns dict of {plant_id: shopify_handle} for plants this retailer carries.
    """
    mapping = load_handle_maps().get(retailer_id, {})
    return {pid: mapping[pid] for pid in plant_ids if pid in mapping}


def save_handle_map_entry(retailer_id: str, plant_id: str, new_handle: str) -> None:
    """Write a single handle update to data/handle_maps.json.

    Creates the retailer key if it doesn't exist. Invalidates the
    in-memory cache so the next load_handle_maps() reads fresh data.
    """
    global _handle_maps_cache
    with open(_HANDLE_MAPS_PATH, encoding="utf-8") as f:
        maps = json.load(f)
    if retailer_id not in maps:
        maps[retailer_id] = {}
    maps[retailer_id][plant_id] = new_handle
    with open(_HANDLE_MAPS_PATH, "w", encoding="utf-8") as f:
        json.dump(maps, f, indent=2, ensure_ascii=False)
    _handle_maps_cache = None
    logger.info(f"Handle map updated: {retailer_id}/{plant_id} -> {new_handle}")
