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
| 1 | Quick wins that change daily use | 13 | 9 |
| 2 | Analysis — what the tool is *for* | 7 | 0 |
| 3 | Reading and filtering | 8 | 0 |
| 4 | Getting logs in | 5 | 0 |
| 5 | Output and performance | 7 | 0 |

**Next task:** W1-04.

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

- [ ] Test: `test_two_components_can_be_shown_at_once`
- [ ] Test: `test_a_single_component_string_still_works` (back-compat)
- [ ] Test: `test_clearing_the_selection_shows_every_component`
- [ ] Replace the combos with checkable ones (`QListWidget` in a
      `QComboBox` view, or a `QToolButton` + checkable `QMenu`); the Thread
      combo has 329 entries on DISM, so keep it searchable
- [ ] Commit

### W1-05 (idea 04): Keyboard navigation

**Files:** `log_viewer_module.py`, `tests/test_log_viewer_module.py`

**Interfaces:** `QShortcut`s owned by the widget: `/` focus filter,
`Ctrl+F` focus find, `F3`/`n` next match, `Shift+F3`/`N` previous,
`Ctrl+Home`/`Ctrl+End` first/last row.

- [ ] Test: `test_the_find_shortcut_focuses_the_find_box`
- [ ] Test: `test_f3_moves_to_the_next_match`
- [ ] Test: `test_shift_f3_moves_back`
- [ ] Single-letter shortcuts must NOT fire while a text box has focus —
      test that too: `test_typing_a_slash_into_the_filter_is_not_a_shortcut`
- [ ] Commit

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

- [ ] Test: `test_a_source_with_no_timestamps_at_all_sorts_last`
- [ ] Test: `test_a_source_with_SOME_timestamps_is_not_moved`
- [ ] Test: `test_an_orphan_continuation_is_still_not_dropped` (regression —
      the epoch is still right for a record inside a timestamped file)
- [ ] Implement: decide per SOURCE, not per record. If a source has no real
      timestamp anywhere, give its records a sentinel that sorts last;
      otherwise the existing inherit-from-above rule stands
- [ ] Real check: reopen the CBS folder, confirm FilterList no longer leads
- [ ] Commit

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

- [ ] Test: `test_column_widths_are_saved_and_restored`
- [ ] Test: `test_the_splitter_position_survives_a_reopen`
- [ ] Test: `test_a_saved_layout_from_an_older_column_set_is_ignored`
      — `COLUMNS` has changed twice; a stale saved width list must not be
      applied positionally to a different set of columns
- [ ] Persist via `self._config`; save on `closeEvent`/`on_deactivate`
- [ ] Commit

---

# Wave 2 — Analysis

The group that changes what the tool is for. Each of these belongs in a new
Qt-free module beside `log_set.py`, with the pane only rendering the result.

### W2-01 (idea 19): Top-N panel

**Files:** create `src/modules/log_viewer/log_stats.py`; pane; create
`tests/test_log_stats.py`

**Interfaces:** `top_codes(entries, n)`, `top_components(entries, n)`,
`top_messages(entries, n)` → `[(value, count)]`.

- [ ] Test each returns counts descending, ties broken by value
- [ ] Test: `test_counting_ignores_folded_state` (it counts records, not rows)
- [ ] Test: `test_an_empty_log_yields_empty_lists_rather_than_raising`
- [ ] Pane: a collapsible panel; clicking a row applies it as a filter
- [ ] **Time it on the real 380 MB archive's 200k records** — if a refresh
      costs more than ~200 ms it must not run on every keystroke
- [ ] Commit

### W2-02 (idea 18): Stall detection

**Files:** `log_stats.py`, `log_model.py` (a marker role), pane, tests

**Interfaces:** `gaps(entries, threshold_seconds) -> [(index, seconds)]`.

- [ ] Test: `test_a_gap_longer_than_the_threshold_is_reported`
- [ ] Test: `test_records_with_no_timestamp_do_not_create_false_gaps` —
      continuations inherit, so use the effective timestamp
- [ ] Test: `test_a_backwards_clock_step_is_not_reported_as_a_gap` —
      setupact jumps ten hours backwards at a phase boundary; a negative
      delta is not a stall
- [ ] Render as a marker in the gutter or a tinted row; threshold in the UI
- [ ] Commit

### W2-03 (idea 22): KB and package column

**Files:** `cmtrace_parser.py` or a new `packages.py`, `log_model.py`, tests

**Interfaces:** `package_of(message) -> str` extracting
`Package_for_KB3025096~31bf3856ad364e35~amd64~~6.4.1.0` → `KB3025096`.

- [ ] Test: with a real CBS line as the fixture
- [ ] Test: `test_a_line_with_no_package_yields_empty`
- [ ] Test: `test_an_update_id_is_not_mistaken_for_a_kb`
- [ ] New optional column, hidden unless a log actually carries packages
      (same rule the Source column follows)
