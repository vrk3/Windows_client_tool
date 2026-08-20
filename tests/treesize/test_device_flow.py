"""Spec 6.2's device flow: RFC 8628.

SharePoint and Google Drive took a PASTED access token. A Graph token lives
about an hour, so a scan set up in the morning was broken by lunchtime with no
way to renew it.

The last third of this file drives the client against a REAL local HTTP server
implementing RFC 8628, not an injected transport -- because an injected seam
is exactly what hid two fatal watcher bugs in this module. That checks the
request shapes, the form encoding, the polling cadence and the error mapping
over a genuine socket. It does NOT check Microsoft's or Google's endpoints;
that needs an app registration this machine does not have.
"""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from modules.treesize.targets import device_flow as df


# ---- providers ----------------------------------------------------------

def test_microsoft_asks_for_offline_access():
    """Without offline_access there is no refresh token, and the whole point
    of this change is that the token outlives the afternoon."""
    assert "offline_access" in df.microsoft().scope


def test_the_tenant_is_configurable_and_defaults_to_common():
    assert "/common/" in df.microsoft().device_endpoint
    assert "/contoso.onmicrosoft.com/" in df.microsoft(
        "contoso.onmicrosoft.com").device_endpoint
    assert "/common/" in df.microsoft("").device_endpoint


def test_google_needs_the_installed_app_secret_and_microsoft_does_not():
    assert df.google().wants_client_secret is True
    assert df.microsoft().wants_client_secret is False


# ---- requesting a code --------------------------------------------------

def _fake(*responses):
    """A transport returning each (status, payload) in turn, recording calls."""
    calls = []
    queue = list(responses)

    def post(url, data):
        calls.append((url, dict(data)))
        return queue.pop(0) if queue else (200, {})

    post.calls = calls
    return post


def test_a_missing_client_id_is_refused_before_any_request():
    transport = _fake()
    with pytest.raises(df.DeviceFlowError, match="client ID"):
        df.request_code(df.microsoft(), "", transport=transport)
    assert transport.calls == [], "it must not have called out at all"


def test_the_code_request_carries_client_id_and_scope():
    transport = _fake((200, {"device_code": "d", "user_code": "ABCD",
                             "verification_uri": "https://x/device",
                             "interval": 7, "expires_in": 300}))
    code = df.request_code(df.microsoft(), "cid", transport=transport)
    _url, data = transport.calls[0]
    assert data["client_id"] == "cid"
    assert "offline_access" in data["scope"]
    assert code.user_code == "ABCD" and code.interval == 7


def test_googles_alternate_field_names_are_accepted():
    """Google answers with verification_url, not verification_uri."""
    transport = _fake((200, {"device_code": "d", "user_code": "Z",
                             "verification_url": "https://google/device"}))
    code = df.request_code(df.google(), "cid", transport=transport)
    assert code.verification_uri == "https://google/device"


def test_a_missing_interval_falls_back_to_the_rfc_default():
    transport = _fake((200, {"device_code": "d", "user_code": "Z",
                             "verification_uri": "u"}))
    code = df.request_code(df.microsoft(), "cid", transport=transport)
    assert code.interval == df.DEFAULT_INTERVAL


def test_the_instructions_name_the_code_and_the_url():
    code = df.DeviceCode("d", "WXYZ", "https://microsoft.com/devicelogin")
    assert "WXYZ" in code.instructions
    assert "microsoft.com/devicelogin" in code.instructions


def test_a_complete_uri_is_preferred_when_offered():
    code = df.DeviceCode("d", "WXYZ", "https://x/device",
                         verification_uri_complete="https://x/device?code=WXYZ")
    assert "?code=WXYZ" in code.instructions


def test_an_error_response_uses_the_providers_own_words():
    transport = _fake((400, {"error": "invalid_client",
                             "error_description": "no such app"}))
    with pytest.raises(df.DeviceFlowError, match="no such app"):
        df.request_code(df.microsoft(), "cid", transport=transport)


# ---- polling ------------------------------------------------------------

def _code(**kw):
    base = dict(device_code="dev", user_code="ABCD",
                verification_uri="u", interval=1, expires_in=100)
    base.update(kw)
    return df.DeviceCode(**base)


