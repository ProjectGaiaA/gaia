"""The reproducibility guard must never be able to stop a publish, and must
be able to see a page the rebuild ADDS.

Two defects, both found by red team against a1272f3e:

F1  The step `Verify the build is reproducible` had no `continue-on-error:`
    and ran under `bash -eo pipefail`. Divergence itself was safe — the
    `git diff --quiet` sat in an `if`, so `-e` did not fire — but a non-zero
    `git add -A site/` or a crashing `python build.py` failed the step, which
    skipped `Commit updated price data`, which discards ~88 minutes of
    scraped prices for that cycle. The commit step's own comment warns about
    exactly this ("would turn a deliberately non-blocking audit into a
    publish blocker"); the new step reintroduced it one step upstream.

F1b `git diff` never reports untracked paths, so the guard was blind to a
    rebuild that ADDS a page. `test_the_old_form_was_blind_to_an_added_page`
    below is the control: it runs the pre-fix body against an added page and
    shows it reporting a clean no-op.

Everything here runs the step body VERBATIM out of the YAML, under the shell
GitHub Actions uses (`bash --noprofile --norc -e -o pipefail`), inside a real
throwaway git repository, with a stub `python` on PATH standing in for
build.py. Nothing asserts a property in prose.

Note the fix is `continue-on-error: true` on the GUARD, not `if: always()` on
the COMMIT step: the data sanity gate, the build and the link check sit
between the checkout and the commit and are meant to BLOCK.
tests/test_audit_step_is_not_a_gate.py pins that.
"""

import os
import shutil
import stat
import subprocess
import textwrap

import pytest
import yaml

WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows", "scrape.yml",
)
GUARD_STEP = "Verify the build is reproducible"
COMMIT_STEP = "Commit updated price data"
ALARM_STEP = "Raise alarms"

BASH = shutil.which("bash")
GIT = shutil.which("git")
needs_bash = pytest.mark.skipif(
    BASH is None or GIT is None,
    reason="bash and git are required to run a workflow step body",
)

# The body as it stood in a1272f3e, kept as a control. If the harness cannot
# show this one failing to notice an added page, the harness is measuring
# nothing (R2).
OLD_GUARD_BODY = textwrap.dedent("""\
    git add -A site/
    python -X utf8 build.py
    if git diff --quiet -- site/; then
      echo "Rebuild is a no-op — committed site/ matches its sources."
    else
      echo "REBUILD_DIVERGED=1" >> "$GITHUB_ENV"
      echo "::error::Rebuilding site/ changed it. Files:"
      git diff --name-only -- site/
    fi
""")


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


