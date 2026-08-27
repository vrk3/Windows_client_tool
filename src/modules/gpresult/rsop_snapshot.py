"""Save a Group Policy report, and say what changed since the last one.

The question this answers is "what changed on this machine since last time?",
which `gpresult` itself cannot answer -- it only ever shows *now*. So a
snapshot is an `RsopResult` frozen to JSON, and a diff is two of them compared.

Four decisions here are load-bearing, each written down because getting them
wrong produces a diff that lies:

* **"We could not look" is not "nothing was there".** `rsop_parser` already
  keeps `available` apart from "empty", and the diff has to keep that apart
  too. Running this tool unelevated and then elevated makes several hundred
  computer settings appear at once; reporting those as *added* would say the
  machine changed when only our view of it did. A scope whose availability
  flipped is reported as a visibility change and its contents are NOT walked.

* **The same setting name legitimately appears more than once.** Five
  `AllowWindows` values live under different SrpV2 keys on this machine, which
  is why `rsop_parser` composes registry names from key *and* value -- but
  collisions still happen across extensions. Settings key on
  ``(category, name)`` and duplicates are matched within their group by
  content first, so a reordering is not reported as five changes and no
  duplicate is silently dropped.

* **Listing must not deserialise every snapshot.** An elevated report is
  megabytes of JSON; a pane that lists twenty of them would parse tens of
  megabytes to fill a combo box. Each snapshot therefore writes a small
  ``.meta.json`` sidecar, and listing reads only those. A snapshot whose
  sidecar is missing (hand-copied, or written by an older build) still lists,
  by falling back to the payload for that one file.

* **A snapshot written by another version must still load.** Missing fields
  take the dataclass default; unknown fields are ignored, not fatal. Both
  directions are pinned by tests, because the failure mode is a user losing
  their history on upgrade.

No Qt here -- this is pure logic so it can be tested headless, and the
directory is a parameter (defaulting to the same `%APPDATA%/WindowsTweaker`
`app.py` computes) rather than an import of the app singleton.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.gpresult.rsop_parser import (
    ExtensionStatus, GpoInfo, PolicySetting, RsopResult, RsopScope,
)

logger = logging.getLogger(__name__)

#: Bumped when the on-disk shape changes in a way readers must know about.
#: Readers never *require* a match -- see the module docstring.
SCHEMA_VERSION = 1

#: Subdirectory of the app data dir that holds snapshots.
SNAPSHOT_DIRNAME = "gpresult_snapshots"

_PAYLOAD_SUFFIX = ".rsop.json"
_META_SUFFIX = ".meta.json"

#: Availability-change kinds. Empty string means the scope's visibility was
#: the same in both snapshots and its contents are therefore comparable.
VISIBILITY_UNCHANGED = ""
VISIBILITY_GAINED = "became_visible"
VISIBILITY_LOST = "became_hidden"


# ------------------------------------------------------------------
# Where snapshots live
# ------------------------------------------------------------------

def default_snapshot_dir() -> str:
    """`%APPDATA%/WindowsTweaker/gpresult_snapshots`.

    Computed the same way `app.py:_get_app_data_dir` does rather than imported
    from it: importing `app` builds a singleton and drags in Qt, which would
    make this module untestable headless. Nothing is created here -- only
    `save_snapshot` has the right to make directories.
    """
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(base, "WindowsTweaker", SNAPSHOT_DIRNAME)


# ------------------------------------------------------------------
# Coercion helpers -- every one of these exists for compatibility
# ------------------------------------------------------------------

def _as_str(raw: Any, default: str = "") -> str:
    """Anything -> str, because a foreign writer may have used a number."""
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (int, float)):
        return str(raw)
    return default


def _as_bool(raw: Any, default: bool) -> bool:
    """Anything -> bool, tolerating the string forms XML/JSON round-trips make."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return default


def _as_int(raw: Any, default: int = 0) -> int:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return default
    return default


def _as_list(raw: Any) -> List[Any]:
    """A missing or wrong-typed list becomes empty rather than raising."""
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    logger.debug("Snapshot field expected a list, got %s; treating as empty",
                 type(raw).__name__)
    return []


def _as_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is not None:
        logger.debug("Snapshot field expected an object, got %s; treating as "
                     "empty", type(raw).__name__)
    return {}


def _as_pairs(raw: Any) -> List[Tuple[str, str]]:
    """JSON has no tuples, so `[k, v]` lists come back as `(k, v)`.

    Restoring the tuple matters for more than tidiness: dataclass equality
    compares element by element, and `("a", "b") != ["a", "b"]`, so a
    round-trip that left lists here would never compare equal to the original.
    """
    pairs: List[Tuple[str, str]] = []
    for item in _as_list(raw):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((_as_str(item[0]), _as_str(item[1])))
        else:
            logger.debug("Skipping malformed pair in snapshot: %r", item)
    return pairs


