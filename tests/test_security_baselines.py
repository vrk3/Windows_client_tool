"""The shipped baselines, checked against the catalog they target."""
import json
import os

import pytest

from modules.security_dashboard.catalog import load_catalog
from modules.security_dashboard.catalog.model import (
    Category, SecurityControl)
from modules.security_dashboard.profile import (
    available_baselines, load_baseline, plan_baseline)


@pytest.fixture(scope="module")
def real_catalog():
    return load_catalog()


def _control(cid, value, **over):
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": value},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_the_three_baselines_ship(real_catalog):
    assert set(available_baselines()) == {"recommended", "hardened",
                                          "developer"}


def test_every_baseline_names_only_controls_that_exist(real_catalog):
    """A target naming nothing changes nothing, silently."""
    for name in available_baselines():
        unknown = [cid for cid in load_baseline(name)
                   if cid not in real_catalog]
        assert not unknown, f"{name} names {unknown}"


def test_every_baseline_target_is_writable(real_catalog):
    """A read-only control in a baseline is a promise it cannot keep."""
    for name in available_baselines():
        unwritable = [cid for cid in load_baseline(name)
                      if not real_catalog[cid].writable]
        assert not unwritable, f"{name} targets read-only {unwritable}"


def test_no_baseline_asks_for_a_value_of_none(real_catalog):
    """`steps_for(None)` raises: a target of None has no steps to apply."""
    for name in available_baselines():
        assert not [cid for cid, value in load_baseline(name).items()
                    if value is None]


def test_recommended_is_exactly_what_the_catalog_recommends(real_catalog):
    """Generated from `desired`, so the two cannot drift apart."""
    expected = {cid: c.desired for cid, c in real_catalog.items()
                if c.desired is not None and c.writable}
    assert load_baseline("recommended") == expected


def test_hardened_is_at_least_as_strict_as_recommended(real_catalog):
    """It may differ in value, but it may not simply drop a control."""
    recommended = load_baseline("recommended")
    hardened = load_baseline("hardened")
    assert set(recommended) <= set(hardened)


def test_developer_omits_rather_than_disables(real_catalog):
    """Leaving a control out means the baseline does not touch it. Shipping a
    baseline that turns Memory Integrity OFF is a different thing entirely,
    and not one this app should do behind a preset name."""
    recommended = load_baseline("recommended")
    developer = load_baseline("developer")
    assert set(developer) < set(recommended)
    for control_id, value in developer.items():
        assert value == recommended[control_id], control_id


def test_a_baseline_reports_what_it_will_skip_and_why():
    catalog = {c.id: c for c in (_control("a", True), _control("b", False))}
    plan = plan_baseline("recommended", catalog)
    assert all(entry["reason"] for entry in plan["skipped"])


def test_a_control_already_at_the_baseline_is_skipped_with_that_reason(
        monkeypatch):
    catalog = {"a": _control("a", True)}
    monkeypatch.setattr(
        "modules.security_dashboard.profile.load_baseline",
        lambda name: {"a": True})
    plan = plan_baseline("recommended", catalog)
    assert len(plan["staged"]) == 0
    assert plan["skipped"][0]["reason"] == "already at the baseline value"


def test_a_read_only_control_is_skipped_with_its_own_reason(monkeypatch):
    catalog = {"a": _control("a", True, on_steps=(), off_steps=(),
                             read_only_reason="TPM presence is hardware")}
    monkeypatch.setattr(
        "modules.security_dashboard.profile.load_baseline",
        lambda name: {"a": False})
    plan = plan_baseline("recommended", catalog)
    assert "hardware" in plan["skipped"][0]["reason"]


def test_a_control_that_could_not_be_read_is_staged_but_called_out(monkeypatch):
    """Applying it is defensible -- the target says what it should be and the
    apply path verifies afterwards. Not saying so is not."""
    catalog = {"a": _control("a", None,
                             reader=lambda: {"available": False})}
    monkeypatch.setattr(
        "modules.security_dashboard.profile.load_baseline",
        lambda name: {"a": True})
    plan = plan_baseline("recommended", catalog)
    assert len(plan["staged"]) == 1
    entry = plan["skipped"][0]
    assert entry["staged"] is True
    assert "could not be read" in entry["reason"]


def test_planning_a_baseline_uses_readings_it_is_given(monkeypatch):
    catalog = {"a": _control("a", True)}
    object.__setattr__(catalog["a"], "reader",
                       lambda: pytest.fail("the machine was read again"))
    monkeypatch.setattr(
        "modules.security_dashboard.profile.load_baseline",
        lambda name: {"a": True})
    plan = plan_baseline("recommended", catalog, readings={"a": True})
    assert len(plan["staged"]) == 0


def test_every_baseline_file_carries_a_description():
    """The difference between these three is the whole point of having three."""
    from modules.security_dashboard.profile import _BASELINE_DIR
    for name in available_baselines():
        with open(os.path.join(_BASELINE_DIR, f"{name}.json"),
                  encoding="utf-8") as handle:
            data = json.load(handle)
        assert data.get("description", "").strip()


def test_the_baselines_are_bundled_into_the_frozen_build():
    """They are JSON beside the catalog, not code, so PyInstaller does not
    find them by following imports. Without a datas entry the exe RUNS and the
    Baselines menu says "No baselines are installed".

    Caught by reading get_datas() before deploying a build -- a raw string
    search over the exe proves nothing either way, because data files sit in
    the PKG archive zlib-compressed. CArchiveReader(exe).toc is what shows
    them.
    """
    import os as _os

    import pyinstaller_common

    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    destinations = [dst for _src, dst in pyinstaller_common.get_datas(root)]
    assert "modules/security_dashboard/catalog/baselines" in destinations