def test_authorization_pending_is_not_an_error():
    """It is the NORMAL answer while the user is still typing the code."""
    transport = _fake((400, {"error": "authorization_pending"}),
                      (400, {"error": "authorization_pending"}),
                      (200, {"access_token": "tok", "expires_in": 3600}))
    token = df.poll_for_token(df.microsoft(), "cid", _code(),
                              transport=transport, sleep=lambda _s: None)
    assert token.access_token == "tok"
    assert len(transport.calls) == 3


def test_slow_down_backs_off_by_five_seconds():
    """RFC 8628 3.5. Ignoring it gets the client rate-limited into failing a
    flow the user actually completed."""
    slept = []
    transport = _fake((400, {"error": "slow_down"}),
                      (400, {"error": "slow_down"}),
                      (200, {"access_token": "tok"}))
    df.poll_for_token(df.microsoft(), "cid", _code(interval=5),
                      transport=transport, sleep=slept.append)
    assert slept == [5, 10, 15]


def test_the_poll_body_is_the_device_code_grant():
    transport = _fake((200, {"access_token": "tok"}))
    df.poll_for_token(df.microsoft(), "cid", _code(),
                      transport=transport, sleep=lambda _s: None)
    _url, data = transport.calls[0]
    assert data["grant_type"] == df.DEVICE_CODE_GRANT
    assert data["device_code"] == "dev"
    assert "client_secret" not in data, "Microsoft is a public client"


def test_google_sends_the_client_secret():
    transport = _fake((200, {"access_token": "tok"}))
    df.poll_for_token(df.google(), "cid", _code(), client_secret="shh",
                      transport=transport, sleep=lambda _s: None)
    assert transport.calls[0][1]["client_secret"] == "shh"


def test_access_denied_says_so_plainly():
    transport = _fake((400, {"error": "access_denied"}))
    with pytest.raises(df.DeviceFlowError, match="refused"):
        df.poll_for_token(df.microsoft(), "cid", _code(),
                          transport=transport, sleep=lambda _s: None)


def test_expired_token_names_the_code():
    transport = _fake((400, {"error": "expired_token"}))
    with pytest.raises(df.DeviceFlowError, match="ABCD"):
        df.poll_for_token(df.microsoft(), "cid", _code(),
                          transport=transport, sleep=lambda _s: None)


def test_polling_stops_at_the_deadline_rather_than_forever():
    """A user who walks away must not leave a thread polling for ever."""
    ticks = iter([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] + [999] * 5)
    transport = _fake(*[(400, {"error": "authorization_pending"})] * 50)
    with pytest.raises(df.DeviceFlowError, match="expired"):
        df.poll_for_token(df.microsoft(), "cid", _code(expires_in=5),
                          transport=transport, sleep=lambda _s: None,
                          clock=lambda: next(ticks))


def test_cancelling_stops_the_poll():
    transport = _fake(*[(400, {"error": "authorization_pending"})] * 5)
    with pytest.raises(df.DeviceFlowError, match="cancelled"):
        df.poll_for_token(df.microsoft(), "cid", _code(),
                          transport=transport, sleep=lambda _s: None,
                          should_cancel=lambda: True)
    assert transport.calls == [], "cancel must be checked before polling"


# ---- refresh ------------------------------------------------------------

def test_refresh_keeps_the_old_token_when_none_is_returned():
    """Providers routinely omit it, meaning "keep the one you have". Dropping
    it would silently turn a renewable session into a one-hour one."""
    transport = _fake((200, {"access_token": "new", "expires_in": 3600}))
    token = df.refresh(df.microsoft(), "cid", "old-refresh",
                       transport=transport)
    assert token.access_token == "new"
    assert token.refresh_token == "old-refresh"


def test_a_rotated_refresh_token_replaces_the_old_one():
    transport = _fake((200, {"access_token": "new", "refresh_token": "newer"}))
    token = df.refresh(df.microsoft(), "cid", "old", transport=transport)
    assert token.refresh_token == "newer"


def test_refreshing_without_a_token_is_refused():
    with pytest.raises(df.DeviceFlowError, match="no refresh token"):
        df.refresh(df.microsoft(), "cid", "", transport=_fake())


