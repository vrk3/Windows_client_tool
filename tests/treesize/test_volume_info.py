import ctypes
import struct
import pytest

from modules.treesize.scan.volume_info import (
    parse_volume_data, get_volume_info, open_volume, read_at,
)


def _buf(bps=512, spc=8, bpr=1024, mft_lcn=786_432, mft_len=268_435_456,
         total_clusters=488_378_646):
    # Layout is NTFS_VOLUME_DATA_BUFFER exactly; getting these offsets wrong
    # is invisible to a test that shares the mistake, so they are spelled out.
    b = bytearray(0x60)
    struct.pack_into("<Q", b, 0x00, 0)                 # VolumeSerialNumber
    struct.pack_into("<Q", b, 0x08, total_clusters * spc)   # NumberSectors
    struct.pack_into("<Q", b, 0x10, total_clusters)    # TotalClusters
    struct.pack_into("<Q", b, 0x18, 0)                 # FreeClusters
    struct.pack_into("<Q", b, 0x20, 0)                 # TotalReserved
    struct.pack_into("<I", b, 0x28, bps)               # BytesPerSector
    struct.pack_into("<I", b, 0x2C, bps * spc)         # BytesPerCluster
    struct.pack_into("<I", b, 0x30, bpr)               # BytesPerFileRecordSegment
    struct.pack_into("<I", b, 0x34, 1)                 # ClustersPerFileRecordSegment
    struct.pack_into("<Q", b, 0x38, mft_len)           # MftValidDataLength
    struct.pack_into("<Q", b, 0x40, mft_lcn)           # MftStartLcn
    struct.pack_into("<Q", b, 0x48, 0)                 # Mft2StartLcn
    return bytes(b)


def test_parses_cluster_geometry():
    v = parse_volume_data(_buf(bps=512, spc=8))
    assert v.bytes_per_sector == 512
    assert v.bytes_per_cluster == 4096
    assert v.bytes_per_record == 1024


def test_parses_mft_location():
    v = parse_volume_data(_buf(mft_lcn=786_432))
    assert v.mft_start_lcn == 786_432


def test_mft_byte_offset_is_lcn_times_cluster_size():
    v = parse_volume_data(_buf(spc=8, mft_lcn=100))
    assert v.mft_offset == 100 * 4096


def test_get_volume_info_returns_none_for_bogus_drive():
    assert get_volume_info("ZZ") is None


@pytest.mark.skipif(
    not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="raw volume access requires elevation",
)
def test_get_volume_info_reads_c_drive_when_elevated():
    v = get_volume_info("C")
    assert v is not None
    assert v.bytes_per_cluster in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
    assert v.bytes_per_record >= 1024


def test_read_at_invalid_handle_returns_empty_bytes():
    assert read_at(0, 0, 512) == b""


@pytest.mark.skipif(
    not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="raw volume access requires elevation",
)
def test_read_at_reads_boot_sector_from_c_drive_when_elevated():
    handle = open_volume("C")
    assert handle != 0
    try:
        data = read_at(handle, 0, 512)
        assert len(data) == 512
        assert data[3:7] == b"NTFS"
    finally:
        from modules.treesize.scan.volume_info import _kernel32
        _kernel32.CloseHandle(handle)
