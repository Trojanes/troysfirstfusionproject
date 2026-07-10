# Register Day1 Connect smoke add-in in Fusion Add-Ins folder (shows on Add-Ins tab).
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repoRoot "fusion360-day1-connect-smoke"
$addinsRoot = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns"
$linkName = "fusion360-day1-connect-smoke"
$linkPath = Join-Path $addinsRoot $linkName

if (-not (Test-Path $target)) {
    throw "Missing add-in folder: $target"
}
New-Item -ItemType Directory -Force -Path $addinsRoot | Out-Null
if (Test-Path $linkPath) {
    Remove-Item $linkPath -Force -Recurse
}
cmd /c mklink /J "$linkPath" "$target" | Out-Null
Write-Host "Registered: $linkPath -> $target"
Write-Host "Restart Fusion (or close/reopen Scripts and Add-Ins), then find Day1ConnectSmoke on Add-Ins tab."
