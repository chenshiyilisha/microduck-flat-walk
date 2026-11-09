#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroDuck HD-1910 真机首跑抓取工具
================================

把 ``robotctl monitor --json`` 的原始字节落盘为 ndjson（每行一帧 RobotState），
并把 ``robotctl health --json`` 的独立 RPC 报告落盘为 JSON，供 ``verify_capture.py``
做**字节级对照**——直接在真实机器人字节上确认：
  * HD-1910 robotd 是否暴露 ``robotctl monitor`` 子命令；
  * RobotState 是否含 ``safety.gravity`` / ``gyro`` / ``head`` / ``odom`` 等字段；
  * health RPC 的真实形状是不是 ``report.robot.imu.consecutive_stale_blocks``。

背景（为什么需要）：live_viewer 的解析路径此前从未对真实 robotctl 字节验证过
（本开发环境无 robotctl 二进制 / 无机器人主机 / 无 WebRTC relay 访问）。
抓取 + 对照让“真机首跑”变成两步一键，且无需启动 GUI 即可在真实字节上静态核对。

依赖：仅 Python 标准库 + 同目录的 live_viewer（仅用于本地 mock 模式生成合成帧）。

用法（operator PC，robotctl 在 PATH 或经 ssh 可达）
--------------------------------------------------
  # 真机：抓 8 秒 monitor 流 + 一次 health，落盘
  python capture_live.py --source robotctl --seconds 8 \
      --out monitor.ndjson --health-out health.json
  # 走 ssh 拉流（无需本机装 robotctl）
  python capture_live.py --source robotctl --host robot-host --seconds 8 \
      --out monitor.ndjson --health-out health.json

本地无硬件，验证整条管线（不连真机，合成帧）
--------------------------------------------
  python capture_live.py --source mock --out monitor.ndjson --health-out health.json
  python verify_capture.py --monitor monitor.ndjson --health health.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

# 允许从任意目录调用：把脚本所在目录加入 sys.path 以便 import live_viewer
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _monitor_cmd(host: str | None) -> list[str]:
    if host:
        return ["ssh", host, "robotctl monitor --json"]
    return ["robotctl", "monitor", "--json"]


def _health_cmd(host: str | None) -> list[str]:
    if host:
        return ["ssh", host, "robotctl health --json"]
    return ["robotctl", "health", "--json"]


def capture_robotctl(out_path: str, health_path: str,
                     host: str | None, seconds: float) -> int:
    """抓真机流：monitor 落盘 ndjson，health 落盘 JSON。返回 monitor 帧数。"""
    mcmd = _monitor_cmd(host)
    hcmd = _health_cmd(host)

    # —— health 是独立 RPC：抓一次即可 ——
    print(f"抓取 health：{' '.join(hcmd)}", file=sys.stderr)
    try:
        hp = subprocess.run(hcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=10)
        if hp.returncode == 0 and hp.stdout.strip():
            try:
                rep = json.loads(hp.stdout)
                with open(health_path, "w", encoding="utf-8") as f:
                    json.dump(rep, f, ensure_ascii=False, indent=2)
                print(f"  health 已落盘：{health_path}", file=sys.stderr)
            except json.JSONDecodeError as e:
                _write_health_error(health_path, f"health 非 JSON：{e}；stderr={hp.stderr[:200]}")
        else:
            _write_health_error(health_path,
                                f"health 返回码 {hp.returncode}；stderr={hp.stderr[:200]}")
    except Exception as e:  # 超时 / robotctl 不存在 等
        _write_health_error(health_path, f"health 抓取失败：{type(e).__name__}: {e}")

    # —— monitor 流：边读边落盘，超时截断 ——
    print(f"抓取 monitor（{seconds}s）：{' '.join(mcmd)}  (Ctrl-C 提前结束)", file=sys.stderr)
    proc = subprocess.Popen(mcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    n = 0
    deadline = time.time() + seconds
    try:
        assert proc.stdout is not None
        with open(out_path, "w", encoding="utf-8") as f:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "joints" not in obj:   # 连接横幅 / 非状态行
                    continue
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                n += 1
                if time.time() > deadline:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    print(f"  monitor 已落盘：{out_path}  ({n} 帧)", file=sys.stderr)
    return n


def _write_health_error(health_path: str, msg: str) -> None:
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump({"_error": msg}, f, ensure_ascii=False, indent=2)
    print(f"  [WARN] {msg}", file=sys.stderr)
    print(f"  health 错误已记录：{health_path}", file=sys.stderr)


def capture_mock(out_path: str, health_path: str, seconds: float) -> int:
    """本地合成：复用 live_viewer.iter_mock_frames 生成 monitor 帧 + 一条 health。"""
    import live_viewer as V  # 仅在 mock 模式需要（纯新增依赖，真机模式不 import）
    print("MOCK 抓取（合成帧，非真机）", file=sys.stderr)
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for obj in V.iter_mock_frames(seconds, 0.1):
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump(V.mock_health_report(stale=2, healthy=True), f,
                  ensure_ascii=False, indent=2)
    print(f"  monitor 已落盘：{out_path}  ({n} 帧)", file=sys.stderr)
    print(f"  health 已落盘：{health_path}", file=sys.stderr)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="MicroDuck HD-1910 真机流抓取（落盘供对照）")
    ap.add_argument("--source", choices=["robotctl", "mock"], default="mock",
                    help="robotctl=真机/ssh 抓取; mock=本地合成(验证管线用)")
    ap.add_argument("--host", default=None,
                    help="ssh 主机（如 robot-host）；指定则走 ssh 拉流，无需本机 robotctl")
    ap.add_argument("--seconds", type=float, default=8.0, help="monitor 抓取时长(秒)")
    ap.add_argument("--out", default="monitor.ndjson", help="monitor 帧输出(ndjson)")
    ap.add_argument("--health-out", default="health.json", help="health 报告输出(JSON)")
    args = ap.parse_args()

    if args.source == "robotctl" and not args.host and shutil.which("robotctl") is None:
        sys.exit("robotctl 不在 PATH：请先装好 robotctl，或用 --host <robot-host> 走 ssh 拉流")

    if args.source == "robotctl":
        capture_robotctl(args.out, args.health_out, args.host, args.seconds)
    else:
        capture_mock(args.out, args.health_out, args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
