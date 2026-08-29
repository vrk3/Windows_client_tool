# Does a revert put the KEY back, not just the value?
#
# The 2026-08-29 round-trip left
# HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient behind with 0 values
# and 0 subkeys: the apply created it, the revert removed only the value, and
# it reported "back to exactly what it was".
#
# This removes that empty leftover (refusing if anything is in it), then runs
# the same round-trip again and reports whether the key survives it.
#
# Start-Process -Verb RunAs cannot redirect for the caller, so this redirects
# its own output to the log named below.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$log  = Join-Path $repo 'tools\_roundtrip_key_elevated.log'
$key  = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient'

$lines = @()
$lines += "elevated: " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# --- 1. clear the leftover, but only if it really is empty -----------------
if (Test-Path $key) {
    $item = Get-Item $key
    $lines += "before: key exists, values=$($item.ValueCount) subkeys=$($item.SubKeyCount)"
    if ($item.ValueCount -eq 0 -and $item.SubKeyCount -eq 0) {
        Remove-Item -Path $key -Force
        $lines += "before: removed the empty leftover -> exists=$(Test-Path $key)"
    } else {
        $lines += "before: REFUSING to remove it, something is in there"
    }
} else {
    $lines += "before: key does not exist"
}

# --- 2. the round-trip, against the current source -------------------------
Set-Location $repo
$out = & '.\.venv\Scripts\python.exe' 'tools\security_catalog_check.py' --apply llmnr 2>&1
$lines += "roundtrip exit=$LASTEXITCODE"
$lines += ($out | ForEach-Object { "    $_" })

# --- 3. what survived it ---------------------------------------------------
if (Test-Path $key) {
    $item = Get-Item $key
    $lines += "after: KEY STILL THERE, values=$($item.ValueCount) subkeys=$($item.SubKeyCount)"
} else {
    $lines += "after: key is gone -- the revert put it back the way it was"
}

$lines | Out-File -FilePath $log -Encoding utf8
