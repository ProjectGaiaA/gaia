"""Nightly offline audits — alarms, never a publish gate.

Runs the six audits proven in PRICE_AND_STOCK_AUDIT.md §4 against the
committed data and the freshly built site. No network. Nothing here can stop
a publish: the workflow runs it AFTER the commit step, and the worst it does
is turn the job red.

WHY THIS EXISTS
---------------
`runner.py` scores a retailer as healthy on products_found / products_expected,
so a WRONG price counts as a hit. A missing product trips an alarm; a wrong
price trips nothing. The FGT positional size/price bug lived for at least 15
days and was found by a human clicking around. Audit D below flags that exact
bug on 2026-07-27, the day it appeared (see CALIBRATION).

THE TWO SEVERITIES
------------------
Not everything found here means "something is broken":

  ALARM   an invariant that must hold was violated, or a check's denominator
          collapsed, or many heuristic findings appeared at once. Exit 2, and
          the workflow prints ::error::. This is meant to be rare.
  NOTICE  a heuristic audit produced a new lead. Recorded in the JSON report
          for the weekly digest; the job stays green. §4 of the audit doc is
          explicit that A/B/C "return a work-list, not a verdict", and a
          work-list that turns the build red every week gets ignored.

RULE ZERO (audit doc §2) — never let the thing under test produce its own
baseline. Where each audit's ground truth comes from:

  A,B,C   cross-checks between INDEPENDENT retailers, or between different
          size tiers of the same retailer. No single scraper's output is
          trusted; the comparison is between separately-fetched sources.
  D       the previous run's committed rows in data/prices/*.jsonl. This is
          the same scraper, so D proves CHANGE, not correctness — which is
          exactly what a snapshot diff is for. It cannot tell you which
          snapshot is right, only that a price moved to a different label.
          NOTE: D deliberately does NOT use data/prev_manifest.json. That file
          is written by the pre-scrape snapshot step and is NOT in the commit
          step's `git add` list, so it does not exist on a fresh checkout and
          would silently give every audit a denominator of 0.
  E       page-against-page. Each quoted price is compared to the TARGET
          page's own schema.org lowPrice, so build.py's in-memory state is
          never the baseline.
  F       the rendered HTML, not build.py's variables (R4: test the artifact).

R10 — every audit reports its denominator, and a denominator below a
calibrated floor is itself an ALARM. A check that finds nothing may have
checked nothing: a cross-page audit here once reported `checked=0
mismatches=0` because of a wrong CSS selector.

CALIBRATION (R9 — measured, not guessed)
----------------------------------------
Replayed against the committed corpus: 130 scrape days, 2026-04-03 ..
2026-08-12, 61,429 row-to-row transitions. Full method in the commit message.
Numbers below are "how often would this have fired on real history".

  A cross-retailer, ratio vs median of others
      2.0x -> 3 standing findings, a new one on 11 of the last 60 nights
      2.5x -> 1 standing finding,  a new one on  5 of the last 60 nights
      3.0x -> 0 standing findings, a new one on  1 of the last 60 nights
      CHOSEN 2.5 — 2.0 is too chatty to read every morning; 3.0 misses the
      class of defect that started this (a 3gal priced like a 1gal is ~2x).

  B two-nursery pairs (no median exists, so neither side is convicted)
      2.0x -> 16 of the last 60 nights produce a new pair
      2.5x ->  5 of the last 60 nights
      3.0x ->  2 of the last 60 nights
      CHOSEN 2.5 — also the figure PRICE_AND_STOCK_AUDIT.md §4B specifies,
      and independently the knee of the measured curve.

  C within-retailer inversion (bigger container priced under a smaller one)
      0%   tolerance -> 15 standing, new on 7 of the last 60 nights
      10%  tolerance -> 12 standing, new on 2 of the last 60 nights
      CHOSEN 10% — a larger pot a few cents cheaper is a rounding artefact of
      a sale, not a mapping defect.

  A/B/C cluster threshold: max NEW findings in any single night over all 129
      transitions was 3 (A:2, B:3, C:3). CHOSEN 5 -> zero false alarms on
      129 nights, while a systemic mapping regression produces dozens.

  D tier-label migration, strict (value must have LEFT its old label)
      per-run distribution over 128 days:
        0 migrations : 106 days      3 : 2 days      15 : 1 day
        1 migration  :  10 days      4 : 1 day       22 : 2 days
        2 migrations :   4 days      8 : 1 day       36 : 1 day
      Clean gap between 4 and 8. CHOSEN 5 -> fires on 5 of 128 days (3.9%),
      and every one of those five is a confirmed FGT positional-shift event:
        2026-07-27 (22)  delaware-valley-white-azalea {1gal:21.95,3gal:42.95}
                         -> {3gal:21.95}; fuji-apple-tree slid two labels
        2026-07-28 (22)  same event persisting
        2026-08-07 ( 8)  coral-bark-japanese-maple, green-giant-arborvitae
        2026-08-11 (15)  the fix landing
        2026-08-12 (36)  the fix landing
      Both 07-27 and 08-07 are the worked examples in audit doc §4D. Zero
      known false positives at this threshold.
      Migrations below the threshold are still RECORDED for the digest.

  E cross-page agreement: 565 quotes checked, 0 mismatches. This is an exact
      invariant, so the threshold is 0 — any mismatch alarms.

  F stock sweeps: all four currently 0 violations. Exact invariants, so any
      violation alarms. See F2's denominator note below — one of these
      currently examines nothing, which is reported as a finding in its own
      right rather than as a pass.

  Denominator floors are ~50% of the 60-day minimum, which absorbs catalogue
  churn but catches a selector or key change collapsing a check to nothing:
      A  min 90 over 60 days -> floor  45
      B  min 139              -> floor  70
      C  min 185              -> floor  90
      E  565 today            -> floor 280
      D/F floors from today's measurement, halved.

THE BASELINE FILE
-----------------
A/B/C findings are stable identities (plant, tier, retailer) with the PRICE
deliberately left out, so a known lead does not re-alarm every time its price
moves a dollar. data/audit_baseline.json holds the accepted set; only findings
outside it are new. CI never regenerates it — `--update-baseline` is a
deliberate human act, because an auto-refreshing baseline would absorb the
next regression on the night it appeared and then report silence forever.
"""

