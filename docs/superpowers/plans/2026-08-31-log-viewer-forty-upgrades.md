# Log Viewer — Forty Upgrades Implementation Plan

> **For agentic workers:** implement task by task, TDD, committing per task.
> Steps use checkbox (`- [ ]`) syntax. **This file is the status ledger** —
> tick boxes as you go and commit the tick with the work. It is IN GIT
> deliberately, unlike `.superpowers/sdd/` ledgers, so that resuming after a
> fresh clone or a lost session works.

**Goal:** Implement the forty upgrades identified for the Log Viewer after
chunks 1–4 shipped, in five waves ordered by value delivered per unit of work.

**Architecture:** The existing split holds throughout and is not to be broken.
`log_reader.py` reads bytes (no Qt, no `core` imports). `log_set.py` merges N
sources (no Qt). `cmtrace_parser.py` parses (no Qt of its own). `log_model.py`
is the `QAbstractTableModel`. `log_viewer_module.py` is the pane. New analysis
work belongs in new Qt-free modules beside `log_set.py`, not inside the pane.

**Tech Stack:** Python 3.12, PyQt6, pytest. No new third-party dependencies
without asking — `requirements.txt` drift is caught by
`tests/test_runtime_dependencies.py`.

**Spec:** the forty ideas as published, plus
`docs/superpowers/specs/2026-08-30-log-viewer-capability-pack-design.md`,
`2026-08-31-log-viewer-backward-paging-design.md` and
`2026-08-31-log-viewer-merged-timeline-design.md`.

## Global Constraints

- **TDD.** Write the failing test, watch it fail for the right reason, then
  implement. No production code without a failing test first.
- **No Qt in `log_reader.py`, `log_set.py`, or any new engine module.**
  `tests/test_log_set.py::test_the_engine_files_declare_no_qt_import` pins
  this; add new engine files to that list.
- **Never raise out of a Qt virtual.** `paint()` and `data()` are routed to
  `sys.excepthook` then `qFatal()` — an exception there kills the process and
  cannot be caught. Validate before the value reaches a paint or data path.
