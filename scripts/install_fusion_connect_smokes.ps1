# Install Connect main flow batch smoke into Fusion Scripts and Add-ins.
# Close Fusion first, run this, restart Fusion.
param(
    [ValidateSet("main")]
    [string]$Batch = "main"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
python (Join-Path $repoRoot "scripts\manage_fusion_smokes.py") install --batch $Batch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
