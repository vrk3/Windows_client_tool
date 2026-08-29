# Runs tools/do_roundtrip.py elevated and redirects its own output, because
# Start-Process -Verb RunAs cannot redirect for the caller.
#
# This WRITES: it applies "Disable Delivery Optimization" (a policy value,
# DODownloadMode=0), reads the registry back, then reverts through the app's
# own restore point and reads again. The machine ends as it started.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$log  = Join-Path $repo 'tools\_do_roundtrip.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\do_roundtrip.py' *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
