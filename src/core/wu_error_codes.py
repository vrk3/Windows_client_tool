"""Windows Update HRESULT decoder — ported from Update Center's Convert-UcWuError.

Known WU_E_* codes get a human explanation. For the 0x8007xxxx (Win32) facility
only, unknown codes fall back to ctypes.WinError()'s system message — that
fallback is NOT valid for other facilities (e.g. 0x8024xxxx WU-specific codes),
so it is intentionally restricted to 0x8007xxxx.
"""
from typing import Optional

WU_ERROR_MAP = {
    0x80240017: "the update is not applicable to this system (WU_E_NOT_APPLICABLE)",
    0x80240037: "unsupported operation (WU_E_NOT_SUPPORTED)",
    0x8024000B: "the operation was cancelled (WU_E_CALL_CANCELLED)",
    0x8024000E: "invalid XML received from server (WU_E_XML_INVALID)",
    0x80240022: "all updates failed to install (WU_E_ALL_UPDATES_FAILED)",
    0x80240034: "download failed (WU_E_DOWNLOAD_FAILED)",
    0x8024001E: "operation stopped — service or system is shutting down",
    0x8024002E: "Windows Update access is restricted by policy (WU_E_WU_DISABLED)",
    0x80240438: "the WU agent could not contact the service — check network/proxy",
    0x8024402C: "server name could not be resolved — DNS or proxy issue",
    0x80244022: "server returned 503 (temporarily unavailable) — try again later",
    0x8024200D: "an additional download is required (WU_E_UH_NEEDANOTHERDOWNLOAD)",
    0x80248007: "local WU datastore is missing data — try resetting WU components",
    0x8024500C: "the server rejected the request (WU_E_REDIRECTOR_LOAD_XML)",
    0x80D02002: "Delivery Optimization download timed out",
    0x800F0922: "installation failed in CBS — often a full System Reserved partition",
    0x80070005: "access denied — run as administrator",
    0x80070020: "file in use by another process (sharing violation)",
    0x80070570: "corrupt file — try DISM /RestoreHealth then sfc /scannow",
    0x800705B4: "timeout",
    0x80070643: "MSI/MSU installation error",
    0x8007000E: "not enough memory",
}


def decode_wu_error(hresult) -> str:
    """Return a human-readable explanation for a Windows Update HRESULT.

    Accepts either a signed or unsigned int. Returns 'success' for 0, a mapped
    explanation for known codes, a Win32Exception-derived message only for the
    0x8007xxxx facility, and the raw hex code otherwise.
    """
    try:
        hr = int(hresult)
    except (TypeError, ValueError):
        return ""
    if hr == 0:
        return "success"

    unsigned = hr & 0xFFFFFFFF
    hex_str = f"0x{unsigned:08X}"

    if unsigned in WU_ERROR_MAP:
        return f"{hex_str} - {WU_ERROR_MAP[unsigned]}"

    if (unsigned & 0xFFFF0000) == 0x80070000:
        msg = _win32_message(unsigned & 0xFFFF)
        if msg:
            return f"{hex_str} - {msg}"

    if (unsigned & 0xFFFF0000) == 0x80240000:
        return f"{hex_str} - unknown Windows Update code, look it up on learn.microsoft.com"

    return hex_str


def _win32_message(code: int) -> Optional[str]:
    try:
        import ctypes

        return ctypes.WinError(code).strerror
    except Exception:
        return None
