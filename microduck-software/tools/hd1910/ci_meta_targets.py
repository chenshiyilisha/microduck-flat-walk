#!/usr/bin/env python3
"""B3: derive the stdlib-only meta-guard list for the lean CI workflow.

Why this exists (2026-11-11)
----------------------------
``run_all_gates.py --check`` runs EVERY discovered --selftest tool, including
ten that import onnx / onnxruntime / mjlab / torch at CLI time. The GitHub
workflow installs only ``tools/hd1910/requirements.txt`` (onnx, onnxruntime,
numpy, pytest; Python 3.12) -- NO torch / mujoco / mjlab / scipy / bam.
Wiring run_all_gates --check into that workflow would produce an honest but
useless red run. Wiring a hand-written list of 9 guards into the YAML would
rot the moment a new guard lands (the repo has already been bitten by a
hard-coded gate count).

So the CI target list is DERIVED from line_labels.json (the single owner of
tool labels), filtered by a real AST dependency probe, and emitted by this
tool. The workflow loops over ``--names`` and runs each guard's --selftest as
a real CLI process; ``run_all_gates.py`` is excluded from the loop (it IS the
orchestrator) but its own --selftest -- which only exercises injected fixtures
-- is run separately.

Boundary: the workflow remains a POST-PUSH ADVISORY CHECK, not a merge gate.
A green run here is not a deployment sign-off; UNVERIFIED != PASS still holds.

Stdlib only. No hardware, no training, no robot.

Usage (cwd = microduck-software):
    python tools/hd1910/ci_meta_targets.py --check
    python tools/hd1910/ci_meta_targets.py --check --json
    python tools/hd1910/ci_meta_targets.py --names
    python tools/hd1910/ci_meta_targets.py --sh
    python tools/hd1910/ci_meta_targets.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import copy
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
LABELS = HERE / "line_labels.json"
REQUIREMENTS = HERE / "requirements.txt"
TOOLS_ROOT = SOFTWARE
META_LINE = "META_GUARD"
ORCHESTRATOR = "run_all_gates.py"
# Modules that are first-party files in this directory, not pip packages.
LOCAL_MODULES = {
    "line_contract", "check_closure", "deploy_stages", "_provenance",
    "sitecustomize_lean_ci", "board_acceptance", "check_image_pairing",
    "reproducible_card", "check_deploy_chain", "check_roller_policy",
    "link_evidence", "ci_meta_targets", "verify_policy_bundle",
    "audit_robotd_toml", "check_control_arm", "summarize_heading_ab",
    "hd1910_ident", "ci_gate_targets", "bundle_bindings",
}
# Explicitly NOT third-party but also NOT safe in lean CI.
HEAVY_MODULES = {
    "numpy", "onnx", "onnxruntime", "torch", "mjlab", "mjlab_microduck",
    "mujoco", "scipy", "serial", "yaml", "tomli", "bam", "bam_actuators",
    "pytest", "requests", "PIL", "cv2",
}


def emit(text: str) -> None:
    """LF-only output for shell consumers.

    print() on Windows emits CRLF; `for G in $(tool --names)` then tries to
    run `tools/hd1910/board_acceptance.py\\r` and every guard dies with rc=2.
    CI is Linux, but the tool must not produce a platform-dependent filename.
    """
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


def load(path: Path = LABELS) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def lean_deps(path: Path = REQUIREMENTS) -> list[str]:
    """Derive the lean CI package list from requirements.txt, not a snapshot.

    A hard-coded "CI has onnx/onnxruntime/numpy/pytest" line would keep lying
    after someone adds or removes a dependency. This reads the file that
    actually installs them.
    """
    if not path.is_file():
        return []
    out: set[str] = set()
    for line in io.open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[ ;]", s)[0].strip()
        if name:
            out.add(name)
    return sorted(out)


def third_party_imports(src: str) -> set[str]:
    """AST over ALL imports (including function-local ones) + dynamic probes."""
    found: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"<SYNTAX_ERROR>"}
    std = set(getattr(sys, "stdlib_module_names", ()))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        # Dynamic import_module("numpy") counts too -- but ONLY a real Call
        # node. A text regex would match the negative-control SAMPLE string
        # inside this very file and falsely mark this tool as heavy.
        elif isinstance(node, ast.Call):
            fn = node.func
            is_import_module = ((isinstance(fn, ast.Name) and fn.id == "import_module")
                                or (isinstance(fn, ast.Attribute)
                                    and fn.attr == "import_module"))
            if is_import_module and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                names = [node.args[0].value]
        for n in names:
            top = n.split(".")[0]
            if top in std or top in LOCAL_MODULES:
                continue
            found.add(top)
    return found


def derive(labels: dict, tools_root: Path = TOOLS_ROOT) -> tuple[list[str], list[str], dict]:
    """Return (basenames, problems, detail) for the CI loop."""
    p: list[str] = []
    detail: dict = {}
    kinds = labels.get("non_line_labels") or {}
    if META_LINE not in kinds:
        p.append("line_labels.json#non_line_labels has no META_GUARD definition")
    entries = labels.get("tools") or []
    metas = [t for t in entries if t.get("line") == META_LINE]
    if not metas:
        p.append("no META_GUARD tools registered: refusing an empty CI loop")
        return [], p, detail

    names: list[str] = []
    seen: set[str] = set()
    for t in metas:
        rel = str(t.get("path", ""))
        name = Path(rel).name
        if not rel.startswith("tools/hd1910/"):
            p.append("%s is not under tools/hd1910/" % rel)
        f = tools_root / rel
        if not f.is_file():
            p.append("META_GUARD file missing: %s" % rel)
            detail[rel] = {"exists": False}
            continue
        src = io.open(f, encoding="utf-8", errors="replace").read()
        if "--selftest" not in src:
            p.append("%s has no --selftest; it cannot be a CI guard" % rel)
        imports = sorted(third_party_imports(src))
        heavy = sorted(set(imports) & HEAVY_MODULES)
        other = sorted(set(imports) - HEAVY_MODULES - {"<SYNTAX_ERROR>"})
        detail[rel] = {"exists": True, "has_selftest": "--selftest" in src,
                       "imports": imports, "heavy": heavy, "other_third_party": other}
        if imports:
            p.append("%s is not stdlib-only (lean CI lacks %s)"
                     % (rel, ", ".join(imports)))
        if name in seen:
            p.append("duplicate META_GUARD basename %s" % name)
        seen.add(name)
        if name == ORCHESTRATOR:
            continue  # the orchestrator is excluded from the per-guard loop
        names.append(name)
    names.sort()

    # The orchestrator exclusion must be an explicit, reviewed fact.
    all_names = {Path(str(t.get("path", ""))).name for t in metas}
    if ORCHESTRATOR not in all_names:
        p.append("%s is no longer registered; re-review the CI split" % ORCHESTRATOR)
    if not names:
        p.append("CI guard list is empty after excluding the orchestrator")
    return names, p, detail


def report(labels: dict, names: list[str], problems: list[str],
           detail: dict) -> dict:
    return {
        "tool": "ci_meta_targets.py",
        "source_of_truth": "line_labels.json#tools[line=META_GUARD]",
        "orchestrator_selftest": ORCHESTRATOR,
        "ci_guard_count": len(names),
        "ci_guards": names,
        "detail": detail,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ci_boundary": "POST-PUSH ADVISORY CHECK, not a merge gate; green != sign-off",
        "lean_ci_dependencies": lean_deps(),
        "excluded_by_design": ("run_all_gates.py --check (discovers heavy tools); "
                               "its --selftest is run separately and only uses "
                               "injected CLI fixtures"),
        "live_hardware_accessed": False,
    }


def selftest() -> int:
    labels = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    names, problems, detail = derive(labels)
    ck("真实标签派生的名单结构自校验通过", not problems, "; ".join(problems[:2]))
    ck("名单非空且不硬编码数量", len(names) >= 8, "count=%d" % len(names))
    ck("编排器被排除在逐条循环之外", ORCHESTRATOR not in names)
    ck("每个入选工具都是 stdlib-only",
       all(not d.get("imports") for d in detail.values() if d.get("exists")))
    ck("每个入选工具都带 --selftest",
       all(d.get("has_selftest") for d in detail.values() if d.get("exists")))

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(labels)
        mutate(bad)
        _, p, _ = derive(bad)
        ck(name, bool(p))

    must_fail("负对照：登记一个不存在的护栏文件必红",
              lambda d: d["tools"].append(
                  {"path": "tools/hd1910/ghost_guard.py", "line": META_LINE}))
    must_fail("负对照：把重依赖工具塞进 META_GUARD 必红",
              lambda d: d["tools"].append(
                  {"path": "tools/hd1910/verify_policy_bundle.py", "line": META_LINE}))
    must_fail("负对照：删掉 META_GUARD 定义必红",
              lambda d: d["non_line_labels"].pop(META_LINE))
    must_fail("负对照：把所有 META_GUARD 标签抹掉必红",
              lambda d: [t.update({"line": "BENCH"}) for t in d["tools"]
                         if t.get("line") == META_LINE])
    must_fail("负对照：登记一个目录外的护栏必红",
              lambda d: d["tools"].append(
                  {"path": "tools/gate_p3_yaw.py", "line": META_LINE}))

    # Dynamic import must be caught too, not only literal `import numpy`.
    ck("负对照：动态 import_module('numpy') 也被判重依赖",
       "numpy" in third_party_imports("import importlib\nx=import_module('numpy')\n"))
    ck("负对照：语法错误不得被当成 stdlib-only",
       "<SYNTAX_ERROR>" in third_party_imports("def (:\n"))

    deps = lean_deps()
    ck("lean CI 依赖从 requirements.txt 实算派生，不是文字快照",
       len(deps) >= 4 and "numpy" in deps and "torch" not in deps,
       ",".join(deps))
    with tempfile.TemporaryDirectory(prefix="md_ci_deps_") as td:
        p = Path(td) / "requirements.txt"
        p.write_text("# comment\ntorch>=2.0\nnumpy\n", encoding="utf-8")
        changed = lean_deps(p)
        ck("负对照：requirements 加 torch 后派生列表必须跟着变",
           "torch" in changed and changed != deps)
        ck("负对照：注释行不得被误读成依赖",
           "# comment" not in changed and len(changed) == 2)

    script = str(HERE / "ci_meta_targets.py")
    names_run = subprocess.run([sys.executable, script, "--names"],
                               cwd=str(SOFTWARE), capture_output=True, text=True)
    emitted = [x for x in names_run.stdout.splitlines() if x.strip()]
    ck("真对照：CLI --names 行数与派生名单一致",
       names_run.returncode == 0 and emitted == names,
       "emitted=%d expected=%d" % (len(emitted), len(names)))
    raw = subprocess.run([sys.executable, script, "--names"],
                         cwd=str(SOFTWARE), capture_output=True)
    ck("跨平台：--names 输出纯 LF，不把 CR 混进文件名",
       b"\r" not in raw.stdout,
       "CR found" if b"\r" in raw.stdout else "")
    sh_raw = subprocess.run([sys.executable, script, "--sh"],
                            cwd=str(SOFTWARE), capture_output=True)
    ck("跨平台：--sh 输出纯 LF", b"\r" not in sh_raw.stdout)
    sh = subprocess.run([sys.executable, script, "--sh"],
                        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：CLI --sh 输出可 source 的计数与名单",
       sh.returncode == 0
       and ("META_GUARD_COUNT=%d" % len(names)) in sh.stdout
       and ("META_GUARDS=\"" + " ".join(names) + "\"") in sh.stdout)
    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：--check --json 结构 PASS 且带 CI 边界声明",
       js.returncode == 0 and json.loads(js.stdout)["structure_verdict"] == "PASS"
       and "POST-PUSH ADVISORY" in json.loads(js.stdout)["ci_boundary"])

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\nci_meta_targets selftest: %d/%d passed"
          % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: CI target derivation only; no hardware, no deploy, no sign-off.")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the derived CI targets")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--names", action="store_true", help="print one guard basename per line")
    ap.add_argument("--sh", action="store_true", help="print source-able shell assignments")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    ap.add_argument("--labels", default=str(LABELS), help="override line_labels.json (tests)")
    ap.add_argument("--tools-dir", default=str(TOOLS_ROOT),
                    help="override the tools root (tests)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    labels = load(Path(args.labels))
    names, problems, detail = derive(labels, Path(args.tools_dir))
    rep = report(labels, names, problems, detail)
    if args.names or args.sh:
        if problems:
            print("[FAIL] " + "; ".join(problems), file=sys.stderr)
            return 1
        if args.names:
            emit("\n".join(names) + "\n")
        else:
            emit("META_GUARD_COUNT=%d\n" % len(names)
                 + 'META_GUARDS="%s"\n' % " ".join(names)
                 + 'ORCHESTRATOR_SELFTEST="%s"\n' % ORCHESTRATOR)
        return 0
    if not args.check:
        ap.print_help()
        return 2
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("CI meta guards (derived from line_labels.json) = %d" % len(names))
        for n in names:
            print("  " + n)
        print("orchestrator selftest = %s --selftest (separate step)" % ORCHESTRATOR)
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("CI boundary: " + rep["ci_boundary"])
        print("live_hardware_accessed = false")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
