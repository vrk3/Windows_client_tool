# Changelog for Windows Client Tool

## Unreleased

### Added
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

### Fixed
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
