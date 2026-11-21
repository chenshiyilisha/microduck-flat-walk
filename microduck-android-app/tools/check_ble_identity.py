#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE 身份校验门禁：锁住「身份 = Noise PSK 持钥证明；serial 只是 PSK 归属标签，
不得从 hello 响应读 serial 做硬拒」这条一手协议性质（stdlib-only）。

为什么需要它：fc0382b 在 BleTransport 自造了「hello 响应必须回 result.serial ==
配对码 serial，否则断链」，而三份一手固件（kissqy v167 / DuckBuddy-main / ft1910
的 duck-ipc-proto）`HelloResult` 都**没有 serial 字段** ⇒ 刷加密 btd 后 100% 断链
（真机症状 `hello: BLE_REQUEST_DROPPED id=1`）。功能自检全绿也没抓到，因为测试夹具
FakeGattLink 塞了假 serial 配合这个错误校验。最容易被无声回退的是：
  ① 把 hello serial 硬校验加回；② 夹具再塞假 serial 掩盖；③ 删掉回归断言；
  ④ 一手 HelloResult 被改成带 serial 却没同步（协议 skew 无人发现）。

判据绑一手源码：kissqy v167 `duck-ipc-proto/src/lib.rs:3059` HelloResult =
{api_version, daemon_version, revision}；`btd::secure::Config::load(&path, id)` 的
id = SoC serial 派生 first name（PSK 已绑机器人身份）。判据独立于被测值：正向结构
断言 + 元负对照（改坏必红），不锁数量文案。

用法：
    python tools/check_ble_identity.py
    python tools/check_ble_identity.py --selftest
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
# App 工程实际落点（E:/WorkBuddyData/.../microduck-android-app）
APP_ROOT = BASE
BT = APP_ROOT / "core/src/main/kotlin/io/microduck/app/core/BleTransport.kt"
FAKE = APP_ROOT / "core/src/test/kotlin/io/microduck/app/core/FakeGattLink.kt"
ST = APP_ROOT / "core/src/test/kotlin/io/microduck/app/core/CoreSelfTest.kt"
# 一手固件源（kissqy v167，本 App 对接目标）；缺失就报 PRECONDITION，不静默跳过
FW_PROTO = BASE.parent / "microduck-software/.upstream/kissqy-firmware/versions/v167/microduck-hd1910/firmware/duck-ipc-proto/src/lib.rs"

FILES = {"bt": BT, "fake": FAKE, "st": ST, "fw": FW_PROTO}


def load(srcs: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, p in FILES.items():
        if srcs and k in srcs:
            out[k] = srcs[k]
            continue
        try:
            out[k] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out[k] = ""
    return out


def check(srcs: dict[str, str]) -> list[str]:
    errs: list[str] = []
    bt, fake, st, fw = (srcs.get(k, "") for k in ("bt", "fake", "st", "fw"))

    # ① 一手固件 HelloResult 必须仍是「无 serial」——变了就是协议 skew，需重新判决
    if not fw:
        errs.append("一手固件 HelloResult 源文件缺失/不可读 ⇒ 无法核协议，PRECONDITION_FAIL")
    else:
        # 正则提取完整结构体（ aliphatic：`pub struct HelloResult { ... }` 到第一个 `}`）。
        # 只取 `pub <name>:` 形式的**字段声明**（正向断言），不裸扫注释里的 "serialised"。
        m = re.search(r"pub struct HelloResult\s*\{([^}]*)\}", fw)
        if not m:
            errs.append("一手固件 lib.rs 找不到 HelloResult 定义（结构被改名/移除？）")
        else:
            fields = set(re.findall(r"pub\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", m.group(1)))
            if "serial" in fields:
                errs.append("一手 HelloResult 出现 serial 字段 ⇒ 协议已变，须重新判决身份校验")
            for field in ("api_version", "daemon_version", "revision"):
                if field not in fields:
                    errs.append(f"一手 HelloResult 缺 {field} ⇒ 结构漂移，需复核")

    # ② BleTransport 不得有 hello serial 硬拒（正向：注释可以解释历史，但运行时不得拒）
    if "markDisconnected(\"authenticated robot serial mismatch\")" in bt:
        errs.append("BleTransport 又把 hello serial mismatch 当断链理由（一手 HelloResult 无 serial）")
    if "responseSerial" in bt and "fun responseSerial" in bt:
        errs.append("BleTransport 又引入 responseSerial() 读取不存在的 result.serial")
    if "PendingResponse(" in bt and "expectedSerial" in bt.split("private class PendingResponse", 1)[-1][:200]:
        errs.append("PendingResponse 又带上 expectedSerial 字段（硬校验回退征兆）")
    # 正向：构造参数保留但只作标签，必须有「不校验/持钥证明」语义注释
    if "持钥证明" not in bt or "PSK 归属标签" not in bt:
        errs.append("BleTransport 缺一手身份语义注释（serial 仅标签 / 身份=PSK 持钥证明）")

    # ③ 测试夹具不得塞假 serial（否则掩盖真机 bug）——只看**代码行**，剔除注释行后正向匹配
    code_lines = [ln for ln in fake.splitlines() if not ln.lstrip().startswith(("//", "*"))]
    fake_serial_hit = re.search(r"""["']serial["']\s+to\s+["']FAKE""", "\n".join(code_lines))
    if fake_serial_hit:
        errs.append("FakeGattLink 又给 hello 响应塞假 serial ⇒ 假绿，掩盖真固件无 serial")

    # ④ 回归断言必须在（改坏必红的锚点）
    if "配对serial≠hello响应" not in st:
        errs.append("CoreSelfTest 缺 serial mismatch 回归断言（无法防回退）")

    return errs


def meta_negative_control() -> list[str]:
    """元验证：把关键性质逐个改坏，门禁必须变红；全绿说明门禁是假绿。"""
    base = load()
    errs: list[str] = []
    if check(base):
        errs.append("元验证前置失败：正常源码下门禁就不 OK")
        return errs

    trials = [
        ("改坏:加回 serial 硬拒", {"bt": base["bt"] + "\nmarkDisconnected(\"authenticated robot serial mismatch\")\n"}),
        ("改坏:加回 responseSerial", {"bt": base["bt"] + "\nfun responseSerial(x:String)=x\n"}),
        ("改坏:夹具塞假 serial", {"fake": base["fake"] + "\n\"serial\" to \"FAKE0001\"\n"}),
        ("改坏:删回归断言", {"st": base["st"].replace("配对serial≠hello响应", "")}),
        ("改坏:一手 HelloResult 漂移", {"fw": base["fw"].replace("pub struct HelloResult", "pub struct HelloResultX")}),
    ]
    for label, patch in trials:
        srcs = dict(base)
        srcs.update(patch)
        if not check(srcs):
            errs.append(f"元负对照失效：{label} 后门禁仍 OK（假绿）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="运行门禁自身元负对照")
    args = ap.parse_args()

    if args.selftest:
        errs = meta_negative_control()
        n = 5
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
    print("VERDICT: OK — BLE 身份=PSK 持钥证明、无 hello serial 硬拒（非整机签收）")
    print("RESULT: 0 errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
