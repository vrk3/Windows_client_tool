r"""Getting a log out of a `.cab` so the viewer can open it.

Windows 11 rolls CBS into cabinet files -- four of them in
`C:\Windows\Logs\CBS` on this machine -- and the plain `CBS.log` beside them
is usually the smallest part of the story.

**Extracted with `expand.exe`, which ships with Windows**, rather than with
7-Zip as the older CBS tab does. 7-Zip happens to be installed on this
machine; it is not on most, and depending on it would make this work on the
developer's box and nowhere else.

Two things real CBS cabs do that a naive extractor gets wrong, both found by
running it against the real folder:

* **The member inside is named like the cab, extension and all** --
  `cbspersist_20260829190803.cab` -- so looking for `*.log` in the output
  finds nothing at all.
* **It is 15.8 MB of text from a 465 KB cab.** The caller has to be given
  somewhere with room, and it has to be cleaned up.

No Qt.
"""
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

#: Windows' own cabinet extractor. Full path deliberately: a bare `expand`
#: resolves to a different, unrelated tool under a POSIX shell.
_EXPAND = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "expand.exe")

#: A cabinet starts with these four bytes. Checked before shelling out, so a
#: file that is merely NAMED .cab fails with a sentence rather than with
#: whatever expand.exe says about it.
_MAGIC = b"MSCF"


def is_cab(path: str) -> bool:
    return bool(path) and path.lower().endswith(".cab")


def largest_cbs_cab(environ=None) -> str:
    r"""The biggest `CbsPersist_*.cab`, or "".

    Largest rather than newest, for the reason the log menu already learned:
    the newest CBS archive is routinely the smallest.
    """
    environ = os.environ if environ is None else environ
    root = environ.get("SystemRoot", "")
    if not root:
        return ""
    folder = os.path.join(root, "Logs", "CBS")
    if not os.path.isdir(folder):
        return ""
    biggest, biggest_size = "", -1
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    for name in names:
        lowered = name.lower()
        if not (lowered.startswith("cbspersist") and lowered.endswith(".cab")):
            continue
        path = os.path.join(folder, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > biggest_size:
            biggest, biggest_size = path, size
    return biggest


def extract_cab(path: str, into: str = None):
    """`(extracted path, problem)`. One of the two is always empty.

    Returns the LARGEST file expand produced, because a CBS cab holds one
    member and looking for `*.log` would find nothing -- the member carries
    the cab's own name.
    """
    if not os.path.isfile(path):
        return "", f"{os.path.basename(path) or path} is not there"
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != _MAGIC:
                return "", (f"{os.path.basename(path)} is not a cabinet file")
    except OSError as problem:
        return "", f"could not read {os.path.basename(path)}: {problem}"

    if not os.path.isfile(_EXPAND):
        return "", "expand.exe was not found on this machine"

    target = into or tempfile.mkdtemp(prefix="logviewer_cab_")
    try:
        done = subprocess.run(
            [_EXPAND, "-F:*", path, target],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as problem:
        return "", f"could not run expand.exe: {problem}"
    except subprocess.TimeoutExpired:
        return "", "expand.exe did not finish within two minutes"

    produced = []
    try:
        for name in os.listdir(target):
            candidate = os.path.join(target, name)
            if os.path.isfile(candidate):
                produced.append((os.path.getsize(candidate), candidate))
    except OSError as problem:
        return "", f"could not read the extracted files: {problem}"

    if not produced:
        # expand exits 0 while extracting nothing when the cab is empty or
        # unreadable, so rc is not the signal -- what came out is.
        detail = (done.stdout or done.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "nothing was extracted"
        return "", f"{os.path.basename(path)}: {reason}"

    produced.sort(reverse=True)
    return produced[0][1], ""
