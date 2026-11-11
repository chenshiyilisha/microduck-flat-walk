#!/usr/bin/env python3
"""B5 · 部署链线别契约校验器（路① 中控链 / B 代 publish 链 / 官方 daemon 链）。

Stdlib only, read-only, offline. No subprocess in --check/--json; the only
subprocess calls are inside --selftest as CLI negative controls.

Scope: contract structure + cross-line refusal only. It does NOT access
hardware, does NOT prove the R17 V167 console works on our robot, and does
NOT close any INCONCLUSIVE item. ship_verdict stays NOT_SHIPPABLE while the
four SSOT-13 board-acceptance items are still owed.

The line constants are NOT duplicated here: `current_line` and
`refuse_for_signoff` are read from line_labels.json at runtime (single owner),
following microai-lab/microduck-studio AGENTS.md:3-12,38-43.

Usage (cwd = microduck-software, use the project venv):
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_deploy_chain.py --list
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_deploy_chain.py --check
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_deploy_chain.py --check --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_deploy_chain.py --check --ship-gate
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_deploy_chain.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "deploy_chain_contract.json"
DEFAULT_LABELS = HERE / "line_labels.json"
def known_lines(labels: dict) -> set[str]:
    """Valid chain lines come from ONE owner: line_labels.json.

    B4 added the TRAINING non-hardware-line label. A second hardcoded tuple
    here would have drifted the moment the label set changed, so derive it.
    """
    return (set((labels.get("lines") or {}).keys())
            | set((labels.get("non_line_labels") or {}).keys()))


class LineMismatch(RuntimeError):
    """A chain from another line was used for the current line's sign-off."""


