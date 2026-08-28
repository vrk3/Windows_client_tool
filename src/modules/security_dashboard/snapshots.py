"""One cmdlet call feeding many readers, with refusals kept separate from
empty answers.

Measured at branch point: _ps() costs 0.54s a call, and the readers made 19
separate Get-MpPreference calls, 7 Get-MpComputerStatus, 6 Get-Service and 4
Get-WindowsOptionalFeature -- about 36 PowerShell launches, ~19s, to read
fields that four calls return in full.

Refusal, not emptiness: a Windows admin cmdlet exits 0 while refusing (Get-Tpm
answers TpmPresent: null; dism exits 740 with its complaint on stdout). Each
snapshot therefore records WHY it is empty, and callers must ask.
"""
import json
import logging
import threading
from typing import Any, Dict, Optional

from .security_reader import _ps

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_reasons: Dict[str, Optional[str]] = {}

#: Phrases a Windows cmdlet uses to refuse while still exiting 0.
_REFUSAL_MARKERS = (
    "access is denied", "elevated permissions are required",
    "requires elevation", "not recognized", "no rules match",
    "unauthorizedaccess", "requested registry access is not allowed",
)


def _looks_refused(rc: int, out: str, err: str) -> Optional[str]:
    """Return a reason string if this was a refusal, else None.

    rc is one signal among several and NOT the deciding one.
    """
    blob = f"{out}\n{err}".strip()
    low = blob.lower()
    if any(marker in low for marker in _REFUSAL_MARKERS):
        return blob.splitlines()[0] if blob else "refused"
    if rc != 0:
        return blob.splitlines()[0] if blob else f"exit code {rc}"
    if not out.strip():
        return "empty response"
    return None


def _fetch_json(name: str, command: str, timeout: int = 30) -> Any:
    rc, out, err = _ps(command, timeout=timeout)
    reason = _looks_refused(rc, out, err)
    if reason:
        logger.warning("snapshot %s unavailable: %s", name, reason)
        _reasons[name] = reason
        return None
    try:
        _reasons[name] = None
        return json.loads(out)
    except (ValueError, TypeError) as exc:
        _reasons[name] = f"unparseable response: {exc}"
        return None


def _cached(name: str, command: str, empty, transform=None, timeout: int = 30):
    with _lock:
        if name in _cache:
            return _cache[name]
        data = _fetch_json(name, command, timeout=timeout)
        value = empty if data is None else (transform(data) if transform else data)
        _cache[name] = value
        return value


def mp_preference() -> Dict[str, Any]:
    """Every Get-MpPreference field, in one call instead of nineteen."""
    return _cached("mp_preference",
                   "Get-MpPreference | ConvertTo-Json -Compress -Depth 3", {})


def mp_computer_status() -> Dict[str, Any]:
    return _cached("mp_computer_status",
                   "Get-MpComputerStatus | ConvertTo-Json -Compress -Depth 3", {})


def service_states() -> Dict[str, Dict[str, Any]]:
    """name (lowercased) -> {'status': ..., 'start_type': ...} for every service."""
    def _index(rows):
        rows = rows if isinstance(rows, list) else [rows]
        return {str(r.get("Name", "")).lower():
                {"status": r.get("Status"), "start_type": r.get("StartType")}
                for r in rows}

    return _cached(
        "service_states",
        "Get-Service | Select-Object Name,Status,StartType | ConvertTo-Json -Compress",
        {}, transform=_index, timeout=60)


def optional_features() -> Dict[str, str]:
    """feature name (lowercased) -> state string."""
    def _index(rows):
        rows = rows if isinstance(rows, list) else [rows]
        return {str(r.get("FeatureName", "")).lower(): str(r.get("State"))
                for r in rows}

    return _cached(
        "optional_features",
        "Get-WindowsOptionalFeature -Online | "
        "Select-Object FeatureName,State | ConvertTo-Json -Compress",
        {}, transform=_index, timeout=120)


#: snapshot name -> the getter that fetches (and caches) it. Used only by
#: `unavailable()` to force a first fetch; callers should keep calling the
#: named functions directly for the data itself.
_FETCHERS = {
    "mp_preference": mp_preference,
    "mp_computer_status": mp_computer_status,
    "service_states": service_states,
    "optional_features": optional_features,
}


def unavailable(name: str) -> Optional[str]:
    """Why this snapshot could not be read, or None if it was read fine.

    Ask THIS, never `if not snapshot_dict:`. An empty snapshot and a refused
    one are different facts, and a snapshot that legitimately returns few or
    no fields is a successful read.

    A snapshot that has never been fetched is neither of those -- it is an
    open question, not an answer -- so this triggers the fetch first. A
    caller must not be able to read silence as "fine"; the alternative
    (returning None for "never tried") would make a snapshot look available
    before anyone ever asked Windows. Every real call site already holds the
    snapshot dict from calling the matching getter first, so this never
    causes I/O the caller wasn't already about to pay for anyway.
    """
    if name not in _reasons:
        fetcher = _FETCHERS.get(name)
        if fetcher is None:
            return f"unknown snapshot: {name}"
        fetcher()
    return _reasons.get(name)


def availability() -> Dict[str, Optional[str]]:
    """snapshot name -> refusal reason, or None if it was read successfully.

    A caller that finds an empty snapshot MUST consult `unavailable(name)`
    (not this) before reporting a setting as absent -- this dict only shows
    what has already been fetched, so a snapshot no one has asked for yet is
    silently missing from it. An empty dict here means "we could not look",
    not "there was nothing there".
    """
    return dict(_reasons)


def invalidate() -> None:
    """Drop every snapshot. Called by the pane's Refresh, never on a timer."""
    with _lock:
        _cache.clear()
        _reasons.clear()
