"""
Shopify Product Scraper

Most online nurseries use Shopify, which exposes structured JSON endpoints:
  - /products/{handle}.json — single product with variants and prices.
    NOTE: .json does NOT carry stock. It has no `available` key at all.
    Per-variant availability comes from /products/{handle}.js, fetched
    separately by fetch_availability(). See that method for why.
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

# schema.org Product/Offer blocks embedded in the product page HTML.
# sku, price, availability — pack SKUs carry a "-10PACK"-style suffix.
# `[^{}]*?` rather than `.*?` so a match cannot run past the end of its own
# Offer object. With `.*?` an Offer that omits `availability` silently
# inherited the NEXT Offer's, so a buyable price could be marked sold out and
# vanish from the site — the same "value inferred instead of read" defect this
# module has already been bitten by twice, in the availability dimension.
_SCHEMA_OFFER_RE = re.compile(
    r'\{"@type":"Offer","sku":"(\d+(?:-\w+)?)"[^{}]*?'
    r'"price":"([\d.]+)"[^{}]*?'
    r'"availability":"([^"]+)"'
)


# schema.org availability values a shopper can actually place an order
# against. Testing `"InStock" in value` alone marked PreOrder, BackOrder and
# LimitedAvailability as sold out, which would hide a buyable price. FGT emits
# only InStock/OutOfStock today, so this is cover for the day it does not.
_ORDERABLE_AVAILABILITY = ("InStock", "PreOrder", "BackOrder", "LimitedAvailability")


def _is_orderable(availability: str) -> bool:
    """True when the schema.org availability value means "you can buy this"."""
    return any(v in availability for v in _ORDERABLE_AVAILABILITY)


# Values that positively mean "cannot be bought". Deliberately an ALLOWLIST,
# and deliberately NOT `not _is_orderable(...)`.
#
# The two predicates drive opposite decisions and so need opposite defaults.
# _is_orderable gates whether to SHOW a price: an unknown value falling to
# False merely hides something, which is conservative. The sold-out branch
# below decides whether to PUBLISH A ROW AND DOWNGRADE THE DRIFT ALARM, so an
# unknown value falling into "sold out" both invents a fact and silences the
# warning. Review measured exactly that: OnlineOnly, PreSale and MadeToOrder
# are all orderable states and all three published a sold-out row. PreSale is
# the one that matters here — a nursery's spring pre-sale is precisely it.
#
# Anything not on this list is UNKNOWN, and unknown must withhold.
_DEFINITELY_UNAVAILABLE = ("outofstock", "soldout", "discontinued", "instoreonly")


def _is_definitely_unavailable(availability: str) -> bool:
    """True only for values positively stating the item cannot be bought."""
    normalized = re.sub(r"[^a-z]", "", (availability or "").lower())
    return bool(normalized) and any(v in normalized for v in _DEFINITELY_UNAVAILABLE)


def _offers_from_ld_json(text: str) -> list[dict]:
    """Offer objects parsed with a real JSON parser, not a regex.

    _SCHEMA_OFFER_RE serves the price path and is documented there as unable
    to be trusted across Offer boundaries. Review found three ways it misreads
    AVAILABILITY specifically: an Offer emitting `availability` before
    `price`, an Offer omitting `availability` and inheriting the next one's,
    and a non-numeric SKU that makes the Offer invisible. Each produced a
    sold-out row while a buyable price sat on the page. It is also 0-for-172
    on real FGT Offers, which nest price inside priceSpecification.

    Returns [] when nothing parses; the caller treats that as "cannot decide"
    and withholds, which is the safe direction.
    """
    found = []
    for match in re.finditer(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        text, re.DOTALL | re.IGNORECASE,
    ):
        try:
            blob = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue

        def walk(node):
            if isinstance(node, dict):
                if str(node.get("@type", "")).endswith("Offer"):
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(blob)
    return found


def _record_size(
    sizes: dict,
    quarantined: set,
    tier: str,
    entry: dict,
    *,
    retailer_id: str,
    handle: str,
    collisions: list,
) -> None:
    """Write one size tier, refusing to silently overwrite a different product.

    A plain `sizes[tier] = {...}` is last-write-wins, and that is how the live
    site came to advertise planting-tree's SOLD-OUT "2 Quart" at $13.95 in the
    `quart` column while the retailer was actively selling "1 Quart" at
    $21.95: both titles normalised to `quart`, the later variant overwrote the
    earlier one, and the price a visitor could actually pay was never
    published at all. _normalize_size now separates those products, so what
    reaches this function is a RESIDUAL collision — something the tier rules
    cannot tell apart — and it must be loud rather than resolved by list order.

    Three outcomes:

    * no clash                        -> write it
    * same price AND same stock       -> the same product listed twice
                                         (measured: FGT renders a duplicate
                                         "1 quart" button on 2 of 65 cached
                                         pages). Dropped silently; there is
                                         no disagreement to report.
    * anything else                   -> QUARANTINE. The tier is removed and
                                         poisoned so no later variant can
                                         claim it, and the clash is logged at
                                         ERROR with both raw labels.

    Quarantine is per-TIER, deliberately, not per-product and not an
    exception. Raising would have withheld whole products for the residual
    cases actually present in the cached corpus — three FGT pages carry two
    buttons with the SAME label and different prices ("1 quart" $25.95 and
    "1 quart" $44.95 on dwarf-cavendish-banana), which no normaliser can
    split — so a raise would delete live, mostly-correct products from the
    site to punish one unattributable cell. That would be a fresh defect of
    the class this change exists to remove. Dropping only the cell we cannot
    attribute keeps every other tier of the product publishing, which is the
    same trade this module already makes for a product whose sizes it cannot
    read: a missing cell is visible, a wrong price is not.
    """
    if tier in quarantined:
        collisions.append((tier, entry.get("raw_size"), entry.get("price")))
        return
    held = sizes.get(tier)
    if held is None:
        sizes[tier] = entry
        return
    if (held.get("price"), held.get("available")) == (entry.get("price"), entry.get("available")):
        return
    del sizes[tier]
    quarantined.add(tier)
    collisions.append((tier, entry.get("raw_size"), entry.get("price")))
    logger.error(
        f"  {retailer_id}/{handle}: size tier {tier!r} claimed by two different "
        f"products — {held.get('raw_size')!r} at {held.get('price')} and "
        f"{entry.get('raw_size')!r} at {entry.get('price')}. Publishing NEITHER: "
        f"an arbitrary winner here is how a sold-out variant's price came to be "
        f"advertised under another variant's label."
    )


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
                return self._parse_product(
                    follow_result.data["product"],
                    self.fetch_availability(new_handle or handle),
                )
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
            return self._parse_product(
                result.data["product"], self.fetch_availability(handle)
            )

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

    def fetch_availability(self, handle: str) -> dict:
        """Per-variant stock, keyed by variant id: {variant_id: bool}.

        WHY THIS EXISTS. The scraper reads /products/{handle}.json, and that
        endpoint HAS NO `available` FIELD. `variant.get("available")` therefore
        returned None for every variant of every Shopify retailer, on every run,
        since this scraper was written — 170 rows in the current corpus. The
        module docstring claimed .json carried availability, which is why nobody
        checked.

        /products/{handle}.js does carry it, per variant, and it matches what a
        shopper sees: verified against plantingtree.com's own size selector,
        which lists exactly the variants this field reports as available.

        Deliberately a SEPARATE fetch rather than switching endpoints. The .js
        payload returns price in CENTS (3495) where .json returns dollar strings
        ("34.95"); swapping wholesale would multiply every price on the site by
        100. Only the boolean is taken from here.

        Returns {} on any failure, which reproduces today's behaviour
        (availability unknown) rather than asserting stock we cannot confirm.
        """
        # This is a SECOND request to the same host for the same product, so it
        # gets its own delay. Without one, every product became a back-to-back
        # pair — 213 extra un-delayed requests per run, 426 a day — which
        # contradicts the project's own stated rule of 5-15s between requests
        # and is exactly the behaviour that gets a scraper blocked.
        self._delay()
        url = f"{self.base_url}/products/{handle}.js"
        result = self._get_json(url)
        data = result.data
        if not isinstance(data, dict):
            return {}
        out = {}
        for variant in data.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            vid = variant.get("id")
            avail = variant.get("available")
            # Only a real boolean counts. A missing key means unknown, and
            # unknown must never be coerced to True.
            if vid is not None and isinstance(avail, bool):
                out[str(vid)] = avail
        return out

    def _parse_product(self, product: dict, availability: dict | None = None) -> dict:
        """Parse a Shopify product JSON into our canonical format."""
        title = product.get("title", "")
        handle = product.get("handle", "")
        variants = product.get("variants", [])

        # Extract prices by size variant
        sizes = {}
        quarantined_tiers: set[str] = set()
        collisions: list = []

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

            # Real per-variant stock, fetched from /products/{handle}.js because
            # the .json endpoint this product came from has no `available` field.
            if availability:
                looked_up = availability.get(str(variant.get("id", "")))
                if isinstance(looked_up, bool):
                    available = looked_up

            # REMOVED: a heuristic that set `available = True` whenever the
            # variant title matched "ships in spring/fall/summer/winter".
            # It fabricated stock. Spring Hill's Pink Lemonade Blueberry had
            # every variant sold out at the retailer and rendered "In Stock"
            # here, carrying the green best-price highlight, because the title
            # contained the word "Spring". Measured: spring-hill asserted
            # availability and was wrong 48 times out of 52.
            #
            # "Ships in Spring" describes WHEN an order ships, not WHETHER one
            # can be placed. Those are different questions and only the
            # retailer can answer the second. It is now answered by the `.js`
            # lookup above, or left unknown.

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

            variant_id = variant.get("id", "")
            _record_size(
                sizes, quarantined_tiers, size_tier,
                {
                    "price": price,
                    "was_price": was_price,
                    "available": available,
                    "raw_size": variant_title,
                    "variant_id": variant_id,
                },
                retailer_id=self.retailer_id, handle=handle, collisions=collisions,
            )

        # Product URL — use variant ID of the first/cheapest size for deep linking
        product_url = f"{self.base_url}/products/{handle}"
        if sizes:
            # Find cheapest available variant for the default link
            cheapest = min(sizes.values(), key=lambda x: x["price"])
            if cheapest.get("variant_id"):
                product_url = f"{self.base_url}/products/{handle}?variant={cheapest['variant_id']}"

        # Aggregate stock from the tiers that SURVIVED quarantine, not from the
        # variants as they were read. Computing it inside the loop above let a
        # variant vote "in stock" and then be withheld by _record_size, so a row
        # could render "In Stock" over the price of a different, sold-out tier —
        # a claim backed by nothing published on the page. Same rule as the aria
        # path (known-in-stock wins; all-unknown stays unknown rather than being
        # reported sold out) because it is the same question.
        # Nature Hills returns null for both in-stock AND sold-out products, so
        # "no explicit value anywhere" must stay None and show a dash.
        explicit = [
            v["available"] for v in sizes.values() if isinstance(v.get("available"), bool)
        ]
        any_available = True if any(explicit) else (False if explicit else None)

        result = {
            "retailer_id": self.retailer_id,
            "retailer_name": self.retailer_id.replace("-", " ").title(),
            "handle": handle,
            "title": title,
            "url": product_url,
            "sizes": sizes,
            "in_stock": any_available,
            # Count of tiers withheld because two products claimed them. Kept
            # on the result so a test can assert the guard fired; runner.py is
            # untouched and ignores unknown keys.
            "size_collisions": len(collisions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Quarantine opened a NEW way to reach defect F1: every tier withheld
        # leaves an empty, freshly-timestamped row, which runner.py counts as a
        # product found and scores as healthy — a retailer publishing not one
        # readable price reporting a 100% hit rate. The aria path already
        # refuses to publish in this state; the JSON path keeps the row (the
        # product does exist) but must not let it pass for a successful price
        # read. Gated on `collisions` so a genuinely priceless product — no
        # variants, all zero-price, all filtered as packs — is untouched: that
        # is a different fact and already has its own handling.
        if not sizes and collisions:
            result["no_sizes_readable"] = True
        return result

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
        # They are the most reliable source — directly from the rendered page, with
        # the size name and its price in the SAME string, so there is no guessing
        # about which price belongs to which size. Schema.org Offers are a fallback
        # ONLY when no aria-labels are found.
        aria_offers = self._extract_aria_size_offers(text)

        # Use aria-labels if we got ANY valid size-named results
        if aria_offers:
            # Availability comes from the page's own schema.org Offers, matched by
            # price. The size buttons carry no stock state, and the old code simply
            # hardcoded available=True for every size it found.
            avail_by_price = self._availability_by_price(text)
            sizes = {}
            quarantined_tiers: set[str] = set()
            collisions: list = []
            for size_name, sale_price, list_price in aria_offers:
                if sale_price <= 0:
                    continue  # a 0 is "no price", never a free plant
                tier = self._normalize_size(size_name)
                available = avail_by_price.get(round(sale_price, 2))
                if available is None and not avail_by_price:
                    # No schema.org stock data on the page at all — no signal either
                    # way, so keep the historical assumption that a priced, rendered
                    # size button is buyable.
                    available = True
                # REPLACED: "keep the first (buttons render smallest-first)".
                # Keeping the first is still picking a winner between two
                # products, and the assumption underneath it is false — on the
                # cached crape-myrtle page the first `quart` button is
                # "1 quart Multi-stem" and the second is "2 quart Multi-stem",
                # a bigger pot, so "first" meant "publish the small pot's price
                # under a tier the big pot also claims". _normalize_size now
                # tells those two apart; what still lands here is a clash no
                # tier rule can resolve, and it is withheld, not guessed.
                _record_size(
                    sizes, quarantined_tiers, tier,
                    {
                        "price": sale_price,
                        "was_price": list_price if list_price and list_price > sale_price else None,
                        "available": available,
                        "raw_size": size_name,
                    },
                    retailer_id=self.retailer_id, handle=handle, collisions=collisions,
                )
            # Aggregate, same rule as the JSON path: known-in-stock wins; all-unknown
            # stays unknown rather than being reported as sold out.
            explicit = [v["available"] for v in sizes.values() if isinstance(v["available"], bool)]
            any_available = True if any(explicit) else (False if explicit else None)
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
                    "size_collisions": len(collisions),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            # The page HAD readable size buttons and every one of them was
            # quarantined. Do NOT fall through: everything below pairs sizes
            # to prices BY POSITION, and answering "we could not tell two
            # products apart" with a positional guess is strictly worse than
            # answering nothing. Withhold the product — a gap is visible in
            # products_error, a wrong price is not.
            logger.error(
                f"  {self.retailer_id}/{handle}: all {len(aria_offers)} size buttons "
                f"were withheld as unattributable — publishing nothing for this product"
            )
            return None

        # Everything below this point pairs size labels to prices BY POSITION,
        # assuming buttons run smallest→largest and prices cheapest→dearest.
        # Measured against 12 live pages that assumption yields 26/37 correct
        # pairs, where reading the name and price out of the SAME aria-label
        # yields 37/37. It is how "1 gallon" came to wear the 4-inch price.
        #
        # It is unreachable while the aria-labels parse. The danger is drift:
        # FGT's label format has already changed once, and when it changes
        # again this code silently resumes publishing wrong prices. Nothing
        # would notice — runner.py scores health as
        # products_found / products_expected, so a wrong-but-present product
        # still counts as a hit and the manifest stays "healthy".
        #
        # So when a page offers more than one size but we could not read a
        # single one of them, publish nothing. A missing product trips the
        # dead-retailer alarm; a wrong price trips nothing at all. Genuinely
        # single-size products are unaffected and still publish normally.
        #
        # "More than one size" is decided from the schema.org Offer COUNT, not
        # from finding a "Select size" heading. The first version of this
        # guard keyed on that heading, so it switched itself off whenever the
        # heading changed — an <h3> instead of an <h2>, an inner <span>, or
        # the words "Select a size" — and then published the Jumbo's $503.95
        # on the standard 6-7ft row, the exact defect it exists to prevent. A
        # theme redesign changes the heading and the aria format together, so
        # that is precisely when the guard was least likely to be watching.
        #
        # The Offer count comes from the page's own structured data and does
        # not depend on presentational markup. The heading check is kept as a
        # second, independent trigger rather than the only one.
        multi_size_product = len(offers) > 1 or bool(self._size_selector_scope(text))
        if not aria_offers and multi_size_product:
            # One legitimate page state also looks exactly like drift: a
            # product whose EVERY size is sold out. FGT removes the size
            # selector entirely then, so there are schema Offers but zero
            # readable sizes. Measured live on /products/russian-sage:
            # HTTP 200, 6 Offers, all OutOfStock, no selector rendered —
            # and 11 of 13 "failed" FGT products in the 2026-08-12 run were
            # this, not drift. Withholding them threw away a true fact (the
            # product exists and is sold out) and permanently pinned FGT
            # below the 80% health threshold, which is recurring alarm
            # noise — the thing that gets alert channels ignored.
            #
            # The distinction is decidable from the page's own data: ALL
            # Offers non-orderable -> genuinely sold out, publish an empty
            # sold-out row. ANY Offer orderable but unreadable -> that is
            # drift, a price exists that we cannot attribute, withhold.
            # No sizes are fabricated from Offer SKUs — that was the
            # phantom-row generator this module already removed once.
            # Decide from a REAL JSON parse of the ld+json block. `offers`
            # comes from _SCHEMA_OFFER_RE, which this module already documents
            # as untrustworthy across Offer boundaries; review showed three
            # ways it misreads availability, each producing a sold-out row
            # while a buyable price sat on the page.
            ld_offers = [
                o for o in _offers_from_ld_json(text)
                if "pack" not in str(o.get("sku", "")).lower()
            ]
            availabilities = [str(o.get("availability", "")) for o in ld_offers]
            # EVERY offer must positively say unavailable. No offers parsed,
            # or any value we do not recognise, means we cannot decide — and
            # "cannot decide" is drift, which withholds and alarms.
            all_gone = bool(availabilities) and all(
                _is_definitely_unavailable(a) for a in availabilities
            )
            if all_gone:
                logger.info(
                    f"  {self.retailer_id}/{handle}: every size sold out "
                    f"({len(ld_offers)} offers, none orderable) — recording as "
                    f"out of stock rather than withholding"
                )
                title_match = re.search(r"<title>([^<]+)</title>", text)
                title = (
                    title_match.group(1).split("|")[0].strip()
                    if title_match else handle.replace("-", " ").title()
                )
                return {
                    "retailer_id": self.retailer_id,
                    "retailer_name": self.retailer_id.replace("-", " ").title(),
                    "handle": handle,
                    "title": title,
                    "url": url,
                    "sizes": {},
                    "in_stock": False,
                    # The drift alarm and the sold-out fact are NOT mutually
                    # exclusive, and the first version of this branch treated
                    # them as if they were. A page can be drifted AND fully
                    # sold out; publishing the row then silenced the alarm.
                    # Review measured the result: a retailer with not one
                    # readable price on any of 68 pages reported
                    # pipeline_status "healthy" at a 100% hit rate, because
                    # empty rows count as products_found and the row carries a
                    # fresh timestamp. This flag lets runner.py keep counting
                    # the fact separately from a successful price read.
                    "no_sizes_readable": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            logger.error(
                f"  {self.retailer_id}/{handle}: page offers {len(offers)} sizes but not "
                f"one could be read. The aria-label format has probably changed. "
                f"REFUSING to fall back to positional size↔price pairing — that is how "
                f"sizes came to wear their neighbour's price. Publishing nothing for "
                f"this product so the gap is visible."
            )
            return None

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
                    if float(price_str) <= 0:
                        continue  # a 0 is "no price", never a free plant
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

    # aria-label formats used by fastgrowingtrees.com's size selector.
    # Verified 2026-08-11 against 10 live product pages (fgt_ground_truth.json):
    #   "1 gallon - Price $45.95"
    #   "2-3 feet - Price $57.95 - Buy 1, Get 1"
    #   "1 quart - Original price $35.95, sale price $30.95 - 14% OFF"
    #   "6-7 feet Jumbo - Original price $766.95, sale price $503.95 - 34% OFF"
    # plus the older theme this scraper was originally written against:
    #   "1 Gallon - Sale price: 39.99 - List price: $49.99"
    # Order matters: the "sale price:/list price:" form must be tried before the
    # bare "- Price $" form.
    _ARIA_LABEL_PATTERNS = (
        re.compile(
            r'^(?P<name>.+?)\s*-\s*original\s+price\s*\$?(?P<was>[\d,]+(?:\.\d+)?)\s*,\s*'
            r'sale\s+price\s*\$?(?P<price>[\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
        re.compile(
            r'^(?P<name>.+?)\s*-\s*sale\s+price:\s*\$?(?P<price>[\d,]+(?:\.\d+)?)\s*-\s*'
            r'list\s+price:\s*\$?(?P<was>[\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
        re.compile(
            r'^(?P<name>.+?)\s*-\s*price:?\s*\$(?P<price>[\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
    )

    @staticmethod
    def _to_price(raw: str) -> float | None:
        """'1,318.00' -> 1318.0. Returns None if it isn't a number."""
        try:
            return float(raw.replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _is_quantity_label(name: str) -> bool:
        """True for buttons that pick a QUANTITY, not a size.

        FGT renders two button groups: "Select size" (4 inch / 1 quart / 1 gallon)
        and "Select quantity" (Single / 10-Pack). Both use the same aria-label
        price format, and a pack price is not a per-plant price.

        "Single-stem" is a FORM, not a quantity. Matching bare "single" threw
        away every Single-stem size button FGT renders — on crape-myrtle that
        left only the Multi-stem prices, published under the plain height
        tiers, so the site quoted a multi-stem price for a plant a visitor
        would receive as a single-stem tree. Verified against the cached page
        scratchpad/fgt_cm.html, which lists "1-2 feet Multi-stem" and
        "1-2 feet Single-stem" side by side at different prices.
        """
        nl = name.strip().lower()
        return (
            "pack" in nl
            # "6 Plants ( 4 Inch Pot)" is a six-plant bundle, and it was
            # claiming the `4inch` size tier next to the real "4 inch" button
            # at a third of the price. The JSON path has filtered exactly this
            # for as long as it has existed — same count guard, so "1 Plant(s)"
            # (a single plant, which Spring Hill writes on every variant) is
            # still a size, not a pack.
            or bool(re.search(r'(?:[2-9]|1\d)[\s-]*plants?\b', nl))
            or ("single" in nl and not re.search(r'\bsingle[\s-]?stems?\b', nl))
            or bool(re.match(r'^\d+[\s-]*(?:pk|ct|x)$', nl))
        )

    @staticmethod
    def _size_selector_scope(text: str) -> str | None:
        """Return only the markup of the 'Select size' section, or None.

        Scoping matters: the "Select quantity" section that follows uses the same
        aria-label format, so an unscoped scan mixes pack prices in with sizes.
        """
        m = re.search(r'select\s+size\s*</h2>', text, re.IGNORECASE)
        if not m:
            return None
        end = text.find("</section>", m.end())
        return text[m.end():end if end != -1 else len(text)]

    def _extract_aria_size_offers(self, text: str) -> list[tuple[str, float, float | None]]:
        """Size buttons as (label, price, was_price), read from aria-labels.

        This is the FGT primary path. Each aria-label pairs a size name with its
        own price inside one string, e.g. "1 gallon - Price $45.95", so the size
        and the price cannot drift apart. Nothing here is positional.
        """
        scope = self._size_selector_scope(text)
        found: list[tuple[str, float, float | None]] = []
        for source in (scope, text):
            if source is None:
                continue
            for label in re.findall(r'aria-label="([^"]+)"', source):
                for pattern in self._ARIA_LABEL_PATTERNS:
                    m = pattern.match(label.strip())
                    if not m:
                        continue
                    name = m.group("name").strip()
                    price = self._to_price(m.group("price"))
                    was = self._to_price(m.groupdict().get("was") or "")
                    if price is None or not name or self._is_quantity_label(name):
                        break
                    found.append((name, price, was))
                    break
            if found:
                # The scoped pass found real sizes; never fall through to the
                # whole document, which would pull in quantity/pack buttons.
                break
        return found

    def _availability_by_price(self, text: str) -> dict[float, bool | None]:
        """Per-price stock from the page's schema.org Offers: {price: in_stock}.

        The size buttons themselves carry no stock state, but the page's
        schema.org Product block lists every variant with an `availability` field.
        On all 10 FGT pages checked, each visible size price matched exactly one
        non-pack Offer. Prices shared by two Offers that disagree map to None
        (unknown) rather than to a guess.
        """
        buckets: dict[float, set[bool]] = {}
        for sku, price_str, availability in _SCHEMA_OFFER_RE.findall(text):
            if "pack" in sku.lower():
                continue  # multi-plant bundle, not a single-plant price
            price = self._to_price(price_str)
            if price is None:
                continue
            buckets.setdefault(round(price, 2), set()).add(_is_orderable(availability))
        return {
            price: (next(iter(vals)) if len(vals) == 1 else None)
            for price, vals in buckets.items()
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

        A tier is a claim that two rows are the SAME PRODUCT at the SAME SIZE.
        When it is not, the tier write downstream is last-write-wins and one
        product's price is published under another product's label. Measured
        live on planting-tree's Nellie Stevens Holly: "1 Quart" ($21.95, in
        stock) and "2 Quart" ($13.95, sold out) both mapped to `quart`, so the
        site advertised the sold-out $13.95 and never published the price a
        visitor could actually pay. Splitting genuinely different products
        into different tiers is what makes the collision guard in
        _record_size() a rare alarm instead of a daily one.
        """
        return self._apply_form_suffix(
            self._normalize_size_base(variant_title), variant_title.lower()
        )

    # Form qualifiers that name a DIFFERENT PRODUCT at the same nominal size,
    # the same way "6-7 feet Jumbo" does (see the -jumbo suffix below). FGT
    # lists "4-5 feet Multi-stem" and "4-5 feet Single-stem" on ONE page at
    # different prices, and both normalised to `4-5ft`. Single-stem is the
    # ordinary form — it keeps the plain tier so it still compares against
    # every other retailer's plain "4-5 Feet" — and only multi-stem moves to
    # its own column.
    _MULTISTEM_RE = re.compile(r'\bmulti[\s-]?stems?\b')

    @classmethod
    def _apply_form_suffix(cls, tier: str, title_lower: str) -> str:
        if tier and not tier.endswith("-multistem") and cls._MULTISTEM_RE.search(title_lower):
            return tier + "-multistem"
        return tier

    @staticmethod
    def _bareroot_tier(title_lower: str) -> str:
        """Tier for a bare-root/dormant variant, keeping any real dimension.

        Spring Hill sells 'DORMANT 2.5" POT' and 'DORMANT 48-54"' of different
        plants under labels that all collapsed onto one `bareroot` tier — a
        two-and-a-half-inch pot and a four-foot plant sharing a column and a
        "Bare Root" label. A stated dimension is the size; dropping it is the
        collision.
        """
        span = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:"|in\b|inch(?:es)?\b)', title_lower)
        if span:
            return f'{span.group(1)}-{span.group(2)}in-bareroot'
        single = re.search(r'(\d+(?:\.\d+)?)\s*(?:"|inch(?:es)?\b)', title_lower)
        if single:
            # '.' -> '-' follows the existing tier-key convention: PWD's
            # "0.65 Gallon" is already carried as `0-65-gallon`.
            return f'{single.group(1).replace(".", "-")}inch-bareroot'
        return 'bareroot'

    def _normalize_size_base(self, variant_title: str) -> str:
        """The size tier before form qualifiers are applied. See _normalize_size."""
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
        # Remove a promotional prefix. "Flash Sale - 1-2 feet" is the same
        # product as "1-2 feet"; a sale is a state of the offer, not a size,
        # exactly like the "Ships in Spring" strip above. Left in, it survives
        # into raw_size and into the Step 9 unrecognised-tier fallback.
        title_lower = re.sub(r'^\s*flash\s+sale\s*[-–—:]\s*', '', title_lower)
        title_lower = title_lower.strip().strip('/').strip()

        # Step 2a: quantity-bearing quart sizes. "2 Quart" and "3 Quart" are
        # BIGGER POTS, not other spellings of "quart" — planting-tree lists
        # 1/2/3 Quart of the same plant at different prices and stock. "1
        # Quart" keeps the plain `quart` tier because it IS a quart: splitting
        # it off would strand Nature Hills' "Quart Container" and GGP's "One
        # Quart" in a different column and lose a comparison the site has today.
        multi_quart = re.search(r'\b([2-9])\s*-?\s*quarts?\b', title_lower)
        if multi_quart:
            return f'{multi_quart.group(1)}quart'

        # Step 2: Container/gallon patterns (most universal — check first)
        gallon_patterns = [
            # Explicit gallon — gal / gallon / gallons (all plural forms)
            (r'\b1[\s-]?gal(?:l*on)?s?\b', '1gal'),
            (r'one\s+gallon', '1gal'),
            (r'#1\s*container', '1gal'),
            (r'trade\s+gallon', '1gal'),
            (r'\b2[\s-]?gal(?:l*on)?s?\b', '2gal'),
            (r'#2\s*container', '2gal'),
            (r'\b3[\s-]?gal(?:l*on)?s?\b', '3gal'),
            # DELETED: (r'3\s*gallon\s*pot', '3gal'). Unreachable dead code —
            # every string it matches contains "3 gallon", which the entry
            # above already matches, to the same tier. Removing it cannot
            # change any output; proved exhaustively over all 1,4xx distinct
            # raw_size values in data/prices/ in test_shopify_sizes.py.
            (r'#3\s*container', '3gal'),
            (r'\b5[\s-]?gal(?:l*on)?s?\b', '5gal'),
            (r'#5\s*container', '5gal'),
            (r'\b7[\s-]?gal(?:l*on)?s?\b', '7gal'),
            (r'#7\s*container', '7gal'),
            (r'\b10[\s-]?gal(?:l*on)?s?\b', '10gal'),
            (r'\b15[\s-]?gal(?:l*on)?s?\b', '15gal'),
            # Quart. Bare "Quart", "1 Quart", "One Quart" and "Quart
            # Container" are all one quart and share this tier; 2/3 Quart were
            # split off in Step 2a above.
            (r'\bquart\b', 'quart'),
            (r'\bqt\b', 'quart'),
            # DELETED: (r'one\s+quart', 'quart'). Unreachable dead code — the
            # \bquart\b entry above matches "one quart" first, to the same
            # tier. Same exhaustive proof as the 3-gallon-pot entry.
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
            return self._bareroot_tier(title_lower)
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
            tier = f"{low}-{high}ft"
            # "6-7 feet Jumbo" is a different, pricier product than "6-7 feet" —
            # FGT sells both on thuja-green-giant. Without this suffix they
            # collapse onto one tier and the 6-7ft row carried the Jumbo price
            # ($503.95) instead of the real 6-7 feet price ($372.95).
            if re.search(r'\bjumbo\b', title_lower):
                tier += "-jumbo"
            return tier

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
        # Checked AFTER jumbo/premium so "JUMBO BAREROOT" keeps its own tier.
        if re.search(r'bare[\s-]?root', title_lower):
            return self._bareroot_tier(title_lower)

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
