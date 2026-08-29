r"""SMBv1 should not cost a full DISM enumeration to read.

Measured on this machine: Firewall & Network reads in 8.8s ELEVATED, and 7.9s
of it is `smbv1` alone. Nothing is wrong with that reader -- it asks the
shared `optional_features` snapshot, and building that snapshot means
`Get-WindowsOptionalFeature -Online`, a DISM enumeration of every feature on
the box. One control on one tab was paying for a list that only the Windows
Features tab actually needs.

The cheaper source, measured unelevated:

    Get-SmbServerConfiguration          1.02s   EnableSMB1Protocol = False
    Get-WindowsOptionalFeature (one)    0.12s   refused, needs elevation
    HKLM\...\LanmanServer\Parameters    0.07s   no SMB1 value at all
    HKLM\...\Services\mrxsmb10          0.04s   key absent (client not installed)

and it agrees with the authoritative reading: the elevated catalog run
recorded `smbv1 = False`, and Get-SmbServerConfiguration says False too.

So the snapshot stays authoritative when it is ALREADY built -- free, and it
knows about the client half as well -- and otherwise the cheap query answers
instead of building a list nobody asked for. It also means smbv1 stops
answering "Unknown" unelevated, where it used to refuse outright.
"""
import pytest

from modules.security_dashboard import security_reader, snapshots


@pytest.fixture(autouse=True)
def clear_snapshot_cache():
    snapshots._cache.clear()
    yield
    snapshots._cache.clear()


@pytest.fixture
def no_dism(monkeypatch):
    """Building the optional_features snapshot is the 7.9s. Forbid it."""
    def explode():
        raise AssertionError(
            "it enumerated every optional feature to read one control")

    monkeypatch.setattr(snapshots, "optional_features", explode)
    return explode


@pytest.fixture
def smb_config(monkeypatch):
    """Stand in for Get-SmbServerConfiguration, recording that it ran."""
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        if "SmbServerConfiguration" in cmd:
            return 0, '{"EnableSMB1Protocol":false}', ""
        return 1, "", "unexpected command"

    monkeypatch.setattr(security_reader, "_ps", fake_ps)
    return calls


def test_smbv1_does_not_build_the_feature_list_to_answer(no_dism, smb_config):
    result = security_reader.check_smbv1()

    assert any("SmbServerConfiguration" in cmd for cmd in smb_config), (
        "it did not use the cheap source")
    assert result["available"] is True
    assert result["status"] == "Disabled"
    assert result["enabled"] is False


def test_an_smbv1_that_is_on_is_still_reported_red(no_dism, monkeypatch):
    def fake_ps(cmd, timeout=30):
        return 0, '{"EnableSMB1Protocol":true}', ""

    monkeypatch.setattr(security_reader, "_ps", fake_ps)
    result = security_reader.check_smbv1()

    assert result["status"] == "Enabled"
    assert result["color"] == "red"
    assert result["enabled"] is True


def test_the_already_built_snapshot_still_wins(monkeypatch, smb_config):
    """When the Windows Features tab has already paid for the list, it is the
    better answer -- it covers the client half, not just the server."""
    snapshots._cache["optional_features"] = {"smb1protocol": "Enabled"}

    result = security_reader.check_smbv1()

    assert result["status"] == "Enabled"
    assert smb_config == [], (
        "it asked the cheap source while the authoritative one was in hand")


@pytest.fixture
def refused_feature_list(monkeypatch):
    """The realistic fallback: unelevated, the feature list refuses too.

    It refuses in 0.12s -- it is only BUILDING the list that costs 7.9s -- so
    falling back to it is right; what matters is that two refusals do not add
    up to a verdict.
    """
    monkeypatch.setattr(snapshots, "optional_features", lambda: {})
    monkeypatch.setattr(
        snapshots, "unavailable",
        lambda name: "Get-WindowsOptionalFeature requires elevation")


def test_a_refused_cheap_read_is_not_a_disabled_verdict(refused_feature_list,
                                                        monkeypatch):
    """The rule this whole module runs on: a refusal is not an answer, and
    'Disabled' is the answer that would let someone stop worrying."""
    def refuse(cmd, timeout=30):
        return 1, "", "Access is denied."

    monkeypatch.setattr(security_reader, "_ps", refuse)
    result = security_reader.check_smbv1()

    assert result["available"] is False
    assert result["status"] != "Disabled"