- [ ] **Run over the real archive and report how many records carry one**
- [ ] Commit

### W2-04 (idea 21): First error, last success

**Files:** `log_stats.py`, pane, tests

**Interfaces:** `first_error(entries)`, `last_before(entries, index)`.

- [ ] Test: `test_the_first_error_is_the_earliest_error_row`
- [ ] Test: `test_the_last_success_is_the_record_before_it`
- [ ] Test: `test_a_log_with_no_errors_says_so_rather_than_returning_none`
- [ ] Render as a summary strip with two clickable rows
- [ ] Commit

### W2-05 (idea 16): Error-density strip

**Files:** create `src/modules/log_viewer/density.py` (Qt-free bucketing) and
a small `QWidget` painter in the pane; tests for the bucketing

**Interfaces:** `buckets(entries, count) -> [(start_time, total, errors)]`.

- [ ] Test: `test_buckets_span_the_whole_range`
- [ ] Test: `test_every_record_lands_in_exactly_one_bucket`
- [ ] Test: `test_a_single_instant_log_does_not_divide_by_zero`
- [ ] Test: `test_records_with_no_timestamp_are_excluded_not_bucketed_at_epoch`
- [ ] Painter: `QPainter`, int coordinates only (PyQt6 is strict — see
      `perfmon_charts.py`), theme colours from `semantic_colors`
- [ ] Click maps x → time → `row_at_or_after` from W1-06 (depends on it)
- [ ] **Look at it in both themes on the real archive**
- [ ] Commit

### W2-06 (idea 17): Servicing sessions

**Files:** create `src/modules/log_viewer/sessions.py`; `log_model.py`; tests

**Interfaces:** `sessions(entries) -> [Session(start, end, outcome, indices)]`
detecting `Beginning TrustedInstaller` / `Ending TrustedInstaller`.

- [ ] Test: `test_a_matched_pair_becomes_one_session`
- [ ] Test: `test_a_session_left_open_at_the_end_of_the_slice_still_reports`
      — a tail slice routinely starts mid-session
- [ ] Test: `test_a_session_with_an_error_inside_it_is_marked_failed`
- [ ] Test: `test_nested_or_repeated_beginnings_do_not_lose_records`
- [ ] Collapse reuses the folding machinery from chunk 2 (`_folded` is just
      a set of indices; it is a filter, not a tree)
- [ ] **Count sessions on the real archive and sanity-check the number**
- [ ] Commit

### W2-07 (idea 20): Collapse near-identical lines

**Files:** create `src/modules/log_viewer/clustering.py`; pane; tests

**Interfaces:** `normalise(message) -> str` replacing GUIDs, hex addresses,
version numbers and package names with placeholders; `cluster(entries)`.

- [ ] Test each normalisation with a real CBS line
- [ ] Test: `test_two_lines_differing_only_by_guid_cluster_together`
- [ ] Test: `test_two_genuinely_different_lines_do_not_cluster`
- [ ] Test: `test_normalising_never_returns_an_empty_string`
- [ ] **Run over the real archive: 125,012 CBS records should collapse to a
      few hundred distinct sentences. If it yields thousands, the
      normalisation is too timid; if it yields ten, it is too aggressive.**
- [ ] Commit

---

# Wave 3 — Reading and filtering

### W3-01 (idea 01): Bookmarks

**Files:** `log_model.py` (a bookmark set keyed by entry index), pane, tests

- [ ] Test: `test_a_bookmarked_row_stays_bookmarked_through_a_filter`
- [ ] Test: `test_bookmarks_follow_their_record_across_a_prepend` — indices
      shift by the chunk size, exactly like the viewport anchor
- [ ] Test: `test_a_bookmark_on_an_unloaded_record_is_dropped_not_stale`
- [ ] Ctrl+D toggles; a side list jumps
- [ ] Commit

### W3-02 (idea 03): Peek context through a filter

**Files:** `log_model.py`, pane, tests

- [ ] Test: `test_peeking_reveals_the_neighbours_of_a_filtered_row`
- [ ] Test: `test_peeked_rows_are_marked_so_they_read_as_context`
- [ ] Test: `test_closing_the_peek_restores_the_filtered_view_exactly`
- [ ] Test: `test_export_ignores_peeked_rows` (they are context, not matches)
- [ ] Commit

### W3-03 (idea 13): Errors with context

**Files:** `log_model.py`, pane, tests

- [ ] Test: `test_context_mode_shows_n_rows_either_side_of_each_error`
- [ ] Test: `test_overlapping_context_windows_are_merged_not_duplicated`
- [ ] Test: `test_context_mode_with_no_errors_shows_nothing`
- [ ] Commit

### W3-04 (idea 09): Several filter terms

**Files:** `log_model.py`, pane, tests

