"""Error-code lookup — CMTrace's Error Lookup.

A wrong explanation is worse than none: it sends someone after a problem they
do not have. So the rule throughout is that anything not reliably known
returns "" rather than a guess.
"""
import pytest

from modules.log_viewer import error_codes


# ---- finding codes in a line -------------------------------------------

def test_a_code_is_found_in_a_line_of_prose():
    line = "Failed to download content id 42 (0x80070005), retrying"
    assert error_codes.find_codes(line) == [0x80070005]


def test_several_codes_come_back_in_order():
    codes = error_codes.find_codes("first 0x80070002 then 0x80070005")
    assert codes == [0x80070002, 0x80070005]


def test_the_same_code_twice_is_reported_once():
    assert error_codes.find_codes("0x80070005 ... 0x80070005") == [0x80070005]


def test_lowercase_hex_is_found():
    assert error_codes.find_codes("0x8007000e") == [0x8007000E]


def test_a_bare_number_is_not_treated_as_a_code():
    """"content id 12345" is not an error code, and flagging it would turn
    the feature into noise."""
    assert error_codes.find_codes("content id 12345 completed") == []


def test_a_line_with_no_codes_yields_none():
    assert error_codes.find_codes("Policy evaluation initiated") == []


def test_empty_and_none_are_safe():
    assert error_codes.find_codes("") == []
    assert error_codes.find_codes(None) == []


# ---- decoding -----------------------------------------------------------

def test_windows_decodes_the_whole_win32_facility():
    """The low word of an 0x8007xxxx HRESULT is a Win32 error, and Windows
    has a real sentence for every one -- far more than any table here."""
    assert "denied" in error_codes.describe(0x80070005).lower()
    assert "another process" in error_codes.describe(0x80070020).lower()
    assert "corrupt" in error_codes.describe(0x80070570).lower()


def test_a_configmgr_code_is_decoded_although_windows_cannot():
    """0x87D00231 is the one an SCCM log is actually full of."""
    assert "distribution point" in error_codes.describe(0x87D00231).lower()


def test_an_unknown_code_says_nothing_rather_than_guessing():
    assert error_codes.describe(0x12345678) == ""


def test_success_is_reported_as_success():
    assert error_codes.describe(0x00000000) == "success"


# ---- explaining a whole line -------------------------------------------

def test_explain_pairs_the_code_with_its_meaning():
    found = error_codes.explain("download failed (0x80070005)")
    assert len(found) == 1
    code, meaning = found[0]
    assert code == "0x80070005"
    assert "denied" in meaning.lower()


def test_explain_skips_codes_it_cannot_describe():
    """A line mentioning an unknown code should not produce a blank row."""
    found = error_codes.explain("odd code 0x12345678 here")
    assert found == []


def test_explain_normalises_the_code_to_eight_digits():
    """0x5 and 0x00000005 are the same error; showing them differently makes
    them look like two."""
    found = error_codes.explain("failed 0x8007000E")
    assert found[0][0] == "0x8007000E"


# ---- the tooltip form ---------------------------------------------------

def test_annotate_appends_the_meaning_below_the_line():
    text = "Failed (0x80070005)"
    out = error_codes.annotate(text)
    assert out.startswith(text)
    assert "0x80070005" in out
    assert "denied" in out.lower()


def test_annotate_leaves_a_line_without_codes_completely_alone():
    """No trailing blank lines on the tooltip of an ordinary message."""
    assert error_codes.annotate("nothing to see") == "nothing to see"


def test_annotate_handles_several_codes():
    out = error_codes.annotate("0x80070005 and 0x80070020")
    assert out.count("—") == 2


# ---- signal, not noise --------------------------------------------------

def test_explain_ignores_success_codes():
    """Measured on a real 85,850-line CBS.log: 4,553 lines carry a hex code
    and 4,427 of them carry nothing but 0x00000000. Reporting those would put
    "success" on screen four thousand times to surface the nine lines that
    actually failed."""
    assert error_codes.explain("Completed [HRESULT = 0x00000000]") == []


def test_explain_still_reports_a_failure_beside_a_success():
    found = error_codes.explain("first 0x00000000 then 0x80070005")
    assert [c for c, _m in found] == ["0x80070005"]


def test_describe_still_answers_for_success():
    """explain() filters; describe() is the full lookup and must not."""
    assert error_codes.describe(0) == "success"


def test_a_failure_is_the_sign_bit_not_merely_non_zero():
    assert error_codes._is_failure(0x80070005) is True
    assert error_codes._is_failure(0x00000000) is False
    assert error_codes._is_failure(0x00270008) is False
