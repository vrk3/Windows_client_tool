import datetime
import json
import subprocess
from dataclasses import dataclass
from typing import List

CREATE_NO_WINDOW = 0x08000000

_PS_CMD = r"""
$drivers = Get-CimInstance -ClassName Win32_PnPSignedDriver |
    Where-Object { $_.DeviceName -ne $null -and $_.DeviceName -ne '' }
$result = foreach ($d in $drivers) {
    $dateStr = ''
    if ($d.DriverDate -and $d.DriverDate.Length -ge 8) {
        $dateStr = $d.DriverDate.Substring(0,8)
    }
    [PSCustomObject]@{
        Name       = [string]$d.DeviceName
        Class      = [string]$d.DeviceClass
        Version    = [string]$d.DriverVersion
        Date       = $dateStr
        Publisher  = [string]$d.Manufacturer
        IsSigned   = [bool]$d.IsSigned
        ErrorCode  = [int]($d.ConfigManagerErrorCode -as [int])
    }
}
$result | ConvertTo-Json -Compress -Depth 2
"""


@dataclass
class DriverInfo:
    device_name: str
    driver_class: str
    version: str
    date: str          # "YYYY-MM-DD" or ""
    publisher: str
    signed: bool
    error_code: int    # 0 = OK
    flags: str         # status flags string


def fetch_drivers() -> List[DriverInfo]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_CMD],
        capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW, timeout=90,
    )
    raw = proc.stdout.strip()
    if not raw:
        return []

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
    drivers: List[DriverInfo] = []

    for d in data:
        name = d.get("Name") or ""
        if not name:
            continue
        cls = d.get("Class") or ""
        version = d.get("Version") or ""
        raw_date = d.get("Date") or ""
        publisher = d.get("Publisher") or ""
        signed = bool(d.get("IsSigned", True))
        try:
            error_code = int(d.get("ErrorCode") or 0)
        except (ValueError, TypeError):
            error_code = 0

        date_str = ""
        date_obj = None
        if raw_date and len(raw_date) >= 8:
            try:
                date_obj = datetime.datetime.strptime(raw_date[:8], "%Y%m%d")
                date_str = date_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass

        flags = []
        if not signed:
            flags.append("🔴 Unsigned")
        if error_code != 0:
            flags.append(f"🔴 Error({error_code})")
        if date_obj and date_obj < two_years_ago:
            flags.append("🟠 Old")

        drivers.append(DriverInfo(
            device_name=name, driver_class=cls, version=version,
            date=date_str, publisher=publisher, signed=signed,
            error_code=error_code, flags=" ".join(flags),
        ))

    drivers.sort(key=lambda d: (d.error_code != 0, not d.signed, d.device_name))
    return drivers
