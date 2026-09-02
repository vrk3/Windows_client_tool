"""The Log Viewer's construction is readable in pieces.

`LogViewerWidget.__init__` ran 480 lines and the class is 105 methods over
2,136 lines — the largest single unit in the codebase, and nothing about it
could be read or tested a piece at a time.

The module already has the right instinct: `cmtrace_parser.py` and
`log_reader.py` are Qt-free and separately tested. `view_state.py` extends
that to the pane's own state.
"""
import ast
import pathlib

import pytest

MODULE = (pathlib.Path(__file__).resolve().parent.parent
          / "src" / "modules" / "log_viewer" / "log_viewer_module.py")


def _function_lengths():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return {
        node.name: node.end_lineno - node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def test_no_function_in_the_log_viewer_runs_past_a_screenful():
    """120 lines is about two screens. __init__ was 480."""
    long = {name: n for name, n in _function_lengths().items() if n > 120}
    assert long == {}, f"still long: {long}"


def test_construction_is_split_into_named_builders():
    names = set(_function_lengths())
    for builder in ("_build_toolbar", "_build_find_row", "_build_range_row",
                    "_build_markers", "_build_table", "_build_status",
                    "_wire_signals"):
        assert builder in names, f"{builder} missing"


def test_the_view_state_imports_no_qt():
    """Same rule cmtrace_parser and log_reader keep, and the reason ~450
    engine tests run with no display.

    Checked on the IMPORTS, not on the text: the module talks about Qt in
    its own docstring, and a substring search cannot tell prose from a
    dependency.
    """
    tree = ast.parse((MODULE.parent / "view_state.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PyQt6" not in imported, f"view_state imports {sorted(imported)}"


def test_the_state_round_trips():
    from modules.log_viewer.view_state import LogViewState

    state = LogViewState()
    state.filter_text = "error"
    state.following = True
    state.hidden_columns = ["Thread"]
    state.range_active = True

    restored = LogViewState.from_dict(state.to_dict())

    assert restored.filter_text == "error"
    assert restored.following is True
    assert restored.hidden_columns == ["Thread"]
    assert restored.range_active is True


def test_an_unknown_key_does_not_cost_the_reader_their_other_settings():
    """This is read back from a config an older or newer build wrote."""
    from modules.log_viewer.view_state import LogViewState

    restored = LogViewState.from_dict(
        {"filter_text": "hresult", "a_key_from_the_future": 7})

    assert restored.filter_text == "hresult"


def test_every_severity_hidden_falls_back_rather_than_showing_nothing():
    """An empty pane looks like an empty log, which is the one thing this
    module exists never to imply."""
    from modules.log_viewer.view_state import LogViewState, KNOWN_SEVERITIES

    restored = LogViewState.from_dict({"severities": ["Nonsense"]})

    assert restored.severities == list(KNOWN_SEVERITIES)


@pytest.mark.parametrize("field,value", [
    ("filter_text", "x"),
    ("exclude_text", "x"),
    ("thread", "4180"),
    ("component", "CBS"),
    ("range_active", True),
])
def test_is_filtering_notices_each_way_of_hiding_rows(field, value):
    from modules.log_viewer.view_state import LogViewState

    state = LogViewState()
    assert state.is_filtering() is False

    setattr(state, field, value)
    assert state.is_filtering() is True, f"{field} hides rows and must count"


def test_a_narrowed_severity_set_counts_as_filtering():
    from modules.log_viewer.view_state import LogViewState

    state = LogViewState(severities=["Error"])
    assert state.is_filtering() is True
