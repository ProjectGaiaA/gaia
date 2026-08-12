"""Pre-build data gate: quarantine bad rows, block only on systemic failure.

Design note — why this quarantines instead of blocking:

The first version blocked the commit whenever it found a bad row. Because
price files are append-only and a blocked run never commits, the next run
re-scraped the identical bad row and failed identically. Review demonstrated
three consecutive runs with main's SHA never moving: one `price: 0` in 1 of
742 plant-retailer pairs stopped all publishing permanently, with no path to
self-heal. A gate that can wedge the pipeline is worse than the garbage it
prevents.

So: individual bad rows are STRIPPED from the working tree and reported.
Good data publishes, and the caller turns the job red afterwards (exit 3) so
the failure is still loud. Only systemic corruption — where the whole scrape
looks wrong — hard-blocks the publish (exit 1).

Row checks (quarantined, exit 3):
  - unparseable JSONL
  - price non-numeric, <= 0, NaN/inf, or > MAX_SANE_PRICE
  - missing / naive (non-tz-aware) timestamp
  - recent row from an unknown or inactive retailer

Systemic checks (hard block, exit 1):
  - a large fraction of fresh prices moved drastically vs the PREVIOUS cycle
    (catches a site redesign making every price the same wrong number)
  - fresh prices collapse to one repeated value
  - every active retailer produced zero fresh rows
  - quarantine would remove more than QUARANTINE_ABORT_PCT of fresh rows

Exit codes: 0 clean | 1 systemic, do not publish | 3 quarantined, publish anyway
"""

import argparse
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

MAX_SANE_PRICE = 5000.0
RECENT_HOURS = 48
FRESH_HOURS = 36

# Systemic thresholds
MAX_PRICE_MOVE_PCT = 60.0       # a single price moving more than this is "drastic"
MAX_MOVED_FRACTION = 0.30       # if >30% of comparable prices moved drastically
MAX_COLLAPSE_FRACTION = 0.50    # if >50% of fresh prices are one identical value
QUARANTINE_ABORT_PCT = 20.0     # quarantining more than this much = systemic
MIN_SAMPLE_FOR_SYSTEMIC = 25    # don't call it systemic on a tiny sample

EXIT_OK, EXIT_BLOCK, EXIT_QUARANTINED = 0, 1, 3


def parse_ts(ts_str):
    """Parse an ISO timestamp; return an aware datetime or None."""
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return ts if ts.tzinfo is not None else None


def bad_price_reason(price):
    """Why this price is unusable, or None if it's fine. None price = 'not scraped', allowed."""
    if price is None:
        return None
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return f"non-numeric price {price!r}"
    if isinstance(price, float) and (math.isnan(price) or math.isinf(price)):
        return f"non-finite price {price!r}"
    if price <= 0:
        return f"price {price} <= 0"
    if price > MAX_SANE_PRICE:
        return f"price {price} > {MAX_SANE_PRICE}"
    return None


def iter_price_files(prices_dir):
    for name in sorted(os.listdir(prices_dir)):
        if name.endswith(".jsonl"):
            yield os.path.join(prices_dir, name)


def load_active_ids(data_dir):
    with open(os.path.join(data_dir, "retailers.json"), encoding="utf-8") as f:
        return {r["id"] for r in json.load(f) if r.get("active")}