def test_unparseable_output_is_not_a_disabled_verdict(refused_feature_list,
                                                      monkeypatch):
    """rc 0 with something that is not the JSON asked for. Windows cmdlets do
    this -- Get-SpeculationControlSettings prints a page of prose first."""
    def chatty(cmd, timeout=30):
        return 0, "Everything is fine, honestly", ""

    monkeypatch.setattr(security_reader, "_ps", chatty)
    result = security_reader.check_smbv1()

    assert result["available"] is False
    assert result["status"] != "Disabled"


def test_a_reader_that_threw_says_it_has_no_reading(no_dism, monkeypatch):
    """The `except Exception` path returned a status string and no
    `available` flag -- the same shape that let a refused BitLocker read be
    published as "not encrypted"."""
    def refuse(cmd, timeout=30):
        return 1, "", "Access is denied."

    monkeypatch.setattr(security_reader, "_ps", refuse)
    result = security_reader.check_smbv1()      # no_dism makes the fallback throw

    assert result["available"] is False
    assert result["status"] != "Disabled"


# --- telnet_client is the other half of the same bill ------------------------
#
# Moving smbv1 off the feature list did not make Firewall & Network fast: the
# 8.10s simply moved to telnet_client, which is on the same tab and also reads
# the list. The Telnet Client feature IS telnet.exe in System32 -- that is
# what installing it puts there -- so its presence answers in 0.039s,
# unelevated, and agrees with the authoritative reading (the elevated catalog
# run recorded telnet_client = False, and telnet.exe is not on this machine).

def test_telnet_does_not_build_the_feature_list_to_answer(no_dism, monkeypatch):
    monkeypatch.setattr(security_reader.os.path, "exists", lambda p: False)

    result = security_reader.check_telnet()

    assert result["available"] is True
    assert result["enabled"] is False
    assert result["status"] == "Not Installed"


def test_a_present_telnet_binary_is_reported_red(no_dism, monkeypatch):
    monkeypatch.setattr(security_reader.os.path, "exists",
                        lambda p: p.lower().endswith("telnet.exe"))

    result = security_reader.check_telnet()

    assert result["enabled"] is True
    assert result["color"] == "red"


def test_the_already_built_feature_list_still_wins_for_telnet(monkeypatch):
    """The list knows Enabled from Disabled-but-staged; the binary does not."""
    snapshots._cache["optional_features"] = {"telnetclient": "Disabled"}
    monkeypatch.setattr(security_reader.os.path, "exists",
                        lambda p: pytest.fail("it went to disk with the list "
                                              "already in hand"))

    result = security_reader.check_telnet()

    assert result["status"] == "Disabled"
    assert result["enabled"] is False


# --- a cached REFUSAL is not a snapshot in hand -----------------------------
#
# Found by measuring, not by testing: unelevated, the prefetch asks for the
# feature list, is refused, and the refusal is cached like any other answer.
# Both readers then saw the key present, concluded "somebody already paid for
# the list" and went back to it -- so Firewall & Network's unreadable count
# climbed from 1 to 2 and the cheap sources stopped being used at the exact
# moment they were most useful. "Already built" has to mean "usable".

def test_a_cached_refusal_does_not_count_as_having_the_list(monkeypatch):
    snapshots._cache["optional_features"] = {}          # what a refusal caches
    monkeypatch.setattr(snapshots, "unavailable",
                        lambda name: "requires elevation")

    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"EnableSMB1Protocol":false}', ""

    monkeypatch.setattr(security_reader, "_ps", fake_ps)
    result = security_reader.check_smbv1()

    assert any("SmbServerConfiguration" in c for c in calls), (
        "a refused snapshot was treated as an answer")
    assert result["available"] is True
    assert result["status"] == "Disabled"


def test_a_cached_refusal_does_not_stop_telnet_reading_the_disk(monkeypatch):
    snapshots._cache["optional_features"] = {}
    monkeypatch.setattr(snapshots, "unavailable",
                        lambda name: "requires elevation")
    monkeypatch.setattr(security_reader.os.path, "exists", lambda p: False)

    result = security_reader.check_telnet()

    assert result["available"] is True
    assert result["status"] == "Not Installed"
