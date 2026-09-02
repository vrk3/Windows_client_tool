import logging

logger = logging.getLogger(__name__)
"""Remote credentials in Windows Credential Manager (spec 6.2).

Spec 6.2 is explicit: credentials go to Credential Manager through pywin32,
**never to a config file**. Only the secret is stored; host, port and path are
ordinary settings and belong wherever the rest of the pane's settings live.

The vault is injected so the tests exercise the keying and the failure paths
without writing to the machine's real credential store -- which a test has no
business doing, and which would fail on a locked-down box anyway.
"""

SERVICE = "TreeSize"


def credential_key(target_id: str, host: str, username: str = "") -> str:
    """One key per backend + host + user.

    All three matter: two accounts on one host, or one account on two hosts,
    are different credentials. A key without the user silently overwrites the
    first account with the second.
    """
    return f"{SERVICE}/{target_id}/{username}@{host}"


class WinCredVault:
    """Windows Credential Manager through pywin32."""

    @staticmethod
    def is_available() -> tuple[bool, str]:
        try:
            __import__("win32cred")
        except ImportError:
            return False, ("pywin32 is not installed, so credentials cannot "
                           "be remembered.")
        return True, ""

    def write(self, key: str, username: str, secret: str) -> None:
        import win32cred

        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": key,
            "UserName": username,
            # CredWrite wants bytes; UTF-16LE is what Credential Manager and
            # every other Windows consumer of this blob expects.
            "CredentialBlob": secret.encode("utf-16-le"),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)

    def read(self, key: str):
        import win32cred

        entry = win32cred.CredRead(key, win32cred.CRED_TYPE_GENERIC, 0)
        blob = entry.get("CredentialBlob") or b""
        return entry.get("UserName") or "", bytes(blob).decode("utf-16-le")

    def erase(self, key: str) -> None:
        import win32cred

        win32cred.CredDelete(key, win32cred.CRED_TYPE_GENERIC, 0)


class CredentialStore:
    """Save, load and forget a remote target's password.

    Every operation swallows vault failures. Credential Manager can be
    disabled by group policy, and a scan that would otherwise run must not die
    because the password could not be cached -- the user typed it, the scan
    can proceed with it, and remembering it was the optional part.
    """

    def __init__(self, vault=None) -> None:
        self._vault = vault if vault is not None else WinCredVault()

    def save(self, target_id: str, credentials) -> bool:
        secret = getattr(credentials, "password", "") or ""
        if not secret:
            # Writing an empty secret would shadow a real stored one on the
            # next load, which reads as "the saved password stopped working".
            return False
        try:
            self._vault.write(
                credential_key(target_id, credentials.host,
                               credentials.username),
                credentials.username, secret)
            return True
        except Exception:                           # noqa: BLE001
            return False

    def load(self, target_id: str, host: str, username: str = ""):
        """(username, password), or None when nothing is stored."""
        try:
            return self._vault.read(credential_key(target_id, host, username))
        except Exception:                           # noqa: BLE001
            # A missing entry raises from CredRead just as a policy block
            # does; neither is worth a dialog. Absent is absent.
            return None

    def forget(self, target_id: str, host: str, username: str = "") -> None:
        try:
            self._vault.erase(credential_key(target_id, host, username))
        except Exception:                           # noqa: BLE001
            logger.debug("forget: giving up on this read", exc_info=True)
            pass
