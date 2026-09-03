"""Saving an investigation so you can come back to it.

Sources, every filter axis, the time range, folding and the column choice, in
one small file. Coming back tomorrow currently means rebuilding it from
memory.

Three things this has to get right, and each has its own test: it must carry
EVERY axis (one missing and the view you reopen is not the one you saved), it
must say which logs are gone rather than opening a smaller view silently, and
a file from a newer version must be refused outright rather than half
applied.
"""
import json

import pytest

from modules.log_viewer.views import VERSION, View, load_view, save_view


def _view(**overrides):
    fields = dict(
        sources=[r"C:\Windows\Logs\CBS\CBS.log"],
        needle="hresult", exclude="detectParent", regex=True,
        levels=["Error", "Warning"], components=["CBS", "CSI"],
        thread="1234", log="CBS.log",
        time_from="2026-08-27 10:00:00", time_to="2026-08-27 11:00:00",
        fold=False, hidden_columns=["Thread"],
    )
    fields.update(overrides)
    return View(**fields)


def test_a_view_round_trips_every_axis(tmp_path):
    path = str(tmp_path / "view.json")
    original = _view()

    save_view(path, original)
    loaded, problem = load_view(path)

    assert not problem
    assert loaded == original


def test_every_field_is_actually_written(tmp_path):
    """A field that quietly fails to serialise would come back as a default
    and the reopened view would not be the saved one."""
    path = str(tmp_path / "view.json")
    save_view(path, _view())

    with open(path, encoding="utf-8") as handle:
        stored = json.load(handle)

    for name in ("sources", "needle", "exclude", "regex", "levels",
                 "components", "thread", "log", "time_from", "time_to",
                 "fold", "hidden_columns"):
        assert name in stored, f"{name} was not saved"


def test_a_view_records_the_version_it_was_written_by(tmp_path):
    path = str(tmp_path / "view.json")
    save_view(path, _view())
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["version"] == VERSION


def test_a_view_from_a_newer_version_is_refused_outright(tmp_path):
    """Half-applying a file we do not understand gives a view that is
    neither the saved one nor the current one, and blames neither."""
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": VERSION + 1, "needle": "x"}),
                    encoding="utf-8")

    loaded, problem = load_view(str(path))

    assert loaded is None
    assert "newer" in problem.lower()


def test_a_file_that_is_not_a_view_says_so(tmp_path):
    path = tmp_path / "junk.json"
    path.write_text("not json at all", encoding="utf-8")
    loaded, problem = load_view(str(path))
    assert loaded is None and problem


def test_a_missing_file_says_so(tmp_path):
    loaded, problem = load_view(str(tmp_path / "nope.json"))
    assert loaded is None and problem


def test_a_view_missing_optional_fields_still_loads(tmp_path):
    """Written by an older version: absent axes take their defaults rather
    than refusing the whole file."""
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": VERSION, "needle": "x"}),
                    encoding="utf-8")

    loaded, problem = load_view(str(path))

    assert not problem
    assert loaded.needle == "x"
    assert loaded.sources == []


# ---- which logs are missing ---------------------------------------------

def test_a_view_reports_the_sources_that_are_gone(tmp_path):
    here = tmp_path / "present.log"
    here.write_text("x", encoding="utf-8")
    view = _view(sources=[str(here), str(tmp_path / "gone.log")])

    assert view.missing() == [str(tmp_path / "gone.log")]


def test_a_view_whose_logs_are_all_present_reports_nothing_missing(tmp_path):
    here = tmp_path / "present.log"
    here.write_text("x", encoding="utf-8")
    assert _view(sources=[str(here)]).missing() == []


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[alpha broke]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="3" thread="7" file="a.cpp:1">\n'
    '<![LOG[beta fine]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CSI" context="" type="1" thread="8" file="a.cpp:2">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_the_pane_captures_what_is_on_screen(viewer):
    viewer.filter_box.setText("broke")
    viewer.exclude_box.setText("noise")
    viewer.set_components({"CBS"})
    viewer.fold.setChecked(False)
    viewer.set_column_hidden("Thread", True)

    view = viewer.current_view()

    assert view.needle == "broke"
    assert view.exclude == "noise"
    assert view.components == ["CBS"]
    assert view.fold is False
    assert view.hidden_columns == ["Thread"]
    assert view.sources == viewer._paths


def test_applying_a_view_puts_the_pane_back(viewer, tmp_path):
    viewer.filter_box.setText("broke")
    viewer.set_components({"CBS"})
    viewer.fold.setChecked(False)
    saved = viewer.current_view()

    viewer.filter_box.setText("")
    viewer.set_components(set())
    viewer.fold.setChecked(True)

    viewer.apply_view(saved)

    assert viewer.filter_box.text() == "broke"
    assert viewer.selected_components() == {"CBS"}
    assert viewer.fold.isChecked() is False


def test_applying_a_view_reopens_its_logs(viewer, tmp_path):
    saved = viewer.current_view()
    other = tmp_path / "second.log"
    other.write_text(CMTRACE, encoding="utf-8")
    viewer.open(str(other))
    assert viewer._paths == [str(other)]

    viewer.apply_view(saved)

    assert viewer._paths == saved.sources


def test_a_view_whose_logs_are_gone_names_them(viewer, tmp_path):
    from modules.log_viewer.views import View

    viewer.apply_view(View(sources=[str(tmp_path / "vanished.log")]))

    assert "vanished.log" in viewer.status.text()


def test_a_view_round_trips_through_a_file(viewer, tmp_path):
    viewer.filter_box.setText("broke")
    path = str(tmp_path / "investigation.json")

    assert viewer.save_view_to(path) == ""
    viewer.filter_box.setText("")
    assert viewer.load_view_from(path) == ""

    assert viewer.filter_box.text() == "broke"


def test_loading_a_bad_view_file_says_why_and_changes_nothing(viewer,
                                                              tmp_path):
    viewer.filter_box.setText("kept")
    bad = tmp_path / "bad.json"
    bad.write_text("not a view", encoding="utf-8")

    problem = viewer.load_view_from(str(bad))

    assert problem
    assert viewer.filter_box.text() == "kept"
