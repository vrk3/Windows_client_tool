"""Showing several components at once.

CSI and CBS together is the ordinary case when reading a servicing failure --
CSI does the work, CBS narrates it -- and until now picking one meant losing
the other. The model takes a set on both the component and thread axes; only
the Component control offers it, because picking two of DISM's 329 threads is
not a thing anyone does.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.log_model import LogModel, MESSAGE


def _entry(message, source="CBS", thread="1"):
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, 0, 0),
                    source=source, level="Info", message=message,
                    raw={"thread": thread})


def _model(entries):
    model = LogModel()
    model.append(list(entries))
    return model


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


THREE = [_entry("from cbs", source="CBS"),
         _entry("from csi", source="CSI"),
         _entry("from sxs", source="SXS")]


# ---- components ---------------------------------------------------------

def test_a_set_of_components_shows_all_of_them(qapp):
    model = _model(THREE)
    model.set_filter(component={"CBS", "CSI"})
    assert _messages(model) == ["from cbs", "from csi"]


def test_a_bare_string_still_selects_one(qapp):
    """Every existing caller passes a string; they must keep working."""
    model = _model(THREE)
    model.set_filter(component="CSI")
    assert _messages(model) == ["from csi"]


def test_an_empty_string_means_show_everything(qapp):
    model = _model(THREE)
    model.set_filter(component="CSI")
    model.set_filter(component="")
    assert len(_messages(model)) == 3


def test_an_empty_set_means_show_everything(qapp):
    """"Nothing ticked" is "no opinion", not "hide every row" -- the latter
    would leave someone staring at an empty table having ticked nothing."""
    model = _model(THREE)
    model.set_filter(component={"CSI"})
    model.set_filter(component=set())
    assert len(_messages(model)) == 3


def test_a_set_of_one_behaves_like_the_string(qapp):
    model = _model(THREE)
    model.set_filter(component={"CSI"})
    assert _messages(model) == ["from csi"]


def test_a_component_not_present_shows_nothing(qapp):
    model = _model(THREE)
    model.set_filter(component={"NOPE"})
    assert _messages(model) == []


def test_components_combine_with_the_other_filters(qapp):
    model = _model(THREE)
    model.set_filter(component={"CBS", "CSI"}, needle="csi")
    assert _messages(model) == ["from csi"]


# ---- threads ------------------------------------------------------------

def test_a_set_of_threads_works_the_same_way(qapp):
    """The model supports it even though only Component offers the control,
    so the UI can catch up without touching the model again."""
    model = _model([_entry("one", thread="1"), _entry("two", thread="2"),
                    _entry("three", thread="3")])
    model.set_filter(thread={"1", "3"})
    assert _messages(model) == ["one", "three"]


def test_a_bare_thread_string_still_selects_one(qapp):
    model = _model([_entry("one", thread="1"), _entry("two", thread="2")])
    model.set_filter(thread="2")
    assert _messages(model) == ["two"]


# ---- the Component control ----------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = "".join(
    '<![LOG[from {c}]LOG]!><time="13:45:1{n}.000+000" date="08-20-2026" '
    'component="{c}" context="" type="1" thread="1" file="a.cpp:1">\n'.format(
        c=component, n=number)
    for number, component in enumerate(("CBS", "CSI", "SXS")))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _viewer_messages(widget):
    model = widget.model
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


def test_the_control_lists_every_component(viewer):
    assert viewer.component_values() == ["CBS", "CSI", "SXS"]


def test_nothing_ticked_shows_everything(viewer):
    assert len(_viewer_messages(viewer)) == 3
    assert viewer.component_button.text().startswith("Component: All")


def test_ticking_two_components_shows_both(viewer):
    """CSI does the work and CBS narrates it; reading a servicing failure
    means seeing both."""
    viewer.set_components({"CBS", "CSI"})
    assert _viewer_messages(viewer) == ["from CBS", "from CSI"]


def test_the_button_names_what_is_ticked(viewer):
    viewer.set_components({"CBS", "CSI"})
    label = viewer.component_button.text()
    assert "CBS" in label and "CSI" in label


def test_many_ticked_are_summarised_rather_than_listed(viewer):
    """A button that grows with the selection pushes the toolbar around."""
    viewer.set_components({"CBS", "CSI", "SXS"})
    assert "3 components" in viewer.component_button.text()


def test_unticking_everything_shows_everything_again(viewer):
    viewer.set_components({"CBS"})
    viewer.set_components(set())
    assert len(_viewer_messages(viewer)) == 3


def test_opening_another_log_clears_a_component_that_is_gone(viewer, tmp_path):
    """The stale-filter shape: the model must not keep filtering on a
    component that belongs to a log which is no longer open."""
    viewer.set_components({"SXS"})
    other = tmp_path / "second.log"
    other.write_text(
        '<![LOG[only line]LOG]!><time="13:45:12.000+000" date="08-20-2026" '
        'component="OTHER" context="" type="1" thread="1" file="a.cpp:1">\n',
        encoding="utf-8")

    viewer.open(str(other))

    assert not viewer.model._component, \
        "the model kept a component from the log that was closed"
    assert len(_viewer_messages(viewer)) == 1
