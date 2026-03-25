from ui.filter_panel import FilterPanel


def test_build_query_defaults():
    panel = FilterPanel()
    query = panel.build_query("test search")
    assert query.text == "test search"
    # All types checked by default → empty list means "no type filter, show all"
    assert query.types == []
    assert query.regex_enabled is False


def test_build_query_with_regex():
    panel = FilterPanel()
    query = panel.build_query("error.*disk", regex=True)
    assert query.text == "error.*disk"
    assert query.regex_enabled is True


def test_build_query_sources_default_checked():
    panel = FilterPanel()
    query = panel.build_query("")
    # All sources checked by default → empty list means "no source filter, search all"
    assert query.sources == []
