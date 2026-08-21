"""Audit D2' — the four clauses, the age gate, and the corpus replay.

The scrape-time predicate in scrapers/shopify.py reads a LABEL. This audit
reads a PRICE, against the retailer's own catalog capture committed at
data/regional_reference/fast-growing-trees.json. That makes it the independent
oracle (nightly_audits.py RULE ZERO) and the thing to believe when the two
disagree — which they measurably do, in both directions.

WHERE THE NUMBERS COME FROM, AND WHY NOT FROM data/prices/
----------------------------------------------------------
The replay at the bottom of this file is the calibration (R9): every number in
the module docstrings is reproduced here, so a change that quietly moves one
turns this suite red.

It is reproduced against a FROZEN SNAPSHOT at tests/fixtures/regional_audit/,
not against data/prices/. That is not a convenience; it is the difference
between a test and a tripwire. The bot appends to data/prices/ twice a day, so
any expectation that is a census of the live corpus is stale within hours —
and it fails in CI, on the production scrape run, for a reason that is not a
defect. scrape.yml already says this out loud: "Tests are fixture-based: they
validate CODE, not this run's data."

So the rule in this file is:

  * A number that describes a CORPUS is pinned against the frozen snapshot,
    which carries its as-of commit in MANIFEST.json. Refreshing it is a
    deliberate act with a diff.
  * A claim about the audit's BEHAVIOUR is written as an invariant — a
    property that holds for any corpus state — and exercised over a synthetic
    corpus built in the test, so it never depends on what tonight's scrape
    happened to find.
  * A number that describes the live tip is not asserted here at all. The
    audit prints it; that is where it belongs.
"""

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.audit_regional_render import (
    EXIT_ALARM,
    main,
    EXIT_OK,
    MAX_REFERENCE_AGE_DAYS,
    evaluate_row,
    load_reference,
    reference_age_days,
    run,
)

REPO = Path(__file__).parent.parent
DATA_DIR = REPO / "data"
REFERENCE = DATA_DIR / "regional_reference" / "fast-growing-trees.json"

# The frozen corpus snapshot. Same on-disk shape as data/ (a prices/ directory
# of .jsonl), so run() drives it through exactly the same loader.
FIXTURES = REPO / "tests" / "fixtures" / "regional_audit"
FIXTURE_CORPUS = FIXTURES / "corpus"
FIXTURE_MANIFEST = FIXTURES / "MANIFEST.json"
PLANTING_TREE_LABELS = FIXTURES / "planting_tree_size_labels.json"

# The capture's own instant, READ OFF THE REFERENCE rather than typed in.
# Every test that wants the price clauses ENABLED ages the reference against a
# fixed point just after it, so the suite neither fails on a calendar boundary
# nor needs editing when the reference is re-captured.
#
# The literal instant IS still pinned, once, in
# test_reference_is_the_expected_capture below. That split is deliberate: if
# this constant were also a literal, a re-capture would fail a dozen tests for
# one reason; if nothing were literal, a corrupted or substituted reference
# could satisfy the whole suite by describing itself.
CAPTURE_AT = datetime.fromisoformat(
    json.loads(REFERENCE.read_text(encoding="utf-8"))
    ["provenance"]["captured_at"].replace("Z", "+00:00")
)
FRESH = CAPTURE_AT + timedelta(hours=1)
STALE = CAPTURE_AT + timedelta(days=MAX_REFERENCE_AGE_DAYS + 1)


@pytest.fixture(scope="module")
def reference():
    return load_reference(REFERENCE)


def _row(sizes, ts="2026-08-20T12:25:00+00:00"):
    return {"retailer_id": "fast-growing-trees", "timestamp": ts, "sizes": sizes}


def _cell(price, was=None):
    return {"price": price, "was_price": was, "available": True}


# The honeycrisp CA catalogue, exactly. test_clause_1 and test_clause_2 prove
# from the reference that this shape fires; the invariant tests below reuse it
# whenever they need a corpus that is GUARANTEED to produce a finding, instead
# of hoping the live tip still has one.
CA_FLIP_SIZES = {"4-5ft": _cell(117.95, 123.95), "5-6ft": _cell(139.95, 146.95)}

# The real national catalogue for the same plant, all six tiers — guaranteed
# clean for the same reason.
NATIONAL_SIZES = {
    "1-2ft": _cell(75.95), "2-3ft": _cell(86.95),
    "3-4ft": _cell(100.95), "4-5ft": _cell(129.95),
    "5-6ft": _cell(153.95), "6-7ft": _cell(183.95),
}


def _corpus(tmp_path, rows_by_plant):
    """Write a synthetic corpus and return its data-dir path."""
    prices = tmp_path / "prices"
    prices.mkdir(exist_ok=True)
    for plant, rows in rows_by_plant.items():
        (prices / f"{plant}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8",
        )
    return tmp_path


