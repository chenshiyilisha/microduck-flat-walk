#!/usr/bin/env bash
# C2+ state-stream gate -- own the full stack lifecycle in ONE foreground WSL call:
#   Windows body_server(0.0.0.0:7801)  <-TCP->  robotd --sim  ->  /run/robotd.sock
#   -> c2_state_probe.py (NDJSON over AF_UNIX)
# The Windows body_server is started separately (see tools/c2_body_server.sh);
# this script only verifies reachability before starting the daemon.
set -u
BASE=/mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app
ROBOTD=/root/duck/DuckBuddy-main/target/debug/robotd
SOCK=/run/robotd.sock
LOG=/root/duck/c2plus_robotd.log

GW=$(ip route show default 2>/dev/null | awk '/default via/{print $3; exit}')
echo "WIN_GATEWAY=$GW"
if [ -z "$GW" ]; then echo "NO_GATEWAY"; exit 2; fi

python3 - "$GW" <<'PY'
import socket, sys
gw = sys.argv[1]
s = socket.socket()
s.settimeout(2.0)
try:
    s.connect((gw, 7801))
    print("BODY_SERVER_REACHABLE %s:7801" % gw)
except OSError as e:
    print("BODY_SERVER_UNREACHABLE %s:7801 %r" % (gw, e))
    sys.exit(3)
finally:
    s.close()
PY
REACH=$?
if [ "$REACH" -ne 0 ]; then
  echo "HINT: start Windows body_server first: tools/c2_body_server.sh"
  exit 2
fi

pkill -f 'DuckBuddy-main/target/debug/robotd' >/dev/null 2>&1 || true
rm -f "$SOCK"
"$ROBOTD" --sim "$GW:7801" --socket "$SOCK" >"$LOG" 2>&1 &
PID=$!
READY=0
for i in $(seq 1 80); do
  if [ -S "$SOCK" ]; then READY=1; break; fi
  sleep 0.2
done
echo "SOCKET_READY=$READY ROBOTD_PID=$PID"
if [ "$READY" -ne 1 ]; then
  echo "---- robotd log ----"; tail -n 40 "$LOG"
  kill "$PID" 2>/dev/null || true
  exit 2
fi

# Give the sim link + control loop a moment to produce sensor readings.
sleep 1.5
python3 "$BASE/tools/c2_state_probe.py"
RC=$?

echo "---- robotd log tail ----"
tail -n 18 "$LOG"
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true
echo "C2PLUS_STATE_PROBE_RC=$RC"
exit "$RC"
