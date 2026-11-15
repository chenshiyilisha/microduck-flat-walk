#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
microduck-android-app 的**统一门禁入口**（stdlib-only）。

为什么要有它：这个模块现在有 core 一键自检（Kotlin/JVM 真跑）+ 四个 Python
`--selftest` 工具，散着跑必然漏跑；项目里 `run_all_gates.py` 存在的理由就是
「50 个测试全绿，但 CI 那条命令没跑」。本 runner 动态发现 `tools/*.py` 里所有
带 `--selftest` 的工具并逐个**真起进程**运行，再统一解析结论。

🔴 防假绿（照抄 run_all_gates.py 的教训，不重复造宽松判据）：
   · 只看 rc 不够：`SELFTEST: 1/5 passed` 但 main 忘了 return 1 也要判红。
   · `RESULT: N errors` / `N passed, M failed` 里 N!=M 或 M!=0 一律红。
   · 无结论行的静默成功判红（「没输出」不等于「跑过了」）。
   · 出现 PRECONDITION_FAIL 判红（最前置前提不成立，别拿后面的绿顶数）。
   · runner 自身不纳入发现集合，否则自指死循环。

verdict 只有三档：ALL_PASS / NOT_PASS / UNVERIFIED（前提缺失）。
**ALL_PASS 只代表离线门禁，不代表真机上板、更不改 ship_verdict。**

用法：
    python tools/check_all_app_gates.py
    python tools/check_all_app_gates.py --json
    python tools/check_all_app_gates.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
SELFTEST_SH = TOOLS / "selftest.sh"
PY = sys.executable
SELF = Path(__file__).name

# 结论行形态（各工具自己打印，runner 只解析不参与生成）
P_RATIO = re.compile(r"(\d+)\s*/\s*(\d+)\s+passed")
P_PASSFAIL = re.compile(r"RESULT:\s*(\d+)\s+passed,\s*(\d+)\s+failed")
P_ERRORS = re.compile(r"RESULT:\s*(\d+)\s+errors")


def discover(tools_dir: Path) -> list[Path]:
    found = []
    for f in sorted(tools_dir.glob("*.py")):
        if f.name == SELF:
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "--selftest" in src:
            found.append(f)
    return found


def classify(out: str, rc: int) -> tuple[bool, str]:
    """返回 (是否真绿, 原因)。刻意比「rc==0」严格。"""
    bad: list[str] = []
    if rc != 0:
        bad.append(f"rc={rc}")
    for m in P_RATIO.finditer(out):
        if int(m.group(1)) != int(m.group(2)):
            bad.append(f"{m.group(1)}/{m.group(2)} passed")
    for m in P_PASSFAIL.finditer(out):
        if int(m.group(2)) != 0:
            bad.append(f"{m.group(2)} failed")
    for m in P_ERRORS.finditer(out):
        if int(m.group(1)) != 0:
            bad.append(f"{m.group(1)} errors")
    if "PRECONDITION_FAIL" in out:
        bad.append("PRECONDITION_FAIL")
    if not re.search(r"passed|errors|RESULT|VERDICT", out):
        bad.append("无结论行(静默成功不算绿)")
    return (not bad), "; ".join(bad) if bad else "ok"


def run_one(script: Path, extra: list[str] | None = None, cwd: Path = BASE) -> dict:
    cmd = [PY, str(script), *(extra or [])]
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        ok, why = classify(out, p.returncode)
        return {"name": script.name, "ok": ok, "why": why, "rc": p.returncode,
                "tail": out.strip().splitlines()[-1] if out.strip() else ""}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"name": script.name, "ok": False, "why": f"EXEC_FAIL {e}",
                "rc": -1, "tail": ""}


def run_core_selftest() -> dict:
    if not SELFTEST_SH.is_file():
        return {"name": "tools/selftest.sh", "ok": False,
                "why": "PRECONDITION_FAIL: selftest.sh 缺失", "rc": -1, "tail": ""}
    try:
        p = subprocess.run(["bash", str(SELFTEST_SH)], cwd=str(BASE),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        out = (p.stdout or "") + (p.stderr or "")
        ok, why = classify(out, p.returncode)
        return {"name": "tools/selftest.sh (core JVM)", "ok": ok, "why": why,
                "rc": p.returncode,
                "tail": next((l for l in reversed(out.splitlines()) if "RESULT:" in l), "")}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"name": "tools/selftest.sh (core JVM)", "ok": False,
                "why": f"EXEC_FAIL {e}", "rc": -1, "tail": ""}


