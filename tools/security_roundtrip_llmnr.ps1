# Runs ONE control round-trip elevated: read, apply, verify, revert, verify.
#
# This one WRITES. It sets HKLM\SOFTWARE\Policies\Microsoft\Windows NT\
# DNSClient\EnableMulticast to 0 and then puts it back to exactly what it was,
# reading the registry value directly at every step rather than trusting the
# reader that decided in the first place. LLMNR is the lowest-risk writable
# control in the catalog: a name-resolution fallback, no reboot, no service.
#
# Start-Process -Verb RunAs cannot redirect for the caller, so this redirects
# its own output to the log named below.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$log  = Join-Path $repo 'tools\_roundtrip_elevated.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\security_catalog_check.py' --apply llmnr *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
