#!/usr/bin/env python3
"""B7: a READ-ONLY capture plan for the first day on the real robot.

Why this exists (2026-11-11)
---------------------------
B5's L1 sign-off chain lists five things still owed on hardware (15-joint
identify / p8head_2999 load / control.43 / gamepad mapping / 5 GHz Wi-Fi), and
B1 has a 24-item acceptance checklist -- but there is no runnable capture
script. This tool is the *skeleton*: it turns those two authoritative files into
a human capture sheet, and can later read COLLECTED evidence records.

Hard boundaries (deliberate, with negative controls):
  * It NEVER executes a command, opens a serial port, or touches the network.
    live_hardware_accessed=false, always. The `command` strings in B1 are
    human instructions, not shell input.
  * It NEVER prints PASS / SHIPPABLE. Even with every record present the
    verdict is COLLECTED (B1 rule: COLLECTED != PASS; closure needs a human
    signature with measured evidence).
  * Every captured item is DERIVED from board_acceptance_contract.json#checks;
    the five owed items come from deploy_chain_contract.json#chains[...].still_owed.
    No third copy of either list.
  * Negative control "pull the IMU": if the IMU check has no COLLECTED record,
    the verdict must be INCOMPLETE with that reason.

Usage (cwd = microduck-software):
    python tools/hd1910/board_capture.py --plan
    python tools/hd1910/board_capture.py --check
    python tools/hd1910/board_capture.py --check --json
    python tools/hd1910/board_capture.py --verify --evidence-dir DIR --json
    python tools/hd1910/board_capture.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
sys.path.insert(0, str(HERE))

import link_evidence  # noqa: E402  (one authoritative COLLECTED-record validator)

BOARD = HERE / "board_acceptance_contract.json"
CHAIN = HERE / "deploy_chain_contract.json"
L1_CHAIN_ID = "L1_CONSOLE_R17_V167"

# (stable key, anchor that must hit EXACTLY ONE still_owed sentence, B1 check ids)
# wifi_5g is intentionally EMPTY: B1 has no Wi-Fi check. That is a real gap and
# must be reported as such, not papered over with a plausible-looking check id.
OWED_SPECS = (
    ("joint_identify", "identify", ("BA-4-1", "BA-5-2")),
    # BA-7-1 is LINE_MISMATCH in B1 (the B-gen publish -> robotctl chain is
    # forbidden for L1). Only BA-7-2 (CURRENT, V167 console) may be captured.
    ("policy_load", "p8head_2999", ("BA-7-2",)),
    ("control_43", "control.43", ("BA-X-1",)),
    ("gamepad_mapping", "手柄", ("BA-X-2",)),
    ("wifi_5g", "5GHz", ()),
)

# Pull-the-IMU negative control. BA-5-2 is the bus IMU (ID200 / identity bytes).
IMU_CHECK_IDS = ("BA-5-2",)
IMU_CLOSURE_REF = "INCONCLUSIVE_LIVE_IDENTIFY"

SAFETY_PRELUDE = (
    "卸力 + 机器人有支撑 + 低增益起步；任何写 EEPROM / 切 mode / 加载策略的动作"
    "都不属于本采集表，本工具也不执行任何命令。",
)


def load_json(path: Path) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def signoff_chain(contract: dict) -> dict:
    for c in contract["chains"]:
        if c["id"] == L1_CHAIN_ID:
            return c
    raise KeyError("L1 sign-off chain %s missing" % L1_CHAIN_ID)


def required_check_ids(specs: tuple = OWED_SPECS) -> list[str]:
    out: list[str] = []
    for _, _, ids in specs:
        for i in ids:
            if i not in out:
                out.append(i)
    return out


def build_plan(board: dict, chain: dict,
               specs: tuple = OWED_SPECS) -> dict:
    still = list(chain.get("still_owed") or [])
    checks = {c["id"]: c for c in board["checks"]}
    owed: list[dict] = []
    hit_texts: list[str] = []
    for key, anchor, ids in specs:
        hits = [x for x in still if anchor in x]
        hit_texts.extend(hits)
        owed.append({
            "key": key,
            "anchor": anchor,
            "anchor_hits": len(hits),
            "owed_text": hits[0] if hits else "",
            "check_ids": list(ids),
            "unmapped": not ids,
            "items": [dict(checks[i]) for i in ids if i in checks],
        })
    # Derive, never invent: which B1 checks are historical / cross-line and
    # therefore must NOT appear on the L1 capture sheet.
    excluded = [{"id": c["id"], "authority": c["authority"]}
                for c in board["checks"] if c.get("authority") != "CURRENT"]
    # Wi-Fi has no standalone B1 check; report exactly where it IS mentioned.
    wifi_mentions = [c["id"] for c in board["checks"]
                     if "5GHz" in str(c.get("pass_criterion", ""))]
    return {
        "still_owed": still,
        "owed": owed,
        "unmapped_owed": [o["key"] for o in owed if o["unmapped"]],
        "anchor_coverage": sorted(hit_texts) == sorted(still),
        "required_check_ids": required_check_ids(specs),
        "excluded_non_current_checks": excluded,
        "wifi_mentioned_in": wifi_mentions,
        "forbidden_commands": list(chain.get("forbidden_commands_for_this_chain") or []),
        "safety_prelude": list(SAFETY_PRELUDE),
        "live_hardware_accessed": False,
    }


def validate(board: dict, chain: dict, plan: dict,
             specs: tuple = OWED_SPECS) -> list[str]:
    """Positive structural assertions. Empty list means the plan is sound."""
    p: list[str] = []
    checks = {c["id"]: c for c in board["checks"]}
    still = plan["still_owed"]
    if len(still) != len(specs):
        p.append("still_owed has %d items but %d capture specs are declared"
                 % (len(still), len(specs)))
    if not plan["anchor_coverage"]:
        p.append("anchors do not cover every still_owed item exactly once")
    for o in plan["owed"]:
        if o["anchor_hits"] != 1:
            p.append("%s anchor %r hits %d owed items, want exactly 1"
                     % (o["key"], o["anchor"], o["anchor_hits"]))
        for cid in o["check_ids"]:
            c = checks.get(cid)
            if c is None:
                p.append("%s references unknown B1 check %s" % (o["key"], cid))
                continue
            for field in ("pass_criterion", "command", "evidence_kind"):
                if not c.get(field):
                    p.append("B1 check %s has no %s" % (cid, field))
            # POSITIVE assertion: a historical / cross-line B1 entry must never
            # become an L1 capture instruction (BA-7-1 is LINE_MISMATCH).
            if c.get("authority") != "CURRENT":
                p.append("B1 check %s is %s, not CURRENT; it must not appear "
                         "on the L1 capture sheet" % (cid, c.get("authority")))
            for bad in plan["forbidden_commands"]:
                if bad and bad in str(c.get("command", "")):
                    p.append("B1 check %s command contains a forbidden L1 command: %s"
                             % (cid, bad))
    for cid in IMU_CHECK_IDS:
        c = checks.get(cid)
        if c is None:
            p.append("pull-the-IMU control references unknown check %s" % cid)
        elif IMU_CLOSURE_REF not in (c.get("closure_refs") or []):
            p.append("%s is no longer tied to %s; the IMU negative control is stale"
                     % (cid, IMU_CLOSURE_REF))
    if not plan["forbidden_commands"]:
        p.append("L1 chain has no forbidden_commands_for_this_chain")
    if not any(x["id"] == "BA-7-1" and x["authority"] == "LINE_MISMATCH"
               for x in plan["excluded_non_current_checks"]):
        p.append("BA-7-1 is no longer LINE_MISMATCH; re-review the policy_load mapping")
    if not plan["wifi_mentioned_in"]:
        p.append("Wi-Fi is not mentioned in any B1 criterion; re-review the Wi-Fi gap")
    if plan["live_hardware_accessed"] is not False:
        p.append("capture plan must declare live_hardware_accessed=false")
    if not plan["safety_prelude"]:
        p.append("capture plan has no safety prelude")
    if not plan["unmapped_owed"]:
        # A gap that silently disappears is exactly the kind of false green
        # this tool exists to prevent: if wifi_5g somehow maps to a check,
        # the report must say so rather than pretending everything is covered.
        p.append("no unmapped owed item reported -- re-check the Wi-Fi gap")
    return p


def capture_verdict(board: dict, plan: dict, evidence_dir: Path,
                    verify: bool = False) -> dict:
    """Read COLLECTED records only. Never prints PASS, never signs off."""
    records, read_problems = link_evidence.collect_records(evidence_dir)
    check_ids = {c["id"] for c in board["checks"]}
    rec_problems = link_evidence.validate_records(records, check_ids, verify)
    present = {r.get("id") for r in records if r.get("verdict") == "COLLECTED"}
    needed = plan["required_check_ids"]
    missing = [x for x in needed if x not in present]
    imu_missing = [x for x in IMU_CHECK_IDS if x not in present]
    problems = read_problems + rec_problems
    return {
        "capture_verdict": "INCOMPLETE" if (missing or problems) else "COLLECTED",
        "needed_check_ids": needed,
        "missing_check_ids": missing,
        "imu_missing_check_ids": imu_missing,
        "collected_records": len(records),
        "problems": problems,
        "note": "COLLECTED != PASS: closure needs a human signature with measured "
                "evidence; this tool never judges the robot shippable.",
        "live_hardware_accessed": False,
    }


def report(board: dict, chain: dict, specs: tuple = OWED_SPECS) -> dict:
    plan = build_plan(board, chain, specs)
    problems = validate(board, chain, plan, specs)
    return {
        "tool": "board_capture.py",
        "sources": ["board_acceptance_contract.json#checks",
                    "deploy_chain_contract.json#chains[%s].still_owed" % L1_CHAIN_ID],
        "plan": plan,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "capture_verdict": "NOT_RUN (no hardware, no evidence read)",
        "live_hardware_accessed": False,
        "scope": "上机当天只读采集表；不执行命令、不碰串口/网络、不判 PASS、不消任何悬案",
    }


def print_plan(plan: dict) -> None:
    print("# 上机当天只读采集表（B7 骨架）")
    print("")
    print("> " + plan["safety_prelude"][0])
    print("> 本工具**不执行任何命令**；下面 `command` 是给人的采集指引，不是 shell 输入。")
    print("> live_hardware_accessed=false；采集结果一律记 COLLECTED，不等于 PASS。")
    print("")
    print("| 必闭合项 | 采集项 | 判据（B1 原文） | 采集指引 | 证据 | 关联悬案 |")
    print("|---|---|---|---|---|---|")
    for o in plan["owed"]:
        if not o["items"]:
            print("| %s | ⚠️ **B1 无对应 check（真实缺口）** | — | 待补 check | — | — |"
                  % o["key"])
            continue
        for c in o["items"]:
            print("| %s | %s %s | %s | %s | %s | %s |"
                  % (o["key"], c["id"], c["title"],
                     str(c.get("pass_criterion", "")).replace("|", "/"),
                     str(c.get("command", "")).replace("|", "/"),
                     "/".join(c.get("evidence_kind") or []),
                     "/".join(c.get("closure_refs") or []) or "—"))
    print("")
    print("禁用命令（路①）：" + " ; ".join(plan["forbidden_commands"]))
    print("未映射必闭合项：" + (", ".join(plan["unmapped_owed"]) or "无")
          + "；Wi-Fi 无独立 B1 check，仅在 "
          + (", ".join(plan["wifi_mentioned_in"]) or "无") + " 的判据里被顺带提及")
    print("已排除的非 CURRENT 条目（不得当路① 采集指引）："
          + ", ".join("%s=%s" % (x["id"], x["authority"])
                      for x in plan["excluded_non_current_checks"]))


def _fake_record(cid: str) -> dict:
    return {"id": cid, "verdict": "COLLECTED",
            "evidence_sha256": hashlib.sha256(cid.encode()).hexdigest(),
            "evidence_bytes": len(cid), "evidence_path": "", "value": "simulated"}


def selftest() -> int:
    board, contract = load_json(BOARD), load_json(CHAIN)
    chain = signoff_chain(contract)
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    rep = report(board, chain)
    ck("盘上采集表结构自校验通过", not rep["problems"],
       "; ".join(rep["problems"][:2]))
    plan = rep["plan"]
    ck("真对照：5 条必闭合项全部绑定且锚点唯一",
       len(plan["owed"]) == 5 and all(o["anchor_hits"] == 1 for o in plan["owed"]))
    ck("真对照：Wi-Fi 缺口被如实报出（不硬凑 check）",
       plan["unmapped_owed"] == ["wifi_5g"], str(plan["unmapped_owed"]))
    ck("真对照：采集项全部来自 B1 且带判据/证据",
       all(x for o in plan["owed"] for x in o["items"])
       and all(c.get("pass_criterion") and c.get("evidence_kind")
               for o in plan["owed"] for c in o["items"]))
    ck("真对照：所有采集项 authority=CURRENT（B 代 publish 链已排除）",
       all(c.get("authority") == "CURRENT"
           for o in plan["owed"] for c in o["items"]))
    ck("真对照：BA-7-1 作为 LINE_MISMATCH 被如实列进排除项",
       any(x["id"] == "BA-7-1" and x["authority"] == "LINE_MISMATCH"
           for x in plan["excluded_non_current_checks"]))
    ck("真对照：Wi-Fi 仅被顺带提及、无独立 check",
       plan["wifi_mentioned_in"] == ["BA-X-2"], str(plan["wifi_mentioned_in"]))
    ck("声明未碰硬件且不判 PASS",
       rep["live_hardware_accessed"] is False and "PASS" not in rep["capture_verdict"])

    # Structural negative controls -----------------------------------------
    bad_chain = copy.deepcopy(chain)
    bad_chain["still_owed"][0] = bad_chain["still_owed"][0].replace("identify", "renamed")
    ck("负对照：锚点在契约里消失必红",
       any("hits 0" in x for x in validate(board, chain, build_plan(board, bad_chain))))
    short = OWED_SPECS[:4]
    ck("负对照：删一条必闭合映射必红",
       any("capture specs" in x for x in validate(board, chain,
                                                  build_plan(board, chain, short), short)))
    ghost = OWED_SPECS[:4] + (("wifi_5g", "5GHz", ("BA-DOES-NOT-EXIST",)),)
    ck("负对照：给 Wi-Fi 硬凑不存在的 check 必红",
       any("unknown B1 check" in x for x in validate(board, chain,
                                                     build_plan(board, chain, ghost), ghost)))
    filled = OWED_SPECS[:4] + (("wifi_5g", "5GHz", ("BA-3-2",)),)
    ck("负对照：Wi-Fi 缺口被悄悄填掉也必须红（防止假绿）",
       any("no unmapped owed item" in x for x in validate(board, chain,
                                                          build_plan(board, chain, filled), filled)))
    bad_board = copy.deepcopy(board)
    next(c for c in bad_board["checks"] if c["id"] == "BA-7-2")["command"] = \
        chain["forbidden_commands_for_this_chain"][1]
    ck("负对照：采集指引里混入 B 代禁用命令必红",
       any("forbidden L1 command" in x
           for x in validate(bad_board, chain, build_plan(bad_board, chain))))
    stale_authority = copy.deepcopy(board)
    next(c for c in stale_authority["checks"] if c["id"] == "BA-7-2")["authority"] = \
        "LINE_MISMATCH"
    ck("负对照：把 CURRENT 采集项改成跨线条目必红",
       any("not CURRENT" in x for x in validate(
           stale_authority, chain, build_plan(stale_authority, chain))))
    no_wifi = copy.deepcopy(board)
    next(c for c in no_wifi["checks"] if c["id"] == "BA-X-2")["pass_criterion"] = \
        "手柄各按键与动作映射实测通过"
    ck("负对照：Wi-Fi 连顺带提及都消失时必红（要求重新审视缺口）",
       any("re-review the Wi-Fi gap" in x for x in validate(
           no_wifi, chain, build_plan(no_wifi, chain))))
    bad_imu = copy.deepcopy(board)
    next(c for c in bad_imu["checks"] if c["id"] == "BA-5-2")["closure_refs"] = []
    ck("负对照：IMU 检查与认板悬案脱钩必红",
       any("IMU negative control is stale" in x
           for x in validate(bad_imu, chain, build_plan(bad_imu, chain))))

    # Pull-the-IMU negative control ----------------------------------------
    with tempfile.TemporaryDirectory(prefix="md_b7_ev_") as td:
        edir = Path(td)
        # every needed record EXCEPT the IMU one == "IMU unplugged"
        for cid in plan["required_check_ids"]:
            if cid in IMU_CHECK_IDS:
                continue
            (edir / ("%s.json" % cid)).write_text(
                json.dumps(_fake_record(cid)), encoding="utf-8")
        unplugged = capture_verdict(board, plan, edir, verify=False)
        ck("负对照：拔掉 IMU（缺 BA-5-2 证据）必 INCOMPLETE",
           unplugged["capture_verdict"] == "INCOMPLETE"
           and unplugged["imu_missing_check_ids"] == list(IMU_CHECK_IDS),
           str(unplugged["missing_check_ids"]))
        # now add the IMU record: still NOT a PASS
        (edir / "BA-5-2.json").write_text(
            json.dumps(_fake_record("BA-5-2")), encoding="utf-8")
        complete = capture_verdict(board, plan, edir, verify=False)
        ck("真实证据齐了也只判 COLLECTED，绝不 PASS",
           complete["capture_verdict"] == "COLLECTED"
           and "PASS" not in complete["capture_verdict"], str(complete))
        forged = _fake_record("BA-5-2")
        forged["verdict"] = "PASS"
        (edir / "BA-5-2.json").write_text(json.dumps(forged), encoding="utf-8")
        ck("负对照：伪造 PASS 记录必被拒（COLLECTED 唯一合法）",
           any("is not COLLECTED" in x
               for x in capture_verdict(board, plan, edir, verify=False)["problems"]))

    # Real CLI entry points --------------------------------------------------
    script = str(Path(__file__).resolve())
    for args, needle in ((("--plan",), "# 上机当天只读采集表"),
                         (("--check", "--json"), '"structure_verdict": "PASS"')):
        r = subprocess.run([sys.executable, script, *args],
                           cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("CLI 真跑：%s rc=0 且输出含 %r" % (" ".join(args), needle),
           r.returncode == 0 and needle in r.stdout,
           "rc=%s %s" % (r.returncode, r.stderr[-120:]))

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name,
                               ("  <- " + note) if note else ""))
    bad = [n for n, ok, _ in checks if not ok]
    print("\nboard_capture selftest: %d/%d passed" % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("scope: read-only capture plan; no command executed, no hardware, no sign-off.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="print the human capture sheet")
    ap.add_argument("--check", action="store_true", help="validate plan structure")
    ap.add_argument("--verify", action="store_true", help="read COLLECTED records only")
    ap.add_argument("--evidence-dir", default="", help="directory of B1 --record JSON files")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--selftest", action="store_true", help="negative controls, no hardware")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    board, contract = load_json(BOARD), load_json(CHAIN)
    chain = signoff_chain(contract)
    rep = report(board, chain)

    if args.verify:
        edir = Path(args.evidence_dir) if args.evidence_dir else Path(".")
        cap = capture_verdict(board, rep["plan"], edir, verify=False)
        rep["capture_verdict"] = cap["capture_verdict"]
        rep["capture"] = cap
        if cap["problems"]:
            rep["structure_verdict"] = "FAIL"
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print("capture_verdict = %s (COLLECTED != PASS)" % cap["capture_verdict"])
            print("missing checks = %s" % (cap["missing_check_ids"] or "none"))
            print("IMU missing = %s" % (cap["imu_missing_check_ids"] or "none"))
            for x in cap["problems"]:
                print("  [FAIL] " + x)
        return 0 if not cap["problems"] else 1

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif args.plan:
        print_plan(rep["plan"])
    else:
        print("capture items = %d (derived from B1 checks)" % len(rep["plan"]["required_check_ids"]))
        print("owed items = %d (derived from B5 still_owed)" % len(rep["plan"]["owed"]))
        print("unmapped owed = %s" % (", ".join(rep["plan"]["unmapped_owed"]) or "none"))
        for x in rep["problems"]:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("capture_verdict = " + rep["capture_verdict"])
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])
    return 0 if not rep["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
