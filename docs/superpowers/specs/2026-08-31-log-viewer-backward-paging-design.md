# Log Viewer Backward Paging — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** Log Viewer upgrades, chunk 3 of 4
**Date:** 2026-08-31
**Status:** Approved

---

## Context

`LogReader` is forward-only. Opening a log larger than `DEFAULT_MAX_BYTES`
(32 MB) seeks to `size - max_bytes` and reads to the end; everything before
that offset is never read, and `_offset` only ever moves forward. On the real
380 MB `CbsPersist` archive this means the viewer shows the last 134,527
records of a file that has far more, and there is no way to reach the rest.

This chunk inverts that: a "Load earlier" step that reads the chunk
immediately *before* the loaded slice and prepends it.

Chunks 1 (capability pack, merge `2a452dc`) and 2 (continuation folding,
`bbac84d`) are done. Chunk 4 (merged multi-log timeline) remains and is out of
scope here.

### Decisions taken, not to be re-derived

The user chose these directly:

- **A repeatable sliding window.** Each step pulls in the previous chunk;
  because the 200,000-record cap cannot hold a 380 MB file, the window slides
  and the newest records are evicted. Walking back to the head of the file is
  therefore possible in steps.
- **Both triggers**: an explicit "Load earlier" button *and* auto-load on
  scrolling to the top, sharing one in-flight lock.
- **32 MB per step**, matching `DEFAULT_MAX_BYTES`. At ~170k records that is
  close to the whole 200k cap, so one step largely replaces what is loaded.
  This was chosen with that trade-off stated.

### What is already true, and must not be re-measured

From the chunk 1 spec, measured on this machine:

- Parsing runs at ~26 MB/s, so a 32 MB step costs ~1.2 s on the UI thread.
- 32 MB yields ~170,000 records against `LogModel`'s 200,000 cap.
- `_reindex()` over 134,527 records costs 0.05 s — negligible beside the parse.
- The 380 MB archive opens in 0.74 s, tail-capped, and yields
  126,932 shown of 134,527 with 7,595 folded.

---

## 1. Reader: an exact byte window

`LogReader` gains `_start`, the byte offset at which the loaded slice begins,
beside the existing `_offset` (how far forward it has read).

**`_start` must be a true line boundary, and today's equivalent is not.** The
first read of an oversized file seeks to `size - max_bytes`, lands mid-line,
and discards the partial first line *in decoded text* — but the byte number it
seeked to still points into the middle of that line. A backward read ending
there would end mid-line too, and the seam line would be lost from both
halves.

So the head-skip trim moves into bytes: find the encoded newline
(`"\n".encode(codec)`, which is `b"\n\x00"` for UTF-16 LE) at a
character-aligned position in the raw data, and set
`_start = start + index + len(newline)`. A backward read ending at `_start`
then loses and duplicates nothing.

Two new methods:

- **`has_earlier() -> bool`** — `_start > 0`.
- **`read_earlier() -> str`** — reads `[max(0, _start - max_bytes), _start)`,
  character-aligned; trims its own leading partial line the same way, unless
  it reaches byte 0, where it keeps everything and strips the BOM; moves
  `_start` backwards; returns the text.

A backward chunk is bounded on line boundaries at both ends, so it decodes
one-shot with `bytes.decode(codec, errors="replace")`. It must **not** touch
`self._decoder`, which holds incremental state for the forward stream that
Follow depends on.

**Out of scope by design:** when `_start` reaches 0, paging stops. Continuing
into the rolled `.lo_` sibling is one-reader-becomes-N, which the chunk 4 spec
owns; the existing "Include rolled" checkbox stays the way to get that
content.

## 2. Model: `prepend`, and eviction that is counted

`LogModel.prepend(entries)`:

- `self._entries.extendleft(reversed(entries))`. **`extendleft` reverses**, so
  the `reversed()` is not optional — without it the prepended chunk is
  inserted backwards and every timestamp runs the wrong way.
