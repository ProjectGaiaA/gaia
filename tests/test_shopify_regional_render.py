"""The FGT regional-render withhold, and the exact edges of what it covers.

WHAT THE DEFECT IS. On some runs fast-growing-trees.com serves a product page
built for one US state: a normal 200 on the normal URL, no redirect, rendering
only the variants that ship to that state at that state's prices. Nothing in
the rendered label says so — the storefront strips the "(CA)" / "(FL)"
parenthetical its own catalog carries. On the 2026-08-20 12:2x run five
products published a California price as if it were the national one, e.g.
bing-cherry-tree 5-6 ft at $153.95 when the national catalogue says $168.95.

WHAT THE SCRAPER DOES ABOUT IT, AND WHAT IT DOES NOT. The scrape-time
predicate is a vocabulary proxy: FGT's regional renders observed so far spell
heights "N-M ft." where the national render spells them "N-M feet".

This file pins BOTH sides of that, because the proxy is partial and a test
suite that only shows the happy case would hide it:

  * test_regional_render_is_withheld            it catches what it catches
  * test_national_render_is_untouched           and nothing else at FGT
  * test_gallon_only_regional_flip_is_NOT_caught the measured blind spot
  * test_other_retailers_are_not_gated_on_this  the measured FP it avoids

MEASURED COVERAGE (replayed over all 16,897 committed FGT rows; the replay
lives in tests/test_audit_regional_render.py):

    vocabulary predicate fires on   44 rows / 5 plants
    catalog audit fires on          58 rows / 6 plants
    they agree on                   15 rows
    UNION                           87 rows   <- the only ground truth we have

    vocabulary share of that union  44/87 = 50.6%

THERE IS NO KNOWN TOTAL. 87 is the union of two partial detectors, not a
census of regional renders — a render neither one catches is by construction
absent from it, so 50.6% is an upper bound on this predicate's recall, not an
estimate of it. Quote 87 as "what we can demonstrate", never as "how many
there were".

The two are COMPLEMENTARY, not redundant. 43 of the audit's 58 carry no "ft."
at all — 27 of them are pink-lemonade-blueberry's gallon-only flip, which is
invisible to any label-based rule, and 16 are fuji-apple-tree regional renders
served in JUNE spelled "5-6 feet". That last group is the important one: it
proves FGT does NOT always use "ft." on a regional render, so this predicate
is a cheap partial defence and must never be described as a complete one.
Conversely 29 of the vocabulary's 44 are rows the audit cannot speak to --
all of them meyer-lemon-tree rows older than the window the price clauses
can honestly compare against.
"""

import json
import logging
import re

import pytest
import responses

from tests.conftest import load_fixture
from scrapers import shopify as shopify_mod
from scrapers.shopify import (
    ShopifyScraper,
    _REGIONAL_SIZE_VOCAB_RE,
    _has_regional_size_vocabulary,
)

BASE = "https://www.fgt.com"
# Any Shopify retailer that is NOT fast-growing-trees. The regional claim was
# measured at FGT only, so this is the control.
OTHER = "planting-tree"


def _scrape(handle, html, retailer_id="fast-growing-trees"):
    responses.add(responses.GET, f"{BASE}/products/{handle}.json", status=404)
    responses.add(responses.GET, f"{BASE}/products/{handle}", body=html, status=200)
    return ShopifyScraper(retailer_id, BASE).scrape_product(handle)


# --- the vocabulary itself -------------------------------------------------


@pytest.mark.parametrize("label", [
    "4-5 ft.", "5-6 ft.", "1-2 ft.", "4-5 ft. Jumbo", "1-2 ft. Tree",
    "2-3 ft. (CA)", "5-6 ft. (FL)",
])
def test_regional_vocabulary_matches_the_ft_period_form(label):
    assert _REGIONAL_SIZE_VOCAB_RE.search(label)


@pytest.mark.parametrize("label", [
    # The national spelling. If this ever matches, EVERY FGT product is
    # withheld on EVERY run: 22,067 of the 22,144 committed FGT height cells
    # are spelled this way.
    "5-6 feet", "1-2 feet", "6-7 feet Jumbo", "Flash Sale - 3-4 feet",
    # No period, so not the form that was measured.
    "5-6 ft", "3 ft tall",
    # `ft` inside another word must not count.
    "Soft. Touch Holly", "Loft.", "Driftwood.",
    # Container tiers carry no height vocabulary at all.
    "2 Gallon", "1 Quart", "4 inch", "Bare Root",
])
def test_regional_vocabulary_does_not_match_the_national_spelling(label):
    assert not _REGIONAL_SIZE_VOCAB_RE.search(label)