def scan(data_dir, now=None, quarantine=False):
    """Inspect every price row. Returns (problems, stats).

    problems: list of dicts {file, line, reason} — rows that should not publish.
    When quarantine=True the offending rows are removed from disk.
    """
    now = now or datetime.now(timezone.utc)
    prices_dir = os.path.join(data_dir, "prices")
    active_ids = load_active_ids(data_dir)

    recent_cutoff = now - timedelta(hours=RECENT_HOURS)
    fresh_cutoff = now - timedelta(hours=FRESH_HOURS)
    offer_cutoff = now - timedelta(days=30)

    problems = []
    fresh_prices = []           # values of fresh, valid prices
    fresh_by_key = {}           # (plant, retailer, tier) -> price
    fresh_rows = 0
    fresh_flagged = 0
    zero_offer_plants = 0
    total_lines = 0

    for path in iter_price_files(prices_dir):
        fname = os.path.basename(path)
        plant_id = fname[:-6]
        kept_lines = []
        removed_any = False
        plant_has_offer = False

        with open(path, encoding="utf-8") as f:
            raw_lines = f.readlines()

        for lineno, line in enumerate(raw_lines, 1):
            stripped = line.strip()
            if not stripped:
                continue
            total_lines += 1
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                problems.append({"file": fname, "line": lineno,
                                 "reason": "unparseable JSONL"})
                removed_any = True
                continue

            ts = parse_ts(entry.get("timestamp"))
            if ts is None:
                problems.append({"file": fname, "line": lineno,
                                 "reason": f"missing or naive timestamp "
                                           f"({entry.get('timestamp')!r})"})
                removed_any = True
                continue

            rid = entry.get("retailer_id", "")
            if ts >= recent_cutoff and rid not in active_ids:
                problems.append({"file": fname, "line": lineno,
                                 "reason": f"recent row from unknown/inactive retailer {rid!r}"})
                removed_any = True
                continue

            row_bad = None
            for tier, info in entry.get("sizes", {}).items():
                if not isinstance(info, dict):
                    continue
                reason = bad_price_reason(info.get("price"))
                if reason:
                    row_bad = f"{reason} ({tier})"
                    break

            if row_bad:
                problems.append({"file": fname, "line": lineno, "reason": row_bad})
                removed_any = True
                continue

            # Row is good — record stats
            if ts >= offer_cutoff:
                plant_has_offer = True
            if ts >= fresh_cutoff:
                fresh_rows += 1
                # runner.py flags a row whose price moved more than the
                # anomaly threshold instead of discarding it. Nothing in the
                # repo read that key until now, which made "flagged for
                # review" decorative. Counting it here puts it in the gate's
                # output and JSON report.
                if entry.get("price_anomaly"):
                    fresh_flagged += 1
                for tier, info in entry.get("sizes", {}).items():
                    price = info.get("price") if isinstance(info, dict) else info
                    if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
                        fresh_prices.append(price)
                        fresh_by_key[(plant_id, rid, tier)] = price
            kept_lines.append(stripped)

        if not plant_has_offer:
            zero_offer_plants += 1

        if quarantine and removed_any:
            with open(path, "w", encoding="utf-8") as f:
                if kept_lines:
                    f.write("\n".join(kept_lines) + "\n")

    stats = {
        "total_lines": total_lines,
        "fresh_rows": fresh_rows,
        "rows_flagged_price_anomaly": fresh_flagged,
        "fresh_price_points": len(fresh_prices),
        "zero_offer_plants": zero_offer_plants,
        "active_retailers": len(active_ids),
    }
    return problems, stats, fresh_prices, fresh_by_key


