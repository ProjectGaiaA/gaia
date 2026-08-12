"""The audit step must never block a publish — asserted, not asserted-in-prose.

nightly_audits.py used to claim its own harmlessness with a sentence:
"the workflow runs it AFTER the commit step". That sentence was false. The
audits are `Nightly offline audits` (scrape.yml, before the commit) and the
commit is `Commit updated price data`. A red team found it; nothing could
have caught it, because the sentence was the only thing asserting it.

What actually makes the audits non-gating is the step BODY: `set +e`, capture
`${PIPESTATUS[0]}`, export a flag, and never propagate the code. So the body
is what gets tested here — run verbatim out of the YAML, under the shell
GitHub Actions uses (`bash --noprofile --norc -e -o pipefail`), against a
stub interpreter that alarms and one that crashes.

`if: always()` on the commit step was considered and rejected: the data
sanity gate, the build and the link check all sit between the checkout and
the commit and are meant to BLOCK. `if: always()` would publish through them.
"""

import os
import shutil
import subprocess
import stat
import textwrap

import pytest
import yaml

WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".github", "workflows", "scrape.yml")
AUDIT_STEP = "Nightly offline audits"
COMMIT_STEP = "Commit updated price data"


def _steps():
    with open(WORKFLOW, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    (job,) = doc["jobs"].values()
    return job["steps"]


def _step(name):
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW}")


def _fake_python(tmp_path, body):
    """A stand-in `python` on PATH, so the step body is exercised without
    running the real audits. Tests never touch the network and never depend on
    how the host resolves `python`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "python"
    script.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(bindir)


def _run_step_body(tmp_path, body, fake_python_body):
    """Run a step's `run:` block the way Actions runs it, and return
    (exit code, contents of GITHUB_ENV)."""
    script = tmp_path / "step.sh"
    script.write_text(body, encoding="utf-8")
    env_file = tmp_path / "github_env"
    env_file.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = _fake_python(tmp_path, fake_python_body) + os.pathsep + env["PATH"]
    env["GITHUB_ENV"] = str(env_file)
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
    )
    return proc.returncode, env_file.read_text(encoding="utf-8"), proc


BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required to run a workflow step body")


# --------------------------------------------------------------------------
# the ordering fact the old docstring got backwards
# --------------------------------------------------------------------------

def test_the_audits_run_before_the_commit_not_after_it():
    """Pinned so the retracted claim cannot quietly come back. If someone DOES
    move the audits after the commit, this fails and they must update the
    docstring that now says the opposite."""
    names = [s.get("name") for s in _steps()]
    assert AUDIT_STEP in names and COMMIT_STEP in names
    assert names.index(AUDIT_STEP) < names.index(COMMIT_STEP), (
        "the audits run BEFORE the commit; nothing about their non-gating "
        "property comes from ordering"
    )


def test_the_commit_step_is_not_unconditional():
    """The other half of the choice made in the docstring: the commit must
    stay gated by the steps before it, or a failed sanity gate would publish."""
    assert "always()" not in str(_step(COMMIT_STEP).get("if", ""))


# --------------------------------------------------------------------------
# the property that actually holds: the step body always exits 0
# --------------------------------------------------------------------------

@needs_bash
def test_audit_step_exits_zero_when_the_audit_alarms(tmp_path):
    code, github_env, proc = _run_step_body(
        tmp_path, _step(AUDIT_STEP)["run"], "echo 'ALARM'; exit 2")
    assert code == 0, f"the audit step gated the publish: {proc.stderr}"
    assert "AUDITS_ALARMED=1" in github_env, "the alarm must still be recorded"


@needs_bash
def test_audit_step_exits_zero_when_the_audit_crashes(tmp_path):
    """A traceback is not an alarm — it is a broken audit. It must still not
    take the publish down with it."""
    code, github_env, proc = _run_step_body(
        tmp_path, _step(AUDIT_STEP)["run"],
        "echo 'Traceback (most recent call last): boom' >&2; exit 1")
    assert code == 0, f"a crashing audit gated the publish: {proc.stderr}"
    assert "AUDITS_ALARMED=1" in github_env


@needs_bash
def test_audit_step_does_not_raise_the_flag_when_the_audit_is_clean(tmp_path):
    """The inverse direction. A flag that is always set is not a signal."""
    code, github_env, _proc = _run_step_body(
        tmp_path, _step(AUDIT_STEP)["run"], "echo 'No alarms.'; exit 0")
    assert code == 0
    assert "AUDITS_ALARMED" not in github_env


@needs_bash
def test_the_bash_harness_can_actually_fail(tmp_path):
    """R2: a check that cannot fail proves nothing. Same harness, same shell,
    a body that does NOT swallow the exit code — this must come back nonzero,
    otherwise the three tests above are measuring nothing."""
    code, _env, _proc = _run_step_body(
        tmp_path, "python -X utf8 scripts/nightly_audits.py | tee audit_out.txt\n",
        "exit 2")
    assert code != 0
