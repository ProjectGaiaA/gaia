"""Audit D2' — did we publish a single-state price as a national one?

An offline alarm, never a publish gate. Same two-severity contract and the
same exit codes as scripts/nightly_audits.py (0 = OK, 2 = ALARM), and the
same RULE ZERO: the thing under test must not produce its own baseline.

WHAT THIS CHECKS THAT THE SCRAPER DOES NOT
------------------------------------------
scrapers/shopify.py withholds an FGT product whose size labels use the "N-M
ft." vocabulary. That predicate is a PROXY. "ft." is FGT's canonical catalog
spelling — 47 of the 58 non-region-restricted variants in the committed
reference are titled that way — and the reason it works on the storefront is
that the
current theme rewrites it to "feet" on the national render and leaves it
alone on the regional one. A theme change breaks the proxy in either
direction, silently.

This audit checks the DURABLE fact instead: whether the prices we actually
published match the retailer's own region-restricted variants rather than its
national ones. It reads them from the UCP catalog API capture committed at
data/regional_reference/<retailer>.json — a DIFFERENT endpoint from the
storefront scrape it is judging, which is what makes it an independent
oracle rather than a restatement.

THE PREDICATE (all four clauses, all required)
----------------------------------------------
For one (plant, FGT row) and one region R the retailer defines for that
plant:

  1. PRICE      every priced tier in the row matches R's twin on BOTH the
                payable price and the was_price. Both, because a regional
                variant frequently shares the national payable price and
                differs only in the strikethrough — meyer-lemon-tree's
                2-3 ft is 9895 in the national catalogue and 9895 in the CA
                one, and only the 14495 list price separates them.
  2. TIER SET   the row's tier set EQUALS the set of R's tiers the catalog
                reports as available. Not a subset: a subset is what an
                ordinary sold-out day looks like. Equality is what says "this
                page rendered R's catalogue and nothing else".
  3. CONTRAST   at least one tier where R's price differs from the national
                price. Without it the two catalogues are indistinguishable
                at these tiers, so "we published the regional price" is a
                claim the data cannot support, and asserting it anyway is how
                an audit invents findings.
  4. NON-EMPTY  the row priced at least one tier. An empty row publishes
                nothing and cannot have published a regional price.

R is whatever the capture says. Regions are read from the reference's own
`region_restricted` values — the corpus already contains CA and FL and the
retailer may add more, so nothing here names a state.

CAPTURE-AGE HARD GATE (why a stale reference is an ALARM, not a pass)
---------------------------------------------------------------------
Clauses 1 and 3 compare live prices to captured ones, so they decay: FGT
moves prices within days, and a month-old reference turns "we published a CA
price" into "these numbers no longer agree", which is not the same claim.

Past MAX_REFERENCE_AGE_DAYS the price clauses are DISABLED and every plant is
reported `reference stale, not checked`. The run then exits EXIT_ALARM, NOT
EXIT_OK. This is deliberate and it is the same rule as nightly_audits.py's
R10 — "a check that finds nothing may have checked nothing", so a collapsed
denominator is itself an alarm. An audit that goes green because it stopped
looking is worse than no audit, because it also stops anybody else looking.
Re-capture the reference (see UCP_API_RUNBOOK.md) to clear it.
"""

import argparse
import collections
import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXIT_OK, EXIT_ALARM = 0, 2

# Beyond this the price clauses stop being evidence. Seven days spans a full
# weekly promo cycle, which is the shortest period over which FGT has been
# observed to reprice.
MAX_REFERENCE_AGE_DAYS = 7

# R10 — "a check that finds nothing may have checked nothing". The floor here
# is DERIVED from the reference rather than written down as a constant,
# because a constant would be a guess: only the plants the capture holds BOTH
# national and region-restricted variants for are answerable at all, and that
# count moves every time the capture is refreshed. At the 2026-08-20 capture
# it is 7 of the 9 plants the capture holds — a hand-picked "20" would have
# turned every clean run red for a reason that has nothing to do with the
# data. (The 9 is the size of a TARGETED capture, not of the catalogue: FGT
# is scraped across 66 plants, so the audit's reach against the retailer is
# 7 of 66, not 7 of 9. See _print_scope.)
#
# So the audit reports its own coverage and alarms only when the denominator
# has actually collapsed: nothing was checked, or the reference cannot answer
# for anybody.