def test_expiry_is_reported_early_so_a_token_cannot_die_mid_request():
    token = df.Token("t", expires_at=1000.0)
    assert token.expired(now=900) is False
    assert token.expired(now=950) is True          # inside the 60s skew
    assert df.Token("t").expired(now=10 ** 9) is False   # no expiry known


# ---- against a real HTTP server ----------------------------------------

class _RFC8628Handler(BaseHTTPRequestHandler):
    """A minimally correct device-flow server. Answers pending twice first."""

    pending_left = 2

    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        self.server.seen.append((self.path, form))

        if self.path == "/devicecode":
            payload, status = {
                "device_code": "DEV-123", "user_code": "USER-XYZ",
                "verification_uri": "https://example.test/device",
                "interval": 1, "expires_in": 60,
            }, 200
        elif form.get("grant_type") == df.DEVICE_CODE_GRANT:
            if type(self).pending_left > 0:
                type(self).pending_left -= 1
                payload, status = {"error": "authorization_pending"}, 400
            else:
                payload, status = {"access_token": "REAL-TOKEN",
                                   "refresh_token": "REAL-REFRESH",
                                   "expires_in": 3600}, 200
        else:
            payload, status = {"error": "unsupported_grant_type"}, 400

        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def rfc_server():
    _RFC8628Handler.pending_left = 2
    server = HTTPServer(("127.0.0.1", 0), _RFC8628Handler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def test_the_whole_flow_over_a_real_socket(rfc_server):
    """Request shapes, form encoding, polling and JSON parsing, end to end.

    The injected transport above proves the state machine. This proves the
    client actually speaks the protocol on the wire.
    """
    server, base = rfc_server
    provider = df.Provider(
        name="Local", device_endpoint=f"{base}/devicecode",
        token_endpoint=f"{base}/token", scope="offline_access Files.Read.All")

    code = df.request_code(provider, "cid")
    assert code.user_code == "USER-XYZ"
    assert code.device_code == "DEV-123"
    assert code.interval == 1

    token = df.poll_for_token(provider, "cid", code, sleep=lambda _s: None)
    assert token.access_token == "REAL-TOKEN"
    assert token.refresh_token == "REAL-REFRESH"
    assert token.expires_at > 0

    paths = [p for p, _ in server.seen]
    assert paths[0] == "/devicecode"
    assert paths.count("/token") == 3, "two pending answers then the token"
    assert server.seen[0][1]["client_id"] == "cid"
    assert server.seen[1][1]["grant_type"] == df.DEVICE_CODE_GRANT


def test_a_dead_endpoint_is_reported_not_raised_raw():
    """A typo'd tenant must read as a sign-in failure, not a traceback."""
    provider = df.Provider(name="Dead",
                           device_endpoint="http://127.0.0.1:9/devicecode",
                           token_endpoint="http://127.0.0.1:9/token",
                           scope="s")
    with pytest.raises(df.DeviceFlowError, match="Could not reach"):
        df.request_code(provider, "cid")


# ---- sign_in and token selection ---------------------------------------

class _Creds:
    def __init__(self, password="", extra=None):
        self.password = password
        self.extra = extra or {}


def test_sign_in_shows_the_code_before_it_polls():
    """A user cannot approve a code they have not been shown."""
    order = []
    transport = _fake((200, {"device_code": "d", "user_code": "SHOWME",
                             "verification_uri": "u", "interval": 1}),
                      (200, {"access_token": "tok"}))
    original = transport

    def recording(url, data):
        order.append("poll" if "grant_type" in data else "request")
        return original(url, data)

    token = df.sign_in(df.microsoft(), "cid",
                       lambda code: order.append(f"shown:{code.user_code}"),
                       transport=recording, sleep=lambda _s: None)
    assert order == ["request", "shown:SHOWME", "poll"]
    assert token.access_token == "tok"


def test_a_pasted_token_is_used_as_given():
    """Someone who pastes a token is telling us to use THAT. Silently
    swapping it for a refreshed one makes a deliberate act look broken."""
    transport = _fake((200, {"access_token": "refreshed"}))
    creds = _Creds(password="pasted",
                   extra={"refresh_token": "r", "client_id": "c"})
    assert df.access_token_for(creds, df.microsoft(),
                               transport=transport) == "pasted"
    assert transport.calls == [], "it must not have refreshed anything"


def test_a_stored_refresh_token_renews_automatically(tmp_path):
    """The fix for "dead by lunchtime": no pasted token, so renew."""
    transport = _fake((200, {"access_token": "fresh", "expires_in": 3600}))
    creds = _Creds(extra={"refresh_token": "r", "client_id": "cid"})
    assert df.access_token_for(creds, df.microsoft(),
                               transport=transport) == "fresh"


def test_a_rotated_refresh_token_is_handed_back_for_storing():
    """Providers that rotate invalidate the old one, so failing to store the
    new one turns a renewable session into a single-use one."""
    stored = []
    transport = _fake((200, {"access_token": "fresh", "refresh_token": "next"}))
    creds = _Creds(extra={"refresh_token": "r", "client_id": "cid"})
    df.access_token_for(creds, df.microsoft(), transport=transport,
                        on_refresh=stored.append)
    assert stored and stored[0].refresh_token == "next"


def test_a_failing_persist_callback_does_not_lose_the_token():
    """The token is good even if we could not write it down."""
    def explode(_token):
        raise OSError("credential store is unavailable")

    transport = _fake((200, {"access_token": "fresh"}))
    creds = _Creds(extra={"refresh_token": "r", "client_id": "cid"})
    assert df.access_token_for(creds, df.microsoft(), transport=transport,
                              on_refresh=explode) == "fresh"


def test_nothing_to_go_on_returns_empty_rather_than_raising():
    """The caller turns this into its own "needs a token" message."""
    assert df.access_token_for(_Creds(), df.microsoft(),
                               transport=_fake()) == ""
    assert df.access_token_for(_Creds(extra={"refresh_token": "r"}),
                               df.microsoft(), transport=_fake()) == ""


# ---- the backends actually use it --------------------------------------

def test_both_token_backends_can_store_a_rotated_refresh_token():
    """Google Drive called self._store_refreshed while only SharePoint
    defined it. That is an AttributeError an HOUR into a session -- the first
    time a token needs renewing -- so nothing short of waiting an hour, or
    this test, would ever have seen it."""
    from modules.treesize.targets.base import Credentials
    from modules.treesize.targets.cloud import GoogleDriveTarget, SharePointTarget

    for target_class in (GoogleDriveTarget, SharePointTarget):
        target = target_class(Credentials())
        target._store_refreshed(df.Token("access", refresh_token="rotated"))
        assert target.credentials.extra["refresh_token"] == "rotated", (
            f"{target_class.__name__} cannot store a rotated refresh token")


def test_storing_ignores_a_response_that_omits_the_refresh_token():
    """Omitted means "keep the one you have", not "forget it"."""
    from modules.treesize.targets.base import Credentials
    from modules.treesize.targets.cloud import SharePointTarget

    target = SharePointTarget(Credentials(extra={"refresh_token": "keep"}))
    target._store_refreshed(df.Token("access"))
    assert target.credentials.extra["refresh_token"] == "keep"


def test_sharepoint_asks_for_a_sign_in_rather_than_a_token(monkeypatch):
    """The message has to point at the thing that now exists."""
    from modules.treesize.targets.base import Credentials, TargetError
    from modules.treesize.targets.cloud import SharePointTarget

    target = SharePointTarget(Credentials())
    with pytest.raises(TargetError, match="Sign in"):
        target.authenticate()


def test_sharepoint_uses_a_stored_refresh_token(monkeypatch):
    """End of "dead by lunchtime": no pasted token, but a stored refresh one."""
    from modules.treesize.targets.base import Credentials
    from modules.treesize.targets import cloud

    monkeypatch.setattr(cloud.device_flow, "refresh",
                        lambda *a, **k: df.Token("renewed",
                                                 refresh_token="rotated"))
    target = cloud.SharePointTarget(
        Credentials(extra={"refresh_token": "old", "client_id": "cid"}))
    target.authenticate()
    assert target._client is not None
    assert target._client.headers["Authorization"] == "Bearer renewed"
    assert target.credentials.extra["refresh_token"] == "rotated"
    target.close()
