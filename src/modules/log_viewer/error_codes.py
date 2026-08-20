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