import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

EXIT_OK, EXIT_ALARM = 0, 2

# --- thresholds, all justified in CALIBRATION above ---
A_RATIO = 2.5
B_RATIO = 2.5
C_TOLERANCE = 0.10
NEW_CLUSTER = 5          # new A/B/C findings in one run before it is an ALARM
D_CLUSTER = 5            # tier migrations in one run before it is an ALARM

DENOM_FLOOR = {
    "A_cross_retailer": 45,
    "B_two_nursery_pairs": 70,
    "C_within_retailer_inversion": 90,
    "D_snapshot_value_diff": 120,
    "E_cross_page_agreement": 280,
    "F_stock_consistency": 140,
}

# Container sizes in true ascending order. Bare-root vs potted inversions are
# real pricing, not defects, so only same-family containers are compared.
CONTAINER_ORDER = ["3inch", "4inch", "6inch", "quart", "1gal", "2gal", "3gal",
                   "5gal", "7gal", "10gal", "15gal"]


# --------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------

def _sizes(entry):
    """{tier: price} for real, positive, non-bool prices. 'default' excluded —
    it is the scraper's fallback when it cannot identify a size, so comparing
    it across retailers compares unlike things."""
    out = {}
    for tier, info in (entry.get("sizes") or {}).items():
        if not isinstance(info, dict) or tier == "default":
            continue
        price = info.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if price > 0:
            out[tier] = float(price)
    return out


