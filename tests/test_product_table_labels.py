"""The desktop column headers and the price-cell `data-label`s are the SAME
vocabulary as everything else on the page.

Until P8, product.html formatted both of them itself:

    {{ tier|replace('gal', ' Gal')|replace('quart', 'Quart')
           |replace('bareroot', 'Bare Root')|title
           |replace('2quart', '2 Quart')|replace('3quart', '3 Quart') }}

That was a second label vocabulary living in the template, and it disagreed
with `get_size_label()` on 50 of the 58 tier ids the corpus carries. Both
vocabularies were published on the same page at the same time: the mobile
"best price" card said "0.65 Gallon" while the column two inches away said
"0-65- Gallon", and the mobile card said '4" Pot' while the column said
"4inch". 1,291 price cells and 433 headers shipped in the losing vocabulary.

The expectations here are LITERALS. They are read out of the hand-written
table in test_size_label_vocabulary.py by parsing that file's source, so this
module never calls `get_size_label`, `normalize_size_tier`, `_dimension_label`,
`SIZE_TIER_LABELS` or `_TIER_SUFFIX_LABELS`. Comparing rendered output against
the function that produced it is a shared oracle and proves nothing; the
hand-pinned literals are the independent side.

`build` is used for exactly one thing: which tier ids a page carries, and in
what order (`active_size_tiers`). That is a key set, never an expected string.
"""

import ast
import functools
import html as htmlmod
import json
import os
import re
from datetime import datetime, timezone

import jinja2
import pytest

import build

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_FILE = os.path.join(REPO, "tests", "test_size_label_vocabulary.py")


def _pinned_literals():
    """LIVE_TIER_LABELS, read out of the sibling test's SOURCE.

    Parsed rather than imported so that nothing in this module can reach the
    formatting code by accident, and so a reader can see at a glance that the
    expected strings are typed by hand somewhere and not derived here.
    """
    tree = ast.parse(open(VOCAB_FILE, encoding="utf-8").read())
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "LIVE_TIER_LABELS"):
            return {
                ast.literal_eval(k): ast.literal_eval(v)
                for k, v in zip(node.value.keys, node.value.values)
            }
    raise AssertionError("LIVE_TIER_LABELS not found in " + VOCAB_FILE)


PINNED = _pinned_literals()

# <th>/data-label strings on the comparison table that are not size tiers.
FIXED_TH = {"Retailer", "In Stock", "Shipping", "Last Checked", "Specials"}
FIXED_DL = {"Stock", "Shipping", "Last Checked", "Specials"}

_TABLE_RE = re.compile(r'<table class="comparison-table">(.*?)</table>', re.S)
_TH_RE = re.compile(r"<th>(.*?)</th>", re.S)
_DL_RE = re.compile(r'data-label="([^"]*)"')


