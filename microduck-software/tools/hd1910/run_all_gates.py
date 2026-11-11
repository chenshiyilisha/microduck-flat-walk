#!/usr/bin/env python3
"""One command that REALLY runs every guard, and never calls a SKIP a pass.

Why this exists (2026-11-11)
---------------------------
The repo has dozens of tools with a --selftest (discovered dynamically by
discover(); do NOT hardcode a count here -- it has drifted 33 -> 47+ already),
but pre_deploy_check.py --selftest conducts only five deployment guards. A
guard's own unit tests can be all green while its CLI dies at argparse -- the
exact "50 tests green, --selftest rc=2" incident recorded in
tests/test_hd1910_tooling.py:714. So this entry point:

  1. runs the two new meta guards (line guard + closure contract) with their
     negative controls, as real CLI processes;
  2. discovers EVERY tools/**/*.py carrying --selftest and runs each one as a
     real CLI process, asserting rc;
  3. reports the coverage gap against pre_deploy_check.py's five guards and
     the unlabelled tools from line_labels.json;
  4. refuses to print a plain PASS when anything is SKIP / PARTIAL /
     UNVERIFIED / TIMEOUT / rc!=0.

Semantics are borrowed, not reinvented:
  - pre_deploy_check.py: rc==2 with argparse usage is FAIL, a SKIP is only
    acceptable with an explicit allow-list and then prints PARTIAL;
  - official microduck_rl AGENTS.md / luwu commit messages: shape + smoke
    gate, and record the actual test counts in the verdict;
  - mdlab CI: list known gaps explicitly instead of pretending full coverage;
  - hd1910m audit_native_observation_contract.py: report carries
    live_hardware_accessed=false and a note saying what it does NOT prove;
  - open-microduck check_book.py: one authoritative list, output hashes.

Stdlib only. Scope: offline gates only; no hardware, no live identify, and
it does NOT close INCONCLUSIVE_RATE_MISMATCH.

Interpreter matters (found in the pre-commit review, 2026-11-11)
---------------------------------------------------------------
PY below is sys.executable, so every child guard inherits the interpreter
that launched THIS script. Several guards import onnx / onnxruntime / torch
at CLI time. Under a bare system python those guards FAIL (rc=1); with the
repo's .venv-mjlab they pass. Do NOT hardcode a pass count here -- the tool
set grows over time and a stale number is itself a documentation bug. Both
outcomes are honest, but a red run under the wrong interpreter is NOT
evidence that a guard is broken. The report therefore records the
interpreter and its dependency probe as an explicit fact, and prints a HINT
naming the project venv when deps are missing. A missing dep is still rc=1
FAIL -- never a SKIP, never a pass.

Usage (cwd = microduck-software):
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --list
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --selftest
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --check
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --check --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --check --ship-gate
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
TOOLS = SOFTWARE / "tools"
PY = sys.executable
CONDUCTOR_GUARDS = ("contract.selftest", "bundle.selftest", "numeric.selftest",
                    "inference.selftest", "toml.selftest")
USAGE = re.compile(r"(usage:|error: unrecognized arguments|argparse)", re.I)
# Do NOT scan the whole output for status words. A guard's negative controls
# legitimately print "SKIP" / "NOT_SHIPPABLE" in their own test names; the
# project rule is that a bare substring match gets bitten by the surrounding
# text. Only an explicit CONCLUSION line counts.
VERDICT_LINE = re.compile(
    r"^\s*(?:self-test|selftest|verdict|status)\s*[:=]\s*"
    r"(PASS|FAIL|SKIP|PARTIAL|UNVERIFIED|NOT_SHIPPABLE)\b", re.I)
BARE_CONCLUSION = re.compile(r"^\s*(SKIP|PARTIAL|UNVERIFIED|NOT_SHIPPABLE|FAIL)\b")

# A3 self-audit (2026-11-11): the marker above only recognises a fixed status
# word. 47 real tools were run and 33/47 emit NO recognised marker -- their
# conclusion is a bare ratio (`selftest: 30/30 passed`, `全部通过`,
# `selftest: ALL PASS`, `15 checks, all consistent` ...). So `classify()` has
# been leaning entirely on rc: a tool whose selftest degrades to
# `selftest: 1/5 passed` while its main() forgets `return 1` would still be
# called PASS. This guard closes that blind spot independently of each tool's
# own discipline.
#
# Scope is DELIBERATELY narrow to dodge rule-10 (bare-substring backfire). A
# first broad `(\d+)/(\d+)` matcher false-positived on 6/47 real tools:
# `50/200 is 0.25x` (a ratio), `0.8 / 1.0` (source values), `26/28 passed (2
# FAIL)` (an intentional negative-control fixture), `3/15 -> refuse` (a
# rejection-path test), `100/107/100 deg/s` (angular rates), `10/20 -> FLAKY`.
# The narrowed form only matches a CONCLUSION line (status prefix or bare ratio
# followed by an explicit pass word) and skips any line carrying an antonym
# context. Verified: 0/47 false positives, all `N!=M` conclusions caught.
VERDICT_RATIO = re.compile(
    r"^\s*(?:self-?test|selftest|verdict|status|全部|共)?\s*[:：]?\s*"
    r"(\d+)\s*/\s*(\d+)\s*(?:checks?\s*)?"
    r"(?:passed|pass|ok|green|通过|自检通过)\b", re.I)
# Antonym / non-verdict context: a whole line matching this is skipped, so a
# negative-control fixture or a ratio computation is never mistaken for the
# guard's real pass/fail tally.
RATIO_ANTONYM = re.compile(
    r"FAIL|拒绝|FLAKY|负对照|期望|must|refus|is\s*\d|应答|折", re.I)


def verdict_ratio_mismatch(output: str) -> tuple[int, int, str] | None:
    """Return (passed, total, line) if a conclusion line reports N/M with N!=M.

    Independent of rc and of the fixed-word marker: even a tool that exits 0
    and prints no `self-test: PASS` cannot hide a degraded `1/5 passed`.
    Lines with antonym context (negative controls, ratios, rejection-path
    tests) are skipped on purpose -- rely on the tool's own rc for those.
    """
    for line in output.splitlines():
        if RATIO_ANTONYM.search(line):
            continue
        m = VERDICT_RATIO.match(line)
        if m:
            got, total = int(m.group(1)), int(m.group(2))
            if total > 0 and got != total:
                return got, total, line.strip()
    return None


def conclusion_marker(output: str) -> str:
    """Extract the guard's own verdict word, never a word from a test name."""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    if not lines:
        return ""
    for line in reversed(lines[-6:]):
        m = VERDICT_LINE.match(line)
        if m:
            return m.group(1).upper()
    m = BARE_CONCLUSION.match(lines[-1])
    return m.group(1).upper() if m else ""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


