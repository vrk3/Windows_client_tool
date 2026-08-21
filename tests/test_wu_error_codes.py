from core import wu_error_codes
from core.wu_error_codes import decode_wu_error


def test_decode_success():
    assert decode_wu_error(0) == "success"


def test_decode_known_wu_code():
    result = decode_wu_error(0x80240017)
    assert "0x80240017" in result
    assert "WU_E_NOT_APPLICABLE" in result


def test_decode_known_wu_code_from_negative_hresult():
    # PowerShell/COM sometimes surfaces these as negative signed ints —
    # 0x80240017 as a signed 32-bit int is -2145124329.
    result = decode_wu_error(-2145124329)
    assert "0x80240017" in result


def test_decode_win32_facility_falls_back_to_system_message():
    # 0x80070005 (E_ACCESSDENIED) is in our explicit map already, but the
    # facility-fallback path is exercised by any 0x8007xxxx code not in the map.
    result = decode_wu_error(0x80070002)  # ERROR_FILE_NOT_FOUND-ish facility
    assert result.startswith("0x80070002")


def test_decode_unknown_wu_facility_code():
    result = decode_wu_error(0x80241234)
    assert result.startswith("0x80241234")
    assert "unknown" in result.lower()


def test_decode_unrecognized_code_returns_hex_only():
    result = decode_wu_error(0x12345678)
    assert result == "0x12345678"


def test_decode_non_numeric_returns_empty_string():
    assert decode_wu_error("not-a-number") == ""


def test_decode_none_returns_empty_string():
    assert decode_wu_error(None) == ""


class TestHresultFromComError:
    """A pywintypes.com_error carries the code that matters two levels down.

    The user's log showed this, in full:

        Failed to query Windows Updates: (-2147352567, 'Exception occurred.',
        (0, None, None, None, 0, -2145124322), None)

    -2147352567 is DISPATCH_E_EXCEPTION, which says only "the callee raised".
    The code worth reading is the scode at the end of the excepinfo tuple:
    -2145124322 is 0x8024001E, and WU_ERROR_MAP has known what that means
    all along.
    """

    def test_the_scode_wins_over_dispatch_e_exception(self):
        exc = _com_error(-2147352567, "Exception occurred.",
                         (0, None, None, None, 0, -2145124322), None)
        assert wu_error_codes.hresult_from_com_error(exc) == -2145124322

    def test_a_plain_hresult_is_used_when_there_is_no_excepinfo(self):
        exc = _com_error(-2147024891, "Access is denied.", None, None)
        assert wu_error_codes.hresult_from_com_error(exc) == -2147024891

    def test_a_non_com_exception_has_no_hresult(self):
        assert wu_error_codes.hresult_from_com_error(OSError("nope")) is None

    def test_the_users_error_decodes_to_a_sentence(self):
        exc = _com_error(-2147352567, "Exception occurred.",
                         (0, None, None, None, 0, -2145124322), None)
        text = wu_error_codes.decode_wu_error(wu_error_codes.hresult_from_com_error(exc))
        assert "0x8024001E" in text
        assert "shutting down" in text


def _com_error(*args):
    import pywintypes
    return pywintypes.com_error(*args)
