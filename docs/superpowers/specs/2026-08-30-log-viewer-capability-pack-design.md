# Log Viewer Capability Pack — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** Log Viewer upgrades, chunk 1 of 4
**Date:** 2026-08-30
**Status:** Approved

---

## Context

The Log Viewer (`src/modules/log_viewer/`) had never met a real log until
2026-08-30, when pointing it at this machine's own found eight defects that
2,525 passing tests could not see (merge `f60d00b`). Severity is now read from
the line rather than guessed, the Component and Thread fields are populated,
messages no longer repeat their own prefix, and a detail pane reaches the
elided ones.

That work made a set of fields *trustworthy* for the first time. This spec
spends them: the pane can now filter on data it could not previously believe.

### Sub-project decomposition

The user asked for six feature areas spanning three layers. They are split
into four chunks, each with its own design-plan-build cycle, in this order:

1. **Capability pack (this spec)** — thread filter, time range, regex,
   export/copy, Error Lookup dialog, colour coding. Additive over the
   existing model; no interface changes.
2. **Continuation folding** — folding CSI's 1,260-line blocks under their
   parent record. Breaks the 1:1 row↔entry mapping that `_visible`,
   `find()` and `LogSearchProvider` assume, so it wants its own pass.
3. **Backward paging** — "load earlier" on a 380 MB file. `LogReader` is
   forward-only from a byte offset today; this inverts that.
4. **Merged multi-log timeline** — one reader becomes N, `LogModel` gains a
   Source column, the status bar and search provider both change. Heaviest,
   and much better after chunk 1, because a merged CBS+DISM+setupact view
   without a time-range filter is unreadable.

Chunks 2–4 are out of scope here and must not be started as part of it.

### What is already true, and must not be re-derived

Measured on this machine on 2026-08-30. These numbers drive design decisions
below and are recorded so nobody re-measures them:

| log | records | distinct threads | distinct components | span |
|---|---|---|---|---|
| CBS.log | 23,957 | 0 | 3 | 18 h |
| dism.log | 11,882 | **329** | 2 | 5 d |
| ReportingEvents.log | 1,693 | 0 | 0 | 32 d |
| setupact.log | 13,473 | 22 | 15 | 10 h |
| setuperr.log | 27 | 0 | 4 | 10 h |
| CbsPersist (archive) | 90,714 | 0 | 3 | 2 d |

Also already established:

- Filtering 134,527 rows costs **0.05 s**; the 380 MB archive opens in
  **0.74 s** on the UI thread, tail-capped.
- `LogSearchProvider` **already** honours `regex_enabled`, `date_from` and
  `date_to` for the global search bar. The pane's own Find and Filter boxes do
  not. Part of this work is catching the pane up to its own provider.
- **The Log Viewer is not theme-exempt.** `tests/test_theme_light_coverage.py`
  has `THEME_EXEMPT = {"TreeSize"}` and measures *rendered luminance*
  specifically so it cannot be fooled by a colour painted by a delegate.
- `ROW_COLOURS` in `log_model.py` is hardcoded for the dark sheet by its own
  comment, and every new colour system in this spec stacks on top of it.

---

## Requirements

1. Filter the open log by thread, and by an absolute or row-anchored time range.
2. Use a regular expression in Find and in Filter.
3. Get the filtered rows out — to the clipboard, to a text file, to CSV.
4. Look up an error code that is not already on a visible row.
5. Colour rows by three independent systems at once without any of them
   hiding another.
6. Everything must work under **both** themes.

---

## Architecture

### File layout

`log_viewer_module.py` is 349 lines. Six features added inline would take it
past 900 and mix six concerns. The codebase's strongest convention says
otherwise — no Qt in `scan/`+`store/`, none in the parser or reader, and only
3 of `gpresult/`'s 10 files import Qt — so the logic layer stays headless:

| file | new? | Qt? | owns |
|---|---|---|---|
| `highlight.py` | new | no | `HighlightRule`, matching, load/save via `app.config` |
| `palette.py` | new | no | component → colour, per theme; returns RGB triples, not `QColor` |
| `log_export.py` | new | no | text and CSV writers over a sequence of `LogEntry` |
| `log_delegate.py` | new | **yes** | inline code colouring in Message; tint in Component |
| `error_lookup_dialog.py` | new | **yes** | paste-a-code dialog over the existing `describe()` |
| `log_model.py` | changed | yes | new filter axes, `threads()`, colour roles |
| `log_viewer_module.py` | changed | yes | one filter row, a context menu, and the wiring |

Every decision about *what* colour or *which* rows is testable without a
display. Only painting needs one.

### Colour model

