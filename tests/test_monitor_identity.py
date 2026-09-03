r"""Naming a monitor: `DisplayConfigGetDeviceInfo`, against this machine.

`display_config` answers *what* is on the desktop; nothing in it can say
which of three 2560x1440 rows is the Dell. That is this module's job, and
the one thing that will silently ruin it is the EDID manufacturer id:

* **`edidManufactureId` arrives byte-swapped.** The raw USHORT for the Dell
  here is `0xAC10`; decoding that five-bits-per-letter gives `K@P`. Swapped
  to `0x10AC` it decodes to `DEL`, which is Dell's real PNP id. `K@P` is not
  an error, it is three printable characters -- nothing downstream can tell
  it is wrong, so it is pinned here for all three panels on this machine.

The other rules are this project's standing ones, applied to an API that
breaks both of them cheerfully: a non-zero return is a refusal and must not
surface as a blank name, and `rc == 0` with a zeroed buffer is not an answer
either.
"""
import pytest

from modules.monitor_control import display_config as dc
from modules.monitor_control import monitor_identity as mi


# -- the byte swap, which is the whole trap ----------------------------
#
# (raw USHORT as Windows returns it, the swapped value, the PNP id it is)
EDID_IDS = [
    (0xAC10, 0x10AC, "DEL"),   # Dell       -- S2719DGF, target 256
    (0x541C, 0x1C54, "GBT"),   # Gigabyte   -- MO27Q28G, target 264
    (0x6D1E, 0x1E6D, "GSM"),   # LG Electr. -- LG ULTRAWIDE, target 265
]


@pytest.mark.parametrize("raw,swapped,_name", EDID_IDS)
def test_the_raw_id_is_byte_swapped(raw, swapped, _name):
    assert mi.byte_swap16(raw) == swapped


@pytest.mark.parametrize("_raw,swapped,name", EDID_IDS)
def test_the_swapped_id_decodes_to_the_pnp_id(_raw, swapped, name):
    assert mi.decode_manufacturer_id(swapped) == name


@pytest.mark.parametrize("raw,_swapped,name", EDID_IDS)
def test_manufacturer_from_edid_swaps_then_decodes(raw, _swapped, name):
    assert mi.manufacturer_from_edid(raw) == name


@pytest.mark.parametrize("raw,_swapped,name", EDID_IDS)
def test_decoding_without_the_swap_is_plausible_garbage(raw, _swapped, name):
    """Not an exception -- three printable characters that are simply wrong."""
    wrong = mi.decode_manufacturer_id(raw)
    assert wrong != name
    assert len(wrong) == 3


def test_the_dell_id_decoded_unswapped_is_exactly_the_garbage_seen():
    assert mi.decode_manufacturer_id(0xAC10) == "K@P"


def test_five_bits_per_letter_with_a_equal_to_one():
    #  A=1, B=2, C=3  ->  (1 << 10) | (2 << 5) | 3
    assert mi.decode_manufacturer_id((1 << 10) | (2 << 5) | 3) == "ABC"


# -- building the record, without touching the API ---------------------

def _built(**over):
    fields = dict(
        target_id=256,
        flags=mi.TARGET_NAME_FLAG_FRIENDLY_NAME_FROM_EDID
              | mi.TARGET_NAME_FLAG_EDID_IDS_VALID,
        output_technology=0x0A,
        edid_manufacture_id=0xAC10,
        edid_product_code_id=0x41A8,
        connector_instance=0,
        friendly_name="S2719DGF",
        device_path=r"\\?\DISPLAY#DEL41A8#5&12345#{guid}",
    )
    fields.update(over)
    return mi.build_target_name(**fields)


def test_a_built_record_carries_the_swapped_manufacturer():
    assert _built().manufacturer_id == "DEL"


def test_the_edid_ids_valid_flag_is_read_from_bit_two():
    assert _built().edid_valid is True
    assert _built(flags=0x1).edid_valid is False


def test_invalid_edid_ids_are_reported_as_unknown_not_as_garbage():
    """Decoding an id the API says is invalid gives a real-looking string."""
    record = _built(flags=0x1)
    assert record.manufacturer_id is None
    assert record.product_code is None


def test_a_valid_product_code_is_an_int():
    assert _built().product_code == 0x41A8


def test_an_empty_friendly_name_falls_back_to_something_usable():
    record = _built(friendly_name="", flags=0x4)
    assert record.friendly_name
    assert record.friendly_name.strip() == record.friendly_name


def test_the_fallback_prefers_the_device_path_over_a_bare_number():
    record = _built(friendly_name="", flags=0x4)
    assert "DEL41A8" in record.friendly_name


def test_with_no_name_and_no_path_the_fallback_still_names_the_target():
    record = mi.build_target_name(
        target_id=265, flags=0, output_technology=0, edid_manufacture_id=0,
        edid_product_code_id=0, connector_instance=0,
        friendly_name="", device_path="")
    assert record.friendly_name
    assert "265" in record.friendly_name