def _normalized_sha256(path):
    """sha256 of a file's content with line endings normalised to LF.

    THE HASH MUST NOT DEPEND ON WHO CHECKED THE FILE OUT. core.autocrlf is
    true on Windows and .gitattributes covers only *.jsonl, so this .json
    lands CRLF in a Windows worktree and LF in a Linux one. Hashing the raw
    bytes therefore pins a hash that is true on exactly one platform — which
    is how the pin came to be a Windows-only value that failed every Linux CI
    run. Normalising first pins the CONTENT, which is what provenance is
    actually about, and makes the value equal to the git blob's own sha256.
    """
    return hashlib.sha256(
        Path(path).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()


# --- the frozen snapshot itself --------------------------------------------


def test_the_frozen_snapshot_records_the_commit_it_was_taken_at():
    """A pinned census is only reviewable if you can say what it is a census
    OF. The manifest carries the commit, the reference it was cut against, and
    the reduction rule, so every number below can be re-derived."""
    m = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert len(m["as_of_commit"]) == 40
    assert m["reference_captured_at"] == (
        load_reference(REFERENCE)["provenance"]["captured_at"]
    ), (
        "the snapshot was cut against a different capture than the one "
        "committed. Re-run the regenerate command in MANIFEST.json."
    )
    assert m["reference_raw_capture_sha256_normalized"] == _normalized_sha256(
        REFERENCE.parent / load_reference(REFERENCE)["provenance"]["raw_capture"]
    )
    assert FIXTURE_CORPUS.is_dir() and any(
        (FIXTURE_CORPUS / "prices").glob("*.jsonl")
    )


# --- the reference artifact itself -----------------------------------------


def test_reference_is_committed_and_carries_its_provenance(reference):
    """The audit's baseline must be reviewable in a diff, not a path into
    somebody's scratch directory."""
    prov = reference["provenance"]
    for key in (
        "raw_capture", "raw_capture_sha256", "source", "endpoint",
        "captured_at", "tier_join", "scope",
    ):
        assert prov.get(key), f"provenance is missing {key}"
    assert reference["retailer_id"] == "fast-growing-trees"
    assert reference["schema"] == "gaia.regional_reference.v1"


def test_raw_capture_is_committed_and_matches_its_pinned_hash(reference):
    """PROVENANCE THAT CAN BE CHECKED, not merely asserted.

    The earlier reference recorded a sha256 of a capture that lived outside
    this repo, so the hash proved nothing a reader could verify — there was
    nothing to hash. The raw capture is now committed beside the reference,
    which turns the pin into a real integrity check: edit either file and this
    fails.

    The pin is over LF-NORMALISED content (see _normalized_sha256). The
    previous pin was over the raw worktree bytes, which made it a Windows-only
    value: it passed locally and failed every Linux CI run, because git had
    normalised the blob on checkout. A provenance check that depends on the
    checking machine's line-ending config is not a provenance check.
    """
    raw_path = REFERENCE.parent / reference["provenance"]["raw_capture"]
    assert raw_path.exists(), f"the pinned raw capture is missing: {raw_path}"
    digest = _normalized_sha256(raw_path)
    assert digest == reference["provenance"]["raw_capture_sha256"], (
        "the committed raw capture does not match the sha256 the reference "
        "pins it to. One of the two has been edited; neither can be trusted "
        f"until that is resolved. file={digest} "
        f"pinned={reference['provenance']['raw_capture_sha256']}"
    )


def test_the_pinned_hash_is_the_one_a_linux_checkout_measures(reference):
    """THE CROSS-PLATFORM PROPERTY, ASSERTED RATHER THAN HOPED FOR.

    The whole failure was that Windows and Linux measured different bytes for
    the same committed file. Normalising fixes it, but "we normalised" is not
    evidence — so this pins the consequence: the file's normalised hash equals
    the hash of the LF-only content git actually stores, which is what a Linux
    runner reads back on checkout. If anyone reverts to hashing raw bytes,
    this fails on Windows immediately rather than in CI a day later.
    """
    raw_path = REFERENCE.parent / reference["provenance"]["raw_capture"]
    stored = raw_path.read_bytes().replace(b"\r\n", b"\n")
    assert b"\r\n" not in stored
    assert hashlib.sha256(stored).hexdigest() == _normalized_sha256(raw_path)
    assert reference["provenance"]["raw_capture_sha256"] == _normalized_sha256(
        raw_path
    )


def test_reference_is_the_expected_capture(reference):
    """THE ONE LITERAL ANCHOR. A file must not be able to self-verify.

    Every other test in this module derives its expectations from the
    reference, so that a re-capture does not turn the suite red for a reason
    that is not a defect. That property has a cost: a truncated, stale or
    substituted reference would satisfy all of them, because they would simply
    describe whatever they were given.

    So exactly one test pins the identity of the file we actually reviewed —
    its capture instant, its raw-capture hash, and the prices read off the
    retailer's catalog by hand. Re-capturing REQUIRES editing this test, on
    purpose, which is the point.
    """
    prov = reference["provenance"]
    assert prov["captured_at"] == "2026-08-20T20:15:02Z"
    assert prov["raw_capture_sha256"] == (
        "0de018b3b88a941931fa50c1bf55f15aaee5bf4081b4e04994c8e57853f6d446"
    )
    assert len(reference["plants"]) == 9
    # Hand-read from the capture: the CA 5-6 ft against its national twin, for
    # the two plants whose spread the audit's newest findings turn on. These
    # pairs used to be asserted indirectly, by reading them back out of
    # whatever the live tip happened to be publishing; they belong here, on
    # the artifact they were read from, where a re-capture is what moves them.
    stella = reference["plants"]["stella-cherry-tree"]
    assert stella["regional"]["CA"]["5-6ft"]["price_cents"] == 14695
    assert stella["national"]["5-6ft"]["price_cents"] == 16095
    bing = reference["plants"]["bing-cherry-tree"]
    assert bing["regional"]["CA"]["5-6ft"]["price_cents"] == 15395
    assert bing["national"]["5-6ft"]["price_cents"] == 16895
    blueberry = reference["plants"]["pink-lemonade-blueberry"]
    assert blueberry["regional"]["CA"]["2gal"]["price_cents"] == 4495


def test_reference_names_no_region_of_its_own(reference):
    """Regions come from the DATA, and there are now four of them.

    The first capture held CA and FL. This one holds CA, FL, GA and TX — all
    on meyer-lemon-tree — which is the concrete reason nothing in the audit
    may enumerate a state list.
    """
    regions = {
        r for p in reference["plants"].values() for r in (p.get("regional") or {})
    }
    assert regions == {"CA", "FL", "GA", "TX"}, regions


def test_every_regional_variant_title_carries_its_region_parenthetical(reference):
    """The DURABLE discriminator, as opposed to the vocabulary proxy.

    All 39 region-restricted variants in the capture are titled
    "<size> (<REGION>)". The storefront strips that parenthetical, which is
    exactly why the scraper has to fall back on a spelling heuristic and why
    this audit — reading the catalog, where the parenthetical survives — is
    the thing to believe when the two disagree.
    """
    bad = [
        v["title"]
        for p in reference["plants"].values()
        for region, twins in (p.get("regional") or {}).items()
        for v in twins.values()
        if v and f"({region})" not in v["title"]
    ]
    assert bad == [], bad


def test_extra_products_are_evidence_and_never_audit_input(reference):
    """`extra_products` holds captured products no plant id points at.

    Today that is `sunshine-blue-blueberry-bush`, the NATIONAL twin of the
    handle `test_sunshine_blue_repoint_is_held_pending_a_measured_price` holds
    on the `-ca` mirror. It is captured as evidence for that decision, NOT as
    something to audit: no committed price row is keyed to it, so feeding it
    to the predicate would compare a row to a product it never came from.

    The audit reads `plants` and nothing else. This pins that.
    """
    extra = reference.get("extra_products") or {}
    assert extra, "the capture is expected to carry evidence products"
    assert not (set(extra) & set(reference["plants"])), (
        "an evidence product leaked into the audited plant set"
    )
    _, report = run(FIXTURE_CORPUS, REFERENCE, now=FRESH)
    assert report["reference_total_plants"] == len(reference["plants"]), (
        "extra_products must not inflate the audit's denominator"
    )


# --- the four clauses ------------------------------------------------------


def test_clause_1_price_and_was_price_must_both_match(reference):
    """A regional twin often shares the payable price and differs only in the
    strikethrough — meyer-lemon 2-3 ft is 9895 in BOTH catalogues and only the
    14495 list price separates them. Matching price alone is not enough."""
    ref = reference["plants"]["honeycrisp-apple-tree"]

    good = _row({"4-5ft": _cell(117.95, 123.95), "5-6ft": _cell(139.95, 146.95)})
    assert evaluate_row(ref, good)[0] == "fired"

    # right payable price, wrong was_price
    bad = _row({"4-5ft": _cell(117.95, 129.95), "5-6ft": _cell(139.95, 146.95)})
    assert evaluate_row(ref, bad)[0] == "clean"

    # right was_price, wrong payable price
    bad2 = _row({"4-5ft": _cell(118.95, 123.95), "5-6ft": _cell(139.95, 146.95)})
    assert evaluate_row(ref, bad2)[0] == "clean"


def test_clause_2_tier_set_must_be_equal_not_a_subset(reference):
    """A SUBSET is what an ordinary sold-out day looks like. Only EQUALITY
    says the page rendered one region's catalogue and nothing else."""
    ref = reference["plants"]["honeycrisp-apple-tree"]

    exact = _row({"4-5ft": _cell(117.95, 123.95), "5-6ft": _cell(139.95, 146.95)})
    assert evaluate_row(ref, exact)[0] == "fired"

    # a strict subset of the CA-available set, every price still a CA price
    subset = _row({"5-6ft": _cell(139.95, 146.95)})
    assert evaluate_row(ref, subset)[0] == "clean"

    # a superset: one extra tier CA does not offer
    superset = _row({
        "4-5ft": _cell(117.95, 123.95),
        "5-6ft": _cell(139.95, 146.95),
        "6-7ft": _cell(183.95),
    })
    assert evaluate_row(ref, superset)[0] == "clean"


def test_clause_3_needs_a_national_regional_contrast(reference):
    """Without a tier where the two catalogues disagree, "we published the
    regional price" is a claim the data cannot support.

    Built here rather than found: a plant whose CA and national prices are
    identical at every available tier must NOT fire, however exactly the row
    matches.
    """
    twin = {
        "title": "2-3 ft. (CA)", "price_cents": 8695,
        "list_price_cents": 8695, "available": True,
    }
    national = {
        "title": "2-3 ft.", "price_cents": 8695,
        "list_price_cents": 8695, "available": True,
    }
    ref = {"national": {"2-3ft": national}, "regional": {"CA": {"2-3ft": twin}}}
    row = _row({"2-3ft": _cell(86.95)})
    verdict, detail = evaluate_row(ref, row)
    assert verdict == "clean", detail

    # Move the national price and the same row now fires.
    ref["national"]["2-3ft"] = dict(national, price_cents=9995)
    assert evaluate_row(ref, row)[0] == "fired"


def test_clause_4_an_empty_row_is_not_a_finding_and_not_a_check(reference):
    """A withheld row published nothing, so there is nothing to judge — and it
    must NOT inflate the checked denominator either."""
    ref = reference["plants"]["honeycrisp-apple-tree"]
    assert evaluate_row(ref, _row({}))[0] == "empty"


def test_an_ambiguous_reference_tier_cannot_confirm_anything():
    """Two variants normalising onto one tier are stored as null. Null must
    read as "cannot say", never as agreement."""
    ref = {
        "national": {"2-3ft": {"price_cents": 9995, "available": True}},
        "regional": {"CA": {"2-3ft": None}},
    }
    assert evaluate_row(ref, _row({"2-3ft": _cell(86.95)}))[0] == "clean"


# --- region genericity -----------------------------------------------------


def test_region_is_read_from_the_data_never_hardcoded():
    """FL exists in the committed capture. A CA-only audit is blind to it."""
    fl_twin = {
        "title": "5-6 ft. (FL)", "price_cents": 25895,
        "list_price_cents": 37995, "available": True,
    }
    ref = {
        "national": {"5-6ft": {"price_cents": 30000, "available": True}},
        "regional": {"FL": {"5-6ft": fl_twin}},
    }
    verdict, detail = evaluate_row(ref, _row({"5-6ft": _cell(258.95, 379.95)}))
    assert verdict == "fired"
    assert detail["region"] == "FL", detail


def test_a_region_the_repo_has_never_seen_still_works():
    """The retailer may add one tomorrow. Nothing enumerates a state list."""
    twin = {
        "title": "5-6 ft. (TX)", "price_cents": 11111,
        "list_price_cents": 11111, "available": True,
    }
    ref = {
        "national": {"5-6ft": {"price_cents": 22222, "available": True}},
        "regional": {"TX": {"5-6ft": twin}},
    }
    verdict, detail = evaluate_row(ref, _row({"5-6ft": _cell(111.11)}))
    assert verdict == "fired" and detail["region"] == "TX"


# --- the capture-age hard gate ---------------------------------------------


def test_age_is_measured_from_the_capture(reference):
    assert reference_age_days(reference, now=FRESH) == pytest.approx(1 / 24, abs=1e-3)
    assert reference_age_days(reference, now=STALE) > MAX_REFERENCE_AGE_DAYS


def test_fresh_reference_enables_the_price_clauses(tmp_path):
    """The clauses turn ON inside the window, and the run really does check
    rows rather than skipping them all.

    Driven over a synthetic corpus holding one honest national row: `checked`
    is then 1 BY CONSTRUCTION. Read off data/prices/ it was a coin flip on
    whether tonight's scrape happened to leave a non-empty FGT row at the tip
    — which is a property of the retailer's stock, not of this code.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(NATIONAL_SIZES)]})
    code, report = run(data, REFERENCE, now=FRESH)
    assert report["price_clauses_enabled"] is True
    assert report["reference_stale"] is False
    assert report["checked"] == 1
    assert code == EXIT_OK


def test_stale_reference_disables_the_price_clauses_and_still_alarms(tmp_path):
    """COULD-NOT-VERIFY MUST NOT READ AS CLEAN.

    Past the window the price comparison is no longer evidence — FGT reprices
    within days — so the clauses are disabled. The exit code must then be
    ALARM, not OK, for the same reason nightly_audits.py R10 alarms on a
    collapsed denominator: an audit that goes green because it stopped looking
    also stops anybody else looking.

    Driven over a corpus that WOULD otherwise fire, so "checked == 0" is the
    gate doing its job and not an empty corpus flattering it.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(CA_FLIP_SIZES)]})
    assert run(data, REFERENCE, now=FRESH)[1]["fired"] == 1, (
        "the fixture corpus must fire when fresh, or the stale case proves "
        "nothing"
    )

    code, report = run(data, REFERENCE, now=STALE)

    assert report["price_clauses_enabled"] is False
    assert report["checked"] == 0
    assert report["fired"] == 0
    assert code == EXIT_ALARM, "a stale reference must never exit 0"
    assert any("reference stale, not checked" in a for a in report["alarms"])