Three systems, three territories, so none can hide another:

| system | territory | precedence |
|---|---|---|
| highlight rule | whole row background | wins over severity |
| severity | whole row background | used when no rule matches |
| component tint | **Component column only** | never leaves that column |
| error codes | inline spans in Message | independent of the above |

The Component column is the one place the row background does **not** apply:
its tint wins there, over both severity and a highlight rule. That is what
"territory" means — otherwise every Error row would lose its component colour,
which is exactly the failure mode the strict-priority option had.

Component colours are assigned by **hash of the component name into a fixed
16-entry palette**, not by sort order. CBS is then the same colour in every
log and after every restart, and a new component appearing does not reshuffle
the others. The measured maximum is 15 distinct components, so collisions are
not a practical concern; a collision is a cosmetic repeat, never an error.

`palette.py` exposes a light and a dark variant of every colour, and
`ROW_COLOURS` is moved into it and given a light variant too — it is the
direct cause of the theme constraint and this work stacks on it.

### Data flow

Nothing changes upstream. `LogReader` → `cmtrace_parser.parse` → `LogEntry`
is untouched. All six features read `LogEntry` and the model's existing
`_visible` index list.

`LogModel.set_filter` gains `thread`, `time_from`, `time_to` and `regex`
arguments, following the existing optional-argument pattern exactly (a `None`
means "leave this axis as it was"). `_matches` gains the corresponding
clauses. `_reindex` stays a single O(n) pass; the regex is compiled **once**
per `set_filter` call and stored, never compiled per row.

`LogModel.threads()` is added beside `components()`, returning
`[(thread_id, count), …]` ordered by count descending — the combo needs the
counts to be usable at 329 entries.

---

## Component design

### `highlight.py` (no Qt)

```
@dataclass(frozen=True)
class HighlightRule:
    pattern: str
    colour: str        # "#RRGGBB", theme-independent; the user picked it
    regex: bool = False
    enabled: bool = True

def matching_rule(rules, entry) -> Optional[HighlightRule]
def load_rules(config) -> list[HighlightRule]
def save_rules(config, rules) -> None
```

- Rules are matched **in order**; the first match wins, so the editor's order
  is meaningful and visible.
- An invalid regex is a typo, not a failure: it matches nothing, raises
  nothing, and the rule is flagged in the editor. This mirrors
  `LogSearchProvider.search`, which already treats a bad pattern that way.
- Persisted globally under `log_viewer.highlight_rules` in `app.config`, as
  a list of dicts. Global, not per-file: the user's answer was that a rule
  like "highlight my machine name" should apply to every log.
- A rule matches against the same haystack the filter uses —
  message, level and component — so a rule can target a component.

### `palette.py` (no Qt)

```
COMPONENT_COLOURS_DARK  = [...16 (bg, fg) pairs...]
COMPONENT_COLOURS_LIGHT = [...16...]
SEVERITY_COLOURS_DARK   = {"Error": (...), "Warning": (...)}
SEVERITY_COLOURS_LIGHT  = {...}

def component_colour(name: str, dark: bool) -> tuple[str, str]
def severity_colour(level: str, dark: bool) -> Optional[tuple[str, str]]
```

Returns hex strings. The model wraps them in `QColor`; nothing here imports
Qt, so contrast can be asserted in a headless test.

Every pair must clear a contrast ratio of **4.5:1** of foreground against its
own background, asserted by a test over all 16 entries in both variants. The
Security Dashboard shipped card titles at 1.51:1 once; that is what the theme
test exists to prevent.

### `log_export.py` (no Qt)

```
def as_text(entries, header: bool = True) -> str
def as_csv(entries) -> str
```

`header=True` for a file export, `header=False` for the clipboard: a two-line
provenance note is right at the top of a saved file and pure noise when
someone copies three rows into a chat message.

**Both write the parsed view, not the original bytes.** This is a deliberate
trade-off, approved by the user: keeping every original line would roughly
double the model's footprint at its 200,000-record cap, and reconstructing
one from `raw["line"]` is unreliable the moment the file is tail-capped,
followed, or read together with a rolled `.lo_` sibling. The original file is
always still on disk when a verbatim copy is wanted. The exporter states this
in a one-line header comment in the `.txt` output so a reader is never misled
about what they are holding.

CSV goes through `csv.writer` with `lineterminator="\n"`, so a message
containing a comma, a quote or a newline survives the round trip.

### `log_delegate.py` (Qt)

A `QStyledItemDelegate` on the table, painting two things:

