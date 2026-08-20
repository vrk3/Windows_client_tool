"""The device-flow sign-in dialog (spec 6.2).

The end-to-end test drives it against the SAME real local RFC 8628 server the
protocol tests use, so the worker thread, the signals and the dialog's own
state machine are exercised over a genuine socket rather than a stub.
"""
import pytest
from PyQt6.QtWidgets import QDialog

from modules.treesize.targets import device_flow as df
from modules.treesize.ui.device_signin_dialog import DeviceSignInDialog

from .test_device_flow import rfc_server            # noqa: F401  (fixture)


def _pump(qapp, predicate, seconds=10.0):
    """Turn the event loop until `predicate`, or give up."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---- shape --------------------------------------------------------------

def test_sharepoint_asks_for_a_tenant(qapp):
    dialog = DeviceSignInDialog("sharepoint")
    assert dialog.tenant_edit.isVisibleTo(dialog)
    assert not dialog.secret_edit.isVisibleTo(dialog), (
        "a widget left out of the layout but not hidden still renders at 0,0")
    assert isinstance(dialog.provider(), df.Provider)
    assert dialog.provider().name == "Microsoft"


def test_google_asks_for_the_installed_app_secret(qapp):
    """Microsoft is a public client and has no secret; Google's token step
    requires one. Showing the wrong field invites a value that goes nowhere."""
    dialog = DeviceSignInDialog("gdrive")
    assert dialog.secret_edit.isVisibleTo(dialog)
    assert not dialog.tenant_edit.isVisibleTo(dialog)
    assert dialog.provider().name == "Google"


def test_the_tenant_reaches_the_provider(qapp):
    dialog = DeviceSignInDialog("sharepoint")
    dialog.tenant_edit.setText("contoso.onmicrosoft.com")
    assert "contoso.onmicrosoft.com" in dialog.provider().device_endpoint


# ---- refusals -----------------------------------------------------------

def test_signing_in_without_a_client_id_says_so_and_starts_nothing(qapp):
    dialog = DeviceSignInDialog("sharepoint")
    dialog.start()
    assert "client ID" in dialog.status.text()
    assert dialog._worker is None, "it must not have started a flow"


def test_a_failure_re_enables_the_button(qapp):
    """A typo'd tenant must be correctable without reopening the dialog."""
    def failing_flow(*_a, **_k):
        raise df.DeviceFlowError("Microsoft sign-in failed: no such app")

    dialog = DeviceSignInDialog("sharepoint", flow=failing_flow)
    dialog.client_id_edit.setText("cid")
    dialog.start()
    assert _pump(qapp, lambda: dialog.sign_in_button.isEnabled())
    assert "no such app" in dialog.status.text()


def test_the_code_is_shown_as_soon_as_it_arrives(qapp):
    """A user cannot approve a code they have not been shown, so this must
    appear while the poll is still running, not after it."""
    code = df.DeviceCode("dev", "SHOW-ME", "https://example.test/device")
    started = []

    def slow_flow(provider, client_id, on_code, **kwargs):
        on_code(code)
        started.append(True)
        while not kwargs["should_cancel"]():
            import time
            time.sleep(0.01)
        raise df.DeviceFlowError("Sign-in was cancelled.")

    dialog = DeviceSignInDialog("sharepoint", flow=slow_flow)
    dialog.client_id_edit.setText("cid")
    dialog.start()
    try:
        assert _pump(qapp, lambda: "SHOW-ME" in dialog.status.text())
        assert dialog.copy_button.isEnabled()
    finally:
        dialog.reject()


def test_cancelling_stops_the_worker(qapp):
    """A user who gives up must not leave a thread polling until the code
    expires fifteen minutes later."""
    def slow_flow(provider, client_id, on_code, **kwargs):
        on_code(df.DeviceCode("dev", "CODE", "u"))
        while not kwargs["should_cancel"]():
            import time
            time.sleep(0.01)
        raise df.DeviceFlowError("Sign-in was cancelled.")

    dialog = DeviceSignInDialog("sharepoint", flow=slow_flow)
    dialog.client_id_edit.setText("cid")
    dialog.start()
    assert _pump(qapp, lambda: dialog._worker is not None
                 and dialog._worker.isRunning())
    worker = dialog._worker
    dialog.reject()
    assert not worker.isRunning(), "the worker outlived the dialog"


# ---- against the real local RFC 8628 server ----------------------------

def test_the_whole_dialog_against_a_real_server(qapp, rfc_server):   # noqa: F811
    """Worker thread, signals and dialog state, over a genuine socket."""
    server, base = rfc_server
    provider = df.Provider(name="Local",
                           device_endpoint=f"{base}/devicecode",
                           token_endpoint=f"{base}/token", scope="s")

    dialog = DeviceSignInDialog("sharepoint")
    dialog.provider = lambda: provider               # point it at the fake
    dialog.client_id_edit.setText("cid")
    dialog.start()

    assert _pump(qapp, lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.token is not None
    assert dialog.token.access_token == "REAL-TOKEN"
    assert dialog.token.refresh_token == "REAL-REFRESH"
    assert dialog.client_id == "cid"
    assert "USER-XYZ" in dialog.status.text(), "the code was never shown"


# ---- the remote-target dialog wiring -----------------------------------

def _remote(qapp, backend_id):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    class _NoStore:
        def load(self, *_a, **_k):
            return None

        def save(self, *_a, **_k):
            pass

        def delete(self, *_a, **_k):
            pass

        def forget(self, *_a, **_k):
            pass

    dialog = RemoteTargetDialog(credential_store=_NoStore())
    index = dialog.backend.findData(backend_id)
    if index < 0:
        pytest.skip(f"{backend_id} is not registered")
    dialog.backend.setCurrentIndex(index)
    # setCurrentIndex fires nothing when the index is already current, and
    # the per-backend form is what shows or hides the button.
    dialog._apply_form()
    return dialog


@pytest.mark.parametrize("backend_id", ["sharepoint", "gdrive"])
def test_the_sign_in_button_shows_for_device_flow_backends(qapp, backend_id):
    dialog = _remote(qapp, backend_id)
    assert dialog.sign_in_button.isVisibleTo(dialog)


def test_the_sign_in_button_hides_for_everything_else(qapp):
    dialog = _remote(qapp, "ssh")
    assert not dialog.sign_in_button.isVisibleTo(dialog), (
        "SSH has no device flow; offering one invites a dead end")


def test_connecting_without_signing_in_is_not_an_error(qapp):
    """Every backend but two never signs in. _signed_in has to exist."""
    dialog = _remote(qapp, "ssh")
    dialog.host.setText("example.test")
    dialog.username.setText("someone")
    dialog.password.setText("secret")
    target, why = dialog.selected()
    assert target is not None, why


def test_a_completed_sign_in_travels_in_extra_not_in_password(qapp,
                                                              monkeypatch):
    """access_token_for deliberately PREFERS a pasted password, so putting
    the signed-in refresh token there too would make the two indistinguishable."""
    dialog = _remote(qapp, "sharepoint")
    dialog._signed_in = {"client_id": "cid", "refresh_token": "r",
                         "tenant": "contoso"}
    dialog.username.setText("b!drive")
    dialog.password.setText("access-token")
    target, why = dialog.selected()
    assert target is not None, why
    assert target.credentials.extra["refresh_token"] == "r"
    assert target.credentials.extra["client_id"] == "cid"
    assert target.credentials.password == "access-token"