def test_stale_gate_boundary_is_the_documented_window(tmp_path):
    """One hour inside the window checks; one day outside does not."""
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(NATIONAL_SIZES)]})
    inside = CAPTURE_AT + timedelta(days=MAX_REFERENCE_AGE_DAYS, hours=-1)
    outside = CAPTURE_AT + timedelta(days=MAX_REFERENCE_AGE_DAYS, hours=1)
    assert run(data, REFERENCE, now=inside)[1]["price_clauses_enabled"] is True
    assert run(data, REFERENCE, now=outside)[1]["price_clauses_enabled"] is False


def test_a_reference_with_no_usable_date_is_stale_not_fresh(tmp_path, reference):
    """Unknown age is not young. The default must fail closed."""
    broken = dict(reference)
    broken["provenance"] = dict(reference["provenance"], captured_at=None)
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    code, report = run(FIXTURE_CORPUS, path, now=FRESH)
    assert report["reference_stale"] is True
    assert code == EXIT_ALARM


def test_a_national_corpus_exits_ok(tmp_path):
    """EXIT_OK must be REACHABLE, or EXIT_ALARM means nothing.

    Every other test here asserts an alarm, and a check that can only ever go
    red is indistinguishable from one that is simply broken. This drives the
    same audit over a corpus holding one honest national row.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(NATIONAL_SIZES)]})
    code, report = run(data, REFERENCE, now=FRESH)
    assert report["checked"] == 1
    assert report["fired"] == 0
    assert report["alarms"] == []
    assert code == EXIT_OK


def test_a_reference_that_can_answer_for_nobody_alarms(tmp_path, reference):
    """R10 — a check that finds nothing may have checked nothing."""
    empty = dict(reference)
    empty["plants"] = {
        p: dict(v, regional={}) for p, v in reference["plants"].items()
    }
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(empty), encoding="utf-8")

    code, report = run(FIXTURE_CORPUS, path, now=FRESH)
    assert report["reference_answerable_plants"] == 0
    assert code == EXIT_ALARM
    assert any("denominator collapsed" in a for a in report["alarms"])


# --- invariants: true of ANY corpus state ----------------------------------


def test_finding_strength_is_decided_by_the_row_capture_gap(tmp_path):
    """`confirmed` vs `lead` is a statement about the ROW's distance from the
    capture, not about which mode the audit was run in.

    This used to be asserted as "the newest rows in data/prices/ are all
    inside the window" — which is a fact about how recently the bot ran, and
    went false the moment tonight's scrape shifted the tip. The property the
    code actually implements is pinned instead, from both sides of the
    boundary, over rows built to sit there.
    """
    inside = (CAPTURE_AT - timedelta(days=1)).isoformat()
    outside = (CAPTURE_AT - timedelta(days=MAX_REFERENCE_AGE_DAYS + 5)).isoformat()
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [
        _row(CA_FLIP_SIZES, ts=outside),
        _row(CA_FLIP_SIZES, ts=inside),
    ]})

    _, report = run(data, REFERENCE, now=FRESH, latest_only=False)
    assert report["fired"] == 2
    strength = {f["timestamp"]: f["strength"] for f in report["findings"]}
    assert strength[inside] == "confirmed"
    assert strength[outside] == "lead"
    assert report["fired_confirmed"] + report["fired_lead"] == report["fired"]


def test_the_mode_ci_runs_reports_no_leads_when_the_tip_is_fresh(tmp_path):
    """The operational claim that used to be a census of data/prices/.

    CI runs latest_only, so it compares the newest row per plant. When that
    row is inside the window every finding is `confirmed` and none is a
    `lead`. Built here rather than found, so it states the rule instead of
    reporting last night's luck — note the STALE row underneath, which would
    have produced a lead had the mode picked it up.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [
        _row(CA_FLIP_SIZES, ts=(CAPTURE_AT - timedelta(days=90)).isoformat()),
        _row(CA_FLIP_SIZES, ts=(CAPTURE_AT - timedelta(hours=8)).isoformat()),
    ]})
    _, report = run(data, REFERENCE, now=FRESH, latest_only=True)
    assert report["fired"] == 1
    assert report["fired_lead"] == 0
    assert report["fired_confirmed"] == report["fired"] == 1


