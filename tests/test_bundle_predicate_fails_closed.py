"""The bundle predicate is the one guard in shopify.py that failed OPEN.

Every other guard in that file fails closed: a page it cannot read publishes
nothing. `_is_bundle_offer` was the exception. A marker it did not recognise
meant the two-plant price sailed through and was published as the price of
ONE plant — silently, with no alarm and no failing test. Withholding a real
single-plant price costs a blank cell; publishing a Buy-1-Get-1 price as a
single-plant price is a false comparison on a site whose entire job is
comparing prices. The two errors are not symmetric, so the predicate is
deliberately wider than the one form FGT writes today.

Two defects, both found by red team against a1272f3e:

  * It ran against RAW, UN-DECODED HTML. The cached corpus proves entities
    survive into label text — one page carries "Today&amp;#x27;s
    announcements", DOUBLE-encoded. "Buy&nbsp;1,&nbsp;Get&nbsp;1" would have
    walked straight past `\\bbuy\\s+`.
  * The forms were too narrow: "BOGO50" (no word boundary exists between "o"
    and "5"), "2-for-1" and "Buy1Get1" (both needed literal whitespace), an
    en-dash instead of the comma, "2 for the price of 1".

Measured over the 35 phrasings below: 17/35 matched before, 35/35 after.
False positives over the 16 single-plant strings below: 2 before, 0 after.

"Wider" is only safe with a control, so `test_no_false_positives_over_*` runs
the predicate over every real value the live corpus contains — all 211
distinct `(retailer, raw_size)` pairs in data/prices/*.jsonl and all
plants.json names, botanicals and aliases. Those must stay at ZERO matches:
each one would be a price cell blanked out on the live site.
"""

import json
import re
from pathlib import Path

import pytest

from scrapers.shopify import ShopifyScraper

ROOT = Path(__file__).resolve().parent.parent

# The predicate as it shipped in a1272f3e. Kept verbatim as a control: if it
# ever stops missing the phrasings below, these tests are measuring nothing.
A1272F3E_RE = re.compile(
    r"\bbogo\b"
    r"|\bb\dg\d\b"
    r"|\bbuy\s+\w+\s*,?\s*get\s+\w+"
    r"|\b\d+\s+for\s+\$?\d",
    re.IGNORECASE,
)

# Each of these means "this price buys more than one plant". Publishing any of
# them in a size column beside another nursery's single plant is the defect.
BUNDLE_PHRASINGS = [
    # what FGT writes today — must keep matching
    "1-2 feet - Price $94.95 - Buy 1, Get 1",
    "3 gallon - Price $114.95 - Buy 1 Get 1",
    "1 gallon - Price $19.99 - Buy One Get One",
    "2-3 feet - Price $57.95 - Buy One, Get One Free",
    # the spring-hill form the runbook records
    "3-4' BOGO",
    "1 Gallon BOGO",
    # BOGO with the discount glued on: \bbogo\b could never match these
    "2 Gallon BOGO50",
    "1 quart BOGO-50",
    "5 gallon BOGO Free",
    # the compact codes
    "3 gallon B1G1",
    "1 gallon B2G1",
    "2 gallon B1-G1",
    "4 inch B1 G1",
    # entities, single- and double-encoded, and a non-breaking space
    "1-2 feet - Price $94.95 - Buy&nbsp;1,&nbsp;Get&nbsp;1",
    "1-2 feet - Price $94.95 - Buy&amp;nbsp;1,&amp;nbsp;Get&amp;nbsp;1",
    "1-2 feet - Price $94.95 - Buy 1, Get 1",
    "1-2 feet - Price $94.95 - buy 1 &amp; get 1",
    # punctuation variants on the separator
    "1-2 feet - Price $94.95 - Buy 1 – Get 1",   # en dash
    "1-2 feet - Price $94.95 - Buy 1 — Get 1",   # em dash
    "1-2 feet - Price $94.95 - Buy1Get1",
    # N-for-M
    "1 gallon 2-for-1",
    # en/em dashes where the hyphen belongs. A theme's typographic filter
    # rewrites these silently, and only _DASHY folding keeps them matching.
    "1 gallon 2–for–1",
    "1 gallon 2—for—1",
    "1 gallon 2−for−1",   # U+2212 MINUS SIGN
    "1 gallon 2 for 1",
    "1 gallon 2for1",
    "3 quart 3 for $20",
    "1 gallon 2 for $50",
    "1 gallon Two for One",
    "1 gallon 2FOR1",
    "1 gallon 2 for the price of 1",
    "1 gallon 3/$20",
    # buy-N-get-M
    "2-3 feet Buy 2 Get 1 Free",
    "2-3 feet Buy 2, get 1 free",
    "1-2 feet - Price $94.95 - Buy 1, Get 1 50% Off",
]

