import datetime
from dataclasses import dataclass
from typing import List


@dataclass
class DriverInfo:
    device_name: str
    driver_class: str
    version: str
    date: str          # "YYYY-MM-DD" or ""
    publisher: str
    signed: bool
    error_code: int    # 0 = OK
    flags: str         # emoji flags string


def fetch_drivers() -> List[DriverInfo]:
    import wmi
    c = wmi.WMI()
    drivers = []
    two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
    for drv in c.Win32_PnPSignedDriver():
        try:
            name = drv.DeviceName or ""
            cls = drv.DeviceClass or ""
            version = drv.DriverVersion or ""
            publisher = drv.Manufacturer or ""
            signed = bool(drv.IsSigned)
            # Parse date: WMI returns "20230101000000.000000+000" format
            date_str = ""
            date_obj = None
            raw_date = drv.DriverDate or ""
            if raw_date and len(raw_date) >= 8:
                try:
                    date_obj = datetime.datetime.strptime(raw_date[:8], "%Y%m%d")
                    date_str = date_obj.strftime("%Y-%m-%d")
                except ValueError:
                    pass
            # Error code
            try:
                error_code = int(drv.ConfigManagerErrorCode or 0)
            except (ValueError, TypeError):
                error_code = 0
            # Flags
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
                error_code=error_code, flags=" ".join(flags)
            ))
        except Exception:
            continue
    drivers.sort(key=lambda d: (d.error_code != 0, not d.signed, d.device_name))
    return drivers
