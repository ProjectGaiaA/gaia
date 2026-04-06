"""
Stark Bros Product Scraper

Stark Bros runs Apache Wicket (custom Java), NOT Shopify.
Product data is in window.dataLayer.push() JavaScript objects.
robots.txt specifies Crawl-delay: 5 — we respect this.

Usage:
    from scrapers.starkbros import StarkBrosScraper
    scraper = StarkBrosScraper()
    result = scraper.scrape_product("honeycrisp-apple", "fruit-trees/apple-trees")
"""

import json
import logging
import re
from datetime import datetime, timezone

import requests

from scrapers.polite import (
    polite_delay,
    log_request, is_allowed_by_robots, make_polite_session,
)

logger = logging.getLogger(__name__)


class StarkBrosScraper:
    """Scrape product data from Stark Bros (starkbros.com)."""

    BASE_URL = "https://www.starkbros.com"
    RETAILER_ID = "stark-bros"
    # Respect robots.txt Crawl-delay: 5, but we use 6-15s to be extra polite
    MIN_DELAY = 6
    MAX_DELAY = 15

    def __init__(self):
        self.session = make_polite_session()

    def _delay(self):
        return polite_delay(self.MIN_DELAY, self.MAX_DELAY)

    def scrape_product(self, slug: str, category_path: str) -> dict | None:
        """Scrape a single Stark Bros product.

        Args:
            slug: Product URL slug (e.g., "honeycrisp-apple")
            category_path: Category path (e.g., "fruit-trees/apple-trees")

        Returns:
            Structured dict with price data, or None on failure.
        """
        url = f"{self.BASE_URL}/products/{category_path}/{slug}"

        if not is_allowed_by_robots(url):
            return None
        try:
            resp = self.session.get(url, timeout=20)
            log_request(url, status_code=resp.status_code)
            if resp.status_code == 404:
                logger.info(f"Product not found: {url}")
                return None
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

        text = resp.text

        # Extract from dataLayer (primary method — cleanest data)
        sizes = {}
        product_name = slug.replace("-", " ").title()
        any_available = False

        datalayer_match = re.search(
            r'dataLayer\.push\((\{"productFamilyList".*?\})\);',
            text, re.DOTALL
        )

        if datalayer_match:
            try:
                data = json.loads(datalayer_match.group(1))
                family_list = data.get("productFamilyList", [])
                if family_list:
                    family = family_list[0]
                    product_name = family.get("productFamily", {}).get(
                        "nameWithCategoryType",
                        family.get("productFamily", {}).get("name", product_name)
                    )

                    for product in family.get("availableProducts", []):
                        desc = product.get("productDescription", "")
                        price = product.get("price", 0)
                        if price <= 0:
                            continue

                        tier = self._normalize_variant(desc)
                        any_available = True

                        sizes[tier] = {
                            "price": price,
                            "was_price": None,
                            "available": True,
                            "raw_size": desc,
                        }

                    # Get regular prices from the family level
                    lowest_regular = family.get("lowestRegularPrice")
                    lowest_sale = family.get("lowestPrice")
                    if lowest_regular and lowest_sale and lowest_regular > lowest_sale:
                        # Find the matching size and set was_price
                        for tier_data in sizes.values():
                            if tier_data["price"] == lowest_sale:
                                tier_data["was_price"] = lowest_regular
                                break

            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning(f"Failed to parse dataLayer for {url}: {e}")

        # Fallback: try JSON-LD for at least aggregate pricing.
        # Stark Bros uses @type "Product" for product pages; some older pages use "ItemPage".
        if not sizes:
            for ld_type, ld_pattern in [
                ("ItemPage", r'<script type="application/ld\+json">\s*(\{.*?"@type"\s*:\s*"ItemPage".*?\})\s*</script>'),
                ("Product",  r'<script type="application/ld\+json">\s*(\{.*?"@type"\s*:\s*"Product".*?\})\s*</script>'),
            ]:
                ld_match = re.search(ld_pattern, text, re.DOTALL)
                if not ld_match:
                    continue
                try:
                    ld_data = json.loads(ld_match.group(1))
                    if ld_type == "ItemPage":
                        offers = ld_data.get("mainEntity", {}).get("offers", {})
                    else:
                        offers = ld_data.get("offers", {})
                    low_price = offers.get("lowPrice")
                    if low_price:
                        sizes["default"] = {
                            "price": float(low_price),
                            "was_price": None,
                            "available": "InStock" in offers.get("availability", ""),
                            "raw_size": "Best available",
                        }
                        any_available = "InStock" in offers.get("availability", "")
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

        if not sizes:
            return None

        return {
            "retailer_id": self.RETAILER_ID,
            "retailer_name": "Stark Bros",
            "handle": slug,
            "title": product_name,
            "url": url,
            "sizes": sizes,
            "in_stock": any_available,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def scrape_promo_codes(self) -> list[dict]:
        """Check Stark Bros homepage for promo codes or discount banners.

        Returns list of dicts like:
            [{"code": "SAVE20", "description": "...", "source": "text-pattern"}]
        """
        if not is_allowed_by_robots(self.BASE_URL):
            return []
        try:
            resp = self.session.get(self.BASE_URL, timeout=20)
            log_request(self.BASE_URL, status_code=resp.status_code)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Promo check failed for stark-bros: {e}")
            return []

        text = resp.text
        promos = []
        seen_codes = set()

        # Strip HTML and focus on top-of-page text (banner/announcement area)
        page_top = re.sub(r'<[^>]+>', ' ', text[:8000])
        page_top = re.sub(r'\s+', ' ', page_top)

        explicit_patterns = [
            r'(?:use|enter|apply)\s+(?:code\s+)?([A-Z][A-Z0-9]{2,19})\b',
            r'promo(?:\s+code)?[:\s]+([A-Z][A-Z0-9]{2,19})\b',
            r'coupon(?:\s+code)?[:\s]+([A-Z][A-Z0-9]{2,19})\b',
            r'code[:\s]+([A-Z][A-Z0-9]{2,19})\b',
        ]
        EXCLUDED = {'HTTP', 'HTML', 'FREE', 'SHIP', 'SALE', 'BEST', 'MORE', 'SHOP', 'VIEW'}
        for pat in explicit_patterns:
            for m in re.finditer(pat, page_top, re.IGNORECASE):
                code = m.group(1).upper()
                if code in seen_codes or len(code) < 3 or code in EXCLUDED:
                    continue
                start = max(0, m.start() - 20)
                end = min(len(page_top), m.end() + 60)
                description = page_top[start:end].strip()
                promos.append({"code": code, "description": description, "source": "text-pattern"})
                seen_codes.add(code)

        if promos:
            logger.info(f"  stark-bros: found {len(promos)} promo(s)")
        return promos

    def scrape_products(self, product_list: list[dict]) -> list[dict]:
        """Scrape multiple products.

        Args:
            product_list: List of {"plant_id": ..., "slug": ..., "category": ...}

        Returns:
            List of result dicts.
        """
        results = []
        for i, item in enumerate(product_list):
            logger.info(f"  [{i+1}/{len(product_list)}] stark-bros: {item['slug']}")
            result = self.scrape_product(item["slug"], item["category"])
            if result:
                results.append((item["plant_id"], result))
            else:
                logger.warning(f"    Failed: {item['slug']}")
            if i < len(product_list) - 1:
                self._delay()
        return results

    def _normalize_variant(self, desc: str) -> str:
        """Normalize Stark Bros variant descriptions to canonical tiers.

        Stark Bros uses compound descriptions like:
          "Honeycrisp Apple Dwarf" → "dwarf-bareroot"
          "Honeycrisp Apple Semi-Dwarf" → "semi-dwarf-bareroot"
          "Honeycrisp Apple Supreme Dwarf" → "supreme-dwarf-bareroot"
        """
        desc_lower = desc.lower()

        # Check for pot size first
        if "7 gal" in desc_lower or "potted" in desc_lower:
            if "semi-dwarf" in desc_lower or "semi dwarf" in desc_lower:
                return "semi-dwarf-potted"
            elif "dwarf" in desc_lower:
                return "dwarf-potted"
            return "potted"

        # Check for rootstock type
        is_bareroot = "bare" in desc_lower or "bare-root" in desc_lower
        is_ez_start = "ez start" in desc_lower or "ez-start" in desc_lower

        # Determine size tier
        if "ultra supreme" in desc_lower:
            base = "ultra-supreme"
        elif "supreme" in desc_lower:
            base = "supreme"
        elif "semi-dwarf" in desc_lower or "semi dwarf" in desc_lower:
            base = "semi-dwarf"
        elif "dwarf" in desc_lower:
            base = "dwarf"
        elif "standard" in desc_lower:
            base = "standard"
        else:
            # No recognizable size info — return default rather than the
            # full product name (which would create a bogus tier key like
            # "patriot-blueberry" instead of something meaningful)
            return 'default'

        if is_ez_start:
            return f"{base}-ez-start"
        elif is_bareroot:
            return f"{base}-bareroot"
        return base


# Product catalog mapping: plant_id → {slug, category}
STARK_BROS_PRODUCTS = {
    "honeycrisp-apple-tree": {"slug": "honeycrisp-apple", "category": "fruit-trees/apple-trees"},
    "bing-cherry-tree": {"slug": "bing-sweet-cherry", "category": "fruit-trees/cherry-trees"},
    "elberta-peach-tree": {"slug": "elberta-peach", "category": "fruit-trees/peach-trees"},
    "bartlett-pear-tree": {"slug": "bartlett-pear", "category": "fruit-trees/pear-trees"},
    # Stark Bros moved roses to garden-plants/ category (2026-04-03)
    "double-knock-out-rose": {"slug": "double-knock-out-rose", "category": "garden-plants/roses"},
    # "knock-out-rose" discontinued by Stark Bros — removed
    "duke-blueberry": {"slug": "duke-blueberry", "category": "berry-plants/blueberry-plants"},
    "patriot-blueberry": {"slug": "patriot-blueberry", "category": "berry-plants/blueberry-plants"},
    "pink-lemonade-blueberry": {"slug": "pink-lemonade-blueberry", "category": "berry-plants/blueberry-plants"},
}
