#!/usr/bin/env bash
# Windows 侧：C2+ 前置 —— 起 MuJoCo body_server，供 WSL 的 `robotd --sim` 连接。
# 现成环境（准则 5）：microduck-software/.venv-mjlab/Scripts/python.exe
#   torch 2.9.1+cu128 / mujoco 3.7.0 / mjlab_microduck 全齐，勿另装。
# 一手依据：docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md §9.2
#   Windows 侧 body_server 必须监听 0.0.0.0（WSL2 NAT 网关 172.26.32.1 才连得上）。
# 用法（Git Bash，前台常驻；或由 Agent 以 background 任务启动）：
#   bash microduck-android-app/tools/c2_body_server.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2
PY="microduck-software/.venv-mjlab/Scripts/python.exe"
[ -x "$PY" ] || { echo "FAIL: 找不到现成 venv: $ROOT/$PY"; exit 2; }
exec "$PY" -m mjlab_microduck.sim.body_server --headless --host 0.0.0.0 --port 7801
