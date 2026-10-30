#Requires -Version 5.1
<#
.SYNOPSIS
  Bootstrap .venv-mjlab on a Windows training server (RTX 4070 Ti / CUDA 12.8).

.DESCRIPTION
  Run from microduck-software\ after transferring the recipe pack (see README.md).
  Does NOT copy a donor venv. Pins: tools\hd1910\server_pack\pins.txt

  If missing, installs winget (App Installer) then Python 3.12 + Git for Windows
  (needs network; may prompt UAC / admin). NVIDIA driver is still manual.

.PARAMETER SkipHostTools
  Do not install winget / Python / Git (fail if already missing).

.PARAMETER SkipSmoke
  Skip the post-install 64x5 GPU smoke (default: run smoke_heading.sh,
  which also verifies the P3 plant + heading-closed-loop readback gate).

.PARAMETER SmokeTrain
  Use smoke_train.sh (m5/kp32 control) instead of smoke_heading.sh for the
  post-install smoke. Default is smoke_heading.sh since the P3 retrain runs
  with --rel-heading-envs and must exercise that path on first smoke.

.PARAMETER Plant
  Which plant to leave live. Default hd1910_kp5 (= P3 training target:
  official m6 params + official STS3215 control law + kp_fw=5).
  Use hd1910 to reproduce the archived m5/kp_fw=32 numbers instead.

.EXAMPLE
  cd D:\train\microduck-software
  powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1

.EXAMPLE
  # reproduce archived readings instead of the P3 target
  powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1 -Plant hd1910
