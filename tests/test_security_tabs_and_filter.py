"""Themed tabs, one filter, and no sweep the pane did not ask for.

Measured at branch point: 57 of the readers launch PowerShell at 0.54s each.
Reading every control on tab open is the Overview 37.3s defect at ten times
the scale, so a tab reads only its own controls and only when shown, and
refresh is a button, never a timer.
"""
import pytest

from modules.security_dashboard.security_module import SecurityDashboardModule


@pytest.fixture
def module(qapp, monkeypatch):
    """A dashboard whose workers never reach the real global thread pool.

    Anything this fixture lets onto the pool outlives the test: the module and
    its widget are collected at teardown, the worker finishes afterwards, and
    its result signal fires into deleted C++ objects. That does not fail this
    file -- it takes down whichever test is running when it lands, which is
    how a whole-suite run died inside test_theme_light_coverage.py with an
    access violation while every file passed on its own.

    `_manual_refresh` is the one that hurts: it also starts the OVERVIEW
    sweep, which is a real 12s COMWorker.
    """
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.QThreadPool.globalInstance",
        lambda: type("Pool", (), {"start": lambda _s, _w: None})())
    mod = SecurityDashboardModule()
    mod.on_start(None)
    widget = mod.create_widget()
    mod._held = widget          # dropping it deletes the Qt children
    yield mod
    mod.on_stop()


def test_the_grab_bag_tabs_are_gone(module):
    titles = [module._tabs.tabText(i) for i in range(module._tabs.count())]
    assert "Advanced" not in titles and "Controls" not in titles


def test_every_category_in_the_catalog_has_a_tab(module):
    names = set(module._tab_names.values())
    for control in module.catalog.values():
        assert control.category.value in names, control.category.value


def test_an_ampersand_in_a_tab_name_is_not_a_keyboard_mnemonic(module):
    """Qt eats a single "&" as a mnemonic, so "Device & Boot" rendered as
    "Device  Boot" with the B underlined. Four of the seven names carry one,
    and it is only visible in a screenshot."""
    labels = [module._tabs.tabText(i) for i in range(module._tabs.count())]
    assert "Device && Boot" in labels
    assert "Device & Boot" not in labels


def test_a_tab_is_found_by_its_real_name_not_its_escaped_label(module):
    module._dispatch = lambda worker: None
    module.show_category_tab("Device & Boot")
    assert module._tab_names[module._tabs.currentIndex()] == "Device & Boot"


def test_staging_a_control_the_pane_has_not_read_does_not_read_it_now(module):
    """That read would be on the UI thread; bitlocker_encryption_detail alone
    is 5.4s of frozen window."""
    module._dispatch = lambda worker: None
    module.show_category_tab("Device & Boot")
    control = next(c for c in module.catalog.values()
                   if c.writable and c.desired is not None)
    object.__setattr__(control, "reader",
                       lambda: pytest.fail("the UI thread read the machine"))
    module._readings.pop(control.id, None)
    module._on_card_staged(control.id, control.desired)
    assert control.id in module.changeset
    assert module.changeset.unread_before


def test_filtering_matches_description_not_only_title(module):
    hits = module.filter_controls("multicast")
    assert any(c.id == "llmnr" for c in hits)


def test_filtering_reaches_text_that_is_only_in_the_body(module):
    """"multicast" is in LLMNR's own title, so it does not prove anything.

    A word that appears ONLY in a description or a why_it_matters does.
    """
    control = module.catalog["llmnr"]
    haystack = f"{control.description} {control.why_it_matters}".lower()
    word = next(w for w in haystack.split()
                if len(w) > 5 and w.isalpha()
                and w not in control.title.lower())
    assert any(c.id == "llmnr" for c in module.filter_controls(word)), word


def test_only_actionable_hides_the_read_only_controls(module):
    hits = module.filter_controls("", only_actionable=True)
    assert all(c.writable for c in hits)
    assert len(hits) < len(module.catalog)


def test_only_problems_keys_off_desired_not_the_readers_colour(module):
    """Ruling 6: 14 controls have desired=None and their readers legitimately
    colour them amber or red. None of those is a problem."""
    module._readings = {cid: False for cid in module.catalog}
    hits = module.filter_controls("", only_problems=True)
    assert all(c.desired is not None for c in hits)
    assert all(c.desired != module._readings[c.id] for c in hits)