def test_predicate_is_any_not_all():
    """One regional label condemns the page; the render is regional whole."""
    assert _has_regional_size_vocabulary(["2 Gallon", "5-6 ft."])
    assert not _has_regional_size_vocabulary(["2 Gallon", "5-6 feet"])
    assert not _has_regional_size_vocabulary([])
    assert not _has_regional_size_vocabulary([None, ""])


# --- the withhold ----------------------------------------------------------


@responses.activate
def test_regional_render_is_withheld(no_sleep):
    """Synthetic fixture, real measured shape. See the fixture's own header.

    The page parses perfectly — two size buttons, two prices, two was_prices —
    and is still published as an EMPTY row, because every one of those prices
    is a California price.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-regional-synthetic-page.html"),
    )

    assert result["sizes"] == {}, (
        "a regional render must publish no cells: every price on it is one "
        f"state's price. Got {result['sizes']}"
    )
    assert result["regional_render"] is True
    assert result["no_sizes_readable"] is True
    # NOT False — the plant is not sold out. NOT True — there is no
    # single-catalogue offer to make a stock claim about.
    assert result["in_stock"] is None


@responses.activate
def test_regional_render_returns_a_row_not_silence(no_sleep):
    """The mechanism that WITHDRAWS the previous price, pinned.

    `return None` would append nothing, and build.py's get_latest_prices takes
    the newest row per (plant, retailer) — so the previous regional row would
    stay newest and keep publishing the very price this branch exists to
    remove. Only a row withdraws a row.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-regional-synthetic-page.html"),
    )
    assert result is not None, "silence does not withdraw a published price"
    assert result["handle"] == "honeycrisp-apple-tree"
    assert result["timestamp"]


@responses.activate
def test_regional_render_carries_no_variant_ids(no_sleep):
    """F4 interaction: a withheld row cannot deep-link to anything.

    `?variant=` ids are minted per CELL inside the size loop. A regional row
    returns before that loop, so there are no cells and therefore no ids —
    which is what must happen: a CA variant id in a national product URL is a
    link to a product the visitor cannot buy.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-regional-synthetic-page.html"),
    )
    assert result["sizes"] == {}
    assert "variant=" not in result["url"], result["url"]
    blob = json.dumps(result)
    assert "variant_id" not in blob


@responses.activate
def test_regional_render_does_not_set_the_bundle_flag(no_sleep):
    """F4 interaction: the three empty-row causes stay distinguishable.

    `sizes: {}` is now reachable three ways — sold out, all-offers-bundled,
    and regional. Each carries its own provenance key and must not carry
    another product's.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-regional-synthetic-page.html"),
    )
    assert result.get("all_offers_bundled") is None
    assert result["in_stock"] is not False, "not a sold-out row"


# --- what must NOT be withheld ---------------------------------------------


