#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A2 配网 / A2' 加密门禁：锁住「明文风险显性化 + psk 脱敏 + Mock 隔离 + deny_unknown_fields
+ 加密不接入真实配网」这组结构性质，防止被无声回退成「看着像安全配网」的假绿（stdlib-only）。

为什么需要它：本功能继承原厂 §8.1 的 pre-shipping blocker——目标固件明文传 Wi-Fi 密码、
固件端零加密实现。功能测试全绿也证明不了「安全交付」，最容易被后人「顺手」破坏的是：
  ① 把明文警示删掉/软化（用户以为安全）；② psk 落日志/快照（凭据泄漏）；
  ③ Mock 下写真网络（伪造实机行为）；④ net.connect 参数多带键（deny_unknown_fields=-32602）；
  ⑤ 把加密原语接进真实配网（固件解不开 = 假绿）。

判据绑一手 fanhao 副本 API40：route.rs:139-155（明文）、lib.rs:2957（NetConnectParams）、
app-path-design.md §8.1（blocker/三候选）。判据独立于被测值：只锁结构签名，不锁数量文案。
verdict: OK / NOT_PASS / UNVERIFIED_ARTIFACTS_ABSENT；末尾打印 RESULT: N errors。

用法：
    python tools/check_net_provisioning.py
    python tools/check_net_provisioning.py --selftest
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
    "net": CORE / "NetSnapshot.kt",
    "prov": CORE / "NetProvisioning.kt",
    "crypto": CORE / "ProvisioningCrypto.kt",
    "vm": APP / "MainViewModel.kt",
    "activity": APP / "MainActivity.kt",
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
    net = code_only(src["net"])
    prov = code_only(src["prov"])
    crypto = code_only(src["crypto"])
    vm = code_only(src["vm"])
    act = code_only(src["activity"])

    # ① Wire.Method 一手常量（方法名照抄 lib.rs pub mod method）
    for name, value in {
        "NET_STATUS": "net.status", "NET_SCAN": "net.scan",
        "NET_CONNECT": "net.connect", "NET_FORGET": "net.forget",
    }.items():
        need(re.search(rf"const val {name}\s*=\s*\"{re.escape(value)}\"", wire) is not None,
             f"Wire.Method 缺 {name} = \"{value}\"")

    # ② 只读白名单含 NET_STATUS/NET_SCAN（断链后可安全重放）；写类 net.connect/forget 不得进白名单
    ro_m = re.search(r"private fun isReadOnly\([^)]*\)\s*:\s*Boolean\s*=\s*method in setOf\(([^)]*)\)",
                     session, re.S)
    need(ro_m is not None, "RobotSession.isReadOnly 的 setOf 白名单未找到")
    ro = ro_m.group(1) if ro_m else ""
    for name in ("NET_STATUS", "NET_SCAN"):
        need(f"Method.{name}" in ro, f"isReadOnly 缺 Method.{name}（只读查询断链后无法重放）")
    for name in ("NET_CONNECT", "NET_FORGET"):
        need(f"Method.{name}" not in ro, f"isReadOnly 误含写方法 Method.{name}（写类不可自动重放）")

    # ③ net.connect 参数 deny_unknown_fields：connectParams 只准 ssid + 可选 psk，无额外键
    cp = body_of(prov, "fun connectParams")
    need(bool(cp), "NetProvisioning.connectParams 未找到")
    # psk 用 m["psk"] = psk 索引赋值（开放网络不写该键），ssid 用 "ssid" to；两种写法都提取
    cp_keys = set(re.findall(r'"(\w+)"\s+to', cp)) | set(re.findall(r'\[\s*"(\w+)"\s*\]\s*=', cp))
    need(cp_keys == {"ssid", "psk"},
         f"net.connect 参数键集不符（应 ssid/psk，实际 {cp_keys}；deny_unknown_fields 会 -32602）")

    # ④ 明文风险警示常驻且点名 §8.1（UI 与 core 都要有；不得软化成「安全」）
    need("PLAINTEXT_TRANSPORT_WARNING" in prov, "NetProvisioning 缺明文风险警示常量")
    need("8.1" in src["prov"], "明文警示未点名原厂 §8.1 blocker")
    need("PLAINTEXT_TRANSPORT_WARNING" in act,
         "MainActivity UI 未展示明文风险警示（用户会被误导为安全配网）")
    need("confirmConnectWifi" in act, "连接 Wi-Fi 无二次确认（写操作不可静默执行）")

    # ⑤ psk 不落日志/快照：Repository 的 Snapshot 不含 psk 字段，connectWifi 只把 psk 传给 connectParams
    snap = body_of(repo, "data class Snapshot")
    need("psk" not in snap.lower(), "RobotRepository.Snapshot 含 psk（凭据进快照 = 泄漏）")
    cw = body_of(repo, "fun connectWifi")
    need('connectParams(ssid, psk)' in cw, "connectWifi 未走 connectParams 构造（可能手写多键）")
    need("Log." not in cw and "println" not in cw, "connectWifi 含日志输出（psk 可能落日志）")

    # ⑥ Mock 隔离：三方法都排除 Mock，且写方法要求 READY
    for fn in ("refreshNet", "connectWifi", "forgetWifi"):
        b = body_of(repo, f"fun {fn}")
        need('kind == "MOCK"' in b, f"{fn} 未排除 Mock（伪造实机网络行为）")
        need("RobotSession.State.READY" in b, f"{fn} 未要求会话 READY")
    # 写类不可自动重放
    for fn in ("connectWifi", "forgetWifi"):
        b = body_of(repo, f"fun {fn}")
        need("replayable = false" in b, f"{fn} 未显式 replayable=false（写类不可断链重放）")

    # ⑦ 缺数据不造假：NetSnapshot 用 nullable + isEmpty，未连接不填 0/假 IP
    need("data class NetSnapshot" in net, "NetSnapshot 数据类缺失")
    need("isEmpty" in net, "NetSnapshot 缺 isEmpty（UI 无法区分未查询/空数据）")
    need("signal: Int?" in net and "ip4: String?" in net, "NetSnapshot 可选量非 nullable（可能填 0/假 IP）")
    # 解析未连接缺字段：fromStatus 缺 state 返回 null
    ns = body_of(net, "fun fromStatus")
    need("?:" in ns and "return null" in ns, "NetSnapshot.fromStatus 缺 state 未视为未读到")

    # ⑧ 加密仅预埋、默认不接入配网：INTEROP_UNVERIFIED 恒真 + Repository 不引用 ProvisioningCrypto
    need("const val INTEROP_UNVERIFIED = true" in crypto, "ProvisioningCrypto 缺 INTEROP_UNVERIFIED 恒真（可能误判可交付）")
    need(re.search(r"Rfc7748|RFC 7748", src["crypto"]) is not None, "加密原语缺 RFC7748 KAT 向量")
    need("HmacSHA256" in crypto, "加密原语缺 HKDF-SHA256 实现依据")
    need("ProvisioningCrypto" not in repo, "RobotRepository 引用了 ProvisioningCrypto（加密接入真实配网 = 固件解不开的假绿）")
    need("ProvisioningCrypto" not in prov, "NetProvisioning 引用了加密原语（默认路径应明文，接入需先做固件对接）")

    # ⑨ ViewModel / UI 事件链完整
    for ev in ("onRefreshNet", "onConnectWifi", "onForgetWifi"):
        need(re.search(rf"fun {ev}\(", vm) is not None, f"MainViewModel 缺事件 {ev}")
    need("netStatusText" in act and "netResultText" in act, "MainActivity 缺配网状态/结果展示")

    # ⑩ SSID 必须「可从 net.scan 结果点选」，而非只能手录
    # 一手依据 configd/src/nm.rs:567 —— connect() 先 scan() 找 SSID，扫不到必 NotFound，
    # 故点选扫描项是固件唯一保证能找到网络的输入方式；手输仍须保留兜底（扫描为空）。
    need("netScanList" in act, "MainActivity 缺扫描列表容器（SSID 又被改回只能手录）")
    need("选择网络" in act, "扫描项缺 contentDescription（真机/无障碍无法定位点选项）")
    scan_body = body_of(act, "fun rebuildNetScanList")
    need("setOnClickListener" in scan_body, "扫描列表项无点击监听（点选不能填入 SSID）")
    sel_body = body_of(act, "fun selectScannedSsid")
    need("netSsidEdit.setText" in sel_body, "点选处理未把 SSID 填入输入框")
    need("netPskEdit" not in sel_body, "点选处理碰了密码框（会覆盖用户已输入的密码）")
    # 手输兜底：允许两种等价构造（直接 EditText(...) / inflate 布局后 findViewById），
    # 但必须真实把 netSsidEdit 绑定成 EditText。2026-11-20 实测：SSID 框改成
    # widget_outlined_field 布局后，裸字面量 "netSsidEdit = EditText" 假红，
    # 而旧负对照因注入不命中变成「假绿」——故改语义判据 + 动态注入（见 selftest）。
    ssid_assign = re.search(r"netSsidEdit\s*=\s*([^\n]+)", act)
    need(ssid_assign is not None,
         "手输 SSID 兜底被删（netSsidEdit 从未赋值，扫描为空时无法配网）")
    ssid_rhs = ssid_assign.group(1).strip() if ssid_assign else ""
    need("EditText(" in ssid_rhs or "findViewById" in ssid_rhs,
         f"netSsidEdit 未绑定到 EditText（赋值 {ssid_rhs!r}；扫描为空时无法配网）")
    need(re.search(r"var\s+netSsidEdit\s*:\s*EditText", act) is not None,
         "netSsidEdit 未声明为 EditText 类型（手输兜底类型不保）")
    need("netScanSignature" in act, "扫描列表缺 tick 节流签名（1s tick 会持续重建 View/发事件）")

    verdict = "NOT_PASS" if errs else "OK"
    if not quiet:
        print(f"VERDICT = {verdict}")
        print(f"RESULT: {len(errs)} errors")
    return verdict, errs


