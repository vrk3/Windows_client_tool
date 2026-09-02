<#
.SYNOPSIS
    Sign the built executables so SmartScreen / WDAC / AppLocker stop blocking them.

.DESCRIPTION
    Signs dist\WinClientTool\WinClientTool.exe and dist\WinClientTool-Portable.exe
    with an Authenticode certificate. Point at a .pfx + password, or a SHA-1/256
    thumbprint of a cert already in the current user's store (common for
    org-issued certs).

    Find signtool (Windows SDK) automatically; you can also pass -Signtool with
    an explicit path.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sign_build.ps1 -Pfx C:\certs\wct.pfx -Password "secret"
    powershell -ExecutionPolicy Bypass -File tools\sign_build.ps1 -Thumbprint "AB12CD34..."

.NOTES
    Signing needs the cert; this script only turns it into a signature and
    verifies the result. Run it after `pyinstaller ...` has produced dist\.
#>
param(
    [string]$Pfx = "",
    [string]$Password = "",
    [string]$Thumbprint = "",
    [string]$Signtool = "",
    [string]$Root = (Join-Path $PSScriptRoot "..")
)

$ErrorActionPreference = "Stop"

function Find-Signtool {
    if ($Signtool) { return $Signtool }
    $candidate = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($candidate) { return $candidate.Source }
    $sdk = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($sdk) { return $sdk.FullName }
    throw "signtool.exe not found. Install the Windows SDK, or pass -Signtool <path>."
}

function Get-Targets {
    @(
        (Join-Path $Root "dist\WinClientTool\WinClientTool.exe"),
        (Join-Path $Root "dist\WinClientTool-Portable.exe")
    ) | Where-Object { Test-Path $_ }
}

if (-not $Pfx -and -not $Thumbprint) {
    throw "Provide -Pfx <file> -Password <pw>, or -Thumbprint <hash>."
}
if ($Pfx -and -not (Test-Path $Pfx)) {
    throw "PFX not found: $Pfx"
}

$signtool = Find-Signtool
if ($Pfx) {
    $auth = "/f `"$Pfx`" /p `"$Password`""
} else {
    $auth = "/sha1 `"$Thumbprint`""
}

$targets = Get-Targets
if (-not $targets) {
    Write-Host "No built exe found under dist\. Build first, then sign." -ForegroundColor Yellow
    exit 1
}

foreach ($t in $targets) {
    Write-Host "Signing $t"
    & $signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com $auth "`"$t`"" 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "signtool failed for $t" }
    & $signtool verify /pa /v "`"$t`"" 2>&1 | Select-String -Pattern "Verifying|Signing Certificate|OK|error" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed for $t" }
}

Write-Host "All targets signed and verified." -ForegroundColor Green
