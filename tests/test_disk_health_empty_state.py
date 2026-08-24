"""Disk Health explains itself in the pane, not only in the toolbar.

The pane needs an explicit scan before it can show anything, and until then it
was ~750px of blank with a small grey line at the top. The measured "ink" of
the rendered pane was 0.010 -- effectively empty in both themes.
"""
import sys

from PyQt6.QtWidgets import QApplication, QLabel

QApplication.instance() or QApplication(sys.argv)

from modules.disk_health.disk_health_module import _DiskHealthWidget
from ui.empty_state import EmptyState


def test_a_fresh_pane_explains_itself_in_the_middle():
    pane = _DiskHealthWidget()
    states = pane.findChildren(EmptyState)
    assert len(states) == 1
    assert not states[0].isHidden()


def test_the_empty_state_offers_the_scan_it_is_waiting_for():
    pane = _DiskHealthWidget()
    state = pane.findChildren(EmptyState)[0]
    assert state.action_button is not None


def test_it_steps_aside_once_there_are_results():
    pane = _DiskHealthWidget()
    state = pane.findChildren(EmptyState)[0]
    pane._cards_layout.insertWidget(0, QLabel("a disk card"))
    pane._update_empty_state()
    assert state.isHidden()


def test_it_comes_back_when_the_results_are_cleared():
    pane = _DiskHealthWidget()
    state = pane.findChildren(EmptyState)[0]
    pane._cards_layout.insertWidget(0, QLabel("a disk card"))
    pane._update_empty_state()
    pane._clear_cards()
    assert not state.isHidden()
