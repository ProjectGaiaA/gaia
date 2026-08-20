"""A literal, hand-checked label for every size tier the live corpus holds.

Why a table of literals and not a sweep.

The pre-existing sweep in `test_size_tier_display.py` asks "does this label
look translated?" — it recomputes the answer from the same code it is
judging, so a formatter that is uniformly wrong passes it. That is how A-24
survived: `get_size_label('2-4ft')` returned `'2 4Ft'`, which is not the tier
id, contains no `multistem`/`bareroot`, and sailed through every shape check
in the repo while shipping a label worse than the ad-hoc template chain it
was meant to replace.

So every string below was read off the retailer's own `raw_size` and typed
in by hand. Nothing here calls `get_size_label`, `normalize_size_tier`,
`_dimension_label`, `SIZE_TIER_LABELS` or `_TIER_SUFFIX_LABELS` to produce an
expectation. The only thing this file borrows from `build` is the function
under test.

`test_table_covers_every_live_tier` is the second half of the guard: a tier
key that appears in `data/prices/*.jsonl` and is not in the table below fails
the suite and raises a CI alarm until somebody chooses a label for it.

It is an alarm, NOT a gate. The nightly workflow runs pytest under `set +e`
and publishes regardless; a failure here only feeds the post-publish alert.
An unlabelled tier can still reach a visitor — this test guarantees somebody
is told, not that the page is held back.
"""

import json
import os

import pytest

import build

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES_DIR = os.path.join(REPO, "data", "prices")


# tier id -> the exact string a visitor must see.
# The comments name the retailer wording that justifies each choice.
LIVE_TIER_LABELS = {
    # --- Proven Winners Direct: "0.65 Gallon". A-24: shipped "0 65 Gallon".
    "0-65-gallon":             "0.65 Gallon",
    # --- Height tiers. The scraper carries the range hyphen into the id.
    "1-2ft":                   "1-2 ft",
    "2-3ft":                   "2-3 ft",
    # A-24: shipped "2 4Ft". Spring Hill's own wording is "2-4 FT".
    "2-4ft":                   "2-4 ft",
    "3-4ft":                   "3-4 ft",
    "4-5ft":                   "4-5 ft",
    "5-6ft":                   "5-6 ft",
    "6-7ft":                   "6-7 ft",
    # --- Height tiers carrying a qualifier.
    "1-2ft-multistem":         "1-2 ft Multi-Stem",
    "2-3ft-multistem":         "2-3 ft Multi-Stem",
    "3-4ft-multistem":         "3-4 ft Multi-Stem",
    "4-5ft-multistem":         "4-5 ft Multi-Stem",
    "5-6ft-multistem":         "5-6 ft Multi-Stem",
    "6-7ft-multistem":         "6-7 ft Multi-Stem",
    # FGT's heavier grade at the same nominal height — a different product.
    "6-7ft-jumbo":             "6-7 ft Jumbo",
    # --- Spring Hill FIELD inch spans, and their DORMANT counterparts.
    "12-18in":                 '12-18"',
    "18-24in":                 '18-24"',
    "24-36in":                 '24-36"',
    "36-48in":                 '36-48"',
    "48-54in":                 '48-54"',
    "12-18in-bareroot":        '12-18" Bare Root',
    "18-24in-bareroot":        '18-24" Bare Root',
    "24-36in-bareroot":        '24-36" Bare Root',
    "36-48in-bareroot":        '36-48" Bare Root',
    "48-54in-bareroot":        '48-54" Bare Root',
    # --- Inch pots.
    "3inch":                   '3" Pot',
    "4inch":                   '4" Pot',
    "6inch":                   '6" Pot',          # PlantingTree "6 Inch Pot"
    # FGT "6 inch" / PlantingTree "6 Inch" — no "Pot" in the retailer's words.
    # A-24: shipped "6 Inch", the only inch tier not using the inch mark.
    # Still a SEPARATE id from `6inch`; collapsing the two is A-11/A-29.
    "6-inch":                  '6"',
    "3inch-bareroot":          '3" Bare Root',    # Spring Hill 'DORMANT 3"'
    # Spring Hill 'DORMANT 2.5" POT'. "." is carried as "-" in tier ids.
    "2-5inch-bareroot":        '2.5" Bare Root',
    # Spring Hill '2.5" POT'. A-24: shipped "2 5 Pot".
    "2-5-pot":                 '2.5" Pot',
    # --- Quart and gallon containers.
    "quart":                   "Quart",
    "2quart":                  "2 Quart",
    "3quart":                  "3 Quart",
    "1gal":                    "1 Gallon",
    "2gal":                    "2 Gallon",
    "3gal":                    "3 Gallon",
    "5gal":                    "5 Gallon",
    "7gal":                    "7 Gallon",
    "3gal-multistem":          "3 Gallon Multi-Stem",
    # --- Bare-root / dormant grades (Spring Hill).
    "bareroot":                "Bare Root",
    "jumbo-bareroot":          "Jumbo Bare Root",
    "premium-bareroot":        "Premium Bare Root",
    # --- Stark Bros rootstock grades.
    "dwarf":                   "Dwarf",
    "semi-dwarf":              "Semi-Dwarf",
    "supreme":                 "Supreme",
    "standard":                "Standard",
    "ultra-supreme":           "Ultra Supreme",
    "semi-dwarf-potted":       "Semi-Dwarf (Potted)",
    # Stark Bros brands it "EZ Start", both letters capital.
    "dwarf-ez-start":          "Dwarf EZ Start",
    "semi-dwarf-ez-start":     "Semi-Dwarf EZ Start",
    "supreme-ez-start":        "Supreme EZ Start",
    # A-24: shipped "Standard Ez Start" — the only one of the four missing a
    # hand-written entry, and the lowercase "z" is what gave it away.
    "standard-ez-start":       "Standard EZ Start",
    # --- Everything else.
    "starter-plug":            "Starter Plug",    # PlantingTree "Starter Plug"
    "default":                 "Best Available",
    # NOT size tiers. Stark Bros variant titles that are the product name, so
    # the tier id became the plant handle. The label is honest about what the
    # id says; the defect is upstream in the scraper, not in this function.
    # Neither is in any retailer's latest entry — history only.
    "patriot-blueberry":       "Patriot Blueberry",
    "pink-lemonade-blueberry": "Pink Lemonade Blueberry",
}


