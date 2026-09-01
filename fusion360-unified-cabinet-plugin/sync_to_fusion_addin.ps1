$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$addin = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns\fusion360-unified-cabinet-plugin"
if (-not (Test-Path $addin)) {
    Write-Error "Fusion AddIns folder not found: $addin"
    exit 1
}
robocopy $repo $addin /E /XD __pycache__ .git logs /XF *.pyc /NFL /NDL /NP
$code = $LastExitCode
if ($code -ge 8) {
    Write-Error "robocopy failed with exit $code"
    exit $code
}
Write-Output "Synced repo -> $addin"
Write-Output "Stop + Run CabinetNC in Fusion so the palette reloads."
exit 0