def load_price_history(data_dir):
    """(plant, retailer) -> [entry, ...] in file order (append-only, so
    chronological). Returns the raw entries; callers pick what they need."""
    history = collections.defaultdict(list)
    prices_dir = os.path.join(data_dir, "prices")
    for path in sorted(glob.glob(os.path.join(prices_dir, "*.jsonl"))):
        plant = os.path.basename(path)[:-6]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue          # the data gate quarantines these
                if isinstance(entry, dict) and entry.get("retailer_id"):
                    history[(plant, entry["retailer_id"])].append(entry)
    return history


# --------------------------------------------------------------------------
# audits. Each returns (denominator, [finding, ...]); a finding is a dict with
# a stable "id" used for baseline matching and a human "detail".
# --------------------------------------------------------------------------

def audit_a_cross_retailer(latest):
    """A. Same plant, same declared size, 3+ nurseries: compare each against
    the median of the OTHERS. A '3 gallon' costing a third of everyone else's
    3 gallon is probably not a 3 gallon."""
    by_plant = collections.defaultdict(lambda: collections.defaultdict(list))
    for (plant, rid), entry in latest.items():
        for tier, price in _sizes(entry).items():
            by_plant[plant][tier].append((rid, price))

    denom, findings = 0, []
    for plant, tiers in sorted(by_plant.items()):
        for tier, rows in sorted(tiers.items()):
            if len(rows) < 3:
                continue
            denom += len(rows)
            for rid, price in rows:
                others = [p for r, p in rows if r != rid]
                med = statistics.median(others)
                if med <= 0:
                    continue
                ratio = price / med
                if ratio >= A_RATIO or ratio <= 1.0 / A_RATIO:
                    findings.append({
                        "id": f"A|{plant}|{tier}|{rid}",
                        "detail": (f"{plant} {tier} at {rid} is ${price:.2f} vs "
                                   f"${med:.2f} median of {len(others)} other "
                                   f"nurseries ({ratio:.2f}x)"),
                    })
    return denom, findings


def audit_b_two_nursery_pairs(latest):
    """B. Most tiers carry only 2 nurseries, so no median exists. Neither side
    can be convicted, but a wide gap on a like-for-like size is a lead. The
    first version of this audit skipped these and therefore could not see the
    azalea that started the whole investigation — do not skip them."""
    by_plant = collections.defaultdict(lambda: collections.defaultdict(list))
    for (plant, rid), entry in latest.items():
        for tier, price in _sizes(entry).items():
            by_plant[plant][tier].append((rid, price))

    denom, findings = 0, []
    for plant, tiers in sorted(by_plant.items()):
        for tier, rows in sorted(tiers.items()):
            if len(rows) != 2:
                continue
            denom += 1
            (r1, p1), (r2, p2) = sorted(rows)
            lo, hi = sorted([p1, p2])
            if lo > 0 and hi / lo >= B_RATIO:
                findings.append({
                    "id": f"B|{plant}|{tier}|{r1}|{r2}",
                    "detail": (f"{plant} {tier}: {r1} ${p1:.2f} vs {r2} "
                               f"${p2:.2f} ({hi / lo:.1f}x apart)"),
                })
    return denom, findings


def audit_c_within_retailer_inversion(latest):
    """C. One retailer pricing a larger container BELOW a smaller one."""
    denom, findings = 0, []
    for (plant, rid), entry in sorted(latest.items()):
        present = sorted(
            (CONTAINER_ORDER.index(t), t, p)
            for t, p in _sizes(entry).items() if t in CONTAINER_ORDER
        )
        if len(present) >= 2:
            denom += len(present) - 1
        for i in range(len(present) - 1):
            (_, small, p_small), (_, large, p_large) = present[i], present[i + 1]
            if p_large < p_small * (1.0 - C_TOLERANCE):
                findings.append({
                    "id": f"C|{plant}|{rid}|{small}|{large}",
                    "detail": (f"{plant} at {rid}: {large} ${p_large:.2f} is "
                               f"cheaper than {small} ${p_small:.2f}"),
                })
    return denom, findings


