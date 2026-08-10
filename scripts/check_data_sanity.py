"""Pre-build data sanity gate.

Runs in CI after scraping, before build. A non-zero exit blocks the
commit/publish for this cycle — the site keeps serving the last known
good data instead of shipping garbage. This is the single point where
"bad data never silently ships" is enforced; before it existed, every
scrape published unconditionally.

Absolute checks (whole files):
  - every JSONL line parses
  - every price is numeric, > 0, and <= MAX_SANE_PRICE
  - every entry has a parseable, timezone-aware ISO timestamp

Recent-row checks (rows scraped in the last RECENT_HOURS):
  - retailer_id is an active retailer in retailers.json
    (historical rows from since-deactivated retailers are fine)

Delta checks (vs the previous committed state, via `git show HEAD:`):
  - fresh price points (last FRESH_HOURS) did not drop > MAX_FRESH_DROP_PCT
  - plants with zero fresh offers did not increase by > MAX_NEW_ZERO_OFFER

Delta checks are skipped with a warning when git or the HEAD version is
unavailable (e.g. first run) — absolute checks always apply.

Usage:
  python scripts/check_data_sanity.py [--data-dir data] [--report]

--report prints the summary JSON and always exits 0 (for runbook use).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

MAX_SANE_PRICE = 5000.0
RECENT_HOURS = 48
FRESH_HOURS = 36
MAX_FRESH_DROP_PCT = 25.0
MAX_NEW_ZERO_OFFER = 2


def parse_ts(ts_str):
    """Parse an ISO timestamp; return aware datetime or None."""
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return ts if ts.tzinfo is not None else None


def iter_price_files(prices_dir):
    for name in sorted(os.listdir(prices_dir)):
        if name.endswith(".jsonl"):
            yield os.path.join(prices_dir, name)


def scan(data_dir, now=None):
    """Scan price data; return (errors, stats).

    errors: list of hard-fail strings (empty = pass)
    stats:  counters used by delta checks and --report
    """
    now = now or datetime.now(timezone.utc)
    prices_dir = os.path.join(data_dir, "prices")
    retailers_path = os.path.join(data_dir, "retailers.json")

    errors = []
    try:
        with open(retailers_path, encoding="utf-8") as f:
            retailers = json.load(f)
        active_ids = {r["id"] for r in retailers if r.get("active")}
        if not active_ids:
            errors.append("retailers.json: no active retailers")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        return [f"retailers.json unreadable: {e}"], {}

    recent_cutoff = now - timedelta(hours=RECENT_HOURS)
    fresh_cutoff = now - timedelta(hours=FRESH_HOURS)
    offer_cutoff = now - timedelta(days=30)  # mirrors build.py staleness

    fresh_points = 0
    zero_offer_plants = 0
    total_lines = 0

    for path in iter_price_files(prices_dir):
        fname = os.path.basename(path)
        plant_has_offer = False
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"{fname}:{lineno}: unparseable JSONL")
                    continue

                ts = parse_ts(entry.get("timestamp"))
                if ts is None:
                    errors.append(
                        f"{fname}:{lineno}: missing or naive timestamp "
                        f"({entry.get('timestamp')!r}) — undated rows never go stale"
                    )
                    continue

                rid = entry.get("retailer_id", "")
                if ts >= recent_cutoff and rid not in active_ids:
                    errors.append(
                        f"{fname}:{lineno}: recent row from unknown/inactive "
                        f"retailer {rid!r}"
                    )

                for tier, info in entry.get("sizes", {}).items():
                    if not isinstance(info, dict):
                        continue
                    price = info.get("price")
                    if price is None:
                        continue
                    if not isinstance(price, (int, float)) or isinstance(price, bool):
                        errors.append(f"{fname}:{lineno}: non-numeric price {price!r} ({tier})")
                        continue
                    if price <= 0:
                        errors.append(f"{fname}:{lineno}: price {price} <= 0 ({tier})")
                    elif price > MAX_SANE_PRICE:
                        errors.append(
                            f"{fname}:{lineno}: price {price} > {MAX_SANE_PRICE} ({tier})"
                        )
                    if ts >= fresh_cutoff:
                        fresh_points += 1
                    if ts >= offer_cutoff:
                        plant_has_offer = True
        if not plant_has_offer:
            zero_offer_plants += 1

    stats = {
        "total_lines": total_lines,
        "fresh_points": fresh_points,
        "zero_offer_plants": zero_offer_plants,
        "active_retailers": len(active_ids),
    }
    return errors, stats


def head_stats(data_dir, now=None):
    """Compute the same stats for the HEAD (previously committed) version.

    Returns None when unavailable (no git, first run, etc.).
    """
    import tempfile

    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", f"{data_dir}/prices"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    names = [n for n in out.stdout.splitlines() if n.endswith(".jsonl")]
    if not names:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        pdir = os.path.join(tmp, "prices")
        os.mkdir(pdir)
        for name in names:
            show = subprocess.run(
                ["git", "show", f"HEAD:{name}"], capture_output=True, text=True,
            )
            if show.returncode == 0:
                with open(
                    os.path.join(pdir, os.path.basename(name)), "w", encoding="utf-8"
                ) as f:
                    f.write(show.stdout)
        # retailers.json from HEAD too, falling back to working tree
        show = subprocess.run(
            ["git", "show", f"HEAD:{data_dir}/retailers.json"],
            capture_output=True, text=True,
        )
        src = (
            show.stdout
            if show.returncode == 0
            else open(os.path.join(data_dir, "retailers.json"), encoding="utf-8").read()
        )
        with open(os.path.join(tmp, "retailers.json"), "w", encoding="utf-8") as f:
            f.write(src)
        _, stats = scan(tmp, now=now)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--report", action="store_true",
                        help="print summary JSON and exit 0")
    args = parser.parse_args()

    errors, stats = scan(args.data_dir)

    delta_notes = []
    prev = head_stats(args.data_dir)
    if prev is None:
        delta_notes.append("delta checks skipped: no HEAD baseline available")
    else:
        prev_fresh = prev.get("fresh_points", 0)
        if prev_fresh > 0:
            drop = (1 - stats.get("fresh_points", 0) / prev_fresh) * 100
            if drop > MAX_FRESH_DROP_PCT:
                errors.append(
                    f"fresh price points dropped {drop:.0f}% vs HEAD "
                    f"({prev_fresh} -> {stats.get('fresh_points', 0)})"
                )
        new_zero = stats.get("zero_offer_plants", 0) - prev.get("zero_offer_plants", 0)
        if new_zero > MAX_NEW_ZERO_OFFER:
            errors.append(
                f"{new_zero} plants newly have zero fresh offers "
                f"(> {MAX_NEW_ZERO_OFFER} allowed per run)"
            )

    summary = {
        "gate": "data_sanity",
        "pass": not errors,
        "errors": errors[:50],
        "error_count": len(errors),
        "stats": stats,
        "notes": delta_notes,
    }
    print(json.dumps(summary, indent=2))

    if args.report:
        return 0
    if errors:
        print(
            f"\nDATA SANITY GATE FAILED: {len(errors)} error(s). "
            "Nothing will be committed this cycle; the site keeps serving "
            "the last known good data.", file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
