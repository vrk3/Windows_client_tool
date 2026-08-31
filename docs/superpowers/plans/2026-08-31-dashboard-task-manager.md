# Dashboard: Task Manager + Process Explorer Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.
> This file is the RESUMABLE LEDGER. It is deliberately in git, unlike the
> gitignored `.superpowers/sdd/` progress files. Tick a box only when the
> thing is built, tested, and committed.

**Goal:** Make the Dashboard a full Task Manager + Process Explorer, absorbing
the standalone Process Explorer module.

**Decided with the user (2026-08-31):**
- Absorb the Process Explorer module into the Dashboard; remove its sidebar entry.
- Build order: Details + Processes tabs first.

**Architecture:** A `CompositeModule` over Task Manager's tab set, on a Qt-free
engine in `src/modules/dashboard/procengine/`. The engine follows the split
TreeSize's `scan/`+`store/` and the Log Viewer's parser/reader already keep:
**no PyQt6 imports in `procengine/`**, so it is testable headless.

**Tech Stack:** PyQt6, ctypes/ntdll, pywin32, WMI, psutil (secondary), PDH.

---

## The measurement that decides the engine

Taken on this machine, 278 processes, best of 5 (`scratchpad/bench_procs.py`):

| Engine | One full refresh | Fields per process |
|---|---|---|
| `psutil.process_iter` (current collector's attrs) | **667.9 ms** | 10 |
| `psutil.process_iter` (Details-tab attrs) | **1081.9 ms** | 17 |
| `NtQuerySystemInformation(SystemProcessInformation)` | **2.6 ms** | 23 |

**257x.** The existing `ProcessCollector` polls at 1 Hz, so it burns ~67% of a
core continuously; asked for Task Manager's columns it would cost longer than
its own tick and never converge. Every hot field therefore comes from the one
syscall. This is not a micro-optimisation -- it is the difference between a
pane that can show 40 live columns and one that cannot.

**Two-tier collection**, and the tiers are drawn by whether a value can change:

- **Hot** (every tick, from the one syscall): pid, ppid, name, threads,
  handles, session, base priority, working set, private bytes, paged and
  non-paged pool, pagefile, virtual size, page faults, kernel/user time,
  cycles, all six I/O counters, create time.
- **Cold** (resolved once per pid, cached for the process's lifetime): full
  image path, command line, user, integrity level, elevation, DEP, ASLR,
  description, company, signature, architecture, window title, service names.
  A new process pays for its own resolution; the other 277 do not.

**Rates are computed, never reported raw.** The current `ProcessNode` sets
`disk_read_bps=float(io.read_bytes)` -- the cumulative counter under a name
that says "per second". Task Manager shows a rate; a rate needs two samples
and the wall time between them.

## Global Constraints

- **No PyQt6 in `procengine/`.** Enforced by a test, like `scan/` and `store/`.
- **A refusal is never an answer.** This project's standing rule (Security
  Dashboard, Group Policy, tweaks): a value we could not read is `None` and
  says why -- never `0`, never "".  A protected process reporting "0 handles"
  is a lie; "could not read: access denied" is an answer.
- **What needs a kernel driver is named, not faked.** Process Explorer ships
  a signed driver. Without one: handle enumeration across other users'
  processes, kernel-mode thread stacks, and some DLL detail are unavailable.
  Those surfaces say so rather than showing an empty list.
- **Every destructive action confirms** (end process, end tree, suspend).
- Widget subclasses own `self._workers` and a `_cancel_all()`; the composite
  calls them (see CLAUDE.md).
- Lazily imported modules go in `HIDDEN_IMPORTS` in `pyinstaller_common.py`,
  or the frozen build runs fine until someone clicks the button.

---

## Wave 1 -- The engine and the two process tabs

### W1-01: The syscall, parsed
**Files:** Create `src/modules/dashboard/procengine/ntquery.py`,
`tests/test_procengine_ntquery.py`

- [x] `SYSTEM_PROCESS_INFORMATION` for x64, `system_processes()` returning
      one dict per process, `STATUS_INFO_LENGTH_MISMATCH` retry loop.
- [x] Tests: every running pid appears; our own pid's name matches; the
      buffer grows rather than truncating; a torn/short buffer raises rather
      than returning half a list.

### W1-02: Rates from two samples
**Files:** Create `procengine/rates.py`, `tests/test_procengine_rates.py`

- [x] CPU% from kernel+user time delta over wall time delta over core count;
      disk read/write B/s; the first sample of any process reports `None`,
      not `0.0` -- there is no rate yet and zero is a claim.
- [x] Tests: a synthetic two-sample pair yields the arithmetic; a pid that
      vanished between samples is dropped; a counter that went backwards
      (pid reuse) restarts rather than reporting a negative rate.

### W1-03: The cold cache
**Files:** Create `procengine/details.py`, `tests/test_procengine_details.py`

- [x] Per-pid lazy resolution of path, command line, user, integrity,
      elevation, description, company, architecture; cached by
      `(pid, create_time)` so pid reuse cannot serve a stale answer.
- [x] Refusals recorded as `None` + reason, never as "".
- [x] Tests: our own process resolves; pid 4 (System) is refused and says so;
      the cache is not consulted across a create_time change.

### W1-04: The snapshot the UI reads
**Files:** Create `procengine/snapshot.py`, `tests/test_procengine_snapshot.py`

- [x] Joins hot + rates + cold into `ProcessInfo`; builds the parent/child
      tree; marks services, own-user, suspended, elevated.
- [x] Tests: the tree roots at the processes whose parent is gone; a cycle in
      ppid (pid reuse makes them) does not recurse forever.

### W1-05: The Details table
**Files:** Create `src/modules/dashboard/details_tab.py`, tests

- [x] Task Manager's full column set (~40), each toggleable via a header
      right-click menu, widths and choice persisted.
- [x] Sorts on the VALUE, not the formatted text (the TreeSize rule: "9 B"
      must not land above "10 GB").
- [x] Tests: every column renders for a real snapshot; a refused value shows
      its reason, not "0".

### W1-06: The context menu
**Files:** Create `src/modules/dashboard/process_menu.py`, tests

- [ ] End task, end process tree, set priority, set affinity, analyse wait
      chain, create dump, open file location, search online, properties,
      go to service(s), UAC virtualisation, efficiency mode.
- [ ] Reuses `process_actions.py`, extended -- not reimplemented.
- [ ] Tests: each action confirms first; each reports the real outcome, and
      a refused kill says "access denied", never a silent no-op.

### W1-07: The Processes tab
**Files:** Create `src/modules/dashboard/processes_tab.py`, tests

- [ ] Task Manager's grouped view: Apps / Background processes / Windows
      processes, per-app child rows, the heat-map tint on the value columns,
      End task, Resource values as values or percents.
- [ ] Tests: grouping puts a windowed process under Apps; the tint scales
      against the busiest row.

### W1-08: The composite, and absorbing Process Explorer
**Files:** Modify `dashboard_module.py`, `main.py`, `pyinstaller_common.py`

- [ ] Dashboard becomes a `CompositeModule`; the existing overview stays as
      its first tab.
- [ ] `ProcessExplorerModule` is unregistered from the sidebar and hosted here.
- [ ] Tests: the sidebar no longer offers two ways to kill a process; the
      composite answers `get_refresh_interval()` for its children (miss this
      and every child loses auto-refresh -- it has happened here before).

---

## Wave 2 -- Performance

- [ ] W2-01 CPU: per-core graphs, utilisation, speed, processes/threads/handles,
      uptime, base speed, sockets, cores, logical processors, virtualisation,
      L1/L2/L3 cache.
- [ ] W2-02 Memory: in use, available, committed, cached, paged and non-paged
      pool, speed, slots used, form factor, hardware reserved.
- [ ] W2-03 Disk: active time, average response time, read/write speed,
      capacity, system disk, page file.
- [ ] W2-04 Network: throughput, adapter, SSID, DNS, IPv4/IPv6, signal.
- [ ] W2-05 GPU: per-engine utilisation, dedicated and shared memory, driver
      version, DirectX version.
- [ ] W2-06 Process Explorer's System Information window (CPU/memory/IO/GPU
      graphs, commit, kernel memory, paging).

