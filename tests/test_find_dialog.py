"""The Find handle or DLL dialog.

Most of these are about the status line. The question people bring here is
"why can't I delete this file", so an empty result table must never be the
whole answer: a search that was truncated, or that met twenty processes it
could not inspect, has not established that nothing holds the file.
"""
import os
import time

import pytest

from modules.process_explorer.find_dialog import FindHandleDialog
from core.procengine.findref import FindReport, Match

MY_PID = os.getpid()


@pytest.fixture
def dialog(qapp):
    window = FindHandleDialog()
    yield window
    window.done(0)
    window.deleteLater()


def test_it_starts_empty(dialog):
    assert dialog._table.rowCount() == 0


def test_an_empty_query_is_refused(dialog):
    dialog._query.setText("   ")
    dialog.start()
    assert "Enter something" in dialog._status.text()
    assert dialog._table.rowCount() == 0


def test_results_fill_the_table(dialog):
    dialog._show_report(FindReport(
        matches=[Match(42, "thing.exe", "Handle", "File", r"C:\a\b.txt", 8)],
        searched_processes=100))
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 0).text() == "thing.exe"
    assert dialog._table.item(0, 1).text() == "42"
    assert r"C:\a\b.txt" in dialog._table.item(0, 4).text()


def test_no_matches_is_never_just_no_matches(dialog):
    """"Nothing has it open" and "nothing I could look at has it open" are
    different answers, and only one is safe to act on."""
    dialog._show_report(FindReport(matches=[], searched_processes=260,
                                   refused_modules=21))
    text = dialog._status.text()
    assert "Nothing matched" in text
    assert "not necessarily everything" in text


def test_a_truncated_search_says_so(dialog):
    dialog._show_report(FindReport(
        matches=[], searched_processes=100, stopped_early=True,
        note="The search ran out of its 8s budget before finishing, so "
             "this is a partial answer."))
    assert "partial" in dialog._status.text()


def test_a_clean_empty_search_does_not_hedge(dialog):
    dialog._show_report(FindReport(matches=[], searched_processes=260))
    text = dialog._status.text()
    assert "Nothing matched" in text
    assert "not necessarily" not in text


def test_double_clicking_a_row_offers_the_pid(dialog, qapp):
    dialog._show_report(FindReport(
        matches=[Match(4242, "thing.exe", "DLL", "Module", "x.dll")],
        searched_processes=1))
    seen = []
    dialog.pid_chosen.connect(seen.append)
    dialog._chose(dialog._table.model().index(0, 0))
    assert seen == [4242]


def test_a_real_search_runs_and_reports(dialog, qapp):
    """End to end through the dialog, inline (no pool in this fixture).

    This asserts the WIRING -- that a real sweep runs and comes back with
    a real report. It deliberately does not assert that a particular file
    is found: `test_an_open_file_handle_is_found` in
    `test_procengine_findref.py` covers that against the engine, where it
    is deterministic. Asserting it here as well was flaky for a reason
    worth recording rather than papering over: under pytest this process
    holds several hundred handles and earlier tests leave abandoned
    naming threads behind, so THIS process is sometimes among the handful
    whose naming blocks during a machine-wide sweep -- and a process that
    cannot name its own handles cannot find its own file.
    """
    dialog._query.setText("ntdll")
    dialog._handles.setChecked(False)      # modules only: no naming needed
    dialog.start()
    assert dialog._table.rowCount() >= 1, dialog._status.text()
    assert "matches" in dialog._status.text()
    pids = {int(dialog._table.item(row, 1).text())
            for row in range(dialog._table.rowCount())}
    assert MY_PID in pids, "this process has ntdll loaded"


def test_the_button_returns_to_search_after_a_run(dialog):
    dialog._show_report(FindReport(matches=[], searched_processes=1))
    assert dialog._button.text() == "Search"
    assert not dialog._progress.isVisible()


def test_a_failure_is_reported_rather_than_silent(dialog):
    dialog._failed("the handle table exploded")
    assert "failed" in dialog._status.text()
    assert dialog._button.text() == "Search"


def test_closing_cancels_a_running_search(qapp):
    window = FindHandleDialog()
    window._running = True
    window.done(0)
    assert window._cancelled is True
    assert window._running is False
