r"""Searching the part of the file that was never loaded.

The window holds 32 MB of a 380 MB archive. A search that looks only at what
is in memory can answer "no match" about a file that contains the thing --
which is the worst answer a log viewer can give, because it is believed.

The awkward part is the read boundary: a needle that straddles two blocks is
invisible unless the blocks overlap. There is a test for exactly that.
"""

from modules.log_viewer.filescan import scan_file


def _write(path, text, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
    return str(path)


def test_a_match_is_found_with_its_offset(tmp_path):
    path = _write(tmp_path / "a.log", "one\ntwo\nNEEDLE here\nfour\n")

    hits = scan_file(path, "NEEDLE")

    assert len(hits) == 1
    assert hits[0].offset == len("one\ntwo\n")
    assert "NEEDLE here" in hits[0].line


def test_the_offset_is_the_start_of_the_LINE(tmp_path):
    r"""So it can be paged to: a byte offset mid-line is not seekable
    without losing the line it lands inside."""
    path = _write(tmp_path / "a.log", "aaaa\nbbbb NEEDLE\n")
    assert scan_file(path, "NEEDLE")[0].offset == 5


def test_matching_is_case_insensitive_like_the_filter(tmp_path):
    path = _write(tmp_path / "a.log", "the needle is here\n")
    assert scan_file(path, "NEEDLE")


def test_nothing_to_find_yields_nothing(tmp_path):
    path = _write(tmp_path / "a.log", "nothing of interest\n")
    assert scan_file(path, "NEEDLE") == []


def test_a_match_split_across_a_read_boundary_is_still_found(tmp_path):
    r"""The bug this feature is most likely to have. With a block size of N,
    a needle straddling the boundary is invisible unless the reads overlap.
    """
    filler = "x" * 1000
    path = _write(tmp_path / "a.log", filler + "\nSPLITME\n" + filler + "\n")

    hits = scan_file(path, "SPLITME", block_size=1004)

    assert len(hits) == 1, "the needle fell into the seam between two reads"


def test_a_needle_is_not_reported_twice_from_the_overlap(tmp_path):
    """The overlap that fixes the seam must not make a match near it count
    as two."""
    filler = "x" * 1000
    path = _write(tmp_path / "a.log", filler + "\nSPLITME\n" + filler + "\n")
    assert len(scan_file(path, "SPLITME", block_size=64)) == 1


def test_a_regex_can_be_scanned_for(tmp_path):
    path = _write(tmp_path / "a.log", "code 0x800f0805 here\n")
    assert scan_file(path, r"0x[0-9a-f]{8}", regex=True)


def test_a_half_typed_regex_finds_nothing_rather_than_raising(tmp_path):
    path = _write(tmp_path / "a.log", "anything\n")
    assert scan_file(path, "0x(", regex=True) == []


def test_the_scan_stops_at_its_limit(tmp_path):
    path = _write(tmp_path / "a.log", "NEEDLE\n" * 50)
    assert len(scan_file(path, "NEEDLE", limit=5)) == 5


def test_the_scan_can_be_cancelled(tmp_path):
    path = _write(tmp_path / "a.log", ("NEEDLE\n" + "x" * 500 + "\n") * 200)

    hits = scan_file(path, "NEEDLE", block_size=256,
                     is_cancelled=lambda: True)

    assert hits == [], "cancelling did not stop the scan"


def test_a_utf16_log_is_scanned_in_its_own_encoding(tmp_path):
    path = tmp_path / "ReportingEvents.log"
    with open(path, "wb") as handle:
        handle.write("first\nNEEDLE here\n".encode("utf-16"))

    hits = scan_file(str(path), "NEEDLE")

    assert hits, "a UTF-16 log was searched as if it were UTF-8"
    assert "NEEDLE" in hits[0].line


def test_a_missing_file_yields_nothing(tmp_path):
    assert scan_file(str(tmp_path / "nope.log"), "NEEDLE") == []


def test_only_the_region_before_an_offset_is_scanned(tmp_path):
    r"""The point of the feature: search what the window did NOT cover."""
    path = _write(tmp_path / "a.log", "EARLY match\n" + "x" * 100 + "\nLATE match\n")

    hits = scan_file(path, "match", end=12)

    assert len(hits) == 1
    assert "EARLY" in hits[0].line


def test_a_straddling_needle_is_found_even_after_an_earlier_hit(tmp_path):
    r"""The duplicate guard must not eat a real match.

    Deduplicating on "this match started inside the carried overlap" is
    wrong: a needle STRADDLING the boundary also starts inside the overlap
    and has never been reported. The first version of this guard only
    behaved because it was written as `if hits and ...`, so it was inert
    until something had already matched -- and the split test happened to
    have nothing matched yet.
    """
    filler = "x" * 1000
    text = ("NEEDLE early\n" + filler + "\nNEEDLE straddling\n" + filler
            + "\n")
    path = _write(tmp_path / "a.log", text)

    hits = scan_file(path, "NEEDLE", block_size=1020)

    assert len(hits) == 2, [h.line for h in hits]


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402


def _record(n, message):
    return ('<![LOG[{m}]LOG]!><time="13:45:{s:02d}.000+000" '
            'date="08-20-2026" component="CBS" context="" type="1" '
            'thread="1" file="a.cpp:1">\n').format(m=message, s=n % 60)


def test_find_offers_to_search_the_unloaded_part(qapp, tmp_path):
    r"""The window opens at the tail, so the early record is never loaded.
    Answering "No match" about a file that contains it is the failure."""
    path = tmp_path / "big.log"
    path.write_text(_record(0, "BURIED treasure")
                    + "".join(_record(n, f"filler {n}") for n in range(400)),
                    encoding="utf-8")

    widget = LogViewerWidget(max_bytes=2048)
    try:
        widget.open(str(path))
        assert widget.model.total < 401, "the fixture was not truncated"

        widget.find_box.setText("BURIED")
        widget.find_next()
        assert "no match" in widget.status.text().lower()

        found = widget.search_unloaded()

        assert found, "the scan missed a record that is in the file"
        assert "BURIED" in found[0].line
    finally:
        widget.stop()


def test_searching_the_unloaded_part_says_where_it_is(qapp, tmp_path):
    path = tmp_path / "big.log"
    path.write_text(_record(0, "BURIED treasure")
                    + "".join(_record(n, f"filler {n}") for n in range(400)),
                    encoding="utf-8")
    widget = LogViewerWidget(max_bytes=2048)
    try:
        widget.open(str(path))
        widget.find_box.setText("BURIED")
        widget.search_unloaded()
        text = widget.status.text().lower()
        assert "earlier" in text or "not loaded" in text
    finally:
        widget.stop()


def test_nothing_to_search_when_the_whole_file_is_loaded(qapp, tmp_path):
    path = tmp_path / "small.log"
    path.write_text(_record(0, "here"), encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.find_box.setText("here")
        assert widget.search_unloaded() == []
        assert "whole file" in widget.status.text().lower()
    finally:
        widget.stop()


def test_the_files_bom_does_not_ride_along_on_the_first_hit(tmp_path):
    r"""Every log under C:\Windows\Logs is UTF-8 WITH a BOM, and a hit on
    the very first line carried the invisible U+FEFF into the reported text.
    `LogReader` strips it; so must this, or the two disagree about what the
    first line of a file says."""
    path = tmp_path / "bom.log"
    path.write_bytes("\ufeffNEEDLE on the first line\n".encode("utf-8"))

    hits = scan_file(str(path), "NEEDLE")

    assert hits
    assert not hits[0].line.startswith("\ufeff")
