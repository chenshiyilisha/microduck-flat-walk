#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE 扫描「候选呈现」门禁：锁住「扫描层全量接收 + 呈现层只按一手判别字段过滤」这组
结构性质，防止被无声回退成两种都会漏掉真板子的写法（stdlib-only）。

一手依据（两条独立来源同一结论）：
  · Pollen 原厂 docs/design/app-path-design.md §3.3：不要用 service UUID 做**硬件**过滤——
    bonded peripheral 常以空 service list 广播，过滤后「not reported at all」；应
    「scan unfiltered and discriminate your own candidates」。
  · Ley-WL/ducklink 0.9.25：移除 Android 硬件 UUID 过滤，全量接收后以服务 UUID 或
    严格后缀广播名筛选。

因此「列表不该出现无名蓝牙」的正确实现不是按设备名筛，也不是给 startScan 传 filters，
而是：全量接收 → discriminate() 产出 matchedBy（服务 UUID / 广播名 / 已绑定 / 附近设备）
→ 呈现层只隐藏 matchedBy == "附近设备" 的非目标项。按名字筛会把「已绑定但无名」的
真板子一起筛掉（原厂 §3.3 明写的场景），是本门禁主要防的假绿。

判据绑结构签名（正则提取 filter lambda 内容 + 集合包含），不锁数量/文案数字；
--selftest 用注入式负对照：把源码改坏，判据必须变红。
verdict: OK / NOT_PASS / UNVERIFIED_ARTIFACTS_ABSENT；末尾打印 RESULT: N errors。

用法：
    python tools/check_ble_candidate_filter.py
    python tools/check_ble_candidate_filter.py --selftest
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
    "panel": APP / "ble/BleConnectPanel.kt",
    "wire": CORE / "Wire.kt",
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

    panel = code_only(src["panel"])

    # ① 扫描层：必须全量接收（startScan 第一个参数是 null filters）
    need(re.search(r"startScan\(\s*null\s*,", panel) is not None,
         "扫描层给 startScan 传了 filters（硬件 UUID 过滤会漏掉空 service list 的已绑定设备）")

    # ② 软件判别仍走三路一手依据，不能被简化成「只看名字」
    disc = body_of(panel, "fun discriminate")
    need(bool(disc), "discriminate() 缺失")
    need("serviceUuids" in disc, "discriminate 缺服务 UUID 判别")
    need("DUCK_NAME" in disc, "discriminate 缺广播名判别")
    need("bondedDevices" in disc, "discriminate 缺已绑定判别（无名真板子唯一兜底）")
    need("matchedBy" in src["panel"], "Candidate 缺 matchedBy 一手判别字段")

    # ③ 呈现层过滤：lambda 必须引用 matchedBy、且不得引用 name（防退化成按名字筛）
    rc = body_of(panel, "fun renderCandidates")
    need(bool(rc), "renderCandidates() 缺失")
    filt = re.search(r"\.filter\s*\{\s*([^}]*)\}", rc)
    need(filt is not None, "呈现层缺候选过滤（非目标无名设备会重新混进列表）")
    lam = filt.group(1) if filt else ""
    need("matchedBy" in lam, "候选过滤没绑一手判别字段 matchedBy")
    need("name" not in lam, "候选过滤按设备名筛（会漏掉已绑定但无名的真板子，原厂 §3.3）")
    need('"附近设备"' in rc, "呈现层未以「附近设备」为非目标判据")

    # ④ 如实回显：状态行报出被隐藏的非目标数量，不假装没扫到
    need("hidden" in rc and "已隐藏" in rc,
         "状态行未如实回显被隐藏的非目标设备数（用户无法知道扫到了别的设备）")

    # ⑤ 候选仍可点击连接（过滤不能顺手把交互也删了）
    need("setOnClickListener { connect(c) }" in rc,
         "候选列表项缺点击连接监听（过滤后变成只读列表）")

    verdict = "NOT_PASS" if errs else "OK"
    if not quiet:
        print(f"VERDICT = {verdict}")
        print(f"RESULT: {len(errs)} errors")
    return verdict, errs


def selftest(src: dict[str, str]) -> list[tuple[str, bool]]:
    """注入式负对照：把候选呈现链改坏，判据必须变红。"""
    def variant(**kw: str) -> dict[str, str]:
        return {**src, **kw}

    panel = src.get("panel", "")

    cases: list[tuple[str, dict[str, str]]] = [
        ("负对照:扫描层加硬件 filters 必红",
         variant(panel=panel.replace("scanner.startScan(null, settings, scanCallback)",
                                     "scanner.startScan(filters, settings, scanCallback)"))),
        ("负对照:删掉候选过滤必红",
         variant(panel=panel.replace('found.values.filter { it.matchedBy != "附近设备" }',
                                     "found.values"))),
        ("负对照:过滤退化成按名字筛必红",
         variant(panel=panel.replace('found.values.filter { it.matchedBy != "附近设备" }',
                                     "found.values.filter { it.name.isNotEmpty() }"))),
        ("负对照:判别删掉已绑定兜底必红",
         variant(panel=panel.replace("bondedDevices", "noBondedLookup"))),
        ("负对照:状态行删掉隐藏数量回显必红",
         variant(panel=panel.replace(" · 非目标 $hidden 台已隐藏", ""))),
        ("负对照:候选删掉点击连接监听必红",
         variant(panel=panel.replace("setOnClickListener { connect(c) }", ""))),
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
    if args.selftest:
        checks = selftest(src)
        print("\n=== 注入式负对照 ===")
        for label, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + label)
        n_ok = sum(1 for _, ok in checks if ok)
        print(f"SELFTEST: {n_ok}/{len(checks)} passed")
        if n_ok != len(checks):
            return 1
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
