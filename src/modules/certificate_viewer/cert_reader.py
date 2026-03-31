import base64
import datetime
import json
import subprocess
from dataclasses import dataclass
from typing import List


@dataclass
class CertInfo:
    subject_cn: str
    subject_full: str
    issuer: str
    expiry: datetime.datetime
    thumbprint: str        # hex string
    key_usage: str
    has_private_key: bool
    raw_der: bytes         # raw certificate bytes for export
    days_until_expiry: int
    flag: str              # "" | "🔴 Expired" | "🟠 Expiring Soon"


_STORE_PATHS = {
    ("MY",               "user"):    r"Cert:\CurrentUser\My",
    ("ROOT",             "user"):    r"Cert:\CurrentUser\Root",
    ("CA",               "user"):   r"Cert:\CurrentUser\CA",
    ("TrustedPublisher", "user"):   r"Cert:\CurrentUser\TrustedPublisher",
    ("MY",               "machine"): r"Cert:\LocalMachine\My",
    ("ROOT",             "machine"): r"Cert:\LocalMachine\Root",
    ("CA",               "machine"): r"Cert:\LocalMachine\CA",
    ("TrustedPublisher", "machine"): r"Cert:\LocalMachine\TrustedPublisher",
}


def fetch_certs(store_name: str, store_location: str = "user") -> List[CertInfo]:
    """Load certificates from a Windows certificate store using PowerShell."""
    store_path = _STORE_PATHS.get(
        (store_name, store_location),
        rf"Cert:\CurrentUser\{store_name}",
    )

    ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
$certs = Get-ChildItem -Path '{store_path}'
if (-not $certs) {{ Write-Output '[]'; exit 0 }}
$result = @()
foreach ($cert in $certs) {{
    $cnMatch = [regex]::Match($cert.Subject, 'CN=([^,]+)')
    $cn = if ($cnMatch.Success) {{ $cnMatch.Groups[1].Value.Trim() }} else {{ $cert.Subject }}
    $issuerMatch = [regex]::Match($cert.Issuer, 'CN=([^,]+)')
    $issuer = if ($issuerMatch.Success) {{ $issuerMatch.Groups[1].Value.Trim() }} else {{ $cert.Issuer }}
    $keyUsage = 'N/A'
    $ext = $cert.Extensions | Where-Object {{ $_.Oid.FriendlyName -eq 'Key Usage' }}
    if ($ext) {{ $keyUsage = $ext.Format($false) }}
    try {{
        $derB64 = [Convert]::ToBase64String(
            $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
        )
    }} catch {{ $derB64 = '' }}
    $result += [PSCustomObject]@{{
        SubjectCN     = $cn
        SubjectFull   = $cert.Subject
        Issuer        = $issuer
        Expiry        = $cert.NotAfter.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
        Thumbprint    = $cert.Thumbprint
        KeyUsage      = $keyUsage
        HasPrivateKey = [bool]$cert.HasPrivateKey
        DerBase64     = $derB64
    }}
}}
if ($result.Count -eq 0) {{ Write-Output '[]'; exit 0 }}
$result | ConvertTo-Json -Depth 3 -Compress
"""

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=60,
        )
        raw = proc.stdout.strip()
        if not raw or raw == "[]":
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []

    today = datetime.datetime.utcnow()
    certs: List[CertInfo] = []
    for item in data:
        try:
            expiry = datetime.datetime.strptime(item["Expiry"], "%Y-%m-%d %H:%M:%S")
            days = (expiry - today).days
            flag = ""
            if days < 0:
                flag = "🔴 Expired"
            elif days <= 30:
                flag = "🟠 Expiring Soon"
            raw_der = base64.b64decode(item.get("DerBase64") or "")
            certs.append(CertInfo(
                subject_cn=item.get("SubjectCN") or "",
                subject_full=item.get("SubjectFull") or "",
                issuer=item.get("Issuer") or "",
                expiry=expiry,
                thumbprint=item.get("Thumbprint") or "",
                key_usage=item.get("KeyUsage") or "N/A",
                has_private_key=bool(item.get("HasPrivateKey", False)),
                raw_der=raw_der,
                days_until_expiry=days,
                flag=flag,
            ))
        except Exception:
            continue
    return certs
