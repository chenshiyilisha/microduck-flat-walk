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
  "tools\install_mjlab_stack.sh"
)
foreach ($rel in $Must) {
  $p = Join-Path $Root $rel
  if (-not (Test-Path $p)) { throw "Missing $rel — cannot pack" }
}

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
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
foreach ($rel in @("tools\export_onnx.py", "tools\eval_velocity_in_sim.py", "tools\rehearse_deploy.py", "README.md")) {
  if (Test-Path (Join-Path $Root $rel)) { Copy-Tree $rel }
}

# Exclude junk from upstream trees
Get-ChildItem $Soft -Recurse -Directory -Filter "__pycache__" -EA SilentlyContinue |
  Remove-Item -Recurse -Force -EA SilentlyContinue
Get-ChildItem $Soft -Recurse -Directory -Filter ".git" -EA SilentlyContinue |
  Remove-Item -Recurse -Force -EA SilentlyContinue

# Top-level instructions
$ReadmeTop = @"
# HD1910 Windows train transfer ($Stamp)

1. Unzip so you have ``microduck-software\`` on the server.
2. Install: NVIDIA driver, Python 3.12, Git for Windows.
3. ``cd microduck-software``
4. ``powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1``
5. Smoke: Git Bash → ``tools/hd1910/smoke_train.sh`` (must log ``device=cuda:0``).

Do NOT copy a donor ``.venv-mjlab``. See ``tools\hd1910\server_pack\README.md``.
"@
Set-Content -Path (Join-Path $Stage "README_TRANSFER.txt") -Value $ReadmeTop -Encoding UTF8

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal
Remove-Item $Stage -Recurse -Force

$size = (Get-Item $Zip).Length / 1MB
Write-Host ("OK -> {0} ({1:N1} MB)" -f $Zip, $size)
Write-Host "Copy zip to Windows server; extract; run bootstrap.ps1"