@pytest.mark.parametrize("corpus", ["fixture", "live"])
def test_every_finding_is_internally_consistent(corpus, reference):
    """WHAT A FINDING CLAIMS, CHECKED AGAINST WHAT IT SHOWS — for whatever the
    corpus happens to hold, including nothing.

    A finding says "we published region R's price". That is only true if, at
    every tier it reports, the published price EQUALS R's twin price, and at
    some tier R's price DIFFERS from the national one. Both are re-derived
    here from the reference rather than taken from the finding's own summary.

    This replaces the old test that pinned the six specific prices sitting at
    the live tip. Those numbers described one night's data and were obsolete
    within a day; the property they were standing in for holds forever, and
    holds vacuously when the tip is clean — which is the correct behaviour
    for a run that legitimately fires nothing.
    """
    data = FIXTURE_CORPUS if corpus == "fixture" else DATA_DIR
    _, report = run(data, REFERENCE, now=FRESH, latest_only=False)

    for f in report["findings"]:
        ref = reference["plants"][f["plant"]]
        twins = ref["regional"][f["region"]]
        national = ref["national"]

        assert f["published_cents"] == f["region_cents"], f
        for tier, cents in f["published_cents"].items():
            assert twins[tier]["price_cents"] == cents, (f["plant"], tier)
        assert f["contrast_tiers"], f
        for tier in f["contrast_tiers"]:
            assert national[tier]["price_cents"] != twins[tier]["price_cents"], (
                f["plant"], tier,
            )
        assert set(f["contrast_tiers"]) <= set(f["published_cents"])
        assert f["strength"] in ("confirmed", "lead")


