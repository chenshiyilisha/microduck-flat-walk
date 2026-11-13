#!/usr/bin/env bash
# C2 probe harness -- own the full robotd lifecycle in ONE foreground WSL call.
# Reason: wsl.exe in a background/non-interactive task context fails (126);
# see docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md §9.7.
set -u
ROBOTD=/root/duck/DuckBuddy-main/target/debug/robotd
SOCK=/run/robotd.sock
LOG=/root/duck/c2_robotd.log
PROBE=/mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app/tools/c2_probe.py

pkill -f 'DuckBuddy-main/target/debug/robotd' >/dev/null 2>&1 || true
rm -f "$SOCK"
"$ROBOTD" --sim 127.0.0.1:7801 --socket "$SOCK" >"$LOG" 2>&1 &
PID=$!
READY=0
for i in $(seq 1 60); do
  if [ -S "$SOCK" ]; then READY=1; break; fi
  sleep 0.2
done
echo "SOCKET_READY=$READY ROBOTD_PID=$PID"
if [ "$READY" -ne 1 ]; then
  echo "---- robotd log ----"
  tail -n 40 "$LOG"
  kill "$PID" 2>/dev/null || true
  exit 2
fi
python3 "$PROBE"
RC=$?
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true
echo "PROBE_RC=$RC"
exit "$RC"
