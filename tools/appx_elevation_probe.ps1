# Does Get-AppxPackage see the interactive user's packages when ELEVATED?
#
# READ-ONLY. No Remove-AppxPackage anywhere in here.
#
# Start-Process -Verb RunAs cannot redirect for the caller, so this redirects
# its own output to the log below.
$log = 'C:\Users\iorda\source\repos\Windows_client_tool\tools\_appx_elevated.log'
$name = 'JAMSoftware.TreeSizeContextMenu'

$lines = @()
$lines += "elevated: " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$lines += "whoami  : " + (whoami)

$all = @(Get-AppxPackage | Select-Object -ExpandProperty Name)
$lines += "Get-AppxPackage total          : $($all.Count)"

$one = @(Get-AppxPackage $name | Select-Object -ExpandProperty Name)
$lines += "Get-AppxPackage '$name' : $($one.Count) -> '$($one -join ",")'"

$allusers = @(Get-AppxPackage -AllUsers $name | Select-Object -ExpandProperty Name)
$lines += "Get-AppxPackage -AllUsers '$name' : $($allusers.Count)"

$lines | Out-File -FilePath $log -Encoding utf8
