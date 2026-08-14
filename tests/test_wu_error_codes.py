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
