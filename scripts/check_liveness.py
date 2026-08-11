"""Check the LIVE site from outside — is it up, and is its content fresh?

This is the only check that looks at what a visitor actually receives. Every
other gate in this repo inspects the repo's own working copy, which stays
perfectly healthy while the deployed site rots: the Vercel deploy failed 44
consecutive times over four months without a single in-repo check noticing.

What it asserts, in order of how badly each failure hurts:

  1. The homepage returns 200. If this fails the site is down.
  2. /health.json parses and has `generated_at`.
  3. Age computed FROM `generated_at` is under the staleness threshold.

Age is computed here, at read time, and never read from the file. A stored age
freezes at its last healthy value the moment the pipeline dies, so the check
would read its own corpse's pulse and report health forever.

No cache-busting query string, deliberately. The question is "what is a visitor
getting right now", and a stale CDN copy in front of a fresh origin is a real
outage for real people. Observed Vercel CDN Age has reached 4.75h and that is
already inside the threshold below.

Threshold rationale, measured from 92 real runs:
    max observed inter-run gap        16.16h
    cron delay                        median 63min, max 163min
    run duration                      ~52min
    observed CDN Age                  up to 4.75h
    -> worst-case legitimate staleness ~21h

STALE_AFTER_HOURS is 22, not 20 (would false-alarm on a legitimately slow
morning) and not 30 (a once-daily probe with a 30h threshold has a real
detection latency of 48h, which defeats the purpose).

Exit codes:  0 = live and fresh   1 = down, stale, or unreadable
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import requests

DEFAULT_BASE = "https://www.plantpricetracker.com"
STALE_AFTER_HOURS = 22.0

# Prices are allowed to lag the pipeline by one full cycle before this fires:
# an individual scraper failing is already alarmed elsewhere, and this should
# only catch the case where NOTHING has updated. Separate from the threshold
# above because it is a different failure — the pipeline running happily while
# every scraper returns nothing keeps generated_at fresh forever.
DATA_STALE_AFTER_HOURS = 30.0
ATTEMPTS = 3
BACKOFF_SECONDS = 5
TIMEOUT = 20

# Identify ourselves; an unlabelled probe looks like the scrapers we ask others
# to tolerate.
HEADERS = {"User-Agent": "PlantPriceTrackerLiveness/1.0 (+https://www.plantpricetracker.com/bot)"}


def fetch(url, attempts=ATTEMPTS, backoff=BACKOFF_SECONDS, sleep=time.sleep):
    """GET with retries. A single CDN blip must not page anyone.

    Returns (response, error_string). Exactly one is None.
    """
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r, None
            last = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        if i < attempts - 1:
            sleep(backoff * (i + 1))
    return None, last


def _parse_ts(raw, field):
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None, f"{field} is not an ISO timestamp: {raw!r}"
    if ts.tzinfo is None:
        return None, f"{field} has no timezone: {raw!r}"
    return ts, None


def parse_generated_at(text):
    """Pull `generated_at` out of health.json. Returns (datetime, error)."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"health.json is not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "health.json is not a JSON object"
    raw = payload.get("generated_at")
    if not raw:
        return None, "health.json has no generated_at field"
    return _parse_ts(raw, "generated_at")


def parse_newest_price_at(text):
    """Pull `newest_price_at`. Absent is tolerated (older deploys); bad is not."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(payload, dict) or payload.get("newest_price_at") in (None, ""):
        return None, None
    return _parse_ts(payload["newest_price_at"], "newest_price_at")


def check(base=DEFAULT_BASE, now=None, sleep=time.sleep, stale_after=STALE_AFTER_HOURS,
          data_stale_after=DATA_STALE_AFTER_HOURS):
    """Returns (ok: bool, lines: list[str]). Pure enough to test."""
    now = now or datetime.now(timezone.utc)
    base = base.rstrip("/")
    problems, notes = [], []

    _, err = fetch(base + "/", sleep=sleep)
    if err:
        problems.append(f"homepage unreachable ({err}) — the site is DOWN")
    else:
        notes.append("homepage: 200")

    resp, err = fetch(base + "/health.json", sleep=sleep)
    if err:
        problems.append(
            f"/health.json unreachable ({err}) — deploy may predate the "
            f"heartbeat, or the site is down"
        )
        return not problems, problems + notes

    ts, err = parse_generated_at(resp.text)
    if err:
        problems.append(err)
        return not problems, problems + notes

    age_h = (now - ts).total_seconds() / 3600.0
    notes.append(f"health.json generated_at={ts.isoformat()} age={age_h:.1f}h")

    if age_h < -0.5:
        # Ahead of us by more than clock jitter: a wrong clock somewhere, and
        # the number cannot be trusted in either direction.
        problems.append(
            f"generated_at is {abs(age_h):.1f}h in the FUTURE — clock skew; "
            f"freshness cannot be verified"
        )
    elif age_h > stale_after:
        problems.append(
            f"content is {age_h:.1f}h old (limit {stale_after:.0f}h) — the "
            f"pipeline published nothing, or the deploy is stuck"
        )

    # Separate question: the pipeline may be running perfectly while every
    # scraper quietly returns nothing, which keeps generated_at fresh forever.
    price_ts, price_err = parse_newest_price_at(resp.text)
    if price_err:
        problems.append(price_err)
    elif price_ts is not None:
        price_age_h = (now - price_ts).total_seconds() / 3600.0
        notes.append(f"newest_price_at={price_ts.isoformat()} age={price_age_h:.1f}h")
        if price_age_h > data_stale_after:
            problems.append(
                f"prices are {price_age_h:.1f}h old (limit {data_stale_after:.0f}h) "
                f"while the pipeline is still running — scrapers are returning "
                f"nothing and the site is serving frozen prices"
            )

    return not problems, problems + notes


def main():
    p = argparse.ArgumentParser(description="External liveness + freshness check")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--stale-after", type=float, default=STALE_AFTER_HOURS)
    args = p.parse_args()

    ok, lines = check(base=args.base, stale_after=args.stale_after)
    for line in lines:
        print(line)
    if not ok:
        # ::error:: surfaces in the Actions annotation API, which is readable
        # without signing in; raw logs are not.
        for line in lines:
            if "200" not in line and "age=" not in line:
                print(f"::error::LIVENESS: {line}")
        return 1
    print("Site is live and fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
