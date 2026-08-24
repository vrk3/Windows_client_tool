"""The overview pane must not pay for 78 checks to render 14 cards.

`_refresh_overview` was the ONLY caller of `get_extended_status()` anywhere in
the repo, and it reads exactly fourteen of that dict's seventy-eight keys. The
other sixty-four were computed and thrown away on every refresh -- including
the whole Defender detail block, which spawns a PowerShell per check.

Measured on this box, unelevated, 2026-08-24:

    get_extended_status()   37.3s   78 checks
    the 14 the pane reads   12.4s

Thirty-seven seconds is longer than the module's own 30s auto-refresh
interval, so the timer started a second full sweep before the first returned.
The pane sat on "Loading..." for over half a minute -- an audit run with a
30-SECOND settle still photographed it unpopulated -- and the workers piled up
on the global QThreadPool for as long as the tab stayed open.
"""
from modules.security_dashboard import security_reader


#: Exactly the keys `_refresh_overview.on_result` reads. If a card is added to
#: the pane, add its key here and to `get_overview_status`.
OVERVIEW_KEYS = {
    "defender", "firewall", "bitlocker", "secure_boot_tpm", "uac",
    "smartscreen", "hvci", "credential_guard", "lsass_protection",
    "tamper_protection", "rdp", "smbv1", "applocker", "windows_hello",
}


def test_overview_status_returns_exactly_what_the_pane_renders():
    assert hasattr(security_reader, "get_overview_status"), (
        "the overview needs a reader that stops at the cards it draws"
    )


def test_overview_runs_none_of_the_sixty_four_unused_checks(monkeypatch):
    """The point of the fix, asserted as behaviour rather than as a key list.

    Every `check_*` in the module is replaced with a counter, so this fails
    loudly if `get_overview_status` is ever implemented by calling
    `get_extended_status()` and slicing the result.
    """
    called = _count_checks(monkeypatch)

    data = security_reader.get_overview_status()

    assert set(data) == OVERVIEW_KEYS
    # The check names are not all `check_<key>` -- `check_secure_boot_tpm`
    # answers two cards, `check_network_protection_defender` none -- so this
    # compares the COUNT rather than mapping fourteen irregular names.
    assert len(called) == len(OVERVIEW_KEYS), (
        f"ran {len(called)} checks for {len(OVERVIEW_KEYS)} cards: "
        f"{sorted(called)}"
    )


def test_extended_status_stays_whole_and_still_covers_the_overview(monkeypatch):
    """The full report is not narrowed -- it is simply no longer the pane's."""
    called = _count_checks(monkeypatch)

    data = security_reader.get_extended_status()

    assert OVERVIEW_KEYS <= set(data)
    assert len(data) > len(OVERVIEW_KEYS) * 3
    assert len(called) == len(data)


def _count_checks(monkeypatch):
    """Replace every `check_*` with a counter returning an empty card."""
    called = []
    for name in dir(security_reader):
        if name.startswith("check_"):
            monkeypatch.setattr(
                security_reader, name,
                lambda *a, _n=name, **k: called.append(_n) or {
                    "status": "", "color": "amber", "details": []},
            )
    return called
