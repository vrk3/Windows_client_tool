# tests/test_sidebar_nav.py
from ui.sidebar_nav import SidebarNav


def test_sidebar_nav_creates_without_error(qapp):
    nav = SidebarNav()
    assert nav is not None


def test_add_module_creates_button(qapp):
    nav = SidebarNav()
    nav.add_module(group="DIAGNOSE", name="EventViewer", icon="📋",
                   display="Event Viewer", requires_admin=False)
    assert "EventViewer" in nav._btn_map


def test_add_two_groups_creates_both(qapp):
    nav = SidebarNav()
    nav.add_module("DIAGNOSE", "Events", "📋", "Events", False)
    nav.add_module("SYSTEM",   "Hardware", "🖥", "Hardware", False)
    assert len(nav._module_buttons) == 2
    assert "DIAGNOSE" in nav._module_buttons
    assert "SYSTEM" in nav._module_buttons


def test_select_sets_active(qapp):
    nav = SidebarNav()
    nav.add_module("DIAGNOSE", "Events", "📋", "Events", False)
    nav.select("Events")
    assert nav._active_name == "Events"
    assert nav._btn_map["Events"].isChecked()


def test_module_selected_signal_emits(qapp):
    results = []
    nav = SidebarNav()
    nav.add_module("DIAGNOSE", "Events", "📋", "Events", False)
    nav.module_selected.connect(results.append)
    nav._on_btn_clicked("Events")
    assert results == ["Events"]


def test_admin_required_button_disabled_when_not_admin(qapp):
    nav = SidebarNav()
    nav.set_admin(False)
    nav.add_module("SYSTEM", "BitLocker", "🔒", "BitLocker", requires_admin=True)
    btn = nav._btn_map["BitLocker"]
    assert not btn.isEnabled()


def test_admin_required_button_enabled_when_admin(qapp):
    nav = SidebarNav()
    nav.set_admin(True)
    nav.add_module("SYSTEM", "BitLocker", "🔒", "BitLocker", requires_admin=True)
    btn = nav._btn_map["BitLocker"]
    assert btn.isEnabled()