# ------------------------------------------------------------------
# Serialisation
# ------------------------------------------------------------------

def _gpo_to_dict(gpo: GpoInfo) -> Dict[str, Any]:
    # `applied` / `denied_reason` are properties derived from these fields, so
    # writing them would be storing a value that can disagree with its inputs.
    return {
        "name": gpo.name,
        "guid": gpo.guid,
        "enabled": gpo.enabled,
        "is_valid": gpo.is_valid,
        "filter_allowed": gpo.filter_allowed,
        "access_denied": gpo.access_denied,
        "som_path": gpo.som_path,
        "applied_order": gpo.applied_order,
        "link_order": gpo.link_order,
        "no_override": gpo.no_override,
        "version_directory": gpo.version_directory,
        "version_sysvol": gpo.version_sysvol,
    }


def _gpo_from_dict(raw: Any) -> GpoInfo:
    data = _as_dict(raw)
    fallback = GpoInfo()
    return GpoInfo(
        name=_as_str(data.get("name"), fallback.name),
        guid=_as_str(data.get("guid"), fallback.guid),
        enabled=_as_bool(data.get("enabled"), fallback.enabled),
        is_valid=_as_bool(data.get("is_valid"), fallback.is_valid),
        filter_allowed=_as_bool(data.get("filter_allowed"),
                                fallback.filter_allowed),
        access_denied=_as_bool(data.get("access_denied"),
                               fallback.access_denied),
        som_path=_as_str(data.get("som_path"), fallback.som_path),
        applied_order=_as_str(data.get("applied_order"), fallback.applied_order),
        link_order=_as_str(data.get("link_order"), fallback.link_order),
        no_override=_as_bool(data.get("no_override"), fallback.no_override),
        version_directory=_as_str(data.get("version_directory"),
                                  fallback.version_directory),
        version_sysvol=_as_str(data.get("version_sysvol"),
                               fallback.version_sysvol),
    )


def _extension_to_dict(ext: ExtensionStatus) -> Dict[str, Any]:
    return {
        "name": ext.name,
        "identifier": ext.identifier,
        "begin_time": ext.begin_time,
        "end_time": ext.end_time,
        "logging_status": ext.logging_status,
        "error": ext.error,
    }


def _extension_from_dict(raw: Any) -> ExtensionStatus:
    data = _as_dict(raw)
    return ExtensionStatus(
        name=_as_str(data.get("name")),
        identifier=_as_str(data.get("identifier")),
        begin_time=_as_str(data.get("begin_time")),
        end_time=_as_str(data.get("end_time")),
        logging_status=_as_str(data.get("logging_status")),
        error=_as_str(data.get("error")),
    )


def _setting_to_dict(setting: PolicySetting) -> Dict[str, Any]:
    return {
        "category": setting.category,
        "name": setting.name,
        "value": setting.value,
        "gpo": setting.gpo,
        "details": [[key, value] for key, value in setting.details],
    }


def _setting_from_dict(raw: Any) -> PolicySetting:
    data = _as_dict(raw)
    return PolicySetting(
        category=_as_str(data.get("category")),
        name=_as_str(data.get("name")),
        value=_as_str(data.get("value")),
        gpo=_as_str(data.get("gpo")),
        details=_as_pairs(data.get("details")),
    )


def _scope_to_dict(scope: RsopScope) -> Dict[str, Any]:
    return {
        "scope": scope.scope,
        "available": scope.available,
        "unavailable_reason": scope.unavailable_reason,
        "name": scope.name,
        "domain": scope.domain,
        "som": scope.som,
        "site": scope.site,
        "slow_link": scope.slow_link,
        "version": scope.version,
        "gpos": [_gpo_to_dict(g) for g in scope.gpos],
        "security_groups": [[sid, name] for sid, name in scope.security_groups],
        "extensions": [_extension_to_dict(e) for e in scope.extensions],
        "settings": [_setting_to_dict(s) for s in scope.settings],
    }


