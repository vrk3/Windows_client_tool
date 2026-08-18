"""NTFS volume geometry via FSCTL_GET_NTFS_VOLUME_DATA."""
import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064
FILE_BEGIN = 0

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
_kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]

# Declared explicitly because an undeclared HANDLE argument is marshalled by
# ctypes as a C int on 64-bit Windows, which truncates a pointer-sized handle.
# The distance argument must be a genuine 64-bit value: volumes are far larger
# than 2 GB, and the MFT commonly sits well past that boundary.
_kernel32.SetFilePointerEx.restype = wintypes.BOOL
_kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                       ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class VolumeInfo:
    bytes_per_sector: int
    bytes_per_cluster: int
    bytes_per_record: int
    mft_start_lcn: int
    mft_valid_length: int
    total_clusters: int

    @property
    def mft_offset(self) -> int:
        return self.mft_start_lcn * self.bytes_per_cluster


def parse_volume_data(buf: bytes) -> VolumeInfo:
    """Unpack NTFS_VOLUME_DATA_BUFFER.

    Field offsets, in order: VolumeSerialNumber 0x00, NumberSectors 0x08,
    TotalClusters 0x10, FreeClusters 0x18, TotalReserved 0x20,
    BytesPerSector 0x28, BytesPerCluster 0x2C, BytesPerFileRecordSegment 0x30,
    ClustersPerFileRecordSegment 0x34, MftValidDataLength 0x38,
    MftStartLcn 0x40.
    """
    total_clusters = struct.unpack_from("<Q", buf, 0x10)[0]
    bps, bpc, bpr = struct.unpack_from("<III", buf, 0x28)
    mft_valid_length = struct.unpack_from("<Q", buf, 0x38)[0]
    mft_start_lcn = struct.unpack_from("<Q", buf, 0x40)[0]
    return VolumeInfo(bps, bpc, bpr, mft_start_lcn, mft_valid_length, total_clusters)


def open_volume(letter: str) -> int:
    """Open \\\\.\\<letter>: for raw read. Returns 0 on failure."""
    handle = _kernel32.CreateFileW(
        f"\\\\.\\{letter.rstrip(':')}:", GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return 0
    return handle


def get_volume_info(letter: str) -> VolumeInfo | None:
    """Volume geometry, or None when the raw volume cannot be read.

    Failure is expected and not an error: an unelevated process, a non-NTFS
    volume, or a network path all land here and select the walk scanner.
    """
    handle = open_volume(letter)
    if not handle:
        return None
    try:
        buf = ctypes.create_string_buffer(0x60)
        returned = wintypes.DWORD(0)
        ok = _kernel32.DeviceIoControl(handle, FSCTL_GET_NTFS_VOLUME_DATA, None, 0,
                                       buf, ctypes.sizeof(buf),
                                       ctypes.byref(returned), None)
        if not ok:
            return None
        return parse_volume_data(buf.raw)
    finally:
        _kernel32.CloseHandle(handle)


def read_at(handle: int, offset: int, length: int) -> bytes:
    """Read `length` bytes starting at absolute byte `offset` from a raw volume handle.

    Uses SetFilePointerEx with a genuine 64-bit offset: volumes are far larger
    than 2 GB, and the MFT commonly sits well past that boundary. Returns b"" on
    failure rather than raising, so callers can treat an unreadable region the
    same way they treat an unopenable volume.
    """
    ok = _kernel32.SetFilePointerEx(handle, ctypes.c_longlong(offset), None, FILE_BEGIN)
    if not ok:
        return b""
    buf = ctypes.create_string_buffer(length)
    read = wintypes.DWORD(0)
    ok = _kernel32.ReadFile(handle, buf, length, ctypes.byref(read), None)
    if not ok:
        return b""
    return buf.raw[:read.value]
