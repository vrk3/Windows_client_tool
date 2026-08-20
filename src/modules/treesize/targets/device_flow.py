"""OAuth 2.0 device authorization grant, RFC 8628 (spec 6.2).

    | **SharePoint** | Microsoft Graph | Entra ID app auth ... |
    | **Google Drive** | Drive v3 API | OAuth device flow ... |

Both took a PASTED access token instead. That is not merely inconvenient: a
Graph access token lives about an hour, so a scan set up in the morning was
broken by lunchtime with no way to renew it except going back to whatever
tool minted the token in the first place.

The device flow is plain HTTP -- no vendor SDK. That matters here, because
the SharePoint backend is already plain Graph REST over `httpx`: with this it
becomes usable end to end, rather than usable for an hour at a time.

**Verification owed.** The protocol below is exercised against a real local
HTTP server in the tests, so the request shapes, the polling cadence, the
`slow_down` back-off and the error mapping are all checked over a genuine
socket. It has NOT been run against Microsoft's or Google's endpoints -- that
needs an app registration this machine does not have. Treat a first live run
as the real test, and see RESUME.md.
"""
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

#: RFC 8628 §3.5. Absent from the response, the client polls every 5 seconds.
DEFAULT_INTERVAL = 5
#: RFC 8628 §3.5: on slow_down the client MUST increase the interval by 5s.
SLOW_DOWN_INCREMENT = 5


class DeviceFlowError(Exception):
    """The flow cannot continue. The message is meant for the user."""


@dataclass(frozen=True)
class Provider:
    name: str
    device_endpoint: str
    token_endpoint: str
    scope: str
    #: Google requires the installed-app secret at the token step; Microsoft
    #: does not use one for a public client. Neither is a secret in any
    #: meaningful sense for a desktop app, which is why the device flow exists.
    wants_client_secret: bool = False


def microsoft(tenant: str = "common") -> Provider:
    """Entra ID. `offline_access` is what buys a refresh token."""
    base = f"https://login.microsoftonline.com/{tenant or 'common'}/oauth2/v2.0"
    return Provider(
        name="Microsoft",
        device_endpoint=f"{base}/devicecode",
        token_endpoint=f"{base}/token",
        scope="offline_access Files.Read.All Sites.Read.All",
    )


def google() -> Provider:
    return Provider(
        name="Google",
        device_endpoint="https://oauth2.googleapis.com/device/code",
        token_endpoint="https://oauth2.googleapis.com/token",
        scope="https://www.googleapis.com/auth/drive.metadata.readonly",
        wants_client_secret=True,
    )


@dataclass(frozen=True)
class DeviceCode:
    """What the user has to be shown, and what we poll with."""
    device_code: str
    user_code: str
    verification_uri: str
    interval: int = DEFAULT_INTERVAL
    expires_in: int = 900
    verification_uri_complete: str = ""

    @property
    def instructions(self) -> str:
        if self.verification_uri_complete:
            return (f"Open {self.verification_uri_complete} and confirm the "
                    f"code {self.user_code}.")
        return (f"Open {self.verification_uri} and enter the code "
                f"{self.user_code}.")


@dataclass
class Token:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scope: str = ""
    extra: dict = field(default_factory=dict)

    def expired(self, now=None, skew: int = 60) -> bool:
        """`skew` seconds early, so a token cannot die mid-request."""
        if not self.expires_at:
            return False
        return (now if now is not None else time.time()) >= self.expires_at - skew


def _post(transport, url: str, data: dict):
    """One form POST. `transport` is injected so tests need no network."""
    try:
        return transport(url, data)
    except DeviceFlowError:
        raise
    except Exception as exc:                        # noqa: BLE001
        raise DeviceFlowError(f"Could not reach {url}: {exc}") from exc


def default_transport(timeout: float = 30.0):
    """An httpx-backed form poster. httpx is already an optional dependency."""
    def post(url: str, data: dict):
        try:
            import httpx
        except ImportError as exc:                  # pragma: no cover
            raise DeviceFlowError(
                "httpx is not installed. Install it with: pip install httpx"
            ) from exc
        response = httpx.post(url, data=data, timeout=timeout)
        try:
            payload = response.json()
        except Exception:                           # noqa: BLE001
            payload = {}
        return response.status_code, payload
    return post


def request_code(provider: Provider, client_id: str, *, transport=None,
                 scope: str = "") -> DeviceCode:
    """Ask the provider for a user code (RFC 8628 §3.1-3.2)."""
    if not client_id:
        raise DeviceFlowError(
            f"{provider.name} needs the client ID of an app registration. "
            f"Register one and paste its ID here — the device flow cannot "
            f"start without it.")
    transport = transport or default_transport()
    status, payload = _post(transport, provider.device_endpoint, {
        "client_id": client_id,
        "scope": scope or provider.scope,
    })
    if status >= 400 or "device_code" not in payload:
        raise DeviceFlowError(_describe(payload, status, provider))
    return DeviceCode(
        device_code=payload["device_code"],
        user_code=payload.get("user_code", ""),
        verification_uri=(payload.get("verification_uri")
                          or payload.get("verification_url", "")),
        verification_uri_complete=(payload.get("verification_uri_complete")
                                   or payload.get("verification_url_complete", "")),
        interval=int(payload.get("interval") or DEFAULT_INTERVAL),
        expires_in=int(payload.get("expires_in") or 900),
    )


