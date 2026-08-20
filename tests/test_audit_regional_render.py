"""Audit D2' — the four clauses, the age gate, and the corpus replay.

The scrape-time predicate in scrapers/shopify.py reads a LABEL. This audit
reads a PRICE, against the retailer's own catalog capture committed at
data/regional_reference/fast-growing-trees.json. That makes it the independent
oracle (nightly_audits.py RULE ZERO) and the thing to believe when the two
disagree — which they measurably do, in both directions.

The replay at the bottom of this file is the calibration (R9): every number
in the module docstrings is reproduced here from the committed corpus, so a
change that quietly moves one turns this suite red.
"""

import hashlib
import json
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
    """
    raw_path = REFERENCE.parent / reference["provenance"]["raw_capture"]
    assert raw_path.exists(), f"the pinned raw capture is missing: {raw_path}"
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    assert digest == reference["provenance"]["raw_capture_sha256"], (
        "the committed raw capture does not match the sha256 the reference "
        "pins it to. One of the two has been edited; neither can be trusted "
        f"until that is resolved. file={digest} "
        f"pinned={reference['provenance']['raw_capture_sha256']}"
    )


def test_reference_is_the_expected_capture(reference):
    """THE ONE LITERAL ANCHOR. A file must not be able to self-verify.

    Every other test in this module derives its expectations from the
    reference, so that a re-capture does not turn the suite red for a reason
    that is not a defect. That property has a cost: a truncated, stale or
    substituted reference would satisfy all of them, because they would simply
    describe whatever they were given.

    So exactly one test pins the identity of the file we actually reviewed —
    its capture instant, its raw-capture hash, and two prices read off the
    retailer's catalog by hand. Re-capturing REQUIRES editing this test, on
    purpose, which is the point.
    """
    prov = reference["provenance"]
    assert prov["captured_at"] == "2026-08-20T20:15:02Z"
    assert prov["raw_capture_sha256"] == (
        "35d62d78c61be3f7ecd1636afa637a1e56b50c2f24d07fcd27fd455729efa1c7"
    )
    assert len(reference["plants"]) == 9
    # Hand-read from the capture: stella's CA 5-6 ft against its national twin.
    # This pair is what the audit's newest finding turns on.
    stella = reference["plants"]["stella-cherry-tree"]
    assert stella["regional"]["CA"]["5-6ft"]["price_cents"] == 14695
    assert stella["national"]["5-6ft"]["price_cents"] == 16095


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
    _, report = run(DATA_DIR, REFERENCE, now=FRESH)
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


def test_fresh_reference_enables_the_price_clauses():
    code, report = run(DATA_DIR, REFERENCE, now=FRESH)
    assert report["price_clauses_enabled"] is True
    assert report["reference_stale"] is False
    assert report["checked"] > 0


def test_stale_reference_disables_the_price_clauses_and_still_alarms():
    """COULD-NOT-VERIFY MUST NOT READ AS CLEAN.

    Past the window the price comparison is no longer evidence — FGT reprices
    within days — so the clauses are disabled. The exit code must then be
    ALARM, not OK, for the same reason nightly_audits.py R10 alarms on a
    collapsed denominator: an audit that goes green because it stopped looking
    also stops anybody else looking.
    """
    code, report = run(DATA_DIR, REFERENCE, now=STALE)

    assert report["price_clauses_enabled"] is False
    assert report["checked"] == 0
    assert report["fired"] == 0
    assert code == EXIT_ALARM, "a stale reference must never exit 0"
    assert any("reference stale, not checked" in a for a in report["alarms"])


def test_stale_gate_boundary_is_the_documented_window():
    """One hour inside the window checks; one day outside does not."""
    inside = CAPTURE_AT + timedelta(days=MAX_REFERENCE_AGE_DAYS, hours=-1)
    outside = CAPTURE_AT + timedelta(days=MAX_REFERENCE_AGE_DAYS, hours=1)
    assert run(DATA_DIR, REFERENCE, now=inside)[1]["price_clauses_enabled"] is True
    assert run(DATA_DIR, REFERENCE, now=outside)[1]["price_clauses_enabled"] is False


def test_a_reference_with_no_usable_date_is_stale_not_fresh(tmp_path, reference):
    """Unknown age is not young. The default must fail closed."""
    broken = dict(reference)
    broken["provenance"] = dict(reference["provenance"], captured_at=None)
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    code, report = run(DATA_DIR, path, now=FRESH)
    assert report["reference_stale"] is True
    assert code == EXIT_ALARM


def test_a_national_corpus_exits_ok(tmp_path):
    """EXIT_OK must be REACHABLE, or EXIT_ALARM means nothing.

    Every other test here asserts an alarm, and a check that can only ever go
    red is indistinguishable from one that is simply broken. This drives the
    same audit over a corpus holding one honest national row.
    """
    prices = tmp_path / "prices"
    prices.mkdir()
    (prices / "honeycrisp-apple-tree.jsonl").write_text(
        json.dumps(_row({
            # the real national catalogue, all six tiers
            "1-2ft": _cell(75.95), "2-3ft": _cell(86.95),
            "3-4ft": _cell(100.95), "4-5ft": _cell(129.95),
            "5-6ft": _cell(153.95), "6-7ft": _cell(183.95),
        })) + "\n",
        encoding="utf-8",
    )
    code, report = run(tmp_path, REFERENCE, now=FRESH)
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

    code, report = run(DATA_DIR, path, now=FRESH)
    assert report["reference_answerable_plants"] == 0
    assert code == EXIT_ALARM
    assert any("denominator collapsed" in a for a in report["alarms"])


# --- calibration against the committed corpus (R9) --------------------------


def test_replay_over_the_whole_corpus_reproduces_the_documented_numbers():
    """58 firings across 6 plants, 0 false positives.

    Was 55 across 5. The 2026-08-20T20:15 re-capture resolved
    stella-cherry-tree, which the previous capture had missed entirely (it
    aborted on an HTTP 429 and stella was one of the casualties), and stella
    contributes exactly 3 rows.

    A false positive here is structurally impossible rather than merely
    unobserved: clause 3 requires a tier where the published price differs
    from the NATIONAL price, so a fired row provably did not publish the
    national price. What the replay establishes is the count and the shape.
    """
    code, report = run(DATA_DIR, REFERENCE, now=FRESH, latest_only=False)

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
    assert report["clean"] == 1700, report["clean"]
    assert code == EXIT_ALARM


def test_replay_marks_old_rows_as_leads_not_verdicts():
    """--all-history compares months-old rows to one fresh capture, which is
    exactly the decay the age gate exists to prevent. Findings outside the
    window must be labelled `lead` so a replay cannot be quoted as a verdict.

    13 confirmed / 45 lead against the 2026-08-20T20:15 capture (was 11/44
    against the earlier one; stella adds 2 confirmed and 1 lead).
    """
    _, report = run(DATA_DIR, REFERENCE, now=FRESH, latest_only=False)
    assert report["fired_confirmed"] == 13, report["fired_confirmed"]
    assert report["fired_lead"] == 45, report["fired_lead"]
    assert report["fired_confirmed"] + report["fired_lead"] == report["fired"]
    for f in report["findings"]:
        assert f["strength"] in ("confirmed", "lead")


def test_latest_rows_are_all_within_the_window_so_ci_never_reports_leads():
    """The mode CI actually runs compares hours-old rows, so every finding it
    produces is `confirmed`. If this ever fails, the corpus went stale."""
    _, report = run(DATA_DIR, REFERENCE, now=FRESH, latest_only=True)
    assert report["fired_lead"] == 0
    assert report["fired_confirmed"] == report["fired"] == 6


def test_the_audit_catches_what_the_vocabulary_predicate_cannot():
    """THE REASON BOTH EXIST. Neither is a superset of the other.

    27 pink-lemonade-blueberry rows are a gallon-only CA flip, invisible to
    any label rule. 16 fuji-apple-tree rows are regional renders FGT served in
    JUNE spelled "5-6 feet" — proof the "ft." vocabulary is not a property of
    regional renders in general, only of the ones observed since August.
    """
    from scrapers.shopify import _has_regional_size_vocabulary

    _, report = run(DATA_DIR, REFERENCE, now=FRESH, latest_only=False)
    counts = {}
    for f in report["findings"]:
        counts[f["plant"]] = counts.get(f["plant"], 0) + 1
    assert counts["pink-lemonade-blueberry"] == 27
    assert counts["fuji-apple-tree"] == 19

    # And the label rule genuinely cannot see the gallon case.
    assert not _has_regional_size_vocabulary(["2 Gallon"])
    assert not _has_regional_size_vocabulary(["5-6 feet"])


def test_the_current_corpus_still_holds_six_regional_rows_at_the_tip():
    """The live defect, pinned. These are the newest committed rows: the site
    built from this corpus is publishing six California prices right now.

    SIX, not five. stella-cherry-tree was invisible to the first capture and
    is the one the vocabulary predicate was carrying alone; now both detectors
    see it.

    When the withhold ships and a run happens, these become empty rows and
    this test must be updated to match — deliberately, with the new numbers.
    """
    code, report = run(DATA_DIR, REFERENCE, now=FRESH, latest_only=True)
    assert code == EXIT_ALARM
    assert report["fired"] == 6
    published = {f["plant"]: f["published_cents"] for f in report["findings"]}
    assert published["bing-cherry-tree"] == {"5-6ft": 15395}
    assert published["pink-lemonade-blueberry"] == {"2gal": 4495}
    assert published["stella-cherry-tree"] == {"5-6ft": 14695}
    nat = {f["plant"]: f["national_cents"] for f in report["findings"]}
    assert nat["bing-cherry-tree"] == {"5-6ft": 16895}, (
        "the national 5-6 ft Bing cherry is $168.95; we published $153.95"
    )
    assert nat["stella-cherry-tree"] == {"5-6ft": 16095}, (
        "the national 5-6 ft Stella cherry is $160.95; we published $146.95"
    )


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
    _, report = run(DATA_DIR, REFERENCE, now=FRESH)

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
    would take it as "FGT is fine". It is not: the audit can speak for 6 of
    68 plants. So the scope banner is printed alongside the verdict, and the
    verdict line says in words that it is not a clean bill of health.
    """
    prices = tmp_path / "prices"
    prices.mkdir()
    (prices / "honeycrisp-apple-tree.jsonl").write_text(
        json.dumps(_row({
            "1-2ft": _cell(75.95), "2-3ft": _cell(86.95),
            "3-4ft": _cell(100.95), "4-5ft": _cell(129.95),
            "5-6ft": _cell(153.95), "6-7ft": _cell(183.95),
        })) + "\n",
        encoding="utf-8",
    )
    code = main([
        "--data-dir", str(tmp_path), "--reference", str(REFERENCE),
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


def test_an_alarming_run_also_prints_the_scope(capsys):
    """The alarm path must size its own findings too: six findings out of
    seven checkable plants is a very different statement from six out of 68.
    """
    code = main([
        "--data-dir", str(DATA_DIR), "--reference", str(REFERENCE),
        "--now", FRESH.isoformat(),
    ])
    out = capsys.readouterr().out
    answerable, total = _expected_scope(load_reference(REFERENCE))

    assert code == EXIT_ALARM
    assert "SCOPE:" in out
    assert f"{answerable} of {total}" in out

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
    """
    import glob
    import os

    from scrapers.shopify import _has_regional_size_vocabulary

    ref = load_reference(REFERENCE)["plants"]
    vocab, d2 = set(), set()
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "prices", "*.jsonl"))):
        plant = os.path.basename(path)[:-6]
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


def test_the_ungated_predicate_would_hit_1065_planting_tree_rows():
    """The false positive the retailer gate prevents, as a live measurement.

    Pinned here rather than only in a comment so the figure quoted in
    scrapers/shopify.py cannot rot away from the corpus.
    """
    import glob
    import os

    from scrapers.shopify import _has_regional_size_vocabulary

    rows = hits = 0
    plants = set()
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "prices", "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("retailer_id") != "planting-tree":
                    continue
                rows += 1
                labels = [
                    (c or {}).get("raw_size") or ""
                    for c in (row.get("sizes") or {}).values()
                    if isinstance(c, dict)
                ]
                if _has_regional_size_vocabulary(labels):
                    hits += 1
                    plants.add(os.path.basename(path)[:-6])

    assert hits == 1065, hits
    assert rows == 19615, rows
    assert len(plants) == 4, sorted(plants)

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