- **Use the Write/Edit tools for Python containing backslashes**, never a
  shell heredoc: `\\` arrives as `\`, which runs but emits `SyntaxWarning` on
  a cold compile. Clear `__pycache__` before counting warnings.
- **Cold-suite baseline: 1 warning** (the `PytestCollectionWarning` in
  `tests/test_integration.py`). Any second warning is yours.
- **Columns are named constants.** Never `model.index(row, 4)` — `COLUMNS`
  has changed twice already.
- **Real data before "done".** Run `tools/log_viewer_real_check.py` after
  touching the reader, parser, set or model. For anything that renders, look
  at it in BOTH themes before claiming it works.
- **Every new disabled control gets checked in the light theme.**
  `light.qss` had no `QPushButton:disabled` rule until 2026-08-31.

---

## Status

| Wave | Theme | Tasks | Done |
|---|---|---|---|
| 1 | Quick wins that change daily use | 13 | **13 — DONE** |
| 2 | Analysis — what the tool is *for* | 7 | **7 — DONE** |
| 3 | Reading and filtering | 8 | **8 — DONE** |
| 4 | Getting logs in | 5 | 4 (5th BLOCKED) |
| 5 | Output and performance | 7 | 2 |

**Next task:** W5-03 (error codes that explain themselves). W4-05 is BLOCKED on a real ConfigMgr/Intune log, which this machine does not have.

---

## Known issue, unrelated to this work

**FIXED on 2026-08-31.** `test_network_view_filters_by_pid` failed once in
nine full runs, then twice in a row as the suite grew past 3,100 tests. It
always passed in isolation.

The cause was a race, not an ordering accident: `_drain()` pumped Qt events
for a flat **100 ms** and then asserted, but a worker delivers its signal when
it delivers it. That is fine on a quiet machine and fails once the run is long
enough for the thread pool to be busy -- and this session's ~700 new tests
made it long enough. Exactly the class of the two previous flakes here, which
were both two clock reads landing in one tick.

`_drain(qapp, ms=2000, until=...)` now waits for the CONDITION and returns as
soon as it holds, so the fast case stays fast and a loaded machine gets room.
Three consecutive full runs green afterwards.

---

# Wave 1 — Quick wins

Small, self-contained, each one visible the moment it lands. All live in
`log_model.py` and `log_viewer_module.py` unless stated.

### W1-01 (idea 08): Exclude filter

**Files:** `src/modules/log_viewer/log_model.py`,
`src/modules/log_viewer/log_viewer_module.py`,
`tests/test_log_model.py`, `tests/test_log_viewer_module.py`

**Interfaces:** `LogModel.set_filter(exclude: str = None)`; pane gains
`self.exclude_box` (a `QLineEdit` beside Filter).

- [x] Test: `test_an_exclude_pattern_hides_matching_rows`
- [x] Test: `test_exclude_combines_with_the_include_filter`
- [x] Test: `test_exclude_honours_the_regex_box`
- [x] Test: `test_a_half_typed_exclude_pattern_hides_nothing` — an invalid
      pattern must not empty the table, the same rule `_matcher is False`
      already follows for the include filter
- [x] Implement `_exclude` / `_exclude_matcher` in `_matches`, mirroring the
      existing needle handling; exclude is applied AFTER include
- [x] Wire `exclude_box` into `_apply_filters` and `_refresh_match_colours`
- [x] Real check + look at it; commit
- **Measured on the live CBS.log (11,277 rows):** hiding `Appl: detect`
  removes 9.7%, `detectParent` 4.8%. Include and exclude both survive a
  reopen, deliberately -- one text box clearing while its neighbour did
  not would be the surprising behaviour.

### W1-02 (idea 14): Live match count while typing

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

- [x] Test: `test_the_status_says_how_many_rows_the_filter_left`
- [x] Test: `test_a_filter_matching_nothing_says_so_rather_than_showing_empty`
- [x] The count already exists in `_update_status` as "N shown of M"; this
      task adds the *no matches* wording and makes it update on every
      keystroke rather than only after a commit
- [x] Commit
- **Done.** The count already refreshed per keystroke; what was missing
  was the wording. An empty table reads as "this log has no such
  records", which is a different claim from "your filter removed
  everything" -- and only said when records ARE loaded, since nothing
  loaded is a third thing and not the filter's fault.

### W1-03 (idea 10): Filter history

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

**Interfaces:** `filter_box` becomes a `QComboBox` with `setEditable(True)`,
or keeps the `QLineEdit` with a `QCompleter` over a history list. Prefer the
completer — the clear button and placeholder behaviour are already right.

- [x] Test: `test_a_committed_filter_joins_the_history`
- [x] Test: `test_the_history_does_not_grow_without_bound` (cap 20)
- [x] Test: `test_an_identical_filter_moves_to_the_front_rather_than_repeating`
- [x] Persist through `self._config` if a config is present, else in memory
- [x] Commit
- **Done.** New Qt-free `src/modules/log_viewer/history.py` holds the
  ordering rules as a pure function so they test without a widget; the
  pane keeps a `QCompleter` over a `QStringListModel`.
- **Enter is the commit gesture, not typing.** The filter applies live,
  so recording on `textChanged` would fill the history with every
  prefix: H, HR, HRE, HRES.
- `MatchContains`, not the default prefix match — a log pattern is
  rarely recalled from its first character.
- A stored value that is not a list of strings is discarded rather than
  trusted: config files get hand-edited and a bad value would otherwise
  reach a completer during `create_widget`.

### W1-04 (idea 12): Multi-select Component and Thread

**Files:** `log_model.py`, `log_viewer_module.py`, tests for both

**Interfaces:** `set_filter(component=...)` and `thread=...` accept a `set()`
as well as a `str`. A bare string keeps working — several tests pass one.

- [x] Test: `test_two_components_can_be_shown_at_once`
- [x] Test: `test_a_single_component_string_still_works` (back-compat)
- [x] Test: `test_clearing_the_selection_shows_every_component`
- [x] Replace the combos with checkable ones (`QListWidget` in a
      `QComboBox` view, or a `QToolButton` + checkable `QMenu`); the Thread
      combo has 329 entries on DISM, so keep it searchable
- [x] Commit
- **Scope call, stated rather than made silently: the MODEL takes a set
  on both axes, but only COMPONENT got the multi-select control.** DISM
  has 329 distinct threads; picking two of them is not a workflow, and a
  checkable popup over 329 entries needs its own search box. Component
  has 3-4 values and "CSI plus CBS" is the everyday case. The model half
  is done, so the Thread control can catch up without touching it again.
- `_as_selection()` takes a bare string as well as a set, because every
  existing caller passes a string and one axis reading differently from
  its neighbour is how a filter quietly stops meaning what it says.
- **An empty set means "show everything", not "accept nothing".** The
  latter would leave someone staring at an empty table having ticked
  nothing at all.
- The Component control is a checkable `QMenu` on a `QToolButton`; "All"
  is the ABSENCE of any tick rather than an entry of its own. A tick only
  survives a reopen if its component is still present -- keeping one from
  a closed log is the stale-filter shape that has bitten this pane twice.
- The button summarises past two selections (`3 components`): a label
  that grows with the selection shoves every control to its right along
  the toolbar.

### W1-05 (idea 04): Keyboard navigation

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

**Interfaces:** `QShortcut`s owned by the widget: `/` focus filter,
`Ctrl+F` focus find, `F3`/`n` next match, `Shift+F3`/`N` previous,
`Ctrl+Home`/`Ctrl+End` first/last row.

- [x] Test: `test_the_find_shortcut_focuses_the_find_box`
- [x] Test: `test_f3_moves_to_the_next_match`
- [x] Test: `test_shift_f3_moves_back`
- [x] Single-letter shortcuts must NOT fire while a text box has focus —
      test that too: `test_typing_a_slash_into_the_filter_is_not_a_shortcut`
- [x] Commit
- **Deviation from this task as written, on purpose.** The plan asked
  for `/` to focus the filter and `n`/`N` for next/previous match. A
  `QShortcut` takes precedence over the widget that has focus, so a bare
  letter or symbol would be STOLEN from the Find, Filter and Hide boxes
  the moment anyone typed one. Every binding therefore carries a
  modifier or is a function key: Ctrl+F, Ctrl+L, Ctrl+H, F3, Shift+F3.
  A test asserts no binding is ever a bare key.
- **Do not test these with `QTest.keyClick`.** An offscreen window is
  never activated, so Qt delivers no shortcut to it and every such test
  passes vacuously. Fire `shortcut.activated` and assert the behaviour;
  what is under test is which sequence is bound to what, not Qt's key
  delivery. For the same reason `hasFocus()` is always False here --
  use `widget.focusWidget()`.

### W1-06 (idea 02): Go to a time

**Files:** `log_model.py` (`row_at_or_after(when)`), `log_viewer_module.py`,
tests for both

**Interfaces:** `LogModel.row_at_or_after(timestamp) -> int` using `bisect`
over `_visible`, mirroring `row_for_entry`.

- [x] Test: `test_going_to_a_time_lands_on_the_first_row_at_or_after_it`
- [x] Test: `test_a_time_after_the_end_lands_on_the_last_row`
- [x] Test: `test_a_time_before_the_start_lands_on_the_first_row`
- [x] Test: `test_rows_with_no_timestamp_are_skipped_rather_than_matched`
- [x] Pane: a "Go to…" button opening a small dialog prefilled with the
      loaded span, or reuse the existing `QDateTimeEdit` pattern
- [x] Commit
- **Done, with two corrections the tests forced.** (1) `row_at_or_after`
  is a LINEAR walk, not a bisect: log timestamps are not sorted --
  setupact jumps ten hours backwards at a phase boundary and a merged
  set interleaves several clocks -- so a bisect answers confidently and
  wrongly. 200k comparisons is a few ms and it runs on a click. (2) The
  jump takes its own time via a small dialog rather than reading the
  From box: editing that box fires `dateTimeChanged`, which is what
  turns the range filter ON, so reusing it would have hidden rows
  before the jump ever happened.

### W1-07 (idea 24): Flag corruption markers

**Files:** `src/modules/log_viewer/error_codes.py` (or a new
`markers.py`), `log_delegate.py`, `tests/test_log_error_codes.py`

**Interfaces:** `corruption_spans(text) -> [(start, end, label)]` for
`STATUS_SXS_*`, `"cannot repair"`, `"store corruption"`,
`"Hashes for file member ... do not match"`.

- [x] Test each marker is found, with a real CBS line as the fixture
- [x] Test: `test_a_line_merely_mentioning_corruption_in_prose_is_not_flagged`
- [x] Colour them with `semantic("error")` in the delegate, joining the
      existing failing-code spans; reuse `_without` so they never overlap
- [x] **Run against the real CBS archive and report the count** — if it
      flags thousands of lines the markers are wrong
- [x] Commit
- **Measured on real logs before wiring it up:** CBS.log 0 of 11,277,
  dism.log 0 of 12,454, CbsPersist_20260831055247.log **522 of 138,683
  (0.38%)** — 261 rows carrying `STATUS_SXS_FILE_HASH_MISMATCH` and 261
  saying "do not match". Signal, not noise, and a real finding about
  this machine's component store.
- `STATUS_SXS_\w+` is open-ended on purpose: new SXS statuses ship with
  new Windows builds and a hardcoded roster would silently stop
  matching. "Repair" and "corruption" alone are NOT markers — CBS says
  both constantly while everything is fine.
- The delegate gained `failure_spans()`, merging failing codes and
  markers into one non-overlapping list: they are the same news to a
  reader, and two spans over one stretch would nest their tags.

### W1-08 (idea 32): Logs with no clock sort last

**Files:** `src/modules/log_viewer/log_set.py`, `tests/test_log_set.py`

**Why:** `FilterList.log` has no timestamps at all, so its 22 records take
the epoch and lead any merged view of `C:\Windows\Logs\CBS`.

- [x] Test: `test_a_source_with_no_timestamps_at_all_sorts_last`
- [x] Test: `test_a_source_with_SOME_timestamps_is_not_moved`
- [x] Test: `test_an_orphan_continuation_is_still_not_dropped` (regression —
      the epoch is still right for a record inside a timestamped file)
- [x] Implement: decide per SOURCE, not per record. If a source has no real
      timestamp anywhere, give its records a sentinel that sorts last;
      otherwise the existing inherit-from-above rule stands
- [x] Real check: reopen the CBS folder, confirm FilterList no longer leads
- [x] Commit
- **Done, and verified on the real CBS folder:** the archive now leads
  and FilterList.log sits at the end. Before, its 22 rows of
  filter-driver names were the first thing anyone saw.
- **Decided per SOURCE, not per record.** A dated file whose slice
  begins mid-block has an orphan continuation with nothing to inherit,
  and that orphan belongs at the front of ITS file -- not dragged, nor
  dragging its whole source, to the end of the timeline.
- The merge check still reports 38,101 == 38,101, 0 cross-file ordering
  steps and 0 separated continuations.

### W1-09 (idea 28): Recent files and folders

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

- [x] Test: `test_opening_a_log_adds_it_to_the_recent_list`
- [x] Test: `test_opening_a_folder_is_recorded_as_a_folder`
- [x] Test: `test_the_recent_list_is_capped_and_deduplicated`
- [x] Test: `test_a_recent_entry_that_no_longer_exists_is_dropped_on_build`
- [x] Render in `_build_open_menu` under the known logs; persist via
      `self._config`
- [x] Commit
- **Done.** Reuses `history.remember` with its own cap (10) and config
  key. A folder is remembered AS the folder, not as the dozen files it
  happened to contain. Entries that no longer exist are dropped when
  the menu is built -- a log can be rolled away between sessions, and
  offering a path that is gone is offering an error message.

### W1-10 (idea 27): Drag and drop

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

- [x] Test: `test_dropping_a_file_opens_it`
- [x] Test: `test_dropping_a_folder_opens_every_log_in_it`
- [x] Test: `test_dropping_several_files_opens_them_as_one_timeline`
- [x] Test: `test_dropping_something_that_is_not_a_log_is_refused_politely`
- [x] `setAcceptDrops(True)`, `dragEnterEvent`, `dropEvent`; build the
      events in the test with `QMimeData().setUrls([...])`
- [x] Commit
- **Done.** Dropped paths are `normpath`ed: `QUrl.toLocalFile()` hands
  back forward slashes on Windows, and the recent list deduplicates by
  string, so without it one file would sit there twice under two
  spellings.
- A drop containing nothing openable leaves the current log alone and
  says so. Replacing it with an empty pane would lose what the person
  was reading in order to report their mistake.

### W1-11 (idea 34): Copy rows as Markdown

**Files:** `src/modules/log_viewer/log_export.py`,
`log_viewer_module.py`, `tests/test_log_export.py`

- [x] Test: `test_markdown_rows_carry_every_visible_column`
- [x] Test: `test_a_pipe_in_a_message_is_escaped` — CBS messages contain `|`
- [x] Test: `test_the_fold_suffix_never_reaches_the_markdown` (the display
      suffix is display-only; the existing export tests pin the same rule)
- [x] Add to the row context menu beside the existing Copy
- [x] Commit
- **Done.** Pipes escaped and newlines folded: a CBS message contains
  both, and either one unescaped turns a row into a broken table for
  every row after it. `_selected_entries()` was extracted so the two
  copy actions cannot disagree about what the selection is.

### W1-12 (idea 33): Export the view as HTML

**Files:** `log_export.py`, `log_viewer_module.py`, `tests/test_log_export.py`

- [x] Test: `test_html_export_carries_the_severity_colour_per_row`
- [x] Test: `test_html_export_escapes_angle_brackets` — CMTrace records are
      literally `<![LOG[...]]>`
- [x] Test: `test_html_export_ignores_folding_like_every_other_export`
- [x] Test: `test_html_export_is_written_atomically` — match the existing
      temp-file-then-replace path, which has its own tests
- [x] Chosen by the `.html` extension in `choose_export`, like `.csv`
- [x] Commit
- **Done.** Chosen by the `.html`/`.htm` extension, `.md` for
  Markdown, alongside the existing `.csv`. Severity colours are
  HARDCODED rather than taken from `semantic_colors`: an exported file
  has one appearance and is read on someone else's machine, in a theme
  this process knows nothing about.
- Escaping matters more here than anywhere: a CMTrace record is
  literally `<![LOG[...]]>`, which unescaped eats the rest of the
  document.

### W1-13 (idea 39): Remember the layout

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

- [x] Test: `test_column_widths_are_saved_and_restored`
- [x] Test: `test_the_splitter_position_survives_a_reopen`
- [x] Test: `test_a_saved_layout_from_an_older_column_set_is_ignored`
      — `COLUMNS` has changed twice; a stale saved width list must not be
      applied positionally to a different set of columns
- [x] Persist via `self._config`; save on `closeEvent`/`on_deactivate`
- [x] Commit
- **Column widths deliberately NOT remembered, and the task title is
  wrong to ask for them.** The narrow columns are `ResizeToContents` and
  cannot be dragged, and that auto-sizing is exactly what stopped the
  Source column rendering every CBS archive as `CbsPersist_20…` -- they
  differ only in the timestamp at the END of the name. Making them
  draggable so they could be memorable would trade a real fix for a
  preference. Column VISIBILITY is W3-06's job.
- What is remembered is what is adjustable: the splitter, and the fold
  and regex checkboxes. Each key is validated and applied on its own, so
  a hand-edited splitter does not cost you the fold setting, and a
  corrupt value cannot take the pane down while it is being built.
- Saved on `stop()`, not on every splitter drag: the splitter emits while
  it is being moved and that would be a config write per pixel.

---

# Wave 2 — Analysis

The group that changes what the tool is for. Each of these belongs in a new
Qt-free module beside `log_set.py`, with the pane only rendering the result.

### W2-01 (idea 19): Top-N panel

**Files:** create `src/modules/log_viewer/log_stats.py`; pane; create
`tests/test_log_stats.py`

**Interfaces:** `top_codes(entries, n)`, `top_components(entries, n)`,
`top_messages(entries, n)` → `[(value, count)]`.

- [x] Test each returns counts descending, ties broken by value
- [x] Test: `test_counting_ignores_folded_state` (it counts records, not rows)
- [x] Test: `test_an_empty_log_yields_empty_lists_rather_than_raising`
- [x] Pane: a collapsible panel; clicking a row applies it as a filter
- [x] **Time it on the real 380 MB archive's 200k records** — if a refresh
      costs more than ~200 ms it must not run on every keystroke
- [x] Commit
- **The timing check mattered: `top_codes` costs 297 ms over the real
  archive's 138,683 records**, well past the 200 ms this task set as the
  line. So the panel is debounced -- a single-shot 400 ms timer restarted
  on each change -- and computes NOTHING while it is hidden. Running it
  inline would have made the Filter box unusable on exactly the logs the
  panel exists for.
- It counts `visible_entries()`, so it answers "what is in what I am
  looking at" and moves with the filter. Folding is ignored, as it is for
  export: a reading convenience is no business of a count.
- Ties break on the value itself. Without that, two equal-count codes
  swap places between refreshes and the panel reorders under the cursor.
- **`top_messages` takes an optional `key`**, which is the seam W2-07's
  normaliser plugs into. Verbatim on the real archive the top line
  repeats 589 times out of 138,683, so it is useful but thin until then.
- Real archive, panel open: 0.52 s over 134,499 shown rows.
  `0x80004005` x522 -- the same 522 rows the corruption markers flag.
  Rendered in both themes; the lists took the table's monospace font so
  the counts line up and more than three rows fit.

### W2-02 (idea 18): Stall detection

**Files:** `log_stats.py`, `log_model.py` (a marker role), pane, tests

**Interfaces:** `gaps(entries, threshold_seconds) -> [(index, seconds)]`.

- [x] Test: `test_a_gap_longer_than_the_threshold_is_reported`
- [x] Test: `test_records_with_no_timestamp_do_not_create_false_gaps` —
      continuations inherit, so use the effective timestamp
- [x] Test: `test_a_backwards_clock_step_is_not_reported_as_a_gap` —
      setupact jumps ten hours backwards at a phase boundary; a negative
      delta is not a stall
- [x] Render as a marker in the gutter or a tinted row; threshold in the UI
- [x] Commit
- **Done, as a fourth Summary column.** Measured on real logs and it is
  selective: **1 gap in the CBS archive's 138,683 records** (121 s), 5 in
  setupact, 31 in dism.log whose longest is 113,897 s -- idle between two
  DISM runs, which is honest rather than wrong. Costs 16 ms, unlike
  `top_codes`' 297 ms.
- **The trap: a gap's index is NOT a row number.** Gaps are counted over
  `visible_entries()`, which ignores folding, so the panel stores the
  RECORD and `LogModel.row_for_record()` finds its row by identity.
  Clicking would otherwise land somewhere arbitrary whenever folding was
  on -- which is the default.
- A backwards clock step is not a stall (setupact jumps ten hours back
  at a phase boundary), a record with no clock creates no gap, and a
  threshold of 0 reports nothing rather than every row in the log.

### W2-03 (idea 22): KB and package column

**Files:** `cmtrace_parser.py` or a new `packages.py`, `log_model.py`, tests

**Interfaces:** `package_of(message) -> str` extracting
`Package_for_KB3025096~31bf3856ad364e35~amd64~~6.4.1.0` → `KB3025096`.

- [x] Test: with a real CBS line as the fixture
- [x] Test: `test_a_line_with_no_package_yields_empty`
- [x] Test: `test_an_update_id_is_not_mistaken_for_a_kb`
- [x] New optional column, hidden unless a log actually carries packages
      (same rule the Source column follows)
- [x] **Run over the real archive and report how many records carry one**
- [x] Commit
- **The real data changed the design.** Only 124 of the archive's
  138,683 records mention a KB, while package tokens appear on 127,623
  of them (92%). A KB-only column would have been empty 99.9% of the
  time, so `package_of()` returns the KB when the package name embeds
  one and the package identity otherwise: 1,691 distinct values, 8 KBs.
- Anchored on the 16-hex publisher key, which is what separates a
  package identity from a sentence containing the word "package".
  GUIDs, UpdateIDs and hex codes do not match.
- **Computed in `data()`, not stored at parse time.** Qt asks only for
  the cells it is about to paint, so this costs ~30 regex searches per
  repaint instead of the 250 ms it would add to every open.
- **No new filter axis, deliberately.** The Filter box already matches
  the whole row, so typing a KB or package name narrows to it today.
- **Found by rendering: the column took 470px and was empty on screen.**
  ResizeToContents measures the widest value in the WHOLE model, and
  servicing names run to 62 characters, so one long name shoved Message
  off to the right for rows with no package at all. Sized to content,
  then capped at PACKAGE_MAX_WIDTH.

### W2-04 (idea 21): First error, last success

**Files:** `log_stats.py`, pane, tests

**Interfaces:** `first_error(entries)`, `last_before(entries, index)`.

- [x] Test: `test_the_first_error_is_the_earliest_error_row`
- [x] Test: `test_the_last_success_is_the_record_before_it`
- [x] Test: `test_a_log_with_no_errors_says_so_rather_than_returning_none`
- [x] Render as a summary strip with two clickable rows
- [x] Commit
- **Done, as the first Summary column** -- it is the answer you want
  before any of the counts.
- **`last_success_before` skips over other errors on purpose.** When a
  failure cascades, the error immediately above the one you found is
  usually the same failure again; the row worth reading is the last
  thing that WORKED. A Warning counts as a success for this, because
  the question is what did not fail.
- A clean log says "No errors in what is shown" rather than leaving an
  empty column, which reads as a broken panel.
- `_add_record()` now backs every clickable summary row and stores the
  RECORD rather than its index -- the W2-02 trap, applied once instead
  of repeated per column.

### W2-05 (idea 16): Error-density strip

**Files:** create `src/modules/log_viewer/density.py` (Qt-free bucketing) and
a small `QWidget` painter in the pane; tests for the bucketing

**Interfaces:** `buckets(entries, count) -> [(start_time, total, errors)]`.

- [x] Test: `test_buckets_span_the_whole_range`
- [x] Test: `test_every_record_lands_in_exactly_one_bucket`
- [x] Test: `test_a_single_instant_log_does_not_divide_by_zero`
- [x] Test: `test_records_with_no_timestamp_are_excluded_not_bucketed_at_epoch`
- [x] Painter: `QPainter`, int coordinates only (PyQt6 is strict — see
      `perfmon_charts.py`), theme colours from `semantic_colors`
- [x] Click maps x → time → `row_at_or_after` from W1-06 (depends on it)
- [x] **Look at it in both themes on the real archive**
- [x] Commit
- **Found by rendering: linear scaling made the strip useless.** CBS
  writes in bursts, so one bucket held the overwhelming majority of
  138,683 records and every other bar rounded to zero pixels -- the
  strip read as a single block with nothing around it. `bar_height()`
  uses a SQUARE ROOT: ordering survives, and a bucket a thousandth the
  size of the busiest stays visible. An error bar is never under two
  pixels, because a single failure is the thing worth seeing.
- **It also caught a bug I had shipped in W1-08.** A clock-less source
  is sorted last by giving its records `APPENDIX_TIME` (datetime.max),
  and both the density strip AND the gap finder were reading that as a
  real timestamp -- year 9999. `log_set.effective_time()` is now the one
  place that says what `merge_time` means, and both go through it.
- Refreshed inline rather than debounced: one pass, no regex, unlike
  the Summary counts. Hidden entirely for a log with no timestamps --
  there is nothing to place on a timeline.

### W2-06 (idea 17): Servicing sessions

**Files:** create `src/modules/log_viewer/sessions.py`; `log_model.py`; tests

**Interfaces:** `sessions(entries) -> [Session(start, end, outcome, indices)]`
detecting `Beginning TrustedInstaller` / `Ending TrustedInstaller`.

- [x] Test: `test_a_matched_pair_becomes_one_session`
- [x] Test: `test_a_session_left_open_at_the_end_of_the_slice_still_reports`
      — a tail slice routinely starts mid-session
- [x] Test: `test_a_session_with_an_error_inside_it_is_marked_failed`
- [x] Test: `test_nested_or_repeated_beginnings_do_not_lose_records`
- [x] Collapse reuses the folding machinery from chunk 2 (`_folded` is just
      a set of indices; it is a filter, not a tree)
- [x] **Count sessions on the real archive and sanity-check the number**
- [x] Commit
- **This task's premise was WRONG and the real logs said so.** It
  specified `Beginning`/`Ending TrustedInstaller`. That phrase appears
  NOWHERE in either CBS log on this machine -- a detector built on it
  would have found zero sessions in every file while looking perfectly
  healthy, which is the "a reader whose answer never varies has not read
  anything" trap.
- What CBS actually writes is
  `Session: <id> initialized by client <name>`, and the CLIENT is the
  valuable half: WindowsUpdateAgent, DISM Package Manager Provider, SPP,
  Arbiter, CbsTask. Measured: **12 sessions in CBS.log across 3 clients,
  9 in the archive across 6, one of which carried errors.**
- **There is no end marker**, so a session runs until the next begins.
  Inventing an end would be inventing information. Records before the
  first marker belong to NO session -- a tail slice opens mid-session,
  and attributing its preamble to a client that never asked for it
  would be a lie.
- **Scope, stated not buried:** this lists sessions and jumps to them.
  COLLAPSING a whole session, which this task also asked for, is
  deferred -- it needs the fold machinery to take arbitrary spans rather
  than parent/continuation pairs, and the listing is the part that
  answers "who asked for the work that failed".

### W2-07 (idea 20): Collapse near-identical lines

**Files:** create `src/modules/log_viewer/clustering.py`; pane; tests

**Interfaces:** `normalise(message) -> str` replacing GUIDs, hex addresses,
version numbers and package names with placeholders; `cluster(entries)`.

- [x] Test each normalisation with a real CBS line
- [x] Test: `test_two_lines_differing_only_by_guid_cluster_together`
- [x] Test: `test_two_genuinely_different_lines_do_not_cluster`
- [x] Test: `test_normalising_never_returns_an_empty_string`
- [x] **Run over the real archive: 125,012 CBS records should collapse to a
      few hundred distinct sentences. If it yields thousands, the
      normalisation is too timid; if it yields ten, it is too aggressive.**
- [x] Commit
- **Tuned against the real logs, in three passes.** First rules:
  16,417 forms -- too timid by this task's own yardstick. Looking at the
  singletons showed 13,093 of them differed only in an `Update:` value,
  so a key-anchored rule took it to 11,068; component-manifest names
  (`amd64_microsoft-windows-...`) and the leading 8-hex record id took
  it to **5,311**.
- **The honest number is not "distinct forms" but coverage: the top 200
  forms cover 95% of the archive's records** (88% of CBS.log, 94% of
  dism.log). "A few hundred forms" was optimistic for a 138,683-record
  file; "read 200 rows and you have seen 95% of the log" is the claim
  that is actually true.
- **Error codes are deliberately NOT normalised.** `0x800f0805` and
  `0x80073701` are the distinction, not noise; collapsing them would
  merge every failure into one row and discard the reason.
- Wired into `top_messages(key=normalise)`, the seam W2-01 left. The
  Repeated lines column now reads 19,962 / 16,748 / 11,950 instead of a
  verbatim maximum of 589.
- `lru_cache` on `normalise`: 35,657 distinct messages across 138,683
  records means three quarters of the work is the same string again.
  Summary refresh 1.91s -> 0.94s, normalising the archive 0.44s -> 0.02s.
- **The backslash-in-heredoc trap struck again and this time produced a
  literal BACKSPACE byte (0x08) inside a regex**, exactly as the project
  memory warns. `grep` cannot see it; `od -c` can. Written with the Write
  tool instead.

---

# Wave 3 — Reading and filtering

### W3-01 (idea 01): Bookmarks

**Files:** `log_model.py` (a bookmark set keyed by entry index), pane, tests

- [x] Test: `test_a_bookmarked_row_stays_bookmarked_through_a_filter`
- [x] Test: `test_bookmarks_follow_their_record_across_a_prepend` — indices
      shift by the chunk size, exactly like the viewport anchor
- [x] Test: `test_a_bookmark_on_an_unloaded_record_is_dropped_not_stale`
- [x] Ctrl+D toggles; a side list jumps
- [x] Commit
- **Held as RECORDS, never indices** -- the W2-02 lesson applied up
  front rather than after being bitten. Rows shift whenever the filter
  changes and entry indices shift by the size of every "load earlier"
  chunk, so either would come to mean a different record.
- Two structures on purpose: an id SET so the lookup in `data()` is
  O(1) (it runs per painted cell) and a reference LIST that keeps those
  ids valid. Without the references a record could be freed and its id
  reused, silently marking the wrong row.
- A bookmark on a record the cap has evicted drops out of the list
  rather than lingering as a row that goes nowhere.
- The star in the Time column is DISPLAY only, the same rule the fold
  suffix follows: export reads the record, so it cannot leak into a
  file.

### W3-02 (idea 03): Peek context through a filter

**Files:** `log_model.py`, pane, tests

- [x] Test: `test_peeking_reveals_the_neighbours_of_a_filtered_row`
- [x] Test: `test_peeked_rows_are_marked_so_they_read_as_context`
- [x] Test: `test_closing_the_peek_restores_the_filtered_view_exactly`
- [x] Test: `test_export_ignores_peeked_rows` (they are context, not matches)
- [x] Commit
- **Done, sharing one primitive with W3-03** (`_widened`): "show rows
  near an anchor", where peek anchors on one record and errors-with-
  context anchors on every Error.
- **They differ on one point, deliberately: peek reveals its
  neighbours UNCONDITIONALLY**, because it is an explicit "show me
  what this filter is hiding around this row" and honouring the filter
  would answer nothing. Error context stays inside the filter.
- **"Peek again to close" cannot ask whether the current row is the
  peeked one.** Once a peek opens, its neighbours are rows too, so the
  current row usually is not -- and the button peeked at a NEIGHBOUR
  instead of closing. `is_peeking()` asks whether a peek is open at
  all.

### W3-03 (idea 13): Errors with context

**Files:** `log_model.py`, pane, tests

- [x] Test: `test_context_mode_shows_n_rows_either_side_of_each_error`
- [x] Test: `test_overlapping_context_windows_are_merged_not_duplicated`
- [x] Test: `test_context_mode_with_no_errors_shows_nothing`
- [x] Commit
- **Done** as an "Errors + context" checkbox. Overlapping windows are
  merged, not concatenated: two errors three apart with three lines of
  context would otherwise list the rows between them twice.
- Context WIDENS what an anchor pulls in; it never overrides a filter
  the user set, or choosing a component would silently show rows from
  the components they excluded.
- A log with no errors says "no errors in what is loaded" rather than
  showing the ordinary "no rows match" -- the user asked for errors,
  and "there are none" is the answer.

### W3-04 (idea 09): Several filter terms

**Files:** `log_model.py`, pane, tests

- [x] Test: `test_space_separated_terms_are_ANDed`
- [x] Test: `test_a_quoted_phrase_is_one_term`
- [x] Test: `test_regex_mode_treats_the_whole_box_as_one_pattern`
- [x] Commit
- **The colouring had to follow the same split, and nothing in the
  suite would have caught it.** With terms ANDed, `package install`
  matches rows that never contain that string as typed, so the delegate
  compiled a needle nothing could match and the highlighting silently
  stopped working while the filter kept working.
- `split_terms` preserves CASE: the delegate colours what it is given
  and the model lowercases when it compares, so lowercasing in the
  split would make the highlight disagree with the box.
- An unmatched quote is a half-typed phrase, not a syntax error -- the
  rest is taken as ordinary terms. Empty terms are dropped, since one
  would match every row and silently widen the filter back out.
- Regex mode passes the box through whole: a pattern contains spaces of
  its own and splitting it would break it.

### W3-05 (idea 11): Saved filter presets

**Files:** create `src/modules/log_viewer/presets.py` with shipped defaults;
pane; tests

- [x] Test: `test_the_shipped_presets_all_parse`
- [x] Test: `test_applying_a_preset_sets_every_axis_it_names`
- [x] Test: `test_a_user_preset_survives_a_restart`
- [x] Ship: CBS servicing errors, DISM corruption, setup phase boundaries
- [x] **Each shipped preset must be checked against the real log it targets
      and its hit count recorded** — a preset that matches nothing is worse
      than no preset
- [x] Commit
- **Every shipped preset was run against the real logs before it was
  shipped**, which is the whole point: a preset that matches nothing
  answers "there is no such problem here" when it means "I was written
  wrong", and nobody re-checks a filter that came with the tool.

  | preset | CBS.log | archive | dism.log | setupact |
  |---|---|---|---|---|
  | Errors only | 0 | 522 | 0 | 29 |
  | Errors and warnings | 5 | 522 | 28 | 359 |
  | Failing result codes | 8 | 530 | 142 | 102 |
  | Store damage | 0 | **261** | 0 | 0 |
  | Hide servicing boilerplate | 10,188 | **48,390** | 12,034 | 13,119 |
  | Setup phase boundaries | 0 | 0 | 21 | **637** |

  (totals: 11,277 / 138,683 / 12,454 / 13,473. "Store damage" finds
  exactly the 261 SXS hash mismatches; "Hide boilerplate" removes 65%
  of the archive. A zero is correct where that log has no such
  problem.)
- **A preset is a whole view, not a patch**: applying one CLEARS the
  axes it does not name. Leaving yesterday's exclude in place would
  give a result neither the preset nor the user asked for, and it would
  be blamed on the preset.
- A stored preset with no name is dropped rather than shown as a blank
  menu row, and one bad row does not discard the good ones.

### W3-06 (idea 07): Column chooser

**Files:** pane, tests

- [x] Test: `test_hiding_a_column_persists`
- [x] Test: `test_the_message_column_cannot_be_hidden`
- [x] Test: `test_a_saved_choice_from_an_older_column_set_is_ignored`
- [x] Header context menu
- [x] Commit
- **Stored by NAME, never by index** -- which makes "a saved choice
  from an older column set is ignored" true by construction rather than
  by a version check. COLUMNS has already changed three times (Source,
  then Package); a saved list of positions would be applied to a
  different set and hide the wrong ones. A name that no longer exists is
  simply not found.
- **Visibility is computed from the whole truth in one place**, not by
  adding hiding on top of what `reload` decided. A column is hidden if
  the reader turned it off OR it would be blank (Source with one log,
  Package in a log naming none). An add-only pass could hide but never
  reveal -- which is exactly the test that failed first.
- The auto rules are cached per load: `has_packages()` scans records and
  this runs on every menu toggle.
- Message cannot be hidden: without it the table is metadata about lines
  you cannot read.

### W3-07 (idea 05): Wrap the selected row

**Files:** `log_delegate.py`, pane, tests

- [x] Test: `test_the_selected_row_reports_a_taller_size_hint`
- [x] Test: `test_only_one_row_is_ever_expanded`
- [x] Test: `test_expanding_does_not_break_the_rich_text_painting`
- [x] `sizeHint` on the delegate plus `resizeRowToContents`; beware the
      200k-row cost — only the selected row may be measured
- [x] Commit
- **The tests all passed while the feature did nothing**, and only the
  real archive showed it. Qt hands `sizeHint` an EMPTY rect when it asks
  during `resizeRowToContents`, and a text width of zero disables
  wrapping -- so the row came back one line tall. Every test here built
  an option rect with a real width and so never met the case. Measured
  on the archive: a 331-character message in an 817px column went
  24px -> 28px when it should have been 24px -> 60px. There is now a
  test that passes an empty rect.
- Only the SELECTED row is ever measured, and the two affected rows are
  resized explicitly rather than resizing the table -- measuring every
  row would lay out 200,000 messages to show one. Cost on the real
  archive: 15 ms on selection, 0 ms moving on.
- The expanded row always takes the rich-text path, because that is
  where wrapping lives; the plain path elides.

### W3-08 (idea 06): Pin rows

**Files:** pane (a second small table above the main one), tests

- [x] Test: `test_a_pinned_row_stays_visible_while_scrolling`
- [x] Test: `test_a_pinned_row_survives_a_filter_that_would_hide_it`
- [x] Test: `test_unpinning_removes_it`
- [x] Commit
- **The strip has its OWN model, not a proxy over the main one.** A
  pinned row has to survive a filter that would hide it -- keeping the
  error on screen while you scroll through what preceded it is the whole
  point -- and a proxy cannot show a row the source model has already
  excluded. That requirement is what chose the design.
- Held as RECORDS, like bookmarks, and sorted into log order rather than
  the order they were pinned.
- Pins are cleared when another log is opened: they belong to the file
  they came from, and carrying them across would show records that are
  not in it.
- Distinct from a bookmark, which is a place to jump back TO. A pin
  stays visible.

---

# Wave 4 — Getting logs in

### W4-01 (idea 26): Open a CbsPersist `.cab`

**Files:** `log_set.py` or a new `archives.py`; pane; tests

**Note:** the Diagnose CBS tab already extracts cabs with 7z — reuse that
code path rather than writing a second one.

- [x] Test: `test_a_cab_is_extracted_to_a_temp_file_and_opened`
- [x] Test: `test_a_cab_that_cannot_be_extracted_says_why`
- [x] Test: `test_the_temp_extraction_is_cleaned_up`
- [x] Test: `test_7z_missing_is_reported_rather_than_silently_failing`
- [x] Commit
- **Used `expand.exe`, NOT 7-Zip as this task suggested.** 7-Zip is
  installed on this machine and is not on most; depending on it would
  make the feature work on the developer's box and nowhere else.
  `expand.exe` ships with Windows. Its full path is used deliberately --
  a bare `expand` resolves to an unrelated tool under a POSIX shell.
- **Two things real CBS cabs do that a naive extractor gets wrong**, both
  found by running against the real folder: the member inside is named
  like the CAB (`cbspersist_20260829190803.cab`), so looking for `*.log`
  finds nothing; and it is 15.8 MB of text from a 465 KB cab.
- `expand` exits 0 while extracting nothing, so the return code is not
  the signal -- what came out is. The same rule the security readers
  follow.
- The status line names the CAB, not the temporary extraction: that is
  the file the user chose and the one still there tomorrow.

### W4-02 (idea 29): Recursive folder open with a checklist

**Files:** `log_set.py` (`logs_under(folder)`), a small dialog, pane, tests

- [x] Test: `test_a_recursive_scan_finds_nested_logs`
- [x] Test: `test_the_scan_is_capped_and_says_when_it_capped`
- [x] Test: `test_the_dialog_preselects_nothing_over_a_size_threshold`
- [x] `C:\Windows\Logs` has ~30 subfolders; the cap is the whole point
- [x] Commit
- **Measured the real tree first:** `C:/Windows/Logs` holds **90 logs,
  106 MB, across twelve subfolders** — 85 of them under 1 MB and one of
  them 84.5 MB. That shape chose the design: the list is ticked BY SIZE
  rather than wholesale, so the big archive is offered and not assumed.
- The flat scan stays flat, with a test pinning it. Pointing at a parent
  directory must not open everything beneath it.
- The scan reports whether it hit its cap, and the dialog says so: a
  silently truncated list reads as "this is everything there is".
- Results are sorted by full path so the checklist reads grouped by
  folder rather than in os.walk order.

### W4-03 (idea 31): Watch a folder for new logs

**Files:** `log_set.py`, pane, tests

- [x] Test: `test_a_log_appearing_after_open_is_picked_up`
- [x] Test: `test_a_log_that_disappears_does_not_raise`
- [x] Test: `test_watching_is_off_unless_following`
- [x] **Do not inject a fake change source and call it tested** — the file
      watcher in TreeSize had two fatal bugs behind 21 passing tests for
      exactly that reason. Drive it against a real temp folder.
- [x] Commit
- **Every test drives a REAL folder on disk**, as this task demanded:
  files are actually created and removed while the pane is open. No
  injected change source, which is what hid two fatal bugs in TreeSize's
  watcher behind 21 passing tests.
- Only a FOLDER is watched, and only while following. Opening one file
  is not a request to open its neighbours, and someone who is not
  following is not waiting for anything to arrive — it would be a
  directory listing per tick for nothing.
- A new source is given the SAME window share as the others rather than
  triggering a re-split: re-splitting would change every reader's budget
  mid-flight and re-read what is already loaded.
- A log — or the whole folder — disappearing is not an error.

### W4-04 (idea 30): Open a support bundle (zip)

**Files:** `archives.py`, pane, tests

- [x] Test: `test_a_zip_of_logs_opens_as_a_merged_set`
- [x] Test: `test_a_zip_entry_that_is_not_a_log_is_skipped`
- [x] Test: `test_a_zip_bomb_or_absolute_path_entry_is_refused` — `zipfile`
      will happily write outside the target directory otherwise
- [x] Commit
- **The Zip Slip guard is the substance of this task.** `zipfile` will
  write a member named `../escaped.log` or an absolute one wherever it
  says, and a viewer that unpacks a bundle from someone else's machine
  has to refuse that. Every member is joined to the target and checked
  AFTER resolution, which is what survives `..`, an absolute name and a
  symlinked temp directory alike. Refused members are logged and the
  safe ones still open.
- Non-log entries are skipped rather than extracted; a bundle holding no
  logs says so instead of opening an empty pane.

### W4-05 (idea 40): Validate the CMTrace path — **BLOCKED**

**Blocked on:** a genuine ConfigMgr or Intune log. A sweep on 2026-08-31 of
`C:\Windows\CCM`, `ccmsetup`, the Intune Management Extension folder,
`C:\Program Files` and `C:\ProgramData` found **zero files containing the
`<![LOG[` marker**. Every CMTrace test runs on fixtures written by hand.

- [ ] Ask the user for one real `CcmExec.log`, `AppEnforce.log` or
      `IntuneManagementExtension.log`
- [ ] Run `tools/log_viewer_real_check.py` against it
- [ ] Fix whatever it finds; record the record/component/thread counts
- [ ] Commit

---

# Wave 5 — Output and performance

### W5-01 (idea 35): Save and reopen a view

**Files:** create `src/modules/log_viewer/views.py`; pane; tests

**Interfaces:** a JSON document naming sources, every filter axis, the time
range, fold state and column layout.

- [x] Test: `test_a_saved_view_round_trips_every_axis`
- [x] Test: `test_opening_a_view_whose_logs_are_gone_says_which`
- [x] Test: `test_a_view_from_a_future_version_is_refused_not_half_applied`
- [x] Commit
- **Three rules, each because the alternative is a quiet lie:**
  every axis is written (one missing field and the view you reopen is
  not the one you saved, with nothing to say so — there is a test that
  every field actually reaches the file); missing sources are NAMED
  rather than skipped, since opening the rest quietly presents a partial
  investigation as a whole one; and a file from a NEWER version is
  refused outright, because half-applying something we do not understand
  gives a view that is neither the saved one nor the current one and
  blames neither.
- A file from an OLDER version still loads, with absent axes taking
  their defaults. Refusing those would make the format a one-way door.

### W5-02 (idea 36): Evidence bundle

**Files:** `log_export.py`, pane, tests

- [x] Test: `test_the_bundle_names_every_source_with_its_size_and_span`
- [x] Test: `test_the_bundle_states_how_much_of_each_file_was_loaded` — a
      32 MB window over a 381 MB file must say so, or the excerpt implies
      the whole file was searched
- [x] Test: `test_the_bundle_states_the_filters_in_force`
- [x] Commit
- **Verified on the real archive**, which is where the point lands:
  `loaded : 32.0 MB of 84.5 MB (38%)` beside the source's span. Without
  that line an excerpt implies the whole file was searched, and an
  absence of hits then reads as "this did not happen".
- **Found while running it: a source can vanish MID-SESSION.** Windows
  re-compacted the 363 MB `CbsPersist_20260827190818.log` back into its
  8.2 MB `.cab` during this very session, and the bundle reported
  `0.0 B of 0.0 B (0%)` — which reads as a fact about the file rather
  than as "it is not there any more". It now says so. (That churn is
  also exactly why W4-01's cab support matters.)
- No filters says "No filters — every loaded record was in view", since
  a blank section reads as "the filters were not recorded".

### W5-03 (idea 23): Error codes that explain themselves

**Files:** `error_codes.py` + a data file; `tests/test_log_error_codes.py`

- [ ] Test: `test_a_known_servicing_code_carries_a_cause_and_a_fix`
- [ ] Test: `test_an_unknown_code_still_decodes_its_name_without_inventing`
- [ ] **Never invent a fix.** Only codes with a documented, checkable cause
      go in the table; everything else keeps the name-only behaviour.
- [ ] Commit

### W5-04 (idea 25): Compare two logs

**Files:** create `src/modules/log_viewer/compare.py`; a dialog; tests

- [ ] Test: `test_identical_logs_report_no_differences`
- [ ] Test: `test_alignment_is_on_normalised_message_not_timestamp` — two
      machines never share a clock; reuse `normalise` from W2-07
- [ ] Test: `test_a_step_present_in_one_and_absent_in_the_other_is_reported`
- [ ] Commit

### W5-05 (idea 37): Parse off the UI thread

**Files:** pane, tests

- [ ] Test: `test_a_large_open_reports_progress`
- [ ] Test: `test_cancelling_a_load_leaves_the_pane_usable`
- [ ] Test: `test_a_worker_that_finishes_after_the_widget_is_gone_does_not_crash`
      — guard with `sip.isdeleted`, as the codebase already does
- [ ] Use `Worker` from `core/worker.py`; `worker.is_cancelled` is a
      property, not a method; cancel via `worker.cancel()`
- [ ] Only worth doing once a real open exceeds ~1 s; measure first
- [ ] Commit

### W5-06 (idea 38): Timestamp index for seeking

**Files:** `log_reader.py` or a new `timeindex.py`; tests

- [ ] Test: `test_the_index_maps_a_time_to_a_byte_offset_at_or_before_it`
- [ ] Test: `test_seeking_by_time_lands_on_a_line_boundary` — the same rule
      `_start` follows; a byte offset that is not a line boundary costs the
      seam line
- [ ] Test: `test_a_non_monotonic_log_does_not_break_the_index` — setupact
      goes backwards ten hours
- [ ] Commit

### W5-07 (idea 15): Search the part that is not loaded

**Files:** `log_reader.py`, pane, tests

- [ ] Test: `test_a_scan_finds_a_match_outside_the_loaded_window`
- [ ] Test: `test_the_scan_reports_the_byte_offset_so_it_can_be_paged_to`
- [ ] Test: `test_the_scan_can_be_cancelled`
- [ ] Test: `test_a_match_split_across_a_read_boundary_is_still_found` —
      overlap the reads by the needle length, or long needles are missed
- [ ] Commit

---

## Self-review notes

- **Coverage:** all forty ideas map to a task; the mapping is in each task's
  heading (`W<wave>-<n> (idea <k>)`).
- **Dependencies:** W2-05 needs W1-06's `row_at_or_after`. W5-04 needs
  W2-07's `normalise`. W4-04 shares `archives.py` with W4-01. Nothing else
  is ordered.
- **Deliberate deviation from the writing-plans skill:** tasks carry files,
  test names and design decisions rather than full implementation code.
  Forty tasks of complete code would be the implementation itself, and the
  test names plus the constraints above are what actually keep an executor
  honest here.
