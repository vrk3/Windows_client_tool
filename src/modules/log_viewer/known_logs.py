"""The logs worth one click, for the viewer's Open menu.

Same idea as TreeSize's quick scan locations: somewhere to go, rather than
typing a path every time. Resolved from the ENVIRONMENT, never a hardcoded
`C:` — Windows is not always on C:, and a hardcoded path does not fail
loudly, it silently opens nothing.

Absent logs are dropped, so the list is what this machine actually has.

No Qt here.
"""
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnownLog:
    label: str
    path: str


def _candidates(environ) -> list:
    system_root = environ.get("SystemRoot", "")
    program_data = environ.get("ProgramData", "")

    def under(*parts):
        return os.path.join(system_root, *parts) if system_root else ""

    return [
        ("CBS (component store)", under("Logs", "CBS", "CBS.log")),
        ("DISM", under("Logs", "DISM", "dism.log")),
        ("Windows Update (ReportingEvents)",
         under("SoftwareDistribution", "ReportingEvents.log")),
        ("Setup (setupact)", under("Panther", "setupact.log")),
        ("Setup errors (setuperr)", under("Panther", "setuperr.log")),
        ("Windows Update (WindowsUpdate.log)", under("WindowsUpdate.log")),
        # ConfigMgr, when the client is installed. Absent on a plain machine,
        # and the whole reason a CMTrace-style viewer exists.
        ("ConfigMgr — CcmExec", under("CCM", "Logs", "CcmExec.log")),
        ("ConfigMgr — AppEnforce", under("CCM", "Logs", "AppEnforce.log")),
        ("ConfigMgr — UpdatesDeployment",
         under("CCM", "Logs", "UpdatesDeployment.log")),
        ("ConfigMgr — client setup", under("ccmsetup", "Logs", "ccmsetup.log")),
        ("Intune Management Extension",
         os.path.join(program_data, "Microsoft", "IntuneManagementExtension",
                      "Logs", "IntuneManagementExtension.log")
         if program_data else ""),
    ]


def known_logs(environ=None, exists=None) -> list:
    """The logs present on this machine, in menu order."""
    environ = os.environ if environ is None else environ
    exists = os.path.isfile if exists is None else exists

    out = []
    seen = set()
    for label, path in _candidates(environ):
        if not path:
            continue
        key = os.path.normcase(os.path.normpath(path))
        if key in seen or not exists(path):
            continue
        seen.add(key)
        out.append(KnownLog(label, path))
    return out


def newest_cbs_archive(environ=None, exists=None, listdir=None):
    """The newest `CbsPersist_*.log` beside CBS.log, or "".

    Windows 11 rolls CBS into `CbsPersist_*.cab` archives, and on a machine
    that has been running a while the live `CBS.log` is the smallest part of
    the story. The extracted `.log` siblings are offered when they are there;
    the `.cab` form needs 7-Zip and is left to the Diagnose tab, which
    already does that extraction.
    """
    environ = os.environ if environ is None else environ
    exists = os.path.isdir if exists is None else exists
    listdir = os.listdir if listdir is None else listdir

    system_root = environ.get("SystemRoot", "")
    if not system_root:
        return ""
    folder = os.path.join(system_root, "Logs", "CBS")
    if not exists(folder):
        return ""
    try:
        names = [n for n in listdir(folder)
                 if n.startswith("CbsPersist_") and n.lower().endswith(".log")]
    except OSError:
        logger.debug("Could not list %s", folder, exc_info=True)
        return ""
    if not names:
        return ""
    paths = [os.path.join(folder, n) for n in names]
    try:
        return max(paths, key=os.path.getmtime)
    except OSError:
        return paths[-1]
