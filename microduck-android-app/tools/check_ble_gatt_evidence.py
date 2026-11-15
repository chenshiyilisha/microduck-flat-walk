#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真板 BLE GATT 证据的**机读契约 + 自动派生判定链**（stdlib-only，可进 CI）。

背景（2026-11-14 实机）：PC 侧 bleak 做了只读服务发现、单次 RPC_UUID read，
Android 真机 App 点了 duck-6a07 但握手 FAILED。这些证据原本散在 /tmp 的
探针 stdout 里，一旦机器清理就没了，也没有任何工具能回答「BA-X-5 现在能不能判 PASS」。

本工具把三件事钉死：
  ① 四份**一手原始日志**固化进 tools/evidence/，契约里记 sha256；每次核验重算哈希，
     防止「改了证据不改结论」或被随手替换成别的东西。
  ② 关键观测值从原始日志**重新派生**，并与契约比对；UUID / App API_VERSION 从
     `core/.../Wire.kt` 单一权威正则提取，避免两份清单漂移。
  ③ `BA-X-5` 的充分条件从 `board_acceptance_contract.json` 的 evidence_kind 派生，
     verdict 只由「条件是否都有落盘一手证据」自动推导；**契约里不许手写 verdict**，
     且本工具永远不输出 `PASS`（签收权在 board_acceptance + signoff）。

🔴 证据分级（不把转录伪装成一手日志）：
   · 服务发现 / App 连接 / logcat / 首次 read 失败 → raw_log_persisted=true
   · `API_VERSION=0x25(37)` 那次稳定 read **没有落盘 JSON**，只有会话 stdout 转录
     ⇒ 明确标 `SESSION_STDOUT_TRANSCRIPT` / `TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS`，
       永远不能作为 PASS 级判据；下次上板用 probe 的 --json-out 补一手日志。

用法：
    python tools/check_ble_gatt_evidence.py                 # 核验 + 派生 verdict
    python tools/check_ble_gatt_evidence.py --rebuild       # 从原始日志重生成契约
    python tools/check_ble_gatt_evidence.py --selftest      # 注入式负对照
    python tools/check_ble_gatt_evidence.py --json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
TOOLS = BASE / "tools"
EVIDENCE_DIR = TOOLS / "evidence/2026-11-14-ble-gatt"
CONTRACT_PATH = TOOLS / "ble_gatt_evidence_contract.json"
WIRE_PATH = BASE / "core/src/main/kotlin/io/microduck/app/core/Wire.kt"
BA_CONTRACT_PATH = ROOT / "microduck-software/tools/hd1910/board_acceptance_contract.json"

SCHEMA = 1

RAW_FILES = {
    "GATT_DISCOVERY": EVIDENCE_DIR / "gatt_discovery_readonly.json",
    "API_FIRST_ATTEMPT": EVIDENCE_DIR / "api_version_read_first_attempt_failed.json",
    "APP_CONNECT": EVIDENCE_DIR / "android_app_connect_live.json",
    "LOGCAT_DIAG": EVIDENCE_DIR / "app_gatt_logcat_diag.json",
}

# 未落盘的转录项。这些值来自会话 stdout，不是从文件读出来的 —— 单独隔离，
# 并强制 grade=TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS。
TRANSCRIBED = {
    "id": "API_VERSION_SINGLE_READ_STABLE",
    "raw_log_persisted": False,
    "source_kind": "SESSION_STDOUT_TRANSCRIPT",
    "grade": "TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS",
    "observed_hex": "25",
    "observed_decimal": 37,
    "stable_repeats": 3,
    "note": (
        "首次 read 落盘为 READ_FAILED (BleakError: disconnected)；随后连续 3 次稳定返回 "
        "单字节 0x25，但那几次 stdout 未落盘。数值用 int(hex,16) 与 "
        "int.from_bytes(bytes.fromhex(hex),'little') 两条独立算法互算自洽，"
        "仍不等于有一手日志。下次上板用 probe_ble_api_version.py --json-out 补齐。"
    ),
}

