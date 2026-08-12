"""Tests for scripts/nightly_audits.py.

Every audit is tested in BOTH directions: it must fire on a seeded defect and
stay silent on the clean version of the same corpus. A test that only asserts
"finds the bad thing" cannot tell a working audit from one that flags
everything, and this repo has shipped exactly that — an audit reporting
`checked=0 mismatches=0` from a wrong CSS selector looked like a pass.

The denominator assertions are load-bearing for the same reason: they are what
distinguishes "examined 157 things and found nothing" from "examined nothing".
"""

import json

import pytest

from scripts.nightly_audits import (
    EXIT_ALARM,
    EXIT_OK,
    FRESH_HOURS,
    audit_a_cross_retailer,
    audit_b_two_nursery_pairs,
    audit_c_within_retailer_inversion,
    audit_d_snapshot_value_diff,
    audit_e_cross_page_agreement,
    audit_f_stock_consistency,
    load_price_history,
    main,
    split_by_freshness,
)

TS1 = "2026-08-11T11:00:00+00:00"
TS2 = "2026-08-12T11:00:00+00:00"


def _entry(rid, sizes, ts=TS2, in_stock=None):
    return {
        "retailer_id": rid,
        "timestamp": ts,
        "in_stock": in_stock,
        "sizes": {t: {"price": p, "available": None} for t, p in sizes.items()},
    }


def _write(tmp_path, per_plant):
    """per_plant: {plant: [entry, ...]} written in order to data/prices."""
    data = tmp_path / "data"
    (data / "prices").mkdir(parents=True)
    for plant, entries in per_plant.items():
        with open(data / "prices" / f"{plant}.jsonl", "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")
    return data


def _latest(tmp_path, per_plant):
    history = load_price_history(str(_write(tmp_path, per_plant)))
    return {k: v[-1] for k, v in history.items()}


# --------------------------------------------------------------------------
# A — cross-retailer outlier
# --------------------------------------------------------------------------

def test_a_fires_on_outlier_against_median_of_others(tmp_path):
    latest = _latest(tmp_path, {"rose": [
        _entry("nursery-a", {"3gal": 40.0}),
        _entry("nursery-b", {"3gal": 42.0}),
        _entry("nursery-c", {"3gal": 10.0}),      # a quarter of the others
    ]})
    denom, findings = audit_a_cross_retailer(latest)
    assert denom == 3, "denominator must count every comparable row"
    assert [f["id"] for f in findings] == ["A|rose|3gal|nursery-c"]


def test_a_silent_when_all_three_agree(tmp_path):
    latest = _latest(tmp_path, {"rose": [
        _entry("nursery-a", {"3gal": 40.0}),
        _entry("nursery-b", {"3gal": 42.0}),
        _entry("nursery-c", {"3gal": 44.0}),
    ]})
    denom, findings = audit_a_cross_retailer(latest)
    assert denom == 3 and findings == []


def test_a_ignores_two_retailer_tiers_which_are_audit_b(tmp_path):
    """No median exists with two samples. A must not invent one — the
    two-nursery case is B's job and carries a weaker claim."""
    latest = _latest(tmp_path, {"rose": [
        _entry("nursery-a", {"3gal": 40.0}),
        _entry("nursery-c", {"3gal": 10.0}),
    ]})
    denom, findings = audit_a_cross_retailer(latest)
    assert denom == 0 and findings == []


# --------------------------------------------------------------------------
# B — two-nursery pairs
# --------------------------------------------------------------------------

def test_b_fires_on_wide_two_nursery_gap(tmp_path):
    latest = _latest(tmp_path, {"azalea": [
        _entry("nursery-a", {"3gal": 21.95}),
        _entry("nursery-b", {"3gal": 62.95}),
    ]})
    denom, findings = audit_b_two_nursery_pairs(latest)
    assert denom == 1
    assert len(findings) == 1 and "2.9x apart" in findings[0]["detail"]


def test_b_silent_below_the_calibrated_ratio(tmp_path):
    """2.4x must not fire. The 2.5 threshold is the measured knee — at 2.0 a
    new pair appears on 16 of any 60 nights, which is noise."""
    latest = _latest(tmp_path, {"azalea": [
        _entry("nursery-a", {"3gal": 20.00}),
        _entry("nursery-b", {"3gal": 48.00}),
    ]})
    denom, findings = audit_b_two_nursery_pairs(latest)
    assert denom == 1 and findings == []


