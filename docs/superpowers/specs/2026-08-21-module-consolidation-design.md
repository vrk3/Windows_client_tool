# Module Consolidation — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #10 — Sidebar consolidation and the composite module
**Date:** 2026-08-21
**Status:** Awaiting review

---

## 1. Overview

The app registers 41 modules. Fifteen of them sit in `TOOLS`, which has become the
drawer everything lands in, and six more modules exist as source files that nothing
imports. Several features are reachable twice by two different implementations, one of
which is always the worse one.

This spec introduces a single mechanism — `CompositeModule`, a `BaseModule` that hosts
other `BaseModule`s as tabs — and expresses five separate consolidations as declarations
against it. The sidebar goes from 41 entries to 34 and `TOOLS` from 15 to 10, no feature
is lost, and six diagnostic search providers that are currently unreachable from global
search come back.

### 1.1 What is actually wrong today

Each of these was confirmed in the code, not inferred:

| Finding | Evidence |
|---|---|
| Six modules are dead source | `cbs_log`, `dism_log`, `event_viewer`, `reliability`, `crash_dumps`, `windows_update` each ship a `*_module.py` that `main.py` never registers. Only their own tests import them. Diagnose imports their *parsers*, not their widgets. |
| Duplicate-finding exists twice, the worse one is on the sidebar | `duplicate_finder_module.py:221` MD5-hashes every file in full. `treesize/store/duplicates.py` groups by size, then hashes a 64 KB head, then BLAKE2b — and never hashes a file whose size is unique. |
| The HOSTS editor exists twice | `hosts_editor` module, and a "HOSTS Editor" tab at `net_extras_module.py:100`. |
| Six log sources are invisible to global search | `diagnose_module.py:404` returns `None` from `get_search_provider` — "unified search is local to the widget". `CBSSearchProvider`, `DISMSearchProvider`, `EventViewerSearchProvider`, `ReliabilitySearchProvider`, `CrashDumpSearchProvider` and `WUSearchProvider` are all constructed and wired to nothing global. `filter_panel.py:19` still lists all six as filterable sources, so the filter offers sources that can return nothing. |

### 1.2 The reuse direction, corrected

The obvious reading of "make Diagnose reuse the six orphaned widgets" is backwards.
`cbs_module.py` is the *older, thinner* implementation: no Refresh button, no lazy load,
no unified search. Diagnose's `_build_tab_widget` (`diagnose_module.py:100`) is the one
worth keeping. So the dedupe runs outward from Diagnose: extract its pane into a shared
component, rebuild the six modules on top of it, and let Diagnose host those modules.

### 1.3 Recorded decisions

Settled during brainstorming; not open questions.

| Decision | Choice |
|---|---|
| Merge depth | True merge into tabs, not a sidebar regroup |
| Boot host identity | Startup Manager, renamed "Startup & Boot" |
| Duplicate Finder | Deleted outright; TreeSize's duplicates view is the one |
| Session log cap | Keep the newest 20, alongside the existing 30-day rule |
| Admin-gated child | Disabled tab carrying the reason, not a hidden tab |

---

## 2. `CompositeModule`

New file `src/core/composite_module.py`. A `BaseModule` subclass that owns an ordered
list of child `BaseModule` instances and presents them as a `QTabWidget`.

```python
class CompositeModule(BaseModule):
    children: list[BaseModule]   # declared by the subclass, in tab order
```

### 2.1 Widget construction

`create_widget()` builds the `QTabWidget` and adds one placeholder page per child. A
child's real widget is built on first show of its tab, not upfront — the pattern
`DiagnoseModule` already uses, and the reason app startup does not pay for 34 modules'
worth of widget construction. The tab label is `f"{child.icon} {child.name}"`.

### 2.2 Lifecycle forwarding

| Host call | Forwarded to |
|---|---|
| `on_start(app)` | every child, in order; a child that raises is logged, its tab disabled, and the others continue |
| `on_activate()` | the visible child only |
| `on_deactivate()` | the visible child only |
| `on_stop()` | every child that was started |
| tab change | `on_deactivate()` on the outgoing child, then `on_activate()` on the incoming one |

The tab-change rule is what keeps a hidden child's refresh timer from running. Getting
this wrong is invisible in tests and shows up as an app that polls WMI for three
modules at once, so §7 tests it directly.

### 2.3 Admin gating

The registry currently drops a `requires_admin` module entirely when unelevated
(`module_registry.py:39`). A composite is registered whenever *any* child is available:
the host's own `requires_admin` is always `False`, and each child that requires
elevation without it gets a disabled tab reading
`"{name} requires administrator privileges."` — the same wording `main_window.py:170`
already uses. A composite whose children are all gated shows one such page and no tabs.

### 2.4 Search

