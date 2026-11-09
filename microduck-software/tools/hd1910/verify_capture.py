#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroDuck HD-1910 真机字节级对照工具
==================================

读 ``capture_live.py`` 落盘的 ``monitor.ndjson`` + ``health.json``，用 live_viewer 的
**真实解析路径** ``parse_state`` 逐帧解析，报告：
  * RobotState 各字段覆盖率（joints / targets / safety.gravity / gyro / head / odom ...）
    —— 直接在真实字节上确认 HD-1910 robotd 的 monitor 流暴露了哪些字段；
  * 合理性检查（joint 数量==15、是否有限、gravity 是否单位向量、倾角范围、fallen 帧数）；
  * health RPC 形状核对（report.robot.imu.consecutive_stale_blocks）。

价值：live_viewer 的解析此前从没对真实 robotctl 字节验证过。本工具让首跑前能用
真实字节静态核对，避免“防御性解析不崩但静默显示 n/a”的坑。

依赖：仅 Python 标准库 + 同目录 live_viewer（parse_state / _imu_health_from）。

用法
----
  # 已抓过真机字节
  python verify_capture.py --monitor monitor.ndjson --health health.json
  # 从管道喂（stdin）
  cat monitor.ndjson | python verify_capture.py --monitor -
  # 本地合成对照（不连真机，验证本工具自身）
  python capture_live.py --source mock --out monitor.ndjson --health health.json
  python verify_capture.py --monitor monitor.ndjson --health health.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import live_viewer as V  # parse_state / N / _imu_health_from


