# Changelog for Windows Client Tool

## Unreleased

### Added
- **Composite modules** — a `CompositeModule` hosts other modules as tabs, so
  a feature made of sibling views is one sidebar entry instead of four. Child
  widgets are built when their tab is first shown, the visible child alone
  receives `on_activate`/`on_deactivate` (so hidden tabs stop polling), and a
  child needing elevation becomes a disabled tab rather than a missing one.
- Session logs are now capped by count as well as age
  (`app.log_retention_count`, default 20). One file per launch meant the
  30-day rule never fired on a working day; 105 had accumulated in two.

- **TreeSize** — a disk-space analyser built to match TreeSize Professional.
  Two scan engines: the NTFS `$MFT` read directly when elevated on an NTFS
  volume, and a `FindFirstFileExW` walk everywhere else. Squarified treemap,
  pie and bar charts; Details, Extensions, File groups, Users, Age of Files
  and Top Files views; saved scans, snapshots, comparison and History; a
  duplicate finder and file search; scheduled scans; live watching of the
  scanned folder; file operations through `IFileOperation`; exports to CSV,
  Excel, PDF, HTML, XML, JSON, SQLite and text; and eight scan targets
  including SSH, WebDAV, Outlook, S3, Azure Blob, SharePoint and Google Drive.
- **Log Viewer** — a CMTrace-style viewer for ConfigMgr and plain-text logs,
  with severity colouring, live tailing, a case-insensitive filter, find, and
  bounded reads so a 300 MB log opens at its tail in about a second.
- OAuth 2.0 device flow (RFC 8628) for SharePoint and Google Drive, replacing
  pasted access tokens that expired after an hour.
- Explorer-style quick scan locations on the TreeSize Home tab, resolved from
  the environment and from `SHGetKnownFolderPath` so redirected Desktop and
  Documents folders are found.

### Changed
- The sidebar is 34 entries, down from 41, with `TOOLS` down from 15 to 10.
  Nothing was dropped except Duplicate Finder:
  - **Debloat** now hosts Store Apps.
  - **Startup & Boot** replaces Startup Manager, Boot Analyzer and Power & Boot.
  - **Network Diagnostics** now hosts Wi-Fi Analyzer, Hosts Editor and Network
    Extras. Network Extras' duplicate HOSTS tab is gone; the Hosts Editor
    module was the better of the two editors.
  - **Diagnose** now hosts six real modules instead of building all six panes
    itself. `LogPane` is the single implementation behind every one of them.
- **Duplicate Finder was removed.** It MD5-hashed every file in full; TreeSize
  groups by size first and never hashes a file whose size is unique. The name
  still navigates to TreeSize.

### Fixed
- Six diagnostic search sources answered nothing. Folding Event Viewer, CBS,
  DISM, Windows Update, Reliability and Crash Dumps into Diagnose left their
  providers registered with no module, while the filter panel went on offering
  all six as sources. A module may now contribute several search providers,
  and the composite hands over its children's.
- Wi-Fi Analyzer crashed on shutdown if its widget had never been built:
  `_stop_scan` reached `self._progress`, which only `create_widget` creates.
  Harmless while every module's widget was built eagerly at startup, fatal for
  a composite tab nobody opened.
- `list_restore_points` ordered by timestamp alone. Restore points created in
  the same clock tick came back in the order SQLite happened to scan a random
  UUID index, so reverting "the most recent" could revert a different one.
- PerfMon's `cleanup_old` deleted records strictly older than the cutoff, so
  `days=0` left behind anything written in the same tick as the call.
- Excel exports past 1,048,576 rows produced a file Excel refuses to open.
  openpyxl does not enforce the limit; the export reported success.
- The text and SQLite exporters crashed on a row shorter than the header
  while the Excel one tolerated it.
- Added comprehensive docstrings to core modules

### Added (earlier)
- LICENSE file (MIT)
- CHANGELOG.md

## [0.1.0] - 2026-03-23

### Added
- Initial release with 18 system optimization modules
