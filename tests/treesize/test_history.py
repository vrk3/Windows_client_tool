"""Snapshots and the History view (spec 4.4, 5.8, 8.3)."""
import os
import time


from modules.treesize.store import snapshots
from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup
from modules.treesize.store.snapshots import SnapshotInfo
from modules.treesize.ui.views.history import HistoryView, Sparkline


def _store(total=1000):
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "data.bin", size=total)
    s.build_child_lists()
    rollup(s)
    return s, root


# ---- snapshots ----------------------------------------------------------

def test_a_snapshot_round_trips(tmp_path):
    store, root = _store(4096)
    path = snapshots.create(store, root, "C:", engine="mft",
                            directory=str(tmp_path))
    assert os.path.exists(path)
    found = snapshots.enumerate_snapshots(str(tmp_path))
    assert len(found) == 1
    assert found[0].target == "C:"
    assert found[0].total_size == 4096


def test_snapshots_come_back_newest_first(tmp_path):
    for size in (100, 200, 300):
        store, root = _store(size)
        snapshots.create(store, root, "C:", directory=str(tmp_path))
        time.sleep(1.05)          # filenames carry a whole-second timestamp
    found = snapshots.enumerate_snapshots(str(tmp_path))
    assert [s.total_size for s in found] == [300, 200, 100]


def test_a_corrupt_snapshot_is_skipped_not_fatal(tmp_path):
    """One bad file must not stop the History view showing the others."""
    store, root = _store(500)
    snapshots.create(store, root, "C:", directory=str(tmp_path))
    (tmp_path / f"broken{snapshots.SNAPSHOT_SUFFIX}").write_bytes(b"garbage")
    found = snapshots.enumerate_snapshots(str(tmp_path))
    assert len(found) == 1


def test_unrelated_files_are_ignored(tmp_path):
    store, root = _store()
    snapshots.create(store, root, "C:", directory=str(tmp_path))
    (tmp_path / "notes.txt").write_text("hello")
    assert len(snapshots.enumerate_snapshots(str(tmp_path))) == 1


def test_snapshots_can_be_filtered_by_target(tmp_path):
    store, root = _store()
    snapshots.create(store, root, "C:", directory=str(tmp_path))
    time.sleep(1.05)
    snapshots.create(store, root, "E:", directory=str(tmp_path))
    assert len(snapshots.enumerate_snapshots(str(tmp_path), target="C:")) == 1


def test_missing_directory_yields_nothing_rather_than_raising(tmp_path):
    assert snapshots.enumerate_snapshots(str(tmp_path / "nope")) == []


def test_targets_that_differ_do_not_collapse_to_one_filename():
    """Colons and separators cannot appear in a filename, but two different
    targets must not end up sharing a slug."""
    assert snapshots._slug("C:\\Users") != snapshots._slug("C:\\Windows")
    assert snapshots._slug("C:\\") != snapshots._slug("D:\\")


def test_deleting_a_snapshot(tmp_path):
    store, root = _store()
    path = snapshots.create(store, root, "C:", directory=str(tmp_path))
    assert snapshots.delete(path)
    assert snapshots.enumerate_snapshots(str(tmp_path)) == []
    assert not snapshots.delete(path), "deleting twice reports failure"


# ---- history view -------------------------------------------------------

def _infos(sizes):
    now = time.time()
    return [SnapshotInfo(path=f"s{i}", target="C:",
                         timestamp=now - (len(sizes) - i) * 86400,
                         total_size=size, node_count=100 + i)
            for i, size in enumerate(sizes)]


def test_history_lists_newest_first(qapp):
    view = HistoryView()
    view.set_snapshots(_infos([100, 200, 300]))
    assert view.table.topLevelItemCount() == 3
    first, last = view.table.topLevelItem(0), view.table.topLevelItem(2)
    assert first.text(2) == "300 B"
    assert last.text(2) == "100 B"


def test_history_shows_the_change_between_consecutive_snapshots(qapp):
    view = HistoryView()
    view.set_snapshots(_infos([100, 250]))
    newest = view.table.topLevelItem(0)
    assert newest.text(3) == "150 B"


def test_the_oldest_snapshot_has_no_change_to_report(qapp):
    view = HistoryView()
    view.set_snapshots(_infos([100, 250]))
    oldest = view.table.topLevelItem(1)
    assert oldest.text(3) == ""


def test_history_summarises_growth_since_the_first_snapshot(qapp):
    view = HistoryView()
    view.set_snapshots(_infos([1000, 3048]))
    assert "2.0 KB" in view.summary.text()
    assert "2 snapshots" in view.summary.text()


def test_history_with_no_snapshots_says_how_to_make_one(qapp):
    view = HistoryView()
    view.set_snapshots([])
    assert "No snapshots" in view.summary.text()
    assert "Create snapshot" in view.summary.text()


def test_sparkline_survives_a_flat_series(qapp):
    """Equal values would divide by zero, and drawing at the top would imply a
    maximum that is not there."""
    chart = Sparkline()
    chart.resize(300, 120)
    chart.set_points([(1.0, 500), (2.0, 500), (3.0, 500)])
    chart.grab()          # must not raise


def test_sparkline_handles_too_few_points(qapp):
    chart = Sparkline()
    chart.resize(300, 120)
    chart.set_points([(1.0, 500)])
    chart.grab()


def test_sparkline_orders_points_by_time_whatever_order_it_is_given(qapp):
    chart = Sparkline()
    chart.set_points([(3.0, 300), (1.0, 100), (2.0, 200)])
    assert [size for _when, size in chart._points] == [100, 200, 300]