## Wave 3 -- Process Explorer depth

- [ ] W3-01 Process tree colour coding (new, deleted, own, services,
      suspended, immersive, .NET, packed) -- extends `color_scheme.py`.
- [ ] W3-02 Properties dialog, 11 tabs: Image, Performance, Performance Graph,
      Disk and Network, GPU Graph, Threads, TCP/IP, Security, Environment,
      Job, Strings.
- [ ] W3-03 Lower pane: DLLs and Handles, with the driver limits stated.
- [ ] W3-04 Find handle or DLL.
- [ ] W3-05 Verify signatures; VirusTotal (reuses `virustotal_client.py`).
- [ ] W3-06 Suspend/resume, restart, run as, create dump.

## Wave 4 -- The remaining tabs

- [ ] W4-01 Users: per-user resource totals, expandable to processes.
- [ ] W4-02 App history: CPU time, network, metered network, tile updates.
- [ ] W4-03 Startup apps with impact (reuses `startup_boot`).
- [ ] W4-04 Services tab (reuses `services`), start/stop/restart, go to process.

## Wave 5 -- Polish

- [ ] W5-01 Column layouts saved per tab.
- [ ] W5-02 Always-on-top, update speed (High/Normal/Low/Paused), minimise on use.
- [ ] W5-03 Export the process list.
- [ ] W5-04 Global search provider over processes.
- [ ] W5-05 Real-machine harness `tools/dashboard_check.py`, the sibling of
      `logviewer_check.py` and `treesize_scan.py`.

