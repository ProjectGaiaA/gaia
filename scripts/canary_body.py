"""Compose the monthly canary email body.

The canary's entire job is to prove the SMTP path still works, so this must
NEVER raise: a crash here sends no email, which is indistinguishable from a dead
pipeline — the exact ambiguity the canary exists to remove. Every read is
wrapped, and a totally unreadable repo still produces a valid body saying so.

Why monthly and not weekly: weekly is 52 chances a year for Gmail to reclassify
the sender, and it trains the reflex to filter. The predecessor,
weekly-recovery-email.yml, ran 18 times, reported success every time, and sent
zero emails — its trigger file never existed in the repo. It was deleted rather
than repaired.

Why the backlog lives in the BODY and never the subject: with zero affiliate
links live, a status-bearing subject would read "PROBLEMS" every month for
months, and a subject that always says PROBLEMS is a subject nobody reads. The
subject carries liveness and a sequence number only, so a missing month shows up
as a numeric gap in a threaded inbox.
"""

import json
import os
from datetime import datetime, timezone

DATA_DIR = "data"
SEQ_EPOCH = (2026, 8)  # canary #1 is August 2026


def sequence_number(now):
    """Months since the epoch, 1-based. A skipped month leaves a visible gap."""
    return (now.year - SEQ_EPOCH[0]) * 12 + (now.month - SEQ_EPOCH[1]) + 1


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _age_hours(iso, now):
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        return None
    return (now - ts).total_seconds() / 3600.0


def build_body(now=None, data_dir=DATA_DIR):
    now = now or datetime.now(timezone.utc)
    seq = sequence_number(now)
    lines = [
        f"PlantPriceTracker monthly canary #{seq} — {now:%Y-%m-%d}",
        "",
        "This email exists to prove the alert channel still works. If you did",
        "not receive one last month, the channel is broken and every 'no news'",
        "since then meant nothing.",
        "",
    ]

    status = _load(os.path.join(data_dir, "status.json"))
    if not isinstance(status, dict):
        lines += ["STATUS: data/status.json unreadable, missing, or malformed.", ""]
    else:
        # Every nested read is type-checked. A malformed status.json must
        # degrade to "unknown", never to an exception — see module docstring.
        gates = status.get("gates")
        if not isinstance(gates, dict):
            gates = {}
        age = _age_hours(status.get("generated_at"), now)
        age_txt = f"{age:.1f}h" if age is not None else "unknown"
        lines += [
            f"Last pipeline run:   {status.get('generated_at', 'unknown')} ({age_txt} ago)",
            f"Built from commit:   {status.get('built_from_commit', 'unknown')}",
            f"Data sanity gate:    {gates.get('data_sanity', 'unknown')}",
            f"Tests:               {gates.get('tests', 'unknown')}",
            f"Quarantined rows:    {gates.get('quarantined_rows', 'unknown')}",
            "",
        ]
        silent = status.get("silent_retailers")
        if not isinstance(silent, list):
            silent = []
        if silent:
            lines += [f"RETAILERS WRITING ZERO ROWS: {', '.join(str(s) for s in silent)}", ""]

    retailers = _load(os.path.join(data_dir, "retailers.json")) or []
    if isinstance(retailers, list):
        active = [r for r in retailers if isinstance(r, dict) and r.get("active")]
        inactive = [r for r in retailers if isinstance(r, dict) and not r.get("active")]
        lines.append(f"Retailers: {len(active)} active, {len(inactive)} deactivated")
        if inactive:
            names = ", ".join(str(r.get("id")) for r in inactive)
            lines.append(f"  deactivated: {names}")
        missing_aff = [
            str(r.get("id")) for r in active
            if not (r.get("affiliate_template") or r.get("affiliate_url"))
        ]
        if missing_aff:
            lines += [
                "",
                f"NO AFFILIATE LINK ({len(missing_aff)}): {', '.join(missing_aff)}",
                "  The site earns nothing from these until a template is filled in.",
            ]
        lines.append("")

    lines += [
        "Full detail: data/status.json in the repo.",
        "Live check:  https://www.plantpricetracker.com/health.json",
    ]
    return "\n".join(lines)


def main():
    now = datetime.now(timezone.utc)
    try:
        body = build_body(now=now)
    except Exception as exc:  # noqa: BLE001 — sending SOMETHING beats sending nothing
        body = (
            f"PlantPriceTracker monthly canary #{sequence_number(now)} — {now:%Y-%m-%d}\n\n"
            f"The channel is alive, but composing the status summary failed:\n"
            f"  {type(exc).__name__}: {exc}\n"
        )
    with open("canary_body.txt", "w", encoding="utf-8") as f:
        f.write(body + "\n")
    print(body)
    seq_line = f"seq={sequence_number(now)}"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"{seq_line}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
