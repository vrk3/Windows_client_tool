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

## Wave 1 -- The engine and the two process tabs  **[COMPLETE]**

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

- [x] End task, end process tree, set priority, set affinity, analyse wait
      chain, create dump, open file location, search online, properties,
      go to service(s), UAC virtualisation, efficiency mode.
- [x] Reuses `process_actions.py`, extended -- not reimplemented.
- [x] Tests: each action confirms first; each reports the real outcome, and
      a refused kill says "access denied", never a silent no-op.

### W1-07: The Processes tab
**Files:** Create `src/modules/dashboard/processes_tab.py`, tests

- [x] Task Manager's grouped view: Apps / Background processes / Windows
      processes, per-app child rows, the heat-map tint on the value columns,
      End task, Resource values as values or percents.
- [x] Tests: grouping puts a windowed process under Apps; the tint scales
      against the busiest row.

### W1-08: The composite, and absorbing Process Explorer
**Files:** Modify `dashboard_module.py`, `main.py`, `pyinstaller_common.py`

- [x] Dashboard becomes a `CompositeModule`; the existing overview stays as
      its first tab.
- [x] `ProcessExplorerModule` is unregistered from the sidebar and hosted here.
- [x] Tests: the sidebar no longer offers two ways to kill a process; the
      composite answers `get_refresh_interval()` for its children (miss this
      and every child loses auto-refresh -- it has happened here before).

---

## Wave 2 -- Performance

- [x] W2-01 CPU: per-core graphs, utilisation, speed, processes/threads/handles,
      uptime, base speed, sockets, cores, logical processors, virtualisation,
      L1/L2/L3 cache.
- [x] W2-02 Memory: in use, available, committed, cached, paged and non-paged
      pool, speed, slots used, form factor, hardware reserved.
- [x] W2-03 Disk: active time, average response time, read/write speed,
      capacity, system disk, page file.
- [x] W2-04 Network: throughput, adapter, SSID, DNS, IPv4/IPv6, signal.
- [x] W2-05 GPU: per-engine utilisation, dedicated and shared memory, driver
      version, DirectX version.
- [x] W2-06 Process Explorer's System Information window (CPU/memory/IO/GPU
      graphs, commit, kernel memory, paging).

**Wave 2 is COMPLETE.**

## Wave 3 -- Process Explorer depth

- [x] W3-01 Process tree colour coding (new, deleted, own, services,
      suspended, immersive, .NET, packed) -- extends `color_scheme.py`.
- [x] W3-02 Properties dialog, 11 tabs: Image, Performance, Performance Graph,
      Disk and Network, GPU Graph, Threads, TCP/IP, Security, Environment,
      Job, Strings.
- [x] W3-03 Lower pane: DLLs and Handles, with the driver limits stated.
- [x] W3-04 Find handle or DLL.
- [x] W3-05 Verify signatures; VirusTotal (reuses `virustotal_client.py`).
- [x] W3-06 Suspend/resume, restart, run as, create dump.

## Wave 4 -- The remaining tabs

- [x] W4-01 Users: per-user resource totals, expandable to processes.
- [x] W4-02 App history: CPU time per program since it started (network
      and metered/tile columns are not reachable without a driver and are
      named as absent rather than faked).
- [x] W4-03 Startup apps: reuses `startup_reader.py` across all six
      sources; startup-impact grades are boot telemetry this tool does not
      read, so there is no impact column and the tab says why.
- [x] W4-04 Services tab: reuses the `services_manager` data layer,
      start/stop/restart with confirmation, "go to process" signal left
      unwired.

## Wave 5 -- Polish

- [x] W5-01 Column layouts saved per tab.
- [x] W5-02 Always-on-top, update speed (High/Normal/Low/Paused), minimise on use.
- [x] W5-03 Export the process list.
- [x] W5-04 Global search provider over processes.
- [ ] W5-05 Real-machine harness `tools/dashboard_check.py`, the sibling of
      `logviewer_check.py` and `treesize_scan.py`.

---

## Where this stopped (2026-09-02)

