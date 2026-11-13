#!/usr/bin/env bash
# P1 驾驶活体 gate —— 单次前台 WSL 调用内拥有整栈生命周期：
#   Windows body_server(0.0.0.0:7801) <-TCP-> real robotd --sim -> /run/robotd.sock
#   -> c2_relay.py (纯字节 AF_UNIX↔TCP、零 canned) -> Windows java DriveLiveCheck
#
# 刻意**复用 C2 的 c2_relay.py、不改 c2_gate.sh / c2_gate_plus.sh**：那两条是已验证的
# 证据链，本轮新增文件不碰它们（C2 11/11 与 C2+ 24/24 仍可原样复跑）。
# 单次前台 harness 的依据：wsl.exe 在后台/非交互上下文报 126
#   （docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md §9.7）。
#
# 前置（WSL 外，Windows Git Bash）：
#   1. bash microduck-android-app/tools/c2_body_server.sh    （常驻）
#   2. bash microduck-android-app/tools/selftest.sh           （产出 build/fat）
set -u
BASE=/mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app
ROBOTD=/root/duck/DuckBuddy-main/target/debug/robotd
SOCK=/run/robotd.sock
PORT=7788
LOG=/root/duck/p1_drive_robotd.log
RLOG=/root/duck/p1_drive_relay.log
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
pkill -f 'tools/c2_relay.py' >/dev/null 2>&1 || true
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

python3 "$BASE/tools/c2_relay.py" --port "$PORT" --unix "$SOCK" >"$RLOG" 2>&1 &
LPID=$!
RREADY=0
for i in $(seq 1 50); do
  if grep -q RELAY_READY "$RLOG"; then RREADY=1; break; fi
  sleep 0.1
done
if [ "$RREADY" -ne 1 ]; then
  echo "RELAY_FAIL"; cat "$RLOG"; kill "$LPID" "$RPID" 2>/dev/null || true; exit 2
fi
cat "$RLOG"

# 等仿真链路 + 50 Hz 控制循环稳定，避免把启动窗口当成驾驶基线。
sleep 1.5
WSL_IP=$(hostname -I | awk '{print $1}')
echo "WSL_IP=$WSL_IP JAVA=$JAVA CP=$FAT_WIN"
"$JAVA" -Dfile.encoding=UTF-8 -cp "$FAT_WIN" \
  io.microduck.app.core.DriveLiveCheck "$WSL_IP" "$PORT"
RC=$?

echo "---- robotd log tail ----"
tail -n 12 "$LOG"

kill "$LPID" 2>/dev/null || true
kill "$RPID" 2>/dev/null || true
wait "$LPID" 2>/dev/null || true
wait "$RPID" 2>/dev/null || true
echo "DRIVE_GATE_RC=$RC"
exit "$RC"
