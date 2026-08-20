"""Link-correctness invariants for data/handle_maps.json and data/plants.json.

The owner's three priorities are price right, size right, LINK right. These
tests pin the third against the specific ways it has already broken. Each one
fails if the corresponding fix is reverted.

Measured 2026-08-14 offline against the built `site/` at `a1272f3e`: 398
`price-link` anchors inside the `table-wrapper desktop-prices` blocks of
`site/plants/*.html`, 302 distinct hrefs, 168 distinct product URLs.

Every claim in this file is sourced to a file in this repo — `data/*.json`,
the built `site/`, or `UCP_API_RUNBOOK.md`. Claims from live retailer requests
were removed: nothing in this repo persists a request log, so they could not
be re-derived and were being taken on trust. Where a live claim contradicted
the runbook, the runbook won. If you add a claim here, name the file it came
from.
"""

import collections
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
HANDLE_MAPS_PATH = DATA_DIR / "handle_maps.json"
PLANTS_PATH = DATA_DIR / "plants.json"

# build.py globs article markdown with exactly this pattern (ARTICLES_DIR is
# the repo root) and rewrites bare `/plants/<id>` hrefs to `/plants/<id>.html`.
GUIDE_MD_GLOB = "[0-9][0-9]-*.md"


@pytest.fixture(scope="module")
def handle_maps():
    with open(HANDLE_MAPS_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def plants():
    with open(PLANTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def plants_by_id(plants):
    return {p["id"]: p for p in plants}


# --- one handle must never serve two different plants ---------------------


def test_no_retailer_handle_is_claimed_by_two_plants(handle_maps):
    """Two plant ids mapping to ONE retailer handle publish the same product
    URL on two different plant pages.

    This is how the generic "Encore Azalea" page came to publish the exact
    two PlantingTree links as the `autumn-royalty-encore-azalea` page: both
    ids mapped to the `autumn-royalty-encore-azalea` handle. A visitor
    comparing "Encore Azalea" was being shown one named cultivar's prices
    under the series name.
    """
    collisions = []
    for retailer_id, mapping in handle_maps.items():
        inverse = collections.defaultdict(list)
        for plant_id, handle in mapping.items():
            inverse[handle].append(plant_id)
        for handle, plant_ids in inverse.items():
            if len(plant_ids) > 1:
                collisions.append((retailer_id, handle, sorted(plant_ids)))
    assert collisions == [], (
        "One retailer handle is mapped from more than one plant id, so the "
        "same product URL will be published on multiple plant pages: "
        f"{collisions}"
    )


# --- the generic Encore Azalea series page --------------------------------


def test_encore_azalea_series_page_is_inactive(plants_by_id):
    """`encore-azalea` is the Encore *series*, not a cultivar.

    Both handles it carried at `a1272f3e` were named cultivars, and they were
    two DIFFERENT cultivars (PlantingTree: `autumn-royalty-encore-azalea` /
    FGT: `azalea-encore-autumn-kiss-shrub`), so the two retailer columns on
    that page were comparing two different plants. The page is deactivated
    rather than filled with that comparison. Re-activating it requires a
    genuinely generic retailer listing to point at; whether any retailer
    publishes one has not been established from anything in this repo.
    """
    plant = plants_by_id["encore-azalea"]
    assert plant.get("active") is False, (
        "encore-azalea is a series, not a cultivar. Re-activating it "
        "republishes a page that compares different named cultivars as if "
        "they were the same plant."
    )


def test_encore_azalea_has_no_cultivar_specific_handles(handle_maps):
    """The series id must not be mapped to any cultivar product.

    It previously mapped to `autumn-royalty-encore-azalea` (PlantingTree) and
    `azalea-encore-autumn-kiss-shrub` (FGT) — a THIRD cultivar, and one that
    is not a plant in plants.json at all. Those two mappings are what made
    the series page a cross-cultivar comparison.
    """
    mapped_in = {r: m["encore-azalea"] for r, m in handle_maps.items()
                 if "encore-azalea" in m}
    assert mapped_in == {}, (
        "encore-azalea must map to no retailer handle: every candidate is a "
        f"specific named cultivar. Found: {mapped_in}"
    )


def test_named_encore_cultivars_remain_active_and_mapped(handle_maps, plants_by_id):
    """Deactivating the series page must not take the honest pages with it.

    The three named cultivars carry the real per-cultivar comparisons and
    must keep publishing.
    """
    for plant_id in (
        "autumn-royalty-encore-azalea",
        "autumn-twist-encore-azalea",
        "autumn-angel-encore-azalea",
    ):
        assert plants_by_id[plant_id].get("active", True) is not False, (
            f"{plant_id} is a real cultivar page and must stay active"
        )
        mapped = [r for r, m in handle_maps.items() if plant_id in m]
        assert mapped, f"{plant_id} lost every retailer mapping"


# --- FGT region-locked handles --------------------------------------------


def test_sunshine_blue_repoint_is_held_pending_a_measured_price(handle_maps):
    """HELD ON PURPOSE. Do not repoint this handle without measuring first.

    `sunshine-blue-blueberry` is mapped at FGT's California mirror
    `sunshine-blue-blueberry-bush-ca`. `UCP_API_RUNBOOK.md` (section 12,
    "Three live defects found on 2026-08-13") names it as one of three CA
    mirror handles and records that all three national twins exist, so
    repointing it at `sunshine-blue-blueberry-bush` is a plausible fix.

    It is NOT applied yet, because the published PRICE outcome has never been
    measured. `data/last_manifest.json` records exactly one live FGT cell for
    this plant, `sunshine-blue-blueberry:fast-growing-trees {"2gal": 90.95}` —
    the ONLY live price on the page. A repoint has two possible outcomes and
    both change or destroy that cell:

      * the national product carries different size tiers, so the 2 Gallon
        cell is replaced by sizes at prices nobody has read; or
      * no tier survives, the page drops to zero offers and goes `noindex`.

    WHAT MUST BE MEASURED BEFORE THIS LANDS (all of it, from one scrape):
      1. the national handle's actual size tiers and prices;
      2. the resulting published cells for `sunshine-blue-blueberry` after a
         full build, diffed against the `-ca` cells above;
      3. that the page still publishes at least one offer (not `noindex`).

    Until then the shipped `-ca` value stands. It is a known defect with a
    known price, which is preferable to an unknown one.
    """
    handle = handle_maps["fast-growing-trees"]["sunshine-blue-blueberry"]
    assert handle == "sunshine-blue-blueberry-bush-ca", (
        "sunshine-blue-blueberry was repointed off the `-ca` mirror. That "
        "changes the only live price on the page. Read this test's docstring "
        f"and measure the three items listed there first. Got: {handle}"
    )


def test_duke_blueberry_stays_on_the_or_handle(handle_maps):
    """Pin `duke-blueberry-bush-or` as the shipped handle.

    NOT a claim that `-or` is canonical. No file in this repo records a live
    check of either the `-or` handle or a `duke-blueberry-bush` national twin,
    and `UCP_API_RUNBOOK.md`'s CA-mirror defect names only the three `-ca`
    handles, not this one. What is committed is that `-or` is the handle
    shipped at `a1272f3e` and that `data/last_manifest.json` carries a live
    cell from it (`duke-blueberry:fast-growing-trees {"1gal": 51.95}`).

    This test therefore pins the status quo: changing it is a PRICE change and
    needs a measured before/after, the same as sunshine-blue above.
    """
    handle = handle_maps["fast-growing-trees"]["duke-blueberry"]
    assert handle == "duke-blueberry-bush-or", (
        "duke-blueberry moved off the shipped `-or` handle. That is a price "
        f"change and needs a measured before/after. Got: {handle}"
    )


def test_no_new_unreviewed_region_suffixed_fgt_handle_appears(handle_maps):
    """Fail when a NEW region-suffixed FGT handle appears, not when one leaves.

    Region codes seen in FGT variant labels, per `UCP_API_RUNBOOK.md`: CA, FL,
    GA, OR, SC, TX. A handle carrying one of those suffixes may be a
    region-restricted mirror that publishes a price a general visitor cannot
    buy at. Each one has to be reviewed before it ships.

    The four below are the reviewed set. Reviewed is NOT a clean bill of
    health: the three `-ca` ones are a documented OPEN defect.
    `UCP_API_RUNBOOK.md` (section 12, defect 1) records: "Three handles in
    `handle_maps.json` point at FGT's California mirror pages ... 7 published
    cells affected, 5 of which happen to be correct today." That is 2 published
    cells known WRONG. An earlier version of this docstring asserted the
    opposite — that the published prices "match the national catalog to the
    cent" — sourced to a live check that persists in no artifact. The runbook
    is committed and specific, so the runbook is what this test records.

    Because the `-ca` entries are open defects, the assertion is a SUBSET
    check: removing one (i.e. fixing it) must not fail this test, only adding
    an unreviewed one.
    """
    reviewed = {
        # (plant_id, handle). The three `-ca` entries are an open defect
        # awaiting a measured repoint; see UCP_API_RUNBOOK.md section 12.
        # `-or` is a status-quo pin, not a defect claim either way.
        ("stella-cherry-tree", "stella-cherry-tree-ca"),
        ("eastern-redbud", "eastern-redbud-tree-form-ca"),
        ("sunshine-blue-blueberry", "sunshine-blue-blueberry-bush-ca"),
        ("duke-blueberry", "duke-blueberry-bush-or"),
    }
    region_suffixes = ("-ca", "-fl", "-ga", "-or", "-sc", "-tx")
    fgt = handle_maps["fast-growing-trees"]
    suffixed = {
        (plant_id, handle)
        for plant_id, handle in fgt.items()
        if handle.endswith(region_suffixes)
    }
    unreviewed = suffixed - reviewed
    assert unreviewed == set(), (
        "A region-suffixed FGT handle appeared that nobody has reviewed. It "
        "may be a region-restricted mirror publishing a price a general "
        "visitor cannot buy at. Check it against the national twin and record "
        f"the result before it ships. Found: {sorted(unreviewed)}"
    )


# --- every active plant must be able to produce an honest page ------------


def test_every_active_plant_has_at_least_one_retailer_handle(handle_maps, plants):
    """An active plant with no mapping publishes an empty comparison page.

    Deactivating a plant is the documented way to remove it (it drops out of
    product pages, the sitemap and category pages while the data is kept);
    stripping its mappings but leaving it active is not.
    """
    mapped_plant_ids = {p for m in handle_maps.values() for p in m}
    orphaned = [
        p["id"]
        for p in plants
        if p.get("active", True) is not False and p["id"] not in mapped_plant_ids
    ]
    assert orphaned == [], (
        "Active plants with no retailer handle at all would render a price "
        f"table with no rows: {orphaned}"
    )


# --- guide markdown must not link to a page the build will not produce ----


def _guide_plant_links():
    """Yield (guide_filename, line_no, plant_id) for every /plants/ link.

    Covers both markdown `](/plants/x)` and raw `href="/plants/x"`, with or
    without the `.html` that build.py appends, and tolerates an anchor or
    query suffix.
    """
    pattern = re.compile(r'[("\']/plants/([A-Za-z0-9_-]+)(?:\.html)?(?=[)"\'#?])')
    for md_path in sorted(REPO_ROOT.glob(GUIDE_MD_GLOB)):
        text = md_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in pattern.finditer(line):
                yield md_path.name, line_no, match.group(1)


def test_guide_markdown_never_links_to_a_page_that_will_not_be_built(plants_by_id):
    """A guide link to a missing or inactive plant ships a dangling link.

    `build.py` builds `site/plants/<id>.html` only for plants where
    `active` is not False (`plants = [p for p in all_plants if
    p.get("active", True)]`), but guide markdown is copied through with its
    hrefs rewritten and is never checked against that set. So deactivating a
    plant, or renaming its id, silently turns every guide link to it into a
    404 — and no existing test notices.

    This is deliberately general: it fails for ANY guide, ANY plant id. It is
    not a check for one known-bad link.
    """
    links = list(_guide_plant_links())

    # Guard the guard: if the regex or the glob above ever stops matching,
    # everything below passes vacuously. 45 links across the 11 guides at this
    # commit; `grep -o "/plants/[^)]*" [0-9][0-9]-*.md | wc -l` agrees exactly.
    assert len(links) >= 40, (
        f"The guide link scanner found only {len(links)} links, so this test "
        "is passing vacuously. Fix the scanner before trusting it."
    )

    dangling = []
    for guide, line_no, plant_id in links:
        plant = plants_by_id.get(plant_id)
        if plant is None:
            reason = "no such plant in plants.json"
        elif plant.get("active", True) is False:
            reason = 'plant is "active": false, so no page is built'
        else:
            continue
        dangling.append(f"{guide}:{line_no} -> /plants/{plant_id}.html ({reason})")

    assert dangling == [], (
        "Guide markdown links to plant pages the build will not produce, so "
        "these ship as 404s:\n  " + "\n  ".join(dangling)
    )