@responses.activate
def test_national_render_is_untouched(no_sleep):
    """Real captured page (2026-08-11), verbatim markup. Six tiers, all live.

    Expected values are the ones a shopper saw, recorded independently in the
    committed row for 2026-08-16 in data/prices/honeycrisp-apple-tree.jsonl.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-national-page.html"),
    )

    assert result.get("regional_render") is None
    assert result.get("no_sizes_readable") is None
    sizes = result["sizes"]
    assert {t: c["price"] for t, c in sizes.items()} == {
        "1-2ft": 75.95,
        "2-3ft": 86.95,
        "3-4ft": 69.95,
        "4-5ft": 129.95,
        "5-6ft": 153.95,
        "6-7ft": 183.95,
    }
    assert sizes["3-4ft"]["was_price"] == 100.95


@responses.activate
def test_gallon_only_regional_flip_is_NOT_caught(no_sleep):
    """THE BLIND SPOT, PINNED AS A FACT RATHER THAN LEFT AS A SURPRISE.

    pink-lemonade-blueberry's regional render is a single "2 Gallon" button at
    $44.95 — the "2 Gallon (CA)" variant. The national "2 Gallon" is $48.95.
    Once the storefront strips the parenthetical the two labels are
    byte-identical, so NO label-based rule can separate them and this one does
    not pretend to.

    27 committed rows are this exact shape, and every one of them published a
    CA price. Catching them is scripts/audit_regional_render.py's job, which
    compares against the catalog instead of the label — and it does catch all
    27 (see tests/test_audit_regional_render.py).

    THIS TEST ASSERTS A GAP, NOT A GUARANTEE. If someone later teaches the
    scraper to catch container-tier flips, this test SHOULD fail; update it,
    do not delete the coverage it documents.
    """
    result = _scrape(
        "pink-lemonade-blueberry",
        load_fixture("fgt", "pink-lemonade-regional-synthetic-page.html"),
    )

    assert result.get("regional_render") is None, (
        "the vocabulary predicate is not supposed to catch container tiers"
    )
    assert result["sizes"]["2gal"]["price"] == 44.95
    # And this is the harm the audit exists to name: a CA price, published.
    assert result["sizes"]["2gal"]["was_price"] == 48.95


@responses.activate
def test_other_retailers_are_not_gated_on_this(no_sleep):
    """THE FALSE POSITIVE THE RETAILER GATE PREVENTS, MEASURED.

    "N-M ft." is planting-tree's ORDINARY size vocabulary: 4,789 cells across
    1,065 committed planting-tree rows are spelled exactly this way, every one
    a normal national listing. Each of those rows is a product an ungated
    predicate would withhold for a claim nobody measured at that retailer.
    (For scale: 1,065 of 19,615 planting-tree rows, 4 of its 75 plants — the
    blast radius is concentrated, not diffuse, which is exactly why it would
    read as "those four plants lost their prices" rather than as an outage.)

    Same fixture, same labels, different retailer_id — and it must publish.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        load_fixture("fgt", "honeycrisp-regional-synthetic-page.html"),
        retailer_id=OTHER,
    )

    assert result.get("regional_render") is None
    assert {t: c["price"] for t, c in result["sizes"].items()} == {
        "4-5ft": 117.95,
        "5-6ft": 139.95,
    }


# --- instrumentation: recorded, never enforced -----------------------------


@responses.activate
def test_region_token_is_logged_and_never_withholds(no_sleep, caplog):
    """isRegionKnown is RECORDED. It must not change what is published.

    Nobody has captured the token in the failure state — all 64 cached FGT
    pages carrying it carry `false`, and all 64 are national renders. Gating
    on an unmeasured value would either withhold everything or nothing.
    """
    with caplog.at_level(logging.INFO, logger="scrapers.shopify"):
        result = _scrape(
            "honeycrisp-apple-tree",
            load_fixture("fgt", "honeycrisp-national-page.html"),
        )
    assert "isRegionKnown=false" in caplog.text
    assert result["sizes"], "the token must not have withheld anything"


@responses.activate
def test_absent_region_token_is_recorded_as_absent_not_alarmed(no_sleep, caplog):
    """Absence means handle rot, not drift, so it must not withhold.

    The only 2 of 66 cached FGT pages missing the token are
    hameln-dwarf-fountain-grass and sunny-knock-out-rose, whose handles have
    rotted to /collections/ pages. That is a different defect with a different
    fix.
    """
    html = load_fixture("fgt", "honeycrisp-national-page.html")
    html = re.sub(r'<script>self\.__next_f[^<]*</script>', "", html)
    assert "isRegionKnown" not in html

    with caplog.at_level(logging.INFO, logger="scrapers.shopify"):
        result = _scrape("honeycrisp-apple-tree", html)
    assert "isRegionKnown=absent" in caplog.text
    assert result["sizes"], "an absent token must not withhold"


@responses.activate
def test_non_fgt_retailers_are_not_instrumented(no_sleep, caplog):
    """The instrumentation is scoped like the predicate it supports."""
    with caplog.at_level(logging.INFO, logger="scrapers.shopify"):
        _scrape(
            "honeycrisp-apple-tree",
            load_fixture("fgt", "honeycrisp-national-page.html"),
            retailer_id=OTHER,
        )
    assert "isRegionKnown" not in caplog.text