**Waves 1, 2 and 3 COMPLETE** -- W3-01..W3-06 done. Wave 4 (Users, App
history, Startup apps, Services tabs) is next.

| | |
|---|---|
| W1-01..W1-08 | engine, Details tab, Processes tab, actions, menu, composite |
| W2-01..W2-06 | CPU, Memory, Disk, Network, GPU, System Information |
| W3-01 | row colour categories (9, ordered) -- `procengine/classify.py` |
| W3-02 | the 11-tab properties dialog -- `procengine/procwatch.py` |
| W3-03 | DLL + handle lower panes -- `procengine/handles.py`, `modinfo.py` |
| W3-04 | find handle or DLL -- `procengine/findref.py` + `find_dialog.py` |
| W3-05 | signatures -- `procengine/signatures.py` + VirusTotal in the menu |
| W3-06 | restart + run-as -- `procengine/actions.py` + menu entries |

The Qt-free engine is now EIGHTEEN modules: `ntquery`, `rates`,
`details`, `snapshot`, `columns`, `grouping`, `actions`, `cpuinfo`,
`meminfo`, `ioinfo`, `gpuinfo`, `sysinfo`, `classify`, `procwatch`,
`handles`, `modinfo`, `findref`, `signatures`. Every one has a test
asserting it does not import PyQt6.

### Pick up here

**Wave 4** adds the last four Task Manager tabs, each a thin child module
wrapping a widget and registered in `DashboardModule.children`:

- **W4-01 Users** -- per-user resource totals, expandable to that user's
  processes. Reuses the snapshot's per-process `details.user`, summed in
  a grouped view like the Processes tab.
- **W4-02 App history** -- CPU time, network, metered network, tile
  updates. Nothing exists to reuse; the readable per-process CPU times in
  `ntquery` are the only data currently collected, so this starts from a
  fresh data source or a documented "not tracked by Windows here" state.
- **W4-03 Startup apps** -- reuse `startup_reader.py` (registry/startup
  folder/tasks/services/browser extensions) which is already a plain
  scanner; note there is NO impact scoring yet anywhere.
- **W4-04 Services** -- reuse `services_manager.services_module`'s
  module-level `get_services`/`query_service_config`/
  `query_required_by`/`service_action` (WMI-based, COMWorker-only).

**Three tests fail and they are not the Dashboard.**
`test_firewall_rule_actions.py` expects Calculator's MUI string to
resolve; the rule names package 11.2606.0.0, the installed one is
11.2607.0.0, so `SHLoadIndirectString` returns ERROR_NOT_FOUND and the
resolver correctly falls back. The code is right; the test asserts a
machine fact that expired when Calculator updated.

### What to run first

- `pytest tests/ -q` -- 3,936 pass, 3 skip.
- Screenshot harnesses in `scratchpad/` (gitignored):
  `drive_dashboard.py` (launches the real app and walks every tab),
  `shoot_properties.py`, `shoot_lower_pane.py`, `shoot_find.py`,
  `check_colors.py`, `check_highlight.py`.
- **Launch the app, do not only render widgets.** Five of this session's
  bugs were only visible at real size with this machine's real device
  count.

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
- **2026-08-31, W1-06:** `psutil.Process(pid).kill()` returns long before
  the process is gone, so `end_process` waits and re-checks. The rule the
  Apps tab already pays for -- verified, never assumed.
- **2026-08-31, W1-06 (a wrong diagnosis, recorded so it is not repeated):**
  "End process tree" on a python child appeared to kill unrelated processes,
  and the first read was that `psutil.children(recursive=True)` adopts
  strangers by joining on the ppid number. It does not -- the validated walk
  returns the same four. The real cause is that `.venv/Scripts/python.exe` is
  a SHIM: killing the interpreter it launched takes the shim with it, so the
  root is already gone when its turn comes. A tree kill therefore counts an
  already-dead member as ended; reporting that as failure told the user a
  kill had failed while everything was dead.
