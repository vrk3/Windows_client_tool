# Changelog for Windows Client Tool

## Unreleased

### Added
- **Tweaks: 306 new tweaks across 10 new categories** — Explorer, Taskbar &
  Start, Power, Input, Windows Update, Defender & Firewall, Browsers, Storage,
  Multimedia and Remote Access. The tab now carries ~700 tweaks over 20
  categories.
- **Tweaks: a "Not Applicable" status.** A tweak whose target service,
  scheduled task or app is not on this machine, or whose `applies_to` gate
  excludes this Windows build, edition or architecture, now says so instead of
  reporting "Unknown" or a permanent "Not Applied". Such rows cannot be ticked
  or applied, and the search bar reads the reason text, so typing "not
  installed" collects them.
- **Tweaks: every status carries a reason.** The Status column's tooltip and
  the details panel state which value was read, what it was, and what the
  tweak wanted — "HKLM\...\EnableLMHOSTS is 1, this tweak wants 0".
- **Tweaks: a "Partial" status** for a multi-step tweak where only some steps
  are in place. Previously only the *first* step was ever checked, so a
  half-applied tweak reported whatever its first step happened to say.
- `applies_to` on a tweak definition, gating on `min_build`/`max_build` (build
  number or alias such as `"23H2"`), `os`, `editions`, `not_editions`, `arch`,
  `requires_gpedit` (Home and S editions write policy values and then ignore
  them), `client_only` and `server_only`.
- `detect` on a tweak definition — a read-only probe that makes a
  `command`/`script` tweak checkable. Probe types: any step type plus
  `registry_key_exists`, `registry_key_absent`, `powershell`, `file_exists`,
  `file_absent`, and `none` for repair actions with no state to read back.
- A `registry_delete` step type, for behaviour that is only off when the value
  is absent rather than zero.
- `tests/test_tweak_definitions.py` — structural validation of every JSON
  definition file: unique ids, known hives and step types, DWORD-vs-SZ data
  types, absolute scheduled-task paths, and a `detect` block on every
  command-driven tweak.

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
- **Tweaks status detection was rewritten.** It checked only the first step of
  each tweak and treated a missing registry key as "Unknown"; on a clean
  install that made most of the Network tab unreadable. All steps are now
  checked and aggregated, and a key or value that does not exist is reported as
  "Not Applied" — Windows sitting at its default is a definite answer, not an
  absence of one. "Unknown" is now reserved for cases where the check genuinely
  could not run, and always says why.
- Tweaks status sweeps run across a thread pool. The cost is dominated by
  process launches (schtasks, powercfg, PowerShell) that block with the GIL
  released, so the full 696-tweak sweep went from ~17 s to ~6 s. Installed
  UWP packages are now enumerated once per session instead of one
  `Get-AppxPackage` launch per row.
- Tweaks category tabs show `(applied/applicable)` counts, and the status
  filter gained Applicable, Partial and Not Applicable. The search bar shows
  which Windows build, edition and architecture the verdicts are judged
  against.

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
- **Tweaks: "Select Applied" also selected every "Not Applied" row.** The
  filter tested `"Applied" in label_text`, and one string contains the other.
  Selection and filtering now match on the stored status code.
- Five tweaks targeted service names that exist on no current Windows build
  and so could never do anything: `utcsvc` (DiagTrack's display name, not its
  service name), `wmisvc` (a typo for `wisvc`), `wmpcsvc`, `UxSvc` (DWM
  stopped being a service in Windows 8) and `SrumSvc`. Each duplicated a
  correctly-named entry elsewhere, and all five are gone. `TabletInputService`
  became `TextInputManagementService` and `CldStorSvc` became
  `WinHttpAutoProxySvc`. Surfacing these was what the new "Not Applicable"
  status was for.
- Four tweak ids were used twice across definition files, so one row's status
  silently overwrote the other's: `disable_wifi_sense`, `disable_llmnr`,
  `disable_wpad` and `disable_search_highlights`.
- `enable_numlock_on_boot` wrote to `HKEY_USERS\...`, which the hive parser
  does not recognise — it fell back to HKLM and wrote into the wrong hive
  entirely. Now `HKU\.DEFAULT\...`.
- Five registry steps declared `kind: SZ` with integer data, which raises
  inside `SetValueEx` at apply time, after a restore point has been taken.
- `enable_secure_boot` only ran `Confirm-SecureBootUEFI`, which reads the
  state and changes nothing — Secure Boot is a firmware setting. It is now
  honestly named "Check Secure Boot Status".
- `disable_auto_logger` added a Deny *audit* rule, which does not stop the
  trace session; it now sets the listener's own `Start` value.
- `use_24hour_clock` called `Set-Culture en-GB`, changing the entire system
  locale to reach a clock format. It now writes the two time-format values.
- `win11_copilot_disable` renamed a System32 binary, which Windows Resource
  Protection restores at the next servicing pass. It now uses the supported
  `TurnOffWindowsCopilot` policy.
- `disable_loading_drivers_test` wrote a value under `KnownDLLs` that does not
  exist; driver test signing lives in the boot configuration.
- `disable_tcp_scaling` ran `netsh ... rss=enabled autotuninglevel=normal`,
  which does not disable window scaling and contradicted `disable_rss`.
- `enable_dns_over_https` only set two DNS resolvers without enabling DoH; it
  now sets `EnableAutoDoh` as well.
- 26 `schtasks /change ... /disable` shell-outs became real `scheduled_task`
  steps, so they are detectable and revertable rather than opaque commands.

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
