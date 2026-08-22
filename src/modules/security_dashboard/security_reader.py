"""
Security status data-gathering and action functions.

Check functions return a dict with: status (str), color ("green"|"amber"|"red"),
details (list of (key, value) tuples), and optionally enabled (bool).
Toggle functions return a dict with: success (bool), message (str), and
optionally before_value and after_value for revert tracking.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CREATION_FLAGS = 0x08000000  # CREATE_NO_WINDOW


# ── Helpers ────────────────────────────────────────────────────────────────

def _ps(cmd: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a PowerShell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout,
        creationflags=CREATION_FLAGS,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


NEEDS_ADMIN = "Requires administrator"

#: WBEM_E_ACCESS_DENIED, as a signed HRESULT — what every privileged WMI
#: namespace answers to an ordinary user.
_WBEM_E_ACCESS_DENIED = -2147217405


def _wmi_failure_reason(exc: Exception) -> str:
    """Say what a failed WMI query means, not what its COM tuple looks like.

    `str(x_wmi)` is `<x_wmi: Unexpected COM Error (-2147217405, 'OLE error
    0x80041003', None, None)>`, which tells a user nothing and reads as a
    crash. The wmi package has already classified it — access denied gets its
    own subclass — so the answer is there to be used rather than stringified.
    """
    try:
        import wmi

        if isinstance(exc, wmi.x_access_denied):
            return NEEDS_ADMIN
    except ImportError:
        pass
    com_error = getattr(exc, "com_error", None)
    if getattr(com_error, "hresult", None) == _WBEM_E_ACCESS_DENIED:
        return NEEDS_ADMIN
    return str(exc)


def _secure_boot_from_registry() -> Optional[bool]:
    """Read Secure Boot state without elevation.

    `Confirm-SecureBootUEFI` needs administrator rights, but the value it
    reports is mirrored under `SecureBoot\\State`, which any user can read.
    The key exists only on UEFI firmware, so its absence — and only its
    absence — is what legitimately means "BIOS/Legacy".

    Returns True/False for enabled/disabled, or None when there is no key.
    """
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
        ) as key:
            return bool(winreg.QueryValueEx(key, "UEFISecureBootEnabled")[0])
    except OSError:
        return None


def _reg_read(key: str, value: str, kind: str = "REG_DWORD") -> Optional[Any]:
    """Read a registry value via reg query. Returns None if not found."""
    try:
        result = subprocess.run(
            ["reg", "query", key, "/v", value],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATION_FLAGS,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if value in line and "REG_" in line:
                parts = line.strip().split()
                raw = parts[-1]
                if kind == "REG_DWORD":
                    return int(raw, 16) if raw.startswith("0x") else int(raw)
                return raw
        return None
    except Exception:
        return None


def _reg_write(key: str, value: str, data: Any, kind: str = "REG_DWORD") -> bool:
    """Write a registry value via reg add. Returns True on success."""
    try:
        cmd = ["reg", "add", key, "/v", value, "/t", kind, "/d", str(data), "/f"]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=10,
            creationflags=CREATION_FLAGS,
        )
        return result.returncode == 0
    except Exception:
        return False


def _resolve_mpcmdrun() -> str:
    """Resolve MpCmdRun.exe path using environment variables."""
    prog = os.environ.get("ProgramFiles", r"C:\Program Files")
    return os.path.join(prog, "Windows Defender", "MpCmdRun.exe")


def _cmd_run(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    """Run an arbitrary command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=CREATION_FLAGS,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ── Read-Only Status Checks ────────────────────────────────────────────────

def check_defender() -> Dict[str, Any]:
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
                ("AV Enabled", "Yes" if av_enabled else "No"),
                ("Real-Time Protection", "On" if rt_enabled else "Off"),
                ("Product Version", version),
            ]
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_firewall() -> Dict[str, Any]:
    try:
        import win32com.client
        fw = win32com.client.Dispatch("HNetCfg.FwPolicy2")
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
            "details": [(k, "On" if v else "Off") for k, v in enabled.items()]
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
            return {"status": "C: Protected", "color": "green", "details": details}
        elif c_protected is False:
            return {"status": "C: Unprotected", "color": "red", "details": details}
        return {"status": "Unknown", "color": "amber", "details": details}
    except Exception as e:
        return {"status": _wmi_failure_reason(e), "color": "amber", "details": []}


def check_secure_boot_tpm() -> Dict[str, Any]:
    details = []
    # Secure Boot
    sb_ok = None
    try:
        rc, out, err = _ps("Confirm-SecureBootUEFI", timeout=15)
        if "not supported" in (err or "").lower():
            details.append(("Secure Boot", "N/A (BIOS/Legacy)"))
        elif rc != 0:
            # The cmdlet needs administrator rights ("Unable to set proper
            # privileges. Access was denied."). A refusal to answer is not
            # evidence of legacy firmware — the registry knows, unelevated.
            # Only the cmdlet's own "not supported" (above) is evidence of
            # legacy firmware. Denied here plus no key leaves us genuinely
            # unable to tell, which is what we then say.
            from_registry = _secure_boot_from_registry()
            if from_registry is None:
                details.append(("Secure Boot", f"Unknown — {NEEDS_ADMIN}"))
            else:
                details.append(
                    ("Secure Boot", "Enabled" if from_registry else "Disabled")
                )
                sb_ok = from_registry
        elif out.lower() == "true":
            details.append(("Secure Boot", "Enabled"))
            sb_ok = True
        else:
            details.append(("Secure Boot", "Disabled"))
            sb_ok = False
    except Exception as e:
        details.append(("Secure Boot", f"Error: {e}"))

    # TPM
    tpm_ok: Optional[bool] = None
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\cimv2\Security\MicrosoftTpm")
        tpms = c.Win32_Tpm()
        if tpms:
            tpm = tpms[0]
            tpm_enabled = bool(tpm.IsEnabled_InitialValue)
            details.append(("TPM", "Enabled" if tpm_enabled else "Disabled"))
            tpm_ok = tpm_enabled
            # Try to get spec version
            try:
                spec_ver = str(tpm.SpecVersion or "")
                if spec_ver:
                    details.append(("TPM Version", spec_ver))
            except Exception:
                logger.warning("Ignored Exception reading TPM spec version", exc_info=True)
        else:
            details.append(("TPM", "Not Found"))
            tpm_ok = False
    except Exception as e:
        details.append(("TPM", _wmi_failure_reason(e)))

    # A check that could not run is unknown, not failed. Scoring an
    # access-denied TPM query as "absent" put a red "Insecure" verdict on a
    # machine nobody had actually asked about.
    answered = [ok for ok in (sb_ok, tpm_ok) if ok is not None]
    all_ok = len(answered) == 2 and all(answered)
    any_ok = any(answered)
    unknown = len(answered) < 2

    if all_ok:
        status, color = "Secure", "green"
    elif any_ok:
        status, color = "Partial", "amber"
    elif unknown:
        status, color = "Unknown", "amber"
    else:
        status, color = "Insecure", "red"
    return {"status": status, "color": color, "details": details}


def check_uac() -> Dict[str, Any]:
    key = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    try:
        enable_lua = _reg_read(key, "EnableLUA")
        consent = _reg_read(key, "ConsentPromptBehaviorAdmin")
        secure_desktop = _reg_read(key, "PromptOnSecureDesktop")

        lua_on = enable_lua == 1
        details = [
            ("UAC Enabled", "Yes" if lua_on else "No"),
        ]

        if consent is not None:
            levels = {0: "Never notify (disabled)", 1: "Notify without dimming",
                      2: "Notify and dim desktop", 3: "Notify and dim (default)",
                      4: "Always notify (no auto-elevate)", 5: "Always notify (max)"}
            details.append(("Prompt Level", levels.get(consent, f"Unknown ({consent})")))
        if secure_desktop is not None:
            details.append(("Secure Desktop", "Yes" if secure_desktop == 1 else "No"))

        if lua_on:
            color, status = "green", "Enabled"
        elif lua_on is False:
            color, status = "red", "Disabled"
        else:
            color, status = "amber", "Unknown"
        return {"status": status, "color": color, "details": details, "enabled": lua_on}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_smartscreen() -> Dict[str, Any]:
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System"
    try:
        val = _reg_read(key, "EnableSmartScreen")
        details = []
        if val == 1:
            return {"status": "Enabled", "color": "green", "details": [("SmartScreen", "On")], "enabled": True}
        elif val == 0:
            return {"status": "Disabled", "color": "red", "details": [("SmartScreen", "Off")], "enabled": False}
        # Fallback: check Explorer key
        val2 = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer", "SmartScreenEnabled", "REG_SZ")
        if val2:
            return {"status": val2, "color": "green" if "off" not in str(val2).lower() else "red",
                    "details": [("SmartScreen", val2)], "enabled": "off" not in str(val2).lower()}
        return {"status": "Not Configured", "color": "amber", "details": [("SmartScreen", "Not configured via policy")]}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_hvci() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\\Microsoft\\Windows\\DeviceGuard | "
            "Select-Object VirtualizationBasedSecurityStatus, RequiredSecurityProperties, "
            "AvailableSecurityProperties, SecurityServicesConfigured, SecurityServicesRunning | "
            "ConvertTo-Json -Compress", timeout=20
        )
        if rc != 0 or not out:
            return {"status": "N/A (WMI unavailable)", "color": "amber",
                    "details": [("HVCI / Memory Integrity", "Not available")]}

        data = json.loads(out)
        vbs_status = data.get("VirtualizationBasedSecurityStatus", 0)
        vbs_map = {0: "Disabled", 1: "Enabled but not running", 2: "Enabled and running"}
        vbs_label = vbs_map.get(vbs_status, f"Unknown ({vbs_status})")
        details = [
            ("VBS Status", vbs_label),
        ]

        sec_running = data.get("SecurityServicesRunning", 0)
        if isinstance(sec_running, int):
            hvci_on = bool(sec_running & 2)  # Bit 1 = Hypervisor-enforced Code Integrity
            details.append(("HVCI / Memory Integrity", "On" if hvci_on else "Off"))
        else:
            hvci_on = False

        if vbs_status >= 1 and hvci_on:
            return {"status": "Protected", "color": "green", "details": details}
        elif vbs_status >= 1:
            return {"status": "Partial (VBS on, HVCI off)", "color": "amber", "details": details}
        return {"status": "Disabled", "color": "red", "details": details}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber",
                "details": [("HVCI", "Check failed")]}


def check_credential_guard() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\\Microsoft\\Windows\\DeviceGuard | "
            "Select-Object SecurityServicesConfigured, SecurityServicesRunning | "
            "ConvertTo-Json -Compress", timeout=20
        )
        if rc != 0 or not out:
            return {"status": "N/A", "color": "amber", "details": [("Credential Guard", "WMI unavailable")]}

        data = json.loads(out)
        sec_conf = data.get("SecurityServicesConfigured", 0)
        sec_run = data.get("SecurityServicesRunning", 0)
        cg_configured = bool(int(sec_conf) & 1) if isinstance(sec_conf, int) else False
        cg_running = bool(int(sec_run) & 1) if isinstance(sec_run, int) else False

        if cg_running:
            return {"status": "Running", "color": "green",
                    "details": [("Credential Guard", "Active")]}
        elif cg_configured:
            return {"status": "Configured (needs reboot)", "color": "amber",
                    "details": [("Credential Guard", "Configured, reboot required")]}
        return {"status": "Not Configured", "color": "amber",
                "details": [("Credential Guard", "Off")]}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber",
                "details": [("Credential Guard", "Check failed")]}


def check_lsass_protection() -> Dict[str, Any]:
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa"
    try:
        val = _reg_read(key, "RunAsPPL")
        if val == 1:
            return {"status": "Protected", "color": "green",
                    "details": [("LSASS Protection", "On (RunAsPPL=1)")], "enabled": True}
        elif val == 2:
            return {"status": "Protected (UEFI Lock)", "color": "green",
                    "details": [("LSASS Protection", "On with UEFI lock (RunAsPPL=2)")], "enabled": True}
        elif val == 0:
            return {"status": "Not Protected", "color": "red",
                    "details": [("LSASS Protection", "Off (RunAsPPL=0)")], "enabled": False}
        return {"status": "Not Configured", "color": "amber",
                "details": [("LSASS Protection", "Not set")]}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_tamper_protection() -> Dict[str, Any]:
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\Microsoft\Windows\Defender")
        status_obj = c.MSFT_MpComputerStatus()[0]
        try:
            tamper = bool(status_obj.IsTamperProtected)
        except Exception:
            return {"status": "Unknown (pre-1903?)", "color": "amber",
                    "details": [("Tamper Protection", "Not supported on this build")]}
        if tamper:
            return {"status": "On", "color": "green",
                    "details": [("Tamper Protection", "On")], "enabled": True}
        return {"status": "Off", "color": "red",
                "details": [("Tamper Protection", "Off")], "enabled": False}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_pua_protection() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-MpPreference | Select-Object PUAProtection | ConvertTo-Json -Compress",
            timeout=15
        )
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("PUA Protection", "WMI failed")]}
        data = json.loads(out)
        level = data.get("PUAProtection", 0)
        labels = {0: "Off", 1: "Audit Mode", 2: "On"}
        label = labels.get(level, f"Unknown ({level})")
        enabled = level >= 1
        return {
            "status": label, "color": "green" if level == 2 else ("amber" if level == 1 else "red"),
            "details": [("PUA Protection", label)], "enabled": enabled, "level": level,
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_controlled_folder_access() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-MpPreference | Select-Object EnableControlledFolderAccess | ConvertTo-Json -Compress",
            timeout=15
        )
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Controlled Folder Access", "WMI failed")]}
        data = json.loads(out)
        cfa = data.get("EnableControlledFolderAccess", 0)
        enabled = cfa == 1
        return {
            "status": "On" if enabled else "Off",
            "color": "green" if enabled else "red",
            "details": [("Controlled Folder Access", "On" if enabled else "Off")],
            "enabled": enabled,
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_cloud_protection() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-MpPreference | Select-Object MAPSReporting, SubmitSamplesConsent | ConvertTo-Json -Compress",
            timeout=15
        )
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Cloud Protection", "WMI failed")]}
        data = json.loads(out)
        maps = data.get("MAPSReporting", 0)
        samples = data.get("SubmitSamplesConsent", 0)
        maps_labels = {0: "Off", 1: "Basic", 2: "Advanced"}
        map_label = maps_labels.get(maps, str(maps))
        samp_labels = {0: "Never", 1: "Always prompt", 2: "Auto (safe)", 3: "Auto (all)"}
        samp_label = samp_labels.get(samples, str(samples))
        cloud_on = maps >= 1
        return {
            "status": map_label,
            "color": "green" if maps >= 2 else ("amber" if maps == 1 else "red"),
            "details": [
                ("Cloud Protection", map_label),
                ("Sample Submission", samp_label),
            ],
            "enabled": cloud_on,
            "maps_level": maps,
            "samples_level": samples,
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_defender_signatures() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-MpComputerStatus | Select-Object AntivirusSignatureLastUpdated, "
            "AntivirusSignatureAge, AntivirusEnabled, AntivirusSignatureVersion | "
            "ConvertTo-Json -Compress", timeout=30
        )
        if rc != 0 or not out:
            return {"status": "Unavailable", "color": "amber",
                    "details": [("Signatures", "Could not retrieve")]}
        data = json.loads(out)
        enabled = data.get("AntivirusEnabled", False)
        age_hours = data.get("AntivirusSignatureAge", -1)
        last_updated = str(data.get("AntivirusSignatureLastUpdated", ""))
        version = str(data.get("AntivirusSignatureVersion", "Unknown"))

        if age_hours >= 0:
            if age_hours < 24:
                age_color = "green"
                age_label = "Up to date"
            elif age_hours < 168:
                age_color = "amber"
                age_label = "Outdated"
            else:
                age_color = "red"
                age_label = "Stale"
        else:
            age_color = "amber"
            age_label = "Unknown"

        # Format the ISO timestamp
        if last_updated:
            try:
                from datetime import datetime
                dt = datetime.strptime(last_updated[:19], "%Y-%m-%dT%H:%M:%S")
                last_updated = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                import logging
                _log = logging.getLogger(__name__)
                _log.debug("Could not parse AV signature timestamp '%s'", last_updated, exc_info=True)

        details = [
            ("AV Enabled", "Yes" if enabled else "No"),
            ("Signature Version", version),
            ("Signature Age", f"{age_hours}h" if age_hours >= 0 else "N/A"),
            ("Last Updated", last_updated or "N/A"),
        ]
        return {
            "status": age_label,
            "color": age_color,
            "details": details,
            "age_hours": age_hours,
            "version": version,
            "last_updated": last_updated,
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_rdp() -> Dict[str, Any]:
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server"
    try:
        val = _reg_read(key, "fDenyTSConnections")
        if val == 1:
            return {"status": "Disabled", "color": "green",
                    "details": [("RDP", "Off (deny connections)")], "enabled": False}
        elif val == 0:
            return {"status": "Enabled", "color": "red",
                    "details": [("RDP", "On (allow connections)")], "enabled": True}
        return {"status": "Not Configured", "color": "amber", "details": [("RDP", "Unknown")]}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_smbv1() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol | "
            "Select-Object State | ConvertTo-Json -Compress",
            timeout=20
        )
        if rc != 0 or not out:
            # Fallback: check service
            rc2, out2, _ = _ps("Get-Service -Name LanmanServer -ErrorAction SilentlyContinue | "
                                "Select-Object Name | ConvertTo-Json -Compress", timeout=15)
            if rc2 != 0:
                return {"status": "Unknown", "color": "amber", "details": [("SMBv1", "Could not determine")]}
            return {"status": "Probably Disabled (Win10+)", "color": "green",
                    "details": [("SMBv1", "Likely off")]}
        data = json.loads(out)
        state = data.get("State", 0)
        if isinstance(state, str) and "Enabled" in state:
            return {"status": "Enabled", "color": "red",
                    "details": [("SMBv1", "On (vulnerable to EternalBlue)")], "enabled": True}
        return {"status": "Disabled", "color": "green",
                "details": [("SMBv1", "Off")], "enabled": False}
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


