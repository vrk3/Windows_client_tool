"""History: what this pane changed, and the way back.

BackupService is shared with Tweaks, Debloat and the performance tuner, so
"everything this app ever did" is the wrong list to offer a Revert button
against.
"""
import pytest

from core.backup_service import RestorePointInfo
from modules.security_dashboard.security_module import SecurityDashboardModule


class _Backup:
    def __init__(self, points):
        self.points = points
        self.reverted = []

    def list_restore_points(self):
        return list(self.points)

    def control_ids_in(self, rp_id):
        return []

    def restore_point(self, rp_id):
        self.reverted.append(rp_id)
        return type("R", (), {"success": True, "partial": False,
                              "failed_steps": [], "errors": [],
                              "reverted_ids": [], "failed_ids": []})()


class _App:
    def __init__(self, backup):
        self.backup = backup


def _point(rp_id, module="Security Dashboard", status="applied"):
    return RestorePointInfo(id=rp_id, label=f"{rp_id} label",
                            created_at="2026-08-29 10:00:00", module=module,
                            status=status, step_count=3)


@pytest.fixture
def module(qapp, monkeypatch):
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.QThreadPool.globalInstance",
        lambda: type("Pool", (), {"start": lambda _s, _w: None})())
    mod = SecurityDashboardModule()
    mod.on_start(None)
    mod._held = mod.create_widget()
    # A modal .exec() waits for a click nobody is going to make: reverting
    # ends by showing the result dialog, and the whole suite hung there.
    mod._show_result_dialog = lambda result: None
    mod._ask_review = lambda changeset: True
    yield mod
    mod.on_stop()


def test_history_shows_only_this_panes_own_batches(module):
    module.app = _App(_Backup([
        _point("a"), _point("b", module="Tweaks"),
        _point("c", module="Debloat"), _point("d")]))
    assert [p.id for p in module.history_rows()] == ["a", "d"]


def test_history_with_no_backup_service_is_empty_not_a_crash(module):
    module.app = None
    assert module.history_rows() == []


def test_a_backup_service_that_throws_is_logged_not_fatal(module):
    class _Broken:
        def list_restore_points(self):
            raise OSError("the database is locked")
    module.app = _App(_Broken())
    assert module.history_rows() == []


def test_the_history_table_is_filled_from_the_restore_points(module):
    module.app = _App(_Backup([_point("a"), _point("d")]))
    module._load_history()
    assert module._history_table.rowCount() == 2
    assert module._history_table.item(0, 1).text() == "a label"


def test_a_batch_already_reverted_cannot_be_reverted_again(module):
    module.app = _App(_Backup([_point("a", status="restored")]))
    module._load_history()
    module._history_table.selectRow(0)
    assert not module._revert_button.isEnabled()


def test_reverting_goes_through_the_restore_point_not_per_control(
        module, monkeypatch):
    """revert_batch undoes the whole session in one call. Reverting each
    control afterwards would unwind an earlier session's steps."""
    backup = _Backup([_point("a")])
    module.app = _App(backup)
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module._load_history()
    module._history_table.selectRow(0)
    module._on_revert_requested()
    assert len(started) == 1
    # Without stubbing it, revert_batch's snapshots.invalidate() waits on
    # every snapshot fetch the rest of the suite has left in flight -- 189s
    # in one measured run.
    monkeypatch.setattr(
        "modules.security_dashboard.reverting.snapshots.invalidate",
        lambda: None)
    started[0].run()
    assert backup.reverted == ["a"]


def test_the_history_columns_are_sized_to_their_contents(module):
    """A column's default width is a guess until it has met the real data --
    the Firewall table's guesses clipped 393 of 544 real rows."""
    module.app = _App(_Backup([
        RestorePointInfo(id="a", label="a much longer label than the header",
                         created_at="2026-08-29 10:00:00",
                         module="Security Dashboard", status="applied",
                         step_count=3)]))
    module._load_history()
    metrics = module._history_table.fontMetrics()
    widest = metrics.horizontalAdvance("a much longer label than the header")
    assert module._history_table.columnWidth(1) >= widest


def test_the_header_can_still_be_dragged(module):
    """QHeaderView.Fixed refuses a user's drag SILENTLY."""
    from PyQt6.QtWidgets import QHeaderView
    module.app = _App(_Backup([_point("a")]))
    module._load_history()
    mode = module._history_table.horizontalHeader().sectionResizeMode(0)
    assert mode == QHeaderView.ResizeMode.Interactive


# --- baselines and profiles, through the pane ------------------------------


def test_a_baseline_stages_rather_than_applies(module):
    module._readings = {cid: None for cid in module.catalog}
    plan = module.plan_for_baseline("recommended")
    assert len(plan["staged"]) > 0
    assert all(entry["reason"] for entry in plan["skipped"])


def test_staging_a_baseline_fills_the_pending_bar(module):
    module._readings = {cid: c.desired for cid, c in module.catalog.items()}
    # everything already compliant -> nothing to stage
    module._on_baseline_requested("recommended")
    assert len(module.changeset) == 0
    assert module._pending.isHidden()


def test_a_baseline_uses_the_readings_the_pane_already_has(module):
    for control in module.catalog.values():
        object.__setattr__(control, "reader",
                           lambda: pytest.fail("the machine was read again"))
    module._readings = {cid: c.desired for cid, c in module.catalog.items()}
    module.plan_for_baseline("recommended")


def test_importing_a_file_that_is_not_a_profile_says_so(module, tmp_path):
    path = tmp_path / "nope.json"
    path.write_text("[1, 2, 3]")
    assert module.import_profile_from(str(path)) is None


def test_exporting_then_importing_this_machine_stages_nothing(module, tmp_path):
    module._readings = {cid: True for cid in module.catalog}
    path = tmp_path / "p.json"
    module.export_profile_to(str(path))
    assert module.import_profile_from(str(path)) == 0