# Tier shapes no plant carries today, pinned so the general rules that make
# the table above work are not silently narrowed to the ids that exercise them.
FUTURE_TIER_LABELS = {
    "7-8ft":                   "7-8 ft",
    "8-9ft":                   "8-9 ft",
    "8-10ft":                  "8-10 ft",          # no hand-written entry
    "10gal":                   "10 Gallon",
    "15gal":                   "15 Gallon",
    "1-5-gallon":              "1.5 Gallon",
    "3-5-pot":                 '3.5" Pot',
    # Step 9 of the scraper's _normalize_size slugifies any title it does
    # not recognise, so BOTH '2.5 Inch' and '12-18 Inch' arrive here as
    # `<digits>-<digits>-inch` and only the digit COUNT tells a decimal
    # from a range. Reading `12-18-inch` as 12.18" is not merely ugly, it
    # is a false size claim, so the two-or-more-digit form is a span.
    "12-18-inch":              '12-18"',
    "18-24-inch":              '18-24"',
    # Single digits either side: decimal. Grounded in the live corpus —
    # Spring Hill's 'DORMANT 2.5" POT' is already the tier `2-5inch`.
    "2-5-inch":                '2.5"',
    # Genuinely ambiguous: Step 9 collapses '1.2 Inch' and '1-2 Inch' to
    # one id. Pinned to the decimal reading for consistency with the line
    # above; if a retailer ever ships a 1-2 inch RANGE the scraper must
    # separate them upstream, because this function cannot.
    "1-2-inch":                '1.2"',
    "quart-multistem":         "Quart Multi-Stem",
    "2gal-treeform":           "2 Gallon Tree Form",
    "4-5ft-treeform":          "4-5 ft Tree Form",
    "ultra-supreme-ez-start":  "Ultra Supreme EZ Start",
    "dwarf-bareroot":          "Dwarf (Bare Root)",
    "semi-dwarf-bareroot":     "Semi-Dwarf (Bare Root)",
    "supreme-bareroot":        "Supreme (Bare Root)",
    "dwarf-potted":            "Dwarf (Potted)",
    "potted":                  "Potted",
    "bulb":                    "Bulb",
}


@pytest.mark.parametrize("tier,expected", sorted(LIVE_TIER_LABELS.items()))
def test_live_tier_renders_its_pinned_label(tier, expected):
    assert build.get_size_label(tier) == expected


@pytest.mark.parametrize("tier,expected", sorted(FUTURE_TIER_LABELS.items()))
def test_unseen_tier_shape_renders_its_pinned_label(tier, expected):
    assert build.get_size_label(tier) == expected


def _corpus_tier_ids():
    """Every tier key any price entry has ever carried, canonicalised.

    Only the KEY SET comes from build; every expected STRING above is a
    literal. This is a coverage guard, not an oracle.
    """
    tiers = set()
    files = [f for f in os.listdir(PRICES_DIR) if f.endswith(".jsonl")]
    assert len(files) > 90, f"price corpus too small to prove anything: {len(files)}"
    for fn in files:
        with open(os.path.join(PRICES_DIR, fn), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                for raw in (json.loads(line).get("sizes") or {}):
                    tiers.add(build.normalize_size_tier(raw))
    return tiers


def test_table_covers_every_live_tier():
    """A tier key nobody has chosen a label for must not reach a visitor."""
    corpus = _corpus_tier_ids()
    missing = sorted(corpus - set(LIVE_TIER_LABELS))
    assert not missing, (
        f"{len(missing)} of {len(corpus)} tier ids in data/prices carry no "
        f"pinned label: {missing}. Read the retailer's raw_size, choose the "
        f"exact string a visitor should see, and add it to LIVE_TIER_LABELS."
    )
    stale = sorted(set(LIVE_TIER_LABELS) - corpus)
    assert not stale, (
        f"{len(stale)} pinned tier ids are no longer anywhere in data/prices: "
        f"{stale}. If that is intended, move them to FUTURE_TIER_LABELS."
    )


def test_no_pinned_dimension_label_is_a_title_cased_tier_id():
    """The A-24 signature, asserted against the literals rather than the code.

    Every one of the six tiers A-24 named carries a digit, and every one of
    them shipped `tier.replace('-', ' ').title()` verbatim: `2 4Ft`,
    `0 65 Gallon`, `2 5 Pot`, `6 Inch`. A word-only id like `standard` or
    `quart` title-cases to its correct label by coincidence, so the check is
    scoped to ids that name a dimension.
    """
    offenders = [
        tier for tier, label in LIVE_TIER_LABELS.items()
        if any(ch.isdigit() for ch in tier)
        and label == tier.replace("-", " ").title()
    ]
    assert not offenders, (
        f"pinned labels that are just the tier id title-cased: {offenders}"
    )