HEAVY_MODULES = ("onnx", "onnxruntime")


def _probe_heavy_deps() -> dict:
    """Detect (without importing) deps that several guards need at CLI time."""
    import importlib.util
    out = {}
    for mod in HEAVY_MODULES:
        try:
            out[mod] = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError, AttributeError):
            out[mod] = False
    return out


def heavy_deps_ok(flags: dict) -> bool:
    """Single injectable predicate, so the negative control can prove it."""
    return all(bool(flags.get(m)) for m in HEAVY_MODULES)


def interpreter_info(flags: dict | None = None) -> dict:
    """Make the interpreter an EXPLICIT, reported fact (mdlab known-gap rule).

    Child guards inherit sys.executable. A missing heavy dep surfaces as
    rc=1 FAIL -- never as a SKIP and never as a pass -- but it is also NOT
    proof that those guards are broken. Recording which interpreter produced
    the verdict keeps a wrong-interpreter red run from being misread.
    """
    probed = _probe_heavy_deps() if flags is None else dict(flags)
    venvs = (SOFTWARE / ".venv-mjlab" / "Scripts" / "python.exe",
             SOFTWARE / ".venv-mjlab" / "bin" / "python")
    recommended = next((str(p) for p in venvs if p.is_file()), "")
    return {
        "executable": sys.executable,
        "heavy_deps": {m: bool(probed.get(m)) for m in HEAVY_MODULES},
        "heavy_deps_ok": heavy_deps_ok(probed),
        "project_venv": recommended,
        "child_guards_inherit": "sys.executable",
        "note": ("missing heavy deps surface as rc=1 FAIL, never a SKIP and never "
                 "a pass; a red run under the wrong interpreter is NOT evidence "
                 "that the guards are broken"),
    }