def test_b_covers_the_pairs_that_started_the_investigation(tmp_path):
    """PRICE_AND_STOCK_AUDIT.md §4B: the first version of this audit skipped
    two-nursery tiers and therefore could not see the Delaware Valley azalea.
    Most tiers only have two nurseries, so skipping them hides the majority."""
    latest = _latest(tmp_path, {
        "p1": [_entry("a", {"1gal": 10.0}), _entry("b", {"1gal": 30.0})],
        "p2": [_entry("a", {"1gal": 10.0}), _entry("b", {"1gal": 11.0})],
    })
    denom, findings = audit_b_two_nursery_pairs(latest)
    assert denom == 2, "both pairs must be examined, not just the flagged one"
    assert len(findings) == 1


# --------------------------------------------------------------------------
# C — within-retailer inversion
# --------------------------------------------------------------------------

def test_c_fires_when_larger_container_is_cheaper(tmp_path):
    latest = _latest(tmp_path, {"maple": [_entry("a", {"1gal": 40.0, "3gal": 20.0})]})
    denom, findings = audit_c_within_retailer_inversion(latest)
    assert denom == 1
    assert findings[0]["id"] == "C|maple|a|1gal|3gal"


def test_c_tolerates_a_small_sale_driven_dip(tmp_path):
    """A 3gal five percent under the 1gal is a sale, not a mapping defect.
    0% tolerance produces a new finding on 7 of any 60 nights; 10% on 2."""
    latest = _latest(tmp_path, {"maple": [_entry("a", {"1gal": 40.0, "3gal": 38.0})]})
    denom, findings = audit_c_within_retailer_inversion(latest)
    assert denom == 1 and findings == []


def test_c_ignores_bareroot_vs_potted(tmp_path):
    """Bare-root priced under a container is real pricing. Only same-family
    container tiers are comparable."""
    latest = _latest(tmp_path, {"maple": [_entry("a", {"bareroot": 90.0, "1gal": 20.0})]})
    denom, findings = audit_c_within_retailer_inversion(latest)
    assert denom == 0 and findings == []


# --------------------------------------------------------------------------
# D — snapshot value diff (the FGT positional bug)
# --------------------------------------------------------------------------

def test_d_catches_a_price_sliding_onto_an_adjacent_label(tmp_path):
    """The worked example from PRICE_AND_STOCK_AUDIT.md §4D."""
    data = _write(tmp_path, {"delaware-valley-white-azalea": [
        _entry("fgt", {"1gal": 21.95, "3gal": 42.95}, ts=TS1),
        _entry("fgt", {"3gal": 21.95}, ts=TS2),
    ]})
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 1
    assert findings[0]["id"] == "D|delaware-valley-white-azalea|fgt|1gal->3gal"


def test_d_sees_a_pure_shift_that_leaves_the_tier_count_unchanged(tmp_path):
    """'A pure shift leaves the tier COUNT unchanged. Compare values, not
    counts.' Four tiers before, four after — a count-based check sees nothing."""
    data = _write(tmp_path, {"fuji-apple-tree": [
        _entry("fgt", {"3-4ft": 79.95, "4-5ft": 84.95, "5-6ft": 99.95, "6-7ft": 154.95}, ts=TS1),
        _entry("fgt", {"3-4ft": 84.95, "4-5ft": 99.95, "5-6ft": 154.95, "6-7ft": 199.95}, ts=TS2),
    ]})
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 1
    assert len(findings) == 3


def test_d_silent_on_an_ordinary_price_change(tmp_path):
    data = _write(tmp_path, {"rose": [
        _entry("a", {"1gal": 20.00, "3gal": 40.00}, ts=TS1),
        _entry("a", {"1gal": 22.00, "3gal": 44.00}, ts=TS2),
    ]})
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 1 and findings == []


def test_d_silent_when_two_sizes_merely_share_a_price(tmp_path):
    """The 'strict' rule: if the value is still at its old label too, this is
    a duplicate price, not a shift. Dropping these took the quiet-night rate
    from 106/128 to 108/128 without losing any real event."""
    data = _write(tmp_path, {"rose": [
        _entry("a", {"1gal": 20.00, "3gal": 40.00}, ts=TS1),
        _entry("a", {"1gal": 20.00, "3gal": 20.00}, ts=TS2),
    ]})
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 1 and findings == []


def test_d_denominator_is_zero_with_only_one_run_of_history(tmp_path):
    """No previous run means nothing was compared. That must read as 0
    examined, never as 0 problems."""
    data = _write(tmp_path, {"rose": [_entry("a", {"1gal": 20.0})]})
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 0 and findings == []


