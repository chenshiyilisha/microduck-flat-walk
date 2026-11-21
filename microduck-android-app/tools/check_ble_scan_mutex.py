#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE 扫描互斥门禁（stdlib-only）：锁住「code=1 是 App 内重复扫描，不是硬件/权限」这条
一手协议性质，并确认设置页与 AI 调试扫描都过同一把互斥闸。

一手依据：Android 官方 `ScanCallback` API：
  SCAN_FAILED_ALREADY_STARTED = 1 (0x00000001)，
  "Fails to start scan as BLE scan with the same settings is already started by the app."
真机截图文案「扫描失败 code=1。请确认蓝牙/定位开关…」是错误归因。

判据：结构签名 + 元负对照（把互斥调用改坏必须红），不锁数量/文案数字。
用法：
    python tools/check_ble_scan_mutex.py
    python tools/check_ble_scan_mutex.py --selftest
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
COORD = BASE / "app/src/main/kotlin/io/microduck/app/ble/BleScanCoordinator.kt"
PANEL = BASE / "app/src/main/kotlin/io/microduck/app/ble/BleConnectPanel.kt"
DEBUG = BASE / "app/src/debug/kotlin/io/microduck/app/AiDebugReceiver.kt"

FILES = {"coord": COORD, "panel": PANEL, "debug": DEBUG}


def load(srcs: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in FILES.items():
        try:
            out[k] = srcs[k] if srcs and k in srcs else p.read_text(encoding="utf-8")
        except OSError:
            out[k] = ""
    return out


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


def check(srcs: dict[str, str]) -> list[str]:
    errs: list[str] = []
    coord, panel, debug = (code_only(srcs.get(k, "")) for k in ("coord", "panel", "debug"))

    # ① 常量值与官方定义
    if not re.search(r"SCAN_FAILED_ALREADY_STARTED\s*[:=]\s*Int\s*=\s*1\b", coord):
        errs.append("协调器缺官方常量 SCAN_FAILED_ALREADY_STARTED = 1")
    if "already started **by the app**" not in srcs.get("coord", ""):
        errs.append("协调器缺一手依据注释（by the app）")

    # ② 协调器必须能停旧扫描 + 解释失败码
    if "stopScan(prev)" not in coord or "current = cb" not in coord:
        errs.append("协调器 begin() 未真正持有/停止旧 callback")
    # 🔴 真机回归：begin() 不得因 prev===cb 提前 return。设置页用单例 scanCallback，
    # 若同一 callback 跳过 stop，则 code=1 重试/连点时系统侧旧扫描没停 → 必然再次 code=1。
    if re.search(r"if\s*\(\s*prev\s*===\s*cb\s*\)\s*return", coord):
        errs.append("协调器 begin() 因 prev===cb 提前 return：单例 callback 重试将永不再 stop，必然 code=1")
    if "fun explain(errorCode: Int)" not in coord or "ALREADY_STARTED" not in coord:
        errs.append("协调器缺失败码解释（code=1 不得再误导成蓝牙/定位开关）")

    # ③ 设置页必须挂协调器，且 code=1 有界重试
    if "BleScanCoordinator.begin(adapter, scanCallback)" not in panel:
        errs.append("设置页 startScan 未过互斥闸")
    if "BleScanCoordinator.end(scanCallback)" not in panel:
        errs.append("设置页 stopScan 未归还互斥闸")
    if ("SCAN_FAILED_ALREADY_STARTED" not in panel or "retried" not in panel or
            "startScan(isRetry = true)" not in panel):
        errs.append("设置页 code=1 未做有界重试（只报错不算恢复）")
    if "请确认蓝牙/定位开关已开，或改用 TCP relay" in panel:
        errs.append("设置页仍把扫描失败统一误导成蓝牙/定位开关问题")

    # ④ AI 调试扫描必须挂同一把闸
    if "BleScanCoordinator.begin(adapter, cb)" not in debug:
        errs.append("AI 调试 scan 未过互斥闸（会与设置页撞 code=1）")
    if "BleScanCoordinator.end(cb)" not in debug:
        errs.append("AI 调试 scan 结束未归还互斥闸")
    if "BleScanCoordinator.explain(errorCode)" not in debug:
        errs.append("AI 调试 scan 未用统一失败码解释")

    return errs


def meta_negative_control() -> list[str]:
    base = load()
    errs: list[str] = []
    if check(base):
        errs.append("元验证前置失败：正常源码下门禁就不 OK")
        return errs
    trials = [
        ("改坏:常量改成2", {"coord": base["coord"].replace(
            "SCAN_FAILED_ALREADY_STARTED: Int = 1", "SCAN_FAILED_ALREADY_STARTED: Int = 2")}),
        ("改坏:协调器不停旧扫描", {"coord": base["coord"].replace("stopScan(prev)", "stopScan(bogus)")}),
        ("改坏:同一callback跳过stop(真机code=1根因)", {"coord": base["coord"].replace(
            "        val prev = current\n", "        val prev = current\n        if (prev === cb) return\n", 1)}),
        ("改坏:设置页绕过互斥", {"panel": base["panel"].replace(
            "BleScanCoordinator.begin(adapter, scanCallback)", "")}),
        ("改坏:设置页去掉重试", {"panel": base["panel"].replace(
            "startScan(isRetry = true)", "startScan()")}),
        ("改坏:调试扫描绕过互斥", {"debug": base["debug"].replace(
            "BleScanCoordinator.begin(adapter, cb)", "")}),
    ]
    for label, patch in trials:
        srcs = dict(base)
        srcs.update(patch)
        if not check(srcs):
            errs.append(f"元负对照失效：{label} 后门禁仍 OK（假绿）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="运行元负对照")
    a = ap.parse_args()
    errs = meta_negative_control() if a.selftest else check(load())
    for e in errs:
        print("ERROR:", e)
    if a.selftest:
        trials = 6
        print(f"SELFTEST: {trials - len(errs)}/{trials} passed")
    print(f"RESULT: {len(errs)} errors")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
