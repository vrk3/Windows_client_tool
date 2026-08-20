"""Cleanup scanners: cloud category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
)

logger = logging.getLogger(__name__)

def scan_onedrive_logs(min_age_days: int = 0) -> ScanResult:
    """OneDrive sync logs under %LOCALAPPDATA%\\Microsoft\\OneDrive\\logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    log_dir = os.path.join(local, r"Microsoft\OneDrive\logs")
    if not os.path.isdir(log_dir):
        return result
    for f in glob.glob(os.path.join(log_dir, "*.log")):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_dropbox_cache(min_age_days: int = 0) -> ScanResult:
    """Dropbox cache, cache.db, and blob metadata — keeps account data intact."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Dropbox\cache"),
        os.path.join(local, r"Dropbox\blob_store"),
        os.path.join(local, r"Dropbox\instance1"),
        os.path.join(appdata, r"Dropbox\cache"),
        os.path.join(appdata, r"Dropbox\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_google_drive_cache(min_age_days: int = 0) -> ScanResult:
    """Google Drive File Stream and Backup and Sync cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Google\DriveFS"),
        os.path.join(local, r"Google\Backup and Sync"),
        os.path.join(local, r"Google\DriveFS\Cache"),
        os.path.join(local, r"Google\DriveFS\Logs"),
        os.path.join(appdata, r"Google\DriveFS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mega_cache(min_age_days: int = 0) -> ScanResult:
    """MEGAsync cache, temp files, and sync database."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"MEGA Limited\MEGAsync\temp"),
        os.path.join(local, r"MEGA Limited\MEGAsync\logs"),
        os.path.join(appdata, r"MEGAsync\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_pcloud_cache(min_age_days: int = 0) -> ScanResult:
    """pCloud cache and temp sync data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"pCloud\Cache"),
        os.path.join(local, r"pCloud\temp"),
        os.path.join(local, r"pCloud\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_icloud_cache(min_age_days: int = 0) -> ScanResult:
    """iCloud for Windows cache and download staging. NOT cookies or accounts."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Apple Computer\iCloud\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_box_cache(min_age_days: int = 0) -> ScanResult:
    """Box Drive cache and sync staging data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Box\Box\cache"),
        os.path.join(local, r"Box\Box\data"),
        os.path.join(local, r"Box\Box\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_tresorit_cache(min_age_days: int = 0) -> ScanResult:
    """Tresorit sync cache and temp files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Tresorit\Cache"),
        os.path.join(appdata, r"Tresorit\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_onedrive_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive known folder mask and sync conflict files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_virtualbox_cache(min_age_days: int = 0) -> ScanResult:
    """VirtualBox hard disk images (.vdi/.vhd), snapshots, and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"VirtualBox"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"VirtualBox VMs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_sharepoint_cache(min_age_days: int = 0) -> ScanResult:
    """SharePoint/OneDrive sync client Known folder mask and local cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Office\OfficeFileCache"),
        os.path.join(local, r"Microsoft\Office\OfficeFileCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_onedrive_full_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive sync conflict files, redirected folder cache, and thumbnail staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
        os.path.join(local, r"Microsoft\OneDrive\ACSBackup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_openvpn_cache(min_age_days: int = 0) -> ScanResult:
    """OpenVPN client logs, script temp, and unifiedpushtoken cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"OpenVPN"),
        os.path.join(appdata, r"OpenVPN Connect"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_wireguard_cache(min_age_days: int = 0) -> ScanResult:
    """WireGuard interface logs and adapter state cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"WireGuard"),
        os.path.join(local, r"WireGuard"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_nordvpn_cache(min_age_days: int = 0) -> ScanResult:
    """NordVPN connection logs and settings cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"NordVPN"),
        os.path.join(appdata, r"Roaming\ClientConfig"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_expressvpn_cache(min_age_days: int = 0) -> ScanResult:
    """ExpressVPN diagnostic logs and split-tunneling config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"ExpressVPN"),
        os.path.join(appdata, r"ExpressVPN Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_aws_cli_cache(min_age_days: int = 0) -> ScanResult:
    """AWS CLI cache, config, and SSM session cache. NOT credentials file."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".aws\cli\cache"),
        os.path.join(home, r".aws\sso\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_azure_cli_cache(min_age_days: int = 0) -> ScanResult:
    """Azure CLI access token cache, cloud shell, and arm cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".azure"),
        os.path.join(home, r".cloudshell"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_gcp_sdk_cache(min_age_days: int = 0) -> ScanResult:
    """Google Cloud SDK credentials, bq cache, and gcloud config."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"AppData\Roaming\gcloud"),
        os.path.join(home, r"AppData\Local\gcloud"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_aws_toolkit_cache(min_age_days: int = 0) -> ScanResult:
    """AWS Toolkit for VS Code cache and SAM CLI build cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"AWStoolkit"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_onedrive_commercial_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive for Business (MSOnline) sync conflict logs and local cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
        os.path.join(local, r"Microsoft\OneDrive\ACSBackup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_sharepoint_desktop_cache(min_age_days: int = 0) -> ScanResult:
    """SharePoint Designer workflow cache and Office document cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Office\OfficeFileCache"),
        os.path.join(local, r"Microsoft\Office\OfficeFileCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_windows_sandbox_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Sandbox base image staging and writable layer cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.Windows.Sandbox_*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_heroku_cli_cache(min_age_days: int = 0) -> ScanResult:
    """Heroku CLI config, plugins, and run dyno logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Heroku")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_vercel_cache(min_age_days: int = 0) -> ScanResult:
    """Vercel CLI build output and now dev server cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"vercel")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_netlify_cache(min_age_days: int = 0) -> ScanResult:
    """Netlify CLI deploy cache and functions build output."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"netlify")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_supabase_cache(min_age_days: int = 0) -> ScanResult:
    """Supabase CLI local dev data and migration staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Supabase")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_firebase_cache(min_age_days: int = 0) -> ScanResult:
    """Firebase CLI token cache and emulator local data staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"firebase")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_planetscale_cache(min_age_days: int = 0) -> ScanResult:
    """Planetscale CLI branch data and query result staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"planetscale")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_stripe_cache(min_age_days: int = 0) -> ScanResult:
    """Stripe CLI logs and webhook event staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"stripe")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_ngrok_cache(min_age_days: int = 0) -> ScanResult:
    """ngrok tunnel session logs and authtoken cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"ngrok")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_cloudflare_warp_cache(min_age_days: int = 0) -> ScanResult:
    """Cloudflare WARP client logs and WireGuard config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Cloudflare")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mullvad_cache(min_age_days: int = 0) -> ScanResult:
    """Mullvad VPN tunnel logs and exit node config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Mullvad VPN")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_ipvanish_cache(min_age_days: int = 0) -> ScanResult:
    """IPVanish VPN client logs and connection profile cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"IPVanish")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scanPIA_vpn_cache(min_age_days: int = 0) -> ScanResult:
    """Private Internet Access VPN cache and connection diagnostic logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"pia")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_tailscale_cache(min_age_days: int = 0) -> ScanResult:
    """Tailscale SSH session logs and subnet router cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Tailscale")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_wg_easy_cache(min_age_days: int = 0) -> ScanResult:
    """WireGuard Easy config backups and peer connection staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"wg-easy")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_metamask_cache(min_age_days: int = 0) -> ScanResult:
    """MetaMask extension cache, vault data, and provider cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"MetaMask"),
        os.path.join(local, r"MetaMask"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_coinbase_cache(min_age_days: int = 0) -> ScanResult:
    """Coinbase wallet extension cache and tx relay data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Coinbase Wallet")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = ['scanPIA_vpn_cache', 'scan_aws_cli_cache', 'scan_aws_toolkit_cache', 'scan_azure_cli_cache', 'scan_box_cache', 'scan_cloudflare_warp_cache', 'scan_coinbase_cache', 'scan_dropbox_cache', 'scan_expressvpn_cache', 'scan_firebase_cache', 'scan_gcp_sdk_cache', 'scan_google_drive_cache', 'scan_heroku_cli_cache', 'scan_icloud_cache', 'scan_ipvanish_cache', 'scan_mega_cache', 'scan_metamask_cache', 'scan_mullvad_cache', 'scan_netlify_cache', 'scan_ngrok_cache', 'scan_nordvpn_cache', 'scan_onedrive_cache', 'scan_onedrive_commercial_cache', 'scan_onedrive_full_cache', 'scan_onedrive_logs', 'scan_openvpn_cache', 'scan_pcloud_cache', 'scan_planetscale_cache', 'scan_sharepoint_cache', 'scan_sharepoint_desktop_cache', 'scan_stripe_cache', 'scan_supabase_cache', 'scan_tailscale_cache', 'scan_tresorit_cache', 'scan_vercel_cache', 'scan_virtualbox_cache', 'scan_wg_easy_cache', 'scan_windows_sandbox_cache', 'scan_wireguard_cache']
