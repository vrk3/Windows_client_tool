"""Error-code lookup for log lines — CMTrace's Error Lookup.

The reason people reach for CMTrace is rarely the colours: it is that a log
line says `0x80070005` and they need to know that means "access denied".

Three sources, in order of how much they actually know:

1. **Windows itself**, for the Win32 facility (`0x8007xxxx`). The low sixteen
   bits are a Win32 error code and `FormatMessage` has a real sentence for
   every one of them. That beats any table this file could carry.
2. **A ConfigMgr table** for the `0x87Dxxxxx` range, which Windows does not
   know and which is most of what an SCCM log actually contains.
3. **The app's existing `decode_wu_error`**, for the Windows Update codes it
   already curates.

Anything still unrecognised returns "" rather than a guess. A wrong
explanation of an error code is worse than none: it sends someone off after
the wrong problem entirely.

No Qt here, so the lookup is testable without a display.
"""
import ctypes
from dataclasses import dataclass
import logging
import re

logger = logging.getLogger(__name__)

#: 0x followed by 8 hex digits. Shorter runs are matched too, since logs
#: write 0x5 as readily as 0x00000005, but a bare number is NOT: "id 12345"
#: is not an error code and flagging it would make the feature noise.
_CODE = re.compile(r"\b0[xX]([0-9a-fA-F]{1,8})\b")

#: The Win32 facility. The low word is a plain Win32 error code.
_WIN32_FACILITY = 0x80070000

#: ConfigMgr's own range. Windows has no idea about these, and they are the
#: ones an SCCM log is full of.
CONFIGMGR_CODES = {
    0x87D00201: "content location request failed — no distribution point",
    0x87D00213: "the client is not assigned to a site",
    0x87D00215: "no matching software update was found",
    0x87D00231: "no distribution point found for the content",
    0x87D00244: "the deployment is not applicable to this machine",
    0x87D00269: "content download failed",
    0x87D00280: "a required policy has not arrived yet",
    0x87D00314: "the application is already installed",
    0x87D01106: "the program failed because a dependency failed",
    0x87D0128F: "waiting for a maintenance window",
    0x87D00668: "the software update failed to install",
    0x87D20B0C: "the task sequence step failed",
}


def find_codes(text: str) -> list:
    """Every distinct hex code in `text`, in the order it appears."""
    seen = []
    for match in _CODE.finditer(text or ""):
        code = int(match.group(1), 16)
        if code not in seen:
            seen.append(code)
    return seen


def code_spans(text: str) -> list:
    """`(start, end, code)` for every code occurrence, in order.

    `find_codes` answers "which codes are here" and de-duplicates. The
    delegate asks "where are they" and must colour both occurrences of a
    code that appears twice, so this one does not.
    """
    return [(match.start(), match.end(), int(match.group(1), 16))
            for match in _CODE.finditer(text or "")]


@dataclass(frozen=True)
class Advice:
    """What a code usually means, and what to do about it."""
    cause: str
    remedy: str
    reference: str


#: Codes whose cause is documented and whose remedy is something a person can
#: actually run and then check.
#:
#: **Nothing here is invented, and the table is deliberately short.** A
#: plausible-sounding fix for the wrong error costs more time than no fix at
#: all, because it gets acted on. A code with no entry keeps the name-only
#: behaviour `describe()` already gives it -- silence beats a guess.
#:
#: The four below are the ones this machine's own logs actually produce:
#: 0x80004005 appears 522 times in the CBS archive and 0x80070490 five times.
CODE_ADVICE = {
    0x800F081F: Advice(
        cause="The component store has no source for the files the update "
              "needs -- usually the payload was cleaned up or the machine "
              "cannot reach Windows Update.",
        remedy="DISM /Online /Cleanup-Image /RestoreHealth, adding "
               "/Source:<path> and /LimitAccess if the machine is offline.",
        reference="CBS_E_SOURCE_MISSING; Microsoft's servicing repair "
                  "guidance."),
    0x80073701: Advice(
        cause="A referenced assembly is missing from the component store, so "
              "servicing cannot complete the operation.",
        remedy="DISM /Online /Cleanup-Image /RestoreHealth, then sfc "
               "/scannow to confirm the store is consistent.",
        reference="ERROR_SXS_ASSEMBLY_MISSING."),
    0x800F0805: Advice(
        cause="The package handed to servicing is not a valid package -- "
              "commonly a damaged or partly downloaded update.",
        remedy="Remove the cached update and let Windows Update download it "
               "again; DISM /Online /Cleanup-Image /RestoreHealth if the "
               "store itself is suspect.",
        reference="CBS_E_INVALID_PACKAGE."),
    0x80070490: Advice(
        cause="An element servicing looked for is not present in the store. "
              "It accompanies a store that is missing or has damaged "
              "manifests rather than being a fault in the update itself.",
        remedy="DISM /Online /Cleanup-Image /RestoreHealth, then sfc "
               "/scannow.",
        reference="ERROR_NOT_FOUND."),
    0x80004005: Advice(
        cause="An unspecified failure. It is a GENERIC code and carries no "
              "detail of its own, so the useful information is in the lines "
              "around it, not in the number.",
        remedy="Read the records immediately before this one -- the Summary "
               "panel's first-error row is usually the specific failure this "
               "is reporting.",
        reference="E_FAIL. Deliberately offers no repair command: doing so "
                  "would be inventing a fix for an error that does not say "
                  "what went wrong."),
}


