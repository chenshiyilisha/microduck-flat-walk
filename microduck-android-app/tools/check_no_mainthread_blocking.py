#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ANR 门禁：地址栏/传输建链不得在主线程同步阻塞（stdlib-only）。

为什么需要它（2026-11-17 anr-audit-and-fix skill 审计发现的真问题）：
  主线程调用链 connectFromUi()(onCreate/点击) → viewModel.onConnect()
  → robotRepository.connect() → connectWith() → RobotSession.connect()
  → TcpTransport.connect()(socket connect 超时 2s) + handshake()(每请求 latch.await 5s)
  最坏把主线程卡住约 7s ⇒ ANR。真机 Mock 不触发（内存），但地址栏填真实 TCP
  地址或配网后走 TCP 就必现卡顿。文本门禁与真机短连接都照不出，故设静态判据锁住。

判据（绑一手事实，不锁文本数量）：
  · 阻塞根在 core：TcpTransport.connect 真做 socket.connect(timeout)，
    RobotSession.connect 同步调 transport.connect + handshake。这些是「阻塞源」，
    门禁不断言它们消失（它们本就该阻塞），而是断言**调用方切了线程**。
  · 修复点在 app：MainViewModel.onConnect / onConnectWith 内必须用 Dispatchers.IO
    启动建链；onConnectWith 的 onDone 必须用 Dispatchers.Main 回主线程。
  · 主线程调用点 connectFromUi() 只能调 viewModel.onConnect（不直接碰 Repository/Transport）。
  · 编译产物（MainViewModel.class 的 DEX）另由真机/反编译侧核；本脚本锁源码结构。

判据独立于被测值：只锁「阻塞调用是否包在 IO 协程里」这一结构性质，
带注入式负对照（把 Dispatchers.IO 换成 Main、把 onDone 切主线程删掉必红）。
verdict: OK / NOT_PASS / UNVERIFIED_ARTIFACTS_ABSENT；末尾打印 RESULT: N errors。

用法：
    python tools/check_no_mainthread_blocking.py
    python tools/check_no_mainthread_blocking.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app/src/main/kotlin/io/microduck/app"
CORE = BASE / "core/src/main/kotlin/io/microduck/app/core"

