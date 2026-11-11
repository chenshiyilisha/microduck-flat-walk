#!/usr/bin/env python3
"""Line guard: refuse to sign off the Radxa-mirror robot with B-generation tools.

Why this exists (2026-11-11, four-source comparison)
---------------------------------------------------
The project's tools/hd1910/ tree was built for the bench / training line
(Orange Pi A733, 500 kbps, ID 1-15, DuckBuddy robotd). The shipped robot is a
DIFFERENT protocol line (Radxa Zero 3W, 1 Mbps, official ID 20-34 + IMU200,
kissqy/fanhao one-click image). Using a B-generation auditor to judge the
shipped robot's config produces a plausible-looking green result that is wrong.

This is a guard on the TOOL layer, not a rewrite of any existing tool. No
number inside an existing tool is changed. The refusal semantics are borrowed
from two first-party sources:
  - official docs/policy-manifest.md: model_api/obs_len/robot.model are
    "refused if it disagrees with the robot";
  - ft1910/docs/design/scs-bus.md: scs=true without scs_config (or the
    reverse) is refused by both the editor and the daemon.

Single source of truth: line_labels.json owns every constant. This file owns
no line constants (official microduck_rl AGENTS.md: "one page owns each
mechanism"; mdlab contract.py: a description is not a second source of truth).

Stdlib only: lean CI installs nothing for this script (same choice as
ci_gate_targets.py).

Usage (cwd = microduck-software):
    python tools/hd1910/line_contract.py --check
    python tools/hd1910/line_contract.py --selftest
    python tools/hd1910/line_contract.py --list
    python tools/hd1910/line_contract.py --tool tools/hd1910/audit_robotd_toml.py --line L1_RADXA_MIRROR
    python tools/hd1910/line_contract.py --check --json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
LABELS = HERE / "line_labels.json"


class LineMismatch(RuntimeError):
    """A tool from another hardware line was asked to sign off this robot."""


def load(path: Path = LABELS) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_source(rel: str) -> str:
    p = SOFTWARE / rel
    if not p.is_file():
        return ""
    return io.open(p, encoding="utf-8", errors="replace").read()


def validate(data: dict, with_sources: bool = True) -> list[str]:
    """Structural checks. Returns problem strings; empty means the labels hold.

    Deliberately POSITIVE assertions only: a declared risk token must be found
    in the tool's own source, so a stale label turns red. We never infer a
    line from a bare substring -- docstrings legitimately mention DuckBuddy
    as a negative control (project rule: bare substring matching backfires).
    """
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    lines = data.get("lines") or {}
    if not lines:
        p.append("empty lines: refusing to call an empty contract verified")
    tools = data.get("tools") or []
    if not tools:
        p.append("empty tools: refusing to call an empty contract verified")

    disc = data.get("discriminators") or []
    if not disc:
        p.append("empty discriminators")
    names = list(lines)
    for name in names:
        for d in disc:
            if d not in lines[name]:
                p.append("line %s missing discriminator %s" % (name, d))
    # Any two lines must differ in at least two discriminators. L1 and L3
    # legitimately share 1 Mbps, so we do NOT require every field to differ.
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            diffs = [d for d in disc
                     if d in lines[a] and d in lines[b]
                     and lines[a][d] != lines[b][d]]
            if len(diffs) < 2:
                p.append("lines %s / %s differ in only %d discriminator(s): %s"
                         % (a, b, len(diffs), diffs))

    shared = [x.get("fact", "") for x in (data.get("shared_not_discriminators") or [])]
    if not shared:
        p.append("shared_not_discriminators must not be empty")

    valid_lines = set(names) | set((data.get("non_line_labels") or {}).keys())
    seen: set[str] = set()
    for t in tools:
        rel = t.get("path", "")
        line = t.get("line", "")
        if not rel or not line:
            p.append("tool entry missing path/line: %r" % t)
            continue
        if rel in seen:
            p.append("duplicate tool path: %s" % rel)
        seen.add(rel)
        if line not in valid_lines:
            p.append("unknown line label %s for %s" % (line, rel))
        if not t.get("evidence"):
            p.append("tool %s has no first-party evidence note" % rel)
        src = tool_source(rel) if with_sources else None
        if with_sources and not src:
            p.append("tool source missing: %s" % rel)
        for tok in (t.get("risk_tokens") or []):
            if any(s and s == tok for s in shared):
                p.append("shared non-discriminator used as risk token: %s" % tok)
            if with_sources and tok not in src:
                p.append("stale risk token %r in %s" % (tok, rel))

    pol = data.get("policy") or {}
    if pol.get("current_line") not in lines:
        p.append("policy.current_line is not a declared line")
    for x in (pol.get("refuse_for_signoff") or []):
        if x not in lines:
            p.append("policy.refuse_for_signoff has unknown line: %s" % x)
    return p


def labelled(data: dict, rel: str) -> dict | None:
    for t in data.get("tools") or []:
        if t.get("path") == rel:
            return t
    return None


def assert_for_line(data: dict, rel: str, line: str, enforce: bool = True) -> str:
    """Refuse cross-line use. Returns a verdict string; raises on mismatch.

    enforce=False exists ONLY so --selftest can prove that disabling the
    guard would let a B-generation tool through (negative control).
    """
    t = labelled(data, rel)
    pol = data.get("policy") or {}
    cur = pol.get("current_line")
    refused = set(pol.get("refuse_for_signoff") or [])

    if t is None:
        msg = "UNLABELLED TOOL %s: not registered in line_labels.json; must not sign off %s" % (rel, line)
        if enforce:
            raise LineMismatch(msg)
        return "WOULD_ALLOW:" + msg

    own = t.get("line", "")
    mismatch = (line == cur and own in refused) or (line != own and own not in ("BENCH", "META_GUARD"))
    if mismatch:
        msg = ("LINE MISMATCH: %s is labelled %s, asked to serve %s. "
               "evidence=%s risk_tokens=%s" % (rel, own, line, t.get("evidence", ""), t.get("risk_tokens") or []))
        if enforce:
            raise LineMismatch(msg)
        return "WOULD_ALLOW:" + msg
    if own == "BENCH":
        return "BENCH_OK_NOT_SIGNOFF:%s" % rel
    if own == "META_GUARD":
        return "META_GUARD_OK:%s" % rel
    return "LINE_OK:%s on %s" % (rel, own)


def unlabelled_tools(data: dict, tools_dir: Path) -> list[str]:
    """Coverage gap: tools with a --selftest but no line label."""
    declared = {t.get("path") for t in (data.get("tools") or [])}
    out = []
    for f in sorted(tools_dir.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        src = io.open(f, encoding="utf-8", errors="replace").read()
        if "--selftest" not in src:
            continue
        rel = f.relative_to(SOFTWARE).as_posix()
        if rel not in declared:
            out.append(rel)
    return out


def selftest() -> int:
    data = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data)
    ck("盘上契约结构自校验通过", not base, "; ".join(base[:3]))

    # 1) cross-line refusal, with the guard disabled as negative control
    btool = "tools/hd1910/audit_robotd_toml.py"
    ck("L1 判据常量是 1M", data["lines"]["L1_RADXA_MIRROR"]["baud"] == 1000000)
    ck("L2 判据常量是 500k", data["lines"]["L2_BGEN"]["baud"] == 500000)
    ck("L3 自写分支也是 1M（不与 L1 混同）", data["lines"]["L3_SELFWRITTEN_SCS"]["baud"] == 1000000)
    ck("gain=200 被列为共享非判据", any("gain = 200" in x["fact"] for x in data["shared_not_discriminators"]))
    try:
        assert_for_line(data, btool, "L1_RADXA_MIRROR")
        ck("B代工具查L1必须拒绝", False, "未抛 LineMismatch")
    except LineMismatch:
        ck("B代工具查L1必须拒绝", True)
    soft = assert_for_line(data, btool, "L1_RADXA_MIRROR", enforce=False)
    ck("负对照：关掉拒绝后会放行", soft.startswith("WOULD_ALLOW:"))
    ck("B代工具查L2允许", assert_for_line(data, btool, "L2_BGEN").startswith("LINE_OK"))
    ck("官方读侧查L3允许", assert_for_line(data, "tools/hd1910/verify_official_loader.py", "L3_SELFWRITTEN_SCS").startswith("LINE_OK"))
    try:
        assert_for_line(data, "tools/hd1910/does_not_exist.py", "L1_RADXA_MIRROR")
        ck("未登记工具不得签收", False)
    except LineMismatch:
        ck("未登记工具不得签收", True)

    # 2) label corruption must turn the checks red
    bad = copy.deepcopy(data)
    for t in bad["tools"]:
        if t["path"] == btool:
            t["risk_tokens"] = ["BAUD_RATE = 500_000", "policy.gain = 200"]
    ck("负对照：共享非判据被塞进 risk_tokens 必红",
       any("shared non-discriminator" in x for x in validate(bad)))

    bad = copy.deepcopy(data)
    for t in bad["tools"]:
        if t["path"] == btool:
            t["risk_tokens"] = ["BAUD_RATE = 500_000", "THIS_TOKEN_DOES_NOT_EXIST_9f3a"]
    ck("负对照：伪造 risk_token 必红", any("stale risk token" in x for x in validate(bad)))

    bad = copy.deepcopy(data)
    bad["tools"] = []
    ck("负对照：空工具清单必红", any("empty tools" in x for x in validate(bad, with_sources=False)))

    bad = copy.deepcopy(data)
    bad["lines"]["L2_BGEN"]["baud"] = 1000000
    bad["lines"]["L2_BGEN"]["joint_ids"] = bad["lines"]["L1_RADXA_MIRROR"]["joint_ids"]
    bad["lines"]["L2_BGEN"]["reg6"] = 0
    bad["lines"]["L2_BGEN"]["board"] = bad["lines"]["L1_RADXA_MIRROR"]["board"]
    bad["lines"]["L2_BGEN"]["imu_path"] = bad["lines"]["L1_RADXA_MIRROR"]["imu_path"]
    bad["lines"]["L2_BGEN"]["deploy_chain"] = bad["lines"]["L1_RADXA_MIRROR"]["deploy_chain"]
    ck("负对照：两条线被抹平后必红", any("differ in only" in x for x in validate(bad, with_sources=False)))

    bad = copy.deepcopy(data)
    bad["policy"]["current_line"] = "NOT_A_LINE"
    ck("负对照：current_line 写错必红", any("current_line" in x for x in validate(bad, with_sources=False)))

    # 3) scope: the guard itself is not hardware evidence
    ck("契约声明不作实机签收", any("不作实机签收" in x for x in data.get("known_gaps") or []))

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\nline_guard selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: label/contract validation only; no hardware, no live identify, no R3 closure.")
    return 0


def report(data: dict, problems: list[str]) -> dict:
    return {
        "tool": "line_contract.py",
        "labels_sha256": sha256_of(LABELS),
        "current_line": data["policy"]["current_line"],
        "lines": {k: {"baud": v["baud"], "reg6": v["reg6"], "role": v["role"]}
                  for k, v in data["lines"].items()},
        "labelled_tools": len(data["tools"]),
        "unlabelled_selftest_tools": unlabelled_tools(data, SOFTWARE / "tools"),
        "problems": problems,
        "verdict": "PASS" if not problems else "FAIL",
        "live_hardware_accessed": False,
        "not_proof_of": ["整机可签收", "IMU 上板认板", "500k 位宽 / R3", "人人 HUB 几何"],
        "scope": "工具层线别标签与跨线拒绝；不验证硬件，不作实机签收",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk labels")
    ap.add_argument("--selftest", action="store_true", help="run negative controls, no hardware")
    ap.add_argument("--list", action="store_true", help="list labels and coverage gap")
    ap.add_argument("--tool", default="", help="tool path relative to microduck-software")
    ap.add_argument("--line", default="L1_RADXA_MIRROR", help="line to serve")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    data = load()
    problems = validate(data)
    if args.tool:
        try:
            v = assert_for_line(data, args.tool, args.line)
            print(v)
        except LineMismatch as e:
            print("REFUSED: %s" % e)
            return 1
        if not args.check and not args.list and not args.json:
            return 0

    rep = report(data, problems)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif args.list:
        for k, v in rep["lines"].items():
            print("%-24s baud=%-9s reg6=%-5s %s" % (k, v["baud"], v["reg6"], v["role"]))
        print("labelled=%d  unlabelled --selftest tools=%d"
              % (rep["labelled_tools"], len(rep["unlabelled_selftest_tools"])))
        for rel in rep["unlabelled_selftest_tools"]:
            print("  UNLABELLED " + rel)
    else:
        print("line_labels.json sha256 = " + rep["labels_sha256"])
        print("current_line = " + rep["current_line"])
        print("labelled tools = %d" % rep["labelled_tools"])
        gap = rep["unlabelled_selftest_tools"]
        print("coverage gap (unlabelled --selftest tools) = %d  [REPORT_ONLY]" % len(gap))
        for x in gap:
            print("  - " + x)
        for x in problems:
            print("  [FAIL] " + x)
        print("verdict = " + rep["verdict"])
        print("scope: " + rep["scope"])
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