SCOPE = (
    "只登记 2026-11-14 真板 BLE GATT 观测并自动派生 BA-X-5 是否具备充分证据；"
    "不验证整机、不改 ship_verdict、不替代 board_acceptance 的 signoff。"
    "铁律：UNVERIFIED != PASS，COLLECTED != PASS。"
)


# ---------------------------------------------------------------- 单一权威提取

def wire_const(name: str, src: str) -> str | None:
    """从 Wire.kt 正则提取完整值，不硬编码 UUID / 版本号。"""
    m = re.search(r'\bconst val\s+' + re.escape(name) + r'\s*=\s*"([^"]+)"', src)
    if m:
        return m.group(1)
    m = re.search(r'\bconst val\s+' + re.escape(name) + r'\s*=\s*(-?\d+)', src)
    return m.group(1) if m else None


def ba_x5_conditions() -> list[dict]:
    """充分条件不另写一份清单：直接从 board_acceptance_contract.json 的 BA-X-5 派生。"""
    if not BA_CONTRACT_PATH.is_file():
        raise FileNotFoundError(f"PRECONDITION_FAIL: 找不到 {BA_CONTRACT_PATH}")
    d = json.loads(BA_CONTRACT_PATH.read_text(encoding="utf-8"))
    hit = next((c for c in d.get("checks", []) if c.get("id") == "BA-X-5"), None)
    if hit is None:
        raise ValueError("PRECONDITION_FAIL: board_acceptance_contract.json 里没有 BA-X-5")
    return [
        {"id": f"BA-X-5-C{i + 1}", "evidence_kind": kind,
         "status": "UNVERIFIED", "raw_log_id": None}
        for i, kind in enumerate(hit.get("evidence_kind", []))
    ]


# ---------------------------------------------------------------- 原始日志

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_raws() -> dict:
    out = {}
    for rid, p in RAW_FILES.items():
        if not p.is_file():
            raise FileNotFoundError(f"PRECONDITION_FAIL: 缺原始日志 {p}")
        out[rid] = {
            "path": str(p.relative_to(BASE)).replace("\\", "/"),
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
            "data": json.loads(p.read_text(encoding="utf-8")),
        }
    return out


def derive_observations(raws: dict, wire: str) -> dict:
    """所有观测值从**原始日志内容**重算，契约里不允许出现手写的观测数字。"""
    svc_uuid = wire_const("BLE_SERVICE_UUID", wire)
    rpc_uuid = wire_const("BLE_RPC_UUID", wire)
    app_api = wire_const("API_VERSION", wire)
    if not (svc_uuid and rpc_uuid and app_api):
        raise ValueError("PRECONDITION_FAIL: Wire.kt 读不到 BLE UUID / API_VERSION")

    g = raws["GATT_DISCOVERY"]["data"]
    svc = next((s for s in g["services"] if s["uuid"] == svc_uuid), None)
    rpc = next((c for c in (svc or {}).get("characteristics", []) if c["uuid"] == rpc_uuid), None)
    cc = g.get("contract_check", {})
    gatt = {
        "expected_service_uuid": svc_uuid,
        "expected_rpc_uuid": rpc_uuid,
        "service_found": svc is not None,
        "rpc_found": rpc is not None,
        "rpc_properties": (rpc or {}).get("properties", []),
        "rpc_has_cccd": (rpc or {}).get("has_cccd", False),
        "rpc_descriptors": (rpc or {}).get("descriptors", []),
        "target_address": g.get("target"),
        "negative_control_connected": g.get("negative_control", {}).get("connected"),
        "negative_control_error": g.get("negative_control", {}).get("error"),
        "probe_verdict": g.get("verdict"),
        "app_contract_aligned": cc.get("app_contract_aligned"),
        "read_only": g.get("read_only"),
        "forbidden_operations_not_performed": g.get("forbidden_operations_not_performed", []),
    }

    a = raws["APP_CONNECT"]["data"]
    app = {
        "adb_device_online": a.get("adb_device_online"),
        "app_installed": a.get("app_installed"),
        "bluetooth_on": a.get("bluetooth_on"),
        "duck_candidate_found": a.get("duck_candidate_found"),
        "handshake_ready_claimed": a.get("handshake_ready_claimed"),
        "handshake_failed_claimed": a.get("handshake_failed_claimed"),
        "probe_verdict": a.get("verdict"),
        "ba_x_5_claim": a.get("ba_x_5"),
    }

    f = raws["API_FIRST_ATTEMPT"]["data"]
    api_first = {
        "probe_verdict": f.get("verdict"),
        "error": f.get("error"),
        "allowed_writes": f.get("allowed_writes"),
        "connected": f.get("connected"),
    }

    lg = raws["LOGCAT_DIAG"]["data"]
    logcat = {"total_kept": lg.get("total_kept"), "verdict": lg.get("verdict")}

    return {
        "app_api_version_from_wire": int(app_api),
        "gatt_discovery": gatt,
        "android_app_connect": app,
        "api_version_first_attempt": api_first,
        "app_gatt_logcat_diag": logcat,
    }


