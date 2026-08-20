import json
import os
import tempfile

import pytest

from modules.updates.history_writer import MAX_ENTRIES, append_run, load_history


@pytest.fixture
def app_data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_load_history_empty_when_no_file(app_data_dir):
    assert load_history(app_data_dir) == []


def test_append_run_creates_entry(app_data_dir):
    append_run(app_data_dir, freed_bytes=1024, updates_installed=3, winget_count=2)
    history = load_history(app_data_dir)
    assert len(history) == 1
    assert history[0]["freed"] == 1024
    assert history[0]["updates"] == 3
    assert history[0]["wg"] == 2
    assert "ts" in history[0]


def test_append_run_accumulates(app_data_dir):
    append_run(app_data_dir, freed_bytes=100)
    append_run(app_data_dir, freed_bytes=200)
    history = load_history(app_data_dir)
    assert len(history) == 2
    assert [e["freed"] for e in history] == [100, 200]


def test_append_run_caps_at_max_entries(app_data_dir):
    for i in range(MAX_ENTRIES + 10):
        append_run(app_data_dir, freed_bytes=i)
    history = load_history(app_data_dir)
    assert len(history) == MAX_ENTRIES
    # Oldest entries should have been dropped, newest kept.
    assert history[-1]["freed"] == MAX_ENTRIES + 9


def test_history_file_is_valid_json_on_disk(app_data_dir):
    append_run(app_data_dir, freed_bytes=42)
    path = os.path.join(app_data_dir, "updates", "history.json")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert data[0]["freed"] == 42


def test_load_history_recovers_from_corrupt_file(app_data_dir):
    updates_dir = os.path.join(app_data_dir, "updates")
    os.makedirs(updates_dir, exist_ok=True)
    with open(os.path.join(updates_dir, "history.json"), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert load_history(app_data_dir) == []
