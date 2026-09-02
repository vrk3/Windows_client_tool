"""The Users tab, as a widget.

Runs against the real machine -- there is no fixture that can stand in for
the machine's real accounts, and the interesting rows are the ones the
kernel actually refuses.
"""
import os

import pytest

from modules.dashboard.users_tab import UsersTab
from core.procengine.users import UNKNOWN, group_by_user


@pytest.fixture
def tab(qapp):
    widget = UsersTab()
    widget.refresh()
    widget.refresh()
    yield widget
    widget.stop()
    widget.deleteLater()


def _settle(qapp, widget, predicate, seconds=8.0):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_users_tab_fills_with_accounts(qapp):
    view = UsersTab()
    view.refresh()
    assert _settle(qapp, view, lambda: view.tree.topLevelItemCount() > 0)
    view.stop()
    view.deleteLater()


def test_every_top_level_row_is_an_account(tab):
    assert tab.tree.topLevelItemCount() > 0
    # A top-level row expands to processes; none should be empty.
    for index in range(tab.tree.topLevelItemCount()):
        item = tab.tree.topLevelItem(index)
        assert item.text(0), f"row {index} has no name"


def test_some_accounts_expand_to_processes(tab):
    """An account with no processes would be a useless row."""
    found = False
    for index in range(tab.tree.topLevelItemCount()):
        item = tab.tree.topLevelItem(index)
        if item.childCount() > 0:
            found = True
            break
    assert found, "no account row had processes under it"


def test_our_own_process_is_somewhere_in_the_tree(tab):
    from PyQt6.QtCore import Qt

    wanted = os.getpid()
    for item in _walk(tab.tree):
        if item.data(0, Qt.ItemDataRole.UserRole + 2) == wanted:
            return
    raise AssertionError(f"our pid {wanted} is not under any account")


def test_the_tree_states_what_it_cannot_read(qapp):
    """Unelevated, about half the machine refuses its token. The pane must
    say so rather than silently charging SYSTEM's work to the viewer."""
    view = UsersTab()
    view.refresh()
    assert _settle(qapp, view, lambda: view.tree.topLevelItemCount() > 0)
    try:
        # "Accounts not readable" is only absent when nothing was refused.
        if view._snapshot is not None and view._snapshot.refused:
            labels = [view.tree.topLevelItem(i).text(0)
                      for i in range(view.tree.topLevelItemCount())]
            assert any(UNKNOWN in label for label in labels), \
                f"{UNKNOWN} missing from {labels}"
    finally:
        view.stop()
        view.deleteLater()


def test_grouping_matches_the_engine(tab):
    if tab._snapshot is None:
        return
    groups = group_by_user(tab._snapshot)
    assert tab.tree.topLevelItemCount() == len(groups)


def _walk(tree):
    stack = [tree.topLevelItem(index)
             for index in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        yield item
        stack.extend(item.child(i) for i in range(item.childCount()))
