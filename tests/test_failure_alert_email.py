"""The failure-alert email must never be able to change what a run concludes.

Open item B-2: until this landed, the only signal that a cycle went wrong was
the workflow's red/green dot on a page nobody opens.

The hazard in fixing that is not "the email does not arrive" — it is the
email path becoming a THIRD way for the run to go red. A mail step that fails
on a rate limit, an expired token or a DNS blip would manufacture a false
alarm twice a day, and the operator would learn to ignore both the mailbox and
the dot. So the properties pinned here are, in priority order:

  1. no alert step can block a publish   (they all sit after Commit)
  2. no alert step can redden a run      (continue-on-error on every one)
  3. no alert step runs on a green run   (except the configuration nag)
  4. missing secrets are a warning, never a failure
  5. the body carries the actual alarm summary, not just "it failed"

Properties 1-4 are structure and are read out of the YAML. Property 5 is
behaviour and is exercised against scripts/compose_failure_alert.py directly.

The SMTP hop itself is NOT tested and cannot be: proving a message was
delivered needs a live server and a mailbox. Everything up to the handoff is
tested; the handoff is documented in ALERTS_RUNBOOK.md instead. Do not read a
green run of this file as evidence that mail works.
"""

import os
import re
import shutil
import stat
import subprocess
import textwrap

import pytest
import yaml

from scripts.compose_failure_alert import FLAG_REASONS, compose

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPE = os.path.join(ROOT, ".github", "workflows", "scrape.yml")
HEARTBEAT = os.path.join(ROOT, ".github", "workflows", "heartbeat.yml")

ALARM_STEP = "Raise alarms"
COMMIT_STEP = "Commit updated price data"
SMTP_STEP = "Check whether alert email is configured"
COMPOSE_STEP = "Compose failure alert"
MAIL_STEP = "Send failure alert email"
REPORT_STEP = "Report how this failure was signalled"
ALERT_STEPS = [SMTP_STEP, COMPOSE_STEP, MAIL_STEP, REPORT_STEP]

OPS_MAILBOX = "projectgaiaa@proton.me"

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    BASH is None, reason="bash is required to run a workflow step body")


