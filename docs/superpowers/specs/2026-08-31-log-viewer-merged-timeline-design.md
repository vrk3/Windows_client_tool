# Log Viewer Merged Multi-Log Timeline — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** Log Viewer upgrades, chunk 4 of 4
**Date:** 2026-08-31
**Status:** Approved

---

## Context

Chunks 1–3 are done and merged (`f60d00b`, `2a452dc`, `bbac84d`, `e8e13ce`).
This is the last of the four, and the chunk-1 spec called it the heaviest and
the biggest capability gap for real update troubleshooting: a Windows
servicing failure is told across CBS, DISM, setupact and ReportingEvents at
once, and reading them one at a time means holding four clocks in your head.

It also carries a directly requested feature: **open every log in a folder**.
That is the same capability with a folder as its entry point, so the two are
built together.

### Decisions taken, not to be re-derived

- **Folder scan takes top-level `*.log` and `*.lo_`.** Not recursive: the
  folders that matter (`C:\Windows\Logs\CBS`, a ConfigMgr `Logs` directory)
  are one flat pile, and recursing `C:\Windows\Logs` would open several
  hundred files and a few hundred MB by accident.
- **"Load earlier" pages EVERY truncated source one step**, then re-merges,
  so the merged timeline extends backwards as a whole.

### What is already true, and must not be re-derived

- `entry.source` is **the Component**, not the file — the Component column
  reads it, and `components()` is built from it. A Source column needs its own
  field.
- Continuation lines carry no timestamp of their own. 9,185 of the big CBS
  archive's 90,714 records are continuations, and one CSI block runs to 1,260
  of them.
- Parsing runs at ~26 MB/s; `_reindex()` over 134,527 records costs 0.05 s.
- `ReportingEvents.log` is UTF-16 LE. Each source is sniffed independently by
  its own `LogReader`, so a merged set spans several encodings at once.

---

## 1. `log_set.py` — N readers behind one interface

A new Qt-free module beside `log_reader.py`. `LogSet` owns one `LogReader`
per path and exposes the same shape the pane already uses, but returns parsed
**entries** rather than text:

```
LogSet(paths, max_bytes=DEFAULT_MAX_BYTES, include_rolled=False)
    read_new()      -> list[LogEntry]      merged, tagged
    has_earlier()   -> bool                any source has
    read_earlier()  -> list[LogEntry]      the WHOLE merged set, rebuilt
    entries()       -> list[LogEntry]      everything accumulated, merged
    sources()       -> list[str]           basenames, menu order
    earlier_bytes() -> int                 summed across sources
```

Entries are returned rather than text because the merge key is the timestamp,
which does not exist until the text has been parsed. `LogReader` is untouched:
it already does everything one source needs.

Each entry is tagged with its file in `raw["log"]` — never in `entry.source`,
which is spoken for.

## 2. The merge key

Per source, in file order, each entry is given an **effective timestamp**: its
own if it has one, otherwise the one inherited from the record above it in
that same file. Sources are then interleaved with `heapq.merge` on
`(effective timestamp, source index, position in source)`.

Two properties this buys, both load-bearing:

- **A continuation sorts immediately after its parent**, wherever that parent
  lands. Sorting continuations on their own (absent) timestamps would scatter
  a 1,260-line CSI block across the whole timeline.
- **File order is authoritative within a log; timestamps only decide between
  logs.** Real logs are not perfectly monotonic, and `heapq.merge` preserves
  each input's own order, so a log's internal sequence is never rearranged by
  its own clock.

An orphan continuation at the head of a truncated slice has nothing to inherit
from and takes the epoch, so it sorts to the front of its source rather than
being dropped.

## 3. Reading budget

In merged mode each source is given `max_bytes // len(paths)`, floored at
2 MB. Twelve logs therefore read ~32 MB in total rather than 384 MB, and Open
stays near a second instead of scaling with the size of the pile. A single
log keeps the full 32 MB window, so nothing about chunk 3 changes.

## 4. Model: a Source column and a Source filter

`COLUMNS` becomes `Time | Source | Severity | Component | Thread | Message`:
when, from which log, how bad, from which component. The column is always
defined — so no index shifts under the delegate — and hidden by the pane while
a single log is open.

A **Source** combo joins Component and Thread to isolate one log inside the
merged view. That is one more axis in `_matches`, the same shape as the two
already there.

`LogModel.replace(entries, keep_oldest=False)` is added for the re-merge path:
it resets to a finished list and trims to the cap from whichever end the
caller names, counting what it dropped into `dropped` or `unloaded_newer`.

## 5. Paging and following with N readers

**Load earlier** steps every truncated source once and then **re-merges from
scratch**, rather than prepending. A prepend would be wrong: source A's
earlier chunk is older than A's own loaded part but not necessarily older than
what is already loaded from B, so it does not belong at the front. After the
re-merge the result is trimmed to the 200,000 cap **from the newest end** —
exactly the sliding-window semantics chosen in chunk 3, one layer up.

**Follow** polls every source each tick and appends that tick's records merged
among themselves. A known and accepted limitation: a slow-writing log can
deliver a record older than one appended on the previous tick, so ordering at
the live tail can be off by up to one poll. Re-sorting 200,000 records every
second to correct that is not affordable, and following a merged set is the
least likely thing to be doing while investigating.

## 6. Open menu

Two entries are added:

- **"CBS — largest archive on disk"**. The existing entry offers the *newest*
  archive, which is routinely the smallest — 15 MB here against the 363 MB one
  that actually holds the history. Reachable today only via Browse….
- **"Open folder…"**.

## 7. Testing

- **The merge key**, headless: a continuation block spanning two sources stays
  intact; a non-monotonic source is not reordered by its own clock; an orphan
  continuation is not dropped.
- **The budget**: twelve paths do not read twelve full windows.
- **Crossing two interactions**, the shape that has caught every real defect
  here: filter → open a folder; follow → load earlier while merged; open a
  folder → open a single log (the Source column must hide again and no stale
  source filter may survive).
- **Real data**: `tools/log_viewer_real_check.py` merges this machine's real
  CBS + DISM + setupact + ReportingEvents — four files, four encodings, one of
  them UTF-16 — and asserts no record is lost and every continuation still
  sits under its parent.
- **Then render it and look at it**, in both themes. That is what found both
  defects in chunk 3, neither of which any test saw.

## 8. Known gap: the CMTrace path is still unvalidated

Swept on 2026-08-31: `C:\Windows\CCM`, `C:\Windows\ccmsetup`, the Intune
Management Extension folder, `C:\Program Files` and `C:\ProgramData` contain
**zero files carrying the `<![LOG[` marker**. There is no ConfigMgr client and
no Intune extension on this machine, so the CMTrace parser — the reason a
CMTrace-style viewer exists — has still never read a genuine one. The
synthetic fixtures are not evidence of this. Recorded here rather than left
implicit; it needs a real log file dropped into the repo to close.