def _scope_from_dict(raw: Any, scope_name: str) -> RsopScope:
    """`scope_name` is the slot being filled, and is the default for `scope`.

    An old snapshot that never stored the field still comes back correctly
    labelled, because the caller always knows which half it is reading.
    """
    data = _as_dict(raw)
    return RsopScope(
        scope=_as_str(data.get("scope"), scope_name) or scope_name,
        available=_as_bool(data.get("available"), False),
        unavailable_reason=_as_str(data.get("unavailable_reason")),
        name=_as_str(data.get("name")),
        domain=_as_str(data.get("domain")),
        som=_as_str(data.get("som")),
        site=_as_str(data.get("site")),
        slow_link=_as_str(data.get("slow_link")),
        version=_as_str(data.get("version")),
        gpos=[_gpo_from_dict(g) for g in _as_list(data.get("gpos"))],
        security_groups=_as_pairs(data.get("security_groups")),
        extensions=[_extension_from_dict(e)
                    for e in _as_list(data.get("extensions"))],
        settings=[_setting_from_dict(s)
                  for s in _as_list(data.get("settings"))],
    )


def result_to_dict(result: RsopResult) -> Dict[str, Any]:
    """The `rsop` block of a snapshot file. Public so callers can embed it."""
    return {
        "read_time": result.read_time,
        "data_type": result.data_type,
        "error": result.error,
        "computer": _scope_to_dict(result.computer),
        "user": _scope_to_dict(result.user),
    }


def result_from_dict(raw: Any) -> RsopResult:
    """Inverse of `result_to_dict`. Never raises on odd input."""
    data = _as_dict(raw)
    return RsopResult(
        computer=_scope_from_dict(data.get("computer"), "Computer"),
        user=_scope_from_dict(data.get("user"), "User"),
        read_time=_as_str(data.get("read_time")),
        data_type=_as_str(data.get("data_type")),
        error=_as_str(data.get("error")),
    )


# ------------------------------------------------------------------
# Snapshot metadata
# ------------------------------------------------------------------

@dataclass
class SnapshotMeta:
    """What the list view needs, without touching the payload.

    `error` non-empty means this file could not be read; every other field is
    then a best guess (the id from the filename, the time from the mtime) so a
    broken snapshot still has a row rather than taking the listing down.
    """

    snapshot_id: str = ""
    path: str = ""
    label: str = ""
    taken_at: str = ""
    schema_version: int = SCHEMA_VERSION
    computer_name: str = ""
    user_name: str = ""
    computer_available: bool = False
    user_available: bool = False
    setting_count: int = 0
    gpo_count: int = 0
    read_time: str = ""
    error: str = ""

    @property
    def readable(self) -> bool:
        return not self.error

    @property
    def display_name(self) -> str:
        """What to put in a combo box."""
        stamp = self.taken_at or "unknown time"
        if self.error:
            return "%s (unreadable)" % (self.label or self.snapshot_id or stamp)
        return "%s - %s" % (stamp, self.label) if self.label else stamp


@dataclass
class Snapshot:
    """A loaded snapshot: its metadata and the report it holds."""

    meta: SnapshotMeta = field(default_factory=SnapshotMeta)
    result: RsopResult = field(default_factory=RsopResult)

    @property
    def ok(self) -> bool:
        return not self.meta.error


def _meta_to_dict(meta: SnapshotMeta) -> Dict[str, Any]:
    # `path` is deliberately not stored: the file can be moved or the profile
    # roamed, and a stale absolute path in the sidecar would then be wrong.
    return {
        "snapshot_id": meta.snapshot_id,
        "label": meta.label,
        "taken_at": meta.taken_at,
        "schema_version": meta.schema_version,
        "computer_name": meta.computer_name,
        "user_name": meta.user_name,
        "computer_available": meta.computer_available,
        "user_available": meta.user_available,
        "setting_count": meta.setting_count,
        "gpo_count": meta.gpo_count,
        "read_time": meta.read_time,
    }


def _meta_from_dict(raw: Any, path: str, snapshot_id: str) -> SnapshotMeta:
    data = _as_dict(raw)
    return SnapshotMeta(
        snapshot_id=_as_str(data.get("snapshot_id"), snapshot_id) or snapshot_id,
        path=path,
        label=_as_str(data.get("label")),
        taken_at=_as_str(data.get("taken_at")),
        schema_version=_as_int(data.get("schema_version"), SCHEMA_VERSION),
        computer_name=_as_str(data.get("computer_name")),
        user_name=_as_str(data.get("user_name")),
        computer_available=_as_bool(data.get("computer_available"), False),
        user_available=_as_bool(data.get("user_available"), False),
        setting_count=_as_int(data.get("setting_count")),
        gpo_count=_as_int(data.get("gpo_count")),
        read_time=_as_str(data.get("read_time")),
    )


def _derive_meta(result: RsopResult, snapshot_id: str, path: str,
                 label: str, taken_at: str) -> SnapshotMeta:
    return SnapshotMeta(
        snapshot_id=snapshot_id,
        path=path,
        label=label,
        taken_at=taken_at,
        schema_version=SCHEMA_VERSION,
        computer_name=result.computer.name,
        user_name=result.user.name,
        computer_available=result.computer.available,
        user_available=result.user.available,
        setting_count=sum(len(s.settings) for s in result.scopes),
        gpo_count=sum(len(s.gpos) for s in result.scopes),
        read_time=result.read_time,
    )