def systemic_checks(data_dir, stats, fresh_prices, fresh_by_key, problems):
    """Failures that mean the whole scrape is untrustworthy. Returns a list."""
    fatal = []

    # 1. Quarantining a large share of fresh data is itself a systemic signal.
    if stats["fresh_rows"] + len(problems) >= MIN_SAMPLE_FOR_SYSTEMIC:
        pct = 100.0 * len(problems) / max(1, stats["fresh_rows"] + len(problems))
        if pct > QUARANTINE_ABORT_PCT:
            fatal.append(
                f"{len(problems)} bad rows = {pct:.0f}% of recent data "
                f"(> {QUARANTINE_ABORT_PCT}%) — scrape looks broken, not noisy"
            )

    # 2. Fresh prices collapsing to one repeated value = parser grabbing the
    #    wrong element sitewide (e.g. every price becomes $9.99).
    if len(fresh_prices) >= MIN_SAMPLE_FOR_SYSTEMIC:
        value, count = Counter(fresh_prices).most_common(1)[0]
        frac = count / len(fresh_prices)
        if frac > MAX_COLLAPSE_FRACTION:
            fatal.append(
                f"{frac:.0%} of {len(fresh_prices)} fresh prices are all ${value} "
                f"— scraper is reading one wrong value sitewide"
            )

    # 3. A large fraction of prices moving drastically vs the PREVIOUS cycle.
    #
    # Only prev_manifest.json counts. last_manifest.json is deliberately NOT a
    # fallback: every scraper step rewrites it with THIS run's prices long
    # before this gate executes, so reading it compares the run against itself
    # and reports flawless 0% movement however corrupt the data is. Measured
    # on this corpus: 735 prices compared, 735 exactly equal — and tripling
    # every price still exited 0 while corrupting 127 of 133 pages.
    #
    # With no snapshot the check is SKIPPED, not passed. Silence is the honest
    # answer when there is nothing to compare against; a green light would be
    # the same lie this file exists to catch.
    manifest_path = os.path.join(data_dir, "prev_manifest.json")
    compared = moved = 0
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        manifest = {}
        print(
            "  NOTE: no prev_manifest.json baseline — price-movement check "
            "SKIPPED this run (skipped, not passed)"
        )
    prev_prices = manifest.get("prices", {})
    for (plant_id, rid, tier), price in fresh_by_key.items():
        prev = (prev_prices.get(f"{plant_id}:{rid}") or {}).get(tier)
        if not isinstance(prev, (int, float)) or prev <= 0:
            continue
        compared += 1
        if abs(price - prev) / prev * 100.0 > MAX_PRICE_MOVE_PCT:
            moved += 1
    if compared >= MIN_SAMPLE_FOR_SYSTEMIC:
        frac = moved / compared
        if frac > MAX_MOVED_FRACTION:
            fatal.append(
                f"{moved}/{compared} ({frac:.0%}) of fresh prices moved more than "
                f"{MAX_PRICE_MOVE_PCT}% vs the previous cycle (> {MAX_MOVED_FRACTION:.0%}) "
                f"— site redesign or parser regression"
            )

    # 4. Every active retailer silent. Only meaningful against a real corpus:
    #    on a trivial dataset "no fresh rows" is just a small sample, not an
    #    outage, and firing there would block on legitimate history-only data.
    if (
        stats["fresh_rows"] == 0
        and stats["active_retailers"] > 0
        and stats["total_lines"] >= MIN_SAMPLE_FOR_SYSTEMIC
    ):
        fatal.append("zero fresh rows from any retailer this cycle")

    # Count rows the scraper flagged with price_anomaly. Until now nothing in
    # the repo READ that key — runner.py wrote it and no code, workflow or
    # template consumed it, so "flagged for review" was decorative. Reporting
    # it here puts it in the gate's stdout and JSON report, which is where the
    # run summary and any future digest can pick it up.
    flagged = stats.get("rows_flagged_price_anomaly", 0)
    if flagged:
        print(f"  {flagged} fresh row(s) carry a price_anomaly flag (recorded, not blocking)")

    return fatal, {
        "prices_compared": compared,
        "prices_moved_drastically": moved,
        "rows_flagged_price_anomaly": flagged,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--report", action="store_true",
                        help="inspect only; never modify files, always exit 0")
    args = parser.parse_args()

    # Report mode must not mutate anything.
    problems, stats, fresh_prices, fresh_by_key = scan(
        args.data_dir, quarantine=not args.report
    )
    fatal, move_stats = systemic_checks(
        args.data_dir, stats, fresh_prices, fresh_by_key, problems
    )
    stats.update(move_stats)

    summary = {
        "gate": "data_sanity",
        "systemic_failures": fatal,
        "quarantined_rows": len(problems),
        "quarantined_sample": problems[:25],
        "stats": stats,
        "mode": "report" if args.report else "enforce",
    }
    print(json.dumps(summary, indent=2))

    if args.report:
        return EXIT_OK

    if fatal:
        print("\n".join(f"::error::data gate: {f}" for f in fatal), file=sys.stderr)
        print(
            "\nSYSTEMIC DATA FAILURE — not publishing this cycle. The site keeps "
            "serving the last known good data.", file=sys.stderr,
        )
        return EXIT_BLOCK

    if problems:
        for p in problems[:25]:
            print(f"::warning::quarantined {p['file']}:{p['line']} — {p['reason']}")
        print(
            f"\nQuarantined {len(problems)} bad row(s); good data will still "
            f"publish. The job will be marked failed so this is not silent.",
            file=sys.stderr,
        )
        return EXIT_QUARANTINED

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