---

## Findings

Recorded as they are learned, the way the Log Viewer plan did.

- **2026-08-31, W1-00 (benchmark):** `NtQuerySystemInformation` is 257x
  faster than `psutil.process_iter` for a full refresh (2.6 ms vs 667.9 ms,
  278 processes) and returns 23 fields against 10. The existing
  `ProcessCollector` therefore burns ~67% of a core at its 1 Hz tick.
- **2026-08-31:** `ProcessNode.disk_read_bps` is fed
  `float(io_counters.read_bytes)` -- a cumulative total under a per-second
  name. Every rate in the new engine is computed from two samples.
- **2026-08-31, W1-03:** the cold sweep costs **141 ms for 275 processes**
  (0.5 ms each) and the cached sweep **0.05 ms** -- so the two-tier split
  holds: a new process pays half a millisecond, the rest pay nothing.
- **2026-08-31, W1-03 (the one that shapes the UI):** unelevated, only
  **142 of 275 processes (52%)** will give up their path, command line, user
  or integrity -- 132 refuse with "Access is denied". Half the Details tab is
  unreadable to a normal user. That is why every unknown here is `None` with
  a reason rather than `""`: as an empty string the pane would show 133 blank
  rows, which reads as "these processes have no path" instead of "you are not
  allowed to look". The pane must offer to relaunch elevated rather than
  quietly showing half a machine.
- **2026-08-31, W1-03 (a crash, not a bug report):** ctypes assumes an
  undeclared function returns `c_int`, so on x64 a **pointer return is
  truncated to 32 bits**. `GetSidSubAuthority` handed back half a pointer and
  the test run died with an access violation -- no exception, no traceback in
  the usual place, just a dead process. Every Win32 prototype in `details.py`
  now declares `restype`/`argtypes`; the pointer-returning ones are the
  reason.
- **2026-08-31, W1-04:** a ppid CYCLE is reachable on a real machine (pid
  reuse lets two processes each name the other as parent). Promoting both to
  roots is not enough -- each stays listed as the other's child, so the
  result is a cycle wearing the shape of a tree, and walking it never
  returns. The test for it HUNG rather than failed, which is its own lesson:
  the link has to be cut, not re-pointed. `_break_cycles` severs one edge per
  cycle in O(n).
- **2026-08-31, W1-04:** a parent link is believed only when the parent was
  created BEFORE the child. Without that check an orphan is adopted by
  whatever process now holds its dead parent's pid -- the mechanism by which
  a process tree claims Notepad started sixty services.
