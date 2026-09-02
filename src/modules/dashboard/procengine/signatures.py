r"""The Authenticode signature of a file -- verified, not guessed.

`WinVerifyTrust` (wintrust.dll) is the check Windows itself runs before it
runs an unknown program: is the certificate chain valid, trusted, and
unexpired? That is the answer this module gives, plus who signed it.

It lives beside `modinfo.py` for a reason. `modinfo` reads the version
resource of the same files this verifies, and both are facts about a FILE
rather than about a process. A machine loads the same hundred system DLLs in
every process, so a signature is cached per path -- verifying `ntdll.dll`
once is the difference between verifying it once and once per process that
loaded it.

The signer name is extracted from the PKCS#7 certificate store the signed
file embeds (`CryptQueryObject`), and the leaf of that chain is the signer:
the one certificate that is not itself the issuer of any other certificate
in the chain. Picking by position would be fragile -- chains are enumerated
CA-first, and some embed their root and some do not.

**A refusal is not an answer.** A file that cannot be read, or a signature
that cannot be processed, is `None` with a reason -- never "unsigned",
which is a claim about the file that may be false. "Unsigned" means
`WinVerifyTrust` said there is no signature, which is itself an answer.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)

# The action that verifies a file as Windows does for an executable.
WINTRUST_ACTION_GENERIC_VERIFY_V2 = (0x00AAC56B, 0xCD44, 0x11D0,
                                     (0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2,
                                      0x95, 0xEE))

WTD_UI_NONE = 2
WTD_CHOICE_FILE = 1
WTD_REVOKE_NONE = 0
WTD_REVOCATION_CHECK_NONE = 0x10

CERT_QUERY_OBJECT_FILE = 1
CERT_NAME_SIMPLE_DISPLAY_TYPE = 4
CERT_NAME_ISSUER_FLAG = 0x00000001

#: HRESULTs WinVerifyTrust can return that are not "valid". Each is a claim
#: about the file: "not signed" and "explicitly distrusted" are different
#: facts and must not be blurred into one.
_TRUST_E_NOSIGNATURE = 0x800B0100      # no signature at all
_TRUST_E_EXPLICIT_DISTRUST = 0x800B0111
_TRUST_E_SUBJECT_NOT_TRUSTED = 0x800B0004
_TRUST_E_BAD_DIGEST = 0x80096010
_CRYPT_E_SECURITY_SETTINGS = 0x80092026
_TRUST_E_TIME_STAMP = 0x800B0108
#: WinVerifyTrust reports an expired signing certificate as 0x800B0101.
#: It is not a refusal -- the file WAS signed, and the signature has lapsed,
#: which is a verdict the user should see, not a "could not verify".
_CERT_E_EXPIRED = 0x800B0101

#: The statuses a file can have, in the words a user understands.
#: "valid" and "not_signed" are answers; "could_not_verify" is a refusal
#: with a reason beside it.
VALID = "valid"
NOT_SIGNED = "not_signed"
INVALID = "invalid"
COULD_NOT_VERIFY = "could_not_verify"


@dataclass(frozen=True, slots=True)
class SignatureFacts:
    """What the Authenticode signature of one file turned out to be.

    `status` is one of `VALID`, `NOT_SIGNED`, `INVALID` or
    `COULD_NOT_VERIFY`. `signer` is the certificate subject of whoever
    signed it -- `None` when there is no signature or no signer could be
    read. `reason` carries the why, and exists precisely for the refusals:
    "could not verify: access denied" reads differently from "unsigned".
    """

    path: str
    status: str
    signer: Optional[str] = None
    reason: Optional[str] = None

    @property
    def signed(self) -> bool:
        return self.status == VALID


#: path -> SignatureFacts. A signature is a fact about a FILE; a machine
#: loads the same hundred system DLLs in every process, so the cache is
#: what keeps verifying ntdll.dll from happening once per process.
_SIGNATURE_CACHE: Dict[str, SignatureFacts] = {}


def verify_signature(path: str) -> SignatureFacts:
    """Verify the Authenticode signature of `path`.

    Cached per path -- the point of the module. Never raises: an
    unreadable file is `COULD_NOT_VERIFY` with a reason, not an exception.
    """
    if path in _SIGNATURE_CACHE:
        return _SIGNATURE_CACHE[path]

    if not path or not os.path.isfile(path):
        facts = SignatureFacts(path, COULD_NOT_VERIFY,
                               reason="the file does not exist")
        _SIGNATURE_CACHE[path] = facts
        return facts

    status, reason = _trust_status(path)
    signer = None
    if status == VALID:
        signer = _signer_name(path)
    elif status == NOT_SIGNED:
        # An unsigned file names no signer, and saying so is not an error.
        pass
    facts = SignatureFacts(path, status, signer=signer, reason=reason)
    _SIGNATURE_CACHE[path] = facts
    return facts


def clear_cache() -> None:
    """Drop every cached verdict. Tests call this between cases."""
    _SIGNATURE_CACHE.clear()


# ---- the verification ---------------------------------------------------

def _trust_status(path: str) -> Tuple[str, Optional[str]]:
    """`(status, reason)` from WinVerifyTrust.

    `reason` is set only for `COULD_NOT_VERIFY`; the other statuses carry
    their meaning in the status itself.
    """
    file_info = _WINTRUST_FILE_INFO()
    file_info.cbStruct = ctypes.sizeof(_WINTRUST_FILE_INFO)
    file_info.pcwszFilePath = path

    data = _WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
    data.dwUIChoice = WTD_UI_NONE
    data.fdwRevocationChecks = WTD_REVOKE_NONE
    data.dwUnionChoice = WTD_CHOICE_FILE
    data.pFile = ctypes.cast(ctypes.byref(file_info), ctypes.c_void_p)
    # WTD_REVOCATION_CHECK_NONE: checking revocation pulls the network in
    # on the verification path and makes it a synchronous stall. The trust
    # verdict here is about the embedded signature, not the network.
    data.dwProvFlags = WTD_REVOCATION_CHECK_NONE

    action = _GUID(*WINTRUST_ACTION_GENERIC_VERIFY_V2)
    code = _wintrust.WinVerifyTrust(None, ctypes.byref(action),
                                    ctypes.byref(data))
    # WinVerifyTrust returns an HRESULT through a c_long, so success is 0
    # and a failure like TRUST_E_NOSIGNATURE comes back NEGATIVE. Mask to
    # unsigned before comparing against the 0x8.../0xC... constants --
    # this project paid for that mistake once (W3-03) and will not again.
    code = code & 0xFFFFFFFF
    if code == 0:
        return VALID, None
    if code == _TRUST_E_NOSIGNATURE:
        return NOT_SIGNED, None
    if code in (_TRUST_E_EXPLICIT_DISTRUST, _TRUST_E_SUBJECT_NOT_TRUSTED,
                _TRUST_E_BAD_DIGEST, _CRYPT_E_SECURITY_SETTINGS,
                _TRUST_E_TIME_STAMP, _CERT_E_EXPIRED):
        return INVALID, _describe(code)
    return COULD_NOT_VERIFY, _describe(code)


def _describe(code: int) -> str:
    """An HRESULT as a sentence someone can act on.

    The common ones are named rather than hex, because "0x800B0100" in a
    cell is a number, not an explanation. The rare ones get hex -- a real
    description is worse than none, and the code is what a search wants.
    """
    known = {
        _TRUST_E_EXPLICIT_DISTRUST: "the certificate is explicitly "
                                    "distrusted",
        _TRUST_E_SUBJECT_NOT_TRUSTED: "the certificate is not trusted",
        _TRUST_E_BAD_DIGEST: "the file has been modified since it was "
                             "signed (digest mismatch)",
        _CRYPT_E_SECURITY_SETTINGS: "the signature does not meet the "
                                    "system's security policy",
        _TRUST_E_TIME_STAMP: "the signature or its timestamp has expired",
        _CERT_E_EXPIRED: "the signing certificate has expired",
    }
    if code in known:
        return known[code]
    try:
        text = ctypes.WinError(code & 0xFFFF).strerror
        if text:
            return f"WinVerifyTrust refused: {text} (0x{code & 0xFFFFFFFF:08X})"
    except Exception:  # noqa: BLE001 - a missing WinError is not fatal
        logger.debug("_describe: giving up on this read", exc_info=True)
        pass
    return f"WinVerifyTrust refused (0x{code & 0xFFFFFFFF:08X})"


# ---- the signer ---------------------------------------------------------

def _signer_name(path: str) -> Optional[str]:
    """The certificate subject of whoever signed `path`.

    Reads the PKCS#7 certificate store the file embeds and picks the LEAF:
    the one certificate that is not the issuer of any other certificate in
    the chain. Chains enumerate CA-first (some even embed their root), so
    neither "first" nor "last" is the signer; the not-an-issuer rule is
    what makes Microsoft Windows the answer for kernel32.dll and Git for
    Git.
    """
    h_store, h_msg = _open_signature(path)
    if not h_store:
        return None
    try:
        certs = _certificates(h_store)
    finally:
        _crypt32.CertCloseStore(h_store, 0)
    if not certs:
        return None
    return _leaf_signer(certs)


def _open_signature(path: str) -> Tuple[Optional[int], Optional[int]]:
    """`(store, message)` handles for the signature embedded in `path`.

    A file with no signature yields no store. A file with one yields a
    store holding the certificate chain. Declared prototypes are not a
    formality here: `CryptQueryObject` returns handles through its
    pointer arguments, and an undeclared ctypes call truncates pointers to
    32 bits (the lesson details.py paid for with an access violation).
    """
    encoding = wintypes.DWORD()
    content_type = wintypes.DWORD()
    format_type = wintypes.DWORD()
    store = wintypes.HANDLE()
    message = wintypes.HANDLE()
    ok = _crypt32.CryptQueryObject(
        CERT_QUERY_OBJECT_FILE, path, 0x3FFF, 0xFFFF, 0,
        ctypes.byref(encoding), ctypes.byref(content_type),
        ctypes.byref(format_type), ctypes.byref(store),
        ctypes.byref(message), None)
    if not ok or not store.value:
        return None, None
    return int(store.value), int(message.value)


def _certificates(store: int) -> List[Tuple[str, str]]:
    """`[(subject, issuer)]` for every certificate in `store`.

    Both names use the simple display form, which is what a user reads in
    a file dialog. The pair is what lets the leaf rule decide who the
    signer is.
    """
    certs = []
    previous = None
    while True:
        context = _crypt32.CertEnumCertificatesInStore(
            wintypes.HANDLE(store), previous)
        if not context:
            break
        certs.append((_cert_name(context, 0), _cert_name(context,
                                                          CERT_NAME_ISSUER_FLAG)))
        previous = context
    return certs


def _cert_name(context, flags: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _crypt32.CertGetNameStringW(
        context, CERT_NAME_SIMPLE_DISPLAY_TYPE, flags, None, buffer,
        len(buffer))
    return buffer.value or ""


def _leaf_signer(certs: List[Tuple[str, str]]) -> Optional[str]:
    """The certificate nobody was issued by.

    In a signature's certificate store, the signer is the leaf: every other
    certificate exists to issue it or to issue its issuer. A subject that
    appears as somebody else's issuer cannot be it. When the rule is
    ambiguous (a single self-signed certificate, say) that one certificate
    IS the signer.
    """
    subjects = {subject for subject, _issuer in certs if subject}
    issuers = {issuer for _subject, issuer in certs if issuer}
    leaves = [subject for subject in sorted(subjects)
              if subject not in issuers]
    if leaves:
        return leaves[0]
    # Everything issues something or is anonymous; fall back to the first
    # named certificate, which for a signed file is the chain's leaf.
    return next((subject for subject, _issuer in certs if subject), None)


# ---- the ctypes declarations -------------------------------------------

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, d1, d2, d3, d4):
        super().__init__(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD),
                ("pcwszFilePath", wintypes.LPCWSTR),
                ("hFile", wintypes.HANDLE),
                ("pgKnownSubject", ctypes.c_void_p)]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD),
                ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPClientData", ctypes.c_void_p),
                ("dwUIChoice", wintypes.DWORD),
                ("fdwRevocationChecks", wintypes.DWORD),
                ("dwUnionChoice", wintypes.DWORD),
                ("pFile", ctypes.c_void_p),
                ("dwStateAction", wintypes.DWORD),
                ("hWVTStateData", wintypes.HANDLE),
                ("pwszURLReference", wintypes.LPCWSTR),
                ("dwProvFlags", wintypes.DWORD),
                ("dwUIContext", wintypes.DWORD)]


_wintrust.WinVerifyTrust.restype = ctypes.c_long
_wintrust.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID),
                                     ctypes.c_void_p]

_crypt32.CryptQueryObject.restype = wintypes.BOOL
_crypt32.CryptQueryObject.argtypes = [
    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
    ctypes.c_void_p]

_crypt32.CertEnumCertificatesInStore.restype = ctypes.c_void_p
_crypt32.CertEnumCertificatesInStore.argtypes = [wintypes.HANDLE,
                                                 ctypes.c_void_p]

_crypt32.CertGetNameStringW.restype = wintypes.DWORD
_crypt32.CertGetNameStringW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.LPWSTR, wintypes.DWORD]

_crypt32.CertCloseStore.restype = wintypes.BOOL
_crypt32.CertCloseStore.argtypes = [wintypes.HANDLE, wintypes.DWORD]