def audit_d_snapshot_value_diff(history):
    """D. A price that sat under one size label now sits under a DIFFERENT
    one for the same plant+retailer. This is the positional-pairing signature:

        delaware-valley-white-azalea  OLD {1gal:21.95, 3gal:42.95}
                                      NEW {3gal:21.95}

    A pure shift leaves the tier COUNT unchanged, so counting tiers sees
    nothing. Compare values, not counts.

    'strict' — the value must have LEFT its old label. A retailer that simply
    prices two sizes the same is a coincidence, not a shift, and dropping
    those took the quiet-night rate from 106/128 to 108/128 with no loss of
    the real events.
    """
    denom, findings = 0, []
    for (plant, rid), entries in sorted(history.items()):
        if len(entries) < 2:
            continue
        prev, cur = _sizes(entries[-2]), _sizes(entries[-1])
        if not prev or not cur:
            continue
        denom += 1
        prev_homes = collections.defaultdict(set)
        for tier, price in prev.items():
            prev_homes[round(price, 2)].add(tier)
        for tier, price in sorted(cur.items()):
            homes = prev_homes.get(round(price, 2))
            if not homes or tier in homes:
                continue
            if any(round(cur.get(h, -1.0), 2) == round(price, 2) for h in homes):
                continue          # still at its old label too: duplicate price
            old = sorted(homes)[0]
            findings.append({
                "id": f"D|{plant}|{rid}|{old}->{tier}",
                "detail": (f"{plant} at {rid}: ${price:.2f} was the {old} "
                           f"price, now labelled {tier}"),
            })
    return denom, findings


def audit_e_cross_page_agreement(site_dir):
    """E. Every price one page quotes about ANOTHER page must equal that
    page's own schema.org lowPrice. Page-against-page, so build.py's internal
    state is never the baseline. This codebase has had widget-vs-page
    divergence three times."""
    from bs4 import BeautifulSoup

    own_low = {}
    for path in glob.glob(os.path.join(site_dir, "plants", "*.html")):
        with open(path, encoding="utf-8") as fh:
            match = re.search(r'"lowPrice":\s*([0-9.]+)', fh.read())
        if match:
            own_low[os.path.basename(path)] = float(match.group(1))

    denom, findings = 0, []
    for sub, label in (("plants", "product"), ("guides", "guide")):
        for path in sorted(glob.glob(os.path.join(site_dir, sub, "*.html"))):
            with open(path, encoding="utf-8") as fh:
                soup = BeautifulSoup(fh.read(), "html.parser")
            for anchor in soup.find_all("a", href=True):
                span = anchor.select_one(".similar-price, .related-price")
                if not span:
                    continue
                target = os.path.basename(anchor["href"].split("#")[0])
                if target not in own_low:
                    continue
                match = re.search(r"([0-9]+\.[0-9]{2})", span.get_text())
                if not match:
                    continue
                denom += 1
                quoted, actual = float(match.group(1)), own_low[target]
                if abs(quoted - actual) > 0.005:
                    src = os.path.basename(path)
                    findings.append({
                        "id": f"E|{label}|{src}|{target}",
                        "detail": (f"{label} {src} quotes ${quoted:.2f} for "
                                   f"{target}, whose own lowPrice is "
                                   f"${actual:.2f}"),
                    })
    return denom, findings