@responses.activate
def test_handle_redirect_is_logged_and_never_enforced(no_sleep, caplog):
    """A handle's redirect target cannot be read from data at rest.

    tests/test_link_correctness.py can lint the SHAPE of a handle offline, but
    "does /products/x redirect to /products/y" needs a fetch. This is where
    that assertion lives — as a log line, not a gate: two FGT handles redirect
    harmlessly today and withholding them would drop real prices.
    """
    responses.add(
        responses.GET, f"{BASE}/products/stella-cherry-tree-ca.json", status=404,
    )
    responses.add(
        responses.GET, f"{BASE}/products/stella-cherry-tree-ca",
        status=302, headers={"Location": f"{BASE}/products/stella-cherry-tree"},
    )
    responses.add(
        responses.GET, f"{BASE}/products/stella-cherry-tree",
        body=load_fixture("fgt", "honeycrisp-national-page.html"), status=200,
    )
    with caplog.at_level(logging.INFO, logger="scrapers.shopify"):
        result = ShopifyScraper("fast-growing-trees", BASE)._scrape_product_html(
            "stella-cherry-tree-ca"
        )
    assert "handle_redirect" in caplog.text
    assert "stella-cherry-tree" in caplog.text
    assert result["sizes"], "a redirect must not withhold anything"


# --- branch precedence when two causes are true at once --------------------


def _one_button_page(labels):
    """Build a page from the REAL captured <button> wrapper, one per label."""
    nat = load_fixture("fgt", "honeycrisp-national-page.html")
    tmpl = [
        b for b in re.findall(r"<button (?:(?!</button>).)*?</button>", nat, re.S)
        if "Original price" not in b
    ][0]
    sec = re.search(r"<section[^>]*>.*?<h2[^>]*>Select size</h2>", nat, re.S).group(0)
    buttons = "".join(
        re.sub(r'aria-label="[^"]*"', 'aria-label="%s"' % lbl, tmpl) for lbl in labels
    )
    offer = {
        "@type": "Product",
        "offers": [{
            "@type": "Offer", "sku": "13940811071540",
            "availability": "https://schema.org/InStock",
            "priceSpecification": [{
                "@type": "UnitPriceSpecification",
                "price": "117.95", "priceCurrency": "USD",
            }],
        }],
    }
    return (
        "<html><head><title>T</title></head><body>" + sec + "<div>" + buttons
        + "</div></section><script type=\"application/ld+json\">"
        + json.dumps(offer) + "</script></body></html>"
    )


