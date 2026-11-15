#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 调试通道的**结构化静态核对器**（stdlib-only，可进 CI 的 meta guard 候选）。

为什么需要它：`AiDebugReceiver` 只在 debug sourceSet 编译，Gradle 编译通过**证明不了**
release 不含这个组件、证明不了白名单没被悄悄加进运动方法、也证明不了 PC 桥仍在发显式广播。
本检查器把这些「跨文件契约」变成可机读断言，并且**自带负对照**：故意把源码改坏，
检查器必须变红；只见过绿的检查器不是证据（项目铁律）。

判据一律用「正则提取完整值 / 集合包含」，不用裸子串 contains 判真假 —— 本项目被
「检查自己源码里的字面量」反噬过多次。

用法：
    python tools/check_ai_debug_channel.py            # 核对真实源码
    python tools/check_ai_debug_channel.py --selftest # 额外跑注入式负对照
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"
CORE = BASE / "core"
TOOLS = BASE / "tools"

PATHS = {
    "debug_manifest": APP / "src/debug/AndroidManifest.xml",
    "main_manifest": APP / "src/main/AndroidManifest.xml",
    "receiver": APP / "src/debug/kotlin/io/microduck/app/AiDebugReceiver.kt",
    "policy": CORE / "src/main/kotlin/io/microduck/app/core/AiDebugPolicy.kt",
    "wire": CORE / "src/main/kotlin/io/microduck/app/core/Wire.kt",
    "bridge": TOOLS / "ai_debug_bridge.py",
    "core_selftest": CORE / "src/test/kotlin/io/microduck/app/core/CoreSelfTest.kt",
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def load_sources() -> dict:
    src = {k: read(p) for k, p in PATHS.items()}
    # main / release 下所有 Kotlin 源码拼起来，用来断言调试组件没有混进发布源码树。
    parts = []
    for variant in ("main", "release"):
        for f in glob.glob(str(APP / f"src/{variant}/**/*.kt"), recursive=True):
            parts.append(read(Path(f)))
    src["main_kotlin"] = "\n".join(parts)
    # 其他变体里是否误放了同名 manifest（如 app/src/release/AndroidManifest.xml）
    src["other_manifests"] = "\n".join(
        read(Path(f)) for f in glob.glob(str(APP / "src/*/AndroidManifest.xml"))
        if not f.replace("\\", "/").endswith("src/debug/AndroidManifest.xml")
        and not f.replace("\\", "/").endswith("src/main/AndroidManifest.xml")
    )
    # AGP 真实合并产物（若本机跑过 Gradle 就有）；不是权威判据，但能独立印证隔离。
    merged = {}
    for f in glob.glob(str(APP / "build/intermediates/**/AndroidManifest.xml"), recursive=True):
        key = "release" if "release" in f.replace("\\", "/").lower() else "debug"
        merged.setdefault(key, []).append((f, read(Path(f))))
    src["_merged"] = merged
    return src


# ---------------------------------------------------------------- 结构化提取

def xml_body(text: str) -> str:
    """先剥掉 XML 注释再做结构化提取。

    🔴 本项目踩过的坑：debug manifest 的**注释里**写了「刻意不写 <intent-filter>」，
    第一次跑检查器就把注释里的字面量当成了真标签，正对照直接变红。
    ⇒ 检查器判据必须只看真实元素，不看说明文字；这正是「裸子串扫描会反噬」的又一例。
    """
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def tag_attrs(tag: str) -> dict:
    return dict(re.findall(r'([\w:.\-]+)\s*=\s*"([^"]*)"', tag))


def receiver_tags(manifest: str) -> list[dict]:
    return [tag_attrs(t) for t in re.findall(r'<receiver\b[^>]*>', xml_body(manifest), re.S)]


def tag_names(manifest: str) -> set[str]:
    return set(re.findall(r'<\s*/?\s*([A-Za-z][\w.\-]*)', xml_body(manifest)))


def import_names(kotlin: str) -> set[str]:
    return set(re.findall(r'^import\s+([\w.]+)', kotlin, re.M))


def qualified_calls(kotlin: str, obj: str) -> set[str]:
    return set(re.findall(r'\b' + re.escape(obj) + r'\.(\w+)\s*\(', kotlin))


def method_refs(block: str) -> set[str]:
    return set(re.findall(r'\bMethod\.(\w+)', block))


def policy_call_names(kotlin: str) -> set[str]:
    """提取「真跑了策略函数」的调用名，兼容 `val p = AiDebugPolicy` 这类别名。

    🔴 只看 `AiDebugPolicy.xxx(` 会漏掉自检里用别名调用的写法；只看裸子串又会
    把文档注释里的字面量当调用。这里先解析赋值别名，再按调用语法提取。
    """
    aliases = {"AiDebugPolicy"} | set(
        re.findall(r'\bval\s+(\w+)\s*=\s*AiDebugPolicy\b', kotlin))
    out: set[str] = set()
    for a in aliases:
        out |= qualified_calls(kotlin, a)
    return out


def main_body(kotlin: str) -> str:
    """取 `fun main(...) { ... }` 的函数体，用来断言新测试真的被挂进执行链。

    本项目真踩过：断言函数写好了、main 里没调用 ⇒ 永远绿但不执行。
    """
    m = re.search(r'fun\s+main\s*\([^)]*\)\s*\{(.*?)\n    \}', kotlin, re.S)
    return m.group(1) if m else ""


def policy_set(policy: str, name: str) -> set[str]:
    m = re.search(r'val\s+' + re.escape(name) + r'\s*:\s*Set<String>\s*=\s*linkedSetOf\((.*?)\)',
                  policy, re.S)
    if not m:
        raise ValueError(f"读不到 AiDebugPolicy.{name}")
    return method_refs(m.group(1))


def wire_const_names(wire: str) -> set[str]:
    return set(re.findall(r'const val\s+(\w+)', wire))


# ---------------------------------------------------------------- 核对

def evaluate(src: dict) -> list[str]:
    """返回错误列表；空列表 = 全部通过。刻意不读运行时状态，纯源码结构。"""
    err: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            err.append(msg)

    d, m, r = src["debug_manifest"], src["main_manifest"], src["receiver"]
    p, w, b, cs = src["policy"], src["wire"], src["bridge"], src["core_selftest"]

    need(bool(d), "debug/AndroidManifest.xml 缺失或为空")
    need(bool(r), "debug sourceSet 里 AiDebugReceiver.kt 缺失或为空")
    need(bool(p), "core/AiDebugPolicy.kt 缺失或为空")
    need(bool(b), "tools/ai_debug_bridge.py 缺失或为空")
    need(bool(cs), "core/CoreSelfTest.kt 缺失或为空")

    # ① debug manifest 只声明这一个 receiver，且没有 intent-filter（显式广播专用）。
    recs = receiver_tags(d)
    names = {a.get("android:name") for a in recs}
    need(".AiDebugReceiver" in names, f"debug manifest 未声明 .AiDebugReceiver（实读={sorted(names)}）")
    # 负对照锚：提取完整值才能证明「拼错的名字不会假绿」。
    need(".AiDebugReceiver_BROKEN" not in names, "receiver 名称提取疑似恒真（自检用）")
    need("intent-filter" not in tag_names(d),
         "debug receiver 写了 intent-filter ⇒ 会接受隐式广播，违背显式组件设计")
    for a in recs:
        if a.get("android:name") == ".AiDebugReceiver":
            need(a.get("android:exported") == "true",
                 "receiver 必须 exported=true，否则 adb shell 这个外部发送方送不进来")
            need(a.get("android:enabled") == "true", "receiver 必须 enabled=true")

    # ② release / main 侧零组件：源树、manifest、类文件三处都不能出现。
    need(".AiDebugReceiver" not in set(re.findall(r'android:name="([^"]+)"', xml_body(m))),
         "main/AndroidManifest.xml 里出现了 AiDebugReceiver ⇒ release 会继承这个组件")
    need(".AiDebugReceiver" not in set(re.findall(r'android:name="([^"]+)"', xml_body(src["other_manifests"]))),
         "其他变体 manifest 里出现了 AiDebugReceiver")
    need(not re.search(r'\bclass\s+AiDebugReceiver\b', src["main_kotlin"]),
         "AiDebugReceiver 类出现在 main/release 源码树（debug-only 被破坏）")

    # ③ 唯一策略真源：Receiver 必须 import 并真的调用判定函数。
    need("io.microduck.app.core.AiDebugPolicy" in import_names(r),
         "Receiver 未 import core.AiDebugPolicy（白名单可能另写了一份）")
    calls = qualified_calls(r, "AiDebugPolicy")
    need("isCommandAllowed" in calls, "Receiver 没有真的调用 AiDebugPolicy.isCommandAllowed")
    need("isRpcAllowed" in calls, "Receiver 没有真的调用 AiDebugPolicy.isRpcAllowed")
    need(bool(re.findall(r'Log\.i\(\s*AiDebugPolicy\.TAG', r)),
         "Receiver 没有往固定 TAG 写单行 JSON 结果")
    need(bool(re.findall(r'\bgoAsync\s*\(', r)), "Receiver 未用 goAsync，阻塞式命令会卡主线程")
    need(bool(re.findall(r'\bpending\.finish\s*\(', r)),
         "Receiver 未调 PendingResult.finish()，goAsync 会广播 ANR")
    need(bool(re.findall(r'\bAiDebugPolicy\.(SCAN_WINDOW_MS|CONNECT_GATT_TIMEOUT_MS|CONNECT_WAIT_MS)', r)),
         "Receiver 未使用有界超时常量（goAsync 约 10 s 预算）")

    # ③b 动态证据：core 自检必须在 JVM 上真跑策略，而不只是被本检查器静态解析。
    #   静态解析能证明「文本写对了」，证明不了 `isRpcAllowed("robot.move")` 真的返回 false。
    cs_calls = policy_call_names(cs)
    need("isCommandAllowed" in cs_calls,
         "core 自检没有真跑 AiDebugPolicy.isCommandAllowed（策略只被静态解析）")
    need("isRpcAllowed" in cs_calls,
         "core 自检没有真跑 AiDebugPolicy.isRpcAllowed（改坏白名单不会在真跑里变红）")
    need("testAiDebugPolicy()" in main_body(cs),
         "core 自检 main 未调用 testAiDebugPolicy（断言写了但不执行＝假绿）")

    # ④ 白名单：只读 ∩ 禁止 == ∅，且危险方法必须在禁止集合里。
    try:
        allowed, forbidden = policy_set(p, "READ_ONLY_METHODS"), policy_set(p, "FORBIDDEN_METHODS")
    except ValueError as e:
        err.append(str(e))
        allowed, forbidden = set(), set()
    need(bool(allowed), "READ_ONLY_METHODS 为空（rpc 命令将无法使用）")
    need(not (allowed & forbidden), f"只读白名单与禁止集合相交: {sorted(allowed & forbidden)}")
    for must in ("ROBOT_MOVE", "ROBOT_DO", "ROBOT_ENABLE", "ROBOT_INIT", "ROBOT_HEAD",
                 "ROBOT_LOAD_POLICY", "NET_CONNECT", "SYSTEM_AUTHENTICATE"):
        need(must in forbidden, f"禁止集合缺高风险方法 Method.{must}")
    for banned in ("ROBOT_STATE", "ROBOT_SUBSCRIBE", "ROBOT_MOVE", "ROBOT_DO", "UPDATE_CHECK"):
        need(banned not in allowed, f"只读白名单混入了 Method.{banned}")
    consts = wire_const_names(w)
    for ref in sorted(allowed | forbidden):
        need(ref in consts, f"AiDebugPolicy 引用了 Wire.kt 里不存在的 Method.{ref}")

    # ⑤ PC 桥：必须发显式组件 + stopped-package flag，且常量取自单一权威。
    need(bool(re.search(r'"-n"\s*,\s*policy\["COMPONENT"\]', b)),
         "PC 桥没有用 -n 指定显式组件（隐式广播在 Android 8+ 收不到）")
    need(bool(re.search(r'"-f"\s*,\s*"32"', b)),
         "PC 桥缺 -f 32 (FLAG_INCLUDE_STOPPED_PACKAGES)，首次安装未启动的 App 收不到")
    need(bool(re.search(r'AiDebugPolicy\.kt', b)),
         "PC 桥未从 core/AiDebugPolicy.kt 提取常量，存在两条链漂移风险")
    need(bool(re.search(r'^TERMINAL_PHASES\s*=\s*\{', b, re.M)),
         "PC 桥缺终态判定，会把 phase=accepted 误读成连接成功")
    bridge_args = set(re.findall(r'add_argument\(\s*"(--[\w-]+)"', b))
    need("--selftest" in bridge_args, "PC 桥没有自带自检入口")
    need("--precheck" in bridge_args, "PC 桥缺 --precheck（零应答时无法机械核对最前置前提）")

    # ⑥ AGP 真实合并产物（若有）：debug 有、release 无。缺文件只如实记 UNVERIFIED，不当 PASS。
    merged = src.get("_merged", {})
    for f, txt in merged.get("release", []):
        need("AiDebugReceiver" not in txt, f"release 合并 manifest 含调试组件: {f}")
    for f, txt in merged.get("debug", []):
        need("AiDebugReceiver" in txt, f"debug 合并 manifest 缺调试组件: {f}")
    return err


# ---------------------------------------------------------------- 负对照

def selftest(src: dict) -> list[tuple[str, bool]]:
    """把源码故意改坏，检查器必须报错。只见过绿的断言不是证据。"""
    mutations = [
        ("debug manifest 加 intent-filter 必红",
         lambda s: {**s, "debug_manifest": s["debug_manifest"].replace(
             '<application>', '<application>\n<intent-filter><action android:name="x"/></intent-filter>')}),
        ("receiver 改成 exported=false 必红",
         lambda s: {**s, "debug_manifest": s["debug_manifest"].replace(
             'android:exported="true"', 'android:exported="false"')}),
        ("main manifest 混入调试组件必红",
         lambda s: {**s, "main_manifest": s["main_manifest"].replace(
             '<application', '<receiver android:name=".AiDebugReceiver" android:exported="true" />\n    <application')}),
        ("Receiver 去掉 isRpcAllowed 必红",
         lambda s: {**s, "receiver": s["receiver"].replace(
             "AiDebugPolicy.isRpcAllowed(method)", "true")}),
        ("Receiver 去掉 pending.finish 必红",
         lambda s: {**s, "receiver": s["receiver"].replace("pending.finish()", "/* removed */")}),
        ("白名单混入 robot.move 必红",
         lambda s: {**s, "policy": s["policy"].replace(
             "Method.SYSTEM_INFO,", "Method.SYSTEM_INFO,\n        Method.ROBOT_MOVE,")}),
        ("PC 桥去掉 -f 32 必红",
         lambda s: {**s, "bridge": s["bridge"].replace('"-f", "32", ', '"" , "", ')}),
        ("PC 桥去掉 -n 显式组件必红",
         lambda s: {**s, "bridge": s["bridge"].replace('"-n", policy["COMPONENT"],', '"-x", "none",')}),
        ("core 自检新断言没挂进 main 必红",
         lambda s: {**s, "core_selftest": s["core_selftest"].replace(
             "testAiDebugPolicy()", "testAiDebugPolicy_DISABLED()")}),
        ("core 自检不真跑策略必红",
         lambda s: {**s, "core_selftest": s["core_selftest"].replace(
             "isRpcAllowed", "isRpcAllowed_REMOVED")}),
    ]
    out = []
    for label, mutate in mutations:
        errs = evaluate(mutate(src))
        out.append((label, len(errs) > 0))
    # 正对照：未改动的源码本身必须是绿的，否则上面全是假红。
    out.append(("正对照:未改动源码零错误", len(evaluate(src)) == 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="核对 debug-only AI 调试通道的跨文件契约")
    ap.add_argument("--selftest", action="store_true", help="跑注入式负对照")
    args = ap.parse_args()
    src = load_sources()
    errs = evaluate(src)
    for e in errs:
        print("  FAIL  " + e)
    print(f"RESULT: {len(errs)} errors" if errs else "RESULT: 0 errors")
    if src.get("_merged", {}).get("release"):
        print("merged_manifest_evidence: PRESENT (debug 有 / release 无 已逐文件核对)")
    else:
        print("merged_manifest_evidence: UNVERIFIED_MERGED_MANIFEST_ABSENT "
              "(本机未跑过 :app:processReleaseManifest；源树检查仍是权威判据)")
    rc = 1 if errs else 0
    if args.selftest:
        print("\n=== 注入式负对照 ===")
        results = selftest(src)
        for label, ok in results:
            print(("  PASS  " if ok else "  FAIL  ") + label)
            if not ok:
                rc = 1
        print(f"SELFTEST: {sum(1 for _, ok in results if ok)}/{len(results)} passed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
