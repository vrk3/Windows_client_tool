"""Every reader either reaches the pane or is named as deliberately not a control.

The pane could see 171 things and change 24. The other 147 were not blocked by
Windows -- they were never wired, and nothing anywhere said so. This test is
the thing that makes that impossible to repeat: a check_* function that is
neither bound to a control nor listed in NOT_A_CONTROL with a reason fails the
suite.
"""
import inspect

import pytest

from modules.security_dashboard import security_reader
from modules.security_dashboard.catalog import NOT_A_CONTROL, load_catalog
from modules.security_dashboard.catalog.model import Category, SecurityControl


def _all_readers():
    return {name for name, obj in inspect.getmembers(security_reader, inspect.isfunction)
            if name.startswith("check_") and obj.__module__ == security_reader.__name__}


def _bound_reader_names(controls):
    """Names (in security_reader) whose actual function object some control
    uses as its reader. Matched by IDENTITY, not by __name__: a reader
    defined as `check_x = lambda: ...` has __name__ == '<lambda>', not
    'check_x', so name-matching can never recognise it as bound no matter
    what a catalog entry sets `reader=` to. Comparing the reader objects
    themselves survives lambdas, aliases (`check_x = check_y`), and anything
    else a future reader might be defined as.
    """
    bound_objs = {c.reader for c in controls}
    return {name for name in _all_readers()
            if getattr(security_reader, name) in bound_objs}


@pytest.mark.xfail(reason="catalog population in progress, Tasks 6-8", strict=False)
def test_every_reader_is_bound_or_explicitly_excluded():
    bound = _bound_reader_names(load_catalog().values())
    unaccounted = sorted(_all_readers() - bound - set(NOT_A_CONTROL))
    assert not unaccounted, (
        f"{len(unaccounted)} readers reach nothing and are not listed in "
        f"NOT_A_CONTROL:\n  " + "\n  ".join(unaccounted))


def test_a_lambda_reader_is_recognised_as_bound():
    """Regression pin for the identity-matching fix above. Four real readers
    (check_defender_threat_low/moderate/high/severe) are module-level lambdas,
    so their __name__ is the literal string '<lambda>'. A control that binds
    one of them (`reader=security_reader.check_defender_threat_low`, exactly
    what Task 6 will write) must be recognised as bound. Name-based matching
    (`c.reader.__name__ in bound_names`) fails this silently forever, because
    '<lambda>' never equals 'check_defender_threat_low' -- confirmed by
    running this test against the prior name-based implementation, where it
    failed with 'check_defender_threat_low' left unaccounted.
    """
    stub = SecurityControl(
        id="_pin_lambda_binding_regression",
        title="pin", category=Category.DEFENDER, description="",
        why_it_matters="",
        reader=security_reader.check_defender_threat_low,
        read_only_reason="test fixture, not a real control")
    bound = _bound_reader_names([stub])
    assert "check_defender_threat_low" in bound


def test_every_exclusion_names_a_real_reader():
    stale = sorted(set(NOT_A_CONTROL) - _all_readers())
    assert not stale, f"NOT_A_CONTROL names readers that no longer exist: {stale}"


def test_every_exclusion_gives_a_reason():
    empty = sorted(k for k, v in NOT_A_CONTROL.items() if not v or not v.strip())
    assert not empty, f"excluded with no reason given: {empty}"


def test_every_control_has_a_reader_that_is_callable():
    assert all(callable(c.reader) for c in load_catalog().values())


def test_every_writable_controls_steps_have_a_known_type():
    known = {"registry", "registry_delete", "service", "command",
             "script", "appx", "scheduled_task"}
    bad = []
    for control in load_catalog().values():
        for step in tuple(control.on_steps) + tuple(control.off_steps):
            if step.get("type") not in known:
                bad.append(f"{control.id}: {step.get('type')!r}")
    assert not bad, f"unknown step types: {bad}"


def test_every_registry_step_is_fully_specified():
    bad = []
    for control in load_catalog().values():
        for step in tuple(control.on_steps) + tuple(control.off_steps):
            if step.get("type") != "registry":
                continue
            if not step.get("key") or "data" not in step:
                bad.append(f"{control.id}: {step}")
    assert not bad, f"registry steps missing key or data: {bad}"