# ------------------------------------------------------------------
# Save / list / load / delete
# ------------------------------------------------------------------

def _paths_for(directory: str, snapshot_id: str) -> Tuple[str, str]:
    return (os.path.join(directory, snapshot_id + _PAYLOAD_SUFFIX),
            os.path.join(directory, snapshot_id + _META_SUFFIX))


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    """Write via a temp file and rename, so a crash cannot leave half a file.

    A half-written snapshot is worse than no snapshot: it lists, it looks
    real, and it fails only when someone tries to diff against it.
    """
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                logger.debug("Could not remove temp file %s", tmp, exc_info=True)


def save_snapshot(result: RsopResult, label: str = "",
                  directory: Optional[str] = None,
                  taken_at: Optional[datetime] = None) -> SnapshotMeta:
    """Freeze `result` to disk and return the metadata describing it.

    `label` is the user's own note and is stored in the sidecar only -- it is
    never used to build the filename, so a label containing a slash or a colon
    cannot escape `directory` or produce a name Windows refuses.

    Raises `OSError` if the directory cannot be created or the payload cannot
    be written; the caller is asking for a write and has to hear about a disk
    that said no.
    """
    directory = directory or default_snapshot_dir()
    os.makedirs(directory, exist_ok=True)

    stamp = taken_at or datetime.now()
    # The random tail keeps two saves in the same second from colliding.
    snapshot_id = "rsop-%s-%s" % (stamp.strftime("%Y%m%d-%H%M%S"),
                                  uuid.uuid4().hex[:6])
    payload_path, meta_path = _paths_for(directory, snapshot_id)

    meta = _derive_meta(result, snapshot_id, payload_path, label,
                        stamp.isoformat(timespec="seconds"))
    document = dict(_meta_to_dict(meta))
    document["rsop"] = result_to_dict(result)

    _write_json(payload_path, document)
    # Sidecar last: if the payload write failed we never claim a snapshot
    # exists. A payload with no sidecar is recoverable (see `_meta_for_file`);
    # a sidecar with no payload is a ghost row.
    try:
        _write_json(meta_path, _meta_to_dict(meta))
    except OSError as exc:
        # Not fatal -- listing falls back to the payload for this one file.
        logger.warning("Snapshot %s saved but its index sidecar failed: %s",
                       snapshot_id, exc)
    logger.debug("Saved RSOP snapshot %s (%d settings)", snapshot_id,
                 meta.setting_count)
    return meta


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _fallback_meta(path: str, snapshot_id: str, error: str) -> SnapshotMeta:
    """A row for a file we could not read. The mtime is the only date left."""
    taken_at = ""
    try:
        taken_at = datetime.fromtimestamp(
            os.path.getmtime(path)).isoformat(timespec="seconds")
    except OSError:
        logger.debug("Could not stat %s for a fallback timestamp", path,
                     exc_info=True)
    return SnapshotMeta(snapshot_id=snapshot_id, path=path, taken_at=taken_at,
                        error=error)


def _meta_for_file(payload_path: str) -> SnapshotMeta:
    """Metadata for one snapshot, from its sidecar when there is one.

    The sidecar is the whole point of the two-file layout: it is a few hundred
    bytes against a payload that can be megabytes.
    """
    directory, filename = os.path.split(payload_path)
    snapshot_id = filename[:-len(_PAYLOAD_SUFFIX)]
    _, meta_path = _paths_for(directory, snapshot_id)

    if os.path.exists(meta_path):
        try:
            return _meta_from_dict(_read_json(meta_path), payload_path,
                                   snapshot_id)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            # Fall through to the payload: the sidecar is a cache, and a
            # damaged cache must not condemn an intact snapshot.
            logger.warning("Snapshot index %s is unreadable (%s); reading the "
                           "snapshot itself instead", meta_path, exc)

    try:
        document = _as_dict(_read_json(payload_path))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("Snapshot %s could not be read: %s", payload_path, exc)
        return _fallback_meta(payload_path, snapshot_id,
                              "Could not read this snapshot: %s" % exc)

    meta = _meta_from_dict(document, payload_path, snapshot_id)
    if not meta.setting_count and not meta.gpo_count:
        # An older layout that stored no counts -- derive them, since the
        # payload is already parsed at this point and it costs nothing.
        derived = _derive_meta(result_from_dict(document.get("rsop")),
                               snapshot_id, payload_path, meta.label,
                               meta.taken_at)
        meta.setting_count = derived.setting_count
        meta.gpo_count = derived.gpo_count
        meta.computer_available = meta.computer_available or derived.computer_available
        meta.user_available = meta.user_available or derived.user_available
        meta.computer_name = meta.computer_name or derived.computer_name
        meta.user_name = meta.user_name or derived.user_name
    return meta