- **Component column** — the component's tint as the cell background.
- **Message column** — error codes picked out in the failure colour.
  `error_codes.find_codes()` already returns the codes in a string; the
  delegate needs their spans, so `find_codes` gains a sibling that returns
  `(start, end, code)` rather than duplicating its regex.

Painted with `QTextDocument` only for rows whose message actually contains a
code — the common row keeps the plain fast path. Qt paints only visible rows,
so the cost is bounded by the viewport, not by the 134,527 records; this is
asserted by measurement rather than assumed (see Risks).

### `error_lookup_dialog.py` (Qt)

A modeless dialog: paste text or a bare code, get every code in it described
via the existing `find_codes()`/`describe()`. Opened from a toolbar button and
from a row's context menu ("Look up codes on this row"). It is a thin shell
over `error_codes.py`; no lookup logic lives in it.

### Pane changes (`log_viewer_module.py`)

One new filter row beneath the existing Find/Filter row:

```
Thread: [ combo, editable, completer ]   From: [ datetime ] To: [ datetime ]
[ Clear range ]   [x] Regex   [ Highlight… ]   [ Export… ]   [ Error lookup… ]
```

- **Thread** is an editable `QComboBox` with a completer, entries formatted
  `"29016  (1,204)"` and ordered by count. Not a flat dropdown: DISM has 329.
- **From/To** are `QDateTimeEdit`s prefilled from the model's own min and max
  timestamps, so the range starts as the whole log rather than as 1752.
- **Row context menu** gains "Show ±1/5/15/60 minutes around this row", which
  sets From/To from the row's timestamp. This is the primary way the range is
  meant to be used: you find an error, then ask what surrounded it.
- **Regex** is one checkbox governing both Find and Filter, mirroring
  `SearchQuery.regex_enabled`.
- **Ctrl+C** copies the selected rows through
  `log_export.as_text(header=False)`.

`Export…` is a split button offering `.txt` and `.csv`, writing whatever the
current filter leaves visible — not the whole log.

---

## Error handling

- An invalid regex, in Find, Filter or a highlight rule, matches nothing and
  says so in the status bar. It never raises and never opens a dialog: the
  user is mid-typing.
- A `From` later than `To` is reported in the status bar and filters nothing,
  rather than silently showing an empty table that reads as "no such records".
- An export that cannot write (permission, disk) reports the reason in the
  status bar and leaves no partial file.
- A corrupt or hand-edited `highlight_rules` config entry is skipped
  per-rule, with a warning logged, rather than costing the user every rule.

---

## Testing

Headless, no display, in the existing style:

- `highlight.py` — order and first-match-wins, invalid regex is inert,
  round-trip through a stub config, a corrupt entry does not poison the rest.
- `palette.py` — same name always yields the same colour; all 16 entries in
  both themes clear 4.5:1; a component absent from the palette still gets one.
- `log_export.py` — a message containing a comma, a quote and a newline
  survives CSV; the text header states it is the parsed view; an empty
  selection yields an empty export, not a crash.
- `log_model.py` — each new filter axis alone and in combination; the regex is
  compiled once per `set_filter`; `threads()` ordering by count.

Widget tests in the style of `test_log_viewer_module.py` for the delegate, the
dialogs, the context menu, and Ctrl+C.

Real-machine verification, which is the standing habit here and the only thing
that has ever found a defect in this module:

- `tools/log_viewer_real_check.py` gains distinct-thread reporting and a
  filter-sanity pass (a filter must never return more rows than it was given).
- Render the pane on the real logs and **look at it**, under **both** themes —
  new territory for this pane, and the reason the theme constraint is called
  out above.
- Run `tests/test_theme_light_coverage.py` explicitly; the Log Viewer is not
  exempt from it.

---

## Risks

| risk | how it is settled |
|---|---|
| Regex filtering on every keystroke across 134,527 rows | Measure. The existing substring filter costs 0.05 s; if regex is materially worse, debounce the Filter box. Do not assume either way. |
| Delegate paint cost while scrolling the 380 MB log | Measure with the Qt probe. Only visible rows paint, and only rows containing a code take the rich-text path. |
| 16 colours indistinguishable from each other on one sheet | The contrast test covers foreground-on-background readability, not inter-colour distinctness. That one is settled by looking at the rendered pane, not by a test. |
| New colours failing the light-theme luminance test | The pane is not exempt. Both palettes ship together, and the test is run as part of the work rather than at the end. |

---

## Out of scope

Chunks 2, 3 and 4 above. Also explicitly not included: saving filter state
across sessions (only highlight rules persist), per-file highlight rules,
reworking the severity palette's *choice* of red and yellow (it gains a light
variant, it does not change hue), and anything touching the CMTrace path,
which still cannot be validated on this machine.