def test_d_does_not_read_prev_manifest(tmp_path):
    """prev_manifest.json is written by the pre-scrape snapshot step and is
    NOT in the commit step's `git add` list, so it is absent on a fresh CI
    checkout. D must derive its baseline from the committed price history."""
    data = _write(tmp_path, {"rose": [
        _entry("a", {"1gal": 20.00, "3gal": 40.00}, ts=TS1),
        _entry("a", {"3gal": 20.00}, ts=TS2),
    ]})
    assert not (data / "prev_manifest.json").exists()
    denom, findings = audit_d_snapshot_value_diff(load_price_history(str(data)))
    assert denom == 1 and len(findings) == 1


# --------------------------------------------------------------------------
# E — cross-page agreement
# --------------------------------------------------------------------------

PLANT_PAGE = """<html><body>
<script type="application/ld+json">{{"lowPrice": {low}}}</script>
{links}
</body></html>"""


def _site(tmp_path, plants, quotes):
    """plants: {file: lowPrice}. quotes: [(src_file, target_file, quoted)]."""
    site = tmp_path / "site"
    (site / "plants").mkdir(parents=True)
    (site / "guides").mkdir(parents=True)
    by_src = {}
    for src, target, quoted in quotes:
        by_src.setdefault(src, []).append(
            f'<a href="/plants/{target}"><span class="similar-price">from ${quoted:.2f}</span></a>'
        )
    for name, low in plants.items():
        (site / "plants" / name).write_text(
            PLANT_PAGE.format(low=low, links="".join(by_src.get(name, []))),
            encoding="utf-8")
    return str(site)


def test_e_fires_when_a_widget_disagrees_with_the_target_page(tmp_path):
    site = _site(tmp_path, {"a.html": 20.00, "b.html": 30.00},
                 [("a.html", "b.html", 25.00)])
    denom, findings = audit_e_cross_page_agreement(site)
    assert denom == 1
    assert "30.00" in findings[0]["detail"] and "25.00" in findings[0]["detail"]


def test_e_silent_when_the_widget_agrees(tmp_path):
    site = _site(tmp_path, {"a.html": 20.00, "b.html": 30.00},
                 [("a.html", "b.html", 30.00)])
    denom, findings = audit_e_cross_page_agreement(site)
    assert denom == 1 and findings == []


def test_e_denominator_is_zero_when_no_quotes_exist(tmp_path):
    """The failure this guards: a wrong selector once made this audit report
    `checked=0 mismatches=0`, which reads as a pass."""
    site = _site(tmp_path, {"a.html": 20.00}, [])
    denom, findings = audit_e_cross_page_agreement(site)
    assert denom == 0 and findings == []


# --------------------------------------------------------------------------
# F — stock consistency
# --------------------------------------------------------------------------

F_PAGE = """<html><body>
<script type="application/ld+json">{{"availability": "https://schema.org/{avail}"}}</script>
<table class="best-prices-table"><tbody>{mobile}</tbody></table>
<table class="comparison-table"><tbody>{rows}</tbody></table>
</body></html>"""


def _fsite(tmp_path, avail="InStock", rows="", mobile="", name="site"):
    site = tmp_path / name
    (site / "plants").mkdir(parents=True, exist_ok=True)
    (site / "guides").mkdir(parents=True, exist_ok=True)
    (site / "plants" / "p.html").write_text(
        F_PAGE.format(avail=avail, rows=rows, mobile=mobile), encoding="utf-8")
    return str(site)


BUYABLE_ROW = ('<tr><td class="retailer-name">A</td>'
               '<td><a class="price-link" href="/x">$20.00</a></td></tr>')


def test_f_silent_on_a_consistent_page(tmp_path):
    site = _fsite(tmp_path, rows=BUYABLE_ROW,
                  mobile='<tr><td><a class="bp-price-link">$20.00</a></td></tr>')
    denom, findings, counts = audit_f_stock_consistency(site, {})
    assert denom == 1 and findings == []
    assert counts["mobile_price_links"] == 1


def test_f1_fires_when_a_sold_out_row_still_links_a_price(tmp_path):
    site = _fsite(tmp_path, rows='<tr class="sold-out-row">'
                                 '<td class="retailer-name">A</td>'
                                 '<td><a class="price-link" href="/x">$20.00</a></td></tr>')
    denom, findings, counts = audit_f_stock_consistency(site, {})
    assert counts["sold_out_rows"] == 1, "denominator: the row WAS examined"
    assert [f["id"].split("|")[0] for f in findings] == ["F1"]


