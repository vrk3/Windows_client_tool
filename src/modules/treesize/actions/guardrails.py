"""Path guardrails for destructive operations (spec 7.2).

The spec calls this the highest-value defence in the module, and the reason is
specific: a path-assembly bug anywhere in the MFT reader could aim a recursive
delete at something unrecoverable. The engine reconstructs paths by walking
parent links across half a million nodes; one wrong parent and a delete lands
somewhere nobody asked for.

So this module does not trust the caller's path. It refuses drive roots and
the well-known system directories outright, and it refuses anything at or above
them, unless the caller passes an explicit override that a human had to tick.

Pure path logic, no Qt and no filesystem writes, so it is fully testable.
"""
import os

#: System directories. Protected as WHOLE TREES: deleting anything inside
#: %SystemRoot% or %ProgramFiles% is dangerous enough to be worth an override,
#: not just deleting the directory itself.
_PROTECTED_TREE_ENV = (
    "SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
    "ProgramData",
)

#: Directories protected only at the ROOT. The spec says "the user profile
#: root", and it means it: clearing junk out of your own Downloads folder is
#: the single most common thing this tool is used for, and demanding an
#: override for it would train people to tick the box without reading it --
#: which is exactly how the override stops protecting anything.
_PROTECTED_ROOT_ENV = ("USERPROFILE", "PUBLIC")


class Refusal(Exception):
    """Raised when a path is refused. The message is shown to the user."""


def _normalise(path: str) -> str:
    """A comparable absolute path: resolved, no trailing slash, lowercased.

    Comparison happens on normalised text rather than on the string the caller
    supplied, because "C:/Windows", "C:\\Windows\\" and "c:\\windows\\." are the
    same directory and only one of them looks dangerous.
    """
    if not path:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(path))
    try:
        resolved = os.path.abspath(expanded)
    except (OSError, ValueError):
        resolved = expanded
    stripped = resolved.rstrip("\\/")
    # A bare drive letter keeps its separator: "C:" means the current directory
    # on C:, while "C:\" means the root. Losing that distinction here would
    # make a root look like something else entirely.
    if len(stripped) == 2 and stripped[1] == ":":
        stripped += "\\"
    return stripped.lower()


def is_drive_root(path: str) -> bool:
    normalised = _normalise(path)
    return len(normalised) == 3 and normalised[1] == ":" and normalised[2] == "\\"


def _from_env(names) -> set[str]:
    out = set()
    for name in names:
        value = os.environ.get(name)
        if value:
            out.add(_normalise(value))
    return out


def protected_trees() -> set[str]:
    """System directories protected along with everything inside them."""
    return _from_env(_PROTECTED_TREE_ENV)


def protected_roots() -> set[str]:
    """Directories protected only at the root itself."""
    return _from_env(_PROTECTED_ROOT_ENV)


def protected_paths() -> set[str]:
    """Every directory that is refused as a target, for either reason."""
    return protected_trees() | protected_roots()


def is_within(path: str, ancestor: str) -> bool:
    """True when `path` is `ancestor` or sits underneath it.

    Uses a separator-terminated prefix so that "C:\\Windows10" is not treated
    as living inside "C:\\Windows" -- a plain startswith would say it does.
    """
    a = _normalise(path)
    b = _normalise(ancestor)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b if b.endswith("\\") else b + "\\")


def check(path: str, *, override: bool = False) -> None:
    """Raise Refusal if `path` must not be operated on destructively.

    `override` corresponds to a checkbox the user had to tick, and it does NOT
    unlock drive roots: there is no legitimate "delete C:\\" and offering one is
    a footgun with no upside.
    """
    if not path or not path.strip():
        raise Refusal("No path given.")

    normalised = _normalise(path)

    if is_drive_root(path):
        raise Refusal(
            f"{path} is a drive root. Deleting an entire drive is never offered, "
            f"with or without the override.")

    everything = protected_paths()

    # The target IS a protected directory. Refused regardless of the override:
    # nobody means to delete Windows or their whole profile.
    if normalised in everything:
        raise Refusal(f"{path} is a protected location and cannot be removed.")

    # The target CONTAINS a protected directory, so removing it takes that
    # directory with it. This is the case a path-assembly bug actually
    # produces, and it is the one worth catching.
    for protected in everything:
        if is_within(protected, normalised):
            raise Refusal(
                f"{path} contains a protected location "
                f"({protected}) and cannot be removed as a whole.")

    # Inside a protected SYSTEM tree: allowed, but only deliberately.
    if not override:
        for protected in protected_trees():
            if is_within(path, protected):
                raise Refusal(
                    f"{path} is inside a protected system location "
                    f"({protected}). Tick the override if you are certain.")


def is_allowed(path: str, *, override: bool = False) -> bool:
    try:
        check(path, override=override)
    except Refusal:
        return False
    return True