def test_a_control_that_could_not_be_read_is_not_called_a_problem(module):
    """"Could not look" is not "wrong", and putting it in the problem list
    sends someone hunting for a setting that may well be correct."""
    module._readings = {cid: None for cid in module.catalog}
    assert module.filter_controls("", only_problems=True) == []


def test_opening_a_tab_reads_only_that_tabs_controls(module, qapp):
    read = []
    for control in module.catalog.values():
        object.__setattr__(control, "reader",
                           lambda c=control: read.append(c.id) or {"available": True,
                                                                   "enabled": True})
    module._dispatch = lambda worker: worker.run()   # synchronous, no pool
    module.show_category_tab("Services")
    assert read, "the tab read nothing"
    assert all(module.catalog[cid].category.value == "Services" for cid in read)


def test_a_tab_already_being_read_does_not_start_a_second_read(module, qapp):
    """The Overview guard, one tab over: 26 controls is not a cheap sweep to
    run twice because someone clicked the tab again."""
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module.show_category_tab("Services")
    module.show_category_tab("Services")
    module.show_category_tab("Services")
    assert len(started) == 1


def test_a_second_read_runs_once_the_first_has_finished(module):
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module.show_category_tab("Services")
    started[0].signals.finished.emit()
    module.show_category_tab("Services")
    assert len(started) == 2


def test_the_pane_starts_no_auto_refresh_timer(module):
    """The Overview pane ran a 30s timer against a 37.3s sweep and relaunched
    the unfinished one, so it sat on 'Loading...' for over half a minute."""
    from PyQt6.QtCore import QTimer
    timers = module._held.findChildren(QTimer)
    assert not [t for t in timers if t.isActive()]


def test_the_pane_asks_for_no_timer_at_all(module):
    """MainWindow owns the timer, so findChildren above cannot see it."""
    assert module.get_refresh_interval() is None


def test_refresh_drops_the_snapshot_caches_first(module, monkeypatch):
    """Otherwise Refresh re-renders the same cached answers and looks broken."""
    dropped = []
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.snapshots.invalidate",
        lambda: dropped.append(1))
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module.show_category_tab("Services")
    started[0].signals.finished.emit()   # the first read is done
    started.clear()
    module._manual_refresh()
    assert started, "refresh started no read"
    assert dropped == [], "invalidate() must not run on the UI thread"
    started[-1].run()
    assert dropped == [1]


def test_refresh_never_invalidates_on_the_ui_thread(module, monkeypatch):
    """invalidate() takes every per-name snapshot lock, so it waits for any
    fetch already in flight -- up to a 30s timeout each. One suite run
    measured 189s. Called from a click handler that is the window frozen."""
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.snapshots.invalidate",
        lambda: pytest.fail("invalidate() ran on the UI thread"))
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module.show_category_tab("Services")
    started[0].signals.finished.emit()
    module._manual_refresh()


def test_a_card_exists_for_every_control_in_a_built_tab(module):
    module._dispatch = lambda worker: None      # build it, do not read it
    module.show_category_tab("Services")
    tab = module._category_tabs["Services"]
    expected = [c.id for c in module.catalog.values()
                if c.category.value == "Services"]
    assert sorted(tab.cards) == sorted(expected)


def test_staging_from_a_card_does_not_touch_the_machine(module):
    module._dispatch = lambda worker: None
    module.show_category_tab("Services")
    tab = module._category_tabs["Services"]
    control_id = next(cid for cid, card in tab.cards.items()
                      if module.catalog[cid].writable)
    module._readings[control_id] = module.catalog[control_id].desired
    module._on_card_staged(control_id, True)
    assert control_id in module.changeset or len(module.changeset) == 0


def test_a_category_read_runs_on_a_com_initialised_thread(module):
    """These readers reach WMI, and CLAUDE.md is explicit that WMI work needs
    COMWorker. Unelevated the two are indistinguishable -- every WMI call in
    the catalog is refused, so nothing exercises COM and the wrong worker
    would survive every test on this machine. Measured: main thread, Worker
    and COMWorker return identical values for all 19 Device & Boot controls.
    """
    from core.worker import COMWorker
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module.show_category_tab("Device & Boot")
    assert isinstance(started[0], COMWorker)