def list_snapshots(directory: Optional[str] = None) -> List[SnapshotMeta]:
    """Every snapshot in `directory`, newest first. Never raises.

    Unreadable files are returned with `error` set rather than skipped: a
    snapshot silently missing from the list is how someone concludes their
    history was deleted.
    """
    directory = directory or default_snapshot_dir()
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        # Nothing saved yet is the normal first-run state, not a problem.
        logger.debug("Snapshot directory %s does not exist yet", directory)
        return []
    except OSError as exc:
        logger.warning("Could not list snapshot directory %s: %s", directory, exc)
        return []

    metas = [_meta_for_file(os.path.join(directory, name))
             for name in names if name.endswith(_PAYLOAD_SUFFIX)]
    # `snapshot_id` carries the same timestamp, so it breaks ties in the same
    # direction instead of leaving equal-second saves in arbitrary order.
    metas.sort(key=lambda m: (m.taken_at, m.snapshot_id), reverse=True)
    return metas


def load_snapshot(path: str) -> Snapshot:
    """Read one snapshot back into a real `RsopResult`.

    Follows `parse_rsop_xml`'s contract rather than raising: a failure comes
    back as a `Snapshot` whose `meta.error` and `result.error` say what went
    wrong, so a pane can show the message in its error banner without a
    try/except around every call.
    """
    snapshot_id = os.path.basename(path)
    if snapshot_id.endswith(_PAYLOAD_SUFFIX):
        snapshot_id = snapshot_id[:-len(_PAYLOAD_SUFFIX)]

    try:
        raw = _read_json(path)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        message = "Could not read this snapshot: %s" % exc
        logger.warning("Snapshot %s could not be loaded: %s", path, exc)
        result = RsopResult()
        result.error = message
        return Snapshot(meta=_fallback_meta(path, snapshot_id, message),
                        result=result)

    document = _as_dict(raw)
    meta = _meta_from_dict(document, path, snapshot_id)
    if meta.schema_version > SCHEMA_VERSION:
        # Load it anyway. Fields we do not know about are ignored, and the
        # ones we do know about have not changed meaning -- refusing here
        # would strand a user who downgraded the app.
        logger.warning("Snapshot %s was written by a newer version (schema %d "
                       "> %d); reading the fields this build understands",
                       snapshot_id, meta.schema_version, SCHEMA_VERSION)

    result = result_from_dict(document.get("rsop"))
    if not meta.taken_at:
        # An older writer that stored no timestamp still sorts and displays,
        # using the file's own mtime.
        stamped = _fallback_meta(path, snapshot_id, "")
        meta.taken_at = stamped.taken_at
    return Snapshot(meta=meta, result=result)


def delete_snapshot(path: str) -> bool:
    """Remove a snapshot and its sidecar. False (logged) if anything refused."""
    directory, filename = os.path.split(path)
    snapshot_id = filename[:-len(_PAYLOAD_SUFFIX)] if filename.endswith(
        _PAYLOAD_SUFFIX) else filename
    ok = True
    for target in _paths_for(directory, snapshot_id):
        if not os.path.exists(target):
            continue
        try:
            os.remove(target)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", target, exc)
            ok = False
    return ok


# ------------------------------------------------------------------
# Diff model
# ------------------------------------------------------------------

@dataclass
class SettingChange:
    """One setting that appeared, disappeared or moved.

    `occurrence` is 1-based within its `(category, name)` group and
    `duplicates` is how many that group holds; both are 1 for the ordinary
    case. They exist so a UI can tell five same-named SrpV2 values apart
    instead of showing five identical-looking rows.
    """

    category: str = ""
    name: str = ""
    occurrence: int = 1
    duplicates: int = 1
    old_value: str = ""
    new_value: str = ""
    old_gpo: str = ""
    new_gpo: str = ""
    details_changed: bool = False

    @property
    def key(self) -> Tuple[str, str]:
        return (self.category, self.name)

    @property
    def value_changed(self) -> bool:
        return self.old_value != self.new_value

    @property
    def gpo_changed(self) -> bool:
        return self.old_gpo != self.new_gpo


