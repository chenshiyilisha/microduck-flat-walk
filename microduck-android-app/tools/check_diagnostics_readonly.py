#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A3/A6/A7 只读诊断门禁：确保系统信息/服务/日志、策略/模型、更新状态
这条只读链路的结构约束不被无声回退（stdlib-only）。

为什么需要它：这三个功能只做只读展示，零运动风险。最容易被后人「顺手」破坏的
是三条铁律：① 把只读方法误当写类（丢失断链重放能力）；② Mock 下也去查（伪造实机
读数）；③ 缺字段被填成 0/false（造假）。纯功能测试锁不住这些结构性质，故设门禁。

判据（绑一手 fanhao 副本 API40 lib.rs / route.rs）：
  · Wire.Method 必有 system.services / update.listInstalled / update.log 等常量；
  · system.logs 的 deny_unknown_fields ⇒ 源码写键时只用 unit/lines/boot 三键；
  · RobotSession.isReadOnly 白名单包含全部新增只读方法；
  · RobotRepository.refreshDiagnostics 必须 Mock 不查 + 未 READY 不查；
  · UI 必须有刷新入口且经 ViewModel（不绕过用户主动触发）。

判据独立于被测值：只锁结构性签名，不锁文本内容/数量。
verdict: OK / NOT_PASS / UNVERIFIED_ARTIFACTS_ABSENT；末尾打印 RESULT: N errors。

用法：
    python tools/check_diagnostics_readonly.py
    python tools/check_diagnostics_readonly.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CORE = BASE / "core/src/main/kotlin/io/microduck/app/core"
APP = BASE / "app/src/main/kotlin/io/microduck/app"

FILES = {
    "wire": CORE / "Wire.kt",
    "session": CORE / "RobotSession.kt",
    "repo": CORE / "RobotRepository.kt",
    "diag": CORE / "DiagnosticsSnapshot.kt",
    "vm": APP / "MainViewModel.kt",
    "activity": APP / "MainActivity.kt",
}

# 一手 lib.rs：这些是只读诊断方法，必须进 isReadOnly 白名单
READ_ONLY_METHODS = [
    "SYSTEM_INFO", "SYSTEM_SERVICES", "SYSTEM_LOGS",
    "ROBOT_POLICIES", "ROBOT_MODEL", "UPDATE_STATUS", "UPDATE_LIST_INSTALLED", "UPDATE_LOG",
]

# Wire.Method 必须定义的方法名常量（字符串字面值，抄自 lib.rs pub mod method）
METHOD_CONSTANTS = {
    "SYSTEM_SERVICES": "system.services",
    "UPDATE_LIST_INSTALLED": "update.listInstalled",
    "UPDATE_LOG": "update.log",
    "NET_FORGET": "net.forget",
}


def load_all() -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in FILES.items():
        try:
            out[k] = p.read_text(encoding="utf-8")
        except OSError:
            out[k] = ""
    return out


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def body_of(src: str, signature: str) -> str:
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find("{", i)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
    return src[j:]