def advice(code: int):
    """What is documented about `code`, or None.

    None is the common answer and the right one: an explanation of the wrong
    error sends someone after a problem they do not have.
    """
    return CODE_ADVICE.get(code & 0xFFFFFFFF)


def describe(code: int) -> str:
    """A sentence for `code`, or "" when nothing reliable is known.

    Silence beats a guess: an explanation of the wrong error sends someone
    after a problem they do not have.
    """
    if code in CONFIGMGR_CODES:
        return CONFIGMGR_CODES[code]

    unsigned = code & 0xFFFFFFFF
    if (unsigned & 0xFFFF0000) == _WIN32_FACILITY:
        try:
            message = ctypes.FormatError(unsigned & 0xFFFF).strip()
        except Exception:                           # noqa: BLE001
            message = ""
        if message and not message.lower().startswith("unknown error"):
            return message

    try:
        from core.wu_error_codes import decode_wu_error

        decoded = decode_wu_error(unsigned)
    except Exception:                               # noqa: BLE001
        return ""
    # decode_wu_error echoes the raw code when it knows nothing; that is not
    # an explanation, so it is not offered as one.
    if decoded and " - " in decoded:
        return decoded.split(" - ", 1)[1]
    if decoded and decoded.lower() == "success":
        return "success"
    return ""


def explain(text: str) -> list:
    """(code_text, meaning) for every FAILING code in `text`.

    Success codes are deliberately left out. Measured on a real 85,850-line
    CBS.log: 4,553 lines carry a hex code and 4,427 of them -- 97% -- carry
    nothing but 0x00000000. Reporting those would put "success" on screen
    four thousand times to surface the nine lines that actually failed, which
    is how a feature earns being ignored. `describe` still answers for any
    code, including success, when something asks about one specifically.
    """
    out = []
    for code in find_codes(text):
        if not _is_failure(code):
            continue
        meaning = describe(code)
        if meaning:
            out.append((f"0x{code:08X}", meaning))
    return out


#: Phrases that mean the component store is damaged, as Windows actually
#: writes them. A servicing failure says so in words at least as often as in
#: a code, and those words rendered as ordinary Info-coloured text.
#:
#: Each one is anchored to real wording rather than to a keyword. "Repair" on
#: its own is routine -- CBS says it constantly while everything is fine --
#: and "corruption" appears in prose about checking for it. A marker that
#: fires on either would colour thousands of rows and stop meaning anything.
#:
#: `STATUS_SXS_\w+` is deliberately open-ended: new SXS statuses arrive with
#: new Windows builds, and a hardcoded roster would silently stop matching.
_CORRUPTION = re.compile(
    r"STATUS_SXS_\w+"
    r"|cannot repair"
    r"|store corruption"
    r"|do not match",
    re.IGNORECASE)


def corruption_spans(text: str) -> list:
    """`(start, end, label)` for every damage marker in `text`.

    Ordered and non-overlapping, so the delegate can lay them alongside the
    error-code spans without nesting tags. The label is the matched phrase
    lowercased, which is what names the finding.
    """
    return [(match.start(), match.end(), match.group(0).lower())
            for match in _CORRUPTION.finditer(text)]


def _is_failure(code: int) -> bool:
    """An HRESULT fails when its sign bit is set; 0 is S_OK."""
    return bool(int(code) & 0xFFFFFFFF & 0x80000000)


def annotate(text: str) -> str:
    """`text` with an explanation appended, or unchanged if nothing is known.

    Used for the tooltip: the line as written, then what its codes mean.
    """
    found = explain(text)
    if not found:
        return text
    lines = [text, ""]
    lines.extend(f"{code}  —  {meaning}" for code, meaning in found)
    return "\n".join(lines)
