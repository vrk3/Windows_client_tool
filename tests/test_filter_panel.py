from ui.filter_panel import FilterPanel


def test_build_query_defaults():
    panel = FilterPanel()
    query = panel.build_query("test search")
    assert query.text == "test search"
    assert "Error" in query.types
    assert "Warning" in query.types
    assert query.regex_enabled is False


def test_build_query_with_regex():
    panel = FilterPanel()
    query = panel.build_query("error.*disk", regex=True)
    assert query.text == "error.*disk"
    assert query.regex_enabled is True


def test_build_query_sources_default_checked():
    panel = FilterPanel()
    query = panel.build_query("")
    assert "EventViewer" in query.sources
    assert "CBS" in query.sources