- **2026-08-31, W1-07 (found by looking at the output, not by a test):**
  rolling an app up to its DESCENDANTS put 60 processes and 6.6 GB under
  "Windows Explorer" -- Steam, WhatsApp and Visual Studio among them. Anything
  launched from the shell inherits explorer.exe as its parent. Task Manager
  groups by app identity, so a member must be a descendant AND the same
  program, matched on image path. Explorer went from 60 processes to 2;
  Chrome still rolls up its 21 correctly.
- **2026-08-31, W1-07:** unelevated, the token cannot classify a single
  system process (all refused), so the "Windows processes" group came out
  EMPTY. Session 0 is the signal that works: it arrives free with the bulk
  syscall, cannot be refused, and is exactly the non-interactive session
  Windows reserves for services. 136 processes classified where 0 were.
- **2026-08-31, W1-08:** absorbing Process Explorer exposed a latent crash in
  it: `on_start` does `app.thread_pool.start(w)` unguarded, and as a
  composite CHILD it is started with whatever app the host was given. It now
  reads service names inline when there is no pool.
- **2026-08-31, W2-01:** `KernelTime` from
  `SystemProcessorPerformanceInformation` ALREADY INCLUDES `IdleTime`, and
  nothing in the API says so. Treat them as separate and an idle machine
  reads as 100% busy on every core -- a graph pinned forever, which is worse
  than no graph. Busy time is `(kernel - idle) + user`.
- **2026-08-31, W2-02:** every figure `GetPerformanceInfo` returns is in
  PAGES except `PageSize`. Raw, the numbers are 4096x too small and still
  look plausible -- 8 GB of commit reads as 2 MB, not as an obvious error.
- **2026-08-31, W2-02 (caught by rendering, not by a test):** the CPU speed
  formatter promotes anything over 1000 MHz to GHz, which is right for a
  processor and wrong for memory: the DDR5 speed rendered as "4.80 GHz",
  a figure nobody quotes and easily misread as the CPU's clock. Memory speed
  has its own formatter now.
- **2026-08-31, W2-03:** opening a raw physical drive with `GENERIC_READ`
  needs elevation -- unelevated, zero of this machine's seven drives opened.
  `IOCTL_DISK_PERFORMANCE` is FILE_ANY_ACCESS, so asking for **zero access
  rights** opens all seven. Measured both ways.
- **2026-08-31, W2-03 (found by rendering):** using a wall clock for the
  interval put a permanent 2-3% ripple on every disk, including ones doing
  nothing -- the drives are polled in a loop, so one `now` taken before it is
  wrong by however long the loop takes, and that error IS the signal when the
  true answer is zero. `DISK_PERFORMANCE` carries its own `QueryTime`; using
  it flattened idle disks to zero and made "active 1% / write 139.9 KB/s"
  agree with itself.
- **2026-08-31, W2-04 (found by rendering):** scaling the network graph
  against the LINK speed means ordinary traffic on a 2.5 Gb/s card is a flat
  line on the floor -- the graph only ever moves during a file transfer. It
  scales to the busiest moment in the visible window instead, which is why
  Task Manager's axis label changes.
- **2026-08-31, W2-04:** loopback is excluded by ADDRESS, not by name.
  "Loopback Pseudo-Interface 1" is the English name only, and a name match
  would quietly start listing it on a localised install.
- **2026-09-01, W2-05 (the measurement that chose the engine):** there is no
  syscall for the GPU the way there is for processors and memory — the
  scheduler's accounting reaches user mode only through PDH. Held OPEN
  across ticks, a full sample of this machine's **483 `GPU Engine`
  instances plus the adapter memory costs 0.33 ms**. PDH keeps the instance
  list and the previous reading inside the query; reopening it per tick
  re-enumerates all 483. Hold the query, close it in `stop()` — it lives in
  the performance-counter service, so an abandoned one outlives the widget.
- **2026-09-01, W2-05:** PDH's first collection of a percentage counter
  RAISES `PDH_INVALID_DATA` rather than returning zeros, which lands exactly
  on the engine's "first sample is None" rule. But the two counter kinds do
  not arrive together: memory in use is instantaneous and answers on the
  first collection, so the first tick legitimately has real memory figures
  and no utilisation. Returning `None` for the whole sample would have
  thrown away half a reading.
