#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 调试能力扩展门禁（stdlib-only）：锁住 2026-11-21 新增的调试接口跨文件契约。

覆盖三条链（任何一条断都必须红）：
  1. 命令白名单：AiDebugPolicy.COMMANDS 含 gatttrace/rootcause/wifidiag/snapshot，
     且 Receiver 的 when(c.cmd) 对每个都有真实分支（不是写进白名单却没实现）。
  2. GATT 稳定性：AndroidBleGattLink 在 connect 失败路径**每次**都 close（资源泄漏修复），
     且实现 diagnostics()；GattLink 接口有 diagnostics 默认方法；DuckBleService 暴露只读访问器。
  3. 扫描可设窗口：doScan 读 --es arg 且上界绑 AiDebugPolicy.SCAN_WINDOW_MAX_MS（不是硬编码）。

判据：结构化提取 + 元负对照（改坏必红），不锁数量/具体文案数字。
用法：
    python tools/check_ai_debug_extended.py
    python tools/check_ai_debug_extended.py --selftest
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"
CORE = BASE / "core"

PATHS = {
    "policy": CORE / "src/main/kotlin/io/microduck/app/core/AiDebugPolicy.kt",
    "gattlink": CORE / "src/main/kotlin/io/microduck/app/core/GattLink.kt",
    "receiver": APP / "src/debug/kotlin/io/microduck/app/AiDebugReceiver.kt",
    "gatt_impl": APP / "src/main/kotlin/io/microduck/app/ble/AndroidBleGattLink.kt",
    "ble_service": APP / "src/main/kotlin/io/microduck/app/ble/DuckBleService.kt",
}

NEW_CMDS = ("gatttrace", "rootcause", "wifidiag", "snapshot")