FILES = {
    "main_vm": APP / "MainViewModel.kt",
    "main_activity": APP / "MainActivity.kt",
    "session_holder": APP / "SessionHolder.kt",
    "tcp": CORE / "TcpTransport.kt",
    "robot_session": CORE / "RobotSession.kt",
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
    """去掉 // 行注释与块注释，避免注释里提到符号就算数（防假绿）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def body_of(src: str, signature: str) -> str:
    """从函数签名起做花括号配平，取出函数体（不靠行数硬编码）。"""
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

    # 前提缺失 → UNVERIFIED，不让后面的绿顶数
    for k, p in FILES.items():
        need(bool(src.get(k)), f"{k} 缺失或为空：{p}")
    if any(not src.get(k) for k in FILES):
        if not quiet:
            print("VERDICT = UNVERIFIED_ARTIFACTS_ABSENT")
        return "UNVERIFIED_ARTIFACTS_ABSENT", errs

    vm = code_only(src["main_vm"])
    act = code_only(src["main_activity"])
    holder = code_only(src["session_holder"])
    tcp = code_only(src["tcp"])
    sess = code_only(src["robot_session"])

    # ① 先证明「阻塞源」客观存在（绑一手事实；若上游哪天改成非阻塞，门禁应提示复核）
    need(re.search(r"\.connect\s*\(\s*addr\s*,\s*connectTimeoutMs", tcp) is not None,
         "TcpTransport 不再用带超时的 socket.connect —— 阻塞源变了，需复核本门禁前提")
    need(re.search(r"latch\.await\s*\(\s*requestTimeoutMs", tcp) is not None,
         "TcpTransport.request 不再 latch.await —— 阻塞源变了，需复核")
    need(re.search(r"transport\.connect\s*\(target\)", sess) is not None,
         "RobotSession.connect 不再同步调 transport.connect —— 调用链变了，需复核")

    # ② 修复点：onConnect 必须在 IO 协程里建链，且不在协程外直调 connect
    on_connect = body_of(vm, "fun onConnect(raw: String)")
    need(bool(on_connect), "MainViewModel.onConnect(raw) 函数体未找到")
    need(re.search(r"launch\s*\(\s*Dispatchers\.IO", on_connect) is not None,
         "MainViewModel.onConnect 未用 Dispatchers.IO 启动建链（主线程同步阻塞 ANR）")
    need(re.search(r"robotRepository\.connect\s*\(raw\)", on_connect) is not None,
         "MainViewModel.onConnect 未调用 robotRepository.connect(raw)")
    # 关键负断言：connect 调用必须出现在 launch(IO) 的函数体内，而不能裸在方法体顶层。
    # 判据：从 launch(IO) 的 { 到配对 } 的子串里能找到 connect 调用。
    io_body = ""
    m = re.search(r"launch\s*\(\s*Dispatchers\.IO\s*\)\s*\{", on_connect)
    if m:
        io_body = body_of(on_connect[m.start():], "launch")
    need(re.search(r"robotRepository\.connect\s*\(raw\)", io_body) is not None,
         "robotRepository.connect(raw) 不在 Dispatchers.IO 协程体内（切线程失效）")

    # ③ 修复点：onConnectWith 同样 IO 建链 + onDone 回主线程
    on_connect_with = body_of(vm, "fun onConnectWith(")
    need(bool(on_connect_with), "MainViewModel.onConnectWith 函数体未找到")
    need(re.search(r"launch\s*\(\s*Dispatchers\.IO", on_connect_with) is not None,
         "MainViewModel.onConnectWith 未用 Dispatchers.IO 启动建链")
    need(re.search(r"withContext\s*\(\s*Dispatchers\.Main\s*\).*onDone", on_connect_with, re.S) is not None,
         "MainViewModel.onConnectWith 的 onDone 未切回 Dispatchers.Main（后台线程改 View）")

    # ④ 主线程调用点：connectFromUi 只能经 ViewModel，不得直连 Repository/Transport
    from_ui = body_of(act, "private fun connectFromUi()")
    need(bool(from_ui), "MainActivity.connectFromUi 函数体未找到")
    need(re.search(r"viewModel\.onConnect\s*\(", from_ui) is not None,
         "connectFromUi 未委托 viewModel.onConnect")
    need(re.search(r"robotRepository|SessionHolder\.connect|Transport", from_ui) is None,
         "connectFromUi 直接触碰 Repository/Transport（绕过了 IO 切线程）")

    # ⑤ SessionHolder.connect 只被后台调试通道使用；若被 UI 线程路径调用需复核
    # （当前仅 AiDebugReceiver.doMock 在后台 task 线程调用，非 ANR 路径，这里只锁「不留 UI 调用」）
    sh_connect = body_of(holder, "fun connect(raw: String")
    if sh_connect:
        need(re.search(r"onDone\s*\(\s*repo\.connect", sh_connect) is not None,
             "SessionHolder.connect 语义变了（不再同步回调），需复核调用方线程假设")

    verdict = "NOT_PASS" if errs else "OK"
    if not quiet:
        print(f"VERDICT = {verdict}")
        print(f"RESULT: {len(errs)} errors")
    return verdict, errs


def selftest(src: dict[str, str]) -> list[tuple[str, bool]]:
    """注入式负对照：把线程修复改坏，判据必须变红。"""
    def variant(**kw: str) -> dict[str, str]:
        return {**src, **kw}

    vm = src.get("main_vm", "")
    act = src.get("main_activity", "")

    cases: list[tuple[str, dict[str, str]]] = [
        ("负对照:onConnect 去掉 IO 切线程必红",
         variant(main_vm=vm.replace("launch(Dispatchers.IO)", "launch(Dispatchers.Main)"))),
        ("负对照:onConnectWith 删除 onDone 主线程回调必红",
         variant(main_vm=vm.replace("withContext(Dispatchers.Main) { onDone(ok) }", "onDone(ok)"))),
        ("负对照:connectFromUi 绕过 ViewModel 直连 Repository 必红",
         variant(main_activity=act.replace("viewModel.onConnect(raw)",
                                           "SessionHolder.connect(raw) { }"))),
        ("负对照:connect 调用移出 IO 协程体必红",
         variant(main_vm=vm.replace(
             "viewModelScope.launch(Dispatchers.IO) {\n            robotRepository.connect(raw)\n        }",
             "robotRepository.connect(raw)\n        viewModelScope.launch(Dispatchers.IO) { }"))),
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