def test_f1_silent_when_a_sold_out_row_shows_an_unlinked_price(tmp_path):
    site = _fsite(tmp_path, avail="OutOfStock", rows='<tr class="sold-out-row">'
                                 '<td class="retailer-name">A</td>'
                                 '<td><span class="price-soldout">$20.00'
                                 '<span class="soldout-tag">Sold out</span></span></td></tr>')
    denom, findings, counts = audit_f_stock_consistency(site, {})
    assert counts["sold_out_rows"] == 1 and counts["sold_out_price_cells"] == 1
    assert findings == []


def test_f2_fires_when_a_sold_out_size_is_flagged_best_price(tmp_path):
    site = _fsite(tmp_path, avail="OutOfStock", rows='<tr><td class="retailer-name">A</td><td>'
                                 '<span class="price-soldout">'
                                 '<span class="best-price">$20.00</span></span></td></tr>')
    _denom, findings, _counts = audit_f_stock_consistency(site, {})
    assert [f["id"].split("|")[0] for f in findings] == ["F2"]


def test_f2b_fires_when_mobile_offers_what_desktop_will_not_link(tmp_path):
    """Desktop and mobile are separate template branches reading the same
    build.py flags. They have disagreed before: Jinja's `==` makes 0.0 equal
    to False, so one surface called a size sold out while the other sold it."""
    site = _fsite(tmp_path, rows=BUYABLE_ROW,
                  mobile='<tr><td><a class="bp-price-link">$77.77</a></td></tr>')
    _denom, findings, counts = audit_f_stock_consistency(site, {})
    assert counts["mobile_price_links"] == 1
    assert [f["id"].split("|")[0] for f in findings] == ["F2b"]


def test_f4_fires_when_schema_says_instock_but_nothing_is_buyable(tmp_path):
    site = _fsite(tmp_path, avail="InStock",
                  rows='<tr><td class="retailer-name">A</td><td>'
                       '<span class="price-soldout">$20.00</span></td></tr>')
    _denom, findings, counts = audit_f_stock_consistency(site, {})
    assert counts["schema_instock_pages"] == 1
    assert [f["id"].split("|")[0] for f in findings] == ["F4"]


def test_f4_silent_when_schema_says_out_of_stock(tmp_path):
    site = _fsite(tmp_path, avail="OutOfStock",
                  rows='<tr><td class="retailer-name">A</td><td>'
                       '<span class="price-soldout">$20.00</span></td></tr>')
    _denom, findings, counts = audit_f_stock_consistency(site, {})
    assert counts["schema_instock_pages"] == 0 and findings == []


def test_f3_reports_retailers_with_no_stock_data_without_alarming(tmp_path):
    """Unknown is not sold out. Audit doc §3b: any change treating None as
    unavailable takes most of the catalogue dark, so this is a COUNT for the
    digest, never a finding."""
    latest = {
        ("p", "knows"): _entry("knows", {}),
        ("p", "blind"): _entry("blind", {}),
    }
    latest[("p", "knows")]["sizes"] = {"1gal": {"price": 10.0, "available": True}}
    latest[("p", "blind")]["sizes"] = {"1gal": {"price": 10.0, "available": None}}
    site = _fsite(tmp_path, rows=BUYABLE_ROW)
    _denom, findings, counts = audit_f_stock_consistency(site, latest)
    assert findings == []
    assert counts["retailers_all_unknown_stock"] == ["blind"]


# --------------------------------------------------------------------------
# main(): severity routing and the meta-alarms
# --------------------------------------------------------------------------

def _full_corpus(tmp_path, extra_plants=None):
    plants = {
        f"p{i}": [_entry("a", {"1gal": 20.0}, ts=TS1), _entry("a", {"1gal": 20.0}, ts=TS2)]
        for i in range(3)
    }
    plants.update(extra_plants or {})
    data = _write(tmp_path, plants)
    site = _fsite(tmp_path, rows=BUYABLE_ROW)
    return str(data), site


