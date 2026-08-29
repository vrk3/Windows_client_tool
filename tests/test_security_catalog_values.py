"""A reader that answered must not read as "could not look".

`SecurityControl.read()` returns `result.get("enabled")` when the entry has no
`read_value`. A reader that reports its finding as `status` and never sets
`enabled` therefore reads as None -- which this project treats as "the machine
could not be asked" -- however well it ran.

Found by driving the real catalog against this machine (Task 18): FIFTEEN
controls read None while their reader plainly had an answer. Thirteen were
read-only and rendered "Unknown" on every machine forever, showing nothing
where the reader had "Mitigated", "Private", "FullLanguage" or an engine
version. The fourteenth was WRITABLE.
"""
import pytest

from modules.security_dashboard.catalog import load_catalog
from modules.security_dashboard.catalog.model import (
    Category, SecurityControl)

#: Every control whose reader answers with `status` rather than `enabled`.
STATUS_VALUED = (
    "crash_dump_encryption", "ntp_sync", "windows_update_policy",
    "network_profile", "ps_constrained_language", "defender_engine_version",
    "cve_downfall_gds", "cve_retbleed", "cve_rfds", "cve_srbds",
    "cve_tsx_async_abort", "cve_zenbleed", "smartscreen",
)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.mark.parametrize("control_id", STATUS_VALUED)
def test_a_status_only_reader_has_a_read_value(catalog, control_id):
    assert catalog[control_id].read_value is not None, (
        f"{control_id}'s reader reports a status and no `enabled`, so without "
        "a read_value it reads None -- 'could not look' -- forever")


def _control(reader, **over):
    base = dict(id="x", title="x", category=Category.SERVICES, description="d",
                why_it_matters="w", reader=reader,
                read_only_reason="informational")
    base.update(over)
    return SecurityControl(**base)


def test_a_status_only_reader_yields_its_status(catalog):
    control = catalog["cve_retbleed"]
    value = control.read_value({"status": "Mitigated", "color": "green"})
    assert value == "Mitigated"


def test_a_reader_that_does_give_a_boolean_still_wins(catalog):
    """The six microcode CVEs share one helper and not all of them are
    status-only: where a reader answers True/False, that is the value."""
    control = catalog["cve_retbleed"]
    assert control.read_value({"status": "Mitigated", "enabled": True}) is True
    assert control.read_value({"status": "Vulnerable", "enabled": False}) is False


def test_smartscreen_reads_the_policy_it_writes(catalog):
    """Its steps write HKLM\\...\\System\\EnableSmartScreen, and the reader
    answers "Not Configured" when that value is absent -- with no `enabled` at
    all. read() was None, so staging recorded no prior value and the verify
    pass compared None against True: APPLIED_UNVERIFIED however well the write
    landed. A writable control that could never be verified."""
    read_value = catalog["smartscreen"].read_value
    assert read_value({"status": "Not Configured"}) is False
    assert read_value({"status": "Enabled"}) is True
    assert read_value({"status": "Enabled", "enabled": True}) is True
    assert read_value({"status": "Disabled", "enabled": False}) is False


def test_smartscreen_says_what_it_actually_covers(catalog):
    """Titled just "SmartScreen" it claimed more than it reads: Windows' own
    default lives elsewhere and this control neither reads nor writes it."""
    control = catalog["smartscreen"]
    assert "policy" in control.title.lower()
    assert "not configured" in control.description.lower()


def test_read_falls_back_to_none_when_a_reader_says_it_could_not_look():
    """The fallback must not paper over a refusal."""
    control = _control(lambda: {"available": False, "status": "Requires admin"},
                       read_value=lambda d: d.get("status"))
    assert control.read() is None


def test_every_writable_control_can_produce_a_comparable_value(catalog):
    """A writable control whose read() cannot answer is a control the apply
    path can never verify, whatever the machine does."""
    for control_id, control in catalog.items():
        if not control.writable or control.desired is None:
            continue
        assert control.read_value is not None or control.desired is not None, (
            control_id)
