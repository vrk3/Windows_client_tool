"""The Startup apps scan sources, as Qt-free engine reads.

The dashboard's Startup tab is a widget around `startup_reader.py`; this pins
that the reader is real, read-only machinery (registry Run keys + the Startup
folder) and stays Qt-free the way every procengine module must. Scheduled
tasks are exercised through the widget's settle test instead, where COM runs
on a COMWorker thread.
"""
import inspect

from modules.startup_manager.startup_reader import (
    StartupEntry,
    get_registry_entries,
    get_startup_folder_entries,
)


def test_registry_scan_returns_a_list():
    entries = get_registry_entries()
    assert isinstance(entries, list)
    assert all(isinstance(entry, StartupEntry) for entry in entries)


def test_startup_folder_scan_returns_a_list():
    entries = get_startup_folder_entries()
    assert isinstance(entries, list)
    assert all(isinstance(entry, StartupEntry) for entry in entries)


def test_rows_carry_the_fields_the_tab_shows():
    entries = get_registry_entries()
    for entry in entries:
        assert isinstance(entry.name, str) and entry.name
        assert isinstance(entry.enabled, bool)
        assert entry.source == "registry_run"


def test_the_scanner_does_not_import_qt():
    import modules.startup_manager.startup_reader as startup_reader

    source = inspect.getsource(startup_reader)
    assert "PyQt6" not in source