def _run(tmp_path, data, site, floors_off=True, baseline=None):
    """Run main() with the denominator floors dropped, so these tests exercise
    severity routing rather than the (separately tested) floor alarm."""
    import scripts.nightly_audits as na
    saved = dict(na.DENOM_FLOOR)
    if floors_off:
        for key in na.DENOM_FLOOR:
            na.DENOM_FLOOR[key] = 0
    base = baseline or str(tmp_path / "baseline.json")
    if baseline is None:
        (tmp_path / "baseline.json").write_text(json.dumps({"accepted": {}}), encoding="utf-8")
    try:
        return main(["--data-dir", data, "--site-dir", site, "--baseline", base,
                     "--json-out", str(tmp_path / "report.json")])
    finally:
        na.DENOM_FLOOR.clear()
        na.DENOM_FLOOR.update(saved)


def test_main_exits_ok_on_a_clean_corpus(tmp_path):
    data, site = _full_corpus(tmp_path)
    assert _run(tmp_path, data, site) == EXIT_OK


def test_main_notices_but_does_not_alarm_on_a_single_new_lead(tmp_path):
    """One new heuristic lead is a work-list item. Turning the build red for
    it is how an alarm gets ignored."""
    data, site = _full_corpus(tmp_path, {"odd": [
        _entry("a", {"1gal": 10.0}), _entry("b", {"1gal": 90.0})]})
    assert _run(tmp_path, data, site) == EXIT_OK
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert len(report["audits"]["B_two_nursery_pairs"]["new_findings"]) == 1
    assert report["alarms"] == []
    assert any("B_two_nursery_pairs" in n for n in report["notices"])


def test_main_alarms_on_a_cluster_of_new_leads(tmp_path):
    """Five at once is a regression, not drift. Measured: the most NEW
    findings any single night produced across 129 real transitions was 3."""
    extra = {f"odd{i}": [_entry("a", {"1gal": 10.0}), _entry("b", {"1gal": 90.0})]
             for i in range(5)}
    data, site = _full_corpus(tmp_path, extra)
    assert _run(tmp_path, data, site) == EXIT_ALARM
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert any("B_two_nursery_pairs" in a for a in report["alarms"])


def test_main_alarms_immediately_on_an_exact_invariant(tmp_path):
    """E and F are invariants, not heuristics: one violation is an alarm, with
    no cluster threshold to hide behind."""
    data, _site = _full_corpus(tmp_path)
    site = _fsite(tmp_path, name="badsite",
                  rows='<tr class="sold-out-row">'
                       '<td class="retailer-name">A</td>'
                       '<td><a class="price-link" href="/x">$20.00</a></td></tr>')
    assert _run(tmp_path, data, site) == EXIT_ALARM


def test_main_alarms_when_a_denominator_collapses(tmp_path):
    """R10. A check that examined nothing must not report a pass."""
    data, _site = _full_corpus(tmp_path)
    empty = tmp_path / "emptysite"
    (empty / "plants").mkdir(parents=True)
    (empty / "guides").mkdir(parents=True)
    assert _run(tmp_path, data, str(empty), floors_off=False) == EXIT_ALARM
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert any("examined only 0" in a for a in report["alarms"])


def test_main_alarms_when_the_baseline_is_missing(tmp_path):
    """Without a baseline every known lead looks new, so novelty is not being
    measured. Silently treating that as 'all findings are new' would bury the
    real signal in accepted noise."""
    data, site = _full_corpus(tmp_path)
    assert _run(tmp_path, data, site, baseline=str(tmp_path / "nope.json")) == EXIT_ALARM
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert any("no readable baseline" in a for a in report["alarms"])


def test_main_never_reports_an_audit_it_did_not_run(tmp_path):
    """Every audit must appear in the JSON with its denominator, so a future
    digest can tell 'clean' from 'did not execute'."""
    data, site = _full_corpus(tmp_path)
    _run(tmp_path, data, site)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert set(report["audits"]) == {
        "A_cross_retailer", "B_two_nursery_pairs", "C_within_retailer_inversion",
        "D_snapshot_value_diff", "E_cross_page_agreement", "F_stock_consistency",
    }
    for name, audit in report["audits"].items():
        assert "denominator" in audit, name
        assert "denominator_floor" in audit, name


def test_update_baseline_accepts_current_findings_and_is_not_a_ci_path(tmp_path):
    data, site = _full_corpus(tmp_path, {"odd": [
        _entry("a", {"1gal": 10.0}), _entry("b", {"1gal": 90.0})]})
    baseline = tmp_path / "b.json"
    assert main(["--data-dir", data, "--site-dir", site,
                 "--baseline", str(baseline), "--update-baseline"]) == EXIT_OK
    accepted = json.loads(baseline.read_text(encoding="utf-8"))["accepted"]
    assert accepted["B_two_nursery_pairs"] == ["B|odd|1gal|a|b"]
    # D/E/F are never baselined — an invariant you can accept is not an
    # invariant, and D's identities change every run by construction.
    assert "D_snapshot_value_diff" not in accepted
    assert "E_cross_page_agreement" not in accepted
    assert "F_stock_consistency" not in accepted


