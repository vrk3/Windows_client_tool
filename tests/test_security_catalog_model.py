"""The catalog is one table; everything else is a filter over it."""
import pytest

from modules.security_dashboard.catalog import load_catalog
from modules.security_dashboard.catalog.model import (
    Category, Risk, SecurityControl,
)


def _control(**over):
    base = dict(id="x", title="X", category=Category.DEFENDER,
                description="d", why_it_matters="w", reader=lambda: {})
    base.update(over)
    return SecurityControl(**base)


def test_a_control_with_no_writer_must_say_why_it_is_read_only():
    with pytest.raises(ValueError, match="read_only_reason"):
        _control()


def test_a_control_with_a_writer_needs_no_reason():
    c = _control(on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                            "data": 1, "kind": "DWORD"},))
    assert c.writable


def test_a_read_only_control_is_not_writable():
    assert not _control(read_only_reason="TPM presence is hardware").writable


def test_reading_defaults_to_the_enabled_key():
    c = _control(read_only_reason="r", reader=lambda: {"enabled": True})
    assert c.read() is True


def test_a_reader_that_could_not_look_reads_as_none_not_as_false():
    """A refused read is not an unset value."""
    c = _control(read_only_reason="r",
                 reader=lambda: {"available": False, "status": "Unknown"})
    assert c.read() is None


def test_a_control_may_supply_its_own_value_extractor():
    c = _control(read_only_reason="r",
                 reader=lambda: {"available": True, "level": 3},
                 read_value=lambda d: d["level"])
    assert c.read() == 3


def test_a_reader_with_no_enabled_key_reads_as_none():
    """A dict that doesn't even mention 'enabled' is an unset read, not False."""
    c = _control(read_only_reason="r", reader=lambda: {"status": "n/a"})
    assert c.read() is None


def test_a_reader_that_raises_reads_as_none_not_as_a_verdict(caplog):
    """A refused read must never surface as False; it must be logged, not
    swallowed."""
    def _boom():
        raise RuntimeError("registry access denied")

    c = _control(read_only_reason="r", reader=_boom)
    with caplog.at_level("WARNING"):
        assert c.read() is None
    assert any("reader raised" in rec.message for rec in caplog.records)


def test_ids_are_unique_across_the_whole_catalog():
    catalog = load_catalog()
    assert len(catalog) == len({c.id for c in catalog.values()})