def audit_f_stock_consistency(site_dir, latest):
    """F. Four stock sweeps. The first three read the rendered HTML rather
    than build.py's variables, because a scraper fix without a display fix is
    inert — feeding true sold-out data through the unfixed display layer once
    produced a byte-identical page.

    Each sub-sweep carries its own denominator. Two of them can legitimately
    have a denominator of 0 (no sold-out rows exist), and that is reported as
    'examined nothing', not as a pass.
    """
    from bs4 import BeautifulSoup

    findings = []
    counts = {
        "pages": 0,
        "table_rows": 0,
        "sold_out_rows": 0,
        "sold_out_price_cells": 0,
        "mobile_price_links": 0,
        "schema_instock_pages": 0,
        "latest_rows": len(latest),
    }

    for path in sorted(glob.glob(os.path.join(site_dir, "plants", "*.html"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        soup = BeautifulSoup(html, "html.parser")
        counts["pages"] += 1

        table = soup.select_one("table.comparison-table")
        rows = table.select("tbody tr") if table else []
        counts["table_rows"] += len(rows)

        # F1 — a row the site calls sold out that still offers a buy link.
        for row in rows:
            if "sold-out-row" not in (row.get("class") or []):
                continue
            counts["sold_out_rows"] += 1
            if row.select("a.price-link"):
                findings.append({
                    "id": f"F1|{name}|{row.select_one('.retailer-name').get_text(strip=True) if row.select_one('.retailer-name') else '?'}",
                    "detail": f"{name}: a sold-out row still renders a clickable price",
                })

        # F2 — a size rendered sold out that is simultaneously promoted.
        # `.price-soldout` is emitted for any size where is_buyable is false.
        for cell in soup.select("span.price-soldout"):
            counts["sold_out_price_cells"] += 1
            if cell.select(".best-price"):
                findings.append({
                    "id": f"F2|{name}",
                    "detail": f"{name}: a sold-out size is flagged as the best price",
                })

        # F2b — the mobile best-prices table must never offer a price the
        # desktop table refuses to link. Both render from the same build.py
        # flags, but they are separate template branches and have disagreed
        # before (Jinja's `==` treating 0.0 as False).
        buyable = set()
        for link in soup.select("table.comparison-table a.price-link"):
            match = re.search(r"([0-9]+\.[0-9]{2})", link.get_text())
            if match:
                buyable.add(match.group(1))
        for link in soup.select("a.bp-price-link"):
            counts["mobile_price_links"] += 1
            match = re.search(r"([0-9]+\.[0-9]{2})", link.get_text())
            if match and match.group(1) not in buyable:
                findings.append({
                    "id": f"F2b|{name}|{match.group(1)}",
                    "detail": (f"{name}: mobile table offers ${match.group(1)} "
                               f"which the desktop table does not link"),
                })

        # F4 — schema claims InStock while no size on the page is buyable.
        match = re.search(r'"availability":\s*"https://schema\.org/(\w+)"', html)
        if match and match.group(1) == "InStock":
            counts["schema_instock_pages"] += 1
            if not soup.select("table.comparison-table a.price-link"):
                findings.append({
                    "id": f"F4|{name}",
                    "detail": f"{name}: schema says InStock but no size is buyable",
                })

    # F3 — retailers whose per-variant availability is uniformly None. Not a
    # defect on its own (audit doc §3b: unknown is the majority and treating
    # it as sold out takes the catalogue dark), but a retailer that USED to
    # report booleans and now reports none has lost its stock source. Reported
    # with counts so the digest can watch the trend; never an alarm here.
    per_retailer = collections.defaultdict(collections.Counter)
    for (_plant, rid), entry in latest.items():
        for info in (entry.get("sizes") or {}).values():
            if isinstance(info, dict):
                per_retailer[rid][str(info.get("available"))] += 1
    counts["retailer_variant_availability"] = {
        rid: dict(c) for rid, c in sorted(per_retailer.items())
    }
    counts["retailers_all_unknown_stock"] = sorted(
        rid for rid, c in per_retailer.items() if set(c) == {"None"}
    )

    denom = counts["table_rows"]
    return denom, findings, counts


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def load_baseline(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return {k: set(v) for k, v in data.get("accepted", {}).items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nightly offline audits (alarm only).")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--baseline", default=None,
                        help="default: <data-dir>/audit_baseline.json")
    parser.add_argument("--json-out", default=None,
                        help="default: <data-dir>/audit_report.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="rewrite the baseline from the current findings. "
                             "A deliberate human act — CI must never do this.")
    args = parser.parse_args(argv)

    baseline_path = args.baseline or os.path.join(args.data_dir, "audit_baseline.json")
    report_path = args.json_out or os.path.join(args.data_dir, "audit_report.json")

    history = load_price_history(args.data_dir)
    latest = {key: entries[-1] for key, entries in history.items() if entries}

    a_denom, a_find = audit_a_cross_retailer(latest)
    b_denom, b_find = audit_b_two_nursery_pairs(latest)
    c_denom, c_find = audit_c_within_retailer_inversion(latest)
    d_denom, d_find = audit_d_snapshot_value_diff(history)
    e_denom, e_find = audit_e_cross_page_agreement(args.site_dir)
    f_denom, f_find, f_counts = audit_f_stock_consistency(args.site_dir, latest)

    audits = {
        "A_cross_retailer": {
            "what": f"same plant+size at 3+ nurseries, >={A_RATIO}x off the median of the others",
            "denominator": a_denom, "denominator_unit": "priced rows at tiers with 3+ nurseries",
            "findings": a_find, "baselined": True, "exact_invariant": False,
        },
        "B_two_nursery_pairs": {
            "what": f"same plant+size at exactly 2 nurseries, >={B_RATIO}x apart",
            "denominator": b_denom, "denominator_unit": "two-nursery tiers",
            "findings": b_find, "baselined": True, "exact_invariant": False,
        },
        "C_within_retailer_inversion": {
            "what": f"larger container >{C_TOLERANCE:.0%} cheaper than the next smaller one",
            "denominator": c_denom, "denominator_unit": "adjacent container pairs",
            "findings": c_find, "baselined": True, "exact_invariant": False,
        },
        "D_snapshot_value_diff": {
            "what": "a price that moved to a different size label since the previous run",
            "denominator": d_denom, "denominator_unit": "plant-retailer rows with a previous run to compare",
            "findings": d_find, "baselined": False, "exact_invariant": False,
        },
        "E_cross_page_agreement": {
            "what": "a price quoted about another page vs that page's own lowPrice",
            "denominator": e_denom, "denominator_unit": "cross-page price quotes",
            "findings": e_find, "baselined": False, "exact_invariant": True,
        },
        "F_stock_consistency": {
            "what": "sold-out rows/sizes that are still offered, and InStock schema with nothing buyable",
            "denominator": f_denom, "denominator_unit": "comparison-table rows",
            "findings": f_find, "baselined": False, "exact_invariant": True,
            "counts": f_counts,
        },
    }

    if args.update_baseline:
        accepted = {
            name: sorted(f["id"] for f in a["findings"])
            for name, a in audits.items() if a["baselined"]
        }
        payload = {
            "_comment": (
                "Accepted A/B/C findings. Anything not listed here is NEW and "
                "gets reported. Regenerated only by a human running "
                "scripts/nightly_audits.py --update-baseline; CI never does, "
                "because a self-refreshing baseline absorbs the next "
                "regression on the night it appears and reports silence "
                "forever afterwards."
            ),
            "generated": datetime.now(timezone.utc).isoformat(),
            "accepted": accepted,
        }
        with open(baseline_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        total = sum(len(v) for v in accepted.values())
        print(f"Baseline rewritten: {baseline_path} ({total} accepted findings)")
        return EXIT_OK

    baseline = load_baseline(baseline_path)
    alarms, notices = [], []

    if baseline is None:
        alarms.append(
            f"no readable baseline at {baseline_path} — every heuristic "
            f"finding would look new, so A/B/C novelty is not being measured"
        )
        baseline = {}

    print("=" * 74)
    print("NIGHTLY OFFLINE AUDITS — alarms only, publishing already happened")
    print("=" * 74)

    for name, audit in audits.items():
        denom = audit["denominator"]
        floor = DENOM_FLOOR[name]
        known = baseline.get(name, set()) if audit["baselined"] else set()
        new = [f for f in audit["findings"] if f["id"] not in known]
        audit["new_findings"] = new
        audit["known_findings"] = len(audit["findings"]) - len(new)

        print()
        print(f"[{name}] {audit['what']}")
        print(f"   examined : {denom} {audit['denominator_unit']} (floor {floor})")
        print(f"   findings : {len(audit['findings'])} total, "
              f"{audit['known_findings']} already accepted, {len(new)} new")

        # R10: a denominator that collapsed means the check stopped checking.
        if denom < floor:
            alarms.append(
                f"{name} examined only {denom} {audit['denominator_unit']} "
                f"(floor {floor}) — the check may be looking at the wrong thing"
            )

        for finding in new[:10]:
            print(f"     - {finding['detail']}")
        if len(new) > 10:
            print(f"     ... and {len(new) - 10} more (full list in the JSON report)")

        if not new:
            continue
        if audit["exact_invariant"]:
            alarms.append(f"{name}: {len(new)} violation(s) of an invariant that must be 0")
        elif name == "D_snapshot_value_diff":
            if len(new) >= D_CLUSTER:
                alarms.append(
                    f"{name}: {len(new)} prices moved to a different size label "
                    f"in one run (>= {D_CLUSTER}) — positional size/price "
                    f"pairing regression"
                )
            else:
                notices.append(f"{name}: {len(new)} isolated tier migration(s), below the {D_CLUSTER} cluster threshold")
        elif len(new) >= NEW_CLUSTER:
            alarms.append(
                f"{name}: {len(new)} new findings in one run (>= {NEW_CLUSTER}) "
                f"— that many at once is a regression, not drift"
            )
        else:
            notices.append(f"{name}: {len(new)} new lead(s) for the weekly digest")

    # F's own denominators, spelled out. Two of these can be a legitimate 0,
    # and 0 examined must not read as 0 problems.
    print()
    print("[F_stock_consistency] sub-denominators")
    for key in ("pages", "table_rows", "sold_out_rows", "sold_out_price_cells",
                "mobile_price_links", "schema_instock_pages", "latest_rows"):
        print(f"   {key:26s} {f_counts[key]}")
    if f_counts["retailers_all_unknown_stock"]:
        print(f"   retailers with no per-variant stock data at all: "
              f"{', '.join(f_counts['retailers_all_unknown_stock'])}")
    if f_counts["sold_out_price_cells"] == 0:
        notices.append(
            "F: 0 sold-out price cells exist site-wide, so the variant-level "
            "sold-out display path was NOT exercised this run (examined "
            "nothing, which is not the same as found nothing)"
        )

    summary = {
        "audit": "nightly_offline",
        "generated": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "A_ratio": A_RATIO, "B_ratio": B_RATIO, "C_tolerance": C_TOLERANCE,
            "new_cluster": NEW_CLUSTER, "d_cluster": D_CLUSTER,
            "denominator_floors": DENOM_FLOOR,
        },
        "alarms": alarms,
        "notices": notices,
        "audits": {
            name: {
                "what": a["what"],
                "denominator": a["denominator"],
                "denominator_unit": a["denominator_unit"],
                "denominator_floor": DENOM_FLOOR[name],
                "total_findings": len(a["findings"]),
                "known_findings": a["known_findings"],
                "new_findings": a["new_findings"],
                **({"counts": a["counts"]} if "counts" in a else {}),
            }
            for name, a in audits.items()
        },
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print()
    print("-" * 74)
    print(f"JSON report: {report_path}")
    for notice in notices:
        print(f"::notice::audit: {notice}")
    for alarm in alarms:
        print(f"::error::audit: {alarm}")
    if alarms:
        print(f"\n{len(alarms)} ALARM(S). Data was already published — this is a "
              f"signal to investigate, not a failed publish.")
        return EXIT_ALARM
    print(f"\nNo alarms. {len(notices)} notice(s) recorded for the weekly digest.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