# --------------------------------------------------------------------------
# the exit code itself. Mutant M10 (`EXIT_OK, EXIT_ALARM = 0, 0`) survived all
# 516 tests: every assertion above compares main()'s return to the IMPORTED
# symbol, i.e. the constant against itself. Nothing checked the number the
# workflow reads. These tests use literals on purpose — do not "tidy" them
# back into the symbols.
# --------------------------------------------------------------------------

def test_the_alarm_exit_code_is_literally_two():
    """scrape.yml reads `${PIPESTATUS[0]}` and only knows 0 from not-0. If
    EXIT_ALARM ever becomes 0 the alarm is silently disabled everywhere, and
    every symbol-vs-symbol assertion in this file still passes."""
    assert EXIT_OK == 0
    assert EXIT_ALARM == 2
    assert EXIT_ALARM != 0


def test_an_alarming_run_returns_a_nonzero_number(tmp_path):
    """The end-to-end version: a corpus that must alarm, asserted against the
    literal, not against whatever EXIT_ALARM happens to be bound to."""
    data, _site = _full_corpus(tmp_path)
    empty = tmp_path / "emptysite2"
    (empty / "plants").mkdir(parents=True)
    (empty / "guides").mkdir(parents=True)
    code = _run(tmp_path, data, str(empty), floors_off=False)
    assert code == 2
    assert code != 0


def test_a_clean_run_returns_literal_zero(tmp_path):
    """The other direction, so 'always alarms' is not a way to pass."""
    data, site = _full_corpus(tmp_path)
    assert _run(tmp_path, data, site) == 0


# --------------------------------------------------------------------------
# D's ALARM path through main(). Mutant M05 (D_CLUSTER 5 -> 50) also survived
# the suite: every D test above calls audit_d_snapshot_value_diff directly, so
# the threshold that decides whether the FGT positional-bug detector says
# anything at all was never executed.
# --------------------------------------------------------------------------

def _migrating(plant_seed):
    """One plant-retailer pair whose price leaves its old label: the exact
    signature from audit doc §4D, {1gal:p, 3gal:q} -> {3gal:p}."""
    price = 20.0 + plant_seed
    return [_entry("a", {"1gal": price, "3gal": price * 2}, ts=TS1),
            _entry("a", {"3gal": price}, ts=TS2)]


def test_main_alarms_when_a_cluster_of_prices_change_size_label(tmp_path):
    """Five migrations in one run is the positional-pairing regression. This
    is the audit the whole file exists for and nothing was exercising its
    alarm: measured over 253 real runs, the noisiest quiet run produced 3 and
    the smallest real event produced 6."""
    data, site = _full_corpus(tmp_path, {f"m{i}": _migrating(i) for i in range(5)})
    assert _run(tmp_path, data, site) == 2
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert len(report["audits"]["D_snapshot_value_diff"]["new_findings"]) == 5
    assert any("D_snapshot_value_diff" in a for a in report["alarms"]), report["alarms"]


def test_main_only_notices_migrations_below_the_cluster_threshold(tmp_path):
    """The other side of the threshold, so raising it cannot pass unnoticed.
    Four is inside the measured noise band (max 3 on a quiet run)."""
    data, site = _full_corpus(tmp_path, {f"m{i}": _migrating(i) for i in range(4)})
    assert _run(tmp_path, data, site) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert len(report["audits"]["D_snapshot_value_diff"]["new_findings"]) == 4
    assert report["alarms"] == []
    assert any("D_snapshot_value_diff" in n for n in report["notices"])


# --------------------------------------------------------------------------
# freshness — R5: the metric must not be satisfiable by the failure mode
# --------------------------------------------------------------------------

STALE_TS = "2026-06-15T11:00:00+00:00"      # ~1416h before TS2


def test_a_row_older_than_the_window_is_not_treated_as_this_run(tmp_path):
    history = load_price_history(str(_write(tmp_path, {
        "rose": [_entry("live", {"1gal": 20.0}, ts=TS2),
                 _entry("dead", {"1gal": 20.0}, ts=STALE_TS)],
    })))
    fresh, stale, meta = split_by_freshness(history)
    assert set(fresh) == {("rose", "live")}
    assert set(stale) == {("rose", "dead")}
    assert meta["pairs_total"] == 2 and meta["pairs_fresh"] == 1
    assert meta["pairs_stale"] == 1
    assert meta["retailers_with_no_fresh_row"] == ["dead"]