def _steps(workflow=SCRAPE):
    with open(workflow, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    (job,) = doc["jobs"].values()
    return job["steps"]


def _step(name, workflow=SCRAPE):
    for step in _steps(workflow):
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {workflow}")


def _names(workflow=SCRAPE):
    return [s.get("name") for s in _steps(workflow)]


# ==========================================================================
# 1. nothing in the alert path can block a publish
# ==========================================================================

def test_every_alert_step_sits_after_the_commit_step():
    """The blocking path is checkout -> ... -> Commit. Anything before Commit
    that fails discards ~88 minutes of scraped prices (see the comment on the
    commit step). The alert path must be entirely downstream of it."""
    names = _names()
    commit_at = names.index(COMMIT_STEP)
    for step in ALERT_STEPS:
        assert step in names, f"{step!r} is missing from scrape.yml"
        assert names.index(step) > commit_at, (
            f"{step!r} runs BEFORE {COMMIT_STEP!r}; a failure in the alert "
            "path would discard a cycle of scraped prices"
        )


def test_every_alert_step_sits_after_the_alarm_step():
    """`Raise alarms` is the single alarm point and the last step that can turn
    the run red. Composing the alert before it would describe a run whose
    verdict had not been reached."""
    names = _names()
    alarm_at = names.index(ALARM_STEP)
    for step in ALERT_STEPS:
        assert names.index(step) > alarm_at, (
            f"{step!r} runs before {ALARM_STEP!r}")


def test_the_mail_step_is_the_last_thing_that_could_matter():
    """Ordering within the alert path: configuration is checked, then the body
    is composed, then it is sent, then the outcome is reported."""
    names = _names()
    assert (names.index(SMTP_STEP) < names.index(COMPOSE_STEP)
            < names.index(MAIL_STEP) < names.index(REPORT_STEP))


def test_the_commit_step_is_still_not_unconditional():
    """Guarded here too, not only in test_audit_step_is_not_a_gate.py. Adding
    an alert path is exactly the kind of change that tempts someone to reach
    for `if: always()` on the commit so the alert 'sees everything'."""
    assert "always()" not in str(_step(COMMIT_STEP).get("if", ""))


# ==========================================================================
# 2. nothing in the alert path can redden a run
# ==========================================================================

@pytest.mark.parametrize("name", ALERT_STEPS)
def test_alert_steps_are_continue_on_error(name):
    """The property that makes a mail outage harmless. Without it, an SMTP
    host that is down turns every run red — including the green ones, via the
    `if: always()` configuration check."""
    assert _step(name).get("continue-on-error") is True, (
        f"{name!r} must be continue-on-error: true, or a mail-side failure "
        "becomes a workflow failure and the alert path starts manufacturing "
        "the alarms it exists to report"
    )


@pytest.mark.parametrize("name", [SMTP_STEP, COMPOSE_STEP, REPORT_STEP])
def test_shell_alert_steps_end_in_an_unconditional_exit_zero(name):
    """Belt to continue-on-error's braces, matching the reproducibility
    guard's convention. Only bites when the LAST command of the body fails."""
    body = [ln for ln in _step(name)["run"].rstrip().splitlines() if ln.strip()]
    assert body[-1].strip() == "exit 0", (
        f"the body of {name!r} ends on {body[-1]!r}")


@needs_bash
@pytest.mark.parametrize("configured,mail_outcome,expected", [
    ("true", "success", "ACCEPTED by the server"),
    ("true", "failure", "DID NOT SEND"),
    ("true", "skipped", "DID NOT SEND"),
    ("true", "", "DID NOT SEND"),
    ("false", "skipped", "UNAVAILABLE, secrets are not set"),
    ("false", "", "UNAVAILABLE, secrets are not set"),
    # The configuration check is continue-on-error, so it can fail and leave
    # its output unset. That is NOT the same fact as "secrets are missing",
    # and reporting the second sends the operator to the secrets page over a
    # broken check. Same rule as REBUILD_CHECK_FAILED: a check that could not
    # run is not a check that answered.
    ("", "skipped", "UNKNOWN"),
    ("", "", "UNKNOWN"),
])
def test_the_report_step_is_honest_in_every_state(tmp_path, configured,
                                                  mail_outcome, expected):
    body = (_step(REPORT_STEP)["run"]
            .replace("${{ steps.smtp.outputs.configured }}", configured)
            .replace("${{ steps.mail.outcome }}", mail_outcome))
    assert "${{" not in body, "an unexpanded Actions expression is left in the body"
    rc, _out, proc = _run_body(tmp_path, body)
    assert rc == 0, f"the report step exited {rc}: {proc.stderr}"
    assert expected in proc.stdout, (
        f"configured={configured!r} mail={mail_outcome!r} reported "
        f"{proc.stdout!r}, expected {expected!r}")


def test_an_unset_configuration_verdict_is_not_reported_as_missing_secrets():
    """Stated separately because the two branches are one `case` pattern apart
    and collapsing them back together would be an easy 'simplification'."""
    body = _step(REPORT_STEP)["run"]
    assert "UNKNOWN" in body and "secrets are not set" in body, (
        "the report step must distinguish 'secrets are missing' from 'the "
        "check did not answer'")


def test_the_report_step_never_exits_nonzero():
    """It runs on an already-red run, so exiting 1 would be harmless today —
    but it is one edit away from being copied somewhere it is not. It reports;
    it does not judge."""
    body = _step(REPORT_STEP)["run"]
    assert not re.search(r"^\s*exit\s+[1-9]", body, re.M), (
        "the report step must never exit non-zero")


# ==========================================================================
# 3. the conditions. Dry-parsed against the states a real run can be in.
# ==========================================================================

def _evaluate(expr, failed, smtp_configured):
    """A deliberately tiny evaluator for the exact expression forms used here.

    It understands `always()`, `failure()`, `&&` and one
    `steps.smtp.outputs.configured == 'true'` comparison — and NOTHING else,
    so an expression that grows a form this cannot parse raises rather than
    silently evaluating to something plausible.
    """
    expr = expr.strip()
    out = True
    for term in [t.strip() for t in expr.split("&&")]:
        if term == "always()":
            value = True
        elif term == "failure()":
            value = failed
        elif term == "success()":
            value = not failed
        elif term == "steps.smtp.outputs.configured == 'true'":
            value = smtp_configured
        else:
            raise AssertionError(
                f"unparseable condition term {term!r} in {expr!r} — extend "
                "this evaluator rather than letting the test guess")
        out = out and value
    return out


# (run failed?, smtp configured?) -> should the mail step run?
MAIL_TRUTH_TABLE = [
    (False, False, False),  # green run, no secrets     -> silent
    (False, True, False),   # green run, secrets set    -> silent (no spam)
    (True, False, False),   # red run, no secrets       -> skipped, warned
    (True, True, True),     # red run, secrets set      -> SEND
]


@pytest.mark.parametrize("failed,configured,expected", MAIL_TRUTH_TABLE)
def test_mail_step_condition(failed, configured, expected):
    got = _evaluate(_step(MAIL_STEP)["if"], failed, configured)
    assert got is expected, (
        f"mail step condition {_step(MAIL_STEP)['if']!r} evaluated to {got} "
        f"for failed={failed} configured={configured}; expected {expected}")


def test_the_mail_step_never_fires_on_a_green_run():
    """Stated separately because it is the property an operator relies on: a
    message in this mailbox means something is wrong. If green runs could mail,
    the mailbox stops being a signal."""
    for configured in (True, False):
        assert not _evaluate(_step(MAIL_STEP)["if"], failed=False,
                             smtp_configured=configured)


def test_the_compose_step_only_runs_on_a_failed_run():
    assert _step(COMPOSE_STEP)["if"].strip() == "failure()"


def test_the_configuration_check_runs_on_every_run():
    """`always()`, not `failure()`, and deliberately. A configuration check
    that only runs when mail is needed tells the owner the mail path is dead
    on the one night it mattered. This one nags on every green run instead."""
    assert _step(SMTP_STEP)["if"].strip() == "always()"


# ==========================================================================
# 4. missing secrets are a warning, never a failure
# ==========================================================================

def _run_body(tmp_path, body, fake_python="exit 0\n", env_extra=None):
    """Run a step body the way Actions runs it: bash --noprofile --norc -e
    -o pipefail. Returns (rc, GITHUB_OUTPUT text, CompletedProcess)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    py = bindir / "python"
    py.write_text("#!/bin/sh\n" + textwrap.dedent(fake_python), encoding="utf-8")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)

    script = tmp_path / "step.sh"
    script.write_text(body, encoding="utf-8")
    out_file = tmp_path / "github_output"
    out_file.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    env["GITHUB_OUTPUT"] = str(out_file)
    env["GITHUB_ENV"] = str(tmp_path / "github_env")
    # The four secrets arrive as env: entries on the step, so an unset secret
    # is an EMPTY variable, not an absent one. Clear any real ones inherited
    # from the developer's shell so the test controls the state.
    for key in ("ALERT_SMTP_SERVER", "ALERT_SMTP_PORT",
                "ALERT_SMTP_USERNAME", "ALERT_SMTP_PASSWORD"):
        env[key] = ""
    env.update(env_extra or {})
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True)
    return proc.returncode, out_file.read_text(encoding="utf-8"), proc


@needs_bash
def test_unconfigured_smtp_warns_and_exits_zero(tmp_path):
    """The headline of property 4. An unconfigured mail path is the state this
    repo is in TODAY, on every single run. It must cost nothing."""
    rc, output, proc = _run_body(tmp_path, _step(SMTP_STEP)["run"])
    assert rc == 0, f"an unconfigured mail path failed the step: {proc.stderr}"
    assert "configured=false" in output
    assert "::warning::" in proc.stdout
    assert "::error::" not in proc.stdout, (
        "missing secrets are a warning, not an error")
    for secret in ("SMTP_SERVER", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"):
        assert secret in proc.stdout, (
            f"the warning must name {secret} so it is actionable without docs")


@needs_bash
def test_fully_configured_smtp_reports_configured_and_exits_zero(tmp_path):
    """The inverse direction. A check that always says 'false' is not a check."""
    rc, output, proc = _run_body(tmp_path, _step(SMTP_STEP)["run"], env_extra={
        "ALERT_SMTP_SERVER": "smtp.protonmail.ch",
        "ALERT_SMTP_PORT": "587",
        "ALERT_SMTP_USERNAME": "projectgaiaa@proton.me",
        "ALERT_SMTP_PASSWORD": "token",
    })
    assert rc == 0
    assert "configured=true" in output
    assert "::warning::" not in proc.stdout


@needs_bash
@pytest.mark.parametrize("missing", [
    "ALERT_SMTP_SERVER", "ALERT_SMTP_PORT",
    "ALERT_SMTP_USERNAME", "ALERT_SMTP_PASSWORD",
])
def test_a_partially_configured_mail_path_is_reported_as_unconfigured(tmp_path, missing):
    """Three secrets out of four is not a working mail path, and reporting it
    as configured would let the mail step fire and fail on every red run."""
    env = {
        "ALERT_SMTP_SERVER": "smtp.protonmail.ch",
        "ALERT_SMTP_PORT": "587",
        "ALERT_SMTP_USERNAME": "projectgaiaa@proton.me",
        "ALERT_SMTP_PASSWORD": "token",
    }
    env[missing] = ""
    rc, output, proc = _run_body(tmp_path, _step(SMTP_STEP)["run"], env_extra=env)
    assert rc == 0
    assert "configured=false" in output
    assert missing.replace("ALERT_", "") in proc.stdout


@needs_bash
def test_the_bash_harness_can_actually_fail(tmp_path):
    """R2: the bodies above prove nothing unless the same harness, same shell,
    reports non-zero for a body that does not swallow its exit code."""
    rc, _out, _proc = _run_body(tmp_path, "false\nexit 0\n")
    assert rc != 0, "the harness cannot observe a failure and proves nothing"


@needs_bash
def test_a_crashing_composer_still_produces_a_body_with_the_run_url(tmp_path):
    """The compose step's fallback. If the script dies, the operator must
    still get a message pointing at the run — an alert that arrives incomplete
    beats an alert that does not arrive."""
    rc, output, proc = _run_body(
        tmp_path, _step(COMPOSE_STEP)["run"],
        fake_python="echo 'Traceback: boom' >&2; exit 1",
        env_extra={
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "ProjectGaiaA/gaia",
            "GITHUB_RUN_ID": "42",
        })
    assert rc == 0, f"a crashing composer failed the step: {proc.stderr}"
    body = (tmp_path / "alert_body.txt").read_text(encoding="utf-8")
    assert "https://github.com/ProjectGaiaA/gaia/actions/runs/42" in body
    assert "subject=" in output
    assert "::warning::" in proc.stdout


@needs_bash
def test_a_composer_that_writes_an_empty_body_is_also_caught(tmp_path):
    """Exit 0 with nothing written is the quieter version of the same defect:
    dawidd6 would send an empty email, which reads as noise, not an alarm."""
    rc, _output, _proc = _run_body(
        tmp_path, _step(COMPOSE_STEP)["run"],
        fake_python="> alert_body.txt\nexit 0\n",
        env_extra={"GITHUB_SERVER_URL": "https://github.com",
                   "GITHUB_REPOSITORY": "ProjectGaiaA/gaia",
                   "GITHUB_RUN_ID": "42"})
    assert rc == 0
    assert (tmp_path / "alert_body.txt").stat().st_size > 0


# ==========================================================================
# 5. the recipient and the sender
# ==========================================================================

@pytest.mark.parametrize("workflow,step", [
    (SCRAPE, MAIL_STEP),
    (HEARTBEAT, "Send alert email"),
])
def test_alerts_go_to_the_ops_mailbox(workflow, step):
    assert OPS_MAILBOX in str(_step(step, workflow)["with"]["to"])


@pytest.mark.parametrize("workflow,step", [
    (SCRAPE, MAIL_STEP),
    (HEARTBEAT, "Send alert email"),
])
def test_the_from_address_falls_back_to_the_authenticated_account(workflow, step):
    """Not to a made-up noreply@plantpricetracker.com. Proton and most other
    providers reject a From the authenticated account may not send as, which
    fails every send with a 550 while all four secrets look correctly set."""
    sender = str(_step(step, workflow)["with"]["from"])
    assert "secrets.SMTP_USERNAME" in sender, (
        f"{step!r} in {os.path.basename(workflow)} falls back to {sender!r}")
    assert "noreply@" not in sender


def test_the_heartbeat_mail_step_is_still_continue_on_error():
    """Unchanged by this work, and load-bearing: the heartbeat's `Raise the
    alarm` step is what actually fails the job, and the mail step must not be
    able to pre-empt it."""
    assert _step("Send alert email", HEARTBEAT).get("continue-on-error") is True


def test_the_heartbeat_smtp_check_cannot_redden_a_healthy_heartbeat():
    """It runs unconditionally, including on healthy heartbeats. A failure
    there would read as PIPELINE DOWN when the pipeline is fine."""
    assert _step("Check whether SMTP is configured",
                 HEARTBEAT).get("continue-on-error") is True


# ==========================================================================
# the drift guard between `Raise alarms` and the composer
# ==========================================================================

def _flags_read_by(body):
    return set(re.findall(r"\$\{([A-Z_]+):-0\}", body))


def test_every_flag_raise_alarms_reads_is_in_the_alert():
    """The composer re-derives the summary from the same $GITHUB_ENV flags
    rather than being handed one, so the two lists can drift. They must not:
    a flag that alarms the run but never reaches the email produces a message
    that says a run failed without saying why.

    If this fails because a new flag was added to `Raise alarms`, add the
    matching entry to FLAG_REASONS in scripts/compose_failure_alert.py.
    """
    in_workflow = _flags_read_by(_step(ALARM_STEP)["run"])
    in_script = {name for name, _ in FLAG_REASONS}
    assert in_workflow == in_script, (
        f"only in Raise alarms: {sorted(in_workflow - in_script)}; "
        f"only in FLAG_REASONS: {sorted(in_script - in_workflow)}")


def test_the_flag_regex_actually_matches_something():
    """R2 again: if the regex stopped matching, the drift guard above would
    compare two empty sets and pass forever."""
    assert len(_flags_read_by(_step(ALARM_STEP)["run"])) >= 6


def _scraper_steps():
    """{retailer-id: step-id} for every per-retailer scrape step."""
    found = {}
    for step in _steps():
        match = re.search(r"--retailer\s+(\S+)", str(step.get("run", "")))
        if match and step.get("id"):
            found[match.group(1)] = step["id"]
    return found


def test_every_scraper_step_is_named_in_the_alert_env():
    """The quietest way this alert could lie.

    `ALERT_SCRAPER_OUTCOMES` refers to steps by id. An unknown id is NOT an
    error in Actions — `${{ steps.typo.outcome }}` expands to the empty
    string. So renaming a scrape step's id, or adding a retailer and
    forgetting the alert, produces an email that cheerfully omits the retailer
    that died, with nothing anywhere going red. `Raise alarms` has the same
    exposure and the same list; this pins both against the actual steps.
    """
    scrapers = _scraper_steps()
    assert len(scrapers) >= 7, f"only found {scrapers} — the regex is stale"

    env = _step(COMPOSE_STEP)["env"]["ALERT_SCRAPER_OUTCOMES"]
    alarm_body = _step(ALARM_STEP)["run"]

    for retailer, step_id in scrapers.items():
        expected = "%s=${{ steps.%s.outcome }}" % (retailer, step_id)
        assert expected in env, (
            f"{retailer!r} is scraped by step id {step_id!r} but the alert "
            f"email does not read it. Expected {expected!r} in "
            "ALERT_SCRAPER_OUTCOMES — without it a failure of this retailer "
            "is silently missing from the alert."
        )
        assert "${{ steps.%s.outcome }}" % step_id in alarm_body, (
            f"{retailer!r} is not read by {ALARM_STEP!r} either")

    # And no phantom entries: an id that no longer exists expands to empty and
    # would quietly stop reporting.
    referenced = set(re.findall(r"\$\{\{\s*steps\.(\w+)\.outcome\s*\}\}", env))
    assert referenced == set(scrapers.values()), (
        f"ALERT_SCRAPER_OUTCOMES references {sorted(referenced - set(scrapers.values()))} "
        f"which are not scrape steps, and misses "
        f"{sorted(set(scrapers.values()) - referenced)}")


# ==========================================================================
# the body itself
# ==========================================================================

RUN_ENV = {
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "ProjectGaiaA/gaia",
    "GITHUB_RUN_ID": "17654321",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_WORKFLOW": "Daily Scrape",
    "GITHUB_SHA": "a10bec9f9a803a75a888c7d64eb96cb12f305949",
    "GITHUB_REF_NAME": "main",
    "GITHUB_EVENT_NAME": "schedule",
}

ALL_FLAGS = [name for name, _ in FLAG_REASONS]


@pytest.fixture
def alert(monkeypatch, tmp_path):
    """Compose a body with a controlled environment and cwd.

    Every flag is cleared first: a leaked TESTS_FAILED from the developer's
    shell would make the 'stays quiet' assertions pass for the wrong reason.
    """
    def _compose(cwd=None, **env):
        monkeypatch.chdir(cwd or tmp_path)
        for key in [*ALL_FLAGS, "ALERT_SCRAPER_OUTCOMES", "ALERT_COMMIT_OUTCOME"]:
            monkeypatch.delenv(key, raising=False)
        for key, value in {**RUN_ENV, **env}.items():
            monkeypatch.setenv(key, value)
        return compose()
    return _compose


def test_body_carries_the_run_url(alert):
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success")
    assert "https://github.com/ProjectGaiaA/gaia/actions/runs/17654321" in body


def test_body_carries_the_attempt_and_commit(alert):
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success")
    assert "Attempt   : 2" in body
    assert "a10bec9f9a80" in body
    assert "main" in body


@pytest.mark.parametrize("flag,fragment", [
    ("TESTS_FAILED", "pytest failed"),
    ("QUARANTINED", "quarantined"),
    ("REBUILD_DIVERGED", "Rebuilding site/ changed it"),
    ("REBUILD_CHECK_FAILED", "reproducibility check could not run"),
    ("AUDITS_ALARMED", "nightly offline audits"),
    ("VERIFY_FAILED", "spot-checks mismatched"),
])
def test_each_flag_reaches_the_body(alert, flag, fragment):
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success", **{flag: "1"})
    assert fragment in body


@pytest.mark.parametrize("flag", ALL_FLAGS)
def test_an_unset_flag_stays_out_of_the_body(alert, flag):
    """The inverse direction. A body that lists every possible problem on
    every failure is noise, and the operator would stop reading it."""
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1")
    reason = dict(FLAG_REASONS)[flag]
    if flag == "TESTS_FAILED":
        assert reason in body
    else:
        assert reason not in body


def test_a_flag_set_to_something_other_than_one_does_not_alarm(alert):
    """`Raise alarms` compares against the literal string "1". The composer
    must agree, or the two disagree about what alarmed."""
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="0")
    assert "pytest failed" not in body


def test_failed_scrapers_are_named(alert):
    _subject, body = alert(
        ALERT_COMMIT_OUTCOME="success",
        ALERT_SCRAPER_OUTCOMES=(
            "nature-hills=success, planting-tree=failure, spring-hill=success, "
            "fast-growing-trees=failure, proven-winners-direct=success, "
            "great-garden-plants=success, stark-bros=skipped"),
    )
    assert "planting-tree" in body
    assert "fast-growing-trees" in body
    assert "nature-hills" not in body.split("WHAT ALARMED")[1].split("DID ANYTHING")[0]


def test_a_healthy_scraper_set_names_nobody(alert):
    _subject, body = alert(
        ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1",
        ALERT_SCRAPER_OUTCOMES="nature-hills=success, stark-bros=success")
    assert "Scraper FAILED" not in body


def test_the_body_says_whether_anything_published(alert):
    _subject, published = alert(ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1")
    assert "YES —" in published
    _subject, blocked = alert(ALERT_COMMIT_OUTCOME="failure")
    assert "NO —" in blocked
    assert "NOTHING WAS PUBLISHED" in blocked


def test_a_skipped_commit_step_reads_as_not_published(alert):
    """The commit step is SKIPPED, not failed, when the data sanity gate
    blocks. An empty outcome must never be read as a successful publish."""
    _subject, body = alert(ALERT_COMMIT_OUTCOME="")
    assert "NOTHING WAS PUBLISHED" in body
    assert "skipped" in body


def test_a_red_run_with_no_known_flags_says_so_rather_than_claiming_health(alert):
    """A timeout, a runner failure or a dependency install error fails the job
    without setting any flag. The body must not come back with an empty
    'WHAT ALARMED' section, which reads as 'nothing is wrong'."""
    _subject, body = alert(ALERT_COMMIT_OUTCOME="success")
    assert "none of the known alarm flags were set" in body
    assert "unclassified" in _subject


def test_the_subject_names_what_alarmed(alert):
    subject, _body = alert(ALERT_COMMIT_OUTCOME="failure", TESTS_FAILED="1",
                           AUDITS_ALARMED="1")
    assert subject.startswith("[PlantPriceTracker] Daily Scrape FAILED")
    assert "tests_failed" in subject
    assert "audits_alarmed" in subject
    assert "publish" in subject
    assert "\n" not in subject, "a multi-line subject would corrupt GITHUB_OUTPUT"


# --- the manifest section -------------------------------------------------

MANIFEST = {
    "timestamp": "2026-08-21T12:42:48.360576+00:00",
    "total_prices_collected": 735,
    "total_anomalies": 3,
    "pipeline_status": "degraded",
    "degraded_retailers": ["fast-growing-trees", "stark-bros"],
    "retailers": [
        {"retailer_id": "nature-hills", "status": "completed",
         "products_expected": 78, "products_found": 78, "prices_collected": 144},
        {"retailer_id": "stark-bros", "status": "failed",
         "products_expected": 40, "products_found": 3, "prices_collected": 3},
    ],
}


def _with_manifest(tmp_path, payload):
    import json
    (tmp_path / "data").mkdir(exist_ok=True)
    path = tmp_path / "data" / "last_manifest.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")
    return tmp_path


def test_degraded_retailers_reach_the_body(alert, tmp_path):
    _subject, body = alert(cwd=_with_manifest(tmp_path, MANIFEST),
                           ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1")
    assert "pipeline_status    : degraded" in body
    assert "fast-growing-trees, stark-bros" in body
    assert "2026-08-21T12:42:48" in body
    assert "735" in body


def test_per_retailer_counts_reach_the_body(alert, tmp_path):
    """found/expected is the ratio runner.py scores health on, so a retailer
    that returned 3 of 40 products is the actionable number, not the verdict
    it produced."""
    _subject, body = alert(cwd=_with_manifest(tmp_path, MANIFEST),
                           ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1")
    assert "3/40" in body
    assert "78/78" in body


def test_a_healthy_manifest_is_reported_as_healthy(alert, tmp_path):
    """The inverse direction: a body that always says 'degraded' is not a
    signal. A run can go red on a code defect with every retailer healthy."""
    healthy = {**MANIFEST, "pipeline_status": "healthy", "degraded_retailers": []}
    _subject, body = alert(cwd=_with_manifest(tmp_path, healthy),
                           ALERT_COMMIT_OUTCOME="success", TESTS_FAILED="1")
    assert "pipeline_status    : healthy" in body
    assert "degraded_retailers : none" in body


def test_a_missing_manifest_degrades_instead_of_crashing(alert, tmp_path):
    """The data sanity gate blocks BEFORE a manifest exists, which is exactly
    the run most worth emailing about. Losing the whole body to a traceback
    there would lose the alert."""
    _subject, body = alert(cwd=tmp_path, ALERT_COMMIT_OUTCOME="failure")
    assert "no data" in body and "last_manifest.json" in body
    assert "actions/runs/17654321" in body, "the run URL must survive"


@pytest.mark.parametrize("payload", [
    "{not json at all",
    "[1, 2, 3]",
    '{"degraded_retailers": "fast-growing-trees"}',
    "{}",
])
def test_a_malformed_manifest_degrades_instead_of_crashing(alert, tmp_path, payload):
    """A truncated or half-written manifest is a plausible product of the very
    crash being reported."""
    _subject, body = alert(cwd=_with_manifest(tmp_path, payload),
                           ALERT_COMMIT_OUTCOME="failure")
    assert "actions/runs/17654321" in body


def test_compose_never_raises_with_a_completely_empty_environment(monkeypatch, tmp_path):
    """The adversarial case: no GITHUB_* variables at all, no manifest, no
    flags. compose() must still return something sendable."""
    monkeypatch.chdir(tmp_path)
    for key in [*ALL_FLAGS, *RUN_ENV, "ALERT_SCRAPER_OUTCOMES",
                "ALERT_COMMIT_OUTCOME"]:
        monkeypatch.delenv(key, raising=False)
    subject, body = compose()
    assert subject and body
    assert "FAILED" in subject
