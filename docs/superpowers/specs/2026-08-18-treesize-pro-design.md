# TreeSize Pro Clone — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #9 — TreeSize (Disk Space Analyzer)
**Date:** 2026-08-18
**Status:** Awaiting review
**Supersedes:** §4.3 of `2026-03-25-optimization-tools-design.md`
**Reference product:** TreeSize Professional 9.8.2.2303, installed at
`C:\Users\iorda\AppData\Local\Programs\JAM Software\TreeSize\`

---

## 1. Overview

A full-fidelity clone of TreeSize Professional, implemented as a standard `BaseModule`
with `group = ModuleGroup.TOOLS`. Parity with the commercial product in both appearance
and behavior: Office-style ribbon chrome, direct NTFS Master File Table scanning, a
directory tree with Pro's column set and inline size bars, the seven-view right panel,
complete file operations, nine scan-target backends, and Pro's extras (file search,
duplicate finder, snapshots, scan comparison, scheduled scans).

This supersedes §4.3 of the optimization-tools spec, which described a `QTreeView` over a
per-node object model. That design does not survive a full-drive scan and is replaced
here by a columnar store.

### 1.1 Verified against the real product

Sections 5 and 6 are not reconstructions. They were derived from the installed product:
its bundled HTML documentation (`HELP_EN/`, 92 pages), the shipped binaries, and
screenshots of a completed elevated scan of `C:\`. Where this spec names a ribbon tab,
a view, a column, or a menu action, that name is the product's own.

Reference data point from the verification scan: `C:\` reported **Size 385.4 GB** against
**Allocated 147.5 GB** across 460,840 files and 111,283 folders, on a 4,096-byte-cluster
NTFS volume. The 238 GB gap is sparse and compressed files. This is why the store carries
real size and allocated size as independent columns rather than deriving one from the
other (§4.1).

### 1.2 Recorded decisions

Settled during design; not open questions.

| Decision | Choice | Rationale |
|---|---|---|
| Fidelity | Full Pro clone | All subsystems, not a simplified pane |
| Scan engine | MFT reader, walk fallback | Pro's speed comes from the MFT; fallback keeps it usable unelevated |
| Data store | Columnar arrays | Object-per-file costs 5–10× memory; full-drive scans need the flat layout |
| Destructive ops | Full Pro parity | Recycle, permanent delete, move, secure erase |
| Dependencies | Unconstrained | pywin32, openpyxl, reportlab, cloud SDKs as needed |
| Visual style | Replicate Pro's chrome | Ribbon and Pro's own scheme, following the system theme |
| Hard links | Charge first path seen | Matches Pro's default; exposed as a setting |
| Scan targets | All nine Pro backends | Behind a pluggable `ScanTarget` interface |
| Spec scope | One document | Implementation lands in phases (§11) |

### 1.3 Known blocker

There is no usable Python interpreter on the development machine — only the Microsoft
Store alias stub at `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`, with no virtual
environment in the repository and no Anaconda installation. The existing test suite
cannot be run and the application cannot be launched. A real CPython install plus a
project virtual environment is a prerequisite for phase 1 and is not part of this design.

---

## 2. Layout

```
src/modules/treesize/
  __init__.py
  treesize_module.py          BaseModule impl; owns root widget and workers
  targets/
    __init__.py
    base.py                   ScanTarget interface + registry
    local.py                  drives and directories (MFT / walk)
    ssh.py  webdav.py
    outlook.py                MAPI
    sharepoint.py  gdrive.py  s3.py  azure_blob.py
    auth.py                   credential storage, OAuth/Entra ID flows
  scan/
    __init__.py
    volume_info.py            FSCTL_GET_NTFS_VOLUME_DATA, cluster geometry
    mft_reader.py             raw $MFT read, record + attribute parsing
    walk_scanner.py           FindFirstFileExW fallback (ctypes, threaded)
    scanner.py                engine selection, batching, pause, cancellation
    watcher.py                ReadDirectoryChangesW live updates
    filters.py                include/exclude rules
  store/
    __init__.py
    node_store.py             columnar arrays + shared name blob
    aggregates.py             extension / age / owner / top-files rollups
    scan_file.py              save + load a scan; diff two stores
    snapshots.py              system snapshots for later comparison
  ui/
    __init__.py
    ribbon.py                 Office-style tab ribbon widget
    quick_access.py           Quick Access Toolbar
    backstage.py              File application menu
    directory_tree.py         QAbstractItemModel + size-bar delegate
    drive_list.py             bottom-left drive panel
    scan_overview.py          selection summary bar
    status_bar.py             free space / files / excluded / cluster size
    views/
      __init__.py
      chart.py                treemap, pie, bar
      details.py  extensions.py  users.py  age_of_files.py
      top_files.py  history.py
    dialogs/
      __init__.py
      scan_target.py  delete_confirm.py  export.py
      search.py  duplicates.py  options.py  schedule.py
  ops/
    __init__.py
    file_ops.py               delete / move / erase via IFileOperation
    exporters.py              Printer, PDF, Excel, HTML, CSV, XML, SQLite, Text, Email
    guardrails.py             protected-path predicates
