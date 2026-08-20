"""On the JSON path, the bundle check must run BEFORE the multi-plant filter.

`test_json_path_all_bundle_health_signal.py` closed the all-bundle hole for
titles like "5-6 FT - Buy 1, Get 1". It did not close it for titles that are a
bundle AND a pack, because the two filters ran in the wrong order:

    if re.search(r'(?:[2-9]|1\\d)[\\s-]*(?:plant|pack)', variant_title, ...):
        continue                      # <- multi-plant PACK filter, ran first
    if self._is_bundle_offer(variant_title):
        bundle_variants.append(variant_title)   # <- never reached
        continue

The pack filter's own comment cites "BOGO / 2 Plant(s)" as a string it
matches. Any such variant `continue`d before `bundle_variants` ever saw it, so
a product whose entire catalogue is BOGO-on-a-pack returned:

    sizes: {}   no_sizes_readable: <ABSENT>   all_offers_bundled: <ABSENT>

and runner.py's `products_priced = products_found - products_no_sizes` scored
it as a SUCCESSFUL PRICE READ — the exact guarantee the bundle signal exists
to make, defeated by ordering.

Swapping the two blocks is output-neutral by construction: a variant matching
both predicates is skipped either way, so `sizes` is unchanged in every case.
The tests below pin both halves — the signal that must now appear, and the
`sizes` that must not move. Two of them are neutrality controls that passed
before the reorder too; they are here to fail if a future "simplification"
makes the reorder change published prices.

All HTTP is mocked. No live retailer is reached.
"""

import responses

from scrapers.shopify import ShopifyScraper

SH = "https://www.springhillnursery.com"


def _variant(vid, title, price):
    return {"id": vid, "title": title, "price": price, "compare_at_price": None}


def _scrape(handle, variants, retailer="spring-hill"):
    responses.add(
        responses.GET, f"{SH}/products/{handle}.json",
        json={"product": {"id": 1, "title": "Limelight Hydrangea",
                          "handle": handle, "variants": variants}},
        status=200,
    )
    responses.add(responses.GET, f"{SH}/products/{handle}.js",
                  json={"variants": []}, status=200)
    return ShopifyScraper(retailer, SH).scrape_product(handle)


# Bundle AND pack. The exact string the pack filter's comment cites.
BOGO_ON_PACK = [
    _variant(1, "BOGO / 2 Plant(s)", "119.99"),
    _variant(2, "3-4 FT - BOGO / 2 Plant(s)", "199.99"),
]

# Pack only, no bundle marker anywhere. Must stay untouched: a product with
# nothing but multi-plant packs is priceless for a DIFFERENT reason, and that
# reason has its own handling.
PURE_PACK = [
    _variant(3, "3 Plant(s)", "59.99"),
    _variant(4, "10-Pack", "149.99"),
    _variant(5, "4-Pack", "79.99"),
]

# A readable single-plant size alongside a pack and a bundle.
MIXED = [
    _variant(6, "1 GALLON / 1 Plant(s)", "29.99"),
    _variant(7, "3 Plant(s)", "59.99"),
    _variant(8, "BOGO / 2 Plant(s)", "119.99"),
    _variant(9, "2 GALLON / 1 Plant(s)", "39.99"),
]


# --------------------------------------------------------------------------
# the defect: a bundle that is also a pack must still register as a bundle
# --------------------------------------------------------------------------

@responses.activate
def test_a_bogo_on_a_pack_product_is_not_counted_as_priced(no_sleep):
    """The headline. Every variant is BOGO-on-a-pack, so nothing publishes —
    and the row must say so, or the retailer scores a healthy hit rate while
    showing none of its prices."""
    result = _scrape("h", BOGO_ON_PACK)
    assert result is not None
    assert result["sizes"] == {}
    assert result.get("no_sizes_readable") is True, (
        "an all-BOGO-on-a-pack product published an empty row that runner.py "
        "counts as a successful price read")