def load_json(path: Path) -> dict:
    return json.loads(io.open(str(path), encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_policy(labels: dict) -> tuple[str, set[str]]:
    pol = labels.get("policy") or {}
    return pol.get("current_line", ""), set(pol.get("refuse_for_signoff") or [])


def validate(data: dict, labels: dict) -> list[str]:
    p: list[str] = []
    cur, refused = line_policy(labels)
    if not cur:
        p.append("line_labels.json#policy.current_line is empty")
    if not refused:
        p.append("line_labels.json#policy.refuse_for_signoff is empty")

    au = data.get("authority") or {}
    if au.get("single_source_of_line") != "line_labels.json#policy.current_line":
        p.append("authority.single_source_of_line must point at line_labels.json")
    if not au.get("source") or not au.get("statement"):
        p.append("authority is missing source/statement")
    if not data.get("rule"):
        p.append("missing rule")

    chains = data.get("chains") or []
    ambiguous = data.get("ambiguous_tokens") or []
    superseded = data.get("superseded_statements") or []
    borrowed = data.get("borrowed_invariants") or []
    req = data.get("required") or {}

    # 集合相等断言（借 open-microduck check_book.py / B1 board_acceptance.py）
    for key, items, field in (
        ("chain_ids", chains, "id"),
        ("ambiguous_tokens", ambiguous, "token"),
        ("superseded_ids", superseded, "id"),
        ("borrowed_ids", borrowed, "id"),
    ):
        want = set(req.get(key) or [])
        got = {x.get(field, "") for x in items}
        if not want:
            p.append("required.%s is empty" % key)
        elif want != got:
            p.append("required.%s != actual: missing=%s extra=%s"
                     % (key, sorted(want - got), sorted(got - want)))

    signoff = [c for c in chains if c.get("status") == "CURRENT_SIGNOFF"]
    if len(signoff) != 1:
        p.append("exactly one CURRENT_SIGNOFF chain required, found %d" % len(signoff))
    else:
        s = signoff[0]
        if s.get("line") != cur:
            p.append("signoff chain line %s != line_labels current_line %s"
                     % (s.get("line"), cur))
        if s.get("ship_ready") is not False:
            p.append("signoff chain must stay ship_ready=false (SSOT-13 still owed)")
        if not s.get("still_owed"):
            p.append("signoff chain must list still_owed items")
        if s.get("board_acceptance_required") is not True:
            p.append("signoff chain requires board_acceptance_required=true")
        if not s.get("forbidden_commands_for_this_chain"):
            p.append("signoff chain must list forbidden cross-line commands")
        if not s.get("entry_points") or not s.get("model_management"):
            p.append("signoff chain must state entry_points and model_management")

    allow = known_lines(labels)
    for c in chains:
        if not c.get("evidence"):
            p.append("chain %s has no evidence" % c.get("id"))
        if c.get("line") not in allow:
            p.append("chain %s has an unknown line %r" % (c.get("id"), c.get("line")))
        if c.get("status") != "CURRENT_SIGNOFF" and c.get("line") in refused:
            if not c.get("refusal_reason"):
                p.append("refused-line chain %s has no refusal_reason" % c.get("id"))

    for a in ambiguous:
        senses = a.get("senses") or []
        if len(senses) < 2:
            p.append("ambiguous token %s has < 2 senses (not ambiguous)" % a.get("token"))
        for s in senses:
            if not s.get("chain") or not s.get("meaning"):
                p.append("ambiguous token %s has an incomplete sense" % a.get("token"))
        if not a.get("rule"):
            p.append("ambiguous token %s has no disambiguation rule" % a.get("token"))

    for x in data.get("port_conflicts") or []:
        if len(x.get("claimants") or []) < 2:
            p.append("port conflict %s has < 2 claimants" % x.get("port"))
        if not x.get("handling"):
            p.append("port conflict %s has no handling" % x.get("port"))

    for s in superseded:
        for k in ("source", "claim", "verdict", "superseded_by", "why_it_matters", "evidence"):
            if not s.get(k):
                p.append("superseded %s missing %s" % (s.get("id"), k))

    for b in borrowed:
        for k in ("source", "quote", "adopted_as", "name"):
            if not b.get(k):
                p.append("borrowed %s missing %s" % (b.get("id"), k))

    for e in data.get("external_references") or []:
        for k in ("source", "findings", "evidence_kind", "not_proof_of"):
            if not e.get(k):
                p.append("external reference %s missing %s" % (e.get("id"), k))

    sc = data.get("scope") or {}
    if sc.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be false")
    if not sc.get("not_proof_of") or not sc.get("known_gaps"):
        p.append("scope must declare not_proof_of and known_gaps")
    return p


def ship_verdict(data: dict) -> str:
    signoff = [c for c in (data.get("chains") or [])
               if c.get("status") == "CURRENT_SIGNOFF"]
    if len(signoff) != 1:
        return "NOT_SHIPPABLE"
    s = signoff[0]
    if s.get("ship_ready") is not False or s.get("still_owed"):
        return "NOT_SHIPPABLE"
    return "SHIPPABLE"


def assert_for_line(data: dict, labels: dict, chain_id: str, line: str,
                    enforce: bool = True) -> str:
    """Refuse a refused-line chain when it is used to sign off the current line."""
    cur, refused = line_policy(labels)
    c = next((x for x in (data.get("chains") or []) if x.get("id") == chain_id), None)
    if c is None:
        raise LineMismatch("unknown chain id: %s" % chain_id)
    if line == cur and c.get("line") in refused:
        msg = ("CROSS-LINE REFUSED: chain %s belongs to %s, cannot sign off %s"
               % (chain_id, c.get("line"), cur))
        if enforce:
            raise LineMismatch(msg)
        return "WOULD_ALLOW:" + msg
    return "OK: %s (%s) usable in context %s" % (chain_id, c.get("line"), line)


def selftest(data: dict, labels: dict) -> int:
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck("负对照：" + name, bool(validate(bad, labels)))

    ck("基线结构校验通过", not validate(data, labels),
       "" if not validate(data, labels) else "; ".join(validate(data, labels))[:200])
    ck("line_labels 单一主人：current_line = L1_RADXA_MIRROR",
       line_policy(labels)[0] == "L1_RADXA_MIRROR")
    ck("CURRENT_SIGNOFF 恰一条且属当前线",
       len([c for c in data["chains"] if c["status"] == "CURRENT_SIGNOFF"]) == 1)
    ck("整体如实 NOT_SHIPPABLE", ship_verdict(data) == "NOT_SHIPPABLE")
    ck("三条链 id 集合与 required 相等",
       {c["id"] for c in data["chains"]} == set(data["required"]["chain_ids"]))
    ck("五个歧义 token 各 ≥2 个 sense",
       all(len(a["senses"]) >= 2 for a in data["ambiguous_tokens"]))
    ck("8090 端口冲突有两个 claimant",
       any(len(x["claimants"]) >= 2 for x in data["port_conflicts"]))
    ck("9 条 borrowed 全带 adopted_as",
       all(b.get("adopted_as") for b in data["borrowed_invariants"]))
    ck("4 条 SUPERSEDED 全带 superseded_by 与 evidence",
       all(s.get("superseded_by") and s.get("evidence")
           for s in data["superseded_statements"]))
    ck("scope 明标 live_hardware_accessed=false",
       data["scope"]["live_hardware_accessed"] is False)

    # 跨线拒绝正对照 + 关掉 enforce 的负对照
    try:
        assert_for_line(data, labels, "L2_PUBLISH_ROBOTCTL", "L1_RADXA_MIRROR")
        ck("正对照：B 代 publish 链查路① 签收被拒", False, "no exception raised")
    except LineMismatch:
        ck("正对照：B 代 publish 链查路① 签收被拒", True)
    allowed = assert_for_line(data, labels, "L2_PUBLISH_ROBOTCTL",
                              "L1_RADXA_MIRROR", enforce=False)
    ck("负对照：关掉 enforce 会放行（证明门禁不是空操作）",
       allowed.startswith("WOULD_ALLOW:"))
    ck("同线自检可放行",
       assert_for_line(data, labels, "L2_PUBLISH_ROBOTCTL", "L2_BGEN").startswith("OK:"))
    ck("官方 daemon 链查路① 签收被拒",
       _refused(data, labels, "L3_OFFICIAL_DAEMON", "L1_RADXA_MIRROR"))
    ck("路① 中控链查路① 签收可放行",
       assert_for_line(data, labels, "L1_CONSOLE_R17_V167",
                       "L1_RADXA_MIRROR").startswith("OK:"))

    # 结构腐化负对照
    must_fail("删一条 chain 必红", lambda d: d["chains"].pop())
    must_fail("把 B 代链标成 CURRENT_SIGNOFF 必红",
              lambda d: _set_status(d, "L2_PUBLISH_ROBOTCTL", "CURRENT_SIGNOFF"))
    must_fail("把路① 链的 line 改成 L2_BGEN 必红",
              lambda d: _set_line(d, "L1_CONSOLE_R17_V167", "L2_BGEN"))
    must_fail("把路① 标成 ship_ready 必红",
              lambda d: _set(d, "L1_CONSOLE_R17_V167", "ship_ready", True))
    must_fail("删掉一条 borrowed 的 source 必红",
              lambda d: d["borrowed_invariants"][0].pop("source"))
    must_fail("删掉一条 SUPERSEDED 的 superseded_by 必红",
              lambda d: d["superseded_statements"][0].pop("superseded_by"))
    must_fail("歧义 token 只剩一个 sense 必红",
              lambda d: d["ambiguous_tokens"][0].__setitem__(
                  "senses", d["ambiguous_tokens"][0]["senses"][:1]))
    must_fail("端口冲突只剩一个 claimant 必红",
              lambda d: d["port_conflicts"][0].__setitem__(
                  "claimants", d["port_conflicts"][0]["claimants"][:1]))
    must_fail("required.chain_ids 与实体不符必红",
              lambda d: d["required"]["chain_ids"].append("GHOST_CHAIN"))
    must_fail("scope.live_hardware_accessed 被改成 true 必红",
              lambda d: d["scope"].__setitem__("live_hardware_accessed", True))
    must_fail("authority 指向别处（第二份真相）必红",
              lambda d: d["authority"].__setitem__(
                  "single_source_of_line", "deploy_chain_contract.json#policy"))

    bad_labels = copy.deepcopy(labels)
    bad_labels["policy"]["current_line"] = "L2_BGEN"
    ck("负对照：line_labels 的 current_line 被改坏必红",
       bool(validate(data, bad_labels)))
    ck("B4：合法线集合从 line_labels 派生（含 TRAINING）",
       "TRAINING" in known_lines(labels) and "L1_RADXA_MIRROR" in known_lines(labels))
    drop = copy.deepcopy(labels)
    drop["lines"].pop("L2_BGEN", None)
    ck("负对照：从标签里删掉 L2_BGEN，引用它的链必红（不再有第二份硬编码清单）",
       any("unknown line" in x for x in validate(data, drop)))

    # CLI 真跑（项目里踩过「只测内部函数不测 CLI」的坑）
    script = str(Path(__file__).resolve())
    ok = subprocess.run([sys.executable, script, "--check", "--json"],
                        capture_output=True, text=True)
    ck("CLI 真跑：--check --json rc=0 且为纯 JSON",
       ok.returncode == 0 and ok.stdout.strip().startswith("{"),
       "rc=%s" % ok.returncode)
    try:
        rep = json.loads(ok.stdout)
        ck("CLI JSON 报告含 structure_verdict / ship_verdict",
           rep.get("structure_verdict") == "PASS"
           and rep.get("ship_verdict") == "NOT_SHIPPABLE")
    except (ValueError, AttributeError):
        ck("CLI JSON 报告含 structure_verdict / ship_verdict", False)

    ship = subprocess.run([sys.executable, script, "--check", "--ship-gate"],
                          capture_output=True, text=True)
    ck("CLI 真跑：--check --ship-gate 必 rc=1",
       ship.returncode == 1, "rc=%s" % ship.returncode)

    tmp = Path(tempfile.gettempdir()) / ("md_bad_chain_%d.json" % os.getpid())
    bad = copy.deepcopy(data)
    _set_status(bad, "L2_PUBLISH_ROBOTCTL", "CURRENT_SIGNOFF")
    try:
        tmp.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, script, "--contract", str(tmp), "--check"],
                           capture_output=True, text=True)
        ck("CLI 真跑：坏契约 --check 必 rc=1", r.returncode == 1,
           "rc=%s" % r.returncode)
    finally:
        tmp.unlink(missing_ok=True)

    bad_n = [n for n, ok, _ in checks if not ok]
    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name,
                               ("  <- " + note) if note else ""))
    print("\ncheck_deploy_chain selftest: %d/%d passed"
          % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: contract structure + cross-line refusal only; no hardware, no live identify.")
    print("self-test: PASS")
    return 0


def _refused(data: dict, labels: dict, chain_id: str, line: str) -> bool:
    try:
        assert_for_line(data, labels, chain_id, line)
        return False
    except LineMismatch:
        return True


def _set_status(d: dict, cid: str, status: str) -> None:
    for c in d["chains"]:
        if c["id"] == cid:
            c["status"] = status


def _set_line(d: dict, cid: str, line: str) -> None:
    for c in d["chains"]:
        if c["id"] == cid:
            c["line"] = line


def _set(d: dict, cid: str, key: str, value) -> None:
    for c in d["chains"]:
        if c["id"] == cid:
            c[key] = value


def build_report(data: dict, labels: dict, contract_path: Path,
                 labels_path: Path) -> dict:
    problems = validate(data, labels)
    cur, refused = line_policy(labels)
    return {
        "tool": "check_deploy_chain.py",
        "contract": str(contract_path.name),
        "contract_sha256": sha256_of(contract_path),
        "line_labels_sha256": sha256_of(labels_path),
        "current_line": cur,
        "refuse_for_signoff": sorted(refused),
        "chain_status": {c.get("id"): c.get("status") for c in data.get("chains") or []},
        "ambiguous_tokens": [a.get("token") for a in data.get("ambiguous_tokens") or []],
        "superseded": [s.get("id") for s in data.get("superseded_statements") or []],
        "borrowed_invariants": [b.get("id") for b in data.get("borrowed_invariants") or []],
        "external_references": [e.get("id") for e in data.get("external_references") or []],
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": ship_verdict(data),
        "live_hardware_accessed": False,
        "scope": data.get("scope") or {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ship-gate", action="store_true")
    args = ap.parse_args()

    data = load_json(args.contract)
    labels = load_json(args.labels)

    if args.selftest:
        return selftest(data, labels)

    if args.list:
        cur, refused = line_policy(labels)
        print("current_line = %s   refused = %s" % (cur, sorted(refused)))
        for c in data.get("chains") or []:
            print("  %-24s %-18s %-24s %s" % (c.get("id"), c.get("line"),
                                              c.get("status"), c.get("name")))
        print("ambiguous tokens = %s" % ", ".join(
            a.get("token", "") for a in data.get("ambiguous_tokens") or []))
        print("verdict = PASS" if not validate(data, labels) else "verdict = FAIL")
        return 0

    rep = build_report(data, labels, args.contract, args.labels)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("deploy_chain_contract.json sha256 = " + rep["contract_sha256"])
        print("line_labels.json sha256 = " + rep["line_labels_sha256"])
        print("current_line = " + rep["current_line"])
        for cid, status in rep["chain_status"].items():
            print("  %-24s %s" % (cid, status))
        print("ambiguous_tokens = " + ", ".join(rep["ambiguous_tokens"]))
        print("superseded = " + ", ".join(rep["superseded"]))
        print("borrowed_invariants = " + ", ".join(rep["borrowed_invariants"]))
        for x in rep["problems"]:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship_verdict = " + rep["ship_verdict"] + "  (UNVERIFIED != PASS)")
        print("live_hardware_accessed = false")
        print("verdict = " + rep["structure_verdict"])

    if rep["structure_verdict"] != "PASS":
        return 1
    if args.ship_gate and rep["ship_verdict"] != "SHIPPABLE":
        if not args.json:
            print("SHIP GATE REFUSED: signoff chain still owes board acceptance")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