# Text the site must keep publishing. Every match here is a price cell blanked
# out on the live site for no reason.
NOT_BUNDLE_TEXT = [
    "1-2 feet - Price $94.95",
    "3 gallon - Price $114.95",
    # "FORM" contains "for"; "Forsythia" starts with it
    "4-5 FT TREE FORM / 1 Plant(s) | Ships Year-Round",
    "#3 Container - Tree Form",
    "Forsythia Lynwood Gold",
    "1 GALLON - 2-4 FT / 1 Plant(s) | Ships Year-round",
    "0.65 Gallon / Ship Week 21 (May 18th – May 22nd)",
    "2-3 Feet (One Gallon)",
    "Bartlett Pear Semi-Dwarf Ultra Supreme XL Growbag",
    "Single Stem Tree / #3 Container | 4-5 ft",
    "6-7 feet Jumbo",
    "Double Knock Out® Rose",
    "Four O'Clock Marvel of Peru",
    # shipping promos are not bundles: the price still buys one plant
    "1 gallon - Price $45.95 - buy 2, get free shipping",
    "1 gallon - buy now, get it before it's gone",
    "1 gallon - Price $45.95, ready for spring",
]


# --------------------------------------------------------------------------
# direction of failure
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", BUNDLE_PHRASINGS)
def test_every_realistic_bundle_phrasing_is_withheld(text):
    assert ShopifyScraper._is_bundle_offer(text) is True, (
        f"{text!r} would publish a multi-plant price as a single-plant price")


@pytest.mark.parametrize("text", NOT_BUNDLE_TEXT)
def test_no_false_positive_on_real_offer_text(text):
    assert ShopifyScraper._is_bundle_offer(text) is False, (
        f"{text!r} is a single-plant offer; withholding it blanks a live cell")


def test_the_shipped_predicate_missed_most_of_these():
    """R2, the control. If a1272f3e's predicate already matched these, the
    parametrised tests above are not measuring the fix."""
    missed = [t for t in BUNDLE_PHRASINGS if not A1272F3E_RE.search(t)]
    assert len(missed) >= 15, (
        f"only {len(missed)}/{len(BUNDLE_PHRASINGS)} were missed before the "
        f"fix — the control has drifted")
    # the forms the red team named specifically
    for named in ("2 Gallon BOGO50", "1 gallon 2-for-1",
                  "1-2 feet - Price $94.95 - Buy1Get1",
                  "1-2 feet - Price $94.95 - Buy&nbsp;1,&nbsp;Get&nbsp;1",
                  "1-2 feet - Price $94.95 - Buy&amp;nbsp;1,&amp;nbsp;Get&amp;nbsp;1"):
        assert named in missed, (
            f"{named!r} was already matched before the fix")


def test_a_raw_nbsp_character_already_matched_but_the_entity_did_not():
    """Worth pinning, because it is the one place the red team report is
    imprecise and someone will re-derive it. Python's ``\\s`` is
    unicode-aware, so a LITERAL U+00A0 already satisfied ``\\bbuy\\s+``.
    What never worked is the ENTITY a theme actually emits, because the
    predicate read RAW html. Both must match now."""
    literal = "1-2 feet - Price $94.95 - Buy\u00a01,\u00a0Get\u00a01"
    entity = "1-2 feet - Price $94.95 - Buy&nbsp;1,&nbsp;Get&nbsp;1"
    assert A1272F3E_RE.search(literal), "the raw character already matched"
    assert not A1272F3E_RE.search(entity), "the entity is what leaked"
    assert ShopifyScraper._is_bundle_offer(literal)
    assert ShopifyScraper._is_bundle_offer(entity)


# --------------------------------------------------------------------------
# entity decoding
# --------------------------------------------------------------------------

def test_entities_are_decoded_before_matching():
    assert ShopifyScraper._normalize_offer_text("Buy&nbsp;1,&nbsp;Get&nbsp;1") == \
        "Buy 1, Get 1"


def test_double_encoded_entities_are_decoded_too():
    """Not hypothetical: the cached corpus holds "Today&amp;#x27;s
    announcements", which needs two passes."""
    assert ShopifyScraper._normalize_offer_text("Today&amp;#x27;s") == "Today's"
    assert ShopifyScraper._is_bundle_offer("Buy&amp;#x20;1,&amp;#x20;Get&amp;#x20;1")


def test_decoding_terminates_on_a_pathological_entity_chain():
    """Bounded loop, not `while decoded != s`. A crafted "&amp;amp;amp;..."
    must not spin inside a scrape of 102 plants x 7 retailers."""
    s = "&" + "amp;" * 500 + "nbsp;"
    out = ShopifyScraper._normalize_offer_text(s)
    assert isinstance(out, str)


def test_normalizing_cannot_invent_a_marker():
    """Decoding only turns entities into characters. Text with no bundle
    marker must not acquire one."""
    for text in NOT_BUNDLE_TEXT:
        assert not ShopifyScraper._is_bundle_offer(
            text.replace(" ", "&nbsp;").replace("-", "–"))


def test_none_and_empty_are_not_bundles():
    assert ShopifyScraper._is_bundle_offer(None) is False
    assert ShopifyScraper._is_bundle_offer("") is False