def build_contract() -> dict:
    raws = load_raws()
    wire = WIRE_PATH.read_text(encoding="utf-8") if WIRE_PATH.is_file() else ""
    if not wire:
        raise FileNotFoundError(f"PRECONDITION_FAIL: 找不到 {WIRE_PATH}")
    return {
        "schema_version": SCHEMA,
        "owner": "tools/check_ble_gatt_evidence.py --rebuild 从原始日志重算；禁止手改 derived 块",
        "scope": SCOPE,
        "observed_on": "2026-11-14",
        "board": {
            "ble_name": raws["GATT_DISCOVERY"]["data"]["candidates"][0]["name"],
            "address": raws["GATT_DISCOVERY"]["data"]["target"],
            "note": "地址仅作缓存；身份判别走 service UUID（App 侧同样口径）",
        },
        "raw_logs": [
            {"id": rid, "path": r["path"], "sha256": r["sha256"], "bytes": r["bytes"]}
            for rid, r in raws.items()
        ],
        "transcribed_observations": [copy.deepcopy(TRANSCRIBED)],
        "derived": derive_observations(raws, wire),
        "ba_x_5_sufficient_conditions": ba_x5_conditions(),
        "derivation_rule": {
            "description": (
                "BA-X-5 verdict 只由充分条件是否都持有『已落盘一手日志』派生；"
                "证据齐全也只到 EVIDENCE_COMPLETE_NOT_SIGNOFF，签收权在 board_acceptance + signoff。"
            ),
            "requires_all_conditions_with_persisted_raw_log": True,
            "forbid_handwritten_verdict_field": True,
            "never_emit_pass": True,
        },
    }


# ---------------------------------------------------------------- 核验 / 派生

def derive_ba_x5(c: dict) -> tuple[str, list[str]]:
    conditions = c.get("ba_x_5_sufficient_conditions", [])
    if not conditions:
        return "PRECONDITION_FAIL_NO_CONDITIONS", ["充分条件清单为空"]
    persisted = {r["id"] for r in c.get("raw_logs", []) if r.get("sha256")}
    unmet = []
    for cond in conditions:
        ok = (cond.get("status") == "COLLECTED"
              and cond.get("raw_log_id") in persisted)
        if not ok:
            unmet.append(cond.get("id", "?"))
    if unmet:
        return "UNVERIFIED_NOT_PASS", unmet
    return "EVIDENCE_COMPLETE_NOT_SIGNOFF", []


