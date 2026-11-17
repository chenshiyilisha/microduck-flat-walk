#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 3「面板组件状态解耦」的结构化静态检查器（stdlib-only）。

为什么需要它：阶段 2 升级了 check_hardware_monitor.py 锁 ViewModel 三链真源，
但三个面板（SshPanel / UpdatePanel / BleConnectPanel）的解耦没有任何门禁覆盖
（2026-11-16 审计：tools/ 下 0 处面板类名断言）。没有判据 ⇒ 后人或我自己把面板
改回「自管 session / 双真源」也无人发现。本工具补这道防线。

判据（绑定官方一手 state hoisting 原则，见重构规划 §2.1）：
  · 由数据层产生的 screen state（SSH 会话、更新流程）→ 单一真源 Repository，
    面板只订阅 onSnapshot + 发事件，不持有 Session / SshClient / 流程状态字段。
  · 瞬时 UI element state（凭据输入框、TerminalEmulator 渲染缓冲、BLE 扫描列表）
    → 留在组件内部（官方「keep state closest to where it is consumed」），
    防止「为了纯展示而过度掏空」这一反向错误。
  · 旧双真源 UpdateController.kt 必须消失。

判据独立于被测值：只锁结构性签名与「字段不存在」，不锁文本内容/数量。
verdict: OK / NOT_PASS；末尾打印 RESULT: N errors。

用法：
    python tools/check_panel_decoupling.py
    python tools/check_panel_decoupling.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app/src/main/kotlin/io/microduck/app"

FILES = {
    "ssh_panel": APP / "ssh/SshPanel.kt",
    "ssh_repo": APP / "ssh/SshRepository.kt",
    "update_panel": APP / "update/UpdatePanel.kt",
    "update_repo": APP / "update/UpdateRepository.kt",
    "ble_panel": APP / "ble/BleConnectPanel.kt",
    "main": APP / "MainActivity.kt",
}

# 旧双真源文件必须不存在
STALE = [APP / "update/UpdateController.kt"]


def load_all() -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in FILES.items():
        try:
            out[k] = p.read_text(encoding="utf-8")
        except OSError:
            out[k] = ""
    return out