def poll_for_token(provider: Provider, client_id: str, code: DeviceCode, *,
                   client_secret: str = "", transport=None,
                   sleep=time.sleep, clock=time.monotonic,
                   should_cancel=None) -> Token:
    """Poll until the user approves, or the code dies (RFC 8628 §3.4-3.5).

    `authorization_pending` is the NORMAL answer for as long as the user is
    still typing the code into a browser, and must not be treated as an error.
    `slow_down` means back off by five seconds and keep going -- a client that
    ignores it gets rate-limited into failing a flow the user completed.
    """
    transport = transport or default_transport()
    interval = max(1, code.interval)
    deadline = clock() + max(1, code.expires_in)

    data = {
        "grant_type": DEVICE_CODE_GRANT,
        "device_code": code.device_code,
        "client_id": client_id,
    }
    if provider.wants_client_secret and client_secret:
        data["client_secret"] = client_secret

    while True:
        if should_cancel is not None and should_cancel():
            raise DeviceFlowError("Sign-in was cancelled.")
        if clock() >= deadline:
            raise DeviceFlowError(
                f"The code {code.user_code} expired before it was approved. "
                f"Start the sign-in again.")
        sleep(interval)
        status, payload = _post(transport, provider.token_endpoint, data)
        error = payload.get("error") or ""

        if not error and payload.get("access_token"):
            return _token_from(payload, clock=time.time)
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += SLOW_DOWN_INCREMENT
            continue
        if error == "expired_token":
            raise DeviceFlowError(
                f"The code {code.user_code} expired. Start the sign-in again.")
        if error == "access_denied":
            raise DeviceFlowError("Sign-in was refused in the browser.")
        raise DeviceFlowError(_describe(payload, status, provider))


def refresh(provider: Provider, client_id: str, refresh_token: str, *,
            client_secret: str = "", transport=None) -> Token:
    """Trade a refresh token for a fresh access token.

    The entire point of asking for `offline_access`: without this a scan set
    up in the morning is dead by lunchtime.
    """
    if not refresh_token:
        raise DeviceFlowError("There is no refresh token to renew with.")
    transport = transport or default_transport()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if provider.wants_client_secret and client_secret:
        data["client_secret"] = client_secret
    status, payload = _post(transport, provider.token_endpoint, data)
    if status >= 400 or not payload.get("access_token"):
        raise DeviceFlowError(_describe(payload, status, provider))
    token = _token_from(payload, clock=time.time)
    if not token.refresh_token:
        # Providers often omit it on refresh, meaning "keep the one you have".
        token.refresh_token = refresh_token
    return token


def _token_from(payload: dict, clock) -> Token:
    expires_in = payload.get("expires_in")
    return Token(
        access_token=payload.get("access_token", ""),
        refresh_token=payload.get("refresh_token", "") or "",
        expires_at=(clock() + int(expires_in)) if expires_in else 0.0,
        scope=payload.get("scope", "") or "",
        extra={k: v for k, v in payload.items()
               if k not in ("access_token", "refresh_token", "expires_in",
                            "scope")},
    )


def _describe(payload: dict, status: int, provider: Provider) -> str:
    """Prefer the provider's own words; they are better than ours."""
    detail = (payload.get("error_description")
              or payload.get("error")
              or f"HTTP {status}")
    return f"{provider.name} sign-in failed: {detail}"


def sign_in(provider: Provider, client_id: str, on_code, *,
            client_secret: str = "", transport=None, sleep=time.sleep,
            clock=time.monotonic, should_cancel=None) -> Token:
    """The whole flow in one call: get a code, show it, wait for approval.

    `on_code(DeviceCode)` is how the caller puts the code in front of the
    user. It is called exactly once, before any polling starts, because the
    user cannot approve a code they have not been shown yet.
    """
    code = request_code(provider, client_id, transport=transport)
    on_code(code)
    return poll_for_token(provider, client_id, code,
                          client_secret=client_secret, transport=transport,
                          sleep=sleep, clock=clock, should_cancel=should_cancel)


def access_token_for(credentials, provider: Provider, *, transport=None,
                     on_refresh=None) -> str:
    """The token to send, renewing it first if we can and it needs it.

    Order matters. A pasted token is used as given -- someone who pastes one
    is telling us to use that, and silently swapping it for a refreshed one
    would make a deliberate act look broken. Only when there is no pasted
    token do we reach for the stored refresh token.

    `on_refresh(Token)` lets the caller persist a rotated refresh token;
    providers that rotate them invalidate the old one, so failing to store the
    new one turns a renewable session into a single-use one.
    """
    extra = getattr(credentials, "extra", None) or {}
    pasted = getattr(credentials, "password", "") or extra.get("token", "")
    if pasted:
        return pasted

    refresh_token = extra.get("refresh_token", "")
    client_id = extra.get("client_id", "")
    if not refresh_token or not client_id:
        return ""
    token = refresh(provider, client_id, refresh_token,
                    client_secret=extra.get("client_secret", ""),
                    transport=transport)
    if on_refresh is not None:
        try:
            on_refresh(token)
        except Exception:                           # noqa: BLE001
            logger.warning("Could not persist the refreshed token",
                           exc_info=True)
    return token.access_token