def test_a_row_inside_the_window_is_still_this_run(tmp_path):
    """The inverse. A retailer that missed one or two scrape runs must not be
    declared dead — measured: over 253 runs the only retailer ever absent for
    more than 2 consecutive runs was great-garden-plants' real 21-day outage."""
    recent = "2026-08-11T13:00:00+00:00"          # 22h before TS2
    history = load_price_history(str(_write(tmp_path, {
        "rose": [_entry("a", {"1gal": 20.0}, ts=TS2),
                 _entry("b", {"1gal": 20.0}, ts=recent)],
    })))
    fresh, stale, meta = split_by_freshness(history)
    assert len(fresh) == 2 and stale == {}
    assert meta["retailers_with_no_fresh_row"] == []
    assert FRESH_HOURS >= 24, "one missed scrape run is ~24h and must stay silent"


def test_an_undated_row_counts_as_stale_not_as_fresh(tmp_path):
    """R7 — re-derive the safe default. If a schema change drops `timestamp`,
    keeping the rows would leave every denominator looking healthy forever;
    dropping them collapses the denominators and trips the floor alarms."""
    undated = _entry("b", {"1gal": 20.0})
    del undated["timestamp"]
    history = load_price_history(str(_write(tmp_path, {
        "rose": [_entry("a", {"1gal": 20.0}, ts=TS2), undated],
    })))
    fresh, stale, meta = split_by_freshness(history)
    assert set(stale) == {("rose", "b")}
    assert meta["undated_rows"] == 1
    assert set(fresh) == {("rose", "a")}


def test_one_broken_clock_does_not_declare_every_other_retailer_dead(tmp_path):
    """A defect introduced by the freshness fix itself and found by probing
    split_by_freshness, not by review: freshness is measured relative to the
    newest row, so a single row dated 3000-01-01 dragged the cutoff forward
    and marked 2 of 3 retailers as having stopped contributing. Rows dated
    after this run started are excluded from the reference point and alarmed
    on separately."""
    history = load_price_history(str(_write(tmp_path, {"rose": [
        _entry("a", {"1gal": 20.0}, ts=TS2),
        _entry("b", {"1gal": 20.0}, ts=TS2),
        _entry("skew", {"1gal": 20.0}, ts="3000-01-01T00:00:00+00:00"),
    ]})))
    fresh, stale, meta = split_by_freshness(history)
    assert meta["retailers_with_no_fresh_row"] == []
    assert sorted(k[1] for k in fresh) == ["a", "b", "skew"]
    assert stale == {}
    assert meta["future_rows"] == [{"plant": "rose", "retailer": "skew"}]