def code_only(src: str) -> str:
    """去掉 // 行注释与块注释，避免注释里提到某符号就算数（防假绿）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def evaluate(src: dict[str, str], quiet: bool = False) -> tuple[str, list[str]]:
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    sp = code_only(src.get("ssh_panel", ""))
    sr = code_only(src.get("ssh_repo", ""))
    up = code_only(src.get("update_panel", ""))
    ur = code_only(src.get("update_repo", ""))
    bp = code_only(src.get("ble_panel", ""))
    main = code_only(src.get("main", ""))

    # ① 文件存在性（前提缺失 → UNVERIFIED，不让后面的绿顶数）
    for k, label in FILES.items():
        need(bool(src.get(k)), f"{label} 缺失或为空")
    if any(not src.get(k) for k in FILES):
        if not quiet:
            print(f"VERDICT = UNVERIFIED_ARTIFACTS_ABSENT")
        return "UNVERIFIED_ARTIFACTS_ABSENT", errs

    # ② 旧双真源必须消失
    for p in STALE:
        need(not p.exists(), f"旧双真源文件仍存在：{p.name}（阶段3应删除）")

    # ③ SshPanel：不持有 session/client，构造注入 Repository，订阅快照
    need("Session" not in sp, "SshPanel 仍 import/持有 Session（数据层状态应在 Repository）")
    need("SshClient" not in sp, "SshPanel 仍持有 SshClient（连接逻辑应在 Repository）")
    need("SshRepository" in sp, "SshPanel 未引用 SshRepository")
    need(re.search(r"repository\.onSnapshot", sp) is not None,
         "SshPanel 未订阅仓库快照（状态无法从单一真源回推）")
    need(re.search(r"repository\.(connect|disconnect|exec|release)\s*\(", sp) is not None,
         "SshPanel 未把连接/命令事件委托给 Repository")
    # UI element state 必须保留（防过度掏空）
    need("TerminalEmulator" in sp, "SshPanel 丢了终端 ANSI 渲染缓冲（瞬时 UI state 应留组件内）")
    need("EditText" in sp or "hostEdit" in sp, "SshPanel 丢了凭据输入框（瞬时 UI state 应留组件内）")

    # ④ SshRepository：onSnapshot 单一出口 + 累积输出（面板不再自管历史）
    need("onSnapshot" in sr and "fun snapshot" in sr, "SshRepository 缺快照出口")
    need("appendTerminal" in sr, "SshRepository 缺累积输出（面板已不自管终端缓冲）")

    # ⑤ UpdatePanel：不自管流程状态，构造注入 Repository，订阅快照
    need("UpdateController" not in up, "UpdatePanel 仍依赖已删的 UpdateController")
    need("UpdateRepository" in up, "UpdatePanel 未引用 UpdateRepository")
    need(re.search(r"repository\.onSnapshot", up) is not None,
         "UpdatePanel 未订阅仓库快照")
    need(re.search(r"repository\.(check|downloadAndInstall)\s*\(", up) is not None,
         "UpdatePanel 未把检查/下载事件委托给 Repository")
    need("lastState" not in up and "releaseUrl: String?" not in up,
         "UpdatePanel 仍自管 lastState/releaseUrl（流程状态应在 Repository）")

    # ⑥ UpdateRepository：单一出口 + 权限回调入口（面板 onResume 委托过来）
    need("onSnapshot" in ur and "fun snapshot" in ur, "UpdateRepository 缺快照出口")
    need("onInstallPermissionGranted" in ur, "UpdateRepository 缺权限回调入口")

    # ⑦ BleConnectPanel：瞬时扫描状态留在组件内（官方原则），不因"纯展示"被掏空
    need("ScanCallback" in bp and "found" in bp,
         "BleConnectPanel 丢了扫描列表/回调（瞬时 UI element state 应留组件内）")

    # ⑧ MainActivity：Repository 作为单一真源被实例化并注入面板
    need("SshRepository" in main and "UpdateRepository" in main,
         "MainActivity 未实例化 SshRepository / UpdateRepository")
    need(re.search(r"SshPanel\([^)]*sshRepository", main) is not None,
         "SshPanel 构造未注入 sshRepository 单例")
    need(re.search(r"UpdatePanel\([^)]*updateRepository", main) is not None,
         "UpdatePanel 构造未注入 updateRepository 单例")

    verdict = "NOT_PASS" if errs else "OK"
    if not quiet:
        print(f"VERDICT = {verdict}")
        print(f"RESULT: {len(errs)} errors")
    return verdict, errs


def selftest(src: dict[str, str]) -> list[tuple[str, bool]]:
    """注入式负对照：把解耦改坏，判据必须变红。只见过绿的断言不是证据。"""
    def variant(**kw: str) -> dict[str, str]:
        return {**src, **kw}

    sp = src.get("ssh_panel", "")
    up = src.get("update_panel", "")
    ur = src.get("update_repo", "")
    main = src.get("main", "")

    cases: list[tuple[str, dict[str, str]]] = [
        # SshPanel 退回自管 session ⇒ 必红
        ("SshPanel 恢复自管 Session 必红",
         variant(ssh_panel=sp + "\nprivate var session: Session? = null\n")),
        ("SshPanel 去掉快照订阅必红",
         variant(ssh_panel=sp.replace("repository.onSnapshot", "NO_SUBSCRIBE"))),
        ("SshPanel 掏空终端缓冲必红",
         variant(ssh_panel=sp.replace("TerminalEmulator", "PlainText"))),
        # UpdatePanel 退回自管流程状态 ⇒ 必红
        ("UpdatePanel 恢复 lastState 必红",
         variant(update_panel=up + "\nprivate var lastState: Int = 0\n")),
        ("UpdatePanel 去掉快照订阅必红",
         variant(update_panel=up.replace("repository.onSnapshot", "NO_SUBSCRIBE"))),
        # Repository 退化 ⇒ 必红
        ("SshRepository 去掉累积输出必红",
         variant(ssh_repo=src.get("ssh_repo", "").replace("appendTerminal", "discard"))),
        ("UpdateRepository 去掉权限回调必红",
         variant(update_repo=ur.replace("onInstallPermissionGranted", "noOp"))),
        # MainActivity 注入断链 ⇒ 必红
        ("MainActivity 断 SshPanel 注入必红",
         variant(main=main.replace("SshPanel(this, sshRepository)", "SshPanel(this)"))),
        ("MainActivity 断 UpdatePanel 注入必红",
         variant(main=main.replace("UpdatePanel(this, updateRepository)", "UpdatePanel(this)"))),
    ]

    out: list[tuple[str, bool]] = []
    for label, evidence in cases:
        verdict, errs = evaluate(evidence, quiet=True)
        out.append((label, verdict != "OK" and len(errs) > 0))
    # 正对照：未改动源码必须零错误
    base_v, base_e = evaluate(src, quiet=True)
    out.append(("正对照:未改动源码零错误", base_v == "OK" and not base_e))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="跑注入式负对照")
    args = ap.parse_args()
    src = load_all()
    verdict, errs = evaluate(src)
    for e in errs:
        print("  ERROR  " + e)
    rc = 1 if (errs or verdict not in ("OK",)) else 0
    if args.selftest:
        print("\n=== 注入式负对照 ===")
        checks = selftest(src)
        for label, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + label)
            if not ok:
                rc = 1
        n = sum(1 for _, ok in checks if ok)
        print(f"SELFTEST: {n}/{len(checks)} passed")
        # verdict UNVERIFIED 时正对照会红，rc 已非 0，不重复计入。
    return rc


if __name__ == "__main__":
    sys.exit(main())
