import subprocess
from typing import Dict, Any


def check_defender() -> Dict[str, Any]:
    """Returns {"enabled": bool, "real_time": bool, "version": str, "status": str, "color": str}"""
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\Microsoft\Windows\Defender")
        status_obj = c.MSFT_MpComputerStatus()[0]
        av_enabled = bool(status_obj.AntivirusEnabled)
        rt_enabled = bool(status_obj.RealTimeProtectionEnabled)
        version = str(status_obj.AMProductVersion or "")
        all_ok = av_enabled and rt_enabled
        return {
            "enabled": av_enabled, "real_time": rt_enabled,
            "version": version,
            "status": "Protected" if all_ok else ("Partial" if av_enabled else "Disabled"),
            "color": "green" if all_ok else ("amber" if av_enabled else "red"),
            "details": [
                ("AV Enabled", str(av_enabled)),
                ("Real-Time Protection", str(rt_enabled)),
                ("Product Version", version),
            ]
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_firewall() -> Dict[str, Any]:
    """Returns {"profiles": dict, "status": str, "color": str}"""
    try:
        import win32com.client
        fw = win32com.client.Dispatch("HNetCfg.FwPolicy2")
        # Profile types: 1=Domain, 2=Private, 4=Public
        profile_names = {1: "Domain", 2: "Private", 4: "Public"}
        enabled = {}
        for profile_type, name in profile_names.items():
            try:
                enabled[name] = bool(fw.FirewallEnabled(profile_type))
            except Exception:
                enabled[name] = False
        all_on = all(enabled.values())
        any_on = any(enabled.values())
        return {
            "profiles": enabled,
            "status": "All On" if all_on else ("Partial" if any_on else "All Off"),
            "color": "green" if all_on else ("amber" if any_on else "red"),
            "details": [(k, "Enabled" if v else "Disabled") for k, v in enabled.items()]
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_bitlocker() -> Dict[str, Any]:
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\cimv2\Security\MicrosoftVolumeEncryption")
        volumes = c.Win32_EncryptableVolume()
        details = []
        c_protected = None
        for vol in volumes:
            ps = int(vol.ProtectionStatus or 0)
            label = {0: "Unprotected", 1: "Protected", 2: "Unknown"}.get(ps, str(ps))
            drive = str(vol.DriveLetter or "?")
            details.append((drive, label))
            if drive.upper().startswith("C"):
                c_protected = (ps == 1)
        if c_protected is True:
            color = "green"
            status = "C: Protected"
        elif c_protected is False:
            color = "red"
            status = "C: Unprotected"
        else:
            color = "amber"
            status = "Unknown"
        return {"status": status, "color": color, "details": details}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_secure_boot_tpm() -> Dict[str, Any]:
    details = []
    # Secure Boot
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Confirm-SecureBootUEFI"],
            capture_output=True, text=True,
            creationflags=0x08000000, timeout=15
        )
        if result.returncode != 0 or "not supported" in (result.stderr or "").lower():
            sb_status = "N/A (BIOS/Legacy)"
            sb_ok = None
        elif result.stdout.strip().lower() == "true":
            sb_status = "Enabled"
            sb_ok = True
        else:
            sb_status = "Disabled"
            sb_ok = False
    except Exception as e:
        sb_status = f"Error: {e}"
        sb_ok = None
    details.append(("Secure Boot", sb_status))

    # TPM
    tpm_ok = False
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\cimv2\Security\MicrosoftTpm")
        tpms = c.Win32_Tpm()
        if tpms:
            tpm = tpms[0]
            tpm_enabled = bool(tpm.IsEnabled_InitialValue)
            details.append(("TPM", "Enabled" if tpm_enabled else "Disabled"))
            tpm_ok = tpm_enabled
        else:
            details.append(("TPM", "Not Found"))
    except Exception as e:
        details.append(("TPM", f"Error: {e}"))

    all_ok = (sb_ok is True) and tpm_ok
    any_ok = (sb_ok is True) or tpm_ok
    return {
        "status": "Secure" if all_ok else ("Partial" if any_ok else "Insecure"),
        "color": "green" if all_ok else ("amber" if any_ok else "red"),
        "details": details,
    }


def get_all_security_status() -> dict:
    return {
        "defender": check_defender(),
        "firewall": check_firewall(),
        "bitlocker": check_bitlocker(),
        "secure_boot_tpm": check_secure_boot_tpm(),
    }
