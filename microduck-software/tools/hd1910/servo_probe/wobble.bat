@echo off
rem NOTE: this .bat must stay pure ASCII. cmd.exe decodes .bat files with the
rem system ANSI codepage (GBK on this box), so UTF-8 Chinese lines get mangled
rem into "not a command" errors. All Chinese text lives in the Python script.
chcp 65001 >nul
cd /d "%~dp0\..\..\.."

set SID=%1
if "%SID%"=="" set SID=1

if not exist ".venv-mjlab\Scripts\python.exe" (
  echo ERROR: venv python not found at .venv-mjlab\Scripts\python.exe
  echo        cd target = %CD%
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo   wobble check   ID %SID%   on COM3
echo   usage: wobble.bat [id]      ^(default id=1^)
echo ----------------------------------------------------------
echo   1^) keep still  3s  - do NOT touch
echo   2^) press ENTER     - then rock the shaft back/forth 12s
echo   3^) press ENTER     - release, watch it settle 4s
echo.
echo   Torque is released automatically ^(reg40=0^) before sampling,
echo   so the shaft should turn freely. If it still won't budge,
echo   fit a servo horn for leverage.
echo ==========================================================
echo.

".venv-mjlab\Scripts\python.exe" tools\hd1910\servo_probe\wobble_check.py run --port COM3 --id %SID% --settle 3 --wobble 12 --release 4 --json out\wobble_id%SID%.json

echo.
echo ==========================================================
echo   done.  saved: out\wobble_id%SID%.json
echo   Only write an ID if every gate PASSED.
echo ==========================================================
pause