# -- refusals ----------------------------------------------------------

def test_a_non_zero_return_is_a_failure_not_an_empty_name(monkeypatch):
    monkeypatch.setattr(mi, "_device_info", lambda packet: 5)  # ACCESS_DENIED
    assert mi.target_name((0, 0), 256) is None
    assert mi.source_gdi_name((0, 0), 0) is None
    assert mi.adapter_name((0, 0)) is None


def test_rc_zero_with_an_empty_buffer_is_not_an_answer(monkeypatch):
    """The API succeeding is not the same as the API telling us anything."""
    monkeypatch.setattr(mi, "_device_info", lambda packet: 0)
    assert mi.source_gdi_name((0, 0), 0) is None
    assert mi.adapter_name((0, 0)) is None


def test_a_refusal_names_the_error_in_the_log(monkeypatch, caplog):
    monkeypatch.setattr(mi, "_device_info", lambda packet: 5)
    with caplog.at_level("WARNING"):
        mi.target_name((0, 0), 256)
    assert "ERROR_ACCESS_DENIED" in caplog.text


def test_rc_zero_still_returns_a_record_when_the_buffer_has_content(monkeypatch):
    """Guard against the refusal tests passing for the wrong reason."""
    def fake(packet):
        packet.monitorFriendlyDeviceName = "S2719DGF"
        packet.monitorDevicePath = r"\\?\DISPLAY#DEL41A8#5&1#{g}"
        packet.edidManufactureId = 0xAC10
        packet.edidProductCodeId = 0x41A8
        packet.flags = 0x5
        packet.outputTechnology = 0x0A
        return 0

    monkeypatch.setattr(mi, "_device_info", fake)
    record = mi.target_name((0, 0), 256)
    assert record is not None
    assert record.friendly_name == "S2719DGF"
    assert record.manufacturer_id == "DEL"


# -- against the real machine ------------------------------------------

EXPECTED_NAMES = {256: "S2719DGF", 264: "MO27Q28G", 265: "LG ULTRAWIDE"}
EXPECTED_MAKERS = {256: "DEL", 264: "GBT", 265: "GSM"}


def _live_monitors():
    try:
        monitors = dc.query().monitors()
    except OSError as exc:                      # DisplayConfigError included
        pytest.skip(f"QueryDisplayConfig is unavailable here: {exc}")
    if not monitors:
        pytest.skip("no monitors reported by QueryDisplayConfig")
    return {m.target_id: m for m in monitors}


def _live_monitor(target_id):
    monitors = _live_monitors()
    if target_id not in monitors:
        pytest.skip(f"target {target_id} is not attached to this machine")
    return monitors[target_id]


@pytest.mark.parametrize("target_id", sorted(EXPECTED_NAMES))
def test_live_friendly_names(target_id):
    monitor = _live_monitor(target_id)
    record = mi.target_name(monitor.adapter, target_id)
    assert record is not None, "DisplayConfigGetDeviceInfo refused"
    assert record.friendly_name == EXPECTED_NAMES[target_id]


@pytest.mark.parametrize("target_id", sorted(EXPECTED_MAKERS))
def test_live_manufacturer_ids_need_the_swap(target_id):
    monitor = _live_monitor(target_id)
    record = mi.target_name(monitor.adapter, target_id)
    assert record is not None
    assert record.edid_valid is True
    assert record.manufacturer_id == EXPECTED_MAKERS[target_id]


def test_live_every_monitor_has_a_device_path():
    for target_id, monitor in _live_monitors().items():
        record = mi.target_name(monitor.adapter, target_id)
        assert record is not None
        assert record.device_path.startswith("\\\\?\\")


def test_live_the_gdi_bridge_is_not_the_display_number():
    r"""source_id 0 -> \\.\DISPLAY1 and 1 -> \\.\DISPLAY2 here, but that is
    a fact about this machine, not a rule: the id is an index, not a name."""
    try:
        topology = dc.query()
    except OSError as exc:
        pytest.skip(f"QueryDisplayConfig is unavailable here: {exc}")
    seen = {}
    for path in topology.active_paths():
        name = mi.source_gdi_name(path.adapter, path.source_id)
        assert name, f"no GDI name for source {path.source_id}"
        assert name.startswith("\\\\.\\DISPLAY")
        seen[path.source_id] = name
    if 0 in seen:
        assert seen[0] == "\\\\.\\DISPLAY1"
    if 1 in seen:
        assert seen[1] == "\\\\.\\DISPLAY2"
    assert len(set(seen.values())) == len(seen), "two sources, one GDI name"


def test_live_the_adapter_is_named():
    monitors = _live_monitors()
    monitor = next(iter(monitors.values()))
    name = mi.adapter_name(monitor.adapter)
    assert name, "adapter name could not be read"
    assert "\\" in name