@functools.lru_cache(maxsize=1)
def _env():
    """The environment build_site() constructs.

    Two things about it matter here, both deliberate on its side.
    `autoescape` is OFF, which is why `data-label` has to be escaped
    explicitly. And no `undefined=` is passed, so Jinja's DEFAULT Undefined
    is in force: a missing key in `tier_labels` renders as the EMPTY STRING
    rather than raising. The guard against that lives in
    build_price_table(); the two tests below exercise both halves.

    Cached because the sweep renders one page per active plant, and the
    environment carries no per-test state.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(build.TEMPLATE_DIR),
        autoescape=False,
    )
    env.globals["current_year"] = 2026
    env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
    return env


def _render(plant, table):
    return _env().get_template("product.html").render(
        plant=plant,
        page_title="t",
        canonical_url="http://x/p.html",
        base_url="http://x",
        category_name="C",
        category_slug="c",
        **table,
    )


def _table_section(html):
    m = _TABLE_RE.search(html)
    assert m, "page carries no desktop comparison table"
    return m.group(1)


def _tier_headers(section):
    return [htmlmod.unescape(t.strip())
            for t in _TH_RE.findall(section) if t.strip() not in FIXED_TH]


def _tier_data_labels(section):
    return [htmlmod.unescape(d)
            for d in _DL_RE.findall(section) if d not in FIXED_DL]


# ---------------------------------------------------------------------------
# Every real page, real corpus data, the real template.
#
# This sweeps ALL active plants rather than one representative page. A single
# page only pins the tiers that page happens to carry: the first version of
# this file tested the plant with the most columns, which left 19 live-active
# tiers with no positional assertion at all. A review mutant that mislabelled
# three of those untested tiers passed the entire suite while money-tree
# published two different columns both headed "1 Gallon" — one of them
# actually the `6inch` tier.
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _corpus():
    """Every active plant and the retailer map, loaded once for the sweep."""
    plants = [p for p in build.load_json(os.path.join(build.DATA_DIR, "plants.json"))
              if p.get("active", True)]
    retailers = {r["id"]: r for r in
                 build.load_json(os.path.join(build.DATA_DIR, "retailers.json"))
                 if r.get("active", True)}
    assert len(plants) > 90, f"corpus too small to prove anything: {len(plants)}"
    return {p["id"]: p for p in plants}, retailers


def _plant_ids():
    return sorted(_corpus()[0])


def _real_table(plant_id):
    plants, retailers = _corpus()
    plant = plants[plant_id]
    entries = build.load_prices(plant_id)
    table = build.build_price_table(
        plant, build.get_latest_prices(entries, retailers), retailers, {}, entries
    )
    return plant, table


@pytest.mark.parametrize("plant_id", _plant_ids())
def test_a_real_product_page_renders_the_pinned_labels(plant_id):
    """Header row and every price row, position by position, against literals.

    Pre-P8 this fails on the first tier whose two vocabularies disagree —
    e.g. "3-4ft" where the pinned literal is "3-4 ft".
    """
    plant, table = _real_table(plant_id)
    tiers = list(table["active_size_tiers"])
    if not tiers:
        pytest.skip(f"{plant_id} carries no size column")

    unpinned = [t for t in tiers if t not in PINNED]
    assert not unpinned, (
        f"{plant_id} renders tier ids with no hand-written label: {unpinned}"
    )
    expected = [PINNED[t] for t in tiers]

    section = _table_section(_render(plant, table))

    got = _tier_headers(section)
    assert got == expected, (
        f"{plant_id} column headers are not the pinned vocabulary"
    )

    # Two columns on one page must never carry the same header. The new
    # vocabulary is NOT injective — `12-18-inch` and `12-18in` both pin to
    # '12-18"', and `18-24-inch` and `18-24in` likewise — so this is a
    # reachable state, not a hypothetical. Both members of each colliding
    # pair are FUTURE-only today; the day the scraper's Step-9 slug path
    # puts one live alongside its twin, this is what says so. P8 is the
    # change that moves that collision onto the visible desktop header.
    assert len(set(got)) == len(got), (
        f"{plant_id} renders two columns under the same header: "
        f"{sorted(h for h in set(got) if got.count(h) > 1)} — tier ids "
        f"{tiers}"
    )

    labels = _tier_data_labels(section)
    n = len(expected)
    assert labels, f"{plant_id}: every price-cell data-label vanished"
    assert len(labels) % n == 0, (
        f"{plant_id}: {len(labels)} price-cell data-labels is not a whole "
        f"number of {n}-column rows"
    )
    for i in range(0, len(labels), n):
        assert labels[i:i + n] == expected, (
            f"{plant_id} row {i // n} data-labels are not the pinned "
            f"vocabulary"
        )


def test_the_sweep_actually_covers_the_live_vocabulary():
    """The sweep is only worth its runtime if it reaches most live tiers.

    Without this, the parametrised sweep above could quietly degrade to
    passing-by-skipping if pages stopped rendering columns.
    """
    seen = set()
    for pid in _plant_ids():
        seen.update(_real_table(pid)[1]["active_size_tiers"])
    assert len(seen) >= 40, (
        f"sweep reaches only {len(seen)} distinct tiers; it is no longer a "
        f"meaningful check of the vocabulary"
    )
    unpinned = sorted(seen - set(PINNED))
    assert not unpinned, f"live tiers with no pinned label: {unpinned}"


def _a_plant_with_columns():
    for pid in _plant_ids():
        if _real_table(pid)[1]["active_size_tiers"]:
            return pid
    raise AssertionError("no plant in the corpus carries a size column")


def test_a_dropped_label_key_would_render_a_blank_header():
    """Why the guard in build_price_table() has to exist.

    Jinja's default Undefined renders a missing dict KEY as the empty string,
    so a short `tier_labels` ships `<th></th>` and `data-label=""` silently.
    That is worse than the replace() chain P8 deleted, which at least
    degraded to printing the raw tier id.

    StrictUndefined is not the alternative: product.html tests
    `retailer_prices.sizes[tier]` for falsiness on tiers a given retailer
    does not stock, and StrictUndefined raises on that instead.
    """
    plant, table = _real_table(_a_plant_with_columns())
    dropped = table["active_size_tiers"][0]

    crippled = dict(table)
    crippled["tier_labels"] = {
        t: lab for t, lab in table["tier_labels"].items() if t != dropped
    }
    section = _table_section(_render(plant, crippled))

    assert "<th></th>" in section, (
        "a dropped tier_labels key no longer renders a blank header — "
        "re-read the guard's rationale in build_price_table()"
    )
    assert 'data-label=""' in section


def test_a_missing_label_is_refused_by_the_builder():
    """...and the builder must never hand the template that state.

    The dict comprehension cannot drop a key on its own; an edit to it can,
    and exactly such an edit survived a 13-mutant review pass before this
    guard existed.
    """
    plants, retailers = _corpus()
    plant = plants[_a_plant_with_columns()]
    entries = build.load_prices(plant["id"])
    latest = build.get_latest_prices(entries, retailers)

    real = build.get_size_label
    try:
        # A label producer that returns blank for one family of tiers.
        build.get_size_label = lambda t: "" if t.endswith("gal") else real(t)
        with pytest.raises(ValueError, match="blank label"):
            build.build_price_table(plant, latest, retailers, {}, entries)
    finally:
        build.get_size_label = real

    # Sanity: with the real producer the same call succeeds and is complete.
    table = build.build_price_table(plant, latest, retailers, {}, entries)
    assert set(table["tier_labels"]) == set(table["active_size_tiers"])


# ---------------------------------------------------------------------------
# A fixed synthetic page. Deterministic, and picks the tiers where the two
# vocabularies disagreed most loudly.
# ---------------------------------------------------------------------------

_PLANT = {
    "id": "p", "common_name": "Test Plant", "botanical_name": "T t",
    "category": "shrubs", "zones": [5], "sun": "Full", "mature_size": "x",
    "bloom_time": "x", "type": "Shrub", "description": "d",
}

# tier id -> (price, the string the OLD in-template replace chain produced).
# The second element is what must NOT appear anywhere on the page.
_CASES = {
    "3gal":              (30.0, "3 Gal"),
    "3-4ft":             (40.0, "3-4ft"),
    "0-65-gallon":       (12.0, "0-65- Gallon"),
    "4inch":             (9.0, "4inch"),
    "2-5-pot":           (11.0, "2-5-Pot"),
    "12-18in-bareroot":  (17.0, "12-18in-Bare Root"),
    "standard-ez-start": (60.0, "Standard-Ez-Start"),
    "6-7ft-jumbo":       (90.0, "6-7ft-Jumbo"),
    # The four tiers the two vocabularies already agreed on — they must come
    # through P8 unchanged, or the fix moved something it had no business
    # moving.
    "quart":             (5.0, "Quart"),
    "2quart":            (6.0, "2 Quart"),
    "3quart":            (7.0, "3 Quart"),
    "bareroot":          (8.0, "Bare Root"),
}


def _synthetic_table():
    retailers = {"r1": {"id": "r1", "name": "R1", "url": "http://r1",
                        "affiliate": None}}
    latest = {"r1": {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sizes": {
            tier: {"price": price, "available": True, "raw_size": tier}
            for tier, (price, _old) in _CASES.items()
        },
        "in_stock": True,
    }}
    return build.build_price_table(_PLANT, latest, retailers)


@pytest.mark.parametrize("tier", sorted(_CASES))
def test_column_header_is_the_pinned_literal(tier):
    table = _synthetic_table()
    assert tier in table["active_size_tiers"], f"{tier} lost its column"
    section = _table_section(_render(_PLANT, table))
    assert PINNED[tier] in _tier_headers(section), (
        f"<th> for {tier} is not {PINNED[tier]!r}"
    )


@pytest.mark.parametrize("tier", sorted(_CASES))
def test_price_cell_data_label_is_the_pinned_literal(tier):
    """The cell's own record of which size it belongs to.

    No CSS reads this attribute — there is no `attr(data-label)` rule in
    style.css, and this table is `display: none` under 600px — so a wrong
    value here is not a wrong size shown on a phone. It still has to be
    right: it is the only marker tying a price cell to a size once the cell
    is read outside its table context, and the page's own script treats a
    present data-label as authoritative and leaves it alone.
    """
    table = _synthetic_table()
    section = _table_section(_render(_PLANT, table))
    assert PINNED[tier] in _tier_data_labels(section), (
        f"data-label for {tier} is not {PINNED[tier]!r}"
    )


@pytest.mark.parametrize("tier", sorted(_CASES))
def test_the_old_template_chain_output_is_gone(tier):
    """Belt and braces: the losing vocabulary must not survive anywhere.

    Skipped for the four tiers the two vocabularies already agreed on — for
    those the "old" string IS the pinned literal.
    """
    _price, old = _CASES[tier]
    if old == PINNED[tier]:
        pytest.skip(f"{tier} rendered identically in both vocabularies")
    section = _table_section(_render(_PLANT, _synthetic_table()))
    # Whole rendered strings, not a substring search: "3 Gal" is a prefix of
    # the correct "3 Gallon", so `old not in section` would fire on a page
    # that is in fact right.
    rendered = set(_tier_headers(section)) | set(_tier_data_labels(section))
    assert old not in rendered, (
        f"{old!r} — output of the replace() chain P8 deleted — is still "
        f"being rendered for {tier}"
    )


def test_every_price_cell_still_carries_a_data_label():
    """P8 changed the VALUE of the attribute. Losing the attribute itself
    would strip a price cell of any record of which size it holds."""
    table = _synthetic_table()
    section = _table_section(_render(_PLANT, table))
    cells = re.findall(r'<td class="price-cell"[^>]*>', section)
    assert cells, "no price cells rendered"
    missing = [c for c in cells if "data-label=" not in c]
    assert not missing, f"{len(missing)} price cells lost their data-label"


def test_the_inch_mark_is_escaped_in_the_attribute_and_raw_in_the_header():
    """autoescape is OFF in this environment. A label like '2.5" Pot' written
    raw into data-label="..." terminates the attribute early and corrupts the
    tag."""
    section = _table_section(_render(_PLANT, _synthetic_table()))
    assert '<th>2.5" Pot</th>' in section
    assert 'data-label="2.5&#34; Pot"' in section
    # The broken form: the attribute terminated early by a raw inch mark.
    assert 'data-label="2.5"' not in section.replace('data-label="2.5&#34;', "")


def test_the_template_contains_no_label_formatting_of_its_own():
    """One producer. The next person to reach for `|replace` on a tier id in
    the template should trip this instead of shipping a third vocabulary."""
    src = open(os.path.join(build.TEMPLATE_DIR, "product.html"),
               encoding="utf-8").read()
    # Strip Jinja comments — they NAME the deleted chain on purpose.
    body = re.sub(r"\{#.*?#\}", "", src, flags=re.S)
    for banned in ("replace('gal'", 'replace("gal"',
                   "replace('quart'", "replace('bareroot'",
                   "replace('2quart'", "replace('3quart'"):
        assert banned not in body, (
            f"product.html formats size labels again: {banned}"
        )