#>
param(
  [switch]$SkipHostTools,
  [switch]$SkipSmoke,
  [switch]$SmokeTrain,
  [string]$Plant = "hd1910_kp5"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location $Root

$Venv = Join-Path $Root ".venv-mjlab"
$Py = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"
$BamDir = Join-Path $Root ".upstream\bam-62bd8ce12154340be97e06f7f41a0ca8f116d967"
$RlDir = Join-Path $Root ".upstream\microduck_rl-develop"
$Idx = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
$TorchIdx = "https://download.pytorch.org/whl/cu128"
$BashCandidates = @(
  "${env:ProgramFiles}\Git\bin\bash.exe",
  "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
  "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
)

function Require-Path($p, $hint) {
  if (-not (Test-Path $p)) { throw "Missing $p — $hint" }
}

function Refresh-Path {
  $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = @($machine, $user) -join ";"
}

function Test-Cmd($name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Find-Bash {
  foreach ($b in $BashCandidates) {
    if (Test-Path $b) { return $b }
  }
  $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Find-Winget {
  Refresh-Path
  $cmd = Get-Command winget.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($p in @(
      "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe",
      "${env:ProgramFiles}\WindowsApps\Microsoft.DesktopAppInstaller*\winget.exe"
    )) {
    $hit = Get-Item $p -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  return $null
}

function Install-WingetFromGitHub {
  # Official offline path: latest stable DesktopAppInstaller msixbundle + x64 deps.
  # https://github.com/microsoft/winget-cli/releases + Learn "Install WinGet"
  $tmp = Join-Path $env:TEMP ("winget_bootstrap_" + [guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    Write-Host "Fetching latest winget-cli release metadata..."
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/microsoft/winget-cli/releases/latest" -Headers @{ "User-Agent" = "microduck-server-pack" }
    $bundle = $rel.assets | Where-Object { $_.name -like "Microsoft.DesktopAppInstaller*.msixbundle" } | Select-Object -First 1
    $depsZip = $rel.assets | Where-Object { $_.name -eq "DesktopAppInstaller_Dependencies.zip" } | Select-Object -First 1
    if (-not $bundle) { throw "no msixbundle in $($rel.tag_name)" }

    $bundlePath = Join-Path $tmp $bundle.name
    Write-Host "Downloading $($bundle.name) ..."
    Invoke-WebRequest -Uri $bundle.browser_download_url -OutFile $bundlePath -UseBasicParsing

    if ($depsZip) {
      $zipPath = Join-Path $tmp $depsZip.name
      Write-Host "Downloading $($depsZip.name) ..."
      Invoke-WebRequest -Uri $depsZip.browser_download_url -OutFile $zipPath -UseBasicParsing
      $depRoot = Join-Path $tmp "deps"
      Expand-Archive -Path $zipPath -DestinationPath $depRoot -Force
      $archDir = Join-Path $depRoot "x64"
      if (-not (Test-Path $archDir)) { $archDir = $depRoot }
      Get-ChildItem $archDir -Recurse -Include *.appx,*.msix |
        Sort-Object FullName |
        ForEach-Object {
          Write-Host "Add-AppxPackage dep: $($_.Name)"
          Add-AppxPackage -Path $_.FullName -ErrorAction SilentlyContinue
        }
    }

    Write-Host "Add-AppxPackage $($bundle.name) ..."
    Add-AppxPackage -Path $bundlePath
  } finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Ensure-Winget {
  if (Find-Winget) { return }
  if ($SkipHostTools) {
    throw "winget missing and -SkipHostTools set"
  }

  Write-Host "winget missing — trying to install App Installer..."

  # 1) Already present as Store package but not registered (fresh login / Server).
  try {
    Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe -ErrorAction Stop
    Refresh-Path
    if (Find-Winget) { Write-Host "winget registered via Appx family name"; return }
  } catch {
    Write-Host "RegisterByFamilyName skipped: $($_.Exception.Message)"
  }

  # 2) PowerShell module repair (Win10/11 with PSGallery).
  try {
    Write-Host "Trying Microsoft.WinGet.Client Repair-WinGetPackageManager..."
    Install-PackageProvider -Name NuGet -Force -Scope CurrentUser | Out-Null
    Install-Module -Name Microsoft.WinGet.Client -Force -Scope CurrentUser -Repository PSGallery -AllowClobber
    Import-Module Microsoft.WinGet.Client -Force
    Repair-WinGetPackageManager -Latest -Force
    Refresh-Path
    if (Find-Winget) { Write-Host "winget OK via Repair-WinGetPackageManager"; return }
  } catch {
    Write-Host "Repair-WinGetPackageManager skipped: $($_.Exception.Message)"
  }

  # 3) Download official GitHub release (msixbundle + deps).
  try {
    Install-WingetFromGitHub
    Refresh-Path
    # WindowsApps shim can lag; wait briefly.
    for ($i = 0; $i -lt 10; $i++) {
      if (Find-Winget) { break }
      Start-Sleep -Seconds 1
      Refresh-Path
    }
    if (Find-Winget) { Write-Host "winget OK via GitHub msixbundle"; return }
  } catch {
    Write-Host "GitHub winget install failed: $($_.Exception.Message)"
  }

  throw "Could not install winget. Install 'App Installer' from Microsoft Store, or install Python 3.12 + Git manually and re-run with -SkipHostTools."
}

function Winget-Install($Id) {
  Ensure-Winget
  $winget = Find-Winget
  Write-Host "winget install $Id ..."
  & $winget install --id $Id -e --accept-package-agreements --accept-source-agreements --disable-interactivity
  # 0 = ok, -1978335189 (0x8A15002B) = already installed — both fine
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
    throw "winget install $Id failed (exit $LASTEXITCODE). Run elevated PowerShell if UAC blocked it."
  }
  Refresh-Path
}

function Ensure-Python312 {
  Refresh-Path
  if ($env:MICRODUCK_PYTHON -and (Test-Path $env:MICRODUCK_PYTHON)) {
    return $env:MICRODUCK_PYTHON
  }
  if (Test-Cmd "py") {
    & py -3.12 -c "import sys; assert sys.version_info[:2]==(3,12)" 2>$null
    if ($LASTEXITCODE -eq 0) { return "py" }
  }
  $direct = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "${env:ProgramFiles}\Python312\python.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($direct) { return $direct }

  if ($SkipHostTools) {
    throw "Python 3.12 missing and -SkipHostTools set"
  }
  Winget-Install "Python.Python.3.12"
  Refresh-Path
  if (Test-Cmd "py") {
    & py -3.12 -c "import sys; assert sys.version_info[:2]==(3,12)"
    if ($LASTEXITCODE -eq 0) { return "py" }
  }
  $direct = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "${env:ProgramFiles}\Python312\python.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($direct) { return $direct }
  throw "Python 3.12 installed but not on PATH — open a new PowerShell and re-run bootstrap.ps1"
}

function Ensure-GitBash {
  $bash = Find-Bash
  if ($bash) { return $bash }
  if ($SkipHostTools) {
    throw "Git bash missing and -SkipHostTools set"
  }
  Winget-Install "Git.Git"
  Refresh-Path
  $bash = Find-Bash
  if (-not $bash) {
    throw "Git installed but bash.exe not found — open a new PowerShell and re-run, or check 'C:\Program Files\Git\bin\bash.exe'"
  }
  return $bash
}

Write-Host "== 0) preflight =="
Require-Path $BamDir "transfer bam-62bd8ce tree (see make_transfer.ps1)"
Require-Path $RlDir "transfer microduck_rl-develop"
Require-Path (Join-Path $Root "tools\hd1910\apply_to_live.py") "transfer tools\hd1910"
Require-Path (Join-Path $Root "tools\bam_params\hd1910\m5.json") "transfer tools\bam_params"
# The default plant's params file must be in the pack, else step 7 exits non-zero.
Require-Path (Join-Path $Root "tools\bam_params\hd1910\official_m6_stslaw.json") "transfer tools\bam_params (P3 target params)"

& nvidia-smi | Out-Host
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed — install Game Ready / Studio driver first (bootstrap does not install GPU drivers)" }

Write-Host "== 0b) host tools (Python 3.12 + Git) =="
$PyLauncher = Ensure-Python312
$Bash = Ensure-GitBash
Write-Host "python launcher: $PyLauncher"
Write-Host "git bash: $Bash"

Write-Host "== 1) venv (Python 3.12) =="
if (-not (Test-Path $Py)) {
  if ($PyLauncher -eq "py") {
    & py -3.12 -m venv $Venv
  } else {
    & $PyLauncher -m venv $Venv
  }
  if ($LASTEXITCODE -ne 0) { throw "venv create failed" }
}
& $Py -c "import sys; assert sys.version_info[:2]==(3,12), sys.version"

Write-Host "== 2) torch 2.9.1+cu128 =="
& $Pip install --upgrade pip
& $Pip install "torch==2.9.1" --index-url $TorchIdx
& $Py -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.__version__, torch.cuda.get_device_name(0))"

Write-Host "== 3) mjlab stack (mirror: $Idx) =="
& $Pip install --index-url $Idx `
  "mjlab>=1.3,<1.4" "mujoco-warp>=3.7,<3.8" "mujoco>=3.7,<3.8" "warp-lang==1.12.0" `
  "onnxruntime>=1.24.4" "huggingface_hub>=0.27.0" "matplotlib>=3.10.9" "rsl-rl-lib>=5.0,<6"

Write-Host "== 4) bam-62bd8ce editable (NOT full ftservo-bam) =="
& $Pip install --no-deps -e $BamDir

Write-Host "== 5) mjlab-microduck (local tree, no-deps) =="
& $Pip install --no-deps $RlDir

Write-Host "== 6) Windows MUJOCO_GL=glfw patch =="
& $Py (Join-Path $PSScriptRoot "patch_mjlab_win_gl.py")

Write-Host "== 7) plant '$Plant' =="
& $Py tools\hd1910\apply_to_live.py --plant $Plant
if ($LASTEXITCODE -ne 0) {
  throw "plant '$Plant' did not pass its gate (exit $LASTEXITCODE). Available: hd1910_kp5 | hd1910 | hd1910_ftservo_m6 | xl330"
}
& $Py tools\hd1910\apply_to_live.py --check | Out-Host

Write-Host "== 8) versions =="
& $Py -c @"
import importlib.metadata as md
for p in ('torch','mjlab','mujoco','mujoco-warp','warp-lang','better-actuator-models','mjlab-microduck','onnxruntime','rsl-rl-lib'):
    try: print(f'  {p:<24} {md.version(p)}')
    except Exception as e: print(f'  {p:<24} MISSING ({e})')
"@

Write-Host ""
Write-Host "Bootstrap OK."

if ($SkipSmoke) {
  Write-Host "SkipSmoke set — run manually:"
  Write-Host "  `$env:MUJOCO_GL='glfw'"
  Write-Host "  & `"$Bash`" tools/hd1910/smoke_heading.sh   (or smoke_train.sh for m5/kp32 control)"
} else {
  Write-Host "== 9) GPU smoke (64 envs x 5 iters) =="
  if ($env:CUDA_VISIBLE_DEVICES -eq "") {
    Remove-Item Env:CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue
  }
  $env:MUJOCO_GL = "glfw"
  $SmokeScript = "tools/hd1910/smoke_train.sh"
  if (-not $SmokeTrain) { $SmokeScript = "tools/hd1910/smoke_heading.sh" }
  Write-Host "smoke: $SmokeScript"
  & $Bash $SmokeScript
  if ($LASTEXITCODE -ne 0) {
    throw "$SmokeScript failed (exit $LASTEXITCODE). Check out/train_*_smoke_*.log for device=cuda:0"
  }
  Write-Host "Smoke OK (device=cuda:0 gate passed)."
}

Write-Host "Next train (P3 + heading closed loop):"
Write-Host "  REL_HEADING=0.30 ENVS=4096 ITERS=2000 & `"$Bash`" tools/hd1910/explore_heading.sh"
Write-Host "4070 Ti (12GB): try ENVS=6144 after smoke; 8192 optional."
