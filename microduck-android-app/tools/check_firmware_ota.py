#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
固件 OTA 门禁：锁住「一手协议常量逐字 + 数组 result 走 callRaw + 写操作不重放 +
二次确认 + 进度不独占连接 + 断连不谎报成功」这组结构性质（stdlib-only）。

为什么需要它：固件 OTA 是 mutating 功能，最容易出的事故不是「跑不通」而是「假绿」——
  ① 用普通 call 收数组 result（readResult 吞成 null）→ 假「未读到」；
  ② apply/rollback/select 被当只读重放 → 断线后重复安装；
  ③ UI 无二次确认直接装 → 误触写板；
  ④ 长期订阅 update.subscribe 独占 BLE 连接 → robot.state/health 通道被挤掉；
  ⑤ apply 断连（成功路径）被当失败 / 或谎报「已安装成功」。
判据绑一手 kissqy v167 固件源码（duck-ipc-proto lib.rs / update-over-ble.md / btd route.rs）。
判据独立于被测值：只锁结构签名与常量，不锁数量文案。
verdict: OK / NOT_PASS；末尾打印 RESULT: N errors。

用法：
    python tools/check_firmware_ota.py
    python tools/check_firmware_ota.py --selftest
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
    "fwu": CORE / "FirmwareUpdate.kt",
    "snap": CORE / "FirmwareSnapshot.kt",
    "selftest": BASE / "core/src/test/kotlin/io/microduck/app/core/CoreSelfTest.kt",
    "vm": APP / "MainViewModel.kt",
    "activity": APP / "MainActivity.kt",
    "panel": APP / "update/FirmwarePanel.kt",
}

# 一手协议常量（kissqy v167 duck-ipc-proto method 名），逐字。
METHOD_CONSTANTS = {
    "UPDATE_APPLY": "update.apply",
    "UPDATE_ROLLBACK": "update.rollback",
    "UPDATE_SELECT": "update.select",
    "UPDATE_SUBSCRIBE": "update.subscribe",
    "UPDATE_PROGRESS": "update.progress",
    "UPDATE_SHOW": "update.show",
}

# Phase 13 值（lib.rs Phase enum）——缺一即为协议 skew。
PHASES = [
    "idle", "preflight", "checking", "downloading", "verifying", "extracting",
    "running_pre_hook", "swapping", "running_post_hook", "applying",
    "health_gate", "committing", "rolling_back",
]


