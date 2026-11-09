#Requires -Version 5.1
<#
.SYNOPSIS
  Build a small Windows transfer zip for a remote train box (no .venv-mjlab).

.DESCRIPTION
  Packs pins + scripts + BAM pin + microduck_rl snapshot + plant tools.
  Typical size ~50 MB (vs ~5 GB for .venv-mjlab). Recipient runs bootstrap.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\make_transfer.ps1
  # → out\hd1910_win_train_pack_YYYYMMDD.zip
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location $Root

$BamName = "bam-62bd8ce12154340be97e06f7f41a0ca8f116d967"
$Stamp = Get-Date -Format "yyyyMMdd"
$OutDir = Join-Path $Root "out"
$Stage = Join-Path $OutDir "_win_pack_stage"
$Zip = Join-Path $OutDir "hd1910_win_train_pack_$Stamp.zip"

$Must = @(
  ".upstream\$BamName",
  ".upstream\microduck_rl-develop",
  "tools\hd1910",
  "tools\bam_params",
  "tools\bam_actuators.py",
  "tools\install_mjlab_stack.sh",
  # 🔴 2026-11-09: the 2026-10-27 pack omitted the P3 trainer entrypoint.
  # explore_heading.sh / smoke_heading.sh both call it, so the old pack could
  # install a full venv and still fail on the first train. verify_pack.py below
  # now derives this list from the .sh references, so a new script cannot
  # silently reintroduce a missing dependency.
  "tools\train_heading_variant.py",
  "tools\eval_velocity_in_sim.py",
  "tools\check_onnx_parity.py",
  "tools\gate_p3_yaw.py",
  "tools\plant_id.py"
)
foreach ($rel in $Must) {
  $p = Join-Path $Root $rel
  if (-not (Test-Path $p)) { throw "Missing $rel - cannot pack" }
}

# A failed verify used to leave a read-only stage behind and block the next run.
function Remove-Stage {
  if (-not (Test-Path $Stage)) { return }
  Get-ChildItem $Stage -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }
  Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
  if (Test-Path $Stage) {
    throw "could not remove stale stage '$Stage' - delete it manually before packing"
  }
}
Remove-Stage
New-Item -ItemType Directory -Path $Stage | Out-Null
$Soft = Join-Path $Stage "microduck-software"
New-Item -ItemType Directory -Path $Soft | Out-Null

function Copy-Tree($rel) {
  $src = Join-Path $Root $rel
  $dst = Join-Path $Soft $rel
  $parent = Split-Path $dst -Parent
  if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  if (Test-Path $src -PathType Container) {
    Copy-Item $src $dst -Recurse -Force
  } else {
    Copy-Item $src $dst -Force
  }
}

foreach ($rel in $Must) { Copy-Tree $rel }

# Optional helpers if present
foreach ($rel in @("tools\export_onnx.py", "tools\rehearse_deploy.py",
                   "tools\eval_joy_in_sim.py", "tools\eval_tracking.py", "README.md")) {
  if (Test-Path (Join-Path $Root $rel)) { Copy-Tree $rel }
}

# 🔴 Hard gate BEFORE zipping. The 2026-10-27 pack shipped without
# tools/train_heading_variant.py; verify_pack.py derives the dependency set from
# every .sh reference so the same omission cannot recur silently.
# Prefer the project's own interpreter: Get-Command python.exe can resolve to
# the Windows Store stub (%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe),
# which exits 9009 and made the gate report a false FAIL.
$VenvPy = Join-Path $Root ".venv-mjlab\Scripts\python.exe"
if (Test-Path $VenvPy) {
  $Python = $VenvPy
} else {
  $Python = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $Python) { $Python = (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
}
if (-not $Python) { throw "python not found - cannot verify pack; refusing to zip an unverified pack" }
& $Python (Join-Path $PSScriptRoot "verify_pack.py") --root $Stage
if ($LASTEXITCODE -ne 0) { Remove-Stage; throw "verify_pack FAILED - pack is incomplete, not zipped" }
& $Python (Join-Path $PSScriptRoot "p3_select.py") selftest | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Remove-Stage; throw "p3_select selftest FAILED - not zipped" }

# Exclude junk from upstream trees
Get-ChildItem $Soft -Recurse -Directory -Filter "__pycache__" -EA SilentlyContinue |
  Remove-Item -Recurse -Force -EA SilentlyContinue
Get-ChildItem $Soft -Recurse -Directory -Filter ".git" -EA SilentlyContinue |
  Remove-Item -Recurse -Force -EA SilentlyContinue

# Top-level instructions
$ReadmeTop = @"
# HD1910 / P3 sweep Windows train transfer ($Stamp) - RTX 4070 Ti

1. Unzip so you have ``microduck-software\`` on the server.
2. NVIDIA driver >= 572.61 (CUDA 12.8 Update 1 Windows floor); Python 3.12 and
   Git for Windows are installed by bootstrap.ps1 unless -SkipHostTools.
3. ``cd microduck-software``
4. ``powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1``
   Default plant is hd1910_kp8 (kp_fw=8, the current deployment line).
   Use -Plant hd1910_kp5 only to reproduce the archived P3/kp5 readings.
5. Smoke runs automatically (smoke_heading.sh with PLANT=p8, verifies plant +
   heading readback + device=cuda:0).
6. P3 seed sweep: Git Bash →
   ``bash tools/hd1910/server_pack/p3_sweep.sh``   (TASKS/SEEDS/ENVS/ITERS overridable)
   ``.venv-mjlab/Scripts/python.exe tools/hd1910/server_pack/p3_select.py select --manifest out/p3_sweep_manifest.jsonl --out out/p3_sweep_summary.json``

This zip was verified by verify_pack.py before compression: every tools/*.py
referenced by a .sh is present. Do NOT copy a donor ``.venv-mjlab``.
See ``tools\hd1910\server_pack\README.md`` for the full recipe and iron rules.
"@
Set-Content -Path (Join-Path $Stage "README_TRANSFER.txt") -Value $ReadmeTop -Encoding UTF8

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal
Remove-Stage

$size = (Get-Item $Zip).Length / 1MB
Write-Host ("OK -> {0} ({1:N1} MB)" -f $Zip, $size)
Write-Host "Copy zip to Windows server; extract; run bootstrap.ps1"
