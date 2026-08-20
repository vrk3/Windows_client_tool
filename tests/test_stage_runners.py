from modules.updates.stage_runners import STAGE_LABELS, STAGE_RUNNERS, normalize_stage_data


def test_stage_runners_has_entry_for_every_label():
    assert set(STAGE_RUNNERS.keys()) == set(STAGE_LABELS.keys())
    assert set(STAGE_RUNNERS.keys()) == {"wu", "winget", "store", "cleanup", "dism"}


def test_normalize_stage_data_empty_input():
    result = normalize_stage_data({})
    assert result == {
        "wu_results": [],
        "wu_installed": 0,
        "winget_results": [],
        "store_triggered": 0,
        "cleanup_freed": 0,
        "cleanup_deleted": 0,
        "dism_output": None,
    }


def test_normalize_stage_data_flattens_all_stages():
    data = {
        "wu": {"results": [{"kb": "KB1", "success": True}], "installed_count": 1},
        "winget": {"results": [{"name": "Foo", "confirmed": True}]},
        "store": {"triggered": 2},
        "cleanup": {"freed": 12345, "deleted": 7},
        "dism": {"output": "some dism text"},
    }
    result = normalize_stage_data(data)
    assert result["wu_results"] == [{"kb": "KB1", "success": True}]
    assert result["wu_installed"] == 1
    assert result["winget_results"] == [{"name": "Foo", "confirmed": True}]
    assert result["store_triggered"] == 2
    assert result["cleanup_freed"] == 12345
    assert result["cleanup_deleted"] == 7
    assert result["dism_output"] == "some dism text"


def test_normalize_stage_data_tolerates_none_stage_values():
    # A stage that raised and was recorded as {} shouldn't blow up normalization.
    data = {"wu": {}, "winget": None, "cleanup": {}}
    result = normalize_stage_data(data)
    assert result["wu_results"] == []
    assert result["winget_results"] == []
    assert result["cleanup_freed"] == 0
