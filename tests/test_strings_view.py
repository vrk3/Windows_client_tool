# tests/test_strings_view.py  (logic only — no Qt)
from modules.process_explorer.lower_pane.strings_view import extract_strings


def test_extract_ascii_strings(tmp_path):
    data = b"\x00hello world\x00" + b"AB" + b"\x00\x00toolong_string_here\x00"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    results = extract_strings(str(f), min_len=4, encoding="ascii")
    assert "hello world" in results
    assert "toolong_string_here" in results
    assert "AB" not in results  # too short


def test_extract_unicode_strings(tmp_path):
    # UTF-16LE encoded string
    text = "hello\x00w\x00o\x00r\x00l\x00d\x00"
    data = text.encode("utf-16-le")
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    results = extract_strings(str(f), min_len=4, encoding="unicode")
    assert any("hello" in r for r in results)