def load(srcs: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in PATHS.items():
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
    policy = code_only(srcs.get("policy", ""))
    receiver = code_only(srcs.get("receiver", ""))
    gatt_impl = code_only(srcs.get("gatt_impl", ""))
    gattlink = code_only(srcs.get("gattlink", ""))
    service = code_only(srcs.get("ble_service", ""))

    # ① 命令白名单：从 COMMANDS linkedSetOf 提取完整集合（不裸子串），断言新命令都在。
    m = re.search(r"val COMMANDS\s*:\s*Set<String>\s*=\s*linkedSetOf\((.*?)\)", policy, re.S)
    if not m:
        errs.append("AiDebugPolicy.COMMANDS 结构变了，无法提取（单一权威损坏）")
        cmds: set[str] = set()
    else:
        cmds = set(re.findall(r'"([a-zA-Z][\w.]*)"', m.group(1)))
    for c in NEW_CMDS:
        if c not in cmds:
            errs.append(f"COMMANDS 缺新调试命令 {c}")

    # ② Receiver 必须对每个新命令分发到**专属**实现（防止白名单有、实现无/串到别的命令的假绿）。
    #    判据：显式 "cmd" -> doXxx( 映射，且 doXxx 与各命令名一一对应（不复用同一实现名）。
    dispatch: dict[str, str] = {}
    for c in NEW_CMDS:
        m2 = re.search(rf'"{c}"\s*->\s*(do\w+)\(', receiver)
        if not m2:
            errs.append(f"Receiver 缺 {c} 的分发分支")
        else:
            dispatch[c] = m2.group(1)
    if len(set(dispatch.values())) != len(dispatch) and dispatch:
        errs.append(f"新命令分发到重复实现（疑似占位/串线）：{dispatch}")

    # ③ GATT 失败路径必须 close：abortConnect 存在且被 3 个失败分支调用。
    if "fun abortConnect(" not in gatt_impl or "g.close()" not in gatt_impl:
        errs.append("AndroidBleGattLink 缺 abortConnect/g.close 收尾（失败路径不 close 是资源泄漏）")
    # 三个失败分支各调用一次 abortConnect（按标签计数，不锁具体文案）。
    abort_calls = len(re.findall(r"abortConnect\(g\)", gatt_impl))
    if abort_calls < 3:
        errs.append(f"connect 失败路径 abortConnect 调用不足 3 处（实际 {abort_calls}）：TIMEOUT/STATUS/NO_CHAR 必须都 close")
    # 每处失败都记录**非空**原因标签（TIMEOUT/STATUS=n/NO_CHAR），改空必须红。
    for tag in ('"TIMEOUT"', '"STATUS=$opStatus"', '"NO_CHAR"'):
        if f"lastConnectFailure = {tag}" not in gatt_impl:
            errs.append(f"失败分支缺原因标签 {tag}（rootcause/gatttrace 将读不到原因）")

    # ④ diagnostics 三处贯通：接口默认方法 + 实现 override + service 只读访问器。
    if not re.search(r"fun diagnostics\(\)\s*:\s*String\s*=\s*\"\"", gattlink):
        errs.append("GattLink 缺 diagnostics() 默认方法（会破坏其它实现）")
    if "override fun diagnostics()" not in gatt_impl:
        errs.append("AndroidBleGattLink 未 override diagnostics()（gatttrace 拿不到轨迹）")
    if "fun heldLinkDiagnostics()" not in service or "?.diagnostics()" not in service:
        errs.append("DuckBleService 缺 heldLinkDiagnostics() 只读访问器")

    # ⑤ 扫描窗口上界绑单一权威：**只看 doScan 函数体**（doHelp 里的说明文案不算证据）。
    dm = re.search(r"private fun doScan\([^)]*\)\s*\{(.*?)\n    \}", receiver, re.S)
    do_scan_body = dm.group(1) if dm else ""
    if not do_scan_body:
        errs.append("Receiver 找不到 doScan 函数体")
    if not re.search(r"parsed\s*>\s*AiDebugPolicy\.SCAN_WINDOW_MAX_MS", do_scan_body):
        errs.append("doScan 未用 SCAN_WINDOW_MAX_MS 作窗口上界比较（硬编码会与策略漂移）")
    if not re.search(r"arg\.toLongOrNull\(\)", do_scan_body):
        errs.append("doScan 未解析 --es arg 窗口参数（加长扫描能力缺失）")

    # ⑥ 负对照不变量：FORBIDDEN ∩ (只读放行) 仍为空（新命令没偷偷放开写方法）。
    fm = re.search(r"val FORBIDDEN_METHODS\s*:\s*Set<String>\s*=\s*linkedSetOf\((.*?)\)", policy, re.S)
    rm = re.search(r"val READ_ONLY_METHODS\s*:\s*Set<String>\s*=\s*linkedSetOf\((.*?)\)", policy, re.S)
    if fm and rm:
        forbidden = set(re.findall(r"Method\.(\w+)", fm.group(1)))
        allowed = set(re.findall(r"Method\.(\w+)", rm.group(1)))
        if forbidden & allowed:
            errs.append(f"只读白名单混入禁止方法：{sorted(forbidden & allowed)}")
    else:
        errs.append("FORBIDDEN/READ_ONLY 方法集提取失败")

    # ⑦ snapshot 方法子集：单一权威在 policy，元素必须是 Method 常量（不是裸字符串），
    #    且 ⊆ READ_ONLY_METHODS、∩ FORBIDDEN_METHODS=∅。防止 snapshot 用写方法/已放开方法。
    sm = re.search(r"val SNAPSHOT_METHODS\s*:\s*List<String>\s*=\s*listOf\((.*?)\)", policy, re.S)
    if not sm:
        errs.append("AiDebugPolicy 缺 SNAPSHOT_METHODS 单一权威（snapshot 方法名散落会漂移）")
    else:
        snap_block = sm.group(1)
        snap = set(re.findall(r"Method\.(\w+)", snap_block))
        bare = re.findall(r'"([a-z.]+\.[a-z.]+)"', snap_block)
        if bare:
            errs.append(f"SNAPSHOT_METHODS 含裸字符串方法名（应走 Method 常量）：{bare}")
        if not snap:
            errs.append("SNAPSHOT_METHODS 提取不到任何 Method 常量")
        if fm and rm:
            if snap & forbidden:
                errs.append(f"SNAPSHOT_METHODS 混入禁止方法：{sorted(snap & forbidden)}")
            if not snap <= allowed:
                errs.append(f"SNAPSHOT_METHODS 不在只读白名单内：{sorted(snap - allowed)}")
    # Receiver 的 snapshot 实现必须消费该权威，不得自己写死方法名列表。
    dm2 = re.search(r"private fun doSnapshot\([^)]*\)\s*\{(.*?)\n    \}", receiver, re.S)
    snap_body = dm2.group(1) if dm2 else ""
    if "AiDebugPolicy.SNAPSHOT_METHODS" not in snap_body:
        errs.append("doSnapshot 未用 AiDebugPolicy.SNAPSHOT_METHODS（硬编码方法名会漂移）")
    if re.search(r'listOf\("system\.info"', snap_body):
        errs.append("doSnapshot 仍有硬编码方法名字符串列表")

    # ⑧ rootcause 不得臆造「unit 白名单」约束（一手 LogsParams 只约束键名 deny_unknown_fields）。
    #    在 doRootCause 函数体内检查，不扫全文注释。
    dm3 = re.search(r"private fun doRootCause\([^)]*\)\s*\{(.*?)\n    \}", receiver, re.S)
    rc_body = dm3.group(1) if dm3 else ""
    if "unit 仅接受固定白名单" in rc_body:
        errs.append("doRootCause 仍输出无一手依据的「unit 固定白名单」提示（误导 AI）")
    if "board_logs_hint" not in rc_body or "system.services" not in rc_body:
        errs.append("doRootCause 缺 board_logs_hint 或 unit 来源指引（system.services）")

    return errs


def _trial_patches(base: dict[str, str]) -> list[tuple[str, dict[str, str]]]:
    """负对照单一权威：每项只改坏一条判据，必须让 check() 变红。"""
    return [
        ("改坏:白名单去掉 snapshot", {"policy": base["policy"].replace(
            '"gatttrace", "rootcause", "wifidiag", "snapshot",',
            '"gatttrace", "rootcause", "wifidiag",')}),
        ("改坏:Receiver 去掉 gatttrace 分支", {"receiver": base["receiver"].replace(
            '"gatttrace" -> doGattTrace(o)', '/* gatttrace removed */')}),
        ("改坏:新命令串到重复实现", {"receiver": base["receiver"].replace(
            '"snapshot" -> doSnapshot(ctx, c)', '"snapshot" -> doGattTrace(o)')}),
        ("改坏:失败路径不 close", {"gatt_impl": base["gatt_impl"].replace(
            "abortConnect(g)", "/* no close */", 1)}),
        ("改坏:丢掉一处 lastConnectFailure", {"gatt_impl": base["gatt_impl"].replace(
            'lastConnectFailure = "TIMEOUT"', 'lastConnectFailure = ""', 1)}),
        ("改坏:GattLink 无 diagnostics", {"gattlink": base["gattlink"].replace(
            'fun diagnostics(): String = ""', 'fun diagnostics_REMOVED(): String = ""', 1)}),
        ("改坏:service 无访问器", {"ble_service": base["ble_service"].replace(
            "fun heldLinkDiagnostics()", "fun heldLinkDiagnostics_REMOVED()", 1)}),
        ("改坏:扫描窗口硬编码绕过策略", {"receiver": base["receiver"].replace(
            "parsed > AiDebugPolicy.SCAN_WINDOW_MAX_MS", "parsed > 20000", 1)}),
        ("改坏:只读白名单混入写方法", {"policy": base["policy"].replace(
            "Method.SYSTEM_INFO,", "Method.SYSTEM_INFO,\n        Method.ROBOT_MOVE,", 1)}),
        ("改坏:snapshot 子集混入写方法", {"policy": base["policy"].replace(
            "Method.SYSTEM_INFO,\n        Method.ROBOT_HEALTH,",
            "Method.ROBOT_MOVE,\n        Method.ROBOT_HEALTH,", 1)}),
        ("改坏:snapshot 子集用裸字符串", {"policy": base["policy"].replace(
            "Method.SYSTEM_INFO,\n        Method.ROBOT_HEALTH,",
            '"system.info",\n        Method.ROBOT_HEALTH,', 1)}),
        ("改坏:doSnapshot 硬编码方法名", {"receiver": base["receiver"].replace(
            "for (m in AiDebugPolicy.SNAPSHOT_METHODS)",
            'for (m in listOf("system.info", "robot.health"))', 1)}),
        ("改坏:rootcause 恢复臆造 unit 白名单", {"receiver": base["receiver"].replace(
            "unit 填 system.services 回报的真实 systemd 单元名，无白名单",
            "unit 仅接受固定白名单")}),
    ]


TRIALS = _trial_patches


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
    ap = argparse.ArgumentParser(description="AI 调试能力扩展门禁（诊断/Wi-Fi/聚合/GATT 稳定性）")
    ap.add_argument("--selftest", action="store_true", help="跑元负对照")
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