@pytest.mark.parametrize("offset_hours,is_future", [(0.5, False), (6, True)])
def test_the_future_boundary_is_hours_not_centuries(tmp_path, offset_hours, is_future):
    """Pins FUTURE_SLACK_HOURS at a realistic scale. A row half an hour ahead
    is clock jitter between the runner and the commit; six hours ahead is a
    wrong clock. Written relative to now so it stays true whenever it runs."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    history = load_price_history(str(_write(tmp_path, {"rose": [
        _entry("a", {"1gal": 20.0}, ts=(now - timedelta(hours=1)).isoformat()),
        _entry("b", {"1gal": 20.0},
               ts=(now + timedelta(hours=offset_hours)).isoformat()),
    ]})))
    _fresh, _stale, meta = split_by_freshness(history)
    assert bool(meta["future_rows"]) is is_future
    assert meta["retailers_with_no_fresh_row"] == []


def test_a_future_dated_row_is_an_alarm_in_its_own_right(tmp_path):
    data, site = _full_corpus(tmp_path, {"skewed": [
        _entry("a", {"1gal": 20.0}, ts="3000-01-01T00:00:00+00:00")]})
    assert _run(tmp_path, data, site) == 2
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert any("dated after this run started" in a for a in report["alarms"]), \
        report["alarms"]


def test_a_stale_row_cannot_convict_a_live_one_in_audit_a(tmp_path):
    """The concrete harm, not just the bookkeeping: audit A compared a
    4-month-old price against today's as if the two were contemporaneous. With
    only two live rows on the tier there is no median, so A must not fire."""
    history = load_price_history(str(_write(tmp_path, {
        "rose": [_entry("a", {"3gal": 40.0}, ts=TS2),
                 _entry("b", {"3gal": 42.0}, ts=TS2),
                 _entry("c", {"3gal": 10.0}, ts=STALE_TS)],
    })))
    stale_denom, stale_findings = audit_a_cross_retailer(
        {k: v[-1] for k, v in history.items()})
    assert stale_denom == 3 and len(stale_findings) == 1, "pre-fix behaviour"

    fresh, _stale, _meta = split_by_freshness(history)
    denom, findings = audit_a_cross_retailer(fresh)
    assert denom == 0 and findings == []


def test_main_alarms_when_a_retailer_stops_contributing(tmp_path):
    """The red team's scenario, in miniature: an entire retailer's rows stop
    two months ago. Before this fix the run exited 0 with zero alarms and
    every denominator ABOVE its floor, because a dead retailer's last-ever row
    counted toward every denominator forever."""
    dead = {f"d{i}": [_entry("gone", {"1gal": 20.0}, ts=STALE_TS),
                      _entry("gone", {"1gal": 20.0}, ts=STALE_TS)]
            for i in range(3)}
    data, site = _full_corpus(tmp_path, dead)
    assert _run(tmp_path, data, site) == 2
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert any("gone" in a and "contributed no row" in a for a in report["alarms"]), \
        report["alarms"]
    assert report["freshness"]["retailers_with_no_fresh_row"] == ["gone"]


def test_main_reports_the_stale_count_with_its_denominator(tmp_path):
    """R10. A retailer that is alive but has one discontinued product is a
    notice with numbers, not an alarm — 5 of 282 pairs on the live corpus."""
    data, site = _full_corpus(tmp_path, {
        "old": [_entry("a", {"1gal": 20.0}, ts=STALE_TS)],
    })
    assert _run(tmp_path, data, site) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    fresh = report["freshness"]
    assert fresh["pairs_total"] == 4 and fresh["pairs_stale"] == 1
    assert fresh["pairs_fresh"] == 3
    assert fresh["fresh_window_hours"] == FRESH_HOURS
    assert fresh["retailers_with_no_fresh_row"] == []
    assert report["alarms"] == []
    assert any("stale" in n for n in report["notices"])


def test_stale_rows_do_not_inflate_the_denominators_in_the_report(tmp_path):
    """The mechanism of the original defect, asserted end to end. Two live
    nurseries and one that stopped two months ago: pre-fix that tier had three
    rows, so A claimed a median and B saw no pair at all. The stale row must
    change which audit even applies."""
    data, site = _full_corpus(tmp_path, {"rose": [
        _entry("live1", {"3gal": 40.0}, ts=TS2),
        _entry("live2", {"3gal": 42.0}, ts=TS2),
        _entry("gone", {"3gal": 10.0}, ts=STALE_TS),
    ]})
    _run(tmp_path, data, site)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["audits"]["A_cross_retailer"]["denominator"] == 0
    assert report["audits"]["B_two_nursery_pairs"]["denominator"] == 1
    assert report["audits"]["F_stock_consistency"]["counts"]["latest_rows"] == \
        report["freshness"]["pairs_fresh"]


def test_a_dead_retailers_last_migration_is_not_re_reported_forever(tmp_path):
    """D is stateless and not baselined, so a stale pair's migration would be
    re-found on every run until the end of time. Only fresh pairs are
    compared."""
    data, site = _full_corpus(tmp_path, {"ghost": [
        _entry("gone", {"1gal": 21.95, "3gal": 42.95}, ts="2026-06-14T11:00:00+00:00"),
        _entry("gone", {"3gal": 21.95}, ts=STALE_TS),
    ]})
    _run(tmp_path, data, site)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["audits"]["D_snapshot_value_diff"]["new_findings"] == []


@pytest.mark.parametrize("mutation,expect_silent", [
    ({"1gal": 20.0, "3gal": 40.0}, True),
    ({"1gal": 20.0, "3gal": 19.0}, True),   # 5% under: inside tolerance
    ({"1gal": 20.0, "3gal": 17.0}, False),  # 15% under: a real inversion
])
def test_c_boundary_is_where_calibration_put_it(tmp_path, mutation, expect_silent):
    latest = _latest(tmp_path, {"m": [_entry("a", mutation)]})
    _denom, findings = audit_c_within_retailer_inversion(latest)
    assert (findings == []) is expect_silent
