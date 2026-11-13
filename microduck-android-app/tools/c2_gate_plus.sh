#!/usr/bin/env bash
# C2+ gate -- own the full stack lifecycle in ONE foreground WSL call:
#   Windows body_server(0.0.0.0:7801)  <-TCP->  real robotd --sim  ->  /run/robotd.sock
#   -> c2_relay_plus.py (zero-canned byte forward + independent drop control)
#   -> Windows java C2PlusLiveCheck
# Single-harness shape: wsl.exe in background/non-interactive context fails (126);
# see docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md §9.7.
# PREREQUISITES (outside WSL):
#   1. bash microduck-android-app/tools/c2_body_server.sh   (Windows, stays running)
#   2. bash microduck-android-app/tools/selftest.sh          (builds build/fat)
set -u
BASE=/mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app
ROBOTD=/root/duck/DuckBuddy-main/target/debug/robotd
SOCK=/run/robotd.sock
PORT=7788
CPORT=7789
LOG=/root/duck/c2plus_robotd.log
RLOG=/root/duck/c2plus_relay.log
JAVA="/mnt/e/软件工具/OpenJdk17/bin/java.exe"
FAT_WIN="$(wslpath -w "$BASE/build/fat")"

GW=$(ip route show default 2>/dev/null | awk '/default via/{print $3; exit}')
echo "WIN_GATEWAY=$GW"
[ -z "$GW" ] && { echo "NO_GATEWAY"; exit 2; }

python3 - "$GW" <<'PY'
import socket, sys
gw = sys.argv[1]
s = socket.socket(); s.settimeout(2.0)
try:
    s.connect((gw, 7801)); print("BODY_SERVER_REACHABLE %s:7801" % gw)
except OSError as e:
    print("BODY_SERVER_UNREACHABLE %s:7801 %r" % (gw, e)); sys.exit(3)
finally:
    s.close()
PY
if [ $? -ne 0 ]; then
  echo "HINT: start Windows body_server first: bash tools/c2_body_server.sh"
  exit 2
fi

pkill -f 'DuckBuddy-main/target/debug/robotd' >/dev/null 2>&1 || true
pkill -f 'tools/c2_relay_plus.py' >/dev/null 2>&1 || true
rm -f "$SOCK"

"$ROBOTD" --sim "$GW:7801" --socket "$SOCK" >"$LOG" 2>&1 &
RPID=$!
READY=0
for i in $(seq 1 80); do
  if [ -S "$SOCK" ]; then READY=1; break; fi
  sleep 0.2
done
if [ "$READY" -ne 1 ]; then
  echo "ROBOTD_SOCKET_FAIL"; tail -n 30 "$LOG"; kill "$RPID" 2>/dev/null || true; exit 2
fi
echo "ROBOTD_READY pid=$RPID"

python3 "$BASE/tools/c2_relay_plus.py" --port "$PORT" --control-port "$CPORT" --unix "$SOCK" >"$RLOG" 2>&1 &
LPID=$!
RREADY=0
for i in $(seq 1 50); do
  if grep -q RELAY_READY "$RLOG" && grep -q CONTROL_READY "$RLOG"; then RREADY=1; break; fi
  sleep 0.1
done
if [ "$RREADY" -ne 1 ]; then
  echo "RELAY_FAIL"; cat "$RLOG"; kill "$LPID" "$RPID" 2>/dev/null || true; exit 2
fi
cat "$RLOG"

# Let the sim link + 50 Hz control loop produce real sensor readings before the check.
sleep 1.5
WSL_IP=$(hostname -I | awk '{print $1}')
echo "WSL_IP=$WSL_IP JAVA=$JAVA CP=$FAT_WIN"
"$JAVA" -Dfile.encoding=UTF-8 -cp "$FAT_WIN" \
  io.microduck.app.core.C2PlusLiveCheck "$WSL_IP" "$PORT" "$CPORT"
RC=$?

echo "---- relay log (FAULT_INJECT_DROP proves the cable pull really happened) ----"
cat "$RLOG"
echo "---- robotd log tail ----"
tail -n 12 "$LOG"

kill "$LPID" 2>/dev/null || true
kill "$RPID" 2>/dev/null || true
wait "$LPID" 2>/dev/null || true
wait "$RPID" 2>/dev/null || true
echo "C2PLUS_GATE_RC=$RC"
exit "$RC"
