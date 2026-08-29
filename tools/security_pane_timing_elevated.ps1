# What each tab costs ELEVATED, which is how the user runs this app.
#
# Firewall & Network cost 8.8s elevated and 7.9s of it was `smbv1` building
# the optional_features snapshot -- a full DISM enumeration -- for one
# control. Unelevated timings cannot show whether moving that helped: there
# the snapshot only ever refuses.
#
# Start-Process -Verb RunAs cannot redirect for the caller, so this redirects
# its own output to the log named below.
$repo = 'C:\Users\iorda\source\repos\Windows_client_tool'
$log  = Join-Path $repo 'tools\_pane_timing_elevated.log'

Set-Location $repo
& '.\.venv\Scripts\python.exe' 'tools\security_pane_timing.py' *> $log
"exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