`BaseModule` gains `get_search_providers() -> list[SearchProvider]`, defaulting to
`[self.get_search_provider()]` minus the `None`. `ModuleRegistry.start_all` registers
every provider a module returns instead of just one. `CompositeModule` overrides it to
return its children's providers.

This replaces the wrapper-provider idea the design first carried. A wrapper would hold
six providers behind one `module_name`, and `search_engine.py:38` filters *per provider*
on that single string — so the wrapper would have to re-implement the engine's own
source-skipping internally and could drift from it. Returning a list keeps each
provider's `module_name` visible to the engine, so `filter_panel.py:19`'s six sources
filter correctly with no new logic anywhere. It is also what restores the six diagnostic
sources to global search.

### 2.5 Navigation by name

`main_window._navigate_to_module(name)` resolves a name against the sidebar
(`main_window.py:342`), and the `NAV_REQUEST_MODULE` event and command palette both go
through it. A child that is no longer a sidebar entry would become unreachable by name.

The composite therefore publishes a route map — `{child.name: (host.name, tab_index)}` —
which `MainWindow` consults when a name misses the sidebar: it selects the host, then
the tab. `dashboard_module.py:255` navigating to "Quick Cleanup" is the existing caller
that proves the path is live; the command palette gains the child names as entries that
route the same way.

The registry holds one merged map built from every composite, plus a small static alias
table for names that survive their module — currently just
`"Duplicate Finder" → ("TreeSize", duplicates view)`, which is a retired name pointed at
a non-composite host rather than a child tab (§3.5). One lookup, two sources; a name in
neither is a miss, logged, and navigation is a no-op as it is today.

---

## 3. The five consolidations

### 3.1 Diagnose ← the six log modules

Extract `_build_tab_widget` and its load/error/progress plumbing from
`diagnose_module.py` into `src/ui/log_pane.py` as a `LogPane` widget: table + detail
panel + error banner + progress + Refresh, parameterised by a loader callable and
optional extra toolbar controls.

Each of the six modules is then rewritten as a thin `BaseModule` — metadata, a `LogPane`
built around its existing parser/reader, and its existing search provider. Their parsers,
readers and providers are untouched. `DiagnoseModule` becomes a `CompositeModule` whose
children are the six, keeping its name, icon and its cross-tab search bar.

Net effect: one pane implementation instead of two, six modules alive again, the same
six tabs on screen, and six providers back in global search.

### 3.2 Network Diagnostics ← Wi-Fi Analyzer, Hosts Editor, Network Extras

`NetworkDiagnosticsModule` keeps its current widget as its own first tab (it does not use
tabs today, so it is wrapped as-is) and becomes a `CompositeModule`. Network Extras loses
its duplicate "HOSTS Editor" tab (`net_extras_module.py:100`); the standalone
`hosts_editor` module is the surviving editor and becomes a sibling tab. Network Extras
keeps DNS Switcher, Proxy Settings and Quick Actions.

### 3.3 Startup & Boot ← Startup Manager, Boot Analyzer, Power & Boot

`StartupModule` is renamed "Startup & Boot" and becomes the host. It already builds its
own `QTabWidget` (`startup_module.py:363`), so its existing widget becomes the first tab
and Boot Analyzer and Power & Boot join as siblings. `group` moves to `SYSTEM`.

### 3.4 Debloat ← Store Apps

`DebloatModule` already hosts tabs (`debloat_module.py:67`). Its existing widget becomes
the first tab; `StoreAppsModule` becomes a sibling. Debloat's curated-blocklist view and
Store Apps' all-packages view stay distinct — the merge is about where they live, not
what they show.

### 3.5 Duplicate Finder — deleted

`src/modules/duplicate_finder/` and its tests are removed. TreeSize's duplicates view is
the replacement and needs no change. This is the one consolidation that removes a
capability from where a user might look for it, so TreeSize's description gains
"duplicate files" and the command palette keeps "Duplicate Finder" as a route to
TreeSize's duplicates view via the §2.5 route map.

---

## 4. Session log retention (independent of the above)

`logging_service.py:130` writes one log per launch beside the exe; rotation is 30 days
only (`app.py:77`). 101 files accumulated in the repo root in two days of development.

`log_rotation.rotate_old_files` gains a sibling, `keep_newest(directory, glob, count)`,
applied to the session-log directory with `count = app.log_retention_count`, default 20.
Both rules run; either may delete. `0` keeps everything, matching the existing
`retention_days` convention. The shared-folder collection design in that docstring is
unaffected — a machine still drops its logs in one place, just fewer of them.

---

## 5. What is explicitly not in scope