def check_network_protection_defender() -> Dict[str, Any]:
    try:
        rc, out, err = _ps(
            "Get-MpPreference | Select-Object EnableNetworkProtection | ConvertTo-Json -Compress",
            timeout=15
        )
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber",
                    "details": [("Network Protection", "WMI failed")]}
        data = json.loads(out)
        np_val = data.get("EnableNetworkProtection", 0)
        labels = {0: "Off", 1: "On (Block)", 2: "Audit Mode"}
        label = labels.get(np_val, f"Unknown ({np_val})")
        enabled = np_val >= 1
        return {
            "status": label,
            "color": "green" if np_val == 1 else ("amber" if np_val == 2 else "red"),
            "details": [("Network Protection", label)],
            "enabled": enabled,
            "level": np_val,
        }
    except Exception as e:
        return {"status": f"Error: {e}", "color": "amber", "details": []}


# ── Toggle / Write Actions ─────────────────────────────────────────────────

def _set_mp_pref(pref_name: str, value: int, label: str) -> Dict[str, Any]:
    """Set a Defender preference and return result dict."""
    rc, out, err = _ps(
        f"$ErrorActionPreference='Stop'; try {{ Set-MpPreference -{pref_name} {value}; "
        f"Write-Output 'SUCCESS' }} catch {{ Write-Error $_.Exception.Message }}",
        timeout=30
    )
    if rc == 0 and "SUCCESS" in out:
        return {"success": True, "message": f"{label} set successfully"}
    return {"success": False, "message": err or out or "Unknown error setting preference"}


def get_defender_realtime() -> Dict[str, Any]:
    """Get current real-time protection state for toggling."""
    try:
        rc, out, err = _ps(
            "Get-MpPreference | Select-Object DisableRealtimeMonitoring | ConvertTo-Json -Compress",
            timeout=15
        )
        if rc != 0 or not out:
            return {"enabled": None, "error": "Could not query state"}
        data = json.loads(out)
        disabled = data.get("DisableRealtimeMonitoring", False)
        return {"enabled": not disabled, "raw": data}
    except Exception as e:
        return {"enabled": None, "error": str(e)}


def set_defender_realtime(enabled: bool) -> Dict[str, Any]:
    """Enable or disable Defender real-time protection."""
    before = get_defender_realtime()
    before_val = before.get("enabled")
    result = _set_mp_pref("DisableRealtimeMonitoring", 0 if enabled else 1,
                          "Real-time protection")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result


def set_defender_cloud(enabled: bool, map_level: int = 2) -> Dict[str, Any]:
    """Enable or disable cloud-delivered protection (MAPS)."""
    before = check_cloud_protection()
    before_val = before.get("maps_level")
    result = _set_mp_pref("MAPSReporting", map_level if enabled else 0,
                          "Cloud protection")
    # Also set sample submission to auto-safe when enabling cloud
    if enabled:
        _set_mp_pref("SubmitSamplesConsent", 1, "Auto sample submission")
    result["before_value"] = before_val
    result["after_value"] = map_level if enabled else 0
    result["action"] = "enable" if enabled else "disable"
    return result


def set_defender_sample_submission(enabled: bool, level: int = 1) -> Dict[str, Any]:
    """Enable or disable automatic sample submission."""
    before_data = check_cloud_protection()
    before_val = before_data.get("samples_level")
    result = _set_mp_pref("SubmitSamplesConsent", level if enabled else 0,
                          "Sample submission")
    result["before_value"] = before_val
    result["after_value"] = level if enabled else 0
    result["action"] = "enable" if enabled else "disable"
    return result


def set_pua_protection(enabled: bool, level: int = 1) -> Dict[str, Any]:
    """Enable or disable PUA protection."""
    before = check_pua_protection()
    before_val = before.get("level")
    result = _set_mp_pref("PUAProtection", level if enabled else 0,
                          "PUA protection")
    result["before_value"] = before_val
    result["after_value"] = level if enabled else 0
    result["action"] = "enable" if enabled else "disable"
    return result


def set_controlled_folder_access(enabled: bool) -> Dict[str, Any]:
    """Enable or disable Controlled Folder Access."""
    before = check_controlled_folder_access()
    before_val = before.get("enabled")
    result = _set_mp_pref("EnableControlledFolderAccess", 1 if enabled else 0,
                          "Controlled Folder Access")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result


def set_network_protection_defender(enabled: bool, level: int = 1) -> Dict[str, Any]:
    """Enable or disable network protection."""
    before = check_network_protection_defender()
    before_val = before.get("level")
    result = _set_mp_pref("EnableNetworkProtection", level if enabled else 0,
                          "Network protection")
    result["before_value"] = before_val
    result["after_value"] = level if enabled else 0
    result["action"] = "enable" if enabled else "disable"
    return result


def set_tamper_protection(enabled: bool) -> Dict[str, Any]:
    """Enable or disable Tamper Protection."""
    before = check_tamper_protection()
    before_val = before.get("enabled")
    new_val = 0 if enabled else 1  # Inverted: DisableTamperProtection=0 means enabled
    result = _set_mp_pref("DisableTamperProtection", new_val, "Tamper protection")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result


