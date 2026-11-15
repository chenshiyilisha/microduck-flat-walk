#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 侧「AI 控制 App」调试桥 —— 发一条 adb 显式广播，取回一条结构化 Logcat JSON。

设计目标（2026-11-14 真机排障复盘）：App 失败原因原本被 UI 与 logcat 同时吞掉，
AI 只能靠 uiautomator 猜。这里让 AI 可以直接：
    python tools/ai_debug_bridge.py --precheck
    python tools/ai_debug_bridge.py --cmd status
    python tools/ai_debug_bridge.py --cmd scan
    python tools/ai_debug_bridge.py --cmd connect --arg CC:C8:37:E3:7C:90
    python tools/ai_debug_bridge.py --cmd rpc --method robot.health
    python tools/ai_debug_bridge.py --cmd mock
    python tools/ai_debug_bridge.py --cmd disconnect
    python tools/ai_debug_bridge.py --cmd help

🔴 零应答排障顺序（项目 SOP 规则 12/18：先机械验证最前置前提）：
  ① adb 在不在、设备在不在线（PnP Code 45 假掉线要重插线，adb 层操作无效）
  ② APK 装没装、是不是 **debug 变体**（release 刻意不含 Receiver）
  ③ App 是否处于 stopped 状态 ⇒ 故固定带 `-f 32` = FLAG_INCLUDE_STOPPED_PACKAGES
  ④ 再看蓝牙开关 / 运行时权限 / 扫描器 —— 这些由 App 侧 `scan` 命令逐条回 PRECONDITION_FAIL

通道能力边界：命令白名单、RPC 只读方法白名单、结果只写 Logcat、不开端口、不加权限；
所有返回值都是 COLLECTED_ONLY_NOT_PASS 级观测，**不产出 PASS / 验收结论**。

单一权威：TAG / COMPONENT / ACTION / EXTRA_* / COMMANDS / RESULT_SCHEMA 全部从
`core/.../AiDebugPolicy.kt` 用正则提取完整值，不在 Python 里另写一份常量，
避免两条链漂移（项目铁律）。源码读不到直接 PRECONDITION_FAIL，不静默用默认值。
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
POLICY_SRC = BASE / "core/src/main/kotlin/io/microduck/app/core/AiDebugPolicy.kt"
TERMINAL_PHASES = {None, "", "result", "timeout"}