def evaluate(src: dict[str, str], quiet: bool = False) -> tuple[str, list[str]]:
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    for k, p in FILES.items():
        need(bool(src.get(k)), f"{k} 缺失或为空：{p}")
    if any(not src.get(k) for k in FILES):
        if not quiet:
            print("VERDICT = UNVERIFIED_ARTIFACTS_ABSENT")
        return "UNVERIFIED_ARTIFACTS_ABSENT", errs

    wire = code_only(src["wire"])
    session = code_only(src["session"])
    repo = code_only(src["repo"])
    diag = code_only(src["diag"])
    vm = code_only(src["vm"])
    act = code_only(src["activity"])

    # ① Wire.Method 常量（一手方法名，别自创）
    for name, value in METHOD_CONSTANTS.items():
        need(re.search(rf"const val {name}\s*=\s*\"{re.escape(value)}\"", wire) is not None,
             f"Wire.Method 缺 {name} = \"{value}\"")

    # ② 只读白名单包含全部诊断方法（isReadOnly 是 = method in setOf(...) 表达式体，
    #    用圆括号提取，不能用 body_of 找花括号 —— 会跨到下一个函数）
    ro_m = re.search(r"private fun isReadOnly\([^)]*\)\s*:\s*Boolean\s*=\s*method in setOf\(([^)]*)\)",
                     session, re.S)
    need(ro_m is not None, "RobotSession.isReadOnly 的 setOf 白名单未找到")
    ro = ro_m.group(1) if ro_m else ""
    for name in READ_ONLY_METHODS:
        need(f"Method.{name}" in ro, f"isReadOnly 白名单缺 Method.{name}（断链后无法安全重放）")

    # ③ system.logs 的 deny_unknown_fields：参数只准 unit/lines/boot
    refresh = body_of(repo, "fun refreshDiagnostics()")
    need(bool(refresh), "RobotRepository.refreshDiagnostics 函数体未找到")
    logs_call = re.search(r"Method\.SYSTEM_LOGS\s*,\s*mapOf\(([^)]*)\)", refresh)
    need(logs_call is not None, "refreshDiagnostics 未按一手契约传 LogsParams")
    if logs_call:
        keys = set(re.findall(r'"(\w+)"\s+to', logs_call.group(1)))
        need(keys == {"unit", "lines", "boot"},
             f"LogsParams 键集不符 deny_unknown_fields（应 unit/lines/boot，实际 {keys}）")

    # ④ Mock 不查 + 未 READY 不查（防伪造实机读数）
    need("kind == \"MOCK\"" in refresh, "refreshDiagnostics 未排除 Mock（伪造实机读数）")
    need("RobotSession.State.READY" in refresh, "refreshDiagnostics 未要求会话 READY")

    # ⑤ 缺数据不造假：解析器用 nullable / emptyList，不填 0/false
    need("data class DiagnosticsSnapshot" in diag, "DiagnosticsSnapshot 数据类缺失")
    need("isEmpty" in diag, "DiagnosticsSnapshot 缺 isEmpty（UI 无法区分未查询/空数据）")
    need("?: return emptyList()" in diag or "?: emptyList()" in diag,
         "诊断解析缺空列表兜底（缺数据可能造假）")

    # ⑥ UI：刷新入口经 ViewModel，且健康页有诊断文本
    need(re.search(r"fun onRefreshDiagnostics\(\)", vm) is not None,
         "MainViewModel 缺 onRefreshDiagnostics 事件入口")
    need(re.search(r"viewModel\.onRefreshDiagnostics\(\)", act) is not None,
         "MainActivity 未把刷新按钮接到 ViewModel")
    need("diagnosticsText" in act, "MainActivity 健康页缺诊断展示文本")

    verdict = "NOT_PASS" if errs else "OK"
    if not quiet:
        print(f"VERDICT = {verdict}")
        print(f"RESULT: {len(errs)} errors")
    return verdict, errs


def selftest(src: dict[str, str]) -> list[tuple[str, bool]]:
    """注入式负对照：把只读链路改坏，判据必须变红。"""
    def variant(**kw: str) -> dict[str, str]:
        return {**src, **kw}

    wire = src.get("wire", "")
    session = src.get("session", "")
    repo = src.get("repo", "")
    vm = src.get("vm", "")

    cases: list[tuple[str, dict[str, str]]] = [
        ("负对照:Wire 删 system.services 常量必红",
         variant(wire=wire.replace('const val SYSTEM_SERVICES = "system.services"', ''))),
        ("负对照:isReadOnly 剔除 system.logs 必红",
         variant(session=session.replace("Method.SYSTEM_LOGS,", ""))),
        ("负对照:LogsParams 多带非法键必红",
         variant(repo=repo.replace('"unit" to "robotd", "lines" to 80, "boot" to 0',
                                   '"unit" to "robotd", "extra" to 1'))),
        ("负对照:refreshDiagnostics 放开 Mock 必红",
         variant(repo=repo.replace('kind == "MOCK" || ', ''))),
        ("负对照:ViewModel 删刷新入口必红",
         variant(vm=vm.replace("fun onRefreshDiagnostics()", "fun noRefresh()"))),
    ]

    out: list[tuple[str, bool]] = []
    for label, evidence in cases:
        verdict, errs = evaluate(evidence, quiet=True)
        out.append((label, verdict != "OK" and len(errs) > 0))
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
    return rc


if __name__ == "__main__":
    sys.exit(main())