def test_unicode_dashes_are_folded_to_a_plain_hyphen():
    """Directly, not only through the phrasings above: a mutation run showed
    that removing the fold left the whole suite green, because the buy/get
    branch happens to accept any non-word separator. The N-for-M branch does
    not, so "2–for–1" is what the fold is actually load-bearing for."""
    assert ShopifyScraper._normalize_offer_text("2–for–1") == "2-for-1"
    assert ShopifyScraper._normalize_offer_text("2—for—1") == "2-for-1"
    assert ShopifyScraper._normalize_offer_text("2−for−1") == "2-for-1"


def test_invisible_characters_cannot_break_a_marker_apart():
    """Zero-width characters are invisible to a shopper, so a marker split by
    one still reads as a bundle and must still be withheld.

    The three cases below are the ones that actually need _INVISIBLE: a
    zero-width space INSIDE a token. A mutation run showed that a ZWSP in a
    separator position survives anyway, because `\\W{0,3}` already accepts it
    — so those would not have tested the stripping at all.
    """
    for text in ("3 gallon B\u200b1G1",        # inside B1G1
                 "3-4' BO\u200bGO",            # inside BOGO
                 "1 gallon 2\u200bfor\u200b1"):  # inside 2-for-1
        assert ShopifyScraper._is_bundle_offer(text), repr(text)


def test_for_must_not_be_glued_to_letters():
    """What `for(?![a-z])` buys, and what it costs, both pinned.

    Without the lookahead, "for" glued to a following word can still complete
    the N-for-M branch whenever that word starts with "one" or "two" — so a
    size string like "2 Fortwo Special" would blank a live price cell. With
    it, the branch also declines "2forone", a bundle phrasing no retailer in
    this corpus writes (they write "2for1", "2 for 1" or "Two for One", all
    of which DO match). That trade is deliberate: this branch is the one with
    the widest false-positive surface, and a wrongly blanked cell is the cost
    of getting it wrong in the other direction.
    """
    assert ShopifyScraper._is_bundle_offer("1 gallon 2 Fortwo Special") is False
    assert ShopifyScraper._is_bundle_offer("Euonymus fortunei 2 gallon") is False
    assert ShopifyScraper._is_bundle_offer("2 Forsythia 1 gallon") is False
    # the forms that must still be caught
    for text in ("1 gallon 2for1", "1 gallon 2 for 1", "1 gallon Two for One"):
        assert ShopifyScraper._is_bundle_offer(text), repr(text)


# --------------------------------------------------------------------------
# the live-corpus false-positive control
# --------------------------------------------------------------------------

def _distinct_raw_sizes():
    pairs, rows = set(), 0
    for f in sorted((ROOT / "data" / "prices").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            rec = json.loads(line)
            rid = rec.get("retailer_id", "")
            for _tier, v in (rec.get("sizes") or {}).items():
                if isinstance(v, dict) and v.get("raw_size"):
                    pairs.add((rid, v["raw_size"]))
    return rows, pairs


def _plant_strings():
    data = json.loads((ROOT / "data" / "plants.json").read_text(encoding="utf-8"))
    plants = data["plants"] if isinstance(data, dict) and "plants" in data else data
    out = set()
    for p in plants:
        for key in ("name", "common_name", "botanical", "botanical_name",
                    "scientific_name", "title", "slug", "id"):
            v = p.get(key)
            if isinstance(v, str) and v:
                out.add(v)
        for key in ("aliases", "alt_names", "search_terms", "synonyms"):
            v = p.get(key)
            if isinstance(v, list):
                out.update(x for x in v if isinstance(x, str) and x)
    return out


def test_no_false_positives_over_every_raw_size_in_the_corpus():
    """The whole published corpus is the control for "wider". Each match here
    is a size tier that would stop being published site-wide."""
    rows, pairs = _distinct_raw_sizes()
    assert len(pairs) >= 200 and rows >= 60000, (
        f"corpus shrank to {len(pairs)} distinct raw_size over {rows} rows — "
        f"a control that measures nothing is worse than none")
    hits = sorted({rs for _r, rs in pairs if ShopifyScraper._is_bundle_offer(rs)})
    assert hits == [], (
        f"{len(hits)} of {len(pairs)} distinct raw_size values would now be "
        f"withheld: {hits[:10]}")


def test_no_false_positives_over_every_plant_name():
    names = _plant_strings()
    assert len(names) >= 400, f"only {len(names)} plant strings — control too thin"
    hits = sorted(n for n in names if ShopifyScraper._is_bundle_offer(n))
    assert hits == [], f"{len(hits)} of {len(names)} plant strings match: {hits[:10]}"


def test_quantity_labels_are_still_told_apart_from_bundles():
    """Spring Hill writes "1 Plant(s)" on every variant it sells. If a plant
    COUNT were ever mistaken for a bundle marker the retailer goes dark."""
    for text in ("1 GALLON / 1 Plant(s) | Ships in Spring",
                 "1-2 FT / 1 Plant(s) | Ships Year-Round"):
        assert ShopifyScraper._is_bundle_offer(text) is False