def discover(tools_dir: Path) -> list[Path]:
    out = []
    for f in sorted(tools_dir.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        src = io.open(f, encoding="utf-8", errors="replace").read()
        if "--selftest" in src:
            out.append(f)
    return out


def classify(rc: int, output: str, timed_out: bool = False, strict: bool = True) -> tuple[str, str]:
    """Return (status, detail). strict=False exists only for a negative control."""
    if timed_out:
        return "FAIL", "TIMEOUT: guard did not finish"
    if rc == 2 and strict:
        if USAGE.search(output):
            return "FAIL", "GUARD INVOCATION BROKEN (argparse usage error, not a SKIP)"
        return "FAIL", "rc=2 is a failure, never a SKIP"
    if rc == 2 and not strict:
        return "SKIP", "negative control only: guard disabled would call rc=2 a SKIP"
    if rc != 0:
        return "FAIL", "rc=%d" % rc
    marker = conclusion_marker(output)
    if marker == "FAIL":
        return "FAIL", "conclusion line says FAIL while rc=0"
    if marker and marker != "PASS":
        return "SUSPECT_SKIP", "conclusion line says %s while rc=0: not evidence of a pass" % marker
    # A3 self-audit fail-safe: independently of the tool's own rc discipline,
    # a conclusion line reporting N/M with N!=M is a degraded selftest even
    # when rc=0 and no fixed status word is present. This is the third layer:
    # (1) rc!=0, (2) explicit FAIL/PARTIAL marker, (3) this ratio guard.
    ratio = verdict_ratio_mismatch(output)
    if ratio:
        got, total, line = ratio
        return "SUSPECT_SKIP", ("conclusion ratio %d/%d while rc=0: degraded "
                                "selftest, not evidence of a pass (%s)" % (got, total, line[:60]))
    return "PASS", "rc=0, conclusion line has no skip marker"


def run_one(script: Path, cwd: Path, timeout: int) -> dict:
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run([PY, str(script), "--selftest"], cwd=str(cwd),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
        rc, out = proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc, out = 124, ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes)
                        else (e.stdout or ""))
    status, detail = classify(rc, out, timed_out)
    return {
        "tool": script.name,
        "path": str(script),
        "rc": rc,
        "status": status,
        "detail": detail,
        "seconds": round(time.time() - started, 2),
        "tail": out.strip().splitlines()[-1][:160] if out.strip() else "",
    }


