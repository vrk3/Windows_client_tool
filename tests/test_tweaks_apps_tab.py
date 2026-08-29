"""The Apps tab has to be able to apply what someone checked in it.

Reported from the running app: check "Bing Search" and "VLC Media Player" in
Tweaks -> Apps, press Apply Selected, and get "Check at least one tweak to
apply." Three separate breaks, none of which any test covered:

* `AppManagerTab._apply_btn` ("Apply Changes") was created and never connected
  to anything at all.
* `_installed_list.itemChanged` was never connected either, so checking an
  installed package to remove never reached `_remove_queue` -- a set that was
  initialised and read, and never written to by anything.
* `TweaksModule._on_apply` iterates `self._tab_widgets`, and the Apps tab is
  added to the QTabWidget but never put in there. So the main Apply button
  could not see it, whatever was checked.

`AppCatalog.install_app`, `.remove_appx` and `.remove_app_winget` were all
fully implemented, and nothing in the UI ever called them.
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from modules.tweaks.app_catalog import AppCatalog
from modules.tweaks.tweaks_module import AppManagerTab


@pytest.fixture
def catalog():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "src", "modules",
                        "tweaks", "definitions", "app_catalog.json")
    return AppCatalog(catalog_path=os.path.abspath(path))


@pytest.fixture
def tab(qapp, catalog):
    widget = AppManagerTab(catalog, None)
    widget.populate_installed({"Microsoft.BingSearch", "Microsoft.ZuneMusic"})
    widget.populate_installed_winget(set())
    return widget


def _item_named(list_widget, text_fragment):
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if text_fragment.lower() in item.text().lower():
            return item
    raise AssertionError(f"no item matching {text_fragment!r}")


def test_checking_an_installed_package_queues_it_for_removal(tab):
    """"check to remove" is what the group box says it is."""
    item = _item_named(tab._installed_list, "BingSearch")
    item.setCheckState(Qt.CheckState.Checked)
    assert tab.queued_changes()["remove"] == ["Microsoft.BingSearch"]


def test_unchecking_takes_it_back_out_of_the_queue(tab):
    item = _item_named(tab._installed_list, "BingSearch")
    item.setCheckState(Qt.CheckState.Checked)
    item.setCheckState(Qt.CheckState.Unchecked)
    assert tab.queued_changes()["remove"] == []


def test_checking_a_catalog_app_queues_it_for_install(tab):
    item = _item_named(tab._catalog_list, "VLC")
    item.setCheckState(Qt.CheckState.Checked)
    assert tab.queued_changes()["install"] == ["VideoLAN.VLC"]


def test_the_two_queues_are_reported_together(tab):
    _item_named(tab._installed_list, "BingSearch").setCheckState(
        Qt.CheckState.Checked)
    _item_named(tab._catalog_list, "VLC").setCheckState(Qt.CheckState.Checked)
    changes = tab.queued_changes()
    assert changes["remove"] == ["Microsoft.BingSearch"]
    assert changes["install"] == ["VideoLAN.VLC"]
    assert tab.has_queued_changes()


def test_the_apply_button_enables_once_something_is_queued(tab):
    assert not tab._apply_btn.isEnabled()
    _item_named(tab._installed_list, "BingSearch").setCheckState(
        Qt.CheckState.Checked)
    assert tab._apply_btn.isEnabled()
    assert "Remove 1" in tab._apply_label.text()


def test_the_apply_button_actually_asks_for_something_to_happen(tab):
    """It was connected to nothing, so clicking it did nothing at all."""
    asked = []
    tab.apply_requested.connect(lambda: asked.append(1))
    _item_named(tab._installed_list, "BingSearch").setCheckState(
        Qt.CheckState.Checked)
    tab._apply_btn.click()
    assert asked == [1]


def test_a_protected_package_cannot_be_queued(tab, catalog):
    """Protected entries are disabled in the list; nothing should be able to
    put one in the removal queue behind that."""
    from modules.tweaks.app_catalog import PROTECTED_APPS_DEFAULT
    protected = sorted(PROTECTED_APPS_DEFAULT)[0]
    tab.populate_installed({protected, "Microsoft.BingSearch"})
    item = _item_named(tab._installed_list, protected.split(".")[-1])
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    item.setCheckState(Qt.CheckState.Checked)      # forced, as code could
    assert protected not in tab.queued_changes()["remove"]


def test_repopulating_the_list_does_not_invent_a_queue(tab):
    """populate_installed sets every item's check state, and each of those
    fires itemChanged. If that is not guarded, refreshing the list queues
    every package on the machine for removal."""
    tab.populate_installed({"Microsoft.BingSearch", "Microsoft.ZuneMusic"})
    assert tab.queued_changes()["remove"] == []
    assert not tab.has_queued_changes()


def test_clearing_the_queue_resets_the_button(tab):
    _item_named(tab._installed_list, "BingSearch").setCheckState(
        Qt.CheckState.Checked)
    tab.clear_queues()
    assert not tab.has_queued_changes()
    assert not tab._apply_btn.isEnabled()
    assert "No changes queued" in tab._apply_label.text()