@dataclass
class GpoChange:
    """A GPO that appeared, disappeared, or flipped applied/denied.

    `old_applied` / `new_applied` are None on the side where the GPO did not
    exist, which is what tells "added" apart from "flipped to applied".
    """

    name: str = ""
    guid: str = ""
    old_applied: Optional[bool] = None
    new_applied: Optional[bool] = None
    old_reason: str = ""
    new_reason: str = ""

    @property
    def flipped(self) -> bool:
        return (self.old_applied is not None and self.new_applied is not None
                and self.old_applied != self.new_applied)


@dataclass
class ExtensionChange:
    """A client-side extension whose reported status moved.

    `change` is "added", "removed" or "status_changed".
    """

    name: str = ""
    identifier: str = ""
    change: str = "status_changed"
    old_status: str = ""
    new_status: str = ""
    old_error: str = ""
    new_error: str = ""
    old_end_time: str = ""
    new_end_time: str = ""

    @property
    def old_failed(self) -> bool:
        return self.old_error not in ("0", "")

    @property
    def new_failed(self) -> bool:
        return self.new_error not in ("0", "")

    @property
    def started_failing(self) -> bool:
        return self.new_failed and not self.old_failed


@dataclass
class ScopeDiff:
    """What changed in one half of the report.

    When `visibility_change` is set the scope was collected in one snapshot
    and not the other, and the change lists are deliberately left EMPTY: a
    scope that went from refused to collected did not change, our access to it
    did. `settings_behind_visibility` / `gpos_behind_visibility` carry how much
    appeared or vanished with it, so the UI can say so without implying the
    machine moved.
    """

    scope: str = ""
    old_available: bool = False
    new_available: bool = False
    visibility_change: str = VISIBILITY_UNCHANGED
    visibility_note: str = ""
    settings_behind_visibility: int = 0
    gpos_behind_visibility: int = 0
    settings_added: List[SettingChange] = field(default_factory=list)
    settings_removed: List[SettingChange] = field(default_factory=list)
    settings_changed: List[SettingChange] = field(default_factory=list)
    gpos_added: List[GpoChange] = field(default_factory=list)
    gpos_removed: List[GpoChange] = field(default_factory=list)
    gpos_state_changed: List[GpoChange] = field(default_factory=list)
    extension_changes: List[ExtensionChange] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """True when both snapshots saw this scope, so a diff means something."""
        return self.visibility_change == VISIBILITY_UNCHANGED

    @property
    def total_changes(self) -> int:
        """Real changes only -- a visibility flip is counted by itself."""
        return (len(self.settings_added) + len(self.settings_removed)
                + len(self.settings_changed) + len(self.gpos_added)
                + len(self.gpos_removed) + len(self.gpos_state_changed)
                + len(self.extension_changes))

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0

    @property
    def has_visibility_change(self) -> bool:
        return self.visibility_change != VISIBILITY_UNCHANGED

    def describe(self) -> str:
        """One line for a status bar or a report header."""
        if self.has_visibility_change:
            return "%s: %s" % (self.scope, self.visibility_note)
        if not self.has_changes:
            return "%s: no changes" % self.scope
        bits = []
        # The plural is spelled out rather than built by appending "s": the
        # noun is not always the last word ("2 settings added", not "2 setting
        # addeds").
        for count, singular, plural in (
                (len(self.settings_added), "setting added", "settings added"),
                (len(self.settings_removed), "setting removed", "settings removed"),
                (len(self.settings_changed), "setting changed", "settings changed"),
                (len(self.gpos_added), "GPO added", "GPOs added"),
                (len(self.gpos_removed), "GPO removed", "GPOs removed"),
                (len(self.gpos_state_changed), "GPO state flipped",
                 "GPO states flipped"),
                (len(self.extension_changes), "extension status change",
                 "extension status changes")):
            if count:
                bits.append("%d %s" % (count, singular if count == 1 else plural))
        return "%s: %s" % (self.scope, ", ".join(bits))


@dataclass
class RsopDiff:
    computer: ScopeDiff = field(default_factory=lambda: ScopeDiff("Computer"))
    user: ScopeDiff = field(default_factory=lambda: ScopeDiff("User"))
    old_label: str = ""
    new_label: str = ""
    old_taken_at: str = ""
    new_taken_at: str = ""

    @property
    def scopes(self) -> List[ScopeDiff]:
        return [self.computer, self.user]

    @property
    def total_changes(self) -> int:
        return sum(s.total_changes for s in self.scopes)

    @property
    def has_changes(self) -> bool:
        return any(s.has_changes for s in self.scopes)

    @property
    def has_visibility_change(self) -> bool:
        return any(s.has_visibility_change for s in self.scopes)

    def describe(self) -> List[str]:
        return [s.describe() for s in self.scopes]


# ------------------------------------------------------------------
# Diffing
# ------------------------------------------------------------------