# --- calibration against the frozen snapshot (R9) ---------------------------


def test_replay_over_the_frozen_corpus_reproduces_the_documented_numbers():
    """58 firings across 6 plants, 0 false positives.

    Was 55 across 5. The 2026-08-20T20:15 re-capture resolved
    stella-cherry-tree, which the previous capture had missed entirely (it
    aborted on an HTTP 429 and stella was one of the casualties), and stella
    contributes exactly 3 rows.

    A false positive here is structurally impossible rather than merely
    unobserved: clause 3 requires a tier where the published price differs
    from the NATIONAL price, so a fired row provably did not publish the
    national price. What the replay establishes is the count and the shape.

    Against the SNAPSHOT, whose as-of commit is in MANIFEST.json. `clean`
    especially is a moving target on the live corpus — it counts every FGT row
    the audit checked and cleared, so it grows by a handful twice a day, and
    it is the number that turned CI red on the 2026-08-20_23:22 run.
    """
    code, report = run(FIXTURE_CORPUS, REFERENCE, now=FRESH, latest_only=False)

    assert report["fired"] == 58, report["fired"]
    assert {f["plant"] for f in report["findings"]} == {
        "bing-cherry-tree",
        "fuji-apple-tree",
        "honeycrisp-apple-tree",
        "meyer-lemon-tree",
        "pink-lemonade-blueberry",
        "stella-cherry-tree",
    }
    # Every finding names a region that came out of the capture. The reference
    # holds four; only CA has ever matched a published row.
    assert {f["region"] for f in report["findings"]} == {"CA"}
    # Clause 3 held for every one of them.
    assert all(f["contrast_tiers"] for f in report["findings"])
    assert report["clean"] == 1707, report["clean"]
    assert code == EXIT_ALARM