def evaluate(c: dict, raws: dict, wire: str) -> list[str]:
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    # ① 契约里不许手写 verdict（否则「派生」就名存实亡）
    for k in ("verdict", "ba_x_5_verdict", "ship_verdict"):
        need(k not in c, f"契约里出现手写 {k} 字段 ⇒ 判定链被绕过")

    # ② 原始日志 sha256 逐份重算
    by_id = {r["id"]: r for r in c.get("raw_logs", [])}
    need(len(by_id) == len(RAW_FILES), "raw_logs 条目数与 RAW_FILES 不一致")
    for rid, actual in raws.items():
        entry = by_id.get(rid)
        need(entry is not None, f"契约缺 raw_log 条目 {rid}")
        if not entry:
            continue
        need(entry.get("sha256") == actual["sha256"],
             f"{rid} sha256 漂移：契约={entry.get('sha256')} 实算={actual['sha256']}")
        need(entry.get("bytes") == actual["bytes"], f"{rid} 字节数漂移")

    # ③ 观测值必须从原始日志重算后与契约逐项相等（不是「自己等于自己」）
    try:
        derived = derive_observations(raws, wire)
    except (ValueError, KeyError) as e:
        errs.append(f"重算观测值失败: {e}")
        derived = None
    if derived is not None:
        need(c.get("derived") == derived,
             "derived 块与原始日志重算结果不一致（改了证据没改结论，或反之间接改了结论）")

    # ④ 转录项：必须如实标未落盘，且数值两条独立算法互算自洽
    trs = c.get("transcribed_observations", [])
    need(len(trs) >= 1, "转录项缺失（API_VERSION=37 的出处会变成无主口述）")
    for t in trs:
        if t.get("raw_log_persisted"):
            need(False, f"{t.get('id')} 标了 raw_log_persisted=true 但没有对应文件 ⇒ 把转录伪装成一手日志")
        need(t.get("grade") == "TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS",
             f"{t.get('id')} grade 不是 TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS")
        try:
            a = int(t["observed_hex"], 16)
            b = int.from_bytes(bytes.fromhex(t["observed_hex"]), "little")
            need(a == t["observed_decimal"] == b,
                 f"{t.get('id')} 转录数值两条算法互算不一致: hex={a} little={b} dec={t['observed_decimal']}")
        except (KeyError, ValueError) as e:
            errs.append(f"{t.get('id')} 转录数值无法互算: {e}")
    # 版本 skew 必须仍存在（板端 37 / App 40）—— 这正是 peerApiVersion 可观测性的动因
    if derived and trs:
        need(derived["app_api_version_from_wire"] != trs[0].get("observed_decimal"),
             "板端读数与 App API_VERSION 相同了：若是真改过 Wire.kt，需同步复核 peerApiVersion 回归锁")

    # ⑤ 充分条件不能凭空标 COLLECTED
    persisted = {r["id"] for r in c.get("raw_logs", []) if r.get("sha256")}
    for cond in c.get("ba_x_5_sufficient_conditions", []):
        if cond.get("status") != "UNVERIFIED":
            need(cond.get("raw_log_id") in persisted,
                 f"{cond.get('id')} 标 {cond.get('status')} 却没有落盘一手日志")
    need(c.get("derivation_rule", {}).get("never_emit_pass") is True,
         "derivation_rule.never_emit_pass 被改掉")
    return errs


# ---------------------------------------------------------------- 注入式负对照