def _read_frames(monitor_path: str) -> list[dict]:
    frames: list[dict] = []
    if monitor_path == "-":
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    else:
        with open(monitor_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    frames.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return frames


def _coverage(frames: list[dict]) -> dict:
    """逐字段统计出现次数；只统计 RobotState 中查看器会用到的字段。"""
    total = len(frames)
    cov = {
        "joints": 0, "targets": 0,
        "safety.gravity": 0, "safety.fallen": 0, "safety.limp": 0,
        "gyro": 0, "head": 0, "odom": 0,
        "velocities": 0, "currents_ma": 0,
    }
    for fr in frames:
        if isinstance(fr.get("joints"), list):
            cov["joints"] += 1
        if isinstance(fr.get("targets"), list):
            cov["targets"] += 1
        safety = fr.get("safety") if isinstance(fr.get("safety"), dict) else {}
        if isinstance(safety.get("gravity"), list) and len(safety["gravity"]) == 3:
            cov["safety.gravity"] += 1
        if isinstance(safety.get("fallen"), bool):
            cov["safety.fallen"] += 1
        if isinstance(safety.get("limp"), bool):
            cov["safety.limp"] += 1
        # 注意：gyro/head/odom 是 RobotState 顶层字段（lib.rs:2651），不是 safety 下
        if isinstance(fr.get("gyro"), list) and len(fr["gyro"]) == 3:
            cov["gyro"] += 1
        if isinstance(fr.get("head"), list) and len(fr["head"]) == 4:
            cov["head"] += 1
        odom = fr.get("odom") if isinstance(fr.get("odom"), dict) else {}
        if isinstance(odom.get("position"), list) and len(odom["position"]) == 3:
            cov["odom"] += 1
        if isinstance(fr.get("velocities"), list) and len(fr["velocities"]) > 0:
            cov["velocities"] += 1
        if isinstance(fr.get("currents_ma"), list) and len(fr["currents_ma"]) > 0:
            cov["currents_ma"] += 1
    return cov


def _sanity(frames: list[dict]) -> dict:
    total = len(frames)
    n_finite = 0
    n_len15 = 0
    g_mags: list[float] = []
    tilts: list[float] = []
    fallen = 0
    max_abs_joint = 0.0
    for fr in frames:
        st = V.parse_state(fr)
        j = st.joints
        if len(j) == V.N:
            n_len15 += 1
        if all(math.isfinite(x) for x in j):
            n_finite += 1
        max_abs_joint = max(max_abs_joint, max((abs(x) for x in j), default=0.0))
        if st.gravity is not None:
            g_mags.append(math.sqrt(sum(x * x for x in st.gravity)))
            tilts.append(V.gravity_tilt_deg(st.gravity))
        if st.fallen:
            fallen += 1
    return {
        "total": total, "n_finite": n_finite, "n_len15": n_len15,
        "g_min": min(g_mags) if g_mags else None,
        "g_max": max(g_mags) if g_mags else None,
        "tilt_min": min(tilts) if tilts else None,
        "tilt_max": max(tilts) if tilts else None,
        "fallen": fallen,
        "max_abs_joint": max_abs_joint,
    }


def _verify_health(health_path: str) -> dict:
    if not health_path or health_path == "-":
        return {"present": False, "note": "未提供 health 文件"}
    try:
        with open(health_path, "r", encoding="utf-8") as f:
            rep = json.load(f)
    except Exception as e:
        return {"present": False, "note": f"health 读取失败：{e}"}
    if isinstance(rep, dict) and rep.get("_error"):
        return {"present": False, "note": f"抓取时 health 失败：{rep['_error']}"}
    stale, healthy = V._imu_health_from(rep)
    return {"present": True, "stale": stale, "healthy": healthy,
            "note": "解析自 report.robot.imu（真机形状）" if stale is not None
                    else "未解析到 report.robot.imu.consecutive_stale_blocks"}


def _pct(cov: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{cov}/{total} ({100.0*cov/total:.0f}%)"


def main() -> int:
    ap = argparse.ArgumentParser(description="MicroDuck HD-1910 真机字节级对照")
    ap.add_argument("--monitor", default="monitor.ndjson",
                    help="monitor 帧文件(ndjson)；'-' 表示 stdin")
    ap.add_argument("--health", default="health.json",
                    help="health 报告文件(JSON)；不提供则跳过 health 核对")
    args = ap.parse_args()

    frames = _read_frames(args.monitor)
    if not frames:
        print("ERROR：没有解析到任何 monitor 帧。请先用 capture_live.py 抓取。", file=sys.stderr)
        return 1

    cov = _coverage(frames)
    san = _sanity(frames)
    health = _verify_health(args.health)

    print("=" * 64)
    print("MicroDuck HD-1910 真机字节对照报告")
    print("=" * 64)
    print(f"帧数: {san['total']}    来源: {args.monitor}")
    print()
    print("RobotState 字段覆盖（出现次数 / 帧数）：")
    print(f"  {'joints':20s}: {_pct(cov['joints'], san['total'])}")
    print(f"  {'targets':20s}: {_pct(cov['targets'], san['total'])}")
    print(f"  {'safety.gravity':20s}: {_pct(cov['safety.gravity'], san['total'])}  "
          f"← 重力/倾角显示依赖此字段")
    print(f"  {'safety.fallen':20s}: {_pct(cov['safety.fallen'], san['total'])}")
    print(f"  {'safety.limp':20s}: {_pct(cov['safety.limp'], san['total'])}")
    print(f"  {'gyro':20s}: {_pct(cov['gyro'], san['total'])}  "
          f"← 陀螺箭头；0% 则该 robotd 未上报(查看器显示 n/a)")
    print(f"  {'head':20s}: {_pct(cov['head'], san['total'])}")
    print(f"  {'odom':20s}: {_pct(cov['odom'], san['total'])}")
    print(f"  {'velocities':20s}: {_pct(cov['velocities'], san['total'])}  (可选)")
    print(f"  {'currents_ma':20s}: {_pct(cov['currents_ma'], san['total'])}  (可选)")
    print()
    print("合理性检查：")
    print(f"  joint 有限值        : {_pct(san['n_finite'], san['total'])}")
    print(f"  joint 数量 == {V.N:<3d}    : {_pct(san['n_len15'], san['total'])}")
    if san['g_min'] is not None:
        print(f"  gravity |g|≈1       : min={san['g_min']:.4f} max={san['g_max']:.4f}")
        print(f"  倾角 tilt 范围      : {san['tilt_min']:.1f}° .. {san['tilt_max']:.1f}°")
    print(f"  fallen 帧数         : {san['fallen']}")
    print(f"  max |joint|         : {san['max_abs_joint']:.3f} rad")
    print()
    print("IMU 健康（独立 robot.health RPC）：")
    if health["present"]:
        print(f"  stale_blocks       : {health['stale']}")
        print(f"  healthy            : {health['healthy']}")
        print(f"  解析路径           : {health['note']}")
    else:
        print(f"  [跳过] {health['note']}")
    print()
    print("结论：")
    # 决定性结论：哪些字段真机有 / 没有
    if cov["safety.gravity"] == san["total"]:
        print("  ✓ monitor 流暴露 safety.gravity → 查看器重力/倾角显示可用")
    else:
        print(f"  ✗ safety.gravity 仅 {cov['safety.gravity']}/{san['total']} 帧 → "
              f"重力/倾角将显示 n/a（检查 HD-1910 robotd 是否吐该字段）")
    if cov["gyro"] == 0:
        print("  ⚠ gyro 未上报 → 查看器陀螺箭头显示 n/a（不崩，仅缺该箭头）")
    else:
        print(f"  ✓ gyro 已上报（{cov['gyro']}/{san['total']} 帧）→ 陀螺箭头可用")
    if cov["head"] == 0:
        print("  ⚠ head 未上报 → 查看器头部姿态显示 n/a")
    else:
        print(f"  ✓ head 已上报（{cov['head']}/{san['total']} 帧）")
    if cov["odom"] == 0:
        print("  ⚠ odom 未上报 → 查看器里程显示 n/a")
    else:
        print(f"  ✓ odom 已上报（{cov['odom']}/{san['total']} 帧）")
    if health["present"] and health["stale"] is not None:
        print("  ✓ health RPC 形状正确（report.robot.imu.consecutive_stale_blocks 可解析）")
    elif health["present"]:
        print("  ✗ health RPC 形状不匹配 → 检查 report.robot.imu 路径（解析失败）")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