- Any change to a parser, reader, scanner or search provider's behaviour
- The `TOOLS` entries not named above (Env Vars, Quick Fix, Registry Explorer, Remote
  Tools, Shared Resources, Software Inventory, System Report, TreeSize, Updates, About)
- `debloat_module.py:61`'s hardcoded dark stylesheet, which ignores the theme manager —
  real, but not this spec's problem
- The 25 tracked `__pycache__/*.pyc` files noted in the TreeSize ledger

---

## 6. Module inventory after this work

Counted from `main.py`'s 41 `register()` calls, not estimated.

| Group | Before | After | Change |
|---|---|---|---|
| OVERVIEW | 1 | 1 | |
| DIAGNOSE | 3 | 3 | the six log modules become Diagnose's children but were never registered |
| SYSTEM | 6 | 6 | −Boot Analyzer, +Startup & Boot moving in from MANAGE |
| MANAGE | 9 | 7 | −Store Apps, −Startup Manager |
| OPTIMIZE | 6 | 6 | |
| TOOLS | 15 | 10 | −Duplicate Finder, −Power & Boot, −Wi-Fi Analyzer, −Hosts Editor, −Network Extras |
| PROCESS | 1 | 1 | |
| **Registered total** | **41** | **34** | |

Six sidebar entries become tabs; one (Duplicate Finder) is deleted.

---

## 7. Testing

Every item below is a test that fails before its change and passes after.

**`CompositeModule` (new `tests/test_composite_module.py`)**

1. Children are built lazily — constructing the host builds no child widget; showing a
   tab builds exactly that one.
2. Switching tabs calls `on_deactivate` on the outgoing child and `on_activate` on the
   incoming one, in that order.
3. `on_stop` reaches every started child, including ones whose tab was never shown.
4. A child raising in `on_start` disables only its own tab; siblings still start.
5. An admin-gated child unelevated yields a disabled tab, and the host still registers.
6. `get_search_providers()` returns every child's provider, each keeping its own
   `module_name`, and `ModuleRegistry.start_all` registers all of them.
7. The route map resolves every child name to its host and tab index.

**Consolidations**

8. `LogPane` renders and loads through a stub loader, with the error path banner-tested.
9. Each of the six diagnostic modules exposes its provider through Diagnose's aggregate —
   the regression in §1.1, asserted per source.
10. `filter_panel._ALL_SOURCES` and the set of `module_name`s reachable from the
    registry agree. This is the test that would have caught the current bug.
11. Registered module count is 34 and no two share a `name`.
12. Nothing imports `modules.duplicate_finder`.

**Retention**

13. `keep_newest` deletes the oldest beyond the count, keeps the newest, and is a no-op
    at `0` and when the directory is short.
14. Both rules composed: a file that is old *and* within the newest 20 is still deleted.

**Whole-app**

15. The existing `tests/test_integration.py` startup path stays green — the real check
    that the registry, sidebar and stack still agree after seven entries move.

Baseline to preserve: 1332 passed, 3 skipped, 1 warning (`PytestCollectionWarning` in
`test_integration.py:16`, pre-existing). Warning counting requires clearing
`__pycache__` first.

---

## 8. Phasing

Ordered so that each phase leaves the app runnable and the suite green.

| Phase | Work | Risk |
|---|---|---|
| 1 | `CompositeModule` + `get_search_providers` + route map, with tests. No module changes. | Low — nothing uses it yet |
| 2 | Session log retention (§4). Independent of everything else. | Low |
| 3 | Delete Duplicate Finder (§3.5). | Low |
| 4 | Debloat ← Store Apps (§3.4) — the smallest real merge, proves the mechanism | Medium |
| 5 | Startup & Boot (§3.3) | Medium |
| 6 | Network Diagnostics (§3.2), including the duplicate HOSTS tab removal | Medium |
| 7 | `LogPane` extraction + the six modules + Diagnose (§3.1) | High — largest, and the search regression fix lands here |

Phase 7 is last because it is the only one that rewrites working UI rather than moving
it, and because phases 4-6 will have exercised `CompositeModule` against three different
shapes of child by the time it starts.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| A merged child's widget assumed it owned the whole pane (margins, splitter sizes, its own toolbar) and looks wrong in a tab | Each merge phase ends with the app run and the pane looked at — the ledger's standing rule that a green suite proves nothing |
| Hidden tabs keep polling, tripling WMI load | §2.2 tab-change forwarding, asserted by test 2 |
| A name-based navigation caller is missed and dies silently | §2.5 route map, asserted by test 7; `grep` for `NAV_REQUEST_MODULE` and palette callers during phase 1 |
| `LogPane` extraction quietly drops a Diagnose behaviour (lazy load, error banner, cross-tab search) | Phase 7 keeps `DiagnoseModule`'s search bar untouched and diffs the six tabs against the current build by eye |
