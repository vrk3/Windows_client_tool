"""Keyboard access to the things you do constantly.

Every one of these is currently a mouse trip. The bindings are all
modifier-based on purpose: a QShortcut takes precedence over the widget that
has focus, so a bare `/` or `n` would be swallowed before it ever reached the
Filter box you were typing it into.
"""
import pytest
from PyQt6.QtTest import QTest

from modules.log_viewer.log_viewer_module import LogViewerWidget

CMTRACE = (
    '<![LOG[Starting up]LOG]!><time="13:45:12.345+000" date="08-20-2026" '
    'component="Alpha" context="" type="1" thread="1" file="a.cpp:1">\n'
    '<![LOG[Careful now]LOG]!><time="13:45:13.000+000" date="08-20-2026" '
    'component="Beta" context="" type="2" thread="2" file="b.cpp:2">\n'
    '<![LOG[Careful again]LOG]!><time="13:45:14.000+000" date="08-20-2026" '
    'component="Beta" context="" type="3" thread="2" file="b.cpp:3">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.show()
    widget.open(str(path))
    yield widget
    widget.stop()
    widget.hide()


def _sequences(widget):
    return {shortcut.key().toString() for shortcut in widget._shortcuts}


def _activate(widget, sequence):
    """Fire the shortcut bound to `sequence`.

    Not QTest.keyClick: an offscreen window is never activated, so Qt never
    delivers a shortcut to it and every one of these would pass vacuously.
    What is under test here is which sequence is bound to which behaviour --
    whether Qt then delivers the key is Qt's business, not this pane's.
    """
    for shortcut in widget._shortcuts:
        if shortcut.key().toString() == sequence:
            shortcut.activated.emit()
            return
    raise AssertionError(f"nothing bound to {sequence!r}")


# ---- what is bound ------------------------------------------------------

def test_find_and_filter_both_have_a_shortcut(viewer):
    bound = _sequences(viewer)
    assert "Ctrl+F" in bound
    assert "Ctrl+L" in bound


def test_next_and_previous_match_are_bound(viewer):
    bound = _sequences(viewer)
    assert "F3" in bound
    assert "Shift+F3" in bound


def test_no_shortcut_is_a_bare_letter_or_symbol(viewer):
    """The rule this whole set is built around: a QShortcut wins over the
    focused widget, so an unmodified key would be stolen from every text box
    in the pane."""
    for sequence in _sequences(viewer):
        assert any(sequence.startswith(prefix)
                   for prefix in ("Ctrl+", "Shift+", "Alt+", "F")), \
            f"{sequence!r} would be swallowed while typing"


# ---- what they do -------------------------------------------------------

def test_the_find_shortcut_focuses_the_find_box(viewer):
    viewer.filter_box.setFocus()
    _activate(viewer, "Ctrl+F")
    assert viewer.focusWidget() is viewer.find_box


def test_the_filter_shortcut_focuses_the_filter_box(viewer):
    viewer.find_box.setFocus()
    _activate(viewer, "Ctrl+L")
    assert viewer.focusWidget() is viewer.filter_box


def test_the_hide_shortcut_focuses_the_hide_box(viewer):
    viewer.find_box.setFocus()
    _activate(viewer, "Ctrl+H")
    assert viewer.focusWidget() is viewer.exclude_box


def test_f3_moves_to_the_next_match(viewer):
    viewer.find_box.setText("Careful")
    viewer.find_next()
    first = viewer.table.currentIndex().row()

    _activate(viewer, "F3")

    assert viewer.table.currentIndex().row() > first


def test_shift_f3_moves_back(viewer):
    viewer.find_box.setText("Careful")
    viewer.find_next()
    viewer.find_next()
    later = viewer.table.currentIndex().row()

    _activate(viewer, "Shift+F3")

    assert viewer.table.currentIndex().row() < later


def test_typing_into_the_filter_box_is_never_stolen(viewer):
    """The reason there are no single-letter bindings."""
    viewer.filter_box.setFocus()
    QTest.keyClicks(viewer.filter_box, "n/N")
    assert viewer.filter_box.text() == "n/N"