def _setting_signature(setting: PolicySetting) -> Tuple[Any, ...]:
    """Everything about a setting except which of its duplicates it is."""
    return (setting.value, setting.gpo, tuple(setting.details))


def _group_settings(
        settings: Sequence[PolicySetting]
) -> "OrderedDict[Tuple[str, str], List[Tuple[int, PolicySetting]]]":
    """`(category, name)` -> its occurrences, in document order."""
    groups: "OrderedDict[Tuple[str, str], List[Tuple[int, PolicySetting]]]"
    groups = OrderedDict()
    for setting in settings:
        bucket = groups.setdefault((setting.category, setting.name), [])
        bucket.append((len(bucket) + 1, setting))  # occurrence is 1-based
    return groups


def _change_from(category: str, name: str, occurrence: int, duplicates: int,
                 old: Optional[PolicySetting],
                 new: Optional[PolicySetting]) -> SettingChange:
    return SettingChange(
        category=category,
        name=name,
        occurrence=occurrence,
        duplicates=duplicates,
        old_value=old.value if old else "",
        new_value=new.value if new else "",
        old_gpo=old.gpo if old else "",
        new_gpo=new.gpo if new else "",
        details_changed=bool(old and new and old.details != new.details),
    )


def _diff_settings(old: Sequence[PolicySetting], new: Sequence[PolicySetting],
                   into: ScopeDiff) -> None:
    """Fill `into`'s three settings lists.

    Duplicates are the interesting part. Within one `(category, name)` group
    the occurrences are first paired off by identical content, so a group that
    merely came back in a different order reports nothing; only what is left
    unpaired is a real add, removal or change. Pairing by position alone would
    turn a reordered group of five into five bogus "changed" rows, and keying
    on the name alone would drop four of the five entirely.
    """
    old_groups = _group_settings(old)
    new_groups = _group_settings(new)

    # Union of keys, new-snapshot order first, so the report reads in the order
    # the current machine presents its settings.
    keys = list(new_groups.keys())
    keys += [key for key in old_groups if key not in new_groups]

    for category, name in keys:
        old_items = list(old_groups.get((category, name), []))
        new_items = list(new_groups.get((category, name), []))
        duplicates = max(len(old_items), len(new_items))

        # Pass 1: exact content matches drop out of the comparison entirely.
        unmatched_old = list(old_items)
        remaining_new: List[Tuple[int, PolicySetting]] = []
        for occurrence, setting in new_items:
            signature = _setting_signature(setting)
            match = next((i for i, (_, candidate) in enumerate(unmatched_old)
                          if _setting_signature(candidate) == signature), None)
            if match is None:
                remaining_new.append((occurrence, setting))
            else:
                unmatched_old.pop(match)

        # Pass 2: whatever is left pairs off in order -- those are changes.
        for index, (occurrence, setting) in enumerate(remaining_new):
            if index < len(unmatched_old):
                into.settings_changed.append(_change_from(
                    category, name, occurrence, duplicates,
                    unmatched_old[index][1], setting))
            else:
                into.settings_added.append(_change_from(
                    category, name, occurrence, duplicates, None, setting))
        for occurrence, setting in unmatched_old[len(remaining_new):]:
            into.settings_removed.append(_change_from(
                category, name, occurrence, duplicates, setting, None))


def _gpo_key(gpo: GpoInfo) -> Tuple[str, str]:
    """Identity of a GPO across snapshots.

    The GUID is the real identity -- a policy can be renamed without becoming
    a different policy -- but a GPO with no GUID in the report would then
    collide with every other one, so those fall back to the name.
    """
    return ("guid", gpo.guid) if gpo.guid else ("name", gpo.name)


def _gpo_change(old: Optional[GpoInfo], new: Optional[GpoInfo]) -> GpoChange:
    reference = new or old
    if reference is None:  # pragma: no cover - keys always come from a GPO
        return GpoChange()
    return GpoChange(
        name=reference.name,
        guid=reference.guid,
        old_applied=old.applied if old else None,
        new_applied=new.applied if new else None,
        old_reason=old.denied_reason if old else "",
        new_reason=new.denied_reason if new else "",
    )


def _diff_gpos(old: Sequence[GpoInfo], new: Sequence[GpoInfo],
               into: ScopeDiff) -> None:
    old_by_key = OrderedDict((_gpo_key(g), g) for g in old)
    new_by_key = OrderedDict((_gpo_key(g), g) for g in new)

    for key, gpo in new_by_key.items():
        previous = old_by_key.get(key)
        if previous is None:
            into.gpos_added.append(_gpo_change(None, gpo))
        elif previous.applied != gpo.applied:
            # The flip is the headline: a GPO that is still listed but no
            # longer winning is invisible in a plain added/removed diff.
            into.gpos_state_changed.append(_gpo_change(previous, gpo))
    for key, gpo in old_by_key.items():
        if key not in new_by_key:
            into.gpos_removed.append(_gpo_change(gpo, None))