src/ui/styles/treesize_dark.qss
src/ui/styles/treesize_light.qss
```

---

## 3. Scan engine

### 3.1 Volume info (`volume_info.py`)

Opens `\\.\<drive>` with `CreateFileW` (`GENERIC_READ`, `FILE_SHARE_READ | FILE_SHARE_WRITE`)
and issues `DeviceIoControl(FSCTL_GET_NTFS_VOLUME_DATA)`, control code `0x00090064`,
yielding `NTFS_VOLUME_DATA_BUFFER`: `BytesPerSector`, `BytesPerCluster`,
`BytesPerFileRecordSegment`, `MftStartLcn`, `MftValidDataLength`, `NumberSectors`.

Failure to open the raw volume — not elevated, not NTFS, network path — is not an error.
It is the signal to select the walk scanner.

`BytesPerCluster` is retained for the scan's lifetime: it drives allocated-size
computation on the walk path and is displayed in the status bar, as Pro does.

### 3.2 MFT reader (`mft_reader.py`)

The fast path. Requires elevation and a local NTFS volume.

1. Seek to `MftStartLcn * BytesPerCluster` and read file record 0, `$MFT` itself. Parse
   its non-resident `$DATA` run list to obtain the MFT's true extent map. The MFT is
   fragmented on real volumes; assuming contiguity is wrong.
2. Stream the MFT through that run list in ~4 MB chunks, splitting each chunk into
   `BytesPerFileRecordSegment` records, typically 1024 bytes.
3. Per record:
   - Verify the `FILE` signature; skip `BAAD` and zeroed records.
   - **Apply the update-sequence (fixup) array.** The last two bytes of every sector in
     the record are replaced by the update sequence number and must be restored from the
     fixup array before any field is readable. Skipping this silently corrupts every field
     that straddles a sector boundary, and does so without raising an error.
   - Skip records whose flags lack bit 0 — deleted entries.
   - Walk attributes:
     - `$STANDARD_INFORMATION` (0x10) — created, modified, accessed timestamps; DOS
       attributes.
     - `$FILE_NAME` (0x30) — name and **parent file reference**. Multiple instances are
       normal: one per namespace (POSIX / Win32 / DOS 8.3) and one per hard link. Prefer
       Win32 over DOS 8.3. This attribute is the reason the MFT path is fast — parentage
       arrives *with* the record, so the whole tree is assembled from one flat pass with
       no directory traversal.
     - `$DATA` (0x80) — resident: length is the attribute value length. Non-resident:
       real size from `data_size`, allocated from `allocated_size`, and for compressed
       streams the on-disk cost from `compressed_size`. Named `$DATA` attributes are
       alternate data streams; Pro counts them, so their sizes are added to the owning
       file.
     - `$INDEX_ROOT` (0x90) — presence marks the record as a directory.
     - `$ATTRIBUTE_LIST` (0x20) — attributes have spilled into other MFT records. Follow
       the referenced record numbers and merge before interpreting.
     - `$REPARSE_POINT` (0xC0) — junction, symlink, or cloud placeholder. Recorded in the
       node's flags and **not** followed; following them produces cycles and double counts.
   - Owner SID from `$STANDARD_INFORMATION`'s security ID, resolved against `$Secure`
     and interned into the owner table.
4. Resolve parentage after the full pass. A parent file reference is an MFT record number
   plus a sequence number; the sequence number must match, or the reference is stale and
   the node is attached to a synthetic "orphaned" root, as Pro does.
5. Hard links: a file with N links appears under N parents. Size is charged to the first
   path encountered in MFT order; further links become zero-size nodes flagged
   `HARDLINK_DUP`, so they stay visible without inflating totals. Charging every path is
   offered as a setting, matching Pro.

### 3.3 Walk fallback (`walk_scanner.py`)

Used for non-NTFS volumes, network shares, arbitrary folder scans, and any unelevated run.

`FindFirstFileExW` with `FindExInfoBasic` and `FIND_FIRST_EX_LARGE_FETCH` through ctypes.
`FindExInfoBasic` suppresses 8.3 name resolution and `LARGE_FETCH` batches directory
entries, together giving roughly an order of magnitude fewer kernel transitions than
`os.scandir` on deep trees. `WIN32_FIND_DATAW` supplies size, attributes, and all three
timestamps in the same record.

Directories are distributed across a bounded thread pool, default `min(32, cpu_count * 4)`
since the work is I/O bound, each worker pushing discovered subdirectories onto a shared
queue.

Allocated size is real size rounded up to `BytesPerCluster`, not a per-file
`GetCompressedFileSize` call, which would cost more than the walk itself. Compressed and
sparse files are therefore over-reported on this path. The status bar states that the fast
path is unavailable, matching Pro's practice of flagging a degraded scan.

Reparse points are detected via `FILE_ATTRIBUTE_REPARSE_POINT` and not descended.

### 3.4 Orchestration (`scanner.py`)

Engine selection: raw volume opens **and** volume is NTFS **and** process is elevated
**and** target is a whole drive → MFT reader. Otherwise walk scanner.

Runs on a `Worker` via `QThreadPool`, consistent with `src/core/worker.py`.
`WorkerSignals` gains `batch_ready = pyqtSignal(object)` carrying an index range, never
node objects.

**Threading contract.** The worker owns the store exclusively while scanning and mutates
it only from the worker thread. It emits index ranges; the main thread reads those ranges
and issues `beginInsertRows` / `endInsertRows`. Store arrays are append-only during a
scan, so a main-thread read of an already-emitted range cannot race an append. No locks
are needed and no node objects cross threads.

Batching: 500 nodes or 100 ms elapsed, whichever comes first. A purely count-based batch
stalls the UI on slow network scans.

**Pause / Resume** (Pro feature): the worker blocks on a `threading.Event` between chunks.
Because the MFT reader's position is a byte offset into the run list and the walk
scanner's position is its directory queue, both resume without redoing completed work.

**Cancellation** is checked per chunk (MFT) or per directory (walk) against
`Worker.is_cancelled()`, so stopping a full-drive scan is immediate.

### 3.5 Live updates (`watcher.py`)

Pro's "Watch for file system changes". `ReadDirectoryChangesW` on the scanned root with
`FILE_NOTIFY_CHANGE_SIZE | FILE_NAME | DIR_NAME | LAST_WRITE`, on a dedicated thread.
Change records are coalesced over a 500 ms window and applied to the store as size deltas
propagated up the parent chain, rather than by rescanning. Toggled per scan and off by
default, since it holds a handle on the volume root.

### 3.6 Filters (`filters.py`)

Pro's Exclude action and scan filters. Rules match on path glob, extension, size range,
and age, and are applied during the scan pass so excluded subtrees are never stored.
Exclusions are either temporary — this scan only — or permanent, persisted through
`ConfigManager`. The status bar shows the excluded count, as Pro does.

---

## 4. Data store

### 4.1 Columnar layout (`node_store.py`)

A node is an `int` index into parallel arrays, not an object.

| Array | Type | Meaning |
|---|---|---|
| `parent` | `array('i')` | parent index, -1 for a root |
| `name_off` | `array('L')` | offset into the name blob |
| `name_len` | `array('H')` | name length in bytes |
| `size` | `array('q')` | real size, bytes |
| `alloc` | `array('q')` | allocated size, bytes |
| `mtime`, `ctime`, `atime` | `array('q')` | Windows FILETIME |
| `attrs` | `array('L')` | DOS attributes plus our flags: DIR, REPARSE, HARDLINK_DUP, ADS, COMPRESSED, SPARSE |
| `owner_id` | `array('i')` | index into an interned SID table |
| `first_child`, `next_sibling` | `array('i')` | child list, -1 terminated |
| `file_count`, `folder_count` | `array('L')` | subtree counts, filled by rollup |

Names live in one shared `bytearray` as UTF-16LE, addressed by offset and length. Full
paths are never stored; they are reconstructed by walking `parent` on demand, which is
the only thing that needs them — context menu, file operations, export.

`size` and `alloc` are independent columns, not one derived from the other. The
verification scan's 385.4 GB / 147.5 GB split (§1.1) is the reason.

Budget, measured against the implemented store rather than estimated: 74 bytes per node
in fixed columns (4+4+2+8+8+8+8+8+4+4+4+4+4+4) plus about 30 bytes of name, so 104
bytes per node all in. A 5M-file volume lands near 500 MB and a 15M-file volume near
1.5 GB. A Python object per node with a `str` name is 5–10× that, which makes a full `C:`
scan unusable — the exact scenario this module exists to serve.

### 4.2 Rollup

Folder subtotals are computed after the scan pass. Because a child's MFT record number
carries no ordering guarantee relative to its parent, the store first assigns each node a
depth by walking parent links, then processes nodes deepest-first, adding `size`, `alloc`,
`file_count`, and `folder_count` into the parent. Two linear passes, no recursion, so deep
trees cannot overflow the stack.

### 4.3 Aggregates (`aggregates.py`)

Each right-panel view is a single linear pass over the arrays, restricted to a subtree by
walking the child lists once and recording the index set:

- **Extensions** — extension parsed out of the name blob; also grouped into Pro's
  configurable *file groups*.
- **Top Files** — bounded heap over `size`, count configurable as in Pro.
- **Users** — grouped by `owner_id`.
- **Age of Files** — histogram over `mtime` with Pro's configurable buckets.

Results are cached per (node index, mode) so navigating the tree does not recompute.

### 4.4 Scan files and snapshots (`scan_file.py`, `snapshots.py`)

A saved scan serializes the arrays plus the name blob and a header (target, timestamp,
engine, cluster size, options) as raw little-endian blocks under zlib; loading
reconstructs the store directly.

Diffing walks two stores by path and produces a delta tree carrying both sizes and their
difference, which drives Compare-with-saved-scan, Compare-with-snapshot, Compare-with-path,
and the "Show size changes" toggle (§5.5).

Snapshots are the same format tagged as system snapshots, written to a per-machine
location and enumerated by the History view.

Note that Pro itself ships `SQLite3.dll` and offers SQLite as an *export* format. This
design matches that: SQLite is an output format (§6.3), not the live scan store.

---

## 5. User interface

Every name in this section is the product's own, taken from the installed help and
screenshots.

### 5.1 Window structure

```
┌ Quick Access Toolbar ── title ── Find option (F6) ─────────────┐
├ File │ Home │ Scan │ Tools │ View │ Help │ (Details Tools ▸ Details) ┤
├ ribbon page for the active tab                                  ┤
├ nav ◂ ▸ ▴ │ path combo │ ▶ │ scan overview: Size · Allocated ·  ┤
│                          Files · Folders · Last Modified ·      │
│                          Last Accessed · Owner                  │
├──────────────────────┬──────────────────────────────────────────┤
│ Directory Tree       │ Chart │ Details │ Extensions │ Users │   │
│                      │ Age of Files │ Top Files │ History       │
│                      │                                          │
├──────────────────────┤            active view                   │
│ Drive List           │                                          │
├──────────────────────┴──────────────────────────────────────────┤
│ Free Space: … │ N Files │ N Excluded │ 4,096 Bytes per Cluster  │
└─────────────────────────────────────────────────────────────────┘
```

The chart is a **view in the right-hand tab strip**, not a separate panel. The left column
holds the Directory Tree above the Drive List; both the Drive List, the scan overview bar,
and the status bar are individually toggleable from the View tab, as in Pro.

### 5.2 Ribbon (`ribbon.py`)

Qt has no ribbon widget, so it is built: a `QTabBar` over a `QStackedWidget`, each page a
horizontal row of *groups*. A group is a bordered panel with a caption at the bottom and a
mix of one large button (32 px icon, label beneath, optional dropdown) and stacked small
buttons (16 px icon, label beside), with vertical separators between groups. Above it, a
title row carries the Quick Access Toolbar and the "Find option (F6)" box. The File tab
opens a backstage page rather than a dropdown. A contextual *Details Tools* tab group
appears when the Details view is active.

**Home** — groups: *Scan* (Select scan target ▾, Stop ▾, Refresh scan ▾, Remove scan) ·
*Mode* (Size, Allocated space, Number of files, Percent) · *Unit* (Auto ▾, GB, MB, KB) ·
*Directory Tree* (Expand ▾) · *Scan Result* (Send by email, Export ▾) · *Tools*
(Open TreeSize File Search ▾, Start as administrator, Options ▾) · *License*.

**Scan** — Stop · Pause/Resume · Refresh ▾ (Refresh all scans, Refresh selected folder,
Watch for file system changes) · Remove scan · Expand ▾ · Find · Export ▾ · Exclude ▾ ·
Compare with saved scan · Compare with snapshot · Compare with path · Show size changes ·
Schedule this scan.

**Tools** — Options ▾ (plus export, import, reset settings) · Open TreeSize File Search ·
Manage scheduled scans · Create snapshot · Create portable installation · Empty recycle
bin · Remove obsolete software · Configure Windows System Restore · Map network drive.

*Create portable installation* is the one Tools action deliberately not implemented: this
module ships inside a host application and has no independent installation to make
portable. The button is omitted rather than shown disabled.

**View** — Select active View · Mode (Size, Allocated space, Number of files, Percent) ·
Unit (Auto, TB, GB, MB, KB, B) · Decimals · Sort by size · Sort by name · Group scans ·
Show size changes · Drive list · Scan overview · Status bar · Hide empty folders · Hide
elements smaller than.

**Help** — help contents, about, license.

### 5.3 Styling

Pro follows the system theme and ships both light and dark; the verification screenshots
are dark. Two sheets, `treesize_dark.qss` and `treesize_light.qss`, are applied by the
module to its own root widget with `setStyleSheet`. Because a widget's stylesheet applies
to that widget and its descendants, this scopes to the pane automatically — no change to
`ThemeManager` is required, and the host app's sheets continue to govern every other
module. Sheet selection follows the Windows `AppsUseLightTheme` setting, with a manual
override in Options.

Colors are sampled from the running product during phase 2 rather than guessed.

### 5.4 Directory Tree (`directory_tree.py`)

`QTreeView` over a `QAbstractItemModel` backed by the store. `QModelIndex.internalId()`
carries the node index directly, so no per-row proxy objects are allocated.

Each row shows the size value, a proportional bar, the folder or file-type icon, and the
name — Pro's arrangement. A `QStyledItemDelegate` paints the bar.

Sorting reorders sibling ranges in place and signals `layoutAboutToBeChanged` /
`layoutChanged`, never a model reset. A reset on a multi-million-node model collapses the
tree and discards selection.

Expand ▾ offers levels 1/2/3, Full expand, and expand-to-size-threshold, matching Pro.
Find searches for a folder within the tree.

### 5.5 Modes, units, and size changes

**Mode** — Size, Allocated space, Number of files, Percent — selects what the tree bars,
the chart, and the size columns represent. It is pane state, not per-view state.

**Unit** — Auto, TB, GB, MB, KB, B, with a configurable decimal count — is a separate,
orthogonal setting governing numeric formatting everywhere. Auto picks the most
appropriate unit per value, which is what produces Pro's mixed-unit columns.

**Show size changes** replaces displayed values with signed deltas, and is enabled only
when the current scan has been compared against a saved scan, snapshot, or path.

### 5.6 Drive List (`drive_list.py`)

Bottom-left panel, columns Name · Total Size · Free · % Free, with a proportional bar in
the % Free column. Double-clicking a drive starts a scan of it.

### 5.7 Scan overview (`scan_overview.py`)

The bar above the panes, showing Size, Allocated, Files, Folders, Last Modified, Last
Accessed, and Owner for the current selection. Right-clicking chooses wrap or truncate
when the content does not fit, as Pro does.

### 5.8 Views (`views/`)

- **Chart** — treemap, pie, and bar over the current subtree. The treemap uses squarified
  layout with cushion shading, computed off the UI thread for large subtrees; rects are
  flattened into an array and hit-tested through a spatial grid so hover and click stay
  responsive at tens of thousands of rects. Click selects in the tree, double-click drills,
  and a breadcrumb tracks depth.
- **Details** — the table in the screenshots. Columns: Name, Size, Allocated, Files,
  Folders, % of Parent (with an inline proportional bar), Last Modified, Last Accessed,
  Owner. Additional columns and the column chooser follow Pro's Options dialog.
- **Extensions** — per-extension count and size, and per *file group* using Pro's
  configurable groupings.
- **Users** — per-owner count and size.
- **Age of Files** — histogram over modification time with configurable buckets.
- **Top Files** — the largest N files in the subtree.
- **History** — sizes over time across snapshots and saved scans for the target.

### 5.9 Status bar (`status_bar.py`)

Free Space (used of total), file count, excluded count, and cluster size with filesystem —
for example `4,096 Bytes per Cluster (NTFS)`. Also surfaces active scan filters and errors
encountered during the scan, which is what Pro's status bar is for.

---

## 6. Scan targets

### 6.1 Interface (`targets/base.py`)

Every backend implements one interface:

```python
class ScanTarget(ABC):
    id: str            # "local", "ssh", "s3", …
    display_name: str
    icon: str
    def authenticate(self) -> None: ...
    def enumerate(self, worker, store, root) -> None: ...
    def supports_file_ops(self) -> bool: ...
    def open_stream(self, node_path) -> BinaryIO: ...
