"""The heartbeat's alert window must mean one thing in every place it appears.

The window is stated in four places: the MAX_AGE_HOURS env var that decides,
the alert email body, the ::error:: annotation, and the healthy message. Only
the first one is executable; the other three are prose that a reader believes.
This repo's two worst defects were false sentences rather than wrong code, so
the sentences are pinned to the value that actually decides.

The calibration itself (median 12.70h, p95 15.87h, max 34.51h over 204 gaps
between commits touching data/prices/ since 2026-05-01) is documented in the
workflow. It is deliberately NOT asserted here: it is a statement about git
history that changes with every new commit, and a test that must be updated
on every scrape is a test that gets deleted. What IS asserted is the thing
the calibration was measured on — that the step still measures data/prices/
and not all commits, which is exactly where the previous calibration went
wrong.
"""

import os
import re

import yaml

WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".github", "workflows", "heartbeat.yml")


def _doc():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _steps():
    (job,) = _doc()["jobs"].values()
    return job["steps"]


def _step(name):
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW}")


def _window():
    return str(_step("Measure pipeline freshness")["env"]["MAX_AGE_HOURS"])


def test_the_window_is_the_calibrated_value():
    assert _window() == "30"


def test_every_stated_window_matches_the_one_that_decides():
    """Change MAX_AGE_HOURS alone and this fails: the email would promise a
    window the check does not use."""
    window = _window()
    alert = _step("Compose alert")["run"]
    assert f"Alert window                      : {window} hours" in alert
    assert f"Crossing\n          {window} hours" in alert or f"{window} hours means" in alert
    assert f"(window {window}h)" in _step("Raise the alarm")["run"]
    assert f"window {window}h" in _step("Report healthy")["run"]


def test_no_other_hour_figure_is_presented_as_the_window():
    """The failure mode this catches: widening the window and leaving '30
    hours' in the alert text, so the alert explains a rule that is no longer
    in force."""
    window = _window()
    for step in ("Compose alert", "Raise the alarm", "Report healthy"):
        body = _step(step)["run"]
        for found in re.findall(r"window[^0-9]{0,12}(\d+)\s*h", body, re.I):
            assert found == window, f"{step} states a window of {found}h, not {window}h"


def test_freshness_is_measured_on_data_commits_not_all_commits():
    """The previous calibration was measured on gaps between ALL commits while
    the step measures commits touching data/prices/ — a sparser series with a
    34.51h maximum instead of 23.88h. Pin the metric the numbers describe."""
    run = _step("Measure pipeline freshness")["run"]
    assert "git log -1 --format=%cI -- data/prices/" in run
    assert 'if [ "$AGE_H" -ge "$MAX_AGE_HOURS" ]' in run


def test_the_calibration_block_states_the_metric_it_was_measured_on():
    """R3: the claim that made this wrong was untethered from its metric."""
    text = open(WORKFLOW, encoding="utf-8").read()
    assert "-- data/prices/" in text.split("WINDOW CALIBRATION")[1].split("- name:")[0]