@responses.activate
def test_a_bogo_on_a_pack_product_records_why_it_is_empty(no_sleep):
    """Provenance. Without it the history holds two empty rows of identical
    shape — 'every size sold out' and 'every size is a two-for-one' — and no
    reader can tell them apart."""
    result = _scrape("h", BOGO_ON_PACK)
    assert result.get("all_offers_bundled") is True, (
        "the empty row carries no reason, so it is indistinguishable from a "
        "sold-out product")


@responses.activate
def test_runner_accounting_scores_the_bogo_on_pack_row_as_unpriced(no_sleep):
    """The defect stated in runner.py's own arithmetic, which is where it
    actually bites: products_priced = products_found - products_no_sizes."""
    rows = [_scrape("h", BOGO_ON_PACK)]
    products_found = len(rows)
    products_no_sizes = sum(1 for r in rows if r.get("no_sizes_readable"))
    assert products_found - products_no_sizes == 0, (
        "a retailer showing not one readable price would report a 100% hit "
        "rate")


# --------------------------------------------------------------------------
# neutrality controls — these passed BEFORE the reorder and must keep passing
# --------------------------------------------------------------------------

@responses.activate
def test_a_pure_pack_product_is_still_left_alone(no_sleep):
    """Deliberate, defensible behaviour that the reorder must not disturb. A
    product sold only in multi-plant packs is priceless for a different
    reason than a bundle, and it does NOT get the bundle signal."""
    result = _scrape("h", PURE_PACK)
    assert result["sizes"] == {}
    assert result.get("all_offers_bundled") is None, (
        "a pure-pack product was mislabelled as a bundle offer")
    assert result.get("no_sizes_readable") is None, (
        "the reorder changed how a pure-pack product is reported")


@responses.activate
def test_sizes_are_byte_identical_for_a_normal_mixed_product(no_sleep):
    """The published prices must not move. A variant matching both filters is
    skipped either way; only the recorded reason differs."""
    result = _scrape("h", MIXED)
    assert sorted(result["sizes"]) == ["1gal", "2gal"]
    assert result["sizes"]["1gal"]["price"] == 29.99
    assert result["sizes"]["1gal"]["raw_size"] == "1 GALLON / 1 Plant(s)"
    assert result["sizes"]["2gal"]["price"] == 39.99
    assert result["sizes"]["2gal"]["raw_size"] == "2 GALLON / 1 Plant(s)"
    # Sizes were read, so neither empty-row signal belongs here.
    assert result.get("no_sizes_readable") is None
    assert result.get("all_offers_bundled") is None


@responses.activate
def test_a_bundle_that_is_not_a_pack_still_works(no_sleep):
    """The case the previous fix already covered. It must not regress."""
    result = _scrape("h", [_variant(20, "5-6 FT - Buy 1, Get 1", "199.99")])
    assert result["sizes"] == {}
    assert result.get("no_sizes_readable") is True
    assert result.get("all_offers_bundled") is True


# --------------------------------------------------------------------------
# the ordering itself — a tripwire, since nothing else pinned it
# --------------------------------------------------------------------------

def test_the_bundle_check_lexically_precedes_the_pack_filter():
    """Before this file, no test pinned the order at all: the two blocks could
    be swapped back and 791 tests still passed. The behavioural tests above
    are the real proof; this one fails faster and names the cause."""
    import inspect

    code = [
        ln.strip()
        for ln in inspect.getsource(ShopifyScraper._parse_product).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    bundle_at = [i for i, ln in enumerate(code)
                 if "self._is_bundle_offer(variant_title)" in ln]
    pack_at = [i for i, ln in enumerate(code)
               if "(?:plant|pack)" in ln]
    assert bundle_at, "the bundle check vanished from the JSON path"
    assert pack_at, "the multi-plant pack filter vanished from the JSON path"
    assert min(bundle_at) < min(pack_at), (
        "the pack filter runs first again, so 'BOGO / 2 Plant(s)' never "
        "reaches bundle_variants and an all-bundle product scores as priced"
    )
