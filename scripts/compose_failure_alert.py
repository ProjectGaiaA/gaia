#!/usr/bin/env python
"""Compose the body of the failure-alert email for scrape.yml.

WHY THIS IS A SCRIPT AND NOT A HEREDOC IN THE YAML
--------------------------------------------------
The alert body is the only part of the alert path that can be exercised
offline. The SMTP hop cannot be: nobody can prove a message was delivered
without a mailbox and a live server. So everything that CAN be proven is
pulled out of the workflow and into a file pytest can run, and the untestable
remainder is kept to a single `uses:` step.

WHY IT RE-DERIVES THE SUMMARY INSTEAD OF READING ONE
----------------------------------------------------
`Raise alarms` in scrape.yml is the single alarm point, and it is heavily
red-teamed (tests/test_reproducibility_guard_is_not_a_gate.py runs its body
verbatim). Rewriting it to also tee its reasons into a file would put that
step's behaviour at risk for a cosmetic gain. Instead this script reads the
SAME `$GITHUB_ENV` flags that `Raise alarms` reads, and
tests/test_failure_alert_email.py::test_every_flag_raise_alarms_reads_is_in_
the_alert asserts the two lists have not drifted apart. Duplication that a
test pins is safer here than surgery on the alarm point.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It never raises. A crash here runs under `continue-on-error: true`, but a
body that failed to compose would still cost the operator the one artifact
the email exists to carry, so every optional input is read defensively and
degrades to a line that says it could not be read. An alert that arrives
incomplete beats an alert that does not arrive.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MANIFEST = Path("data/last_manifest.json")

# Mirrors the `${FLAG:-0}` reads in scrape.yml's `Raise alarms` step, in the
# same order. Kept in step by test_every_flag_raise_alarms_reads_is_in_the_alert.
FLAG_REASONS: list[tuple[str, str]] = [
    (
        "QUARANTINED",
        "Bad rows were quarantined by the data sanity gate. The good rows "
        "still published; the quarantined ones are missing from the site.",
    ),
    (
        "TESTS_FAILED",
        "pytest failed — a code defect, not a data problem. Download the "
        "'pytest-output' artifact from the run page for the failure list.",
    ),
    (
        "VERIFY_FAILED",
        "Live price spot-checks mismatched — a scraper may be reading the "
        "wrong element, which publishes WRONG prices rather than none.",
    ),
    (
        "AUDITS_ALARMED",
        "The nightly offline audits raised an alarm. Download the "
        "'nightly-audit' artifact. Good data still published.",
    ),
    (
        "REBUILD_DIVERGED",
        "Rebuilding site/ changed it — a step after 'Build site' writes a "
        "build input and needs moving earlier. The corrected build published.",
    ),
    (
        "REBUILD_CHECK_FAILED",
        "The reproducibility check could not run, so this cycle has NO answer "
        "on whether the build reproduces. Prices still published.",
    ),
]


def _flag(name: str) -> bool:
    return os.environ.get(name, "0") == "1"


def _failed_scrapers() -> list[str]:
    """Parse ALERT_SCRAPER_OUTCOMES ('id=outcome,id=outcome,...').

    The workflow builds it from the same `${{ steps.*.outcome }}` expressions
    `Raise alarms` uses, so the two cannot disagree about which retailer died.
    """
    raw = os.environ.get("ALERT_SCRAPER_OUTCOMES", "").strip()
    failed = []
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, outcome = pair.partition("=")
        if outcome.strip() == "failure":
            failed.append(name.strip())
    return failed


def _manifest_lines() -> list[str]:
    """Health from the manifest this run just wrote.

    Absent is a real and expected state, not an error: the data sanity gate
    blocks BEFORE the manifest is committed, and on a fresh checkout of a
    blocked cycle there may be no file at all. Say which it is.
    """
    if not MANIFEST.exists():
        return [f"  (no {MANIFEST} in the workspace — the run may have been "
                "blocked before any scraper wrote one)"]
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"  (could not read {MANIFEST}: {exc})"]
    if not isinstance(data, dict):
        return [f"  (unexpected shape in {MANIFEST}: {type(data).__name__})"]

    degraded = data.get("degraded_retailers") or []
    if not isinstance(degraded, list):
        degraded = [str(degraded)]
    lines = [
        f"  pipeline_status    : {data.get('pipeline_status', 'unknown')}",
        f"  degraded_retailers : {', '.join(str(d) for d in degraded) or 'none'}",
        f"  timestamp          : {data.get('timestamp', 'unknown')}",
        f"  prices collected   : {data.get('total_prices_collected', 'unknown')}",
        f"  anomalies          : {data.get('total_anomalies', 'unknown')}",
    ]

    # Per-retailer found/expected. runner.py scores health as
    # products_found / products_expected, so this is the number that decides
    # "degraded" — worth showing rather than only the verdict it produced.
    retailers = data.get("retailers")
    if isinstance(retailers, list) and retailers:
        lines.append("  per retailer (found/expected, prices):")
        for r in retailers:
            if not isinstance(r, dict):
                continue
            lines.append(
                "    {:<22} {}/{}  {} prices  [{}]".format(
                    str(r.get("retailer_id", "?"))[:22],
                    r.get("products_found", "?"),
                    r.get("products_expected", "?"),
                    r.get("prices_collected", "?"),
                    r.get("status", "?"),
                )
            )
    return lines


def compose() -> tuple[str, str]:
    """Return (subject, body). Pure with respect to os.environ and the cwd."""
    env = os.environ.get
    server = env("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = env("GITHUB_REPOSITORY", "unknown/unknown")
    run_id = env("GITHUB_RUN_ID", "")
    attempt = env("GITHUB_RUN_ATTEMPT", "1")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else "(run id unavailable)"

    failed = _failed_scrapers()
    commit_outcome = env("ALERT_COMMIT_OUTCOME", "") or "skipped"
    published = commit_outcome == "success"

    reasons: list[str] = []
    tags: list[str] = []
    if failed:
        reasons.append(
            "Scraper FAILED for: " + " ".join(failed)
            + " — a dead retailer, a layout change, or a crash."
        )
        tags.append("scrapers")
    for flag, reason in FLAG_REASONS:
        if _flag(flag):
            reasons.append(reason)
            tags.append(flag.lower())
    if not published:
        reasons.append(
            f"NOTHING WAS PUBLISHED this cycle (commit step: {commit_outcome}). "
            "The live site is still serving the last good build, so visitors "
            "see stale prices rather than a broken site."
        )
        tags.append("publish")

    if not reasons:
        # The job went red without any flag this script knows about — an
        # infrastructure failure, a timeout, or a step that failed before the
        # flags were set. Saying "no problems" here would be a lie the operator
        # would act on.
        reasons.append(
            "The run failed but none of the known alarm flags were set. That "
            "means a step failed OUTSIDE the alarm path — a timeout, a runner "
            "or network failure, a dependency install, or the checkout. Open "
            "the run and read the first red step."
        )
        tags.append("unclassified")

    subject = "[PlantPriceTracker] Daily Scrape FAILED — " + ", ".join(tags)

    body = [
        "The twice-daily scrape for plantpricetracker.com finished RED.",
        "",
        f"Run       : {run_url}",
        f"Attempt   : {attempt}",
        f"Workflow  : {env('GITHUB_WORKFLOW', 'Daily Scrape')}",
        f"Repository: {repo}",
        f"Commit    : {env('GITHUB_SHA', 'unknown')[:12]} on {env('GITHUB_REF_NAME', 'unknown')}",
        f"Trigger   : {env('GITHUB_EVENT_NAME', 'unknown')}",
        "",
        "WHAT ALARMED",
        "------------",
    ]
    body += [f"  {i}. {r}" for i, r in enumerate(reasons, 1)]
    body += [
        "",
        "DID ANYTHING PUBLISH?",
        "---------------------",
        (
            "  YES — data from the healthy retailers was committed and pushed, "
            "so Vercel has already deployed it. The alarms above are things "
            "that need attention, not reasons the site is down."
            if published
            else
            "  NO — the commit step did not succeed (outcome: "
            f"{commit_outcome}). This cycle's prices were dropped. The live "
            "site keeps serving the last good build; prices are ageing."
        ),
        "",
        "PIPELINE HEALTH (data/last_manifest.json as of this run)",
        "-------------------------------------------------------",
    ]
    body += _manifest_lines()
    body += [
        "",
        "WHERE TO LOOK, IN ORDER",
        "-----------------------",
        f"  1. {run_url}",
        "     The 'Raise alarms' step at the bottom names every problem with an",
        "     ::error:: annotation. Annotations are readable without signing in;",
        "     the raw logs are not.",
        "  2. The run's Artifacts section: 'pytest-output' (test failures) and",
        "     'nightly-audit' (audit findings, plus data/audit_report.json).",
        "  3. If a single retailer failed, that is usually a layout change on",
        "     their site. Reproduce locally with:",
        "       python -X utf8 -m scrapers.runner --retailer <id> --skip-promos",
        "  4. If NOTHING published for two consecutive cycles, the heartbeat",
        f"     workflow will also fire: {server}/{repo}/actions/workflows/heartbeat.yml",
        "",
        "This message was sent by the 'Send failure alert email' step in",
        ".github/workflows/scrape.yml. It is best-effort: it runs with",
        "continue-on-error, so a mail outage cannot redden a run on its own —",
        "and equally, silence from this mailbox is NOT proof the pipeline is",
        "healthy. The workflow's own red/green status remains the source of",
        "truth. See ALERTS_RUNBOOK.md.",
        "",
    ]
    return subject, "\n".join(body)


def main() -> int:
    subject, body = compose()
    out = Path(os.environ.get("ALERT_BODY_FILE", "alert_body.txt"))
    try:
        out.write_text(body, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - only a broken runner disk
        print(f"::warning::could not write {out}: {exc}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        try:
            with open(github_output, "a", encoding="utf-8") as fh:
                fh.write(f"subject={subject}\n")
        except OSError as exc:  # pragma: no cover
            print(f"::warning::could not write GITHUB_OUTPUT: {exc}")
    print(f"Subject: {subject}")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
