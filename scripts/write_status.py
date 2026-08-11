"""Write health status from CI, recording what actually happened.

Two files, deliberately different audiences:

  data/status.json  — full operational detail. Lives in the repo (public, so
                      readable via raw.githubusercontent.com) but NOT served
                      from the site.
  site/health.json  — two fields only: generated_at and commit. Published to
                      the live site so an outside checker can detect a stalled
                      deploy.

Three design rules, all from review findings:

1. **No stored age.** The previous design baked `data_age_hours` into the file.
   That number freezes at its last healthy value the moment the pipeline stops,
   so the dead-man's switch would read its own corpse's pulse and report health
   forever. Only `generated_at` is written; every consumer computes age itself.

2. **Written from an `if: always()` step, after the gates.** The old plan
   generated status inside build.py, which is skipped whenever an earlier step
   fails — so a blocked run left a stale file saying "healthy". This script runs
   regardless and takes the real gate outcomes as arguments.

3. **No `published_this_run` field.** This script must run BEFORE the commit
   step, or the files it writes are never committed and never reach the site.
   That means publication has not happened yet at write time and any value
   written here would be a prediction, not a record — the same "assume success"
   defect the file exists to prevent. Publication is instead proven by evidence
   rather than assertion: if you are reading this file at a fresh
   `generated_at`, the commit and deploy that carried it necessarily succeeded.
   A failed publish leaves the previous copy in place with an old timestamp,
   which is exactly what the liveness check looks for.

site/health.json deliberately excludes retailer names, price counts, scraper
health, and monetization status: the site is fully crawlable, and that detail
would hand the merchants being scraped a live effectiveness dashboard and tell
affiliate reviewers the site currently monetizes nothing.

Usage:
  python scripts/write_status.py --gate pass --tests fail --quarantined 4
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone

DATA_DIR = "data"
SITE_DIR = "site"
STALE_AFTER_HOURS = 22


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def git_sha():
    """The commit this run was BUILT FROM, not the commit it produces.

    This runs before the daily-update commit exists, so it can never name the
    commit that carries it. Consumers use `generated_at` for freshness; this
    field is for answering "which code produced this?" during triage.
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def parse_ts(value):
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return ts if ts.tzinfo else None


def newest_price_timestamp(prices_dir):
    """Newest scrape timestamp across all price files — the real data age."""
    newest = None
    if not os.path.isdir(prices_dir):
        return None
    for name in os.listdir(prices_dir):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(prices_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        # Newest row is usually last; scan the tail rather than the whole file.
        for line in reversed(lines[-40:]):
            line = line.strip()
            if not line:
                continue
            try:
                ts = parse_ts(json.loads(line).get("timestamp"))
            except json.JSONDecodeError:
                continue
            if ts and (newest is None or ts > newest):
                newest = ts
            break
    return newest


def retailer_rows(manifest, now):
    """Per-retailer freshness FROM ROWS WRITTEN, not from process exit codes.

    A scraper that returns zero rows and exits 0 is indistinguishable from a
    healthy one if you only read step outcomes — which is how a retailer sat
    dead for 21 days while CI reported success.
    """
    out = []
    for entry in (manifest or {}).get("retailers", []):
        found = entry.get("products_found", 0)
        expected = entry.get("products_expected", 0) or 0
        out.append({
            "id": entry.get("retailer_id"),
            "products_found": found,
            "products_expected": expected,
            "health": entry.get("health", "unknown"),
            "silent": bool(expected and found == 0),
        })
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gate", default="unknown")
    p.add_argument("--tests", default="unknown")
    p.add_argument("--build", default="unknown")
    p.add_argument("--quarantined", default="0")
    args = p.parse_args()

    now = datetime.now(timezone.utc)

    try:
        with open(os.path.join(DATA_DIR, "last_manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        manifest = {}

    newest = newest_price_timestamp(os.path.join(DATA_DIR, "prices"))
    retailers = retailer_rows(manifest, now)
    silent = [r["id"] for r in retailers if r["silent"]]

    status = {
        # No age field, by design — consumers compute it from these.
        "generated_at": _iso(now),
        "newest_price_at": _iso(newest) if newest else None,
        "built_from_commit": git_sha(),
        "gates": {
            "data_sanity": args.gate,
            "tests": args.tests,
            "build": args.build,
            "quarantined_rows": int(args.quarantined or 0),
        },
        "retailers": retailers,
        "silent_retailers": silent,
        "stale_after_hours": STALE_AFTER_HOURS,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
        f.write("\n")

    # Public file: only what an external freshness check needs.
    os.makedirs(SITE_DIR, exist_ok=True)
    # newest_price_at is published too, because generated_at alone is not
    # enough: it says when the PIPELINE ran, not when PRICES last changed. A
    # pipeline that runs on schedule while every scraper silently returns
    # nothing would hold generated_at fresh indefinitely while the site served
    # frozen prices. Publishing both lets the external check tell those apart.
    # It leaks nothing — the site already displays per-price update dates.
    public = {
        "generated_at": status["generated_at"],
        "newest_price_at": status["newest_price_at"],
        "commit": status["built_from_commit"],
    }
    with open(os.path.join(SITE_DIR, "health.json"), "w", encoding="utf-8") as f:
        json.dump(public, f, indent=2)
        f.write("\n")

    print(json.dumps(status, indent=2))
    if silent:
        print(f"::warning::Retailers wrote zero rows: {', '.join(silent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