def _diff_extensions(old: Sequence[ExtensionStatus],
                     new: Sequence[ExtensionStatus], into: ScopeDiff) -> None:
    """Compare on status and error only.

    Begin/end times move on every policy refresh, so including them would
    report every extension as changed on every diff and bury the one that
    actually started failing. The times are still carried on the change for
    display.
    """
    old_by_key = OrderedDict(((e.name, e.identifier), e) for e in old)
    new_by_key = OrderedDict(((e.name, e.identifier), e) for e in new)

    for key, ext in new_by_key.items():
        previous = old_by_key.get(key)
        if previous is None:
            into.extension_changes.append(ExtensionChange(
                name=ext.name, identifier=ext.identifier, change="added",
                new_status=ext.logging_status, new_error=ext.error,
                new_end_time=ext.end_time))
        elif (previous.logging_status, previous.error) != (ext.logging_status,
                                                           ext.error):
            into.extension_changes.append(ExtensionChange(
                name=ext.name, identifier=ext.identifier,
                change="status_changed",
                old_status=previous.logging_status,
                new_status=ext.logging_status,
                old_error=previous.error, new_error=ext.error,
                old_end_time=previous.end_time, new_end_time=ext.end_time))
    for key, ext in old_by_key.items():
        if key not in new_by_key:
            into.extension_changes.append(ExtensionChange(
                name=ext.name, identifier=ext.identifier, change="removed",
                old_status=ext.logging_status, old_error=ext.error,
                old_end_time=ext.end_time))


def diff_scopes(old: RsopScope, new: RsopScope) -> ScopeDiff:
    """Compare one half of two reports."""
    diff = ScopeDiff(scope=new.scope or old.scope or "",
                     old_available=old.available,
                     new_available=new.available)

    if old.available != new.available:
        # See the ScopeDiff docstring: this is a change in what we could SEE.
        # Walking the contents here would report hundreds of settings as new.
        if new.available:
            diff.visibility_change = VISIBILITY_GAINED
            diff.settings_behind_visibility = len(new.settings)
            diff.gpos_behind_visibility = len(new.gpos)
            diff.visibility_note = (
                "not collected before, collected now - %d settings and %d GPOs "
                "are newly visible; this is a change in what could be read, "
                "not a change on this machine"
                % (diff.settings_behind_visibility, diff.gpos_behind_visibility))
        else:
            reason = (" (%s)" % new.unavailable_reason
                      if new.unavailable_reason else "")
            diff.visibility_change = VISIBILITY_LOST
            diff.settings_behind_visibility = len(old.settings)
            diff.gpos_behind_visibility = len(old.gpos)
            diff.visibility_note = (
                "collected before, not collected now - %d settings and %d GPOs "
                "can no longer be read%s; this is a change in what could be "
                "read, not a change on this machine"
                % (diff.settings_behind_visibility,
                   diff.gpos_behind_visibility, reason))
        return diff

    if not new.available:
        # Never collected in either snapshot: nothing to say, and nothing to
        # imply. An empty diff here is the honest answer.
        return diff

    _diff_settings(old.settings, new.settings, diff)
    _diff_gpos(old.gpos, new.gpos, diff)
    _diff_extensions(old.extensions, new.extensions, diff)
    return diff


def diff_rsop(old: RsopResult, new: RsopResult) -> RsopDiff:
    """Compare two reports, scope by scope. `old` is the earlier one."""
    return RsopDiff(
        computer=diff_scopes(old.computer, new.computer),
        user=diff_scopes(old.user, new.user),
        old_taken_at=old.read_time,
        new_taken_at=new.read_time,
    )


def diff_snapshot_files(old_path: str, new_path: str) -> RsopDiff:
    """Load two snapshots and diff them, keeping their labels and times.

    A snapshot that failed to load contributes an empty `RsopResult`, so the
    diff is still returned; the caller checks the loaded snapshots (or the
    labels) if it needs to tell that apart from "nothing changed".
    """
    old = load_snapshot(old_path)
    new = load_snapshot(new_path)
    diff = diff_rsop(old.result, new.result)
    diff.old_label = old.meta.label
    diff.new_label = new.meta.label
    diff.old_taken_at = old.meta.taken_at or diff.old_taken_at
    diff.new_taken_at = new.meta.taken_at or diff.new_taken_at
    return diff
