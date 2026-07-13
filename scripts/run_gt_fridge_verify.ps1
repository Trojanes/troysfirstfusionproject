#!/usr/bin/env pwsh
# Offline + hand-test guide for General Tall fridge stack.
# Usage (from repo root):
#   pwsh -File scripts/run_gt_fridge_verify.ps1
#   pwsh -File scripts/run_gt_fridge_verify.ps1 -SkipOffline

param(
  [switch]$SkipOffline
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "modules\generalTallCabinet"))) {
  $Root = (Get-Location).Path
}
$Gt = Join-Path $Root "modules\generalTallCabinet"
$PluginTests = Join-Path $Root "fusion360-unified-cabinet-plugin\tests"

Write-Host "=== GT fridge verify ===" -ForegroundColor Cyan
Write-Host "repo: $Root"

if (-not $SkipOffline) {
  Write-Host "`n[1/2] Offline unit + smoke" -ForegroundColor Cyan
  Push-Location $Gt
  try {
    node --experimental-strip-types fridgeZone.test.ts
    if ($LASTEXITCODE -ne 0) { throw "fridgeZone.test.ts failed ($LASTEXITCODE)" }
  } finally {
    Pop-Location
  }

  Push-Location $PluginTests
  try {
    python run_gt_fridge_zone_offline.py
    if ($LASTEXITCODE -ne 0) { throw "run_gt_fridge_zone_offline.py failed ($LASTEXITCODE)" }

    python -m unittest test_generator_declared_relationships.GeneratorDeclaredRelationshipTests.test_general_tall_fridge_panel_ids_filter_declarations -v
    if ($LASTEXITCODE -ne 0) { throw "fridge declaration unit test failed ($LASTEXITCODE)" }
  } finally {
    Pop-Location
  }
  Write-Host "[PASS] offline" -ForegroundColor Green
} else {
  Write-Host "[skip] offline (-SkipOffline)" -ForegroundColor Yellow
}

Write-Host "`n[2/2] Fusion hand-test checklist" -ForegroundColor Cyan
@"

Fusion hand-test (General Tall fridge stack)
--------------------------------------------
1. Restart Fusion / reload UnifiedCabinetPlugin so palette + generator pick up this commit.
2. Open Unified Cabinet palette → General Tall.
3. Stack:
   - Zone A: drawer, height ~200
   - Zone B: type = fridge
     appliance W/D/H ≈ 550 / 580 / 1470
4. Avoidance: enabled, depth 300, height 200  (expect raised: gap < 105)
5. Exterior side: left  (expect SidePanel_L + V5 on right)
6. Generate Data → Create Fusion Rough Bodies.
7. Spot-check bodies:
   - fridge cavity height ≈ 1470
   - SidePanel_L present; no SidePanel_R
   - V5 present on right, Z spans fridge cavity
   - no H13/H24/H34_bottom; H*_fridge present above fridge-base Zi
8. Connect → 当前板对 / 整柜:
   - declarations include gt_sidepanel_l_v1 and gt_v5_v2 (plus skeleton rail→deck)
   - pick one declared pair → preview screw_hole (do not auto cut-all)

Optional second pass: exteriorSide = none → expect V5 left, gt_v5_v1, no SidePanel decls.
Optional third pass: drawer height 400 → normal avoidance (keep H*_bottom, no H*_fridge).

"@ | Write-Host

Write-Host "Done. Offline gate green; Fusion steps are manual." -ForegroundColor Green
exit 0
