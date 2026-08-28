# Runs tools/security_catalog_probe.py elevated and redirects its own output,
# because Start-Process -Verb RunAs cannot redirect for the caller.
#
# READ-ONLY. The probe calls Get-* cmdlets and reads registry values; it writes
# nothing to this machine except the two files named below.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$json = Join-Path $repo 'tools\_probe_elevated.json'
# (evidence is copied into .superpowers/sdd/ after each run)
$log  = Join-Path $repo 'tools\_probe_elevated.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\security_catalog_probe.py' $json *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
