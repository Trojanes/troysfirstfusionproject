# Remove temporary Connect smoke scripts from Fusion after verification PASS.
# Close Fusion first, run this, restart Fusion.
param(
    [Parameter(Mandatory = $true)]
    [int]$PassedDay
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
python (Join-Path $repoRoot "scripts\manage_fusion_smokes.py") remove --passed $PassedDay
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