def test_replay_marks_old_rows_as_leads_not_verdicts():
    """--all-history compares months-old rows to one fresh capture, which is
    exactly the decay the age gate exists to prevent. Findings outside the
    window must be labelled `lead` so a replay cannot be quoted as a verdict.

    13 confirmed / 45 lead against the 2026-08-20T20:15 capture (was 11/44
    against the earlier one; stella adds 2 confirmed and 1 lead).
    """
    _, report = run(FIXTURE_CORPUS, REFERENCE, now=FRESH, latest_only=False)
    assert report["fired_confirmed"] == 13, report["fired_confirmed"]
    assert report["fired_lead"] == 45, report["fired_lead"]
    assert report["fired_confirmed"] + report["fired_lead"] == report["fired"]
    for f in report["findings"]:
        assert f["strength"] in ("confirmed", "lead")


def test_the_audit_catches_what_the_vocabulary_predicate_cannot():
    """THE REASON BOTH EXIST. Neither is a superset of the other.

    27 pink-lemonade-blueberry rows are a gallon-only CA flip, invisible to
    any label rule. 19 fuji-apple-tree rows are regional renders FGT served in
    JUNE spelled "5-6 feet" — proof the "ft." vocabulary is not a property of
    regional renders in general, only of the ones observed since August.
    """
    from scrapers.shopify import _has_regional_size_vocabulary

    _, report = run(FIXTURE_CORPUS, REFERENCE, now=FRESH, latest_only=False)
    counts = {}
    for f in report["findings"]:
        counts[f["plant"]] = counts.get(f["plant"], 0) + 1
    assert counts["pink-lemonade-blueberry"] == 27
    assert counts["fuji-apple-tree"] == 19

    # And the label rule genuinely cannot see the gallon case.
    assert not _has_regional_size_vocabulary(["2 Gallon"])
    assert not _has_regional_size_vocabulary(["5-6 feet"])


def test_union_of_both_detectors_is_87_rows():
    """THE ONLY GROUND TRUTH THAT EXISTS. Pinned so it cannot drift in prose.

    44 vocabulary + 58 audit, overlapping on 15, union 87. The vocabulary
    predicate is 44/87 = 50.6% of it.

    THE UNION DID NOT MOVE WHEN THE REFERENCE DID, and that is worth noticing.
    The 2026-08-20T20:15 re-capture took the audit from 55 to 58 by resolving
    stella-cherry-tree — but stella's 3 rows were already caught by the
    vocabulary predicate, so they moved from vocabulary-only into the overlap
    (12 -> 15) and the union stayed at 87. Two independently captured
    references, same 87. That is corroboration, not a coincidence to lean on.

    87 is still a UNION OF TWO PARTIAL DETECTORS, not a census. A regional
    render that neither catches is by construction missing from it, so 50.6%
    is an upper bound on recall, not a measurement of it. Any figure claiming
    to be the true total is unsourced.

    Counted over the snapshot, which holds every FGT row for the nine plants
    the reference covers. The snapshot builder asserts that no FGT row OUTSIDE
    those nine carries a vocabulary hit, so scoping it this way leaves all
    four counts unchanged — see MANIFEST.json.
    """
    from scrapers.shopify import _has_regional_size_vocabulary

    ref = load_reference(REFERENCE)["plants"]
    vocab, d2 = set(), set()
    for path in sorted((FIXTURE_CORPUS / "prices").glob("*.jsonl")):
        plant = path.name[:-6]
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("retailer_id") != "fast-growing-trees":
                    continue
                labels = [
                    (c or {}).get("raw_size") or ""
                    for c in (row.get("sizes") or {}).values()
                    if isinstance(c, dict)
                ]
                if _has_regional_size_vocabulary(labels):
                    vocab.add((plant, i))
                pref = ref.get(plant)
                if pref is not None and evaluate_row(pref, row, True)[0] == "fired":
                    d2.add((plant, i))

    assert len(vocab) == 44, len(vocab)
    assert len(d2) == 58, len(d2)
    assert len(vocab & d2) == 15, len(vocab & d2)
    assert len(vocab | d2) == 87, len(vocab | d2)
    # Every row the vocabulary catches and the audit does not is meyer-lemon,
    # whose older rows predate the capture window the audit can speak for.
    assert {p for p, _ in vocab - d2} == {"meyer-lemon-tree"}


