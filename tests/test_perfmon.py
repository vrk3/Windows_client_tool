import os
import tempfile
from datetime import datetime
from modules.perfmon.perfmon_collector import PerfMonStore, collect_snapshot
from modules.perfmon.perfmon_alerts import AlertRule
from modules.perfmon.perfmon_search_provider import PerfMonSearchProvider
from core.search_provider import SearchQuery
from core.types import LogEntry


def test_collect_snapshot():
    snapshot = collect_snapshot()
    assert "cpu_total" in snapshot
    assert "memory_percent" in snapshot
    assert "disk_percent" in snapshot
    assert isinstance(snapshot["cpu_total"], float)


def test_store_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_perfmon.db")
        store = PerfMonStore(db_path)
        store.store_snapshot({"cpu_total": 50.0, "memory_percent": 60.0})
        results = store.query("cpu_total", hours_back=1)
        assert len(results) == 1
        assert results[0][1] == 50.0
        store.close()


def test_store_cleanup():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_perfmon.db")
        store = PerfMonStore(db_path)
        store.store_snapshot({"cpu_total": 50.0})
        store.cleanup_old(days=0)  # Delete everything
        results = store.query("cpu_total", hours_back=24)
        assert len(results) == 0
        store.close()


def test_alert_rule_no_trigger():
    rule = AlertRule(counter="cpu_total", operator=">", threshold=90, duration_sec=5)
    result = rule.check(50.0)  # Below threshold
    assert result is None


def test_alert_rule_immediate_no_fire():
    rule = AlertRule(counter="cpu_total", operator=">", threshold=90, duration_sec=300)
    result = rule.check(95.0)  # Above threshold but not long enough
    assert result is None  # Duration not met yet


def test_alert_rule_disabled():
    rule = AlertRule(counter="cpu_total", operator=">", threshold=90, duration_sec=0, enabled=False)
    result = rule.check(95.0)
    assert result is None


def test_alert_rule_fires_after_duration():
    rule = AlertRule(counter="cpu_total", operator=">", threshold=90, duration_sec=0)
    # duration_sec=0 means fire immediately when threshold crossed
    result = rule.check(95.0)
    assert result is not None
    assert "cpu_total" in result


def test_search_provider():
    sp = PerfMonSearchProvider()
    sp.add_alert(LogEntry(
        timestamp=datetime(2026, 3, 25, 12, 0),
        source="PerfMon",
        level="Warning",
        message="cpu_total > 90 for 300s",
    ))
    results = sp.search(SearchQuery(text="cpu"))
    assert len(results) == 1


def test_perfmon_module_creates_widget():
    from modules.perfmon.perfmon_module import PerfMonModule
    mod = PerfMonModule()
    widget = mod.create_widget()
    assert widget is not None
    assert mod._dashboard is not None