def selftest(base_contract: dict, raws: dict, wire: str) -> list[tuple[str, bool]]:
    """把契约 / 证据故意改坏，检查器必须报错。"""
    def m(label: str, mutate, expect_red: bool = True) -> tuple[str, bool]:
        c = copy.deepcopy(base_contract)
        mutate(c)
        errs = evaluate(c, raws, wire)
        return (label, (len(errs) > 0) == expect_red)

    out = [
        m("手写 ba_x_5_verdict 必红", lambda c: c.update({"ba_x_5_verdict": "PASS"})),
        m("sha256 被改必红",
          lambda c: c["raw_logs"][0].update({"sha256": "0" * 64})),
        m("derived 观测值被改必红",
          lambda c: c["derived"]["gatt_discovery"].update({"rpc_has_cccd": False})),
        m("条件凭空标 COLLECTED 必红",
          lambda c: c["ba_x_5_sufficient_conditions"][0].update({"status": "COLLECTED"})),
        m("转录项伪装成一落盘必红",
          lambda c: c["transcribed_observations"][0].update({"raw_log_persisted": True})),
        m("转录项 grade 被抬高必红",
          lambda c: c["transcribed_observations"][0].update({"grade": "PASS"})),
        m("转录 hex 与 dec 不自洽必红",
          lambda c: c["transcribed_observations"][0].update({"observed_hex": "26"})),
        m("never_emit_pass 被改必红",
          lambda c: c["derivation_rule"].update({"never_emit_pass": False})),
        m("负对照:删掉手写 verdict 的字段后不因该项报错",
          lambda c: c.pop("ba_x_5_verdict", None), expect_red=False),
    ]
    errs = evaluate(base_contract, raws, wire)
    out.append(("正对照:未改动契约零错误", not errs))
    # 派生链本身也要有负对照：把条件全填成 COLLECTED 且挂上真实 raw_log_id 才允许变化
    c2 = copy.deepcopy(base_contract)
    for cond in c2["ba_x_5_sufficient_conditions"]:
        cond["status"] = "COLLECTED"
        cond["raw_log_id"] = c2["raw_logs"][0]["id"]
    v2, unmet2 = derive_ba_x5(c2)
    out.append(("派生链灵敏:条件齐全时 verdict 变化且仍非 PASS",
                v2 == "EVIDENCE_COMPLETE_NOT_SIGNOFF" and not unmet2
                and "PASS" not in v2.replace("NOT_PASS", "")))
    v1, unmet1 = derive_ba_x5(base_contract)
    out.append(("当前证据派生为 UNVERIFIED_NOT_PASS 且列出全部未满足条件",
                v1 == "UNVERIFIED_NOT_PASS" and len(unmet1) == len(c2["ba_x_5_sufficient_conditions"])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="核验真板 BLE GATT 证据契约并自动派生 BA-X-5")
    ap.add_argument("--rebuild", action="store_true", help="从原始日志重生成契约")
    ap.add_argument("--selftest", action="store_true", help="注入式负对照")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = ap.parse_args()

    try:
        raws = load_raws()
        wire = WIRE_PATH.read_text(encoding="utf-8")
        if args.rebuild:
            c = build_contract()
            CONTRACT_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
            print(f"REBUILT {CONTRACT_PATH.relative_to(BASE)}")
        else:
            if not CONTRACT_PATH.is_file():
                print("PRECONDITION_FAIL: 契约不存在，先跑 --rebuild", file=sys.stderr)
                return 2
            c = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"PRECONDITION_FAIL: {e}", file=sys.stderr)
        return 2

    errs = evaluate(c, raws, wire)
    verdict, unmet = derive_ba_x5(c)
    report = {
        "schema_version": SCHEMA,
        "scope": SCOPE,
        "ba_x_5_verdict": verdict,
        "unmet_conditions": unmet,
        "raw_logs_verified": len(raws),
        "transcribed_items": len(c.get("transcribed_observations", [])),
        "evidence_policy": "COLLECTED != PASS; 转录项不作 PASS 级判据",
        "errors": errs,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not errs else 1

    print(f"BA-X-5 (自动派生) = {verdict}")
    print(f"  未满足充分条件 {len(unmet)} 项: {unmet}")
    print(f"  一手日志 sha 校验 {len(raws)}/{len(raws)}  {c['board']['ble_name']} @ {c['board']['address']}")
    print(f"  转录项 {report['transcribed_items']} 条 → NOT_ADMISSIBLE_FOR_PASS")
    for e in errs:
        print("  FAIL  " + e)
    rc = 0 if not errs else 1

    if args.selftest:
        print("\n=== 注入式负对照 ===")
        results = selftest(c, raws, wire)
        for label, ok in results:
            print(("  PASS  " if ok else "  FAIL  ") + label)
            if not ok:
                rc = 1
        print(f"SELFTEST: {sum(1 for _, ok in results if ok)}/{len(results)} passed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