- [ ] Test: `test_space_separated_terms_are_ANDed`
- [ ] Test: `test_a_quoted_phrase_is_one_term`
- [ ] Test: `test_regex_mode_treats_the_whole_box_as_one_pattern`
- [ ] Commit

### W3-05 (idea 11): Saved filter presets

**Files:** create `src/modules/log_viewer/presets.py` with shipped defaults;
pane; tests

- [ ] Test: `test_the_shipped_presets_all_parse`
- [ ] Test: `test_applying_a_preset_sets_every_axis_it_names`
- [ ] Test: `test_a_user_preset_survives_a_restart`
- [ ] Ship: CBS servicing errors, DISM corruption, setup phase boundaries
- [ ] **Each shipped preset must be checked against the real log it targets
      and its hit count recorded** — a preset that matches nothing is worse
      than no preset
- [ ] Commit

### W3-06 (idea 07): Column chooser

**Files:** pane, tests

- [ ] Test: `test_hiding_a_column_persists`
- [ ] Test: `test_the_message_column_cannot_be_hidden`
- [ ] Test: `test_a_saved_choice_from_an_older_column_set_is_ignored`
- [ ] Header context menu
- [ ] Commit

### W3-07 (idea 05): Wrap the selected row

**Files:** `log_delegate.py`, pane, tests

- [ ] Test: `test_the_selected_row_reports_a_taller_size_hint`
- [ ] Test: `test_only_one_row_is_ever_expanded`
- [ ] Test: `test_expanding_does_not_break_the_rich_text_painting`
- [ ] `sizeHint` on the delegate plus `resizeRowToContents`; beware the
      200k-row cost — only the selected row may be measured
- [ ] Commit

### W3-08 (idea 06): Pin rows

**Files:** pane (a second small table above the main one), tests

- [ ] Test: `test_a_pinned_row_stays_visible_while_scrolling`
- [ ] Test: `test_a_pinned_row_survives_a_filter_that_would_hide_it`
- [ ] Test: `test_unpinning_removes_it`
- [ ] Commit

---

# Wave 4 — Getting logs in

### W4-01 (idea 26): Open a CbsPersist `.cab`

**Files:** `log_set.py` or a new `archives.py`; pane; tests

**Note:** the Diagnose CBS tab already extracts cabs with 7z — reuse that
code path rather than writing a second one.

- [ ] Test: `test_a_cab_is_extracted_to_a_temp_file_and_opened`
- [ ] Test: `test_a_cab_that_cannot_be_extracted_says_why`
- [ ] Test: `test_the_temp_extraction_is_cleaned_up`
- [ ] Test: `test_7z_missing_is_reported_rather_than_silently_failing`
- [ ] Commit

### W4-02 (idea 29): Recursive folder open with a checklist

**Files:** `log_set.py` (`logs_under(folder)`), a small dialog, pane, tests

- [ ] Test: `test_a_recursive_scan_finds_nested_logs`
- [ ] Test: `test_the_scan_is_capped_and_says_when_it_capped`
- [ ] Test: `test_the_dialog_preselects_nothing_over_a_size_threshold`
- [ ] `C:\Windows\Logs` has ~30 subfolders; the cap is the whole point
- [ ] Commit

### W4-03 (idea 31): Watch a folder for new logs

**Files:** `log_set.py`, pane, tests

- [ ] Test: `test_a_log_appearing_after_open_is_picked_up`
- [ ] Test: `test_a_log_that_disappears_does_not_raise`
- [ ] Test: `test_watching_is_off_unless_following`
- [ ] **Do not inject a fake change source and call it tested** — the file
      watcher in TreeSize had two fatal bugs behind 21 passing tests for
      exactly that reason. Drive it against a real temp folder.
- [ ] Commit

### W4-04 (idea 30): Open a support bundle (zip)

**Files:** `archives.py`, pane, tests

- [ ] Test: `test_a_zip_of_logs_opens_as_a_merged_set`
- [ ] Test: `test_a_zip_entry_that_is_not_a_log_is_skipped`
- [ ] Test: `test_a_zip_bomb_or_absolute_path_entry_is_refused` — `zipfile`
      will happily write outside the target directory otherwise
- [ ] Commit

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

- [ ] Test: `test_a_saved_view_round_trips_every_axis`
- [ ] Test: `test_opening_a_view_whose_logs_are_gone_says_which`
- [ ] Test: `test_a_view_from_a_future_version_is_refused_not_half_applied`
- [ ] Commit

### W5-02 (idea 36): Evidence bundle

**Files:** `log_export.py`, pane, tests

- [ ] Test: `test_the_bundle_names_every_source_with_its_size_and_span`
- [ ] Test: `test_the_bundle_states_how_much_of_each_file_was_loaded` — a
      32 MB window over a 381 MB file must say so, or the excerpt implies
      the whole file was searched
- [ ] Test: `test_the_bundle_states_the_filters_in_force`
- [ ] Commit

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