def test_the_ungated_predicate_would_fire_on_a_thousand_planting_tree_rows():
    """The false positive the retailer gate prevents, as a measurement.

    This is the reason _REGIONAL_RENDER_RETAILERS exists: without the retailer
    gate the "ft." rule would withhold four planting-tree products outright,
    on more than a thousand rows, none of which is a regional render.

    WHAT THIS DOES AND DOES NOT PROTECT. It pins the PREDICATE'S BEHAVIOUR
    against a frozen corpus: given this exact body of real planting-tree
    labels, `_has_regional_size_vocabulary` fires on exactly these rows. Break
    the regex or turn the `any` into an `all` and the counts move, which is
    how M1 and M3 die here.

    It does NOT keep the figures quoted in scrapers/shopify.py honest against
    the live corpus, and an earlier version of this docstring wrongly claimed
    it did. Freezing the census is what removed that coupling — say so rather
    than imply a protection that no longer exists. Nothing can restore it
    without re-introducing the defect: those figures are a census of
    data/prices/, the bot appends to data/prices/ twice a day, and a test that
    recomputed them goes red on an ordinary scrape run. That is exactly what
    happened — 1,065 -> 1,069 on the 2026-08-20_23:22 run, on healthy data.

    So the comment in scrapers/shopify.py is labelled there as a DATED census
    carrying its as-of commit, and the authoritative frozen numbers live in
    MANIFEST.json beside this fixture. If the two ever disagree, the manifest
    is right and the prose is stale; neither is a defect in the gate.

    Measured over a frozen LABEL CENSUS: every planting-tree row reduced to
    its ordered raw_size tuple, deduplicated with a multiplicity count (78
    distinct tuples standing in for 19,688 rows). The predicate reads nothing
    but those labels, so the counts are exact.
    """
    from scrapers.shopify import _has_regional_size_vocabulary

    census = json.loads(PLANTING_TREE_LABELS.read_text(encoding="utf-8"))
    rows = hits = 0
    plants = set()
    for plant, entries in census.items():
        for labels, count in entries:
            rows += count
            if _has_regional_size_vocabulary(labels):
                hits += count
                plants.add(plant)

    assert hits == 1069, hits
    assert rows == 19688, rows
    assert len(plants) == 4, sorted(plants)
    assert hits / rows > 0.05, (
        "the gate is only worth having while the ungated rule would misfire "
        "at scale; if this collapses, re-derive the argument"
    )


def test_the_national_ft_statistic_quoted_in_the_scraper_is_real(reference):
    """47 of 58. The number scrapers/shopify.py uses to argue the proxy is a
    proxy, checked against the file it is quoted from.

    THIS IS THE CLAIM THE WHOLE DESIGN RESTS ON. "ft." is not semantically
    regional — it is FGT's canonical catalog spelling, carried by the large
    majority of NATIONAL variants too. The storefront's national render
    rewrites it to "feet"; the regional render does not. If that ever stops
    being true the scrape-time predicate withholds the entire FGT catalogue.

    The previous version of this figure (139 of 287) was quoted from a capture
    that is no longer committed, so nobody could check it. This one is.
    """
    import re

    ft = re.compile(r"\bft\.")
    nat = [
        v for p in reference["plants"].values()
        for v in (p.get("national") or {}).values() if v
    ]
    nat_ft = [v for v in nat if ft.search(v["title"])]
    assert (len(nat_ft), len(nat)) == (47, 58), (len(nat_ft), len(nat))
    assert len(nat_ft) / len(nat) > 0.5, (
        "the argument is that MOST national variants carry the regional "
        "spelling; if that stops holding, revisit the proxy"
    )


# --- the failure mode this restructure exists to prevent --------------------


def test_a_scrape_append_cannot_move_a_pinned_number(tmp_path):
    """THE REGRESSION TEST FOR THE 2026-08-20_23:22 CI FAILURE ITSELF.

    Six tests in this file went red on a production scrape run because their
    expected values were censuses of data/prices/, which the bot appends to
    twice a day. Nothing was wrong with the pipeline; the tests were wrong
    about what they were allowed to depend on.

    This proves both halves of the fix at once. Three rows of exactly the kind
    tonight's run added — a planting-tree "ft." row, an FGT national row, and
    an FGT regional-shaped row — are appended to a COPY of the snapshot.

      * The audit SEES them. The copy's counts move by exactly the expected
        amounts, so the append is real and would have moved a live census.
      * The pinned numbers DO NOT move, because they are read off the frozen
        snapshot, which no scrape can reach.

    If anyone re-points a pinned assertion at data/prices/, the second half of
    this test still passes — but the first half is the standing demonstration
    of why they must not.
    """
    from scrapers.shopify import _has_regional_size_vocabulary

    before_code, before = run(
        FIXTURE_CORPUS, REFERENCE, now=FRESH, latest_only=False,
    )

    copy = tmp_path / "data"
    shutil.copytree(FIXTURE_CORPUS, copy)
    ts = (CAPTURE_AT - timedelta(hours=2)).isoformat()

    # 1. a planting-tree row carrying the "ft." vocabulary — the retailer the
    #    gate exists to exclude, and the source of the 1065 -> 1069 drift.
    pt_row = {
        "retailer_id": "planting-tree", "timestamp": ts,
        "sizes": {"5-6ft": {"price": 129.99, "raw_size": "5-6 ft."}},
    }
    assert _has_regional_size_vocabulary(["5-6 ft."]), "the appended row must hit"
    with open(copy / "prices" / "honeycrisp-apple-tree.jsonl", "a",
              encoding="utf-8") as fh:
        fh.write(json.dumps(pt_row) + "\n")
        # 2. an honest FGT national row — one more `clean`.
        fh.write(json.dumps(_row(NATIONAL_SIZES, ts=ts)) + "\n")
        # 3. an FGT regional-shaped row — one more `fired`, confirmed.
        fh.write(json.dumps(_row(CA_FLIP_SIZES, ts=ts)) + "\n")

    after_code, after = run(copy, REFERENCE, now=FRESH, latest_only=False)

    # The append is real: a census over the copy moves, and moves precisely.
    assert after["fired"] == before["fired"] + 1
    assert after["clean"] == before["clean"] + 1
    assert after["fired_confirmed"] == before["fired_confirmed"] + 1
    assert after["fired_lead"] == before["fired_lead"]
    # The planting-tree row is another retailer's and never reaches the audit.
    assert after["rows_considered"] == before["rows_considered"] + 2
    assert after_code == before_code == EXIT_ALARM

    # And the snapshot the pinned numbers are read from did not budge.
    again_code, again = run(
        FIXTURE_CORPUS, REFERENCE, now=FRESH, latest_only=False,
    )
    assert (again["fired"], again["clean"]) == (58, 1707)
    assert (again["fired_confirmed"], again["fired_lead"]) == (13, 45)
    assert again_code == EXIT_ALARM


