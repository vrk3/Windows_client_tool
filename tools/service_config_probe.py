r"""Can an elevated Administrator actually change these services' start type?

    .venv\Scripts\python.exe tools\service_config_probe.py

WRITES NOTHING. Every ChangeServiceConfig call below passes SERVICE_NO_CHANGE
for every field, which asks Windows the permission question and alters no
setting -- the same trick as reading `show rule` before `set rule`.

Why: on 2026-08-29 15:16, in a session that was definitely elevated (it had
started Services, Firewall Rules, System Restore and Disk Health, all
admin-gated), the tweak "Disable Delivery Optimization" failed with

    Step failed (service DoSvc): (5, 'ChangeServiceConfig', 'Access is denied.')

and DoSvc's start type is still 2 (Automatic), so it did not take. That is
odd, because `sc sdshow DoSvc` grants Builtin Administrators DC
(SERVICE_CHANGE_CONFIG):

    D:(A;;CCLCSWRPLORC;;;AU)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)...

Run elevated (through the .ps1 wrapper) and unelevated, and compare.
"""
import sys

#: Every service any tweak in services.json changes, plus DoSvc.
SERVICES = [
    "DoSvc", "RemoteRegistry", "DiagTrack", "SysMain", "WSearch",
    "Fax", "MapsBroker", "RetailDemo", "WMPNetworkSvc", "lfsvc",
]

START_TYPES = {0: "boot", 1: "system", 2: "auto", 3: "manual", 4: "disabled"}


def main() -> int:
    import ctypes
    import win32service

    elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"elevated: {elevated}\n")

    hscm = win32service.OpenSCManager(None, None,
                                      win32service.SC_MANAGER_CONNECT)
    try:
        for name in SERVICES:
            handle = None
            try:
                handle = win32service.OpenService(
                    hscm, name,
                    win32service.SERVICE_QUERY_CONFIG
                    | win32service.SERVICE_CHANGE_CONFIG)
            except Exception as exc:
                print(f"   {name:<16} OpenService refused: {exc}")
                continue

            try:
                config = win32service.QueryServiceConfig(handle)
                current = START_TYPES.get(config[1], config[1])
                # Every field SERVICE_NO_CHANGE: asks "may I?", changes nothing.
                win32service.ChangeServiceConfig(
                    handle,
                    win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_NO_CHANGE,
                    None, None, False, None, None, None, None)
                print(f"   {name:<16} start={current:<9} "
                      f"ChangeServiceConfig ALLOWED")
            except Exception as exc:
                print(f"   {name:<16} start={current:<9} "
                      f"ChangeServiceConfig REFUSED: {exc}")
            finally:
                win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(hscm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
