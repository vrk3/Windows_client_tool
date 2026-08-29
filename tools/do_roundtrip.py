r"""Does "Disable Delivery Optimization" actually work now?

    .venv\Scripts\python.exe tools\do_roundtrip.py          (elevated)

It failed for everyone until now: the step was ChangeServiceConfig on DoSvc,
which Windows refuses even to an elevated administrator. It is a policy write
now, so this applies it FOR REAL, reads the registry back directly, reverts,
and reads again -- the same round-trip the LLMNR security control gets, and
for the same reason: nothing here is believed because a writer said "success".

It leaves the machine exactly as it found it.
"""
import os
import sys
import time
import winreg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from core.backup_service import BackupService          # noqa: E402
from modules.tweaks.tweak_engine import TweakEngine    # noqa: E402

KEY = r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization"
ABSENT = "<absent>"


def read(value_name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY) as k:
            return winreg.QueryValueEx(k, value_name)[0]
    except FileNotFoundError:
        return ABSENT
    except OSError as exc:
        return f"<refused: {exc}>"


def show(label: str) -> None:
    print(f"   {label:<22} DODownloadMode={read('DODownloadMode')!r}  "
          f"DOPerMachineMode={read('DOPerMachineMode')!r}")


def main() -> int:
    import ctypes
    print("elevated:", bool(ctypes.windll.shell32.IsUserAnAdmin()))

    data_dir = os.path.join(os.environ["APPDATA"], "WindowsTweaker")
    backup = BackupService(data_dir=data_dir)
    engine = TweakEngine(backup_service=backup)

    tweaks = TweakEngine.load_definitions(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "modules", "tweaks", "definitions", "services.json"))
    tweak = next(t for t in tweaks if t["id"] == "disable_delivery_optimization")

    print(f"\n{tweak['name']}")
    print("   reader says            :", engine.detect(tweak).status)
    show("before")

    errors = []
    rp_id = backup.create_restore_point("DO round-trip", "Tweaks")
    ok = engine.apply_tweak(tweak, rp_id, on_error=errors.append)
    print(f"\n   applying -> {ok}"
          + (f"   errors: {errors}" if errors else ""))
    show("after apply")
    print("   reader says            :", engine.detect(tweak).status)

    # Does anything put it back? The AppX package in this project did, ten
    # seconds later, and the before/after snapshot could not see it.
    time.sleep(12)
    show("12s later")

    print("\n   reverting")
    outcome = backup.restore_point(rp_id)
    print(f"   revert success={outcome.success} partial={outcome.partial} "
          f"errors={outcome.errors}")
    show("after revert")
    print("   reader says            :", engine.detect(tweak).status)
    backup.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
