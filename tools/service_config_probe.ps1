# Runs tools/service_config_probe.py elevated and redirects its own output,
# because Start-Process -Verb RunAs cannot redirect for the caller.
#
# WRITES NOTHING: every ChangeServiceConfig call in the probe passes
# SERVICE_NO_CHANGE for every field, which asks the permission question
# without altering any service.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$log  = Join-Path $repo 'tools\_service_probe_elevated.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\service_config_probe.py' *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
