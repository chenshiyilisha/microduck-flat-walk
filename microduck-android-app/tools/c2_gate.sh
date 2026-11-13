#!/usr/bin/env bash
# C2 gate -- own the full stack lifecycle in ONE foreground WSL call:
#   real robotd --sim  ->  /run/robotd.sock  ->  c2_relay.py (TCP)  ->  Windows java C2LiveCheck
# Reason for the single-harness shape: wsl.exe in a background/non-interactive
# task context fails (126); see docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md §9.7.
set -u
BASE=/mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app
ROBOTD=/root/duck/DuckBuddy-main/target/debug/robotd
SOCK=/run/robotd.sock
PORT=7788
LOG=/root/duck/c2_robotd.log
RLOG=/root/duck/c2_relay.log
JAVA="/mnt/e/软件工具/OpenJdk17/bin/java.exe"
FAT_WIN="$(wslpath -w "$BASE/build/fat")"

pkill -f 'DuckBuddy-main/target/debug/robotd' >/dev/null 2>&1 || true
pkill -f 'tools/c2_relay.py' >/dev/null 2>&1 || true
rm -f "$SOCK"

"$ROBOTD" --sim 127.0.0.1:7801 --socket "$SOCK" >"$LOG" 2>&1 &
RPID=$!
READY=0
for i in $(seq 1 60); do
  if [ -S "$SOCK" ]; then READY=1; break; fi
  sleep 0.2
done
if [ "$READY" -ne 1 ]; then
  echo "ROBOTD_SOCKET_FAIL"; tail -n 30 "$LOG"; kill "$RPID" 2>/dev/null || true; exit 2
fi
echo "ROBOTD_READY pid=$RPID"

python3 "$BASE/tools/c2_relay.py" --port "$PORT" --unix "$SOCK" >"$RLOG" 2>&1 &
LPID=$!
RREADY=0
for i in $(seq 1 40); do
  if grep -q RELAY_READY "$RLOG"; then RREADY=1; break; fi
  sleep 0.1
done
if [ "$RREADY" -ne 1 ]; then
  echo "RELAY_FAIL"; cat "$RLOG"; kill "$LPID" "$RPID" 2>/dev/null || true; exit 2
fi
cat "$RLOG"

WSL_IP=$(hostname -I | awk '{print $1}')
echo "WSL_IP=$WSL_IP"
echo "JAVA=$JAVA"
echo "CP=$FAT_WIN"
"$JAVA" -Dfile.encoding=UTF-8 -cp "$FAT_WIN" io.microduck.app.core.C2LiveCheck "$WSL_IP" "$PORT"
RC=$?

kill "$LPID" 2>/dev/null || true
kill "$RPID" 2>/dev/null || true
wait "$LPID" 2>/dev/null || true
wait "$RPID" 2>/dev/null || true
echo "C2_GATE_RC=$RC"
exit "$RC"