def _git(cwd, *args):
    return subprocess.run(
        [GIT, "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def _repo(tmp_path):
    """A throwaway repo whose committed site/ is the FIRST build's output."""
    repo = tmp_path / "repo"
    (repo / "site" / "plants").mkdir(parents=True)
    (repo / "site" / "index.html").write_text("home v1\n", encoding="utf-8")
    (repo / "site" / "plants" / "rose.html").write_text("rose v1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first build")
    return repo


def _fake_python(tmp_path, body):
    """A stand-in `python` on PATH, so the guard is exercised without running
    the real build.py. It receives `-X utf8 build.py` as its arguments."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "python"
    script.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(bindir)


def _run(repo, tmp_path, body, rebuild):
    """Run a step body the way Actions runs it.

    Returns (exit code, GITHUB_ENV contents, CompletedProcess).
    """
    script = tmp_path / "step.sh"
    script.write_text(body, encoding="utf-8")
    env_file = tmp_path / "github_env"
    env_file.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = _fake_python(tmp_path, rebuild) + os.pathsep + env["PATH"]
    env["GITHUB_ENV"] = str(env_file)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@t"
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
        cwd=str(repo), env=env, capture_output=True, text=True,
    )
    return proc.returncode, env_file.read_text(encoding="utf-8"), proc


def _breaking_git(tmp_path, failing_subcommand):
    """A `git` shim that delegates to the real git except for one subcommand,
    which it fails. Used to break the LAST command in a branch of the guard."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "git"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1 $2" = "{failing_subcommand}" ]; then\n'
        '  echo "git: simulated failure" >&2\n'
        "  exit 3\n"
        "fi\n"
        f'exec "{GIT.replace(chr(92), "/")}" "$@"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _guard(repo, tmp_path, rebuild):
    return _run(repo, tmp_path, _step(GUARD_STEP)["run"], rebuild)


# A rebuild that reproduces exactly: touch nothing.
REBUILD_REPRODUCES = "exit 0\n"


# --------------------------------------------------------------------------
# F1 — the guard can never block the publish
# --------------------------------------------------------------------------

def test_the_guard_step_is_marked_continue_on_error():
    """The outer half of the guarantee. Without it, anything Actions counts as
    a step failure skips the commit and throws the cycle away."""
    assert _step(GUARD_STEP).get("continue-on-error") is True, (
        "the reproducibility guard must be continue-on-error, or a failure "
        "inside it skips 'Commit updated price data' and discards a full "
        "cycle of scraped prices"
    )


def test_the_guard_runs_before_the_commit():
    """Ordering is the reason continue-on-error is load-bearing. If the guard
    ever moves after the commit, this fails and the comment above it — which
    says the commit below publishes the corrected build — must be rewritten."""
    names = [s.get("name") for s in _steps()]
    assert names.index(GUARD_STEP) < names.index(COMMIT_STEP)


def test_the_commit_step_is_still_not_unconditional():
    """The fix must not be `if: always()` on the commit. The sanity gate, the
    build and the link check are between here and there, and they BLOCK."""
    assert "always()" not in str(_step(COMMIT_STEP).get("if", ""))


@needs_bash
def test_guard_exits_zero_when_the_rebuild_crashes(tmp_path):
    """The headline failure: build.py raises, the step dies, the commit is
    skipped, ~88 minutes of scraped prices are discarded."""
    repo = _repo(tmp_path)
    code, github_env, proc = _guard(
        repo, tmp_path, "echo 'Traceback: boom' >&2; exit 1")
    assert code == 0, f"a crashing rebuild gated the publish: {proc.stderr}"
    assert "REBUILD_CHECK_FAILED=1" in github_env, (
        "a check that could not run must still alarm")


@needs_bash
def test_guard_exits_zero_when_git_itself_fails(tmp_path):
    """`git add -A site/` exiting non-zero was the other half of F1. Simulated
    by running the body outside a git repository, which is the real shape of
    the failure: every git invocation returns 128."""
    notrepo = tmp_path / "notrepo"
    (notrepo / "site").mkdir(parents=True)
    code, github_env, proc = _guard(notrepo, tmp_path, REBUILD_REPRODUCES)
    assert code == 0, f"a failing git gated the publish: {proc.stderr}"
    assert "REBUILD_CHECK_FAILED=1" in github_env


@needs_bash
def test_a_crashed_rebuild_does_not_publish_a_half_written_site(tmp_path):
    """Swallowing the exit code is not enough on its own. A rebuild that dies
    part-way leaves site/ half-written, and the commit step would publish
    that. The index holds the first build — the one 'Build site' produced and
    'Verify internal links' passed — so the worktree is restored from it."""
    repo = _repo(tmp_path)
    code, github_env, _ = _guard(repo, tmp_path, """\
        printf 'CORRUPT\\n' > site/index.html
        printf 'half\\n' > site/plants/__partial.html
        exit 1
    """)
    assert code == 0
    assert "REBUILD_CHECK_FAILED=1" in github_env
    assert (repo / "site" / "index.html").read_text(encoding="utf-8") == "home v1\n", (
        "the half-written rebuild was left in place and would have published")
    assert not (repo / "site" / "plants" / "__partial.html").exists(), (
        "a file the failed rebuild created was left in place and would have "
        "published")


def test_the_guard_body_ends_in_an_unconditional_exit_zero():
    """Belt, to continue-on-error's braces. Every branch already ends on a
    command that exits 0 in the normal case, so this only bites when that
    LAST command fails — which is exactly the class of failure that took the
    cycle down in the first place."""
    body = [ln for ln in _step(GUARD_STEP)["run"].rstrip().splitlines() if ln.strip()]
    assert body[-1].strip() == "exit 0", (
        f"the guard body ends on {body[-1]!r}; a failure there propagates")


@needs_bash
def test_guard_exits_zero_when_the_last_command_in_the_diverged_branch_fails(tmp_path):
    """The behavioural half of the test above. `git diff --name-only` between
    two tree objects is the last thing the diverged branch runs; break it and
    the step must still come back 0 and still have recorded the alarm."""
    repo = _repo(tmp_path)
    _breaking_git(tmp_path, "diff --name-only")
    code, github_env, proc = _guard(
        repo, tmp_path, "printf 'x\\n' > site/plants/__probe.html; exit 0")
    assert "simulated failure" in proc.stderr, "the git shim did not fire"
    assert code == 0, f"a failing `git diff` gated the publish: {proc.stderr}"
    assert "REBUILD_DIVERGED=1" in github_env


@needs_bash
def test_the_harness_can_actually_fail(tmp_path):
    """R2: the four tests above prove nothing unless this same harness, same
    shell, reports non-zero for a body that does NOT swallow the code."""
    repo = _repo(tmp_path)
    code, _env, _proc = _run(
        repo, tmp_path, "python -X utf8 build.py\n", "exit 1")
    assert code != 0


# --------------------------------------------------------------------------
# F1b — the guard must see additions, not only modifications
# --------------------------------------------------------------------------

@needs_bash
def test_guard_sees_a_page_the_rebuild_ADDS(tmp_path):
    """The defect: a new plant/category/guide page appears on the second
    build and `git diff` does not report untracked paths."""
    repo = _repo(tmp_path)
    code, github_env, proc = _guard(
        repo, tmp_path, "printf 'x\\n' > site/plants/__probe.html; exit 0")
    assert code == 0
    assert "REBUILD_DIVERGED=1" in github_env, (
        "the guard is blind to a page the rebuild ADDS")
    assert "site/plants/__probe.html" in proc.stdout


@needs_bash
def test_guard_sees_a_page_the_rebuild_DELETES(tmp_path):
    repo = _repo(tmp_path)
    code, github_env, proc = _guard(
        repo, tmp_path, "rm site/plants/rose.html; exit 0")
    assert code == 0
    assert "REBUILD_DIVERGED=1" in github_env
    assert "site/plants/rose.html" in proc.stdout


@needs_bash
def test_guard_sees_a_page_the_rebuild_MODIFIES(tmp_path):
    """The one case the pre-fix form did catch. It must keep working."""
    repo = _repo(tmp_path)
    code, github_env, proc = _guard(
        repo, tmp_path, "printf 'home v2\\n' > site/index.html; exit 0")
    assert code == 0
    assert "REBUILD_DIVERGED=1" in github_env
    assert "site/index.html" in proc.stdout


@needs_bash
def test_guard_stays_quiet_when_the_rebuild_reproduces(tmp_path):
    """The inverse direction. An alarm that always fires is not a signal —
    and this is the state every healthy cycle is in, so a false positive here
    would cost a red build twice a day, every day."""
    repo = _repo(tmp_path)
    code, github_env, proc = _guard(repo, tmp_path, REBUILD_REPRODUCES)
    assert code == 0
    assert "REBUILD_DIVERGED" not in github_env
    assert "REBUILD_CHECK_FAILED" not in github_env
    assert "no-op" in proc.stdout


@needs_bash
def test_guard_stays_quiet_when_only_untouched_files_moved_since_HEAD(tmp_path):
    """site/ is a committed build artifact and differs from HEAD on every
    cycle that moved a price. The guard must compare first-build against
    rebuild, not against HEAD, or it would fire on every normal run."""
    repo = _repo(tmp_path)
    (repo / "site" / "index.html").write_text("home v2 (this cycle)\n", encoding="utf-8")
    (repo / "site" / "plants" / "tulip.html").write_text("new plant\n", encoding="utf-8")
    code, github_env, _ = _guard(repo, tmp_path, REBUILD_REPRODUCES)
    assert code == 0
    assert "REBUILD_DIVERGED" not in github_env


@needs_bash
def test_the_old_form_was_blind_to_an_added_page(tmp_path):
    """The control for F1b. Same repo, same rebuild, the a1272f3e body: it
    reports a clean no-op. If this ever starts detecting the addition, the
    two tests above are not measuring what they claim to."""
    repo = _repo(tmp_path)
    code, github_env, proc = _run(
        repo, tmp_path, OLD_GUARD_BODY,
        "printf 'x\\n' > site/plants/__probe.html; exit 0")
    assert code == 0
    assert "REBUILD_DIVERGED" not in github_env
    assert "no-op" in proc.stdout


# --------------------------------------------------------------------------
# the alarm side
# --------------------------------------------------------------------------

def test_raise_alarms_reports_a_check_that_could_not_run():
    """A check that could not run is not a check that passed. Both flags the
    guard can raise must reach the single alarm point."""
    body = _step(ALARM_STEP)["run"]
    assert "REBUILD_DIVERGED" in body
    assert "REBUILD_CHECK_FAILED" in body


@needs_bash
def test_raise_alarms_turns_the_check_failed_flag_red(tmp_path):
    """The flag has to do something. Run the alarm body with it set and
    confirm the step goes non-zero — alarming is its whole job."""
    body = _step(ALARM_STEP)["run"]
    # The alarm body interpolates ${{ steps.* }} expressions Actions expands
    # before the shell ever sees them; substitute the values a healthy publish
    # would produce, so only the flag under test is in play.
    for step_id in ("nature_hills", "planting_tree", "spring_hill",
                    "fast_growing_trees", "proven_winners",
                    "great_garden_plants", "stark_bros"):
        body = body.replace("${{ steps.%s.outcome }}" % step_id, "success")
    body = body.replace("${{ steps.commit.outcome }}", "success")
    assert "${{" not in body, "an unexpanded Actions expression is left in the body"

    repo = _repo(tmp_path)
    clean_code, _env, _p = _run(repo, tmp_path, body, REBUILD_REPRODUCES)
    assert clean_code == 0, "the alarm step must be green when nothing alarmed"

    code, _env, proc = _run(
        repo, tmp_path, "REBUILD_CHECK_FAILED=1\n" + body, REBUILD_REPRODUCES)
    assert code != 0, "REBUILD_CHECK_FAILED did not turn the run red"
    assert "reproducibility check itself failed to run" in proc.stdout