- **2026-09-01, W2-05:** an engine TYPE can be backed by several physical
  engines — two Copy engines on this card, and **thirty-three 3D engines on
  the basic render driver**. Instances must be summed across PROCESSES (each
  is one process's share of one engine) but not across physical engines, or
  a class of engine that is at most fully busy reports 3300%. The class
  reads as its busiest member, and the adapter as its busiest class, which
  is also Task Manager's headline definition.
- **2026-09-01, W2-05:** `Win32_VideoController.AdapterRAM` is a signed
  32-bit field. This machine's 24 GB card reports **-1048576** through it.
  `HKLM\SOFTWARE\Microsoft\DirectX` carries a real 64-bit
  `DedicatedVideoMemory`, plus the driver version, feature levels and the
  shared limit — it is where Task Manager's own panel reads them. WMI is
  consulted for the driver DATE alone, joined on the PCI vendor/device ids
  parsed out of `PNPDeviceID` rather than on the adapter's name.
- **2026-09-01, W2-05:** the DirectX key records a feature level only for an
  adapter DirectX has actually INITIALISED. This machine's integrated Radeon
  has never had a display attached, so its subkey carries the identity and
  the memory sizes but no `MaxD3D11FeatureLevel` and no
  `MaxD3D12FeatureLevel` at all. That is a fact about the machine, not a gap
  in the reader — so it is `None` with a reason, and the panel says which.
- **2026-09-01, W2-05:** WARP is excluded by its fixed PCI identity
  (`0x1414`/`0x8C`), not by the string "Microsoft Basic Render Driver",
  which is the English name only. Same trap as the loopback adapter.
- **2026-09-01, W2-05 (found by rendering):** the integrated adapter read
  "Utilisation 0%" beside "No engine is reporting work". Both cannot be
  true. Engines that report zero are a MEASUREMENT — the GPU is idle; no
  engines at all is the ABSENCE of one, and `utilisation` is `None` there.
  The two now say different things.
- **2026-09-01, W2-05 (the check the tests could not do):** idle numbers are
  the easy half, and a counter stuck at a plausible 0.2% forever passes
  every test in the suite. The reader was watched through a real OpenGL
  workload: the discrete card moved 22% → 30% and its dedicated memory rose
  2748 → 2895 MiB, then fell back. `scratchpad/gpu_load_check.py`.
  (Its first version imported PyOpenGL inside `paintGL` — an ImportError in
  a Qt virtual is not a traceback, it is a dead process at exit 127. The
  `paintEvent` rule in CLAUDE.md covers every reimplemented virtual.)
- **2026-09-01, W2-06:** `SYSTEM_PERFORMANCE_INFORMATION` is undocumented and
  has grown across Windows versions, so the layout was verified at BOTH ends
  rather than trusted — the head against `GetPerformanceInfo` (available,
  committed and commit-limit pages all agree exactly) and the tail against
  PDH (context switches 23,851/s vs 23,843/s; system calls 444,024/s vs
  444,270/s; page faults 5,087/s vs 5,090/s). Agreement at both ends is what
  makes the thirty undocumented cache-manager counters in the middle
  believable. Both cross-checks are kept as tests, so a future Windows that
  moves a field is caught rather than silently producing plausible numbers.
- **2026-09-01, W2-06:** the call reports how many bytes it wrote, and a
  reply SHORTER than the struct is refused rather than read. On a build with
  a shorter struct the tail fields would be uninitialised buffer, and
  uninitialised buffer formats as a perfectly ordinary number of context
  switches.
- **2026-09-01, W2-06 (found by rendering, the fifth of these):** the pool
  allocation rows showed **"0 (0 / 0)" beside a paged pool of 1.2 GB**. A
  machine holding 1.2 GB of paged pool has not made zero pool allocations —
  the two readings contradict each other, and the contradiction is the proof
  that the kernel is not maintaining the counter rather than reporting an
  empty pool. Windows agrees: its own `\Memory\Pool Paged Allocs` reads 0
  next to a `Pool Paged Bytes` of 1.34 GB. The row now says "not tracked by
  this Windows build". Free system PTEs looked equally wrong at
  4,288,176,072 and turned out to be REAL — PDH reports 4,288,175,957 — so
  the two had to be told apart by checking, not by how they looked.
- **2026-09-01 (five bugs from ONE session of looking at the running app):**
  the tests were green for all of these. Launching the real `MainWindow`,
  navigating the sidebar and screenshotting each tab found: seven disks
  stacked past the bottom of the window with no scroll; the Overview RAM
  row reading "B/61.6 GB)" because a fixed 60px value label clips
  right-aligned text from the LEFT; a Process Explorer tab that sat empty
  for five seconds; and its GPU column reading 0.0 for every process since
  the day it was added. Rendering a widget in isolation would have caught
  none of them -- they are all about the app at its real size, with this
  machine's real number of devices.
- **2026-09-01:** the cold sweep's cost depends on PRIVILEGE, which the
  wave-1 measurement did not capture. Unelevated, half the processes refuse
  at once and a full sweep is ~141 ms; elevated, nothing refuses and the
  same sweep is **2,252 ms** against 8.5 ms warm. A pane pays that on the
  tick it is opened, which is the tick someone is watching it. Hence the
  cold budget: 60 new resolutions a tick, list first, paths behind it. Any
  measurement of a permission-sensitive path should be taken BOTH ways.
- **2026-09-01:** a `QTimer` does not fire until its first interval has
  elapsed, so `start()`ing a 1 Hz collector buys a guaranteed second of
  empty table. Read once immediately as well.
- **2026-09-01:** `diff_snapshots` decided "changed" from CPU, memory and
  status only. That was harmless while nothing wrote to the GPU column and
  became a bug the moment something did -- a row whose only movement is on
  the GPU never repaints, so the column shows whatever it read the last
  time some other number happened to move. When you start writing to a
  field, check what decides whether it is drawn.
- **2026-09-01:** `psutil.Process(pid).cmdline()` returns an empty LIST for
  the kernel processes rather than raising, so `" ".join(...)` produced
  `""` -- the one value `details.py` promises never to emit. pid 4 has no
  user-mode PEB and therefore no command line, which is a different fact
  from an empty one. A library that answers instead of refusing is its own
  trap: the refusal rule has to be checked at the boundary, not assumed.
- **2026-09-01 (a wrong suspicion, recorded so the method is not lost):**
  the Details tab showed Ascension.exe holding 639,325 handles, which
  looked impossible beside a system total seen at ~521,000 earlier. It was
  CORRECT -- per-process handles summed to 819,630 against a system total
  of 826,100 at the same instant, and the game really is leaking handles.
  Free system PTEs at 4,288,176,072 looked equally broken and was also
  real. The lesson is the one W2-06 already paid for in the other
  direction: a number that looks wrong and a number that is wrong are told
  apart by a second source, never by how they look.
- **2026-09-01, W3-01 (a source that is cheap, wrong, AND contaminating):**
  the `.NET CLR Memory` counter set enumerates the whole machine in 140 ms
  against 1.69 ms per process for a module scan -- and finds **4 processes
  where the scan finds 15**, because .NET Core does not publish the legacy
  counters. Worse, asking PDH for it **loads `mscoree.dll` into the asking
  process**, after which any shim-based detector calls itself .NET forever.
  Found because two tests in one run disagreed about this very process.
  `mscoree`/`mscoreei` are the SHIM, not the runtime; only `clr.dll`,
  `coreclr.dll` and `mscorwks.dll` mean managed code is running.
- **2026-09-01, W3-01:** "hosts a service" matched **0 of 114** service
  hosting processes, because it compared process names against SERVICE
  names -- services are called `wuauserv`, the processes hosting them are
  all `svchost.exe`. `EnumServicesStatusEx` gives the real pid mapping in
  1.3 ms, which is exactly what `SnapshotSource.set_service_pids` was built
  for and what nothing had ever called. Now 113.
- **2026-09-01, W3-01 (dead code that was about to become a regression):**
  the old GPU row tint coloured any row over 0.5% GPU. It had never once
  appeared, because `gpu_percent` was never written to until W2-05 -- so
  fixing that column would have silently started overriding the .NET and
  service tints. A colour nobody has ever seen is not a feature, it is an
  unexploded one. Process Explorer has no GPU category; the column carries
  the number.
- **2026-09-01, W3-01:** "packed" is entropy, and entropy is not evidence.
  At the standard 7.0 threshold it flags OneNote, the Command Palette and
  this tool. It carries its number beside the verdict, ranks below every
  factual category, and is off unless asked for -- 4.11 ms a process, more
  than all the other category facts together.
- **2026-09-01, W3-02:** a properties window OUTLIVES what it watches, in
  two ways that need different answers. A process exiting is not an error:
  stop the timer, keep the last reading on screen, say so in the title --
  blanking to zeros destroys the record of what it was doing. A pid being
  REUSED is the dangerous one, because the window would go on reporting a
  different program under the old one's title. Pinned to
  `(pid, create_time)`, the same key the detail cache uses.
- **2026-09-01, W3-02:** watching ONE process still goes through the bulk
  syscall. `system_processes()` returns all 270 in 2.6 ms, which is
  cheaper than `psutil.Process(pid)` reading the same fields for one. There
  is no cheaper per-process path; the syscall IS the cheap path.
- **2026-09-01, W3-02 (found by rendering):** the dialog's 700x500 default
  was chosen when it had six tabs. Eleven overflowed the tab bar into
  scroll arrows at both ends -- half the window reachable only by
  scrolling a strip of text nobody thinks to scroll. Adding tabs to a
  dialog means re-checking the size it was given for fewer.
- **2026-09-01, W3-03 (a tab that had never once worked):**
  `NtQuerySystemInformation` answers its FIRST call with
  `STATUS_INFO_LENGTH_MISMATCH` by design. With no `restype` declared,
  ctypes returns a SIGNED int, so the status reads `-1073741820`, never
  equals `0xC0000004`, and the buffer-growth retry can never fire. The
  Handles tab therefore showed **zero handles for every process, always** --
  the kernel said this process holds 185 and the pane said 0. Nothing
  about the UI looked broken. Declare `restype` on every ntdll call, and
  be suspicious of any status compared against a `0x8...`/`0xC...`
  constant.
- **2026-09-01, W3-03:** `SystemHandleInformation` (class 16) stores
  `UniqueProcessId` in a **USHORT**. Windows pids are DWORDs and this
  machine is already at 35,612; past 65,535 that field wraps and hands one
  process another's handles. Class 64 is full width for the same 8 ms.
- **2026-09-01, W3-03:** the DLL pane had shown Size, Company and Version
  columns since it was written, all of them hardcoded empty or zero. A
  column of zeros reads as a measurement. If a column cannot be filled,
  it should not be there.
- **2026-09-01, W3-04 (the measurement that a sample cannot make):**
  extrapolating the handle-naming sweep from twelve readable processes
  said 0.5 s. The real sweep took **20 s**, because the cost lives
  entirely in the processes that BLOCK -- and a sample of readable ones
  contains none of them by construction. Corollary: **a per-item deadline
  is not a bound on a loop over items.** Only a total is.
- **2026-09-01, W3-04:** the hang risk and the cost turned out to be the
  same thing. `NtQueryObject(ObjectNameInformation)` never returns on a
  synchronous pipe whose peer is silent, and `GetFileType` identifies a
  pipe without touching the other end. Skipping them took the sweep from
  **5.5 s to 1.2 s** and cut blocking processes from 37 to 2.
- **2026-09-01, W3-04:** counting "we were refused" together with "the
  query blocked" made the number useless -- 17 "refusals" was really 16
  processes we cannot open and 1 that blocked. One is a permission, the
  other is the driver limit; a user can act on the first.
- **2026-09-01, W3-04 (a leak I wrote, and how it hid):** closing the
  target's process handle only on the success path leaked one handle per
  timed-out process. It is self-amplifying -- the leak accumulates in the
  process doing the searching, which then takes longer to search and times
  out more often -- so it presented as a search failing to find a file
  THIS process had open, and only after a few hundred earlier searches.
  Whoever spawns the worker should not own the handle the worker uses.
- **2026-09-01, W3-04:** iterate by handle count, not pid. In pid order a
  truncated sweep always drops the HIGHEST pids, i.e. the most recently
  started processes -- exactly what someone searching for their own
  just-locked file is looking for.
- **2026-09-01, W3-04 (a test worth deleting):** the find DIALOG had a
  test asserting it could find a file this process held open. It passed
  alone and failed after the engine suite, because under pytest this
  process holds hundreds of handles and earlier tests leave blocked
  naming threads behind, so it is sometimes among the handful whose
  naming blocks -- and a process that cannot name its own handles cannot
  find its own file. The engine test covers the same behaviour
  deterministically. Duplicating an end-to-end assertion at a second
  layer bought flakiness and no coverage.
- **2026-09-02, W3-05:** `WinVerifyTrust` returns its HRESULT through a
  ctypes `c_long`, so on success it is 0 and every failure is NEGATIVE.
  Comparing an undeclared call's return against the `0x8...`/`0xC...`
  trust constants NEVER matches -- `TRUST_E_NOSIGNATURE` reads as
  `-2146762752`, not `0x800B0100` -- and every status fell through to
  "could not verify". This is the same bug W3-03 recorded for the handle
  syscall, showing up in a different shape: there the unsigned int was
  compared against a negative; here the signed long is compared against
  positive constants. Mask `& 0xFFFFFFFF` before any comparison.
- **2026-09-02, W3-05:** the signer is the LEAF of the embedded
  certificate chain, and it is found structurally, not by position.
  `CryptQueryObject`'s store enumerates CA-first and some files embed
  their root -- for Git for Windows the enumeration is [PCA, intermediate,
  signer, root] -- so neither "first" nor "last" is reliable. The signer
  is the one certificate that is not itself the issuer of any other
  certificate in the store. Two lines, and it survives chains of any
  length.
- **2026-09-02, W3-05 (found by cross-checking, the W2-06 lesson in the
  other direction):** Git for Windows' signing certificate lapsed in May
  2026, and its binaries now read `0x800B0101` (`CERT_E_EXPIRED`) from
  WinVerifyTrust. It is NOT a refusal -- the file WAS signed and the
  signature has lapsed, which is a verdict the user can act on. Mapping
  it to "could not verify" would hide that the signature expired; the
  expiry is the answer. Cross-checked against PowerShell's
  `Get-AuthenticodeSignature`, which agrees the certificate is out of
  validity period.
- **2026-09-02, W3-05 (a machine fact asserted by its absence):** an
  unsigned file is a STATUS (`not_signed`), not a fall-through. Finding a
  genuinely unsigned, genuinely valid PE on a real machine is harder than
  it sounds -- Git's `cygwin-console-helper.exe` is one, and its test
  skips rather than asserting a machine fact a vendor update could
  quietly change. The malformed-PE case is asserted for what it is: a
  refusal with a reason, never a claim of "unsigned".
- **2026-09-02, W3-06:** "restart" can only honestly mean "end the old
  process, verified gone, and ask Windows to start its executable again
  with the same command line." Whether the new instance runs as the same
  account, or keeps a window state, or survives at all, is not knowable
  from one call -- so the engine claims none of it. ShellExecute's verdict
  (>32 accepted, <=32 an error code like 5=access denied) is the only
  launch truth available, and the code says exactly that.
- **2026-09-02, W3-06:** a command line is rebuilt with
  `subprocess.list2cmdline`, never `" ".join`. The latter is exactly what
  breaks a path containing spaces -- the flaw `elevated_helper.py`
  already documents in `core/admin_utils.py`. psutil hands back a parsed
  argv list, which is a lossless way to get quoting back.
- **2026-09-02, W3-06:** `run_as` and `restart` deliberately do NOT
  reproduce the original's working directory or user token. Reading cwd
  via `psutil.Process(pid).cwd()` is cheap but was never collected, and
  re-running as the logged-on user is what "run as administrator" means --
  ShellExecute's `runas` verb is the feature, not an approximation.
