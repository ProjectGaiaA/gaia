"""Nightly offline audits — alarms, never a publish gate.

Runs the six audits proven in PRICE_AND_STOCK_AUDIT.md §4 against the
committed data and the freshly built site. No network.

NON-GATING — WHERE THAT PROPERTY ACTUALLY COMES FROM (corrected 2026-08-12)
--------------------------------------------------------------------------
This docstring used to say "the workflow runs it AFTER the commit step".
That was false. `Nightly offline audits` is scrape.yml:236 and `Commit
updated price data` is scrape.yml:268 — the audits run BEFORE the commit.
A red team found the sentence; no test could have, because the sentence was
the only thing asserting it.

The non-gating property is real, but it rests on exactly one mechanism: the
audit step's BODY swallows the exit code (`set +e`, capture
`${PIPESTATUS[0]}`, export AUDITS_ALARMED, never propagate). Ordering
contributes nothing. That body is now under test —
tests/test_audit_step_is_not_a_gate.py extracts it verbatim from the
workflow and runs it under `bash -eo pipefail` (what Actions uses) against a
stub that exits 2 and a stub that raises, requiring exit 0 from both.

`if: always()` was deliberately NOT added to the commit step instead. The
steps between the checkout and the commit include the data-sanity gate, the
build, and the broken-link check, all of which are meant to BLOCK a publish.
`if: always()` there would commit through a failed gate — it would publish
precisely when the pipeline said do not. Testing the audit step's own exit
code fixes the audit's non-gating claim without weakening any real gate.

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
      RE-DERIVED 2026-08-12 at the granularity the check actually runs at.
      The previous version of this block was stated per DAY. scrape.yml crons
      at `0 11` and `30 21`, so the audit runs TWICE a day and D compares each
      pair's last two committed rows — i.e. per RUN. A red team found the
      mismatch; the per-day numbers below it are not reproducible from the
      corpus and are not used any more.

      Replay method: every row in data/prices/*.jsonl bucketed into a run by
      clustering timestamps (a gap > 3h starts a new run), then audit_d run
      against the corpus as it stood at the end of each run.
      253 runs, 2026-04-03T20:28 .. 2026-08-12T11:41, 68,329 rows, 282 pairs.
      (130 calendar days: 113 with 2 runs, 12 with 1, 5 with 3.)

      new findings per RUN:
        0 migrations : 226 runs     6 : 1 run      22 : 1 run
        1 migration  :  10 runs    10 : 1 run      26 : 1 run
        2 migrations :   7 runs    13 : 1 run      32 : 1 run
        3 migrations :   4 runs

      The gap is 3 -> 6, NOT the "4 to 8" the old block claimed. So the
      margin at 5 is one migration below the smallest real event, two above
      the noisiest quiet run.

      KEPT 5, not widened. Thresholds 4, 5 and 6 are indistinguishable on
      this history — each fires on the same 6 of 253 runs (2.4%) — so 5 is
      not tuned to noise, it is the midpoint of a flat region. Widening past
      6 would start dropping real events: the 6-migration run is one of them.
      All six firing runs are confirmed FGT positional-shift events:
        2026-07-27 22:34 (22)  delaware-valley-white-azalea
                               {1gal:21.95,3gal:42.95} -> {3gal:21.95};
                               fuji-apple-tree slid two labels
        2026-07-28 12:50 (26)  same event persisting
        2026-07-28 22:33 (10)  same event persisting
        2026-08-07 11:41 ( 6)  coral-bark-japanese-maple, crape-myrtle
        2026-08-11 20:02 (13)  the fix landing
        2026-08-12 11:41 (32)  the fix landing
      Both 07-27 and 08-07 are the worked examples in audit doc §4D. Zero
      known false positives at this threshold, on 247 non-event runs.
      Migrations below the threshold are still RECORDED for the digest.
      Caveat stated plainly: 5 of the 6 firing runs are two calendar events,
      so this is 2 independent incidents, not 6.

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

FRESHNESS (added 2026-08-12 — R5: a metric must not be satisfiable by the
failure mode)
-------------------------------------------------------------------------
`latest` used to be every pair's last-ever row, with no freshness test, and
nothing in this module read the `timestamp` field at all. A dead retailer's
final row therefore counted toward every denominator forever. A red team
deleted every fast-growing-trees row after 2026-06-15 — 7,388 rows, one of
seven retailers dead for two months — and this script returned exit 0, zero
alarms, with every denominator ABOVE its floor and two of them HIGHER than
on the real corpus (A 95 -> 119, C 191 -> 199, D 248 -> 254). The corpus
looked healthier for having lost a retailer.

So: a pair's last row is used only if it is within FRESH_HOURS of the newest
row anywhere in the corpus. Excluded rows are counted and printed (R10), and
a retailer that contributes NO fresh row while having committed rows is an
ALARM — that is the dead-retailer signature.

Window calibration (R9), same 253-run replay as D:
  * Today's corpus is bimodal with nothing in between: 277 of 282 pairs are
    within 2.3h of the newest row; the other 5 are 864h, 1054h, 2471h,
    2901h and 3014h old (discontinued products at live retailers). Every
    window from 3h to 864h produces the identical split, so the split is not
    sensitive to the number.
  * The number matters only for the dead-retailer alarm. Replayed over all
    253 runs, alarming runs per retailer:
        48h : great-garden-plants 38, everyone else 0
        36h : great-garden-plants 39, planting-tree 1, proven-winners 1,
              spring-hill 1
        30h : great-garden-plants 40, and 1 each for five retailers
    The great-garden-plants firings are a genuine 21-day outage
    (2026-07-21 -> 2026-08-11, absent from 40 consecutive runs); the others
    are all the 2026-04-05 -> 2026-04-08 bring-up gap, when the whole
    pipeline was down for 3.5 days.
  * CHOSEN 48 — the only window with zero firings outside the one confirmed
    outage. It tolerates a retailer missing two consecutive scrape runs
    (~36h) and alarms on three (~48h). Cost of the choice, stated: a
    retailer that dies right after a run is reported ~48h later, not ~24h.

Defect introduced by this fix and caught by probing it (not by review):
measuring "stale" relative to the newest row means one row with a broken
clock drags the reference point forward and declares everyone else dead — a
single row dated 3000-01-01 marked 2 of 3 retailers as stopped. Rows dated
more than FUTURE_SLACK_HOURS after the run started are therefore excluded
from the reference point and alarmed on separately.

Consequence to know about: a retailer in a real outage alarms on EVERY run
until it comes back (great-garden-plants would have been 38 consecutive red
runs). That is deliberate — the alternative is a one-shot alarm that is
missed and never repeats — but it is why this is an alarm on the retailer,
not on each stale row. Stale rows at a live retailer are a NOTICE.

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
from datetime import datetime, timedelta, timezone

EXIT_OK, EXIT_ALARM = 0, 2

# --- thresholds, all justified in CALIBRATION above ---
A_RATIO = 2.5
B_RATIO = 2.5
C_TOLERANCE = 0.10
NEW_CLUSTER = 5          # new A/B/C findings in one run before it is an ALARM
D_CLUSTER = 5            # tier migrations in one run before it is an ALARM
FRESH_HOURS = 48         # a row older than this vs the newest row is stale
FUTURE_SLACK_HOURS = 1   # a row dated further ahead than this has a bad clock

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


def _row_time(entry):
    """The row's timestamp as an aware datetime, or None if it has none this
    module can read. None is treated as STALE, never as fresh: a schema change
    that drops or renames the field must collapse the denominators loudly
    rather than quietly keep every row forever."""
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def split_by_freshness(history, fresh_hours=FRESH_HOURS):
    """Split each pair's last row into fresh vs stale.

    Returns (fresh, stale, meta). `fresh` is what the audits should measure;
    `stale` is what a dead retailer leaves behind. See FRESHNESS above for
    why this exists and how 48h was chosen.
    """
    latest = {key: entries[-1] for key, entries in history.items() if entries}
    stamps = {key: _row_time(entry) for key, entry in latest.items()}

    # Everything here is measured RELATIVE to the newest row, so one row with
    # a broken clock would drag the cutoff forward and declare every other
    # retailer dead. Found by probing this function, not by review: a single
    # row dated 3000-01-01 marked 2 of 3 retailers as having stopped. Rows
    # dated after this run started cannot be from this run, so they are
    # excluded from the reference point and reported in their own right.
    horizon = datetime.now(timezone.utc) + timedelta(hours=FUTURE_SLACK_HOURS)
    from_the_future = sorted(
        (key for key, t in stamps.items() if t is not None and t > horizon),
        key=lambda k: (k[1], k[0]),
    )
    dated = [t for key, t in stamps.items()
             if t is not None and key not in set(from_the_future)]
    newest = max(dated) if dated else None
    cutoff = newest - timedelta(hours=fresh_hours) if newest else None

    fresh, stale = {}, {}
    for key, entry in latest.items():
        stamp = stamps[key]
        if stamp is not None and cutoff is not None and stamp >= cutoff:
            fresh[key] = entry
        else:
            stale[key] = entry

    fresh_retailers = {rid for _plant, rid in fresh}
    all_retailers = fresh_retailers | {rid for _plant, rid in stale}
    per_retailer = {}
    for rid in sorted(all_retailers):
        per_retailer[rid] = {
            "fresh": sum(1 for _p, r in fresh if r == rid),
            "stale": sum(1 for _p, r in stale if r == rid),
        }

    meta = {
        "fresh_window_hours": fresh_hours,
        "newest_row": newest.isoformat() if newest else None,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "pairs_total": len(latest),
        "pairs_fresh": len(fresh),
        "pairs_stale": len(stale),
        "undated_rows": sum(1 for t in stamps.values() if t is None),
        "future_rows": [{"plant": p, "retailer": r} for p, r in from_the_future],
        "per_retailer": per_retailer,
        "retailers_with_no_fresh_row": sorted(all_retailers - fresh_retailers),
        "stalest": [
            {"plant": k[0], "retailer": k[1],
             "hours": round((newest - stamps[k]).total_seconds() / 3600, 1)
                      if newest and stamps[k] else None}
            for k in sorted(stale, key=lambda k: (stamps[k] or newest or
                                                  datetime.min.replace(tzinfo=timezone.utc)))
        ][:20],
    }
    return fresh, stale, meta


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
    # R5 — a dead retailer's last-ever row must not keep counting toward every
    # denominator. See FRESHNESS in the module docstring.
    latest, _stale, fresh_meta = split_by_freshness(history)
    fresh_history = {key: entries for key, entries in history.items()
                     if key in latest}

    a_denom, a_find = audit_a_cross_retailer(latest)
    b_denom, b_find = audit_b_two_nursery_pairs(latest)
    c_denom, c_find = audit_c_within_retailer_inversion(latest)
    d_denom, d_find = audit_d_snapshot_value_diff(fresh_history)
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

    # R10 for the input itself: how many rows reached the audits at all, and
    # how many were dropped for being too old to be from this run.
    print()
    print(f"[freshness] rows within {FRESH_HOURS}h of the newest committed row")
    print(f"   newest row : {fresh_meta['newest_row']}")
    print(f"   cutoff     : {fresh_meta['cutoff']}")
    print(f"   examined   : {fresh_meta['pairs_fresh']} of "
          f"{fresh_meta['pairs_total']} plant-retailer pairs")
    print(f"   excluded   : {fresh_meta['pairs_stale']} stale "
          f"({fresh_meta['undated_rows']} of them carry no readable timestamp)")
    for rid, counts in fresh_meta["per_retailer"].items():
        print(f"     {rid:26s} fresh {counts['fresh']:4d}  stale {counts['stale']:4d}")
    for row in fresh_meta["stalest"][:5]:
        print(f"     - {row['plant']} at {row['retailer']} last seen "
              f"{row['hours']}h ago")

    if fresh_meta["future_rows"]:
        named = ", ".join(f"{r['plant']}@{r['retailer']}"
                          for r in fresh_meta["future_rows"][:5])
        print(f"   dated after this run started: "
              f"{len(fresh_meta['future_rows'])} ({named})")
        alarms.append(
            f"{len(fresh_meta['future_rows'])} row(s) are dated after this run "
            f"started ({named}) — a clock is wrong somewhere, and freshness is "
            f"measured relative to the newest row, so they are excluded from "
            f"that reference point rather than making every other retailer "
            f"look dead"
        )
    if fresh_meta["newest_row"] is None:
        alarms.append(
            "no row in data/prices/ carries a readable timestamp, so freshness "
            "could not be measured and every row was excluded — the audits "
            "below examined nothing"
        )
    dead = fresh_meta["retailers_with_no_fresh_row"]
    if dead:
        alarms.append(
            f"retailer(s) {', '.join(dead)} contributed no row within "
            f"{FRESH_HOURS}h of the newest committed row "
            f"({fresh_meta['newest_row']}) — their last-known prices are still "
            f"on the site but the scraper has stopped producing them"
        )
    elif fresh_meta["pairs_stale"]:
        notices.append(
            f"{fresh_meta['pairs_stale']} of {fresh_meta['pairs_total']} "
            f"plant-retailer pairs are stale (>{FRESH_HOURS}h) at retailers "
            f"that are otherwise reporting — probably discontinued products; "
            f"they are excluded from every denominator below"
        )

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
        if name != "E_cross_page_agreement":
            print(f"   drawn from : {fresh_meta['pairs_fresh']} fresh rows, "
                  f"{fresh_meta['pairs_stale']} of "
                  f"{fresh_meta['pairs_total']} excluded as stale")
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
            "fresh_hours": FRESH_HOURS,
            "denominator_floors": DENOM_FLOOR,
        },
        "freshness": fresh_meta,
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