def selftest(src: dict[str, str]) -> list[tuple[str, bool]]:
    """注入式负对照：把配网安全链改坏，判据必须变红。"""
    def variant(**kw: str) -> dict[str, str]:
        return {**src, **kw}

    def break_mock_guard(repo_src: str, fn: str) -> str:
        """只把某个函数体里的 MOCK 守卫去掉，验证 ⑥ 判据能抓到。"""
        raw = body_of(repo_src, f"fun {fn}")
        if not raw:
            return repo_src
        broken = raw.replace('kind == "MOCK"', 'kind == "NO_MOCK"')
        return repo_src.replace(raw, broken, 1)

    def break_ssid_fallback(act_src: str) -> str:
        """动态定位当前真实赋值行再删：SSID 框的构造方式换过（inflate 布局），
        写死旧字面量的注入会静默不命中 → 负对照假绿。改法变了，注入必须跟着变。"""
        m = re.search(r"netSsidEdit\s*=\s*[^\n]+", act_src)
        return act_src.replace(m.group(0), "/* 手输兜底被删 */", 1) if m else act_src

    wire = src.get("wire", "")
    session = src.get("session", "")
    repo = src.get("repo", "")
    prov = src.get("prov", "")
    crypto = src.get("crypto", "")
    act = src.get("activity", "")

    cases: list[tuple[str, dict[str, str]]] = [
        ("负对照:Wire 删 net.connect 常量必红",
         variant(wire=wire.replace('const val NET_CONNECT = "net.connect"', ''))),
        ("负对照:isReadOnly 误含写方法 net.connect 必红",
         variant(session=session.replace("Method.NET_SCAN,", "Method.NET_SCAN, Method.NET_CONNECT,"))),
        ("负对照:net.connect 参数多带非法键必红",
         variant(prov=prov.replace('val m = linkedMapOf<String, Any?>("ssid" to ssid)',
                                   'val m = linkedMapOf<String, Any?>("ssid" to ssid, "token" to 1)'))),
        ("负对照:UI 删明文警示展示必红",
         variant(activity=act.replace("PLAINTEXT_TRANSPORT_WARNING", "PLAINTEXT_PLACEHOLDER"))),
        ("负对照:connectWifi 放开 Mock 必红",
         variant(repo=break_mock_guard(repo, "connectWifi"))),
        ("负对照:写类去掉 replayable=false 必红",
         variant(repo=repo.replace("replayable = false", "replayable = true"))),
        ("负对照:INTEROP_UNVERIFIED 改成 false 必红",
         variant(crypto=crypto.replace("const val INTEROP_UNVERIFIED = true", "const val INTEROP_UNVERIFIED = false"))),
        ("负对照:Repository 误接入加密原语必红",
         variant(repo=repo.replace("class RobotRepository(",
                                   "class RobotRepository(\n    private val cryptoRef = ProvisioningCrypto.INTEROP_UNVERIFIED,"))),
        ("负对照:扫描项删点击监听必红",
         variant(activity=act.replace("setOnClickListener { selectScannedSsid(net.ssid) }", ""))),
        ("负对照:点选误清空密码框必红",
         variant(activity=act.replace("fun selectScannedSsid(ssid: String) {",
                                       "fun selectScannedSsid(ssid: String) {\n        netPskEdit.setText(\"\")"))),
        ("负对照:扫描列表去掉 tick 节流必红",
         variant(activity=act.replace("netScanSignature", "netScanSigUnused"))),
        ("负对照:删掉手输 EditText 必红",
         variant(activity=break_ssid_fallback(act))),
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