def artifact_isolation() -> dict:
    """不带 --selftest 再跑一次产物核验，单独把「release 是否干净」列成显式一行。"""
    s = TOOLS / "check_apk_debug_isolation.py"
    if not s.is_file():
        return {"name": "apk-debug-isolation", "state": "UNVERIFIED",
                "detail": "检查器缺失"}
    r = run_one(s, ["--json"])
    # --json 模式 rc 非 0 也可能是产物缺失；重跑文本模式读 verdict 更清楚。
    p = subprocess.run([PY, str(s)], cwd=str(BASE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"VERDICT:\s*(\S+)", out)
    v = m.group(1) if m else "UNVERIFIED_PARSE_FAIL"
    state = {"DEBUG_ONLY_ISOLATION_CONFIRMED": "PASS",
             "ISOLATION_BROKEN": "FAIL",
             "UNVERIFIED_ARTIFACTS_ABSENT": "UNVERIFIED"}.get(v, "FAIL")
    return {"name": "apk-debug-isolation", "state": state, "detail": v,
            "json_rc": r["rc"]}


# ---------------------------------------------------------------- 自检负对照

def selftest() -> list[tuple[str, bool]]:
    """用真实的子进程夹具验证 classify/run_one，不是拿字符串自己比自己。"""
    fixtures = {
        "fixture_good.py": "# --selftest\nprint('SELFTEST: 5/5 passed')\n",
        "fixture_degraded_rc0.py": "# --selftest\nprint('SELFTEST: 1/5 passed')\n",
        "fixture_rc1.py": "# --selftest\nimport sys\nprint('SELFTEST: 5/5 passed')\nsys.exit(1)\n",
        "fixture_silent.py": "# --selftest\npass\n",
        "fixture_precond.py": "# --selftest\nprint('PRECONDITION_FAIL: no env')\nprint('SELFTEST: 5/5 passed')\n",
        "fixture_errors.py": "# --selftest\nprint('RESULT: 2 errors')\n",
    }
    out: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="md_app_gates_") as td:
        d = Path(td)
        for name, body in fixtures.items():
            (d / name).write_text(body, encoding="utf-8")
        found = discover(d)
        out.append(("发现逻辑抓到全部夹具且不含 runner 自身",
                    len(found) == len(fixtures) and all(f.name != SELF for f in found)))
        got = {f.name: run_one(f, ["--selftest"], cwd=d) for f in found}
        out.append(("负对照:rc=0 但 1/5 passed 必红", not got["fixture_degraded_rc0.py"]["ok"]))
        out.append(("负对照:rc=1 必红", not got["fixture_rc1.py"]["ok"]))
        out.append(("负对照:无结论行的静默成功必红", not got["fixture_silent.py"]["ok"]))
        out.append(("负对照:PRECONDITION_FAIL 必红", not got["fixture_precond.py"]["ok"]))
        out.append(("负对照:RESULT 2 errors 必红", not got["fixture_errors.py"]["ok"]))
        out.append(("正对照:5/5 passed + rc=0 为真绿", got["fixture_good.py"]["ok"]))
    # classify 直接再验一组纯文本形态，覆盖工具实际打印的两种句式
    out.append(("classify: RESULT 383 passed, 0 failed 为真绿",
                classify("RESULT: 383 passed, 0 failed", 0)[0]))
    out.append(("classify: RESULT 380 passed, 3 failed 为红",
                not classify("RESULT: 380 passed, 3 failed", 0)[0]))
    out.append(("classify: RESULT 0 errors 为真绿",
                classify("RESULT: 0 errors", 0)[0]))
    return out


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="microduck-android-app 统一门禁")
    ap.add_argument("--selftest", action="store_true", help="注入式子进程负对照")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = ap.parse_args()

    scripts = discover(TOOLS)
    if not scripts:
        print("PRECONDITION_FAIL: 没有发现任何 --selftest 工具（发现逻辑坏了？）")
        return 2

    results = [run_one(s, ["--selftest"]) for s in scripts]
    results.append(run_core_selftest())
    artifact = artifact_isolation()

    checks: list[tuple[str, bool]] = []
    if args.selftest:
        checks = selftest()
        results.append({
            "name": "check_all_app_gates.py --selftest (子进程夹具)",
            "ok": all(ok for _, ok in checks), "why": "见下方逐项",
            "rc": 0 if all(ok for _, ok in checks) else 1,
            "tail": f"SELFTEST: {sum(1 for _, ok in checks if ok)}/{len(checks)} passed",
        })

    failed = [r for r in results if not r["ok"]]
    if artifact["state"] == "FAIL":
        failed.append({"name": artifact["name"], "why": artifact["detail"]})
    verdict = "NOT_PASS" if failed else (
        "UNVERIFIED" if artifact["state"] == "UNVERIFIED" else "ALL_PASS")

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "scope": "离线门禁；不验证真机、不改 ship_verdict",
            "tools": results, "artifact": artifact,
            "failed": [{"name": r["name"], "why": r["why"]} for r in failed],
        }, ensure_ascii=False, indent=2))
        return 0 if not failed else 1

    print(f"VERDICT = {verdict}   (离线门禁，非整机签收)")
    for r in results:
        print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['name']:<48} {r['why']}"
              + (f"  | {r['tail'][:70]}" if r.get("tail") else ""))
    print(f"  [{artifact['state']}] {artifact['name']:<48} {artifact['detail']}")
    if args.selftest:
        print("\n=== runner 自检（真实子进程夹具） ===")
        for label, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + label)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
