r"""Collapsing lines that say the same thing about different objects.

A real CBS archive holds 138,683 records and a few hundred distinct
sentences. Every fixture below is a real line shape from this machine.

The tuning target is stated because it is the only way to know the rules are
right: 125,012 CBS records should fall to a few HUNDRED normalised forms. A
few thousand means the rules are too timid; a few dozen means they have eaten
the distinctions that matter.
"""

from modules.log_viewer.clustering import normalise


def test_a_guid_is_replaced():
    assert normalise(
        "WU creates the package, UpdateID:{33D6CF13-224E-459B-AD4F-"
        "AF8C5E3CC469}, revision: 202"
    ) == normalise(
        "WU creates the package, UpdateID:{11111111-2222-3333-4444-"
        "555555555555}, revision: 7")


def test_a_package_token_is_replaced():
    assert normalise(
        "Appl: Evaluating package applicability for package "
        "HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~10.0.26100.1"
    ) == normalise(
        "Appl: Evaluating package applicability for package "
        "Microsoft-Windows-MediaPlayer-Package~31bf3856ad364e35~amd64~~9.9.9")


def test_a_long_hex_address_is_replaced():
    assert normalise("Perf: LRU Cache Initialize @0x1a044547900") == \
        normalise("Perf: LRU Cache Initialize @0x2b155658a11")


def test_a_plain_number_is_replaced():
    assert normalise("Direct SIL provider: Number of files opened: 155209.") \
        == normalise("Direct SIL provider: Number of files opened: 42.")


def test_two_genuinely_different_lines_do_not_collapse():
    assert normalise("CbsCoreFinalize: DrupUnload") != \
        normalise("CbsCoreFinalize: SrUnload")


def test_an_error_code_still_separates_two_lines():
    """The code IS the distinction. Normalising it away would merge every
    failure into one row and lose the reason."""
    assert normalise("failed [HRESULT = 0x800f0805]") != \
        normalise("failed [HRESULT = 0x80073701]")


def test_normalising_never_returns_an_empty_string():
    """A line that is nothing but a number would otherwise vanish into a
    blank row at the top of the panel."""
    assert normalise("155209").strip()
    assert normalise("{33D6CF13-224E-459B-AD4F-AF8C5E3CC469}").strip()


def test_an_empty_message_stays_empty():
    assert normalise("") == ""


def test_normalising_is_stable():
    line = "Appl: detectParent: parent found: X~31bf3856ad364e35~amd64~~1.0"
    assert normalise(line) == normalise(line)


def test_a_session_id_is_replaced():
    assert normalise("Session: 31275276_4079573531 initialized by client A") \
        == normalise("Session: 31275275_2216988162 initialized by client A")


# ---- plugged into the Summary panel -------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

VARIED = "".join(
    '<![LOG[Appl: detectParent: parent found: Pkg{n}~31bf3856ad364e35~amd64'
    '~~10.0.{n}.1, state: Staged]LOG]!><time="13:45:1{n}.000+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'.format(n=n) for n in range(5))


def test_the_repeated_lines_column_groups_near_identical_records(qapp,
                                                                 tmp_path):
    """Verbatim, these five lines are five different sentences and the
    column says "1" five times, which is true and useless. Normalised they
    are one sentence said five times, which is the answer."""
    path = tmp_path / "cbs.log"
    path.write_text(VARIED, encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.summary_button.setChecked(True)
        rows = [widget.summary_messages.item(i).text()
                for i in range(widget.summary_messages.count())]
        assert len(rows) == 1, "the five lines did not collapse into one"
        assert rows[0].startswith("5")
    finally:
        widget.stop()