# --- the audit must never be mistaken for a clean bill of health -----------


def _expected_scope(reference):
    """(answerable, total) computed from the reference, not typed in."""
    plants = reference["plants"]
    answerable = {
        p for p, v in plants.items()
        if (v.get("national") or {}) and (v.get("regional") or {})
    }
    return len(answerable), len(plants)


def test_report_carries_its_own_coverage_denominator(reference):
    """Both numbers, so neither can be quoted alone.

    DERIVED, not hardcoded: the counts move whenever the reference is
    re-captured, and a suite that goes red for that reason trains people to
    edit expectations without reading them. The literal identity of the
    current file is pinned once, in test_reference_is_the_expected_capture.
    """
    answerable, total = _expected_scope(reference)
    _, report = run(FIXTURE_CORPUS, REFERENCE, now=FRESH)

    assert report["reference_total_plants"] == total
    assert report["reference_answerable_plants"] == answerable
    assert len(report["answerable_plant_ids"]) == answerable
    # Every answerable plant really does have both sides in the capture.
    for pid in report["answerable_plant_ids"]:
        ref = reference["plants"][pid]
        assert ref["national"] and ref["regional"], pid
    # And the unanswerable ones are unanswerable for a stated reason, not by
    # accident: at this capture, eastern-redbud has national tiers but no
    # region-restricted variant at all (nothing to compare against), and
    # sunshine-blue-blueberry resolves to no variants because it is held on
    # its `-ca` mirror handle.
    unanswerable = set(reference["plants"]) - set(report["answerable_plant_ids"])
    for pid in unanswerable:
        ref = reference["plants"][pid]
        assert not (ref.get("national") and ref.get("regional")), pid


def test_a_clean_run_still_prints_the_scope_and_refuses_the_word_clean(
    tmp_path, capsys,
):
    """THE MISREADING THIS GUARDS AGAINST.

    A reader who skims to the last line and sees "no regional prices found"
    would take it as "FGT is fine". It is not: the audit can speak for 7 of
    the 9 plants this targeted capture holds — and FGT is scraped across 66,
    so it is silent about 59 of them. So the scope banner is printed alongside
    the verdict, and the verdict line says in words that it is not a clean
    bill of health.

    The counts are read off the reference by _expected_scope rather than typed
    into the assertions, so a re-capture moves them without touching this
    test; the numbers in this docstring are illustrative of the current
    capture only.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(NATIONAL_SIZES)]})
    code = main([
        "--data-dir", str(data), "--reference", str(REFERENCE),
        "--now", FRESH.isoformat(),
    ])
    out = capsys.readouterr().out
    answerable, total = _expected_scope(load_reference(REFERENCE))

    assert code == EXIT_OK
    assert f"{answerable} of {total}" in out, (
        "the coverage denominator must be on screen"
    )
    assert "NOT a clean bill of health" in out
    assert "NOT checked and NOT cleared" in out
    # printed at both ends, not just once above the numbers
    assert out.count("SCOPE:") == 2, out


def test_an_alarming_run_also_prints_the_scope(tmp_path, capsys):
    """The alarm path must size its own findings too: one finding out of the
    7 checkable plants is a very different statement from one out of the 66
    FGT plants that actually get scraped.

    Driven over a corpus BUILT to fire. Read off data/prices/ this test was
    really asserting "the live tip is still broken", so shipping the withhold
    — the fix — turned it red: tonight's run cleared the flip and the audit
    correctly, legitimately, alarmed about nothing. A test of the alarm
    PRINTER must not depend on the retailer currently misbehaving.
    """
    data = _corpus(tmp_path, {"honeycrisp-apple-tree": [_row(CA_FLIP_SIZES)]})
    code = main([
        "--data-dir", str(data), "--reference", str(REFERENCE),
        "--now", FRESH.isoformat(),
    ])
    out = capsys.readouterr().out
    answerable, total = _expected_scope(load_reference(REFERENCE))

    assert code == EXIT_ALARM
    assert "SCOPE:" in out
    assert f"{answerable} of {total}" in out
    assert "FIRED[confirmed] honeycrisp-apple-tree [CA]" in out, out