def run_meta(timeout: int) -> list[dict]:
    out = []
    for name in ("line_contract.py", "check_closure.py"):
        script = HERE / name
        started = time.time()
        try:
            proc = subprocess.run([PY, str(script), "--selftest"], cwd=str(SOFTWARE),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
            rc, text = proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            rc, text = 124, "TIMEOUT"
        out.append({"stage": name + " --selftest", "rc": rc,
                    "status": "PASS" if rc == 0 else "FAIL",
                    "seconds": round(time.time() - started, 2),
                    "tail": text.strip().splitlines()[-1][:160] if text.strip() else ""})
    return out


def fake_tools(root: Path) -> None:
    """Injected CLI fixtures for --selftest: each one is a REAL process."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "green.py").write_text(
        "# --selftest\nprint('selftest: 3/3 passed')\n", encoding="utf-8")
    (root / "argparse_broken.py").write_text(
        "# --selftest\nimport sys\nprint('usage: x.py [-h]', file=sys.stderr)\n"
        "print('error: unrecognized arguments', file=sys.stderr)\nsys.exit(2)\n", encoding="utf-8")
    (root / "silent_skip.py").write_text(
        "# --selftest\nprint('SKIP: dependency absent')\n", encoding="utf-8")
    (root / "failing.py").write_text(
        "# --selftest\nimport sys\nprint('selftest: 1 check FAILED')\nsys.exit(1)\n", encoding="utf-8")
    (root / "mentions_skip.py").write_text(
        "# --selftest\nprint('negative control mentions SKIP and NOT_SHIPPABLE in its name')\n"
        "print('self-test: PASS -- negative-control logic wired correctly')\n", encoding="utf-8")
    # A3 self-audit: a tool that reports a DEGRADED ratio (1/5) yet exits 0.
    # Its main() forgot `return 1`; only the A3 ratio guard can catch it.
    (root / "ratio_degenerate.py").write_text(
        "# --selftest\nprint('selftest: 1/5 passed')\n", encoding="utf-8")
    # Positive control: same shape, all checks pass (N==M) -- must stay PASS.
    (root / "ratio_allgreen.py").write_text(
        "# --selftest\nprint('selftest: 5/5 passed')\n", encoding="utf-8")


def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    with tempfile.TemporaryDirectory(prefix="md_gates_") as td:
        root = Path(td)
        fake_tools(root)
        found = discover(root)
        ck("假工具目录被发现 7 个", len(found) == 7, "found=%d" % len(found))
        results = {r["tool"]: r for r in (run_one(f, root, 20) for f in found)}
        ck("green rc=0 判 PASS", results["green.py"]["status"] == "PASS")
        ck("A3 自查：1/5 退化但 rc=0 必判 SUSPECT_SKIP",
           results["ratio_degenerate.py"]["status"] == "SUSPECT_SKIP",
           results["ratio_degenerate.py"]["detail"])
        ck("A3 正对照：5/5 全绿保持 PASS",
           results["ratio_allgreen.py"]["status"] == "PASS",
           results["ratio_allgreen.py"]["detail"])
        ck("rc=2 argparse 判 FAIL（不是 SKIP）",
           results["argparse_broken.py"]["status"] == "FAIL"
           and "GUARD INVOCATION BROKEN" in results["argparse_broken.py"]["detail"])
        ck("结论行 SKIP 判 SUSPECT_SKIP",
           results["silent_skip.py"]["status"] == "SUSPECT_SKIP")
        ck("rc=1 判 FAIL", results["failing.py"]["status"] == "FAIL")
        ck("负对照：正文提到 SKIP/NOT_SHIPPABLE 不得误判",
           results["mentions_skip.py"]["status"] == "PASS",
           results["mentions_skip.py"]["detail"])
        ck("假工具真的作为 CLI 进程跑过", all(r["rc"] in (0, 1, 2) for r in results.values()))

    # negative controls on the classifier itself
    strict, _ = classify(2, "usage: x.py [-h]\nerror: unrecognized arguments")
    loose, _ = classify(2, "usage: x.py [-h]\nerror: unrecognized arguments", strict=False)
    ck("负对照：关掉严格模式会把 rc=2 放成 SKIP", strict == "FAIL" and loose == "SKIP")
    ck("结论行 NOT_SHIPPABLE 不算 PASS",
       classify(0, "NOT_SHIPPABLE")[0] == "SUSPECT_SKIP")
    ck("负对照：正文提到状态词、结论行 PASS 不得误判",
       classify(0, "negative control mentions NOT_SHIPPABLE and SKIP\nself-test: PASS -- ok")[0] == "PASS")
    ck("结论行 PARTIAL 不算 PASS",
       classify(0, "self-test: PARTIAL -- 1 guard skipped")[0] == "SUSPECT_SKIP")
    # A3 self-audit: the ratio guard must bite on degraded conclusions ...
    for degraded in ("selftest: 1/5 passed", "selftest: 0/9 passed",
                     "verdict: 14/15 passed", "全部 8/10 通过",
                     "selftest: 26/28 checks passed"):
        ck("A3 负对照：退化结论 %s 必红" % degraded,
           classify(0, degraded)[0] == "SUSPECT_SKIP")
    # ... and must NOT bite on N==M, on antonym context (negative-control
    # fixtures / ratio computations), or on the 33 rc-only markers in the wild.
    for clean in ("selftest: 31/31 passed", "39/39 passed", "selftest: ALL PASS",
                  "15 checks, all consistent", "selftest: 30/30 passed"):
        ck("A3 正对照：%s 不误红" % clean, classify(0, clean)[0] == "PASS")
    for antonym in ("26/28 checks passed (2 FAIL)", "只读到 3/15 → 拒绝写入",
                    "N2b 10/20 应答 -> FLAKY", "50/200 is 0.25x", "0.8 / 1.0 对照"):
        ck("A3 反义上下文不误红：%s" % antonym,
           verdict_ratio_mismatch(antonym) is None)
    ck("A3 端到端：注入退化工具使全量报告 FAILED",
       build_report([], [{"status": "SUSPECT_SKIP"}], [], False)["verdict"] == "FAILED")
    ck("负对照：空发现清单不得报全绿",
       discover(Path(tempfile.gettempdir()) / "_md_no_such_dir_9f3a") == [])

    info = interpreter_info()
    ck("解释器事实被显式记录",
       info["executable"] == sys.executable
       and set(info["heavy_deps"]) == set(HEAVY_MODULES)
       and isinstance(info["heavy_deps_ok"], bool)
       and info["child_guards_inherit"] == "sys.executable")
    ck("负对照：缺任一重依赖时 heavy_deps_ok 必为 False",
       not heavy_deps_ok({"onnx": False, "onnxruntime": True})
       and not heavy_deps_ok({"onnx": True, "onnxruntime": False})
       and not heavy_deps_ok({}))
    ck("报告携带 interpreter 段且 executable 与真实一致",
       build_report([], [], [], False, info)["interpreter"]["executable"] == sys.executable)
    ck("负对照：零发现清单不得被算成 ALL_PASS",
       build_report([], [], [], False, info)["verdict"] == "FAILED")

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad = [n for n, ok, _ in checks if not ok]
    print("\nrun_all_gates selftest: %d/%d passed" % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("scope: gate plumbing only; no hardware, no live identify, no R3 closure.")
    return 0


def build_report(meta: list[dict], tools: list[dict], unlabelled: list[str],
                 ship_gate: bool, interp: dict | None = None) -> dict:
    statuses = [m["status"] for m in meta] + [t["status"] for t in tools]
    n_pass = statuses.count("PASS")
    n_bad = len(statuses) - n_pass
    # An empty discovery is NOT a green run. Otherwise a wiped tools dir (or
    # an injected empty one) would report ALL_PASS with zero evidence.
    verdict = "ALL_PASS" if statuses and n_bad == 0 else "FAILED"
    ship = "NOT_SHIPPABLE"
    if ship_gate and verdict == "ALL_PASS":
        ship = "SHIPPABLE_OFFLINE_ONLY"
    return {
        "tool": "run_all_gates.py",
        "interpreter": interp if interp is not None else interpreter_info(),
        "meta_stages": meta,
        "tool_stages": tools,
        "counts": {"total": len(statuses), "pass": n_pass, "not_pass": n_bad,
                   "conductor_guards": len(CONDUCTOR_GUARDS),
                   "unlabelled_tools": len(unlabelled)},
        "coverage_gap": {
            "note": "pre_deploy_check.py --selftest conducts only 5 guards; this run covers all --selftest tools",
            "conductor_guards": list(CONDUCTOR_GUARDS),
            "unlabelled": unlabelled,
        },
        "verdict": verdict,
        "ship_verdict": ship,
        "live_hardware_accessed": False,
        "not_proof_of": ["整机可签收", "策略上真机", "IMU live 认板", "500k 位宽 / R3",
                         "人人 HUB 几何与载流", "左右腿文字定义"],
        "known_gaps": [
            "robotd --sim 验不了总线驱动/BLE/ISP+rkaiq 3A/NPU/编码器+RGA",
            "UNLABELLED 工具只报告不判红（line_labels.json policy.unlabelled=REPORT_ONLY）",
            "SUSPECT_SKIP 需人工看该工具输出，不自动升级为 PASS",
            "离线门禁全绿不等于上板验收（四源共识：UNVERIFIED != PASS）",
            "子门禁继承 sys.executable；用错解释器（缺 onnx/onnxruntime）会让 10 个工具 rc=1，本次解释器与依赖探测结果见 interpreter 段；此类红不是工具损坏的证据，也绝不放行为 PASS",
        ],
        "contract_hashes": {
            "line_labels.json": sha256_of(HERE / "line_labels.json"),
            "closure_contract.json": sha256_of(HERE / "closure_contract.json"),
        },
        "scope": "离线门禁编排；不验证硬件，不作实机签收，不消 INCONCLUSIVE_RATE_MISMATCH",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="run all real CLI gates")
    ap.add_argument("--selftest", action="store_true", help="injected CLI fixtures + negative controls")
    ap.add_argument("--list", action="store_true", help="list discovered tools, run nothing")
    ap.add_argument("--tools-dir", default="", help="override the tools root (for --selftest fixtures)")
    ap.add_argument("--timeout", type=int, default=60, help="per-tool timeout in seconds")
    ap.add_argument("--ship-gate", action="store_true", help="require a fully green offline run")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    root = Path(args.tools_dir) if args.tools_dir else TOOLS
    found = discover(root)
    if args.list:
        print("tools root = %s" % root)
        print("discovered --selftest tools = %d" % len(found))
        for f in found:
            print("  " + f.relative_to(root).as_posix())
        print("conductor guards (pre_deploy_check.py) = %d" % len(CONDUCTOR_GUARDS))
        print("scope: offline gates only; --list runs nothing")
        return 0

    if not args.check:
        ap.print_help()
        return 2

    injected = bool(args.tools_dir)
    meta = [] if injected else run_meta(args.timeout)
    tools = [run_one(f, SOFTWARE, args.timeout) for f in found]

    try:
        sys.path.insert(0, str(HERE))
        import line_contract  # noqa: E402
        unlabelled = line_contract.unlabelled_tools(line_contract.load(), TOOLS)
    except Exception as e:  # a broken label file must not silently become green
        unlabelled = ["LINE_GUARD_IMPORT_FAILED: %s" % e]

    interp = interpreter_info()
    rep = build_report(meta, tools, unlabelled, args.ship_gate, interp)
    if injected:
        rep["injected_tools_dir"] = str(root)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("python = %s" % interp["executable"])
        print("heavy_deps = %s  (onnx=%s, onnxruntime=%s)" % (
            "OK" if interp["heavy_deps_ok"] else "MISSING",
            interp["heavy_deps"]["onnx"], interp["heavy_deps"]["onnxruntime"]))
        if not interp["heavy_deps_ok"] and interp["project_venv"]:
            print("HINT: child guards inherit this interpreter; missing heavy deps "
                  "cause rc=1 FAIL. Re-run with the project venv:")
            print("  %s tools/hd1910/run_all_gates.py --check" % interp["project_venv"])
        print("== meta guards ==")
        for m in meta:
            print("  [%-4s] %-34s rc=%-3s %ss  %s" % (m["status"], m["stage"], m["rc"], m["seconds"], m["tail"]))
        print("== --selftest tools (%d) ==" % len(tools))
        for t in tools:
            if t["status"] != "PASS":
                print("  [%-12s] %-38s rc=%-3s %s" % (t["status"], t["tool"], t["rc"], t["detail"]))
        print("  PASS %d / %d   NOT_PASS %d" % (rep["counts"]["pass"], rep["counts"]["total"], rep["counts"]["not_pass"]))
        print("coverage gap: conductor=%d guards, unlabelled tools=%d" %
              (rep["counts"]["conductor_guards"], rep["counts"]["unlabelled_tools"]))
        print("verdict = %s   ship_verdict = %s" % (rep["verdict"], rep["ship_verdict"]))
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if rep["verdict"] != "ALL_PASS":
        return 1
    if args.ship_gate and any(x.startswith("LINE_GUARD_IMPORT_FAILED") for x in unlabelled):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
