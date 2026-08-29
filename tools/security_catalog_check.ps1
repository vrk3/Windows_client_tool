# Runs tools/security_catalog_check.py elevated and redirects its own output,
# because Start-Process -Verb RunAs cannot redirect for the caller.
#
# READ-ONLY. The check calls Get-* cmdlets and reads registry values; it never
# presses a button (--apply is a separate opt-in and is NOT passed here). It
# writes nothing to this machine except the two files named below.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$json = Join-Path $repo 'tools\_check_elevated.json'
$log  = Join-Path $repo 'tools\_check_elevated.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\security_catalog_check.py' $json *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