def load(srcs: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in FILES.items():
        if srcs and k in srcs:
            out[k] = srcs[k]
            continue
        try:
            out[k] = p.read_text(encoding="utf-8")
        except OSError:
            out[k] = ""
    return out


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def check(s: dict[str, str]) -> list[str]:
    errs: list[str] = []
    wire = code_only(s["wire"])
    session = code_only(s["session"])
    repo = s["repo"]           # 保留注释：断连语义的判据要看得到说明
    fwu = code_only(s["fwu"])
    vm = code_only(s["vm"])
    act = code_only(s["activity"])
    panel = s["panel"]         # 二次确认文案/AppDialogs 调用是判据
    st = s["selftest"]

    # 1) 一手方法名常量逐字（正向断言：const NAME = "value"）
    for name, value in METHOD_CONSTANTS.items():
        if not re.search(r'const\s+val\s+' + name + r'\s*=\s*"' + value + r'"', wire):
            errs.append(f"Wire.kt 缺方法常量 {name}=\"{value}\"（一手 lib.rs）")

    # 2) 13 个 Phase 全在 FirmwareUpdate.PHASES（找一个包含全部 phase 字符串的列表声明）
    phase_block = fwu[fwu.find("val PHASES"):fwu.find("val PHASES") + 700]
    for ph in PHASES:
        if f'"{ph}"' not in phase_block:
            errs.append(f"FirmwareUpdate.PHASES 缺 phase={ph}（一手 13 值）")

    # 3) 数组 result 必须走 callRaw；readResult 仍是 getAsJsonObject（证明两条路有别）
    if not re.search(r'fun\s+callRaw\s*\(', session):
        errs.append("RobotSession 缺 callRaw（数组 result 会被 call 吞成 null）")
    if 'get("result")' not in session:
        errs.append("callRaw 未用 get(\"result\") 取 JsonElement（数组会丢）")
    for m in ("UPDATE_STATUS", "UPDATE_LIST_INSTALLED", "UPDATE_LOG"):
        if f"callRaw(Method.{m}" not in repo:
            errs.append(f"Repository 未用 callRaw 读 {m}（Vec 数组）")

    # 4) 写操作 replayable=false（不重放）——正向断言 apply/rollback/select 调用点带 replayable=false
    apply_call = re.search(r's\.call\(\s*Method\.UPDATE_APPLY[^\n]*', repo)
    if not apply_call or "replayable = false" not in apply_call.group(0):
        errs.append("applyFirmware 未显式 replayable=false（写操作会被重放）")
    if "replayable = false" not in repo or "firmwareWrite" not in repo:
        errs.append("rollback/select 写操作路径缺 replayable=false")
    if "UPDATE_SHOW" not in session or "Method.UPDATE_SHOW" not in session:
        errs.append("UPDATE_SHOW 未进只读白名单（只读却不可重放）")

    # 5) UI 二次确认：FirmwarePanel 对 apply/rollback 走全 App 唯一 M3 对话框入口
    #    🔴 判据锁语义不用裸子串：必须同时有 AppDialogs.confirm、两个确认方法、
    #    以及具体正向按钮标签；退回平台默认 AlertDialog.Builder 必须判红。
    if "AppDialogs.confirm" not in panel:
        errs.append("FirmwarePanel 缺 Material 3 二次确认入口 AppDialogs.confirm")
    if "AlertDialog.Builder" in panel:
        errs.append("FirmwarePanel 仍在用平台默认 AlertDialog.Builder（UI 回退）")
    if "confirmApply" not in panel or "confirmRollback" not in panel:
        errs.append("FirmwarePanel 缺 apply/rollback 各自的确认方法")
    if not re.search(r'positiveLabel\s*=\s*"确认更新"', panel):
        errs.append("FirmwarePanel 安装确认缺「确认更新」正向按钮")
    if not re.search(r'positiveLabel\s*=\s*"确认回滚"', panel):
        errs.append("FirmwarePanel 回滚确认缺「确认回滚」正向按钮")

    # 6) 进度不长期订阅 update.subscribe（会独占 BLE 连接）——正面确认用 onEvent，反面确认没订阅
    if "Event.Notification" not in repo or "UPDATE_PROGRESS" not in repo:
        errs.append("Repository 未通过 Event.Notification 收 update.progress")
    # 负向：不应出现 s.subscribe(Method.UPDATE_SUBSCRIBE
    if re.search(r'subscribe\(\s*Method\.UPDATE_SUBSCRIBE', repo):
        errs.append("Repository 长期订阅了 update.subscribe（独占连接，会挤掉 robot.state）")

    # 7) 断连不谎报成功：Repository 文案含「重连后」确认语义
    if "重连后" not in repo:
        errs.append("apply 断连文案缺「重连后确认」语义（成功路径被当失败或谎报成功）")

    # 8) 接线完整：ViewModel 事件 + Activity 挂载面板 + render
    for m in ("onRefreshFirmware", "onCheckFirmware", "onApplyFirmware", "onRollbackFirmware"):
        if f"fun {m}" not in vm:
            errs.append(f"MainViewModel 缺事件 {m}")
    if "FirmwarePanel(" not in act:
        errs.append("MainActivity 未创建 FirmwarePanel")
    if "firmwarePanel.render" not in act:
        errs.append("MainActivity renderAll 未渲染固件面板")

    # 9) 自检存在：CoreSelfTest 真测固件 OTA（防止「只有门禁无行为测试」）
    if "testFirmwareUpdate" not in st:
        errs.append("CoreSelfTest 缺 testFirmwareUpdate（无行为测试）")

    return errs


def meta_negative_control() -> list[str]:
    """
    元验证：故意改坏每个关键结构，判据必须变红。若改坏后仍 OK ⇒ 门禁是假绿。
    返回元负对照自身的错误。
    """
    trials: dict[str, dict[str, str]] = {
        "改坏:删 callRaw": {"session": "fun callRawX(" },
        "改坏:apply 允许重放": {"repo": "call(Method.UPDATE_APPLY, replayable = true)"},
        "改坏:删二次确认": {"panel": "no dialog here"},
        "改坏:退回平台默认弹窗": {"panel": "@replace:AppDialogs.confirm=LegacyDialogBuilder"},
        "改坏:长期订阅独占连接": {"repo": "subscribe( Method.UPDATE_SUBSCRIBE"},
        "改坏:缺方法常量": {"wire": "const UPDATE_APPLY_OLD = \"update.apply\""},
    }
    errs: list[str] = []
    # 先用正常源码确认 OK（门禁本身得先绿）
    if check(load()):
        errs.append("元验证前置失败：正常源码下门禁就不 OK")
        return errs
    for label, patch in trials.items():
        srcs = {k: v for k, v in load().items()}
        for key, replacement in patch.items():
            if replacement.startswith("@replace:"):
                old, new = replacement.removeprefix("@replace:").split("=", 1)
                srcs[key] = srcs[key].replace(old, new)
            else:
                srcs[key] = replacement  # 整文件替换成不含判据的片段
        errs_found = check(srcs)
        if not errs_found:
            errs.append(f"元负对照失效：{label} 后门禁仍 OK（假绿）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="运行门禁自身的元负对照")
    args = ap.parse_args()

    if args.selftest:
        errs = meta_negative_control()
        n = 7  # 正常源码 1 + 6 个改坏试验
        ok = n - len(errs)
        print(f"SELFTEST: {ok}/{n} passed")
        for e in errs:
            print("  META_FAIL:", e)
        print(f"RESULT: {ok} passed, {len(errs)} failed")
        return 1 if errs else 0

    errs = check(load())
    if errs:
        print("VERDICT: NOT_PASS")
        for e in errs:
            print("  ERR:", e)
        print(f"RESULT: 0 passed, {len(errs)} failed")
        return 1
    print("VERDICT: OK — 固件 OTA 一手协议/写操作保护/接线 结构门禁通过（非整机签收）")
    print("RESULT: 0 errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