@responses.activate
def test_bundle_cause_wins_the_label_when_a_page_is_both(no_sleep):
    """A regional page whose every offer is ALSO a bundle is labelled
    `all_offers_bundled`, not `regional_render`. Pinned so the precedence is
    a decision rather than an accident.

    WHY, and why it is harmless. A bundle label never enters `aria_offers` —
    `_extract_aria_size_offers` diverts it to `withheld_bundles` — so an
    all-bundle page arrives with `aria_offers` EMPTY and never reaches the
    regional branch, which lives inside `if aria_offers:`.

    What matters is unchanged: the row is EMPTY, `no_sizes_readable` is set,
    the stale price is withdrawn and the health signal drops. Only the
    provenance key is the less precise of two true ones. Publishing nothing
    for two reasons and naming one of them is not a correctness defect.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        _one_button_page(["4-5 ft. - Price $117.95 - Buy 1, Get 1"]),
    )
    assert result["sizes"] == {}
    assert result["no_sizes_readable"] is True
    assert result["all_offers_bundled"] is True
    assert result.get("regional_render") is None


@responses.activate
def test_a_mixed_vocabulary_page_is_withheld_whole(no_sleep):
    """One regional label condemns the page.

    A render that offers "4-5 feet" and "5-6 ft." side by side is not half
    national; it is a page we cannot attribute, and the tier set on it is
    whatever that state stocks. Publishing the "feet" half would republish the
    defect with a smaller blast radius.
    """
    result = _scrape(
        "honeycrisp-apple-tree",
        _one_button_page([
            "4-5 feet - Price $129.95",
            "5-6 ft. - Price $139.95",
        ]),
    )
    assert result["sizes"] == {}
    assert result["regional_render"] is True


@responses.activate
def test_a_zero_priced_regional_page_is_still_withheld(no_sleep):
    """A 0 is "no price", never a free plant — and it must not route the page
    around the regional branch into the positional-pairing fallback."""
    result = _scrape(
        "honeycrisp-apple-tree", _one_button_page(["4-5 ft. - Price $0.00"]),
    )
    assert result["sizes"] == {}
    assert result["regional_render"] is True

# --- the JSON-path bypass: a KNOWN, PINNED gap -----------------------------


def test_the_withhold_fires_from_exactly_one_parser():
    """THE WITHHOLD IS NOT UNIVERSAL. This test exists to say so out loud.

    `all_offers_bundled` is emitted from TWO parsers, because a bundle can
    arrive down either. `regional_render` is emitted from ONE: the aria branch
    of `_scrape_product_html`. Two other code paths in this module can publish
    sizes and neither is guarded:

      1. `_parse_product` -- the /products/{handle}.json path. FGT reaches the
         HTML fallback ONLY because its .json endpoint 404s today. That is a
         setting on the retailer's side. If it flips, every FGT product routes
         through `_parse_product`, the withhold stops firing, and nothing
         fails: no error, no alarm, no red test. The regional prices would
         simply start publishing again.
      2. the positional size<->price fallback lower in `_scrape_product_html`,
         reached when the aria format has drifted.

    WHY IT IS NOT SIMPLY FIXED. The vocabulary claim was measured on
    storefront aria labels. The JSON path carries variant TITLES, and the
    committed reference shows 47 of its 58 NATIONAL variants titled "N-M ft."
    -- so copying the predicate across would withhold most of the FGT
    catalogue the moment that path started being used. The durable
    discriminator there is the "(CA)"/"(FL)" parenthetical, which the JSON
    path DOES carry and the storefront strips, and wiring that up is a
    separate measured change.

    THIS TEST FAILS IF SOMEONE ADDS COVERAGE WITHOUT UPDATING THE DOCS.
    That is deliberate: the failure message is the handoff.
    """
    import ast
    import pathlib

    src = pathlib.Path(shopify_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _emitters(key):
        """Function names that set `key` to True, by any syntax."""
        out = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, fn) or ""
            if f'"{key}"' in body:
                out.append((fn.name, body.count(f'"{key}"')))
        # keep only the innermost function for each occurrence
        return sorted(out, key=lambda t: -t[1])

    regional = {name for name, _ in _emitters("regional_render")}
    bundled = {name for name, _ in _emitters("all_offers_bundled")}

    assert regional == {"_scrape_product_html"}, (
        "The set of parsers that emit `regional_render` changed. If you added "
        "the withhold to another path (e.g. the JSON path `_parse_product`), "
        "that is GOOD -- but update this test, the comment at the emission "
        "site in shopify.py, and the module docstring above, all of which "
        f"currently tell the reader it fires from exactly one. Found: {regional}"
    )
    assert "_parse_product" in bundled, (
        "sanity: all_offers_bundled is the two-parser precedent this test "
        "contrasts against"
    )
    assert "_parse_product" not in regional, (
        "the JSON path is documented as UNGUARDED; see this test's docstring"
    )


@responses.activate
def test_the_json_path_publishes_a_regional_label_unguarded(no_sleep):
    """The bypass, DEMONSTRATED rather than merely described.

    Same regional labels, arriving as Shopify variant titles down the JSON
    endpoint instead of as aria labels down the HTML one. The prices publish.

    This is the current, accepted behaviour and the test asserts it so the gap
    is visible in the suite rather than only in a comment. If the withhold is
    ever extended to the JSON path this test SHOULD fail -- rewrite it to
    assert the withhold, do not delete it.
    """
    handle = "honeycrisp-apple-tree"
    responses.add(
        responses.GET, f"{BASE}/products/{handle}.json",
        json={"product": {"id": 1, "title": "Honeycrisp Apple Tree",
                          "handle": handle, "variants": [
                              {"id": 13940811071540, "title": "4-5 ft.",
                               "price": "117.95", "compare_at_price": "123.95"},
                              {"id": 13940811104308, "title": "5-6 ft.",
                               "price": "139.95", "compare_at_price": "146.95"},
                          ]}},
        status=200,
    )
    responses.add(
        responses.GET, f"{BASE}/products/{handle}.js",
        json={"variants": [{"id": 13940811071540, "available": True},
                           {"id": 13940811104308, "available": True}]},
        status=200,
    )
    result = ShopifyScraper("fast-growing-trees", BASE).scrape_product(handle)

    assert result.get("regional_render") is None, (
        "the JSON path is UNGUARDED -- see "
        "test_the_withhold_fires_from_exactly_one_parser"
    )
    assert {t: c["price"] for t, c in result["sizes"].items()} == {
        "4-5ft": 117.95, "5-6ft": 139.95,
    }, "the gap: two California prices, published as national"

