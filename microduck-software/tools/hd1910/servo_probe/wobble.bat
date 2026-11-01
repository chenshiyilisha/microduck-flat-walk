@echo off
chcp 65001 >nul
cd /d "%~dp0\..\..\.."

set SID=%1
if "%SID%"=="" set SID=1

echo.
echo ============================================================
echo   摇晃法验收  ID %SID%  (COM3)
echo   (可带参数: wobble.bat 10   默认 ID 1)
echo ------------------------------------------------------------
echo   1) 静止 3 秒   -- 别碰
echo   2) 按回车      -- 然后来回扳输出轴几度，共 12 秒
echo   3) 按回车      -- 松手，看是否回稳
echo.
echo   扳起来会觉得紧、越扳越紧 = P=32 的 PD 在抵抗，是正确行为
echo ============================================================
echo.

.venv-mjlab\Scripts\python.exe tools\hd1910\servo_probe\wobble_check.py run --port COM3 --id %SID% --settle 3 --wobble 12 --release 4 --json out\wobble_id%SID%.json

echo.
echo ============================================================
echo   结束。存档: out\wobble_id%SID%.json
echo   全部 PASS 才给它写 ID
echo ============================================================
pause