def set_firewall_profile(profile: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a firewall profile (Domain, Private, or Public)."""
    profile_map = {"Domain": "domainprofile", "Private": "privateprofile", "Public": "publicprofile"}
    netsh_profile = profile_map.get(profile, profile.lower() + "profile")
    state = "on" if enabled else "off"
    rc, out, err = _cmd_run(
        ["netsh", "advfirewall", "set", netsh_profile, "state", state],
        timeout=30
    )
    if rc == 0:
        return {"success": True, "message": f"{profile} firewall turned {state}",
                "before_value": not enabled, "after_value": enabled,
                "action": "enable" if enabled else "disable"}
    return {"success": False, "message": err or out or f"Failed to set {profile} firewall"}


def set_smartscreen(enabled: bool) -> Dict[str, Any]:
    """Enable or disable SmartScreen via registry policy."""
    before = check_smartscreen()
    before_val = before.get("enabled")
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System"
    ok = _reg_write(key, "EnableSmartScreen", 1 if enabled else 0, "REG_DWORD")
    if ok:
        return {"success": True, "message": f"SmartScreen {'enabled' if enabled else 'disabled'}",
                "before_value": before_val, "after_value": enabled,
                "action": "enable" if enabled else "disable"}
    return {"success": False, "message": "Failed to write registry key"}


def set_lsass_protection(enabled: bool) -> Dict[str, Any]:
    """Enable or disable LSASS Protected Process Light (requires reboot)."""
    before = check_lsass_protection()
    before_val = before.get("enabled")
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa"
    ok = _reg_write(key, "RunAsPPL", 1 if enabled else 0, "REG_DWORD")
    if ok:
        msg = f"LSASS protection {'enabled' if enabled else 'disabled'} (reboot required)"
        return {"success": True, "message": msg,
                "before_value": before_val, "after_value": enabled,
                "action": "enable" if enabled else "disable",
                "reboot_required": True}
    return {"success": False, "message": "Failed to write LSASS registry key"}


def set_uac_level(enable_lua: bool = True, consent_level: int = 2) -> Dict[str, Any]:
    """Configure UAC level. consent_level: 0=never, 1=no dim, 2=dim, 3=default, 4=always, 5=max."""
    before = check_uac()
    key = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    ok1 = _reg_write(key, "EnableLUA", 1 if enable_lua else 0)
    ok2 = _reg_write(key, "ConsentPromptBehaviorAdmin", consent_level)
    ok3 = _reg_write(key, "PromptOnSecureDesktop", 1)
    success = ok1 and ok2 and ok3
    return {
        "success": success,
        "message": f"UAC {'enabled' if enable_lua else 'disabled'} at level {consent_level}"
        if success else "Failed to configure UAC",
        "before_value": before, "after_value": {"enable_lua": enable_lua, "level": consent_level},
        "action": "configure_uac",
    }


def run_quick_scan() -> Dict[str, Any]:
    """Run a Windows Defender quick scan."""
    mp = _resolve_mpcmdrun()
    rc, out, err = _cmd_run([mp, "-Scan", "-ScanType", "1"], timeout=600)
    return {
        "success": rc == 0,
        "stdout": out, "stderr": err,
        "message": "Quick scan completed" if rc == 0 else
        f"Scan returned code {rc}: " + (err or out)[:200]
    }


def run_update_definitions() -> Dict[str, Any]:
    """Update Windows Defender signature definitions."""
    mp = _resolve_mpcmdrun()
    rc, out, err = _cmd_run([mp, "-SignatureUpdate"], timeout=300)
    return {
        "success": rc == 0,
        "stdout": out, "stderr": err,
        "message": "Definitions updated" if rc == 0 else
        f"Update returned code {rc}: " + (err or out)[:200]
    }


def get_security_events(count: int = 30) -> List[Dict[str, str]]:
    """Retrieve recent security events from the Security log."""
    try:
        rc, out, err = _cmd_run(
            ["wevtutil", "qe", "Security", f"/c:{count}", "/f:text", "/rd:true"],
            timeout=30
        )
        if rc != 0:
            return []
        events = []
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Event["):
                if current:
                    events.append(current)
                current = {}
            elif line.startswith("EventID:"):
                current["event_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("TimeCreated:"):
                tc = line.split(":", 1)[1].strip()
                tc = tc.replace("SystemTime=", "")
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(tc[:19])
                    current["time"] = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    current["time"] = tc[:16]
            elif line.startswith("Message:"):
                current["message"] = line.split(":", 1)[1].strip()
                msg = current["message"]
                eid = current.get("event_id", "")
                if "4624" in eid:
                    current["description"] = "Logon success"
                elif "4625" in eid:
                    current["description"] = "Logon failure"
                elif "4634" in eid:
                    current["description"] = "Logoff"
                elif "4648" in eid:
                    current["description"] = "Explicit credential logon"
                elif "4657" in eid:
                    current["description"] = "Registry value modified"
                elif "4672" in eid:
                    current["description"] = "Special privileges assigned"
                elif "4688" in eid:
                    current["description"] = "Process created"
                elif "4720" in eid:
                    current["description"] = "User account created"
                elif "4722" in eid:
                    current["description"] = "User account enabled"
                elif "4723" in eid:
                    current["description"] = "Password change attempt"
                elif "4724" in eid:
                    current["description"] = "Password reset attempt"
                elif "4725" in eid:
                    current["description"] = "User account disabled"
                elif "4726" in eid:
                    current["description"] = "User account deleted"
                elif "4740" in eid:
                    current["description"] = "Account locked out"
                elif "1102" in eid:
                    current["description"] = "🛑 Audit log cleared"
                elif "5140" in eid:
                    current["description"] = "Network share accessed"
                elif "5156" in eid:
                    current["description"] = "WFP connection allowed"
                elif "5157" in eid:
                    current["description"] = "WFP connection blocked"
                else:
                    current["description"] = msg[:80] if len(msg) > 80 else msg
        if current:
            events.append(current)

        known_ids = {"4624", "4625", "4634", "4648", "4657", "4672", "4688",
                     "4720", "4722", "4723", "4724", "4725", "4726", "4740",
                     "1102", "5140", "5156", "5157"}
        return [e for e in events if e.get("event_id") in known_ids]
    except Exception:
        return []


# ── Aggregation ────────────────────────────────────────────────────────────

def get_all_security_status() -> dict:
    return {
        "defender": check_defender(),
        "firewall": check_firewall(),
        "bitlocker": check_bitlocker(),
        "secure_boot_tpm": check_secure_boot_tpm(),
    }


def check_applocker() -> Dict[str, Any]:
    """Check if AppLocker (AppIDSvc) is configured via policy."""
    try:
        key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\SrpV2"
        for sub in ["Exe", "Dll", "Msi", "Script"]:
            val = _reg_read(f"{key}\\{sub}", "EnforcementMode")
            if val is not None:
                mode_map = {0: "Audit Only", 1: "Enforce Rules"}
                mode = mode_map.get(val, f"Unknown ({val})")
                return {"status": f"Active ({mode})", "color": "green",
                        "details": [("AppLocker", f"Configured — {mode}")], "enabled": True}
        # Also check if just the service is running
        rc, out, _ = _ps("Get-Service AppIDSvc -ErrorAction SilentlyContinue | "
                          "Select-Object Status | ConvertTo-Json -Compress", timeout=15)
        if rc == 0 and out:
            data = json.loads(out)
            if data.get("Status") == "Running":
                return {"status": "Service Running", "color": "amber",
                        "details": [("AppLocker", "Service running, no rules detected")]}
        return {"status": "Not Configured", "color": "amber",
                "details": [("AppLocker", "Not configured")], "enabled": False}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("AppLocker", "Check failed")]}


def check_windows_hello() -> Dict[str, Any]:
    """Check if Windows Hello for Business is configured."""
    try:
        key = r"HKLM\SOFTWARE\Policies\Microsoft\PassportForWork"
        val = _reg_read(key, "Enabled")
        if val == 1:
            return {"status": "Enabled", "color": "green",
                    "details": [("Windows Hello", "Configured via policy")], "enabled": True}
        # Check local machine config
        key2 = r"HKLM\SOFTWARE\Microsoft\Policies\PassportForWork"
        val2 = _reg_read(key2, "Enabled")
        if val2 == 1:
            return {"status": "Enabled", "color": "green",
                    "details": [("Windows Hello", "Policy enabled")], "enabled": True}
        # Check NGC key existence (indicates PIN/Hello configured for at least one user)
        rc, out, _ = _ps(
            "Get-ChildItem -Path 'HKLM:\\SOFTWARE\\Microsoft\\Cryptography\\Ngc\\*' "
            "-ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count",
            timeout=15
        )
        if rc == 0 and out.strip() and int(out.strip()) > 0:
            return {"status": "Configured (users enrolled)", "color": "green",
                    "details": [("Windows Hello", f"{out.strip()} user(s) enrolled")],
                    "enabled": True}
        return {"status": "Not Configured", "color": "amber",
                "details": [("Windows Hello", "Not set up")], "enabled": False}
    except Exception:
        return {"status": "Unknown", "color": "amber",
                "details": [("Windows Hello", "Check failed")]}


def get_extended_status() -> dict:
    """Full security posture: all checks in one call."""
    return {
        "defender": check_defender(),
        "firewall": check_firewall(),
        "bitlocker": check_bitlocker(),
        "secure_boot_tpm": check_secure_boot_tpm(),
        "uac": check_uac(),
        "smartscreen": check_smartscreen(),
        "hvci": check_hvci(),
        "credential_guard": check_credential_guard(),
        "lsass_protection": check_lsass_protection(),
        "tamper_protection": check_tamper_protection(),
        "pua_protection": check_pua_protection(),
        "controlled_folder_access": check_controlled_folder_access(),
        "cloud_protection": check_cloud_protection(),
        "network_protection": check_network_protection_defender(),
        "rdp": check_rdp(),
        "smbv1": check_smbv1(),
        "applocker": check_applocker(),
        "windows_hello": check_windows_hello(),
        # --- Defender Detail ---
        "def_behavior": check_defender_behavior_monitoring(),
        "def_nis": check_defender_nis(),
        "def_script_scan": check_defender_script_scanning(),
        "def_ioav": check_defender_ioav(),
        "def_email_scan": check_defender_email_scanning(),
        "def_archive_scan": check_defender_archive_scanning(),
        "def_removable_scan": check_defender_removable_drive(),
        "def_cloud_timeout": check_defender_cloud_timeout(),
        "def_cloud_block": check_defender_cloud_block_level(),
        "def_cpu_limit": check_defender_cpu_usage(),
        "def_check_sigs": check_defender_check_signatures(),
        "def_catchup_scan": check_defender_catchup_scan(),
        "def_threats": check_defender_threats(),
        "def_quarantine": check_defender_quarantine(),
        "def_last_scan": check_defender_last_scan(),
        "def_engine_ver": check_defender_engine_version(),
        "def_av_mode": check_defender_av_mode(),
        "def_oobe": check_defender_oobe(),
        "def_asr_rules": check_defender_asr_rules(),
        "def_elam": check_elam(),
        "def_scan_history": check_defender_scanning_history(),
        # --- Network ---
        "llmnr": check_llmnr(),
        "netbios": check_netbios_tcpip(),
        "wpad": check_wpad(),
        "mdns": check_mdns(),
        "winrm": check_winrm(),
        "remote_registry": check_remote_registry(),
        "telnet": check_telnet(),
        "smb_signing": check_smb_signing(),
        "ntlm_level": check_ntlm_level(),
        "network_profile": check_network_profile(),
        "fw_stealth": check_firewall_stealth(),
        "listening_ports": check_listening_ports(),
        "rdp_nla": check_rdp_nla(),
        "anonymous_restrict": check_anonymous_restrict(),
        "admin_shares": check_admin_shares(),
        "autorun": check_autorun(),
        # --- System Hardening ---
        "powershell_v2": check_powershell_v2(),
        "ps_constrained": check_ps_constrained_lang(),
        "ps_exec_policy": check_ps_execution_policy(),
        "ps_script_log": check_ps_script_block_logging(),
        "ps_transcription": check_ps_transcription(),
        "wdigest": check_wdigest(),
        "cached_logons": check_cached_logons(),
        "account_lockout": check_account_lockout(),
        "password_min_len": check_password_min_length(),
        "pagefile_clear": check_pagefile_clear(),
        "ctrl_alt_del": check_ctrl_alt_del(),
        # --- Features ---
        "sandbox": check_sandbox(),
        "hyperv": check_hyperv(),
        "wsl": check_wsl(),
        "audit_policy": check_audit_policy(),
        "tpm_details": check_tpm_details(),
        "bios_mode": check_bios_mode(),
        "test_signing": check_test_signing(),
        "windows_version": check_windows_version(),
        "wu_service": check_wu_service(),
        "wu_auto_update": check_wu_auto_update(),
        "dump_encryption": check_dump_encryption(),
        "bitlocker_enc": check_bitlocker_encryption(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY A — DEFENDER DETAILS (15 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def check_defender_behavior_monitoring() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableBehaviorMonitoring | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Behavior Monitoring", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableBehaviorMonitoring", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Behavior Monitoring", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_nis() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object NISEnabled | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("NIS", "WMI failed")]}
        data = json.loads(out)
        nis = bool(data.get("NISEnabled", False))
        return {"status": "On" if nis else "Off", "color": "green" if nis else "red",
                "details": [("Network Inspection System", "On" if nis else "Off")], "enabled": nis}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_script_scanning() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableScriptScanning | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Script Scanning", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableScriptScanning", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Script Scanning", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_ioav() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableIOAVProtection | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("IOAV", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableIOAVProtection", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Downloaded Files Scanning", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_email_scanning() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableEmailScanning | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Email Scanning", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableEmailScanning", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Email Scanning", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_archive_scanning() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableArchiveScanning | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Archive Scanning", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableArchiveScanning", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Archive Scanning", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_removable_drive() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableRemovableDriveScanning | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Removable Drive Scanning", "WMI failed")]}
        data = json.loads(out)
        disabled = data.get("DisableRemovableDriveScanning", 0)
        enabled = not bool(disabled)
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("Removable Drive Scanning", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_cloud_timeout() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object CloudTimeout | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Cloud Timeout", "WMI failed")]}
        data = json.loads(out)
        timeout = data.get("CloudTimeout", 50)
        color, label = ("green", f"{timeout}s") if timeout >= 30 else ("amber", f"{timeout}s (short)")
        return {"status": label, "color": color, "details": [("Cloud Timeout", f"{timeout}s")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_cloud_block_level() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object CloudBlockLevel | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Cloud Block Level", "WMI failed")]}
        data = json.loads(out)
        level = data.get("CloudBlockLevel", 0)
        labels = {0: "Default", 2: "Low", 4: "Moderate", 6: "High", 7: "High+"}
        label = labels.get(level, f"Unknown ({level})")
        color = "green" if level >= 4 else "amber"
        return {"status": label, "color": color, "details": [("Cloud Block Level", f"Level {level} — {label}")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_cpu_usage() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object ScanAvgCPULoadFactor | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("CPU Load Limit", "WMI failed")]}
        data = json.loads(out)
        cpu = data.get("ScanAvgCPULoadFactor", 50)
        color = "green" if cpu <= 50 else "amber"
        return {"status": f"{cpu}%", "color": color, "details": [("Scan CPU Load Limit", f"{cpu}%")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_check_signatures() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object CheckForSignaturesBeforeRunningScan | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Check Signatures Before Scan", "WMI failed")]}
        data = json.loads(out)
        enabled = bool(data.get("CheckForSignaturesBeforeRunningScan", False))
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "amber",
                "details": [("Check Signatures Before Scan", "Yes" if enabled else "No")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_catchup_scan() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object DisableCatchupQuickScan, DisableCatchupFullScan | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Catchup Scans", "WMI failed")]}
        data = json.loads(out)
        quick = bool(data.get("DisableCatchupQuickScan", False))
        full = bool(data.get("DisableCatchupFullScan", False))
        both_disabled = quick and full
        return {"status": "Enabled" if not both_disabled else "Both Disabled",
                "color": "green" if not both_disabled else "red",
                "details": [("Catchup Quick Scan", "Enabled" if not quick else "Disabled"),
                            ("Catchup Full Scan", "Enabled" if not full else "Disabled")],
                "enabled": not both_disabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_threats() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("(Get-MpThreatDetection -ErrorAction SilentlyContinue | Measure-Object).Count", timeout=30)
        if rc != 0 or out is None:
            return {"status": "Unknown", "color": "amber", "details": [("Threats Detected", "WMI failed")]}
        count = int(out.strip()) if out.strip().isdigit() else 0
        return {"status": "No active threats" if count == 0 else f"{count} threat(s)",
                "color": "green" if count == 0 else "red",
                "details": [("Active Threats", str(count))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_quarantine() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("(Get-MpThreat -ErrorAction SilentlyContinue | Measure-Object).Count", timeout=30)
        if rc != 0 or out is None:
            return {"status": "Unknown", "color": "amber", "details": [("Quarantined Items", "WMI failed")]}
        count = int(out.strip()) if out.strip().isdigit() else 0
        return {"status": "Empty" if count == 0 else f"{count} item(s)",
                "color": "green" if count == 0 else "amber",
                "details": [("Quarantined Items", str(count))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_last_scan() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object QuickScanStartTime, FullScanStartTime | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Last Scans", "WMI failed")]}
        data = json.loads(out)
        def fmt(raw):
            if not raw or str(raw).startswith("0001"):
                return "Never"
            try:
                from datetime import datetime
                dt = datetime.strptime(str(raw)[:19], "%Y-%m-%dT%H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(raw)[:16]
        quick_raw = data.get("QuickScanStartTime", "")
        full_raw = data.get("FullScanStartTime", "")
        quick = fmt(quick_raw)
        full = fmt(full_raw)
        if full != "Never":
            return {"status": "Scanned", "color": "green",
                    "details": [("Last Quick Scan", quick), ("Last Full Scan", full)]}
        elif quick != "Never":
            return {"status": "Quick scan only", "color": "amber",
                    "details": [("Last Quick Scan", quick), ("Last Full Scan", "Never")]}
        return {"status": "Never scanned", "color": "red",
                "details": [("Last Quick Scan", "Never"), ("Last Full Scan", "Never")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_engine_version() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object AMEngineVersion | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Engine Version", "WMI failed")]}
        data = json.loads(out)
        ver = str(data.get("AMEngineVersion", "Unknown"))
        return {"status": ver, "color": "green", "details": [("AM Engine Version", ver)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_av_mode() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object AMRunningMode | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("AV Mode", "WMI failed")]}
        data = json.loads(out)
        mode = data.get("AMRunningMode", -1)
        if isinstance(mode, str):
            label = mode
        else:
            mode_map = {0: "Normal", 1: "Passive", 2: "EDR Block", 3: "SxS"}
            label = mode_map.get(mode, f"Unknown ({mode})")
        color = "green" if "Normal" in str(label) else ("amber" if "Passive" in str(label) else "red")
        return {"status": label, "color": color, "details": [("Defender AV Mode", label)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_oobe() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object OobeEnableRtpAndSigUpdate | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("OOBE RTP", "WMI failed")]}
        data = json.loads(out)
        enabled = bool(data.get("OobeEnableRtpAndSigUpdate", False))
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "amber",
                "details": [("OOBE RTP + Sig Update", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_asr_rules() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpPreference | Select-Object AttackSurfaceReductionRules_Ids | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("ASR Rules", "WMI failed")]}
        data = json.loads(out)
        ids = data.get("AttackSurfaceReductionRules_Ids", []) or []
        count = len(ids) if isinstance(ids, list) else (1 if ids else 0)
        if count == 0:
            return {"status": "No Rules", "color": "red", "details": [("ASR Rules", "None configured")], "enabled": False}
        return {"status": f"{count} Rules", "color": "green", "details": [("ASR Rules Configured", str(count))], "enabled": True, "rule_count": count}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_elam() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object AMServiceEnabled | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("ELAM", "WMI failed")]}
        data = json.loads(out)
        enabled = bool(data.get("AMServiceEnabled", False))
        return {"status": "On" if enabled else "Off", "color": "green" if enabled else "red",
                "details": [("ELAM (Early Launch Antimalware)", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_defender_scanning_history() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-MpComputerStatus | Select-Object QuickScanEndTime, FullScanEndTime, QuickScanSignatureVersion | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Scan History", "WMI failed")]}
        data = json.loads(out)
        quick = str(data.get("QuickScanEndTime", "Never"))
        full = str(data.get("FullScanEndTime", "Never"))
        sig = str(data.get("QuickScanSignatureVersion", "?"))
        return {"status": "History Available" if quick != "Never" else "No History",
                "color": "green" if quick != "Never" else "amber",
                "details": [("Last Quick Scan", quick[:19]), ("Signature Version", sig)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY B — NETWORK SECURITY (17 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def check_llmnr() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient", "EnableMulticast")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("LLMNR", "No policy — enabled by default")]}
        disabled = val == 0
        return {"status": "Disabled" if disabled else "Enabled",
                "color": "green" if disabled else "red",
                "details": [("LLMNR", "Off" if disabled else "On (MitM risk)")], "enabled": disabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_netbios_tcpip() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Services\NetBT\Parameters", "NodeType")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("NetBIOS", "No NodeType — default H-node")]}
        labels = {1: "B-node (broadcast)", 2: "P-node (NetBIOS disabled)", 4: "M-node", 8: "H-node (default)"}
        label = labels.get(val, f"Unknown ({val})")
        disabled = val == 2
        return {"status": label,
                "color": "green" if disabled else ("amber" if val == 8 else "red"),
                "details": [("NetBIOS NodeType", label)], "enabled": disabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_wpad() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings", "AutoDetect")
        if val is None:
            return {"status": "Disabled (default)", "color": "green",
                    "details": [("WPAD", "Off")], "enabled": False}
        enabled = val != 0
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if not enabled else "red",
                "details": [("WPAD Auto-Detect", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_mdns() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Services\Dnscache\Parameters", "EnableMDNS")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("mDNS", "No policy — enabled by default")]}
        disabled = val == 0
        return {"status": "Disabled" if disabled else "Enabled",
                "color": "green" if disabled else "red",
                "details": [("mDNS", "Off" if disabled else "On")], "enabled": disabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_winrm() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-Service WinRM -ErrorAction SilentlyContinue | Select Status | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "green",
                    "details": [("WinRM", "Not found")], "enabled": False}
        data = json.loads(out)
        status = str(data.get("Status", ""))
        running = "Running" in status or status == "4"
        return {"status": "Running" if running else "Stopped",
                "color": "red" if running else "green",
                "details": [("WinRM", "Running" if running else "Stopped")], "enabled": running}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_remote_registry() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-Service RemoteRegistry -ErrorAction SilentlyContinue | Select Status | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "green",
                    "details": [("Remote Registry", "Not found")], "enabled": False}
        data = json.loads(out)
        status = str(data.get("Status", ""))
        running = "Running" in status or status == "4"
        return {"status": "Running" if running else "Stopped",
                "color": "red" if running else "green",
                "details": [("Remote Registry", "Running" if running else "Stopped")], "enabled": running}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_telnet() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-WindowsOptionalFeature -Online -FeatureName TelnetClient | Select State | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "green",
                    "details": [("Telnet Client", "Feature not present")], "enabled": False}
        data = json.loads(out)
        state = str(data.get("State", ""))
        enabled = "Enabled" in state
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "red" if enabled else "green",
                "details": [("Telnet Client", state)], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_smb_signing() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters", "RequireSecuritySignature")
        if val is None:
            return {"status": "Not Required", "color": "red",
                    "details": [("SMB Signing", "Not configured — not required")], "enabled": False}
        required = val == 1
        return {"status": "Required" if required else "Not Required",
                "color": "green" if required else "red",
                "details": [("SMB Signing Required", "Yes" if required else "No")], "enabled": required}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ntlm_level() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa", "LmCompatibilityLevel")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("NTLM Level", "Default (send NTLMv2)")]}
        labels = {0: "Send LM & NTLM", 1: "Negotiate", 2: "Send NTLM only",
                  3: "NTLMv2 only", 4: "NTLMv2, refuse LM", 5: "NTLMv2, refuse LM & NTLM"}
        label = labels.get(val, f"Unknown ({val})")
        color = "green" if val >= 5 else ("green" if val >= 3 else ("amber" if val >= 1 else "red"))
        return {"status": f"Level {val} — {label}", "color": color,
                "details": [("LM Compatibility Level", f"Level {val} — {label}")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_network_profile() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select -ExpandProperty NetworkCategory -First 1", timeout=20)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Network Profile", "Unknown")]}
        cat_map = {"0": "Public", "1": "Private", "2": "DomainAuthenticated"}
        cat = out.strip()
        label = cat_map.get(cat, f"Unknown ({cat})")
        if cat == "0":
            return {"status": "Public (most secure)", "color": "green",
                    "details": [("Network Category", "Public")]}
        return {"status": label, "color": "amber" if cat != "0" else "green",
                "details": [("Network Category", label)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_firewall_stealth() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-NetFirewallProfile | Select Name,DefaultInboundAction,DefaultOutboundAction | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Profiles", "WMI failed")]}
        data = json.loads(out) if out.strip().startswith("[") else [json.loads(out)]
        details, stealth_ok = [], True
        for prof in data:
            name = prof.get("Name", "?")
            ib = str(prof.get("DefaultInboundAction", "?"))
            ob = str(prof.get("DefaultOutboundAction", "?"))
            details.append((f"{name} Inbound", ib))
            details.append((f"{name} Outbound", ob))
            if "allow" in ib.lower() or ib == "0":
                stealth_ok = False
        return {"status": "Inbound Blocked (Stealth)" if stealth_ok else "Inbound Allowed",
                "color": "green" if stealth_ok else "red", "details": details}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_listening_ports() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["netstat", "-an"], timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Ports", "Could not query")]}
        lines = [l for l in out.splitlines() if "LISTENING" in l.upper()]
        count = len(lines)
        color = "green" if count <= 20 else ("amber" if count <= 40 else "red")
        return {"status": f"{count} listening", "color": color,
                "details": [("Listening Ports", str(count))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_rdp_nla() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"
        val = _reg_read(key, "UserAuthentication")
        if val == 1:
            return {"status": "NLA Required", "color": "green",
                    "details": [("RDP NLA", "On — auth before session")], "enabled": True}
        elif val == 0:
            return {"status": "NLA Not Required", "color": "red",
                    "details": [("RDP NLA", "Off — MitM risk")], "enabled": False}
        return {"status": "Not Configured", "color": "amber", "details": [("RDP NLA", "Not set")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_anonymous_restrict() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa"
        ra = _reg_read(key, "RestrictAnonymous")
        ras = _reg_read(key, "RestrictAnonymousSAM")
        details = [("RestrictAnonymous", "On" if ra == 1 else "Off"),
                   ("RestrictAnonymousSAM", "On" if ras == 1 else "Off")]
        if ra == 1 and ras == 1:
            return {"status": "Fully Restricted", "color": "green", "details": details}
        return {"status": "Partially Restricted" if (ra == 1 or ras == 1) else "Not Restricted",
                "color": "amber" if (ra == 1 or ras == 1) else "red", "details": details}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_admin_shares() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters", "AutoShareWks")
        if val == 0:
            return {"status": "Disabled", "color": "green",
                    "details": [("Admin Shares (C$, ADMIN$)", "Off")], "enabled": False}
        return {"status": "Enabled", "color": "red",
                "details": [("Admin Shares (C$, ADMIN$)", "On — lateral movement risk")], "enabled": True}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_autorun() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun")
        if val == 255:
            return {"status": "Disabled (All)", "color": "green",
                    "details": [("AutoRun", "Off — all drives")], "enabled": False}
        if val is not None:
            return {"status": f"Partial (value={val})", "color": "amber",
                    "details": [("AutoRun", f"Value: {val}")]}
        return {"status": "Not Configured", "color": "red",
                "details": [("AutoRun", "Not set — may be active")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY C — SYSTEM HARDENING (16 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def check_powershell_v2() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-WindowsOptionalFeature -Online -FeatureName MicrosoftWindowsPowerShellV2Root | Select State | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "green",
                    "details": [("PowerShell v2", "Not present")], "enabled": False}
        data = json.loads(out)
        enabled = "Enabled" in str(data.get("State", ""))
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "red" if enabled else "green",
                "details": [("PowerShell v2 Engine", "Enabled (downgrade risk)" if enabled else "Disabled")],
                "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ps_constrained_lang() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("$ExecutionContext.SessionState.LanguageMode", timeout=10)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Language Mode", "Could not query")]}
        mode = out.strip()
        constrained = mode == "ConstrainedLanguage"
        return {"status": mode, "color": "green" if constrained else ("amber" if mode == "FullLanguage" else "amber"),
                "details": [("PS Language Mode", mode)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ps_execution_policy() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-ExecutionPolicy", timeout=10)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Execution Policy", "Unknown")]}
        policy = out.strip()
        color = "green" if "Restricted" in policy else ("amber" if "RemoteSigned" in policy else "red")
        return {"status": policy, "color": color, "details": [("PowerShell Execution Policy", policy)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ps_script_block_logging() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", "EnableScriptBlockLogging")
        if val == 1:
            return {"status": "Enabled", "color": "green",
                    "details": [("Script Block Logging", "On")], "enabled": True}
        return {"status": "Disabled", "color": "red",
                "details": [("Script Block Logging", "Off")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ps_transcription() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription", "EnableTranscripting")
        if val == 1:
            return {"status": "Enabled", "color": "green",
                    "details": [("PS Transcription", "On")], "enabled": True}
        return {"status": "Disabled", "color": "amber",
                "details": [("PS Transcription", "Off (not configured)")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_wdigest() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest", "UseLogonCredential")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("WDigest", "Key not present")]}
        if val == 0:
            return {"status": "Disabled (secure)", "color": "green",
                    "details": [("WDigest Caching", "Off — credentials not cached")], "enabled": False}
        return {"status": "Enabled (insecure)", "color": "red",
                "details": [("WDigest Caching", "On — credentials cached")], "enabled": True}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_cached_logons() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "CachedLogonsCount", "REG_SZ")
        if val is None:
            return {"status": "10 (default)", "color": "amber",
                    "details": [("Cached Logons", "Default: 10")]}
        count = int(val) if str(val).isdigit() else 10
        color = "green" if count <= 2 else ("amber" if count <= 10 else "red")
        return {"status": f"{count} cached logons", "color": color,
                "details": [("Cached Logon Count", str(count))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_account_lockout() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["net", "accounts"], timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Account Lockout", "Could not query")]}
        threshold = "Never"
        for line in out.splitlines():
            if "Lockout threshold" in line:
                threshold = line.split(":", 1)[-1].strip()
        if threshold.lower() == "never":
            return {"status": "Never (disabled)", "color": "red",
                    "details": [("Lockout Threshold", "Never — brute-force risk")], "enabled": False}
        return {"status": f"{threshold} attempts", "color": "green",
                "details": [("Lockout Threshold", threshold)], "enabled": True}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_password_min_length() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["net", "accounts"], timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Password Min Length", "Unknown")]}
        min_len = 0
        for line in out.splitlines():
            if "Minimum password length" in line:
                raw = line.split(":", 1)[-1].strip()
                min_len = int(raw) if raw.isdigit() else 0
        color = "green" if min_len >= 14 else ("amber" if min_len >= 8 else "red")
        return {"status": f"{min_len} chars", "color": color,
                "details": [("Minimum Password Length", str(min_len))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_pagefile_clear() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management", "ClearPageFileAtShutdown")
        if val == 1:
            return {"status": "Enabled", "color": "green",
                    "details": [("Pagefile Clear", "On — wiped on restart")], "enabled": True}
        return {"status": "Disabled", "color": "amber",
                "details": [("Pagefile Clear", "Off — data may persist")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ctrl_alt_del() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "DisableCAD")
        if val == 0:
            return {"status": "Required", "color": "green",
                    "details": [("Ctrl+Alt+Del", "Required for logon")], "enabled": True}
        elif val == 1:
            return {"status": "Not Required", "color": "amber",
                    "details": [("Ctrl+Alt+Del", "Not required")], "enabled": False}
        return {"status": "Not Configured", "color": "amber",
                "details": [("Ctrl+Alt+Del", "Not configured")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY D — FEATURES & MISC (12 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def check_sandbox() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM | Select State | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "amber",
                    "details": [("Sandbox", "Feature not present")], "enabled": False}
        data = json.loads(out)
        enabled = "Enabled" in str(data.get("State", ""))
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if enabled else "amber",
                "details": [("Windows Sandbox", str(data.get("State", "?")))], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_hyperv() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All | Select State | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Not Installed", "color": "amber",
                    "details": [("Hyper-V", "Feature not present")], "enabled": False}
        data = json.loads(out)
        enabled = "Enabled" in str(data.get("State", ""))
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if enabled else "amber",
                "details": [("Hyper-V Platform", str(data.get("State", "?")))], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_wsl() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["wsl", "--status"], timeout=20)
        if rc != 0:
            return {"status": "Not Installed", "color": "amber",
                    "details": [("WSL", "Not installed")], "enabled": False}
        details = [("WSL", "Installed")]
        for line in out.splitlines():
            if ":" in line:
                k, v = line.strip().split(":", 1)
                details.append((k.strip(), v.strip()))
        v2 = any("version: 2" in l.lower() or "wsl2" in l.lower() for l in out.splitlines())
        return {"status": "Installed (WSL2)" if v2 else "Installed",
                "color": "green", "details": details, "enabled": True}
    except FileNotFoundError:
        return {"status": "Not Installed", "color": "amber",
                "details": [("WSL", "Not installed")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_audit_policy() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["auditpol", "/get", "/category:*"], timeout=30)
        if rc != 0 or not out:
            return {"status": "Not Available", "color": "amber",
                    "details": [("Audit Policy", "Could not retrieve (needs admin)")]}
        enabled = sum(1 for line in out.splitlines() if "Enabled" in line and "No Auditing" not in line)
        total = sum(1 for line in out.splitlines() if "No Auditing" in line)
        if enabled == 0:
            return {"status": "No Categories Enabled", "color": "red",
                    "details": [("Enabled", "0 categories")]}
        return {"status": f"{enabled} Categories Enabled", "color": "green",
                "details": [("Enabled", f"{enabled} categories")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_tpm_details() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-Tpm | Select TpmPresent, TpmReady, TpmEnabled | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Not Available", "color": "red", "details": [("TPM", "Not present")]}
        data = json.loads(out)
        present = bool(data.get("TpmPresent", False))
        ready = bool(data.get("TpmReady", False))
        enabled = bool(data.get("TpmEnabled", False))
        if not present:
            return {"status": "No TPM", "color": "red", "details": [("TPM", "Not present")]}
        return {"status": "Ready" if ready else "Present (not ready)", "color": "green" if ready else "amber",
                "details": [("TPM Ready", str(ready)), ("TPM Enabled", str(enabled))], "enabled": ready}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_bios_mode() -> Dict[str, Any]:
    try:
        uefi = os.path.exists(r"C:\Windows\System32\winload.efi")
        return {"status": "UEFI" if uefi else "Legacy BIOS",
                "color": "green" if uefi else "amber",
                "details": [("Firmware", "UEFI" if uefi else "Legacy")], "enabled": uefi}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_test_signing() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["bcdedit", "/enum"], timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber",
                    "details": [("Test Signing", "Could not query BCD")]}
        test_on = "testsigning" in out.lower() and "yes" in out.lower()
        if test_on:
            return {"status": "Enabled (DANGER)", "color": "red",
                    "details": [("Test Signing", "On — allows unsigned drivers!")], "enabled": True}
        return {"status": "Disabled", "color": "green",
                "details": [("Test Signing", "Off")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_windows_version() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-ComputerInfo -Property OsBuildNumber | Select OsBuildNumber | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("Version", "Unknown")]}
        data = json.loads(out)
        build = str(data.get("OsBuildNumber", "?"))
        return {"status": f"Build {build}", "color": "green",
                "details": [("OS Build", build)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_wu_service() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-Service wuauserv -ErrorAction SilentlyContinue | Select Status,StartType | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Service Not Found", "color": "red", "details": [("WU Service", "Not found")]}
        data = json.loads(out)
        status = str(data.get("Status", "?"))
        stype = str(data.get("StartType", "?"))
        running = "Running" in status or status == "4"
        return {"status": status if isinstance(status, str) else ("Running" if running else "Stopped"),
                "color": "green" if running else "amber",
                "details": [("Windows Update Service", status), ("Start Type", stype)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_wu_auto_update() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU", "AUOptions")
        if val is None:
            return {"status": "Default (auto-install)", "color": "green",
                    "details": [("Auto Update", "Default policy")]}
        labels = {2: "Notify before download", 3: "Auto download, notify",
                  4: "Auto install", 5: "Admin chooses"}
        label = labels.get(val, f"Unknown ({val})")
        return {"status": label, "color": "green" if val in (3, 4) else "amber",
                "details": [("Auto Update Policy", label)]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_dump_encryption() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\CrashControl", "EncryptionEnabled")
        if val is None:
            return {"status": "Not Supported", "color": "amber",
                    "details": [("Crash Dump Encryption", "Feature not present")]}
        return {"status": "Enabled" if val == 1 else "Disabled",
                "color": "green" if val == 1 else "amber",
                "details": [("Crash Dump Encryption", "On" if val == 1 else "Off")], "enabled": val == 1}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_bitlocker_encryption() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-BitLockerVolume | Select MountPoint,EncryptionMethod,VolumeStatus,ProtectionStatus | ConvertTo-Json -Compress", timeout=30)
        if rc != 0 or not out:
            return {"status": "N/A", "color": "amber", "details": [("BitLocker", "No volumes or not available")]}
        data = json.loads(out) if out.strip().startswith("[") else [json.loads(out)]
        details, c_protected = [], False
        for vol in data:
            mp = vol.get("MountPoint", "?")
            method = str(vol.get("EncryptionMethod", "None"))
            vstat = str(vol.get("VolumeStatus", "?"))
            prot = vol.get("ProtectionStatus", 0)
            details.append((f"Drive {mp}", f"{vstat} ({method})"))
            if str(mp).upper() == "C:" and prot == 1:
                c_protected = True
        return {"status": "C: Protected" if c_protected else "C: Not Protected",
                "color": "green" if c_protected else "red", "details": details}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}


# ═══════════════════════════════════════════════════════════════════════════════
# Toggle helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_mp_pref_value(pref_name: str) -> Optional[int]:
    try:
        rc, out, _ = _ps(f"Get-MpPreference | Select-Object {pref_name} | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return None
        return json.loads(out).get(pref_name)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Additional toggle functions (15)
# ═══════════════════════════════════════════════════════════════════════════════

def set_defender_behavior_monitoring(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableBehaviorMonitoring")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableBehaviorMonitoring", 0 if enabled else 1, "Behaviour monitoring")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_script_scanning(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableScriptScanning")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableScriptScanning", 0 if enabled else 1, "Script scanning")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_email_scanning(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableEmailScanning")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableEmailScanning", 0 if enabled else 1, "Email scanning")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_archive_scanning(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableArchiveScanning")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableArchiveScanning", 0 if enabled else 1, "Archive scanning")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_ioav(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableIOAVProtection")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableIOAVProtection", 0 if enabled else 1, "IOAV protection")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_removable_drive_scanning(enabled: bool) -> Dict[str, Any]:
    before_raw = _get_mp_pref_value("DisableRemovableDriveScanning")
    before_val = None if before_raw is None else (before_raw == 0)
    result = _set_mp_pref("DisableRemovableDriveScanning", 0 if enabled else 1, "Removable drive scanning")
    result["before_value"] = before_val
    result["after_value"] = enabled
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_catchup_scans(enabled: bool) -> Dict[str, Any]:
    before_quick = _get_mp_pref_value("DisableCatchupQuickScan")
    before_full = _get_mp_pref_value("DisableCatchupFullScan")
    before_val = {"quick": None if before_quick is None else (before_quick == 0),
                  "full": None if before_full is None else (before_full == 0)}
    new_val = 0 if enabled else 1
    r1 = _set_mp_pref("DisableCatchupQuickScan", new_val, "Catch-up quick scan")
    r2 = _set_mp_pref("DisableCatchupFullScan", new_val, "Catch-up full scan")
    success = r1["success"] and r2["success"]
    return {"success": success, "message": f"Catch-up scans {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": enabled,
            "action": "enable" if enabled else "disable"}

def set_defender_cloud_block_level(level: int) -> Dict[str, Any]:
    if level not in (0, 2, 4, 6):
        return {"success": False, "message": f"Invalid level: {level}. Use 0, 2, 4, or 6.",
                "before_value": None, "after_value": None, "action": "set_cloud_block_level"}
    before_val = _get_mp_pref_value("CloudBlockLevel")
    result = _set_mp_pref("CloudBlockLevel", level, f"Cloud block level ({level})")
    result["before_value"] = before_val
    result["after_value"] = level
    result["action"] = "set_cloud_block_level"
    return result

def set_llmnr(enabled: bool) -> Dict[str, Any]:
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient"
    before_val = _reg_read(key, "EnableMulticast")
    ok = _reg_write(key, "EnableMulticast", 1 if enabled else 0)
    return {"success": ok, "message": f"LLMNR {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}

def set_wpad(enabled: bool) -> Dict[str, Any]:
    key = r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings"
    before_val = _reg_read(key, "AutoDetect")
    ok = _reg_write(key, "AutoDetect", 1 if enabled else 0)
    return {"success": ok, "message": f"WPAD {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}

def set_wdigest_credential_caching(enabled: bool) -> Dict[str, Any]:
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest"
    before_val = _reg_read(key, "UseLogonCredential")
    ok = _reg_write(key, "UseLogonCredential", 1 if enabled else 0)
    return {"success": ok, "message": f"WDigest caching {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}

def set_ntlm_level(level: int) -> Dict[str, Any]:
    if not isinstance(level, int) or level < 0 or level > 5:
        return {"success": False, "message": f"Invalid NTLM level: {level}. Must be 0-5.",
                "before_value": None, "after_value": None, "action": "set_ntlm_level"}
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa"
    before_val = _reg_read(key, "LmCompatibilityLevel")
    ok = _reg_write(key, "LmCompatibilityLevel", level)
    return {"success": ok, "message": f"NTLM level set to {level}",
            "before_value": before_val, "after_value": level,
            "action": "set_ntlm_level"}

def set_cached_logons(count: int) -> Dict[str, Any]:
    if not isinstance(count, int) or count < 0 or count > 50:
        return {"success": False, "message": f"Invalid count: {count}. Must be 0-50.",
                "before_value": None, "after_value": None, "action": "set_cached_logons"}
    key = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    before_val = _reg_read(key, "CachedLogonsCount", "REG_SZ")
    ok = _reg_write(key, "CachedLogonsCount", str(count), "REG_SZ")
    return {"success": ok, "message": f"Cached logons set to {count}",
            "before_value": before_val, "after_value": count, "action": "set_cached_logons"}

def set_pagefile_clear(enabled: bool) -> Dict[str, Any]:
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
    before_val = _reg_read(key, "ClearPageFileAtShutdown")
    ok = _reg_write(key, "ClearPageFileAtShutdown", 1 if enabled else 0)
    return {"success": ok, "message": f"Pagefile clear {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}

def set_ps_script_block_logging(enabled: bool) -> Dict[str, Any]:
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"
    before_val = _reg_read(key, "EnableScriptBlockLogging")
    ok = _reg_write(key, "EnableScriptBlockLogging", 1 if enabled else 0)
    return {"success": ok, "message": f"PS script block logging {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY E — SERVICES STATUS (20 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_service(service_name: str, display: str, good_running: bool = True) -> Dict[str, Any]:
    try:
        rc, out, _ = _ps(
            f"Get-Service {service_name} -ErrorAction SilentlyContinue | Select Status | ConvertTo-Json -Compress",
            timeout=15)
        if not out or "{" not in out:
            return {"status": "Not Found", "color": "amber",
                    "details": [(display, "Service not found")], "enabled": False}
        data = json.loads(out)
        st = str(data.get("Status", ""))
        running = "Running" in st or st == "4"
        if running:
            color, status = ("green", "Running") if good_running else ("red", "Running")
        else:
            color, status = ("red", "Stopped") if good_running else ("green", "Stopped")
        return {"status": status, "color": color, "details": [(f"{display} Service", st)], "enabled": running}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [(display, "Check failed")], "enabled": False}


def check_service_dnscache() -> Dict[str, Any]:
    return _check_service("Dnscache", "DNS Client", good_running=True)

def check_service_dhcp() -> Dict[str, Any]:
    return _check_service("Dhcp", "DHCP Client", good_running=True)

def check_service_lanman_workstation() -> Dict[str, Any]:
    return _check_service("LanmanWorkstation", "Lanman Workstation", good_running=True)

def check_service_lanman_server() -> Dict[str, Any]:
    return _check_service("LanmanServer", "Lanman Server", good_running=False)

def check_service_wsearch() -> Dict[str, Any]:
    return _check_service("WSearch", "Windows Search", good_running=False)

def check_service_sysmain() -> Dict[str, Any]:
    return _check_service("SysMain", "SysMain / Superfetch", good_running=False)

def check_service_fax() -> Dict[str, Any]:
    return _check_service("Fax", "Fax", good_running=False)

def check_service_xbox_live() -> Dict[str, Any]:
    return _check_service("XboxNetApiSvc", "Xbox Live Networking", good_running=False)

def check_service_xbox_game_save() -> Dict[str, Any]:
    return _check_service("XblGameSave", "Xbox Game Save", good_running=False)

def check_service_xbox_accessory() -> Dict[str, Any]:
    return _check_service("XboxGipSvc", "Xbox Accessory Management", good_running=False)

def check_service_diag_track() -> Dict[str, Any]:
    return _check_service("DiagTrack", "Connected User Experiences / Telemetry", good_running=False)

def check_service_wpn() -> Dict[str, Any]:
    return _check_service("WpnService", "Push Notifications", good_running=False)

def check_service_maps_broker() -> Dict[str, Any]:
    return _check_service("MapsBroker", "Maps Broker", good_running=False)

def check_service_walletsvc() -> Dict[str, Any]:
    return _check_service("WalletService", "Wallet Service", good_running=False)

def check_service_fdphost() -> Dict[str, Any]:
    return _check_service("fdPHost", "Function Discovery Provider", good_running=False)

def check_service_fdrespub() -> Dict[str, Any]:
    return _check_service("FDResPub", "Function Discovery Publication", good_running=False)

def check_service_net_tcp_port_sharing() -> Dict[str, Any]:
    return _check_service("NetTcpPortSharing", "Net.Tcp Port Sharing", good_running=False)

def check_service_remote_access_connection() -> Dict[str, Any]:
    return _check_service("RasMan", "Remote Access Connection Manager", good_running=False)

def check_service_telephony() -> Dict[str, Any]:
    return _check_service("TapiSrv", "Telephony", good_running=False)

def check_service_webclient() -> Dict[str, Any]:
    return _check_service("WebClient", "WebClient", good_running=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY F — SERVICE TOGGLES (10)
# ═══════════════════════════════════════════════════════════════════════════════

def _set_service_startup(svc: str, label: str, enabled: bool) -> Dict[str, Any]:
    startup = "Automatic" if enabled else "Disabled"
    try:
        rc_before, out_before, _ = _ps(
            f"Get-Service {svc} -ErrorAction SilentlyContinue | Select StartType | ConvertTo-Json -Compress",
            timeout=15)
        before_val = json.loads(out_before).get("StartType", "Unknown") if (rc_before == 0 and out_before) else None
    except Exception:
        before_val = None

    rc, out, err = _ps(
        f"$ErrorActionPreference='Stop'; try {{ Set-Service {svc} -StartupType {startup}; Write-Output 'SUCCESS' }} "
        f"catch {{ Write-Error $_.Exception.Message }}",
        timeout=30)
    success = rc == 0 and "SUCCESS" in out
    msg = f"{label} set to {startup}" if success else (err or out or f"Failed to set {label}")
    return {"success": success, "message": msg, "before_value": before_val,
            "after_value": startup, "action": "enable" if enabled else "disable"}


def set_service_wsearch(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("WSearch", "Windows Search", enabled)

def set_service_sysmain(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("SysMain", "SysMain / Superfetch", enabled)

def set_service_fax(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("Fax", "Fax", enabled)

def set_service_xbox_live(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("XboxNetApiSvc", "Xbox Live Networking", enabled)

def set_service_diag_track(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("DiagTrack", "Connected User Experiences", enabled)

def set_service_wpn(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("WpnService", "Push Notifications", enabled)

def set_service_maps_broker(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("MapsBroker", "Maps Broker", enabled)

def set_service_fdphost(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("fdPHost", "Function Discovery Provider", enabled)

def set_service_webclient(enabled: bool) -> Dict[str, Any]:
    return _set_service_startup("WebClient", "WebClient", enabled)

def set_service_remote_registry_disabled() -> Dict[str, Any]:
    try:
        rc, out_before, _ = _ps(
            "Get-Service RemoteRegistry -ErrorAction SilentlyContinue | Select StartType | ConvertTo-Json -Compress",
            timeout=15)
        before_val = json.loads(out_before).get("StartType", "Unknown") if (rc == 0 and out_before) else None
    except Exception:
        before_val = None
    rc, out, err = _cmd_run(["sc", "config", "RemoteRegistry", "start=", "disabled"], timeout=15)
    success = rc == 0
    msg = "RemoteRegistry set to disabled" if success else (err or out or "Failed to set RemoteRegistry")
    return {"success": success, "message": msg, "before_value": before_val,
            "after_value": "Disabled", "action": "disable"}


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY G — WINDOWS FEATURES (10 checks)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_win_feature(feature: str, label: str, good_enabled: bool = True) -> Dict[str, Any]:
    try:
        rc, out, _ = _ps(
            f"Get-WindowsOptionalFeature -Online -FeatureName {feature} | Select State | ConvertTo-Json -Compress",
            timeout=20)
        if rc != 0 or not out:
            return {"status": "Not Available", "color": "amber",
                    "details": [(label, "Feature not found")], "enabled": False}
        data = json.loads(out)
        state = str(data.get("State", ""))
        enabled = "Enabled" in state
        if enabled:
            color, status = ("green", "Enabled") if good_enabled else ("red", "Enabled")
        else:
            color, status = ("red", "Disabled") if good_enabled else ("green", "Disabled")
        return {"status": status, "color": color, "details": [(label, state)], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [(label, "Check failed")], "enabled": False}


def check_feature_windows_media_player() -> Dict[str, Any]:
    return _check_win_feature("MediaPlayback", "Windows Media Player", good_enabled=False)

def check_feature_work_folders() -> Dict[str, Any]:
    return _check_win_feature("WorkFolders-Client", "Work Folders Client", good_enabled=False)

def check_feature_print_xps() -> Dict[str, Any]:
    return _check_win_feature("Printing-XPSServices-Features", "XPS Document Services", good_enabled=False)

def check_feature_internet_explorer() -> Dict[str, Any]:
    return _check_win_feature("Internet-Explorer-Optional-amd64", "Internet Explorer 11", good_enabled=False)

def check_feature_netfx3() -> Dict[str, Any]:
    return _check_win_feature("NetFx3", ".NET Framework 3.5", good_enabled=True)

def check_feature_iis() -> Dict[str, Any]:
    return _check_win_feature("IIS-WebServerRole", "IIS Web Server", good_enabled=False)

def check_feature_windows_fax_scan() -> Dict[str, Any]:
    return _check_win_feature("Printing-Fax-Features", "Windows Fax & Scan", good_enabled=False)

def check_feature_simple_tcpip() -> Dict[str, Any]:
    return _check_win_feature("SimpleTCP", "Simple TCP/IP Services", good_enabled=False)

def check_feature_legacy_components() -> Dict[str, Any]:
    return _check_win_feature("LegacyComponents", "Legacy Components", good_enabled=False)

def check_feature_direct_play() -> Dict[str, Any]:
    return _check_win_feature("DirectPlay", "DirectPlay", good_enabled=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY H — MISCELLANEOUS CHECKS (10)
# ═══════════════════════════════════════════════════════════════════════════════

def check_disk_cleanup_state() -> Dict[str, Any]:
    try:
        details = []
        rc, out, _ = _ps("Get-Command cleanmgr.exe -ErrorAction SilentlyContinue", timeout=10)
        cleanmgr_available = rc == 0
        details.append(("Disk Cleanup (cleanmgr)", "Available" if cleanmgr_available else "Not found"))
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy",
                        "01", "REG_DWORD")
        if val is not None:
            sense_on = val == 1
            details.append(("Storage Sense", "On" if sense_on else "Off"))
        else:
            sense_on = None
            details.append(("Storage Sense", "Not configured"))
        if cleanmgr_available:
            return {"status": "Available", "color": "green", "details": details, "enabled": True}
        return {"status": "Limited", "color": "amber", "details": details, "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Disk Cleanup", "Check failed")]}

def check_system_restore_disks() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["vssadmin", "list", "shadowstorage"], timeout=20)
        if rc != 0:
            return {"status": "N/A (not elevated?)", "color": "amber",
                    "details": [("Shadow Storage", "Could not query")]}
        details = []
        used_total = 0
        for line in out.splitlines():
            if "Used Shadow Copy Storage space" in line:
                try:
                    pct_str = line.split("(")[-1].split("%")[0].strip()
                    used_total = float(pct_str)
                except Exception:
                    logger.warning("Ignored Exception parsing vssadmin output", exc_info=True)
        if used_total > 0:
            details.append(("Shadow Storage Used", f"{used_total:.1f}%"))
            color = "green" if used_total < 50 else ("amber" if used_total < 80 else "red")
            return {"status": f"{used_total:.1f}% used", "color": color, "details": details, "enabled": True}
        details.append(("Shadow Storage", "0% used"))
        return {"status": "0% used", "color": "green", "details": details, "enabled": True}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("System Restore", "Check failed")]}

def check_hibernation() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["powercfg", "/hibernate"], timeout=15)
        if rc != 0:
            return {"status": "N/A", "color": "amber",
                    "details": [("Hibernation", f"Query returned code {rc}")], "enabled": False}
        details = []
        # powercfg /hibernate alone returns status; /availoffsets shows more
        rc2, out2, _ = _cmd_run(["powercfg", "/a"], timeout=15)
        hibernate_available = "hibernate" in out2.lower() if out2 else False
        details.append(("Hibernation Available", "Yes" if hibernate_available else "No"))
        if hibernate_available:
            rc3, out3, _ = _cmd_run(["powercfg", "/hibernate", "on"], timeout=10)
            details.append(("Hibernation Status", "Enabled"))
            return {"status": "Enabled", "color": "amber", "details": details, "enabled": True}
        return {"status": "Disabled / Not Available", "color": "green", "details": details, "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Hibernation", "Check failed")]}

def check_fast_startup() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power"
        val = _reg_read(key, "HiberbootEnabled")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("Fast Startup", "Not set (default enabled)")], "enabled": True}
        enabled = val == 1
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if not enabled else "amber",
                "details": [("Fast Startup", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Fast Startup", "Check failed")]}

def check_core_isolation_summary() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
        val = _reg_read(key, "Enabled")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("Core Isolation", "No registry entry")], "enabled": False}
        enabled = val == 1
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if enabled else "red",
                "details": [("Core Isolation / Memory Integrity", "On" if enabled else "Off")], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Core Isolation", "Check failed")]}

def check_memory_integrity_registry() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
        val = _reg_read(key, "Enabled")
        if val is None:
            return {"status": "Not Configured", "color": "amber",
                    "details": [("Memory Integrity", "No registry policy")], "enabled": False}
        enabled = val == 1
        return {"status": "Enabled" if enabled else "Disabled",
                "color": "green" if enabled else "red",
                "details": [("HypervisorEnforcedCodeIntegrity\\Enabled", str(val))], "enabled": enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Memory Integrity", "Check failed")]}

def check_exploit_protection_system() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-ProcessMitigation -System | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "N/A", "color": "amber",
                    "details": [("System Exploit Protections", "WMI unavailable")]}
        data = json.loads(out)
        count = 0
        enabled_list = []
        if isinstance(data, dict):
            for category, settings in data.items():
                if isinstance(settings, dict):
                    for k, v in settings.items():
                        if v in (1, True, "On") and "enable" in str(k).lower():
                            count += 1
                            enabled_list.append(str(k))
                elif isinstance(settings, (list, int, bool)):
                    if settings in (1, True, "On", "True"):
                        count += 1
                        enabled_list.append(str(category))
        color = "green" if count >= 10 else ("amber" if count >= 5 else "red")
        return {"status": f"{count} mitigations active", "color": color,
                "details": [("System Mitigations", str(count))], "enabled": count > 0,
                "mitigation_count": count}
    except Exception:
        return {"status": "Error", "color": "amber",
                "details": [("Exploit Protection", "Check failed")]}

def check_exploit_protection_cfg() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-ProcessMitigation -System | ConvertTo-Json -Compress", timeout=20)
        if rc != 0 or not out:
            return {"status": "N/A", "color": "amber",
                    "details": [("CFG", "WMI unavailable")], "enabled": False}
        data = json.loads(out)
        cfg_enabled = False
        if isinstance(data, dict):
            for cat, settings in data.items():
                if isinstance(settings, dict):
                    if "enable" in str(settings.get("CFG", "")).lower():
                        cfg_enabled = settings.get("CFG") in (1, True, "On", "True")
                        if cfg_enabled:
                            break
                    if settings.get("EnableControlFlowGuard") in (1, True, "On"):
                        cfg_enabled = True
                        break
        return {"status": "On" if cfg_enabled else "Off",
                "color": "green" if cfg_enabled else "red",
                "details": [("Control Flow Guard (CFG)", "On" if cfg_enabled else "Off")],
                "enabled": cfg_enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("CFG", "Check failed")]}

def check_exploit_protection_dep() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["bcdedit", "/enum"], timeout=15)
        dep_enabled = False
        if rc == 0 and out:
            dep_enabled = "nx" in out.lower() and "optin" in out.lower() or "alwayson" in out.lower() or "optout" in out.lower()
            if not dep_enabled:
                rc2, out2, _ = _ps("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management').ClearPageFileAtShutdown", timeout=10)
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management", "DataExecutionPrevention_Available")
        pol = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management", "DataExecutionPrevention_Policy")
        details = []
        if val is not None:
            details.append(("DEP Hardware Support", "Yes" if val == 1 else "No"))
        if pol is not None:
            dep_map = {0: "OptIn (default)", 1: "Disabled", 2: "OptOut (enforce)", 3: "AlwaysOn"}
            dep_label = dep_map.get(pol, f"Unknown ({pol})")
            details.append(("DEP Policy", dep_label))
            dep_enabled = pol in (0, 2, 3)
        if not details:
            details.append(("DEP", "No policy found — Windows default (OptIn)"))
            dep_enabled = True
        return {"status": "Enabled" if dep_enabled else "Disabled",
                "color": "green" if dep_enabled else "red", "details": details, "enabled": dep_enabled}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("DEP", "Check failed")]}

def check_exploit_protection_aslr() -> Dict[str, Any]:
    try:
        key = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
        mb = _reg_read(key, "MoveImages")
        details = []
        if mb is not None:
            mb_on = mb == 0xFFFFFFFF  # bottom-up randomization is ASLR
            details.append(("Bottom-Up Randomization", "On" if mb_on else "Off"))
        else:
            details.append(("Bottom-Up Randomization", "Default (On)"))
        he = _reg_read(key, "HighEntropyASLROn64Bit")
        if he is not None:
            he_on = he == 1
            details.append(("High Entropy ASLR (64-bit)", "On" if he_on else "Off"))
        else:
            details.append(("High Entropy ASLR (64-bit)", "Not configured (Windows default)"))
        # Also check via Get-ProcessMitigation
        rc, out, _ = _ps("Get-ProcessMitigation -System | ConvertTo-Json -Compress", timeout=15)
        if rc == 0 and out:
            data = json.loads(out) if out else {}
            # count ASLR-related mitigations found
            aslr_count = 0
            raw = str(data).lower()
            for term in ["bottomup", "high entropy", "aslr", "forcerelocate", "force,"]:
                if term in raw:
                    aslr_count += 1
            details.append(("ASLR Mitigation Count", str(aslr_count)))
        color = "green" if all("Off" not in d[1] for d in details) else "amber"
        return {"status": "Active", "color": color, "details": details, "enabled": True}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("ASLR", "Check failed")]}


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS BATCH — Services, Network Toggles, Account Security (~40 functions)
# ═══════════════════════════════════════════════════════════════════════════════

def _svc_check(name: str, label: str, running_bad: bool = True) -> Dict[str, Any]:
    try:
        rc, out, _ = _ps(f"Get-Service {name} -ErrorAction SilentlyContinue | Select Status,StartType | ConvertTo-Json -Compress", timeout=15)
        if not out:
            return {"status": "Not Found", "color": "green", "details": [(label, "Not found")], "enabled": False}
        data = json.loads(out)
        st, ty = str(data.get("Status", "")), str(data.get("StartType", ""))
        running = "Running" in st or st == "4"
        auto = "2" in str(ty) or "Automatic" in str(ty)
        if running_bad:
            color = "red" if running else ("amber" if auto else "green")
        else:
            color = "green" if running else ("amber" if auto else "red")
        return {"status": "Running" if running else "Stopped", "color": color,
                "details": [(label, f"{'Running' if running else 'Stopped'} ({'Auto' if auto else 'Manual'})")],
                "enabled": running}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [(label, "Check failed")]}

def _svc_toggle(name: str, label: str, enabled: bool) -> Dict[str, Any]:
    before = _svc_check(name, label, running_bad=True)
    start_type = "Automatic" if enabled else "Disabled"
    try:
        rc, out, err = _ps(f"Set-Service {name} -StartupType {start_type} -ErrorAction Stop 2>&1; if($?){{'SUCCESS'}}else{{$Error[0]}}", timeout=20)
        ok = "SUCCESS" in (out or "")
        return {"success": ok, "message": f"{label} set to {start_type}" if ok else (err or out or "Failed"),
                "before_value": before.get("enabled"), "after_value": enabled,
                "action": "enable" if enabled else "disable"}
    except Exception as ex:
        return {"success": False, "message": str(ex), "before_value": before.get("enabled"),
                "after_value": before.get("enabled"), "action": "enable" if enabled else "disable"}

def check_service_print_spooler(): return _svc_check("Spooler", "Print Spooler", running_bad=True)
def check_service_dnscache(): return _svc_check("Dnscache", "DNS Client", running_bad=False)
def check_service_dhcp(): return _svc_check("Dhcp", "DHCP Client", running_bad=False)
def check_service_wsearch(): return _svc_check("WSearch", "Windows Search", running_bad=True)
def check_service_sysmain(): return _svc_check("SysMain", "SysMain (Superfetch)", running_bad=True)
def check_service_fax(): return _svc_check("Fax", "Fax Service", running_bad=True)
def check_service_xbox_live(): return _svc_check("XboxNetApiSvc", "Xbox Networking", running_bad=True)
def check_service_diagtrack(): return _svc_check("DiagTrack", "Diagnostics Tracking", running_bad=True)
def check_service_wpn(): return _svc_check("WpnService", "Push Notifications", running_bad=True)
def check_service_mapsbroker(): return _svc_check("MapsBroker", "Maps Broker", running_bad=True)
def check_service_fdphost(): return _svc_check("fdPHost", "Function Discovery", running_bad=True)
def check_service_webclient(): return _svc_check("WebClient", "WebClient", running_bad=True)
def check_service_bthserv(): return _svc_check("bthserv", "Bluetooth", running_bad=True)
def check_service_snmp(): return _svc_check("SNMP", "SNMP Service", running_bad=True)
def check_service_upnp(): return _svc_check("upnphost", "UPnP Device Host", running_bad=True)

def check_service_defender_status():
    try:
        rc, out, _ = _ps("Get-Service WinDefend | Select Status,StartType | ConvertTo-Json -Compress", timeout=15)
        if not out:
            return {"status": "Not Found", "color": "red", "details": [("WinDefend", "Not found!")], "enabled": False}
        data = json.loads(out)
        running = "Running" in str(data.get("Status", "")) or data.get("Status") == 4
        return {"status": "Running" if running else "Stopped", "color": "green" if running else "red",
                "details": [("Defender Service", "Running" if running else "Stopped")], "enabled": running}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("WinDefend", "Check failed")]}

# Service toggles
set_service_print_spooler = lambda e: _svc_toggle("Spooler", "Print Spooler", e)
set_service_fax = lambda e: _svc_toggle("Fax", "Fax Service", e)
set_service_xbox_live = lambda e: _svc_toggle("XboxNetApiSvc", "Xbox Networking", e)
set_service_diagtrack = lambda e: _svc_toggle("DiagTrack", "Diagnostics Tracking", e)
set_service_wsearch = lambda e: _svc_toggle("WSearch", "Windows Search", e)

def set_remote_desktop(enabled: bool) -> Dict[str, Any]:
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server"
    before_val = _reg_read(key, "fDenyTSConnections")
    ok = _reg_write(key, "fDenyTSConnections", 0 if enabled else 1)
    return {"success": ok, "message": f"RDP {'enabled' if enabled else 'disabled'}",
            "before_value": before_val, "after_value": 0 if enabled else 1,
            "action": "enable" if enabled else "disable"}

def set_network_discovery(enabled: bool) -> Dict[str, Any]:
    state = "yes" if enabled else "no"
    rc, out, err = _cmd_run(["netsh", "advfirewall", "firewall", "set", "rule",
                              "group=\"Network Discovery\"", "new", f"enable={state}"], timeout=30)
    ok = rc == 0 and "error" not in (err or "").lower()
    return {"success": ok, "message": f"Network Discovery {'enabled' if enabled else 'disabled'}",
            "before_value": not enabled, "after_value": enabled,
            "action": "enable" if enabled else "disable"}

def set_file_sharing(enabled: bool) -> Dict[str, Any]:
    state = "yes" if enabled else "no"
    rc, out, err = _cmd_run(["netsh", "advfirewall", "firewall", "set", "rule",
                              "group=\"File and Printer Sharing\"", "new", f"enable={state}"], timeout=30)
    ok = rc == 0
    return {"success": ok, "message": f"File Sharing {'enabled' if enabled else 'disabled'}",
            "before_value": not enabled, "after_value": enabled,
            "action": "enable" if enabled else "disable"}

# Account checks
def check_guest_account() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["net", "user", "guest"], timeout=10)
        if rc != 0:
            return {"status": "Not Found", "color": "green", "details": [("Guest", "Account not found")], "enabled": False}
        active = "Account active" in out and "Yes" in out
        return {"status": "Active" if active else "Inactive", "color": "red" if active else "green",
                "details": [("Guest Account", "Active" if active else "Disabled")], "enabled": active}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("Guest", "Check failed")]}

def check_autologon() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "AutoAdminLogon", "REG_SZ")
        active = val and str(val) != "0"
        return {"status": "Enabled" if active else "Disabled", "color": "red" if active else "green",
                "details": [("Auto Logon", "On (security risk)" if active else "Off")], "enabled": active}
    except Exception:
        return {"status": "Error", "color": "amber", "details": [("AutoLogon", "Check failed")]}

def check_last_username_hidden() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "DontDisplayLastUserName")
        hidden = val == 1
        return {"status": "Hidden" if hidden else "Shown", "color": "green" if hidden else "amber",
                "details": [("Last Username", "Hidden on logon" if hidden else "Shown (less secure)")], "enabled": hidden}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_screensaver_secure() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKCU\Control Panel\Desktop", "ScreenSaverIsSecure", "REG_SZ")
        secure = val and str(val) == "1"
        return {"status": "Lock on resume" if secure else "No lock", "color": "green" if secure else "amber",
                "details": [("Screen Saver Lock", "On" if secure else "Off (no lock on resume)")], "enabled": secure}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_screensaver_active() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKCU\Control Panel\Desktop", "SCRNSAVE.EXE", "REG_SZ")
        if val and str(val).strip():
            return {"status": "Configured", "color": "green",
                    "details": [("Screen Saver", str(val)[:50])], "enabled": True}
        return {"status": "Not Configured", "color": "amber",
                "details": [("Screen Saver", "None")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_fast_startup() -> Dict[str, Any]:
    try:
        val = _reg_read(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled")
        if val == 1:
            return {"status": "Enabled", "color": "amber",
                    "details": [("Fast Startup", "On (may cause issues)")], "enabled": True}
        return {"status": "Disabled", "color": "green",
                "details": [("Fast Startup", "Off")], "enabled": False}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_dns_servers() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("Get-DnsClientServerAddress -AddressFamily IPv4 | Select -ExpandProperty ServerAddresses | ConvertTo-Json -Compress", timeout=15)
        if rc != 0 or not out:
            return {"status": "Unknown", "color": "amber", "details": [("DNS", "Could not query")]}
        servers = json.loads(out) if out.startswith("[") else [out.strip('"')]
        if isinstance(servers, str):
            servers = [servers]
        details = [("DNS Server", s) for s in servers[:3]]
        return {"status": f"{len(servers)} server(s)", "color": "green",
                "details": details or [("DNS", "DHCP-assigned")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_ntp_sync() -> Dict[str, Any]:
    try:
        rc, out, _ = _cmd_run(["w32tm", "/query", "/status"], timeout=10)
        if rc != 0:
            return {"status": "Not Synced", "color": "amber", "details": [("NTP", "Could not query")]}
        source = ""
        for line in out.splitlines():
            if "Source:" in line:
                source = line.split(":", 1)[1].strip()
        if source:
            return {"status": f"Synced to {source}", "color": "green",
                    "details": [("NTP Source", source)]}
        return {"status": "Unknown", "color": "amber", "details": [("NTP", "No source found")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

# Defender exclusions
def check_defender_exclusions() -> Dict[str, Any]:
    try:
        p = len(_get_mp_pref_value("ExclusionPath") or [])
        r = len(_get_mp_pref_value("ExclusionProcess") or [])
        e = len(_get_mp_pref_value("ExclusionExtension") or [])
        total = p + r + e
        color = "green" if total == 0 else ("amber" if total <= 5 else "red")
        return {"status": f"{total} exclusions", "color": color,
                "details": [("Paths", str(p)), ("Processes", str(r)), ("Extensions", str(e))]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

# Threat actions
def _threat_label(v):
    return {0: "Default", 1: "Clean", 2: "Quarantine", 3: "Remove", 6: "Allow", 8: "UserDefined", 9: "NoAction", 10: "Block"}.get(v, f"Unknown ({v})")

def _threat_check(level_name: str, pref: str):
    try:
        v = _get_mp_pref_value(pref)
        lbl = _threat_label(v) if v is not None else "Unknown"
        color = "red" if v in (0, 6, 9) else "green"
        return {"status": lbl, "color": color,
                "details": [(f"{level_name} Threat Action", lbl)], "enabled": v is not None and v not in (0, 6, 9)}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

check_defender_threat_low = lambda: _threat_check("Low", "LowThreatDefaultAction")
check_defender_threat_moderate = lambda: _threat_check("Moderate", "ModerateThreatDefaultAction")
check_defender_threat_high = lambda: _threat_check("High", "HighThreatDefaultAction")
check_defender_threat_severe = lambda: _threat_check("Severe", "SevereThreatDefaultAction")

# Toggle: set threat actions
def _toggle_threat(pref: str, level: int, label: str) -> Dict[str, Any]:
    before = _get_mp_pref_value(pref)
    result = _set_mp_pref(pref, level, label)
    result["before_value"] = before
    result["after_value"] = level
    result["action"] = f"set_{label.lower().replace(' ','_')}"
    return result

set_defender_threat_low = lambda l: _toggle_threat("LowThreatDefaultAction", l, "Low threat action")
set_defender_threat_moderate = lambda l: _toggle_threat("ModerateThreatDefaultAction", l, "Moderate threat action")
set_defender_threat_high = lambda l: _toggle_threat("HighThreatDefaultAction", l, "High threat action")
set_defender_threat_severe = lambda l: _toggle_threat("SevereThreatDefaultAction", l, "Severe threat action")

# More Defender toggles
def set_defender_scan_only_idle(enabled: bool) -> Dict[str, Any]:
    before = _get_mp_pref_value("ScanOnlyIfIdle")
    result = _set_mp_pref("ScanOnlyIfIdle", 1 if enabled else 0, "Scan only if idle")
    result["before_value"] = before
    result["after_value"] = 1 if enabled else 0
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_restore_point(enabled: bool) -> Dict[str, Any]:
    before = _get_mp_pref_value("DisableRestorePoint")
    result = _set_mp_pref("DisableRestorePoint", 0 if enabled else 1, "Restore point before scan")
    result["before_value"] = before
    result["after_value"] = 0 if enabled else 1
    result["action"] = "enable" if enabled else "disable"
    return result

def set_defender_intrusion_prevention(enabled: bool) -> Dict[str, Any]:
    before = _get_mp_pref_value("DisableIntrusionPreventionSystem")
    result = _set_mp_pref("DisableIntrusionPreventionSystem", 0 if enabled else 1, "Intrusion prevention")
    result["before_value"] = before
    result["after_value"] = 0 if enabled else 1
    result["action"] = "enable" if enabled else "disable"
    return result

# Screen saver toggles
def set_screensaver_secure(enabled: bool) -> Dict[str, Any]:
    before = _reg_read(r"HKCU\Control Panel\Desktop", "ScreenSaverIsSecure", "REG_SZ")
    ok = _reg_write(r"HKCU\Control Panel\Desktop", "ScreenSaverIsSecure", "1" if enabled else "0", "REG_SZ")
    return {"success": ok, "message": f"Screen saver lock {'enabled' if enabled else 'disabled'}",
            "before_value": before, "after_value": "1" if enabled else "0",
            "action": "enable" if enabled else "disable"}

def set_last_username_hidden(enabled: bool) -> Dict[str, Any]:
    before = _reg_read(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "DontDisplayLastUserName")
    ok = _reg_write(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "DontDisplayLastUserName", 1 if enabled else 0)
    return {"success": ok, "message": f"Last username {'hidden' if enabled else 'shown'}",
            "before_value": before, "after_value": 1 if enabled else 0,
            "action": "enable" if enabled else "disable"}

# Log size checks
def check_security_log_size() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("(Get-WinEvent -ListLog Security).MaximumSizeInBytes / 1MB", timeout=15)
        mb = float(out.strip()) if out else 0
        color = "green" if mb >= 128 else ("amber" if mb >= 64 else "red")
        return {"status": f"{mb:.0f} MB", "color": color, "details": [("Security Log Max Size", f"{mb:.0f} MB")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}

def check_system_log_size() -> Dict[str, Any]:
    try:
        rc, out, _ = _ps("(Get-WinEvent -ListLog System).MaximumSizeInBytes / 1MB", timeout=15)
        mb = float(out.strip()) if out else 0
        return {"status": f"{mb:.0f} MB", "color": "green" if mb >= 64 else "amber",
                "details": [("System Log Max Size", f"{mb:.0f} MB")]}
    except Exception:
        return {"status": "Error", "color": "amber", "details": []}


# ═══════════════════════════════════════════════════════════════════════════════
# CPU VULNERABILITY MITIGATIONS — Spectre, Meltdown, all known variants
# Uses Get-SpeculationControlSettings if available, else registry fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _get_speculation_data() -> Dict[str, Any]:
    """Get SpeculationControl data — downloads module if needed."""
    try:
        rc, out, _ = _ps(
            "if (-not (Get-Command Get-SpeculationControlSettings -ErrorAction SilentlyContinue)) {"
            " $url='https://raw.githubusercontent.com/microsoft/SpeculationControl/master/SpeculationControl.psm1';"
            " $dir=\"$env:USERPROFILE\\Documents\\WindowsPowerShell\\Modules\\SpeculationControl\";"
            " New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null;"
            " Invoke-WebRequest -Uri $url -OutFile \"$dir\\SpeculationControl.psm1\" -ErrorAction SilentlyContinue | Out-Null } ;"
            " if (Get-Command Get-SpeculationControlSettings -ErrorAction SilentlyContinue) {"
            " Import-Module SpeculationControl -Force -ErrorAction SilentlyContinue | Out-Null;"
            " Get-SpeculationControlSettings | ConvertTo-Json -Compress } else { 'MODULE_UNAVAILABLE' }",
            timeout=60)
        if rc == 0 and out and out != "MODULE_UNAVAILABLE":
            return json.loads(out)
    except Exception:
        logger.warning("Get-SpeculationControlSettings failed, using registry fallback", exc_info=True)
    return {"source": "registry_fallback"}


def check_spectre_v2() -> Dict[str, Any]:
    """Spectre v2 / BTI (CVE-2017-5715)."""
    try:
        d = _get_speculation_data()
        hw = d.get("BTIHardwarePresent", False)
        os_ok = d.get("BTIWindowsSupportEnabled", False) or d.get("BTIWindowsSupportPresent", False)
        retpoline = d.get("BTIKernelRetpolineEnabled", False)
        enabled = hw and os_ok
        status = "Mitigated" if enabled else ("Hardware OK but OS off" if hw else "Not mitigated")
        color = "green" if enabled else "red" if hw else "amber"
        return {"status": status, "color": color,
                "details": [("BTI Hardware", "Present" if hw else "N/A"),
                            ("BTI OS Support", "Enabled" if os_ok else "Disabled"),
                            ("Retpoline", "Enabled" if retpoline else "N/A")], "enabled": enabled}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Spectre v2", "Check failed")]}

def check_meltdown() -> Dict[str, Any]:
    """Meltdown (CVE-2017-5754)."""
    try:
        d = _get_speculation_data()
        hw_vuln = d.get("RdclHardwareProtectedReported") and not d.get("RdclHardwareProtected", True)
        kva_present = d.get("KVAShadowWindowsSupportPresent", False)
        kva_enabled = d.get("KVAShadowWindowsSupportEnabled", False)
        kva_required = d.get("KVAShadowRequired", False)
        enabled = kva_present and kva_enabled
        if not hw_vuln and not kva_required:
            return {"status": "Not vulnerable (HW)", "color": "green",
                    "details": [("Hardware", "Not vulnerable to Meltdown")], "enabled": True}
        status = "Mitigated (KPTI on)" if kva_enabled else ("Vulnerable (KPTI off)" if hw_vuln else "Unknown")
        color = "green" if kva_enabled or not hw_vuln else "red"
        return {"status": status, "color": color,
                "details": [("Hardware Vulnerable", str(hw_vuln)), ("KVA Shadow", "On" if kva_enabled else "Off"),
                            ("KVA Required", str(kva_required))], "enabled": not hw_vuln or kva_enabled}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Meltdown", "Check failed")]}

def check_l1tf() -> Dict[str, Any]:
    """L1TF/Foreshadow (CVE-2018-3615, -3620, -3646)."""
    try:
        d = _get_speculation_data()
        hw_vuln = d.get("L1TFHardwareVulnerable", True)
        os_present = d.get("L1TFWindowsSupportPresent", False)
        os_enabled = d.get("L1TFWindowsSupportEnabled", False)
        if not hw_vuln:
            return {"status": "Not vulnerable (HW)", "color": "green",
                    "details": [("Hardware", "Not vulnerable to L1TF")], "enabled": True}
        enabled = os_present and os_enabled
        return {"status": "Mitigated" if enabled else "Vulnerable",
                "color": "green" if enabled else "red",
                "details": [("OS Support", "Present" if os_present else "N/A"),
                            ("OS Enabled", "Yes" if os_enabled else "No")], "enabled": enabled}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("L1TF", "Check failed")]}

def check_mds() -> Dict[str, Any]:
    """MDS/Zombieload (CVE-2018-12126/127/130, CVE-2019-11091)."""
    try:
        d = _get_speculation_data()
        hw_vuln = d.get("MDSHardwareVulnerable", True)
        os_present = d.get("MDSWindowsSupportPresent", False)
        if not hw_vuln:
            return {"status": "Not vulnerable (HW)", "color": "green",
                    "details": [("Hardware", "Not vulnerable to MDS")], "enabled": True}
        return {"status": "Mitigated" if os_present else "Vulnerable (no OS support)",
                "color": "green" if os_present else "red",
                "details": [("OS MDS Support", "Present" if os_present else "Absent")], "enabled": os_present}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("MDS", "Check failed")]}

def check_ssbd() -> Dict[str, Any]:
    """Spectre v4 / SSBD (CVE-2018-3639)."""
    try:
        d = _get_speculation_data()
        hw_present = d.get("SSBDHardwarePresent", False)
        os_present = d.get("SSBDWindowsSupportPresent", False)
        sys_enabled = d.get("SSBDWindowsSupportEnabledSystemWide", False)
        enabled = hw_present and os_present and sys_enabled
        status = "System-wide enabled" if enabled else ("HW/OS present, not enabled" if hw_present else "N/A")
        color = "green" if enabled else ("amber" if hw_present else "amber")
        return {"status": status, "color": color,
                "details": [("HW Support", str(hw_present)), ("OS Support", str(os_present)),
                            ("System-Wide", "Yes" if sys_enabled else "No")], "enabled": enabled}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("SSBD/Spectre v4", "Check failed")]}

def check_swapgs() -> Dict[str, Any]:
    """SWAPGS (CVE-2019-1125)."""
    try:
        d = _get_speculation_data()
        bhb = d.get("BhbEnabled", False) or d.get("BhbDisabledSystemPolicy") is False
        return {"status": "Mitigated" if bhb else "N/A", "color": "green" if bhb else "amber",
                "details": [("BHB Mitigation", "Enabled" if bhb else "N/A")]}
    except Exception:
        return {"status": "N/A", "color": "amber", "details": [("SWAPGS", "Check failed")]}

def check_tsx_async_abort() -> Dict[str, Any]:
    """TSX Async Abort / TAA (CVE-2019-11135) — checked via MDS/SBDR/FBSDP."""
    try:
        d = _get_speculation_data()
        ok = not d.get("SBDRSSDPHardwareVulnerable", True) and not d.get("FBSDPHardwareVulnerable", True)
        return {"status": "Mitigated (HW immune)" if ok else "Unknown", "color": "green" if ok else "amber",
                "details": [("SBDR HW Vulnerable", str(d.get("SBDRSSDPHardwareVulnerable", "?"))),
                            ("FBSDP HW Vulnerable", str(d.get("FBSDPHardwareVulnerable", "?")))]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("TAA", "Check failed")]}

def check_srbds() -> Dict[str, Any]:
    """SRBDS/CrossTalk (CVE-2020-0543) — checked via SBDR."""
    try:
        d = _get_speculation_data()
        ok = not d.get("SBDRSSDPHardwareVulnerable", True)
        return {"status": "Not vulnerable (HW)" if ok else "Unknown", "color": "green" if ok else "amber",
                "details": [("SBDR HW", "Immune" if ok else "Unknown")]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("SRBDS", "Check failed")]}

def check_retbleed() -> Dict[str, Any]:
    """Retbleed (CVE-2022-29900/29901)."""
    try:
        d = _get_speculation_data()
        branch_ok = d.get("BranchConfusionStatus", "").upper() == "SYSTEM_SPECULATION_CONTROL_BRANCH_CONFUSION_HARDWARE_IMMUNE"
        retpoline = d.get("BTIKernelRetpolineEnabled", False)
        cured = branch_ok or retpoline
        return {"status": "Mitigated" if cured else "Unknown", "color": "green" if cured else "amber",
                "details": [("Branch Confusion", "HW Immune" if branch_ok else "Unknown"),
                            ("Retpoline", "On" if retpoline else "Off")]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Retbleed", "Check failed")]}

def check_mmio_stale_data() -> Dict[str, Any]:
    """MMIO Stale Data (CVE-2022-21123/125/127/166) — checked via FBClear."""
    try:
        d = _get_speculation_data()
        ok = d.get("FBClearWindowsSupportPresent", False)
        return {"status": "Mitigated" if ok else "N/A", "color": "green" if ok else "amber",
                "details": [("Fill Buffer Clear", "Present" if ok else "N/A")]}
    except Exception:
        return {"status": "N/A", "color": "amber", "details": [("MMIO", "Check failed")]}

def check_downfall_gds() -> Dict[str, Any]:
    """Downfall / GDS (CVE-2022-40982)."""
    try:
        d = _get_speculation_data()
        status = d.get("GdsStatus", "")
        immune = "HARDWARE_IMMUNE" in str(status).upper()
        return {"status": "Not vulnerable (HW immune)" if immune else status,
                "color": "green" if immune else "amber",
                "details": [("GDS Status", str(status))]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Downfall", "Check failed")]}

def check_zenbleed() -> Dict[str, Any]:
    """Zenbleed (CVE-2023-20593) — AMD Zen 2."""
    try:
        d = _get_speculation_data()
        div_by_zero = str(d.get("DivideByZeroStatus", "")).upper()
        mitigated = "MITIGATED" in div_by_zero
        return {"status": "Mitigated" if mitigated else "Unknown",
                "color": "green" if mitigated else "amber",
                "details": [("Divide by Zero", str(d.get("DivideByZeroStatus", "N/A")))]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Zenbleed", "N/A")]}

def check_inception() -> Dict[str, Any]:
    """Inception (CVE-2023-20569) — AMD Zen 3/4, checked via SRSO."""
    try:
        d = _get_speculation_data()
        srso = str(d.get("SrsoStatus", "")).upper()
        mitigated = "MITIGATION" in srso or "IMMUNE" in srso
        return {"status": "Mitigated" if mitigated else "Disabled",
                "color": "green" if mitigated else "amber",
                "details": [("SRSO Status", str(d.get("SrsoStatus", "N/A")))]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("Inception", "N/A")]}

def check_rfds() -> Dict[str, Any]:
    """RFDS (CVE-2023-28746) — Register File Data Sampling (Atom)."""
    try:
        d = _get_speculation_data()
        status = str(d.get("RfdsStatus", "")).upper()
        immune = "IMMUNE" in status
        return {"status": "Not vulnerable (HW immune)" if immune else "Unknown",
                "color": "green" if immune else "amber",
                "details": [("RFDS Status", str(d.get("RfdsStatus", "N/A")))]}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("RFDS", "N/A")]}


# ═══════════════════════════════════════════════════════════════════════════════
# TOP WINDOWS 11 CVE MITIGATION CHECKS (PrintNightmare, Zerologon, etc.)
# ═══════════════════════════════════════════════════════════════════════════════

def check_printnightmare() -> Dict[str, Any]:
    """PrintNightmare (CVE-2021-34527, CVE-2021-36958)."""
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PointAndPrint"
    restrict = _reg_read(key, "RestrictDriverInstallationToAdministrators")
    no_warn = _reg_read(key, "NoWarningNoElevationOnInstall")
    update_pr = _reg_read(key, "UpdatePromptSettings")
    protected = restrict == 1
    details = [
        ("Restrict Drivers to Admins", "Yes" if protected else "No (vulnerable)"),
        ("No Warning on Install", "Disabled" if no_warn == 0 else "Enabled" if no_warn == 1 else "Not set"),
        ("Update Prompt", "On" if update_pr == 1 else "Off" if update_pr == 0 else "Not set"),
    ]
    return {"status": "Mitigated" if protected else "Not Mitigated",
            "color": "green" if protected else "red",
            "details": details, "enabled": protected}

def check_zerologon() -> Dict[str, Any]:
    """Zerologon (CVE-2020-1472) — Netlogon secure channel."""
    key = r"HKLM\SYSTEM\CurrentControlSet\Services\Netlogon\Parameters"
    full_secure = _reg_read(key, "FullSecureChannelProtection")
    seal_secure = _reg_read(key, "SealSecureChannel")
    sign_secure = _reg_read(key, "SignSecureChannel")
    protected = full_secure == 1
    details = [
        ("Full Secure Channel", "On" if full_secure == 1 else "Off" if full_secure == 0 else "Not set"),
        ("Seal Secure", "Yes" if seal_secure == 1 else "No" if seal_secure == 0 else "Not set"),
        ("Sign Secure", "Yes" if sign_secure == 1 else "No" if sign_secure == 0 else "Not set"),
    ]
    return {"status": "Mitigated" if protected else "Not Mitigated",
            "color": "green" if protected else "red",
            "details": details, "enabled": protected}

def check_petitpotam() -> Dict[str, Any]:
    """PetitPotam (CVE-2021-36942) — NTLM relay via EPA."""
    wk_key = r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters"
    sv_key = r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters"
    wk_epa = _reg_read(wk_key, "RequireExtendedProtection")
    sv_epa = _reg_read(sv_key, "RequireExtendedProtection")
    protected = (wk_epa == 1) or (sv_epa == 1)
    details = [
        ("Workstation EPA", "On" if wk_epa == 1 else "Off" if wk_epa == 0 else "Not set"),
        ("Server EPA", "On" if sv_epa == 1 else "Off" if sv_epa == 0 else "Not set"),
    ]
    return {"status": "Mitigated" if protected else "Not Mitigated",
            "color": "green" if protected else "red",
            "details": details, "enabled": protected}

def check_follina() -> Dict[str, Any]:
    """Follina (CVE-2022-30190) — MSDT URL protocol."""
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\ScriptedDiagnosticsProvider\Policy"
    disabled = _reg_read(key, "DisableQueryRemoteServer")
    protected = disabled == 1
    return {"status": "Protected" if protected else "Not Protected",
            "color": "green" if protected else "red",
            "details": [("MSDT Remote Query", "Disabled" if disabled == 1 else "Enabled" if disabled == 0 else "Not set")],
            "enabled": protected}

def check_blacklotus() -> Dict[str, Any]:
    """BlackLotus (CVE-2023-24932) — Secure Boot bypass."""
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\SecureBoot"
    updates = _reg_read(key, "AvailableUpdates")
    applied = _reg_read(key, "AppliedUpdates")
    details = [("Available Updates", f"0x{updates:X}" if updates else "None"),
               ("Applied Updates", f"0x{applied:X}" if applied else "None")]
    ok = (updates is not None and applied is not None and applied >= updates) or (applied and applied > 0)
    return {"status": "Patched" if ok else "May need updates",
            "color": "green" if ok else "amber",
            "details": details, "enabled": ok}

def check_kerberos_armoring() -> Dict[str, Any]:
    """Kerberos PAC armoring (CVE-2022-33679, CVE-2022-33647)."""
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa\Kerberos\Parameters"
    pac = _reg_read(key, "KrbtgtFullPacSignature")
    details = [("Full PAC Signature", "On" if pac == 1 else "Off" if pac == 0 else "Not set")]
    return {"status": "ARMORED" if pac == 1 else "Not Armored",
            "color": "green" if pac == 1 else "amber",
            "details": details, "enabled": pac == 1}

def check_credential_guard_vbs() -> Dict[str, Any]:
    """VBS-based Credential Guard (CVE-2022-22047, CVE-2021-36934)."""
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard"
    vbs = _reg_read(key, "EnableVirtualizationBasedSecurity")
    req = _reg_read(key, "RequirePlatformSecurityFeatures")
    details = [("VBS Enabled", "Yes" if vbs == 1 else "No" if vbs == 0 else "Not configured"),
               ("Platform Security", "Required" if req and req > 0 else "Not required")]
    return {"status": "VBS Active" if vbs == 1 else "VBS Off",
            "color": "green" if vbs == 1 else "red",
            "details": details, "enabled": vbs == 1}

def check_smb_ghost() -> Dict[str, Any]:
    """SMBGhost (CVE-2020-0796) — SMBv3 compression RCE."""
    try:
        rc, out, _ = _ps("Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\LanmanServer\\Parameters' "
                          "-Name SMB1 -ErrorAction SilentlyContinue | Select -ExpandProperty SMB1", timeout=10)
        smb1 = int(out.strip()) if out and out.strip().isdigit() else None
        return {"status": "SMBv1 Disabled (safe)" if smb1 == 0 else "SMBv1 Enabled" if smb1 == 1 else "Unknown",
                "color": "green" if smb1 == 0 else ("red" if smb1 == 1 else "amber"),
                "details": [("SMBv1", "Disabled" if smb1 == 0 else "Enabled" if smb1 == 1 else "Not configured")],
                "enabled": smb1 == 0}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("SMBGhost", "Check failed")]}

def check_sam_hive_permissions() -> Dict[str, Any]:
    """HiveNightmare (CVE-2021-36934) — SAM file readable by non-admin (Win10/11 pre-July 2021)."""
    try:
        import os
        sam_path = r"C:\Windows\System32\config\SAM"
        if not os.path.exists(sam_path):
            return {"status": "N/A", "color": "green", "details": [("SAM", "File not found")], "enabled": True}
        # Check if BUILTIN\Users has read access (simplified: check ACL)
        rc, out, _ = _ps(f"icacls '{sam_path}' 2>&1 | Select-String 'BUILTIN\\\\Users'", timeout=10)
        has_users_read = ":(R)" in out or ":(F)" in out or ":(M)" in out if out else False
        if not has_users_read:
            return {"status": "Restricted (safe)", "color": "green",
                    "details": [("SAM ACL", "BUILTIN\\Users not readable")], "enabled": True}
        return {"status": "Exposed (vulnerable)", "color": "red",
                "details": [("SAM ACL", "BUILTIN\\Users has read access!")], "enabled": False}
    except Exception:
        return {"status": "Unknown", "color": "amber", "details": [("HiveNightmare", "Check failed")]}

def check_ntlm_relay_protection() -> Dict[str, Any]:
    """NTLM relay attack mitigations (PetitPotam, DFSCoerce, etc.)."""
    key = r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa\MSV1_0"
    restrict_out = _reg_read(key, "RestrictSendingNTLMTraffic")
    restrict_in = _reg_read(key, "RestrictReceivingNTLMTraffic")
    details = [
        ("Outgoing NTLM Restricted", "Yes" if restrict_out == 2 else "Partial" if restrict_out == 1 else "No"),
        ("Incoming NTLM Restricted", "Yes" if restrict_in == 2 else "Partial" if restrict_in == 1 else "No"),
    ]
    ok = restrict_out == 2 and restrict_in == 2
    return {"status": "Hardened" if ok else "Not Hardened",
            "color": "green" if ok else "amber",
            "details": details, "enabled": ok}

def check_windows_defender_cve_mitigations() -> Dict[str, Any]:
    """Aggregate check: all major Win10/11 CVEs."""
    checks = [
        ("Spectre v2", check_spectre_v2), ("Meltdown", check_meltdown),
        ("L1TF/Foreshadow", check_l1tf), ("MDS/Zombieload", check_mds),
        ("Spectre v4/SSBD", check_ssbd), ("PrintNightmare", check_printnightmare),
        ("Zerologon", check_zerologon), ("PetitPotam", check_petitpotam),
        ("Follina", check_follina), ("BlackLotus", check_blacklotus),
        ("Kerberos Armoring", check_kerberos_armoring), ("Credential Guard", check_credential_guard_vbs),
        ("SMB Ghost", check_smb_ghost), ("HiveNightmare", check_sam_hive_permissions),
        ("NTLM Relay", check_ntlm_relay_protection), ("SWAPGS", check_swapgs),
        ("TSX Abort", check_tsx_async_abort), ("SRBDS", check_srbds),
        ("Retbleed", check_retbleed), ("MMIO Stale", check_mmio_stale_data),
        ("Downfall/GDS", check_downfall_gds), ("Zenbleed", check_zenbleed),
        ("Inception", check_inception), ("RFDS", check_rfds),
    ]
    mitigated, vulnerable, na = 0, 0, 0
    details = []
    for name, fn in checks:
        try:
            r = fn()
            s = r.get("status", "")
            if "Mitigated" in s or "Protected" in s or "Patched" in s or "Hardened" in s or "Not vulnerable" in s or "ARMORED" in s or "VBS Active" in s or "N/A" in s or "Restricted" in s or "Disabled (safe)" in s:
                mitigated += 1
                details.append((name, s[:50]))
            else:
                vulnerable += 1
                details.append((name, f"CHECK: {s[:40]}"))
        except Exception:
            na += 1
    if vulnerable > 0:
        color, overall = "red", f"{vulnerable} issue(s) need attention"
    elif na > 0:
        color, overall = "amber", f"{mitigated} OK, {na} unknown"
    else:
        color, overall = "green", f"All {mitigated} mitigations active"
    return {"status": overall, "color": color, "details": details[:15]}