RETAILER_ID = "fast-growing-trees"


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def load_reference(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def reference_age_days(reference, now=None):
    """Age of the capture in days, or None if it carries no usable date."""
    raw = (reference.get("provenance") or {}).get("captured_at")
    if not raw:
        return None
    try:
        captured = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if captured.tzinfo is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - captured).total_seconds() / 86400.0


def _row_gap_days(row, reference):
    """Days between a row's timestamp and the capture, or None."""
    raw_row = row.get("timestamp")
    raw_cap = (reference.get("provenance") or {}).get("captured_at")
    if not raw_row or not raw_cap:
        return None
    try:
        a = datetime.fromisoformat(str(raw_row).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(raw_cap).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if a.tzinfo is None or b.tzinfo is None:
        return None
    return (b - a).total_seconds() / 86400.0


def load_rows(data_dir, retailer_id, latest_only=True):
    """[(plant, row)] for one retailer, newest last within each plant."""
    out = []
    for path in sorted(glob.glob(os.path.join(data_dir, "prices", "*.jsonl"))):
        plant = os.path.basename(path)[:-6]
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue          # the data gate quarantines these
                if isinstance(row, dict) and row.get("retailer_id") == retailer_id:
                    rows.append(row)
        if not rows:
            continue
        out.extend((plant, r) for r in (rows[-1:] if latest_only else rows))
    return out


def priced_tiers(row):
    """{tier: (price_cents, was_cents_or_None)} for real, positive prices."""
    out = {}
    for tier, info in (row.get("sizes") or {}).items():
        if not isinstance(info, dict):
            continue
        price = info.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if price <= 0:
            continue
        was = info.get("was_price")
        was_cents = None
        if isinstance(was, (int, float)) and not isinstance(was, bool) and was > 0:
            was_cents = int(round(was * 100))
        out[tier] = (int(round(price * 100)), was_cents)
    return out


# --------------------------------------------------------------------------
# the predicate
# --------------------------------------------------------------------------


def _twin_matches(observed, variant):
    """One tier: does the published cell match this catalog variant exactly?

    `variant` is None when two variants normalised onto the same tier — an
    ambiguous reference, which cannot confirm anything and must not be
    silently treated as agreement.
    """
    if not variant:
        return False
    price_cents, was_cents = observed
    if variant.get("price_cents") != price_cents:
        return False
    listed = variant.get("list_price_cents")
    if was_cents is None:
        # The scraper only emits was_price when the list price is strictly
        # above the payable one, so "no was_price" must mean the catalog
        # agrees there is no discount here.
        return listed is None or listed <= price_cents
    return listed == was_cents


def evaluate_row(plant_ref, row, check_prices=True):
    """Decide D2' for one row. Returns (verdict, detail).

    verdict is one of:
      'fired'        the row published this region's catalogue
      'clean'        checked against every region, and it matched none
      'empty'        clause 4: the row prices nothing, so nothing was
                     published and there is nothing to judge. Kept OUT of
                     the checked denominator — counting a withheld row as a
                     clean check is how an audit reports coverage it does
                     not have.
      'not_checked'  the reference cannot answer for this plant/row
    """
    observed = priced_tiers(row)
    if not observed:
        return "empty", {"reason": "row prices nothing"}       # clause 4

    if not check_prices:
        return "not_checked", {"reason": "reference stale, not checked"}

    national = plant_ref.get("national") or {}
    regional = plant_ref.get("regional") or {}
    if not regional:
        return "not_checked", {
            "reason": "no region-restricted variants in the reference for this plant"
        }
    if not national:
        return "not_checked", {
            "reason": "no national variants in the reference for this plant"
        }

    for region in sorted(regional):
        twins = regional[region]
        # clause 2 — the row's tiers are exactly this region's live tiers.
        available = {t for t, v in twins.items() if v and v.get("available") is True}
        if available != set(observed):
            continue
        # clause 1 — every tier agrees on price AND was_price.
        if not all(_twin_matches(observed[t], twins.get(t)) for t in observed):
            continue
        # clause 3 — at least one tier where the two catalogues differ.
        contrast = [
            t for t in observed
            if national.get(t)
            and twins.get(t)
            and national[t].get("price_cents") != twins[t].get("price_cents")
        ]
        if not contrast:
            continue
        return "fired", {
            "region": region,
            "tiers": sorted(observed),
            "row_timestamp": row.get("timestamp"),
            "contrast_tiers": sorted(contrast),
            "published_cents": {t: observed[t][0] for t in sorted(observed)},
            "region_cents": {
                t: twins[t].get("price_cents") for t in sorted(observed)
            },
            "national_cents": {
                t: (national.get(t) or {}).get("price_cents")
                for t in sorted(observed)
            },
        }
    return "clean", {"reason": "no region's catalogue matches this row"}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def run(data_dir, reference_path, now=None, latest_only=True):
    """Returns (exit_code, report_dict). No printing — the caller prints."""
    reference = load_reference(reference_path)
    age = reference_age_days(reference, now=now)
    stale = age is None or age > MAX_REFERENCE_AGE_DAYS
    check_prices = not stale

    plants_ref = reference.get("plants") or {}
    rows = load_rows(data_dir, reference.get("retailer_id", RETAILER_ID), latest_only)

    # The reference's OWN coverage: the plants it can answer for at all.
    answerable = {
        p for p, ref in plants_ref.items()
        if (ref.get("national") or {}) and (ref.get("regional") or {})
    }

    findings = []
    counts = collections.Counter()
    not_checked = []
    for plant, row in rows:
        plant_ref = plants_ref.get(plant)
        if plant_ref is None:
            counts["not_checked"] += 1
            not_checked.append({
                "plant": plant,
                "timestamp": row.get("timestamp"),
                "reason": "plant absent from the reference capture",
            })
            continue
        verdict, detail = evaluate_row(plant_ref, row, check_prices=check_prices)
        counts[verdict] += 1
        if verdict == "fired":
            # How far the ROW sits from the capture, which is a different
            # question from how far the CAPTURE sits from now. The age gate
            # above protects the default (newest-row) mode, where every row
            # is hours old. --all-history deliberately compares months-old
            # rows to one fresh capture, and a price that agreed in April
            # and still agrees in August may simply not have moved. Findings
            # outside the window are marked `lead`, not `confirmed`, so a
            # replay cannot be quoted as if it were a verdict.
            gap = _row_gap_days(row, reference)
            confirmed = gap is not None and abs(gap) <= MAX_REFERENCE_AGE_DAYS
            counts["confirmed" if confirmed else "lead"] += 1
            findings.append({
                "plant": plant,
                "timestamp": row.get("timestamp"),
                "row_vs_capture_days": None if gap is None else round(gap, 1),
                "strength": "confirmed" if confirmed else "lead",
                **detail,
            })
        elif verdict == "not_checked":
            not_checked.append({
                "plant": plant, "timestamp": row.get("timestamp"), **detail
            })

    checked = counts["fired"] + counts["clean"]
    alarms = []
    if stale:
        alarms.append(
            "reference stale, not checked: "
            + (
                f"capture is {age:.1f} days old, limit is {MAX_REFERENCE_AGE_DAYS}"
                if age is not None
                else "capture carries no usable captured_at"
            )
            + ". The price clauses were DISABLED, so a clean result here would "
            "mean nothing. Re-capture data/regional_reference/ per "
            "UCP_API_RUNBOOK.md."
        )
    elif not answerable:
        alarms.append(
            "denominator collapsed: the reference holds no plant with BOTH "
            "national and region-restricted variants, so this predicate could "
            "not have fired for anybody. Nothing was established."
        )
    elif checked == 0:
        alarms.append(
            f"denominator collapsed: {len(rows)} rows considered and NONE was "
            f"checked, though the reference can answer for "
            f"{len(answerable)} plant(s). Nothing was established."
        )
    if findings:
        by_plant = sorted({f"{f['plant']}({f['region']})" for f in findings})
        alarms.append(
            f"{len(findings)} row(s) across {len(by_plant)} product(s) published a "
            f"region-restricted price as a national one "
            f"[{counts['confirmed']} confirmed, {counts['lead']} lead]: "
            + ", ".join(by_plant)
        )

    report = {
        "audit": "D2_prime_regional_render",
        "retailer_id": reference.get("retailer_id", RETAILER_ID),
        "reference_captured_at": (reference.get("provenance") or {}).get("captured_at"),
        "reference_age_days": age,
        "reference_stale": stale,
        "price_clauses_enabled": check_prices,
        "rows_considered": len(rows),
        # How many plants the capture could answer for at all — the audit's
        # real coverage, and the number a reader needs to size every other
        # number below.
        "reference_answerable_plants": len(answerable),
        "reference_total_plants": len(plants_ref),
        "answerable_plant_ids": sorted(answerable),
        "checked": checked,
        "fired": counts["fired"],
        "fired_confirmed": counts["confirmed"],
        "fired_lead": counts["lead"],
        "clean": counts["clean"],
        "empty": counts["empty"],
        "not_checked": counts["not_checked"],
        "findings": findings,
        "not_checked_detail": not_checked,
        "alarms": alarms,
    }
    return (EXIT_ALARM if alarms else EXIT_OK), report


def _print_scope(report):
    """The audit's REACH, printed as a banner rather than a stat line.

    This check can only speak for plants whose capture holds BOTH a national
    and a region-restricted variant — 7 of the 9 plants in the 2026-08-20
    capture. A reader who sees "no regional prices found" and takes it as "FGT
    is clean" has misread the result by an order of magnitude, so the scope is
    printed next to the verdict at both ends of the output, not buried above
    it.

    READ THE DENOMINATOR CAREFULLY: it is the CAPTURE's plant count, not the
    retailer's. This capture is a targeted 9-plant one, so the banner prints
    "7 of 9 (78%)" — which sizes the audit against what was captured, not
    against what is scraped. FGT is scraped across 66 plants, so the audit is
    silent about 59 of them. The banner deliberately names the answerable
    plants so the reader can see how short the list is.
    """
    n = report["reference_answerable_plants"]
    total = report["reference_total_plants"]
    pct = (100.0 * n / total) if total else 0.0
    print("  " + "-" * 68)
    print(f"  SCOPE: this audit can speak for {n} of {total} plants "
          f"({pct:.0f}%) — only those the")
    print("         capture holds BOTH a national and a region-restricted "
          "variant for.")
    print(f"         The other {total - n} are NOT checked and NOT cleared: "
          f"{report['not_checked']} row(s)")
    print("         were skipped for want of a reference.")
    if report["answerable_plant_ids"]:
        print(f"         Answerable: {', '.join(report['answerable_plant_ids'])}")
    print("  " + "-" * 68)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=os.path.join(REPO_ROOT, "data"))
    ap.add_argument(
        "--reference",
        default=os.path.join(
            REPO_ROOT, "data", "regional_reference", f"{RETAILER_ID}.json"
        ),
    )
    ap.add_argument(
        "--all-history", action="store_true",
        help="check every committed row, not just the newest per plant",
    )
    ap.add_argument("--json-out", default=None)
    ap.add_argument(
        "--now", default=None,
        help="ISO instant to age the reference against (tests and replays)",
    )
    args = ap.parse_args(argv)

    now = None
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

    code, report = run(
        args.data_dir, args.reference, now=now, latest_only=not args.all_history,
    )

    print(f"D2' regional render — {report['retailer_id']}")
    print(f"  reference captured {report['reference_captured_at']} "
          f"({report['reference_age_days']:.1f} days old)"
          if report["reference_age_days"] is not None else
          "  reference carries no usable captured_at")
    print(f"  price clauses: {'ENABLED' if report['price_clauses_enabled'] else 'DISABLED'}")
    _print_scope(report)
    print(f"  rows={report['rows_considered']} checked={report['checked']} "
          f"fired={report['fired']} clean={report['clean']} "
          f"empty={report['empty']} not_checked={report['not_checked']}")
    for f in report["findings"]:
        print(f"  FIRED[{f['strength']}] {f['plant']} [{f['region']}] "
              f"{f['timestamp']} tiers={f['tiers']} "
              f"published={f['published_cents']} region={f['region_cents']} "
              f"national={f['national_cents']}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)

    if report["alarms"]:
        for a in report["alarms"]:
            print(f"\nALARM: {a}")
        print(
            "\nThis audit does not gate publishing. Exit 2 so the workflow can "
            "raise it after the fact."
        )
        return EXIT_ALARM
    # NOT "clean". The scope banner is repeated here on purpose: this line is
    # the one a reader skims to, and on its own it would overstate the result
    # by the 2 captured plants the reference cannot answer for — and, more
    # importantly, by the 57 scraped FGT plants this capture never covered.
    print(
        f"\nNo regional prices found in the {report['checked']} row(s) this "
        f"audit could check — which is "
        f"{report['reference_answerable_plants']} of "
        f"{report['reference_total_plants']} plants. This is NOT a clean bill "
        f"of health for the retailer."
    )
    _print_scope(report)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
