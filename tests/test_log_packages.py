r"""Which package or update a line is about.

Built against real CBS lines, and the shape of the real data decided the
design. In `CbsPersist_20260831055247.log` only 124 of 138,683 records mention
a KB at all, while package tokens like
`HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~10.0.26100.1` appear on tens
of thousands. A KB-only column would be empty 99.9% of the time.

So the column answers the question someone actually has -- "which thing is
this line about" -- returning the KB when the package name embeds one, and the
package identity otherwise.
"""
import pytest

from modules.log_viewer.packages import package_of

# Verbatim from this machine's CBS archive.
KB_LINE = ("Appl: detect Parent, Package: "
           "Package_4_for_KB5044030~31bf3856ad364e35~amd64~~10.0.9277.2, "
           "Parent: Microsoft-Windows-NetFx3-OnDemand-Package~31bf3856ad364e35")
COMPONENT_LINE = ("Appl: Evaluating package applicability for package "
                  "HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~"
                  "10.0.26100.1, applicable state: Installed")


def test_a_kb_package_yields_the_kb():
    """The KB is what someone hunting an update knows the thing by."""
    assert package_of(KB_LINE) == "KB5044030"


def test_a_component_package_yields_its_name():
    assert package_of(COMPONENT_LINE) == "HyperV-KMCL-Host-Package"


def test_the_first_package_on_the_line_wins():
    """The KB line above names a Parent package too. The subject of the line
    is the first one; the parent is context."""
    assert package_of(KB_LINE) == "KB5044030"


def test_a_line_with_no_package_yields_nothing():
    assert package_of("CbsCoreFinalize: DrupUnload") == ""
    assert package_of("") == ""


def test_a_guid_is_not_mistaken_for_a_package():
    """CBS lines carry UpdateIDs. They are not packages and must not fill
    the column with noise."""
    assert package_of(
        "WU creates the package, UpdateID:"
        "{33D6CF13-224E-459B-AD4F-AF8C5E3CC469}, revision: 202") == ""


def test_a_hex_code_is_not_mistaken_for_a_package():
    assert package_of("failed [HRESULT = 0x800f0805]") == ""


def test_a_bare_word_ending_in_package_is_not_enough():
    """The publisher key is what makes it a package identity. Without it,
    every sentence containing the word would match."""
    assert package_of("Planning child capability as a package") == ""


def test_the_kb_is_found_whatever_the_package_index():
    assert package_of("Package: Package_11_for_KB5044030~31bf3856ad364e35~"
                      "amd64~~10.0.1.0") == "KB5044030"


def test_a_lowercase_kb_still_reads_as_one():
    assert package_of("Package: package_1_for_kb5044030~31bf3856ad364e35~"
                      "amd64~~1.0") == "KB5044030"


def test_a_message_that_is_only_a_package_still_works():
    assert package_of("HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~1.0") \
        == "HyperV-KMCL-Host-Package"


# ---- the column ---------------------------------------------------------

from modules.log_viewer.log_model import PACKAGE  # noqa: E402
from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

PACKAGED = (
    '<![LOG[Appl: Evaluating package HyperV-KMCL-Host-Package~'
    '31bf3856ad364e35~amd64~~10.0.26100.1]LOG]!><time="13:45:12.000+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'
)
PLAIN = (
    '<![LOG[CbsCoreFinalize: DrupUnload]LOG]!><time="13:45:12.000+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'
)


def _open(qapp, tmp_path, text, name="cbs.log"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    return widget


def test_the_column_shows_the_package(qapp, tmp_path):
    widget = _open(qapp, tmp_path, PACKAGED)
    try:
        assert widget.model.data(widget.model.index(0, PACKAGE)) == \
            "HyperV-KMCL-Host-Package"
    finally:
        widget.stop()


def test_the_column_is_shown_when_the_log_names_packages(qapp, tmp_path):
    widget = _open(qapp, tmp_path, PACKAGED)
    try:
        assert not widget.table.isColumnHidden(PACKAGE)
    finally:
        widget.stop()


def test_the_column_is_hidden_when_it_would_be_all_blanks(qapp, tmp_path):
    widget = _open(qapp, tmp_path, PLAIN)
    try:
        assert widget.table.isColumnHidden(PACKAGE)
    finally:
        widget.stop()


def test_opening_a_packageless_log_hides_the_column_again(qapp, tmp_path):
    """The stale-state shape: the column must not stay visible from the
    previous log."""
    widget = _open(qapp, tmp_path, PACKAGED)
    try:
        assert not widget.table.isColumnHidden(PACKAGE)
        other = tmp_path / "plain.log"
        other.write_text(PLAIN, encoding="utf-8")
        widget.open(str(other))
        assert widget.table.isColumnHidden(PACKAGE)
    finally:
        widget.stop()


def test_the_text_filter_already_finds_a_package(qapp, tmp_path):
    """No new filter axis is needed: the Filter box matches the whole row,
    so typing a KB or a package name already narrows to it."""
    widget = _open(qapp, tmp_path, PACKAGED + PLAIN)
    try:
        widget.filter_box.setText("HyperV-KMCL")
        assert widget.model.rowCount() == 1
    finally:
        widget.stop()


def test_the_package_column_is_not_allowed_to_dominate(qapp, tmp_path):
    r"""Found by rendering the real archive.

    ResizeToContents sizes to the widest value in the WHOLE model, and
    servicing package names run to 62 characters
    (`Microsoft-Windows-TerminalServices-AppServer-Client-FOD-Package`). That
    gave a 470px column which was empty on every visible row while shoving
    Message off to the right. Sized to content, then capped.
    """
    from modules.log_viewer.log_viewer_module import PACKAGE_MAX_WIDTH

    long_name = ("Microsoft-Windows-TerminalServices-AppServer-Client-FOD-"
                 "Package~31bf3856ad364e35~amd64~~10.0.1.0")
    widget = _open(qapp, tmp_path,
                   '<![LOG[Appl: {name}]LOG]!><time="13:45:12.000+000" '
                   'date="08-20-2026" component="CBS" context="" type="1" '
                   'thread="1" file="a.cpp:1">\n'.format(name=long_name))
    try:
        width = widget.table.horizontalHeader().sectionSize(PACKAGE)
        assert 0 < width <= PACKAGE_MAX_WIDTH
    finally:
        widget.stop()