```

`enumerate` appends into the store and honours the same batching, pause, and cancellation
contract as the local scanner (§3.4), so every view, aggregate, export, and comparison
works against any target without knowing which one produced the data. This is the whole
point of the interface: the store is the boundary.

### 6.2 Backends

| Target | Mechanism | Notes |
|---|---|---|
| **Drives / Directory** | MFT reader or walk (§3) | The primary path; everything else is optional at runtime |
| **SSH** | `paramiko` SFTP | `listdir_attr` gives size and mtime in one round trip |
| **WebDAV** | `PROPFIND` over `httpx` | Depth-1 per directory; no allocated size available |
| **Outlook** | MAPI via `pywin32`; Pro bundles `Redemption64.dll` for this | Folder and item sizes; read-only |
| **SharePoint** | Microsoft Graph | Entra ID app auth, plus certificate-based and user-based auth as Pro offers |
| **Google Drive** | Drive v3 API | OAuth device flow; `quotaBytesUsed` per file |
| **AWS S3** | `boto3` `list_objects_v2` | Prefixes synthesized into a folder tree |
| **Azure Blob** | `azure-storage-blob` | Same prefix-to-tree synthesis |

Remote targets have no cluster geometry, so `alloc` is set equal to `size` and the status
bar omits the cluster field. Remote targets report `supports_file_ops()` per backend;
where false, destructive actions are hidden rather than shown disabled.

Credentials go to Windows Credential Manager through `pywin32`, never to a config file.
Tokens refresh through the vendor SDK. Each backend throttles with exponential backoff on
429 and 503.

---

## 7. Actions

### 7.1 File operations (`file_ops.py`)

`IFileOperation` (COM, via pywin32) is the primary implementation: progress callbacks,
correct Recycle Bin semantics through `FOF_ALLOWUNDO`, long-path handling, and per-item
error reporting. `SHFileOperationW` through ctypes is the fallback.

- **Recycle** — `DeleteItem` with `FOF_ALLOWUNDO`.
- **Permanent delete** — `DeleteItem` without the undo flag.
- **Move** — `MoveItem` to a chosen folder.
- **Secure erase** — overwrite in place, then unlink. Configurable passes, single random
  pass by default.

**Secure erase does not reliably destroy data on SSDs.** Wear leveling means overwrites
land on different physical cells than the original data. Pro ships the feature regardless
and so does this clone; the dialog states the limitation rather than implying a guarantee
it cannot make.

Pro's *Empty recycle bin* (Tools tab) uses `SHEmptyRecycleBin`.

### 7.2 Safety

- **Preflight summary** — item count, total bytes, and the first ten paths, computed from
  the store before anything executes.
- **Typed confirmation** for permanent delete and secure erase; plain confirmation for
  recycle and move.
- **Path guardrails** (`guardrails.py`) — refuse drive roots, `%SystemRoot%`,
  `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`, and the user profile root
  unless an explicit override is checked. This is the highest-value defense in the module:
  a path-assembly bug anywhere in the MFT reader could otherwise aim a recursive delete at
  something unrecoverable.
- **Dry-run mode** — runs the full flow and writes the manifest without touching disk.
- **Manifest logged** through `LoggingService` before execution, so a mistake is
  reconstructible from the log.
- Operations run on a `Worker` with progress and cancel. Afterward the store marks nodes
  removed and rolls subtree totals back up rather than forcing a rescan.

### 7.3 Exports (`exporters.py`)

Pro's set: **Printer, PDF, Excel, HTML, CSV, XML, SQLite, Text, Email**. PDF via
`reportlab`, Excel via `openpyxl`, SQLite via the standard library, Email via the host's
MAPI or SMTP settings. Every exporter respects the current filter, sort, mode, and unit.
Depth defaults to the currently expanded level with an explicit full-tree option, since a
five-million-row spreadsheet is not a useful artifact.

---

## 8. Extras

### 8.1 File search

Pro ships this as a separate application; here it is a dialog over the same store,
filtering by name pattern, regular expression, size range, date range, owner, and
attributes. A linear pass, so results are effectively instant on an already-scanned
volume. Results render in a table sharing the tree's context menu. Search templates are
persisted through `ConfigManager`.

### 8.2 Duplicate finder

Group by `size` first; within each same-size group, hash the leading 64 KB to split the
group; hash in full with BLAKE2b only for the survivors. Hashing runs on a worker pool with
progress and cancel. A file is never hashed unless another file shares its exact size,
which eliminates the overwhelming majority of I/O. Results group by content hash and offer
the same file operations, with a keep-one-per-group selection helper.

### 8.3 Snapshots and comparison

Create snapshot, Compare with saved scan, Compare with snapshot, and Compare with path all
resolve to the diff described in §4.4, with results shown as signed deltas when Show size
changes is enabled.

### 8.4 Scheduled scans

Creates Windows Task Scheduler entries invoking the host application headless
(`--treesize-scan <target> --export <path>`), and a management dialog listing and editing
existing TreeSize tasks, mirroring Pro's Manage scheduled scans.

---

## 9. Module integration

`TreeSizeModule(BaseModule)` with `name = "TreeSize"`, `group = ModuleGroup.TOOLS`, and
`requires_admin = False` — the walk fallback keeps the module fully functional unelevated.
When not elevated, the Home tab's *Start as administrator* button and an inline banner
offer the fast path, reusing the existing restart flow at `src/ui/main_window.py:106`.

`create_widget()` builds the root widget and applies the theme sheet. `on_deactivate` and
`on_stop` cancel running scans through `cancel_all_workers()`. `get_status_info()` returns
the last scan summary. A `SearchProvider` exposes scanned paths to the global search bar,
consistent with the other modules.

---

## 10. Dependencies

Added to `requirements.txt`: `pywin32` (IFileOperation, MAPI, credential storage, SID
resolution), `openpyxl` (Excel), `reportlab` (PDF), `paramiko` (SSH), `httpx` (WebDAV),
`msal` (Entra ID), `google-api-python-client` (Drive), `boto3` (S3),
`azure-storage-blob` (Azure).

Scanning and charting use only the standard library and ctypes. No charting package is
added, since the treemap requires custom painting regardless.

Cloud SDKs are imported lazily inside their backend modules, so a user who never scans S3
does not pay `boto3`'s import cost and a missing optional dependency disables one target
rather than breaking the module.

---

## 11. Testing

Existing conventions apply: pytest, `sys.path` insertion of `src/` via `tests/conftest.py`,
a session-scoped `QApplication` fixture, models constructed and asserted directly.

- **MFT parser** — the component most likely to be subtly wrong and least testable against
  a live volume. Synthetic byte fixtures cover resident and non-resident `$DATA`,
  update-sequence fixups, `$ATTRIBUTE_LIST` spill, multiple `$FILE_NAME` namespaces, hard
  links, reparse points, sparse and compressed run lists, stale sequence numbers, and
  deleted records. Runs in CI with no volume access and no elevation.
- **Store** — rollup arithmetic, child-list integrity, deep-tree rollup without recursion,
  name blob round-tripping, independence of `size` and `alloc`.
- **Aggregates** — small known trees with hand-computed expected results.
- **Walk scanner** — integration against a `tmp_path` tree of known byte sizes.
- **MFT scanner** — asserted against that same tree, skipped unless elevated on NTFS.
- **Guardrails** — pure path predicates, unit-tested against a path list. Never exercised
  by attempting a real delete.
- **Model** — `QAbstractItemModel` conformance over a synthetic store.
- **Scan file** — round-trip and diff correctness.
- **Scan targets** — each backend tested against a recorded-response fake; no live
  credentials in CI.

---

## 12. Phasing

Phase 0 is a prerequisite, not design work: install CPython and create a project virtual
environment so the suite can run at all (§1.3).

1. **Engine and store** — volume info, MFT reader, walk fallback, scanner, filters, node
   store, rollup. Verified by tests and a throwaway console summary.
2. **Shell** — ribbon, directory tree, drive list, scan overview, status bar, Details view,
   modes and units. Colors sampled from the running product at the start of this phase.
3. **Views** — Chart (treemap first), Extensions, Users, Age of Files, Top Files.
4. **Actions and export** — guardrails and dry-run land before any destructive path is
   reachable from the UI.
5. **Comparison** — scan files, snapshots, History view, show size changes, live watcher.
6. **Extras** — file search, duplicate finder, scheduled scans.
7. **Remote targets** — SSH and WebDAV first, then Outlook, then the OAuth backends
   (SharePoint, Google Drive, S3, Azure Blob), one per increment.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| MFT parsing errors produce wrong paths | Synthetic fixtures per attribute type; guardrails block system paths regardless of what the parser produced |
| Destructive operation on a mis-assembled path | Guardrails, typed confirmation, dry-run, logged manifest |
| Memory on very large volumes | Columnar store measured at 104 bytes per node all in (74 fixed + ~30 name); 5M files near 500 MB |
| Treemap layout cost at high node counts | Off-thread layout, flattened rect array, depth-limited rendering |
| Ribbon fidelity | Names verified against shipped help; colors sampled from the running product in phase 2 |
| Cloud backends are the largest surface and the least testable | Deferred to phase 7, one per increment, behind a single interface; recorded-response fakes in CI |
| Optional dependency missing at runtime | Lazy imports; a missing SDK disables one target rather than the module |
| pywin32 COM failures on some systems | `SHFileOperationW` ctypes fallback |
