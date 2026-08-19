"""NTFS owners, for the Users view (spec 5.8).

Two Win32 steps, injected so the caching and the fallbacks can be tested
without an ACL: path -> owner SID, then SID -> account name. Both are
optional at runtime; without pywin32 every lookup declines and the Users view
says so, rather than the scan failing.

**The SID lookup is cached, the path read is not.** LookupAccountSid can be a
domain round trip and a volume has a handful of distinct owners, so caching it
turns half a million lookups into a handful. Reading the SID off a file, by
contrast, genuinely differs per file.

No PyQt6 here: this is engine code (see the standing constraint in the ledger).
"""


def _default_sid_of_path(path: str):
    import win32security

    descriptor = win32security.GetFileSecurity(
        path, win32security.OWNER_SECURITY_INFORMATION)
    sid = descriptor.GetSecurityDescriptorOwner()
    return win32security.ConvertSidToStringSid(sid), sid


def _default_name_of_sid(sid) -> str:
    import win32security

    name, domain, _type = win32security.LookupAccountSid(None, sid)
    return "\\".join((domain, name)) if domain else name


def is_available() -> tuple[bool, str]:
    try:
        __import__("win32security")
    except ImportError:
        return False, ("pywin32 is not installed, so file owners cannot be "
                       "read.")
    return True, ""


class OwnerResolver:
    """path -> account name, with the SID lookup memoised.

    Returns "" when the owner cannot be read at all. An unreadable ACL is
    ordinary -- a locked folder, a file that vanished mid-scan -- and is not
    worth an exception on the hot path of a scan.
    """

    def __init__(self, sid_of_path=None, name_of_sid=None) -> None:
        self._sid_of_path = sid_of_path or _default_sid_of_path
        self._name_of_sid = name_of_sid or _default_name_of_sid
        self._names: dict[str, str] = {}

    def for_path(self, path: str) -> str:
        try:
            sid_string, sid = self._sid_of_path(path)
        except Exception:                           # noqa: BLE001
            return ""
        if not sid_string:
            return ""
        cached = self._names.get(sid_string)
        if cached is not None:
            return cached
        try:
            name = self._name_of_sid(sid) or sid_string
        except Exception:                           # noqa: BLE001
            # An account that no longer exists still owns files. The raw SID
            # is a usable bucket in the Users view; "" is not. Cached, so a
            # dead account is not looked up once per file that it owns.
            name = sid_string
        self._names[sid_string] = name
        return name


PLACEHOLDER_PREFIX = "$SECURE:"


def resolve_sampled_owners(store, resolver, on_progress=None) -> int:
    """Turn an MFT scan's `$SECURE:<id>` placeholders into account names.

    The MFT gives every record a security id but not the descriptor behind it,
    so the fast path can only record `$SECURE:256`. One file per distinct id
    is enough to recover the name: sample its path, read its owner, and rename
    the whole bucket. A volume has a handful of distinct ids and hundreds of
    thousands of files, so this costs a handful of calls rather than one per
    file.

    Returns how many buckets were named. A bucket whose sample cannot be read
    keeps its placeholder -- an honest `$SECURE:256` beats a name borrowed
    from a different file.
    """
    samples: dict[int, int] = {}
    for node in range(len(store)):
        owner_id = store.owner_id[node]
        if owner_id < 0 or owner_id in samples:
            continue
        if not store.owner(owner_id).startswith(PLACEHOLDER_PREFIX):
            continue
        samples[owner_id] = node

    resolved = 0
    for index, (owner_id, node) in enumerate(sorted(samples.items())):
        name = resolver.for_path(store.path(node))
        if name:
            store.rename_owner(owner_id, name)
            resolved += 1
        if on_progress:
            on_progress(index + 1, len(samples))
    return resolved
