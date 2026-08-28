"""One cmdlet call, many readers.

Measured at branch point: one _ps() call costs 0.54s and 57 of the 171 readers
use it -- 19 of them each running Get-MpPreference to pull ONE field out of a
cmdlet that returns all of them. 155 controls read that way is a minute-long
tab, which is the Overview 37.3s defect at ten times the scale.

A refused snapshot must be distinguishable from an empty one. Get-MpPreference
on a machine with Defender replaced by a third-party AV does not fail -- it
answers with fewer fields.
"""
import pytest

from modules.security_dashboard import snapshots
from modules.security_dashboard import security_reader


@pytest.fixture(autouse=True)
def _clean():
    snapshots.invalidate()
    yield
    snapshots.invalidate()


def test_the_cmdlet_runs_once_for_many_reads(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"DisableRealtimeMonitoring":false,"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    for _ in range(10):
        snapshots.mp_preference()
    assert len(calls) == 1, f"ran the cmdlet {len(calls)} times, not once"


def test_invalidate_forces_a_refetch(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    snapshots.mp_preference()
    snapshots.invalidate()
    snapshots.mp_preference()
    assert len(calls) == 2


def test_a_refusal_is_recorded_as_a_reason_not_as_an_empty_answer(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    assert snapshots.mp_preference() == {}
    assert "Access is denied" in snapshots.availability()["mp_preference"]


def test_a_cmdlet_that_exits_zero_with_a_complaint_on_stdout_is_a_refusal(monkeypatch):
    """dism exits 740 with its complaint on STDOUT; netsh exits 0 and says
    'No rules match'. rc alone is not a success signal."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, "Elevated permissions are required.", ""))
    assert snapshots.mp_preference() == {}
    assert snapshots.availability()["mp_preference"] is not None


# ── `unavailable()` semantics ───────────────────────────────────────────────
#
# This is the review finding for Task 3: ~30 readers in security_reader.py
# test `if not snapshots.mp_preference():` to decide whether a read was
# refused. That is wrong -- a successful fetch that legitimately parses to
# `{}` (or to a dict missing the one field a reader wants) is truthy-false
# but was NOT refused, and the reader must not report it as such.


def test_unavailable_is_none_for_a_snapshot_that_fetched_successfully_and_empty(monkeypatch):
    """Get-MpPreference exiting 0 with a genuinely empty/minimal JSON body is
    a successful read, not a refusal -- `unavailable()` must say so."""
    monkeypatch.setattr(snapshots, "_ps", lambda cmd, timeout=30: (0, "{}", ""))
    assert snapshots.mp_preference() == {}
    assert snapshots.unavailable("mp_preference") is None


def test_unavailable_carries_the_reason_for_a_refused_snapshot(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    assert snapshots.mp_preference() == {}
    reason = snapshots.unavailable("mp_preference")
    assert reason is not None
    assert "Access is denied" in reason


def test_unavailable_triggers_a_fetch_when_the_snapshot_was_never_asked_for(monkeypatch):
    """Never-tried is a third state, distinct from both "fine" and "refused".
    Rather than let a caller read silence as "fine", asking `unavailable()`
    forces the fetch so the answer reflects reality."""
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    assert len(calls) == 0
    assert snapshots.unavailable("mp_preference") is None
    assert len(calls) == 1


# ── The finding itself: a reader must not mistake "empty but successful"
#   for "refused". ────────────────────────────────────────────────────────


def test_a_successful_but_empty_mp_preference_read_is_reported_available(monkeypatch):
    """Pins the review finding for Task 3.

    `snapshot_dict` being falsy is not evidence of refusal: Get-MpPreference
    exiting 0 with `{}` on stdout is a real, successful answer (this is
    exactly the shape the next task's SpeculationControl snapshot will take
    on a machine where the module didn't load: a small truthy-but-uninformative
    dict, or here, a directly empty one). A reader must ask
    `snapshots.unavailable(...)`, never `if not prefs:`, to tell that apart
    from an actual refusal.
    """
    monkeypatch.setattr(snapshots, "_ps", lambda cmd, timeout=30: (0, "{}", ""))
    result = security_reader.check_pua_protection()
    assert result["available"] is True, (
        f"an empty-but-successful read was reported unavailable: {result}")


def test_a_refused_mp_preference_read_is_reported_unavailable_with_its_reason(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    result = security_reader.check_pua_protection()
    assert result["available"] is False
    detail_text = " ".join(str(v) for _, v in result.get("details", []))
    assert "Access is denied" in detail_text


# ── task-3b: speculation_control ────────────────────────────────────────────
#
# Defect C1 -- _get_speculation_data used to download and execute
# SpeculationControl.psm1 from GitHub as a side effect of a *read* when the
# module wasn't already on the machine. Defect C2 -- the registry fallback
# it returned on failure, `{"source": "registry_fallback"}`, was truthy and
# every one of the fourteen CPU-vulnerability readers then did
# `d.get("BTIHardwarePresent", False)` -> False -> "Not mitigated" / red. A
# PowerShell module that failed to load told the user their CPU was
# unpatched against Spectre and Meltdown.

_NETWORK_PRIMITIVES = (
    "invoke-webrequest", "invoke-restmethod", "curl", "wget",
    "downloadfile", "downloadstring", "start-bitstransfer",
)

_SPECULATION_READERS = [
    security_reader.check_spectre_v2,
    security_reader.check_meltdown,
    security_reader.check_l1tf,
    security_reader.check_mds,
    security_reader.check_ssbd,
    security_reader.check_swapgs,
    security_reader.check_tsx_async_abort,
    security_reader.check_srbds,
    security_reader.check_retbleed,
    security_reader.check_mmio_stale_data,
    security_reader.check_downfall_gds,
    security_reader.check_zenbleed,
    security_reader.check_inception,
    security_reader.check_rfds,
]


def test_speculation_control_never_downloads_or_installs_anything(monkeypatch):
    """Pins defect C1: a *read* must never fetch and execute remote code."""
    seen = []

    def fake_ps(cmd, timeout=30):
        seen.append(cmd)
        return 0, '{"Source":"registry_fallback"}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    snapshots.speculation_control()
    assert seen, "speculation_control never called _ps"
    low = seen[0].lower()
    for primitive in _NETWORK_PRIMITIVES:
        assert primitive not in low, (
            f"speculation_control's command still contains {primitive!r}: {seen[0]}")


def test_speculation_control_registry_fallback_is_a_successful_empty_read(monkeypatch):
    """The module being absent is not a refusal -- it is a real, successful
    answer that just doesn't carry the per-CVE fields (the same shape
    Task 3's `mp_preference` test pins for an empty-but-successful read)."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, '{"Source":"registry_fallback"}', ""))
    data = snapshots.speculation_control()
    assert data == {"Source": "registry_fallback"}
    assert snapshots.unavailable("speculation_control") is None


@pytest.mark.parametrize("reader", _SPECULATION_READERS, ids=lambda fn: fn.__name__)
def test_every_cpu_vulnerability_reader_answers_unknown_not_vulnerable_when_module_absent(
        monkeypatch, reader):
    """The whole point of task-3b: a missing SpeculationControl module (or
    any refused read of it) must render as Unknown/amber, never as
    Not-mitigated/red -- across all fourteen CVE readers, not just one."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, '{"Source":"registry_fallback"}', ""))
    result = reader()
    assert result["status"] == "Unknown", (
        f"{reader.__name__} answered {result['status']!r} instead of Unknown "
        f"when the speculation data source was unavailable: {result}")
    assert result["color"] == "amber", (
        f"{reader.__name__} answered color {result['color']!r} instead of amber: {result}")
    assert result.get("available") is False


@pytest.mark.parametrize("reader", _SPECULATION_READERS, ids=lambda fn: fn.__name__)
def test_every_cpu_vulnerability_reader_answers_unknown_when_the_fetch_is_refused(
        monkeypatch, reader):
    """Same requirement, but for an outright refusal (not just an absent
    module) -- rc!=0 must not read as "vulnerable" either."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    result = reader()
    assert result["status"] == "Unknown"
    assert result["color"] == "amber"
    assert result.get("available") is False
    detail_text = " ".join(str(v) for _, v in result.get("details", []))
    assert "Access is denied" in detail_text


def test_windows_defender_cve_mitigations_reports_unknown_sub_checks_as_na_not_vulnerable():
    """The aggregate must preserve the Unknown verdict of its sub-readers
    rather than folding "Unknown" into the vulnerable bucket via a status-
    substring match that doesn't recognise it. Uses `readings` to isolate
    the classification logic from any single sub-reader's real machine
    state -- the fourteen speculation-based ones are supplied as Unknown,
    the rest as cleanly mitigated."""
    speculation_ids = {
        "check_spectre_v2", "check_meltdown", "check_l1tf", "check_mds", "check_ssbd",
        "check_swapgs", "check_tsx_async_abort", "check_srbds", "check_retbleed",
        "check_mmio_stale_data", "check_downfall_gds", "check_zenbleed",
        "check_inception", "check_rfds",
    }
    readings = {}
    for key, _label, _fn in security_reader._CVE_MITIGATION_CHECKS:
        if key in speculation_ids:
            readings[key] = {"status": "Unknown", "color": "amber", "available": False, "details": []}
        else:
            readings[key] = {"status": "Mitigated", "color": "green", "available": True, "details": []}
    result = security_reader.check_windows_defender_cve_mitigations(readings=readings)
    assert result["color"] != "red", (
        f"an unavailable data source turned into a red aggregate verdict: {result}")
    assert "unknown" in result["status"].lower()


def test_windows_defender_cve_mitigations_consumes_supplied_readings(monkeypatch):
    """Defect A: given a mapping of already-computed readings, the aggregate
    must not re-run those readers itself."""
    calls = []

    def spy_spectre():
        calls.append("check_spectre_v2")
        return {"status": "Mitigated", "color": "green", "available": True, "details": []}

    monkeypatch.setattr(security_reader, "check_spectre_v2", spy_spectre)
    readings = {
        name: {"status": "Mitigated", "color": "green", "available": True, "details": []}
        for name, _label, _fn in security_reader._CVE_MITIGATION_CHECKS
    }
    result = security_reader.check_windows_defender_cve_mitigations(readings=readings)
    assert not calls, "the aggregate re-ran a reader whose reading was already supplied"
    assert result["color"] == "green"


def test_windows_defender_cve_mitigations_still_callable_with_no_arguments(monkeypatch):
    """Other code and tests may depend on the zero-argument call still
    working -- it is just documented as the slow path."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, '{"Source":"registry_fallback"}', ""))
    result = security_reader.check_windows_defender_cve_mitigations()
    assert "status" in result and "color" in result


# ── task-3b: one lock per snapshot name ─────────────────────────────────────


def test_two_threads_racing_for_the_same_snapshot_launch_the_cmdlet_once(monkeypatch):
    import threading
    import time as _time

    calls = []
    call_lock = threading.Lock()

    def fake_ps(cmd, timeout=30):
        with call_lock:
            calls.append(_time.perf_counter())
        _time.sleep(0.15)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    threads = [threading.Thread(target=snapshots.mp_preference) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert len(calls) == 1, f"the cmdlet launched {len(calls)} times for one snapshot name"


def test_two_different_snapshots_fetch_concurrently_not_serialised(monkeypatch):
    """The Task 3 finding this closes: one lock for every snapshot name made
    a cold fetch for snapshot B wait on an unrelated cold fetch for snapshot
    A. Different names must be able to overlap."""
    import threading
    import time as _time

    windows = {}

    def fake_ps(cmd, timeout=30):
        start = _time.perf_counter()
        _time.sleep(0.2)
        end = _time.perf_counter()
        if "Get-MpPreference" in cmd:
            windows["mp_preference"] = (start, end)
            return 0, '{"PUAProtection":1}', ""
        windows["mp_computer_status"] = (start, end)
        return 0, '{"NISEnabled":true}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    t1 = threading.Thread(target=snapshots.mp_preference)
    t2 = threading.Thread(target=snapshots.mp_computer_status)
    overall_start = _time.perf_counter()
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    overall_elapsed = _time.perf_counter() - overall_start
    assert overall_elapsed < 0.35, (
        f"two different snapshots took {overall_elapsed:.2f}s combined -- "
        f"they serialised through one lock instead of overlapping"
    )
    a_start, a_end = windows["mp_preference"]
    b_start, b_end = windows["mp_computer_status"]
    assert a_start < b_end and b_start < a_end, (
        f"the two fetch windows did not overlap: {windows}")