class BridgeError(Exception):
    def __init__(self, reason: str, next_step: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.next_step = next_step


# ---------------------------------------------------------------- 单一权威读取

def read_policy_source() -> str:
    if not POLICY_SRC.is_file():
        raise BridgeError("POLICY_SOURCE_MISSING", f"找不到 {POLICY_SRC}")
    return POLICY_SRC.read_text(encoding="utf-8")


def extract_const(src: str, name: str) -> str | None:
    # 正则取「完整引号值」，不是裸子串 contains（本项目被裸子串反噬过）。
    m = re.search(r'const val\s+' + re.escape(name) + r'\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else None


def extract_commands(src: str) -> list[str]:
    m = re.search(r'val COMMANDS\s*:\s*Set<String>\s*=\s*linkedSetOf\((.*?)\)', src, re.S)
    if not m:
        raise BridgeError("POLICY_COMMANDS_UNREADABLE", "AiDebugPolicy.COMMANDS 结构变了，需同步本桥")
    return re.findall(r'"([^"]+)"', m.group(1))


def load_policy() -> dict:
    src = read_policy_source()
    keys = ("TAG", "ACTION", "COMPONENT", "PACKAGE", "RECEIVER_FQCN",
            "EXTRA_CMD", "EXTRA_RID", "EXTRA_ARG", "EXTRA_METHOD", "EXTRA_PARAMS_JSON")
    out = {k: extract_const(src, k) for k in keys}
    missing = [k for k, v in out.items() if v is None]
    if missing:
        raise BridgeError("POLICY_CONST_MISSING", "缺常量: " + ",".join(missing))
    schema = re.search(r'const val RESULT_SCHEMA\s*=\s*(\d+)', src)
    if not schema:
        raise BridgeError("POLICY_SCHEMA_MISSING", "读不到 RESULT_SCHEMA")
    out["RESULT_SCHEMA"] = int(schema.group(1))
    out["COMMANDS"] = extract_commands(src)
    return out


# ---------------------------------------------------------------- adb 封装

def adb_args(serial: str | None) -> list[str]:
    exe = shutil.which("adb")
    if exe is None:
        raise BridgeError("PRECONDITION_FAIL: NO_ADB", "先装 platform-tools 并把 adb 放进 PATH")
    return [exe] + (["-s", serial] if serial else [])


def adb(serial: str | None, *args: str, timeout: float = 12.0) -> str:
    try:
        p = subprocess.run(adb_args(serial) + list(args), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BridgeError("ADB_TIMEOUT", "adb 命令超时，检查设备是否卡死")
    except OSError as e:
        raise BridgeError("ADB_EXEC_FAILED", str(e))
    return p.stdout or ""


def shell(serial: str | None, remote_cmd: str, timeout: float = 12.0) -> str:
    return adb(serial, "shell", remote_cmd, timeout=timeout)


# ---------------------------------------------------------------- 指令构造 / 结果解析

def build_broadcast(policy: dict, cmd: str, rid: str, *,
                    arg: str | None = None, method: str | None = None,
                    params_json: str | None = None) -> str:
    parts = ["am", "broadcast", "-f", "32", "-n", policy["COMPONENT"],
             "-a", policy["ACTION"],
             "--es", policy["EXTRA_RID"], rid,
             "--es", policy["EXTRA_CMD"], cmd]
    if arg is not None:
        parts += ["--es", policy["EXTRA_ARG"], arg]
    if method is not None:
        parts += ["--es", policy["EXTRA_METHOD"], method]
    if params_json is not None:
        parts += ["--es", policy["EXTRA_PARAMS_JSON"], params_json]
    return " ".join(shlex.quote(p) for p in parts)


def parse_logcat_lines(raw: str, schema: int) -> list[dict]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("v") == schema:
            out.append(obj)
    return out


def pick_result(objects: list[dict], rid: str) -> dict | None:
    """只认终态行。`phase=accepted` 只是「已开始」，不能当结果，否则 AI 会把「发起连接」
    误读成「连接成功」——那正是本项目 UNVERIFIED != PASS 要防的假绿。"""
    hits = [o for o in objects if o.get("rid") == rid]
    terminal = [o for o in hits if o.get("phase") in TERMINAL_PHASES]
    return terminal[-1] if terminal else None


def logcat_dump(serial: str | None, tag: str, tail: int = 800) -> str:
    # -s <TAG>:V 只留本通道；-v raw 让每行就是纯 JSON，便于直接 json.loads。
    return adb(serial, "logcat", "-d", "-t", str(tail), "-s", f"{tag}:V", "-v", "raw",
               timeout=15.0)


# ---------------------------------------------------------------- 前置检查

def precheck(serial: str | None, policy: dict) -> dict:
    devices = adb(serial, "devices")
    online = [l for l in devices.splitlines()
              if "\tdevice" in l and not l.startswith("List of devices")]
    if not online:
        raise BridgeError("PRECONDITION_FAIL: NO_ONLINE_ADB_DEVICE",
                          "检查 USB 线；PnP Code 45 (CM_PROB_PHANTOM) 是物理已断，必须重新插线")
    path = shell(serial, f"pm path {policy['PACKAGE']}")
    if "package:" not in path:
        raise BridgeError("PRECONDITION_FAIL: APK_NOT_INSTALLED",
                          "先 adb install -r -g <debug APK>")
    dump = shell(serial, f"dumpsys package {policy['PACKAGE']}")
    present = policy["RECEIVER_FQCN"] in dump
    return {
        "v": policy["RESULT_SCHEMA"], "cmd": "precheck", "ok": present,
        "adb_devices": online, "apk_path": path.strip(),
        "debug_receiver_present": present,
        "reason": "" if present else "DEBUG_RECEIVER_ABSENT",
        "next": "" if present else
                "release 包刻意不含该组件；装 debug 变体，或先把 App 手动启动一次脱离 stopped 状态",
        "flags_note": "发送固定带 -f 32 (FLAG_INCLUDE_STOPPED_PACKAGES)",
        "evidence": "COLLECTED_ONLY_NOT_PASS",
    }


# ---------------------------------------------------------------- 自检（带负对照）

def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    try:
        p = load_policy()
    except BridgeError as e:
        print(f"FAIL  load_policy  {e.reason}")
        return 1
    ck("单一权威读回 TAG", p["TAG"] == "MicroDuckAiDebug", p["TAG"])
    ck("单一权威读回显式组件", p["COMPONENT"] == "io.microduck.app/.AiDebugReceiver", p["COMPONENT"])
    ck("单一权威读回命令表", set(p["COMMANDS"]) >=
       {"help", "status", "scan", "connect", "mock", "rpc", "disconnect"}, str(p["COMMANDS"]))
    ck("schema 为正整数", isinstance(p["RESULT_SCHEMA"], int) and p["RESULT_SCHEMA"] > 0)

    bc = build_broadcast(p, "status", "rid-abc")
    ck("广播是显式组件 -n", f"-n {shlex.quote(p['COMPONENT'])}" in bc, bc)
    ck("广播带 stopped-package flag", "-f 32" in bc, bc)
    ck("广播回传 rid", "--es rid 'rid-abc'" in bc or "--es rid rid-abc" in bc, bc)
    ck("广播带 action", f"-a {shlex.quote(p['ACTION'])}" in bc, bc)
    ck("负对照:广播不含隐式 action 通配", "-a '*'" not in bc)

    rid = "rid-ok"
    good = ('{"v":1,"rid":"rid-ok","cmd":"status","ok":true}')
    objs = parse_logcat_lines(good + "\n" +
                              '{"v":1,"rid":"rid-OTHER","cmd":"status","ok":false}\n' +
                              'I/MicroDuckAiDebug: not-json\n' +
                              '{"v":99,"rid":"rid-ok","cmd":"status"}\n', 1)
    ck("只接受 schema 匹配的 JSON", len(objs) == 2, str(objs))
    ck("负对照:别的 rid 不会被选中",
       (pick_result(objs, "rid-ok") or {}).get("rid") == "rid-ok" and
       (pick_result(objs, "rid-OTHER") or {}).get("rid") == "rid-OTHER")
    ck("负对照:不存在的 rid 返回 None（不会拿陈腐行冒充）",
       pick_result(objs, "rid-NOT-SENT") is None)
    ck("负对照:畸形行 / 错 schema 不会冒充结果",
       len(objs) == 2 and all(o.get("v") == 1 for o in objs))

    accepted = {"v": 1, "rid": "r", "cmd": "connect", "phase": "accepted", "ok": True}
    result = {"v": 1, "rid": "r", "cmd": "connect", "phase": "result", "ok": True}
    ck("负对照:phase=accepted 不是终态",
       pick_result([accepted], "r") is None)
    ck("phase=result 是终态", pick_result([accepted, result], "r") == result)
    ck("无 phase 的普通响应是终态",
       pick_result([{"v": 1, "rid": "r", "cmd": "status", "ok": True}], "r") is not None)

    # 检查器自身负对照：把源码里 COMPONENT 改坏，提取结果必须跟着变；删掉常量必须返回 None。
    src = read_policy_source()
    mutated = src.replace(f'const val COMPONENT = "{p["COMPONENT"]}"',
                          'const val COMPONENT = "evil.example/.Receiver"')
    ck("负对照:改坏单一权威常量后提取值跟着变（正则非硬编码）",
       extract_const(mutated, "COMPONENT") == "evil.example/.Receiver")
    ck("负对照:删掉常量定义时提取返回 None",
       extract_const(src.replace(f'const val COMPONENT = "{p["COMPONENT"]}"', ""), "COMPONENT") is None)
    ck("负对照:COMMANDS 结构损坏会抛 BridgeError", _raises(extract_commands, src.replace("linkedSetOf(", "BROKEN(")))

    for name, ok, detail in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"  {detail}" if not ok else ""))
    failed = sum(1 for _, ok, _ in checks if not ok)
    print(f"RESULT: {len(checks) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def _raises(fn, arg) -> bool:
    try:
        fn(arg)
        return False
    except BridgeError:
        return True


# ---------------------------------------------------------------- CLI

def jdump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MicroDuck debug-only AI 控制桥（adb 广播 + Logcat JSON）")
    ap.add_argument("--cmd", choices=None, help="status/scan/connect/mock/rpc/disconnect/help")
    ap.add_argument("--arg", help="connect 用的 BLE MAC 地址")
    ap.add_argument("--method", help="rpc 用的只读方法名")
    ap.add_argument("--params-json", help="rpc 用的 JSON 对象参数（可省略）")
    ap.add_argument("--serial", help="adb -s <serial>，多设备时必填")
    ap.add_argument("--timeout", type=float, default=12.0, help="等结果的最长秒数")
    ap.add_argument("--precheck", action="store_true", help="只做最前置前提检查")
    ap.add_argument("--print-command", action="store_true", help="只打印将发送的 adb shell 命令")
    ap.add_argument("--selftest", action="store_true", help="PC 侧自检（含负对照），不碰 adb")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.cmd and not args.precheck:
        ap.error("需要 --cmd / --precheck / --selftest 之一")

    try:
        policy = load_policy()
        if args.precheck:
            print(jdump(precheck(args.serial, policy)))
            return 0
        if args.cmd not in policy["COMMANDS"]:
            print(jdump({"v": policy["RESULT_SCHEMA"], "cmd": args.cmd, "ok": False,
                         "reason": "CMD_NOT_IN_POLICY",
                         "next": "命令白名单: " + ",".join(policy["COMMANDS"])}))
            return 2
        rid = uuid.uuid4().hex[:12]
        remote = build_broadcast(policy, args.cmd, rid,
                                 arg=args.arg, method=args.method, params_json=args.params_json)
        if args.print_command:
            print(jdump({"v": policy["RESULT_SCHEMA"], "rid": rid, "cmd": args.cmd,
                         "ok": True, "shell": "adb shell " + remote,
                         "logcat": f"adb logcat -s {policy['TAG']}"}))
            return 0
        # 最前置前提：设备在不在线。零应答先查这一条，不先猜蓝牙/GATT。
        devices = adb(args.serial, "devices")
        if not any("\tdevice" in l for l in devices.splitlines()):
            print(jdump({"v": policy["RESULT_SCHEMA"], "rid": rid, "cmd": args.cmd,
                         "ok": False, "reason": "PRECONDITION_FAIL: NO_ONLINE_ADB_DEVICE",
                         "next": "检查 USB 线 / PnP Code 45 需重插线；再跑 --precheck"}))
            return 3
        sent = shell(args.serial, remote)
        if "Broadcast completed" not in sent and "Broadcast" not in sent:
            print(jdump({"v": policy["RESULT_SCHEMA"], "rid": rid, "cmd": args.cmd,
                         "ok": False, "reason": "BROADCAST_NOT_CONFIRMED",
                         "adb_stdout": sent.strip()[:300],
                         "next": "跑 --precheck：确认装的是 debug 变体且组件存在"}))
            return 3
        deadline = time.time() + args.timeout
        last_raw = ""
        while time.time() < deadline:
            last_raw = logcat_dump(args.serial, policy["TAG"])
            hit = pick_result(parse_logcat_lines(last_raw, policy["RESULT_SCHEMA"]), rid)
            if hit is not None:
                print(jdump(hit))
                return 0
            time.sleep(0.4)
        print(jdump({"v": policy["RESULT_SCHEMA"], "rid": rid, "cmd": args.cmd,
                     "ok": False, "reason": "NO_REPLY",
                     "next": "按序查：① --precheck 看 Receiver 是否存在 ② App 是否 stopped（本桥已带 -f 32）"
                             " ③ logcat 是否被过滤 ④ 换 --cmd status 验证通道本身",
                     "logcat_tail": last_raw[-400:]}))
        return 3
    except BridgeError as e:
        print(jdump({"ok": False, "reason": e.reason, "next": e.next_step}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
