"""Profiles and baselines: a set of target values, and what it would change.

A profile is this machine's answers, exported. A baseline is a set of targets
shipped with the app. They are the same shape and go through the same
`diff_against`, so importing either stages a diff rather than applying a list.

Two rules, both of which exist because of something already found here:

* **A control that could not be read is not exported.** `read()` answers None
  for "we could not look", and None written into a profile comes back as an
  instruction on import -- "set it to nothing" -- which `ChangeSet.add`
  correctly refuses, one machine too late. Refusals are recorded separately
  so the export can still say what it could not see.

* **A baseline says what it will NOT do, and why.** Compliant already, no
  writer at all, could not be read, needs a restart: four different reasons a
  control is not in the staged set, and a plan that reports only a count
  cannot tell you which.
"""
import json
import logging
import os
import platform
from typing import Any, Dict, List, Optional

from .staging import ChangeSet, diff_against

logger = logging.getLogger(__name__)

PROFILE_VERSION = 1

#: Baselines ship beside the catalog.
_BASELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "catalog", "baselines")


def _app_version() -> str:
    try:
        from app import APP_VERSION
        return str(APP_VERSION)
    except Exception:
        return "unknown"


def export_profile(catalog: Dict[str, Any],
                   readings: Optional[Dict[str, Any]] = None) -> dict:
    """This machine's current values, as a portable target set.

    `readings` is what the caller already has -- the pane holds a value for
    every card it has drawn. Without it every control is read, which is 12.7s
    here.
    """
    known = readings if readings is not None else {}
    controls: Dict[str, Any] = {}
    unreadable: List[str] = []
    for control_id, control in catalog.items():
        value = known[control_id] if control_id in known else control.read()
        if value is None:
            # Never exported: on import this would read as "set it to
            # nothing", which has no steps and no meaning.
            unreadable.append(control_id)
            continue
        if not control.writable:
            continue
        controls[control_id] = value
    return {
        "version": PROFILE_VERSION,
        "os_build": platform.version(),
        "app_version": _app_version(),
        "controls": controls,
        "unreadable": sorted(unreadable),
    }


def import_profile(data: dict, catalog: Dict[str, Any],
                   readings: Optional[Dict[str, Any]] = None) -> ChangeSet:
    """Stage everything in `data` that differs from this machine.

    Controls this build does not have are ignored rather than an error: a
    profile from a newer build names controls this one has not got.
    """
    return diff_against(catalog, data.get("controls", {}), readings=readings)


def write_profile(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def read_profile(path: str) -> Optional[dict]:
    """A profile from disk, or None if it is not one.

    None rather than an exception: this is a file a person picked, and half a
    JSON file is a thing that happens.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("not a usable profile at %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("controls"), dict):
        logger.warning("%s is JSON but not a profile", path)
        return None
    return data


def available_baselines() -> List[str]:
    try:
        return sorted(name[:-5] for name in os.listdir(_BASELINE_DIR)
                      if name.endswith(".json"))
    except OSError:
        return []


def load_baseline(name: str) -> Dict[str, Any]:
    """The target values a named baseline asks for."""
    path = os.path.join(_BASELINE_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("controls", {})


def plan_baseline(name: str, catalog: Dict[str, Any],
                  readings: Optional[Dict[str, Any]] = None) -> dict:
    """What applying a baseline would stage, and what it would skip.

    Every skipped control carries a reason. "48 of 149 applied" with no
    account of the other 101 is the report that sends someone looking for a
    setting the tool silently declined to touch.
    """
    targets = load_baseline(name)
    known = readings if readings is not None else {}
    staged = ChangeSet()
    skipped: List[Dict[str, str]] = []

    for control_id, desired in targets.items():
        control = catalog.get(control_id)
        if control is None:
            skipped.append({"id": control_id,
                            "reason": "this build has no such control"})
            continue
        if desired is None:
            skipped.append({"id": control_id,
                            "reason": "the baseline records no value for it"})
            continue
        if not control.writable:
            skipped.append({
                "id": control_id,
                "reason": control.read_only_reason or "it cannot be written"})
            continue
        current = known[control_id] if control_id in known else control.read()
        if current is None:
            # Staged anyway -- the target says what it should be and the apply
            # path verifies afterwards -- but called out, because it is a
            # different thing from "this differs from what you want".
            staged.add(control, desired, from_value=None)
            skipped.append({
                "id": control_id,
                "reason": "its current value could not be read, so it is "
                          "staged without knowing what it was",
                "staged": True})
            continue
        if current == desired:
            skipped.append({"id": control_id,
                            "reason": "already at the baseline value"})
            continue
        staged.add(control, desired, from_value=current)
        if control.requires_reboot:
            skipped.append({
                "id": control_id,
                "reason": "staged, but only takes effect after a restart",
                "staged": True})

    return {"name": name, "staged": staged, "skipped": skipped}