- The deque's `maxlen` then evicts from the **newest** end. That is the
  intended sliding-window behaviour, but it is silent, so the overflow is
  computed explicitly and added to a new counter, `unloaded_newer`, kept
  separate from the existing `dropped` ("aged out at the old end").
- Then `beginResetModel()` → `_reindex()` → `endResetModel()`.

A full reset rather than incremental index shifting: `_visible`, `_folded` and
`_fold_counts` are all keyed by entry index and every one of them shifts by N
anyway, and `_reindex()` costs 0.05 s against the 1.2 s parse that precedes
it. The reset clears the selection — which `append` documents as the trap it
exists to avoid — and that is acceptable only because a prepend is a
deliberate user action and section 4 restores the viewport regardless.

**This is what fixes chunk 2's orphan.** `_recount_folds()` re-runs over the
whole deque, so the continuation that had no parent at the top of the tail
slice finds its real parent in the newly-arrived chunk and folds under it.
The correction is free but needs its own test: it is the only place chunks 2
and 3 touch.

**Degenerate case:** if a prepended batch exceeds `maxlen`, `extendleft` keeps
its oldest end and discards the seam along with everything already loaded.
32 MB ≈ 170k records against a 200k cap, so it cannot happen today; it is one
comparison to refuse rather than silently corrupt.

## 3. Pane: button plus auto-load, one lock

- A **"Load earlier"** button beside Follow, enabled only when
  `_reader.has_earlier()`.
- `verticalScrollBar().valueChanged` triggers the same load at the minimum.
- Both go through one method holding a `_loading_earlier` flag. Without it the
  auto path chains: a load takes ~1.2 s, during which more scroll events
  arrive.
- **Loading earlier unchecks Follow.** With the window slid back, the tail has
  been evicted, so appending live lines would splice new records onto a slice
  they are not contiguous with — a fabricated timeline, worse than not
  following. A **"Newest"** button restores the tail by calling `reload()`.
- After a prepend, `provider.set_entries(...)` is called, exactly as `_poll`
  does today. Otherwise Find silently searches the pre-prepend list.

## 4. Viewport anchoring

Before the load, record the entry index at the view's top row. After it, that
index has shifted by exactly N — eviction happens at the far end and shifts
nothing — so a `bisect` over `_visible` (which is sorted ascending) finds its
new row, and `scrollTo(..., PositionAtTop)` puts it back under the cursor.

This is not a nicety. Without it the view stays at row 0, which immediately
re-fires the auto-load. If the anchor was itself evicted — possible when the
button is pressed while scrolled near the bottom — the bisect lands past the
end and the view goes to the last row.

## 5. Status bar

The status gains the loaded window's true extent, replacing the vaguer
"opened at the tail of a large file" once paging has happened: which byte
range of the file is loaded, and `N newer records unloaded` when
`unloaded_newer` is non-zero.

Showing a slice out of the middle of a file without saying so is the same
failure as silently showing the last 200k lines of a 900k-line log: it is how
someone concludes a log is clean.

## 6. Testing

- **Reader, on real temp files.** Page a file backwards to byte 0 and
  reassemble it: the concatenation must equal the original line for line, with
  no line lost or duplicated at any seam. The same against a UTF-16 LE file,
  where a one-byte misalignment turns the whole slice into CJK.
- **Model.** Order preserved through `extendleft`; `unloaded_newer` counted;
  the orphan continuation folding under its newly-arrived parent.
- **Crossing two interactions** — the specific gap that let three defects
  through in the real-log pass: filter → load earlier → filter still applied;
  Follow on → load earlier → Follow off; find a match → load earlier → the
  search provider sees the new entries.
- **Real data.** Extend `tools/log_viewer_real_check.py` to page the 380 MB
  CBS archive back to byte 0, checking continuity and reporting totals. Per
  the standing habit of this project, a green suite is not evidence here; the
  archive is.
