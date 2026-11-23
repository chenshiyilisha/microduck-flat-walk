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
GATT = BASE / "app/src/main/kotlin/io/microduck/app/ble/AndroidBleGattLink.kt"

FILES = {"coord": COORD, "panel": PANEL, "debug": DEBUG, "gatt": GATT}


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

    # ⑤ 失败分类可达性（GATT 诊断三标签）：awaitConnectReady=false 后必须按 opStatus
    #    分流到 NO_CHAR / TIMEOUT / STATUS，不能一律 TIMEOUT（那样 gatttrace/rootcause
    #    永远读不到真因）。判据绑 opStatus 分支结构，不锁具体文案数字。
    if "gatt" not in srcs or srcs["gatt"] == "":
        errs.append("缺 AndroidBleGattLink.kt，无法核 GATT 失败分类")
    else:
        gatt = code_only(srcs["gatt"])
        cm = re.search(r"if\s*\(!awaitConnectReady\(\)\)\s*\{(.*?)\n        \}", gatt, re.S)
        if not cm:
            errs.append("GATT connect 找不到 awaitConnectReady 失败分支")
        else:
            body = cm.group(1)
            if "when (opStatus)" not in body:
                errs.append("GATT 失败未按 opStatus 分流（一律 TIMEOUT 会丢真因）")
            for label in ("NO_CHAR", "TIMEOUT", "STATUS=$opStatus"):
                if f'lastConnectFailure = "{label}"' not in body:
                    errs.append(f"GATT 失败分支缺可达标签 {label}")
            if body.count("abortConnect(g)") < 3:
                errs.append("GATT 三失败分支未各自 close（资源泄漏/闸位残留）")

    # ⑥ 互斥闸 stop/start 必须同一 adapter（多卡设备 stop 错卡会让旧扫描残留）
    if "BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner?.stopScan" in coord:
        errs.append("协调器 end() 用 getDefaultAdapter stop，与 begin 的 adapter 可能不同卡")
    if "activeAdapter" not in coord or "activeAdapter?.bluetoothLeScanner?.stopScan" not in coord:
        errs.append("协调器未记住 begin 的 adapter 用于 stop")

    # ⑦ code=1 重试路径：先只 stop + 空窗收敛，不得在 start 前再 begin（会吃掉收敛间隔/撞 code=6）。
    #    判据绑 onScanFailed 内调用 stop 而非 begin，且 stopScan 能力存在于协调器。
    if "fun stop(cb: ScanCallback)" not in coord or "fun end(cb: ScanCallback)" not in coord:
        errs.append("协调器缺 stop()/end()（重试无法只停不登记）")
    pfm = re.search(r"onScanFailed\(errorCode: Int\)\s*\{(.*?)\n        \}", panel, re.S)
    if not pfm:
        errs.append("设置页找不到 onScanFailed")
    else:
        pf = pfm.group(1)
        if "BleScanCoordinator.stop(this)" not in pf:
            errs.append("code=1 重试未用 stop 归还闸位（旧 begin 重试会再 stop 吃收敛间隔）")
        if re.search(r"BleScanCoordinator\.begin\(", pf):
            errs.append("onScanFailed 重试路径又调 begin：紧贴 start 的第二次 stop 会吃掉 500ms 收敛")
    # startScan 异常路径必须归还闸位（begin 后 start 抛异常会残留 current）
    if panel.count("BleScanCoordinator.end(scanCallback)") < 3:
        errs.append("设置页 start/onScanFailed 异常路径未全部归还互斥闸（残留 current 卡下次扫描）")
    if debug.count("BleScanCoordinator.end(cb)") < 2:
        errs.append("AI 调试 scan 的 start 异常路径未归还互斥闸")

    return errs


def _trial_patches(base: dict[str, str]) -> list[tuple[str, dict[str, str]]]:
    """负对照单一权威：每项只改坏一条判据，必须让 check() 变红。"""
    return [
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
        ("改坏:GATT 失败一律 TIMEOUT（丢真因）", {"gatt": base["gatt"].replace(
            "when (opStatus)", "when (true)")}),
        ("改坏:GATT 缺 NO_CHAR 标签", {"gatt": base["gatt"].replace(
            'lastConnectFailure = "NO_CHAR"', 'lastConnectFailure = "X"')}),
        ("改坏:end 用默认 adapter（多卡 stop 错卡）", {"coord": base["coord"].replace(
            "activeAdapter?.bluetoothLeScanner?.stopScan(cb)",
            "BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner?.stopScan(cb)")}),
        ("改坏:重试路径回到 begin（吃收敛间隔）", {"panel": base["panel"].replace(
            "BleScanCoordinator.stop(this)", "bleAdapter?.let { BleScanCoordinator.begin(it, this) }")}),
        ("改坏:协调器无 stop（重试无法只停不登记）", {"coord": base["coord"].replace(
            "fun stop(cb: ScanCallback)", "fun stopV2(cb: ScanCallback)")}),
        ("改坏:设置页 start 异常不归还闸位", {"panel": base["panel"].replace(
            "            BleScanCoordinator.end(scanCallback)\n            scanning = false\n            setStatus(\"⚠ 权限被撤销",
            "            scanning = false\n            setStatus(\"⚠ 权限被撤销")}),
        ("改坏:AI scan 启动异常不归还闸位", {"debug": base["debug"].replace(
            "            io.microduck.app.ble.BleScanCoordinator.end(cb)\n            o.fail(\"SCAN_START_FAILED",
            "            o.fail(\"SCAN_START_FAILED")}),
    ]


TRIALS = _trial_patches  # 供 selftest 取长度，避免计数写死


def meta_negative_control() -> list[str]:
    base = load()
    errs: list[str] = []
    if check(base):
        errs.append("元验证前置失败：正常源码下门禁就不 OK")
        return errs
    for label, patch in _trial_patches(base):
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
        trials = len(TRIALS(load()))
        print(f"SELFTEST: {trials - len(errs)}/{trials} passed")
    print(f"RESULT: {len(errs)} errors")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
