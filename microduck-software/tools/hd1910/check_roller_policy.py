#!/usr/bin/env python3
"""P0-2: roller-variant policy contract (offline structure, never a sign-off).

Why this exists (2026-11-11)
----------------------------
The user decided to build BOTH the walking and the roller variant. The
printing/assembly list is executable, but "the roller version can walk" is a
software/policy claim with zero board evidence. Three separate things were
being conflated:

  * official V8 roller ONNX: XL330 simulation weights, NOT an HD-1910 policy;
  * the training-studio catalog's kissqy V167 entries: HD1910-specific roller
    ONNX listed inside the R17 firmware bundle, verified by the author only in
    QEMU ARM64 with ``hardware_tested=false`` -- a CATALOG fact, not a board
    acceptance fact;
  * our own ``train_roller.sh``: trains from scratch on hd1910_kp8.

Reading the local catalog (rather than only the 11-06 plan document) narrowed
the open question: it is no longer "does any HD-1910 roller policy exist at
all" but "can R17 V167 actually list/load/switch it on OUR robot, and what is
the real action_scale". Listing a model is not loading it; QEMU is not a robot.

Single sources of truth, all read at runtime and never copied as a verdict:
  line_labels.json (current line), closure_contract.json (open marker),
  deploy_chain_contract.json (chain ids), pretrained_models.json (catalog).

Stdlib only. This tool never trains, downloads a bundle, opens a serial port,
loads an ONNX, or talks to a robot. ``--verify-sources`` EXISTS only when the
upstream catalog is present; a missing/broken/tampered catalog is rc=1 FAIL,
never a SKIP.

Usage (cwd = microduck-software):
    python tools/hd1910/check_roller_policy.py --check
    python tools/hd1910/check_roller_policy.py --check --json
    python tools/hd1910/check_roller_policy.py --check --verify-sources
    python tools/hd1910/check_roller_policy.py --check --ship-gate
    python tools/hd1910/check_roller_policy.py --selftest
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
ROOT = SOFTWARE.parent
CONTRACT = HERE / "roller_policy_contract.json"
LABELS = HERE / "line_labels.json"
CLOSURE = HERE / "closure_contract.json"
CHAIN = HERE / "deploy_chain_contract.json"
DEFAULT_CATALOG = (ROOT / "microduck-software/.upstream/replica/software/"
                   "training-studio/training_studio/pretrained_models.json")


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog_path(explicit: str = "") -> Path:
    return Path(explicit) if explicit else DEFAULT_CATALOG


def validate(data: dict, labels: dict, closure: dict, chain: dict) -> list[str]:
    p: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            p.append(msg)

    need(data.get("schema") == 1, "schema must be 1")
    rule = data.get("rule") or ""
    need("UNVERIFIED" in rule and "PASS" in rule,
         "rule must state UNVERIFIED is not PASS")
    need(data.get("status") == "UNVERIFIED",
         "status must stay UNVERIFIED; a catalog entry is not board acceptance")
    need(data.get("line") == (labels.get("policy") or {}).get("current_line"),
         "line disagrees with line_labels.json#policy.current_line")
    need(data.get("closure_ref") == "INCONCLUSIVE_ROLLER_POLICY",
         "closure_ref must name the registered open marker")
    closure_hit = [c for c in closure.get("contracts", [])
                   if c.get("id") == data.get("closure_ref")]
    need(len(closure_hit) == 1 and closure_hit[0].get("status") == "UNVERIFIED",
         "closure contract missing or no longer UNVERIFIED")
    need(data.get("deploy_chain", {}).get("chain_id")
         in (chain.get("required") or {}).get("chain_ids", []),
         "deploy chain id is not registered in deploy_chain_contract.json")

    # No single "authoritative" action scale may appear: the two sources
    # conflict and neither is a board measurement.
    conflict = data.get("action_scale_conflict") or {}
    need("resolved_action_scale" not in data,
         "resolved_action_scale is forbidden while the conflict is open")
    need("resolved_action_scale" not in conflict,
         "resolved_action_scale is forbidden while the conflict is open")
    sources = conflict.get("sources") or []
    need(len(sources) == 2, "action_scale conflict must name both sources")
    claims = " ".join(str(s.get("claim", "")) for s in sources)
    need("0.8" in claims and "1.0" in claims,
         "both conflicting action_scale claims (0.8 / 1.0) must be recorded")
    need(conflict.get("resolution") == "UNRESOLVED",
         "action_scale conflict must stay UNRESOLVED")

    shared = data.get("shared_contract") or {}
    dims = (data.get("required") or {}).get("shared_dims") or {}
    for k, v in dims.items():
        need(shared.get(k) == v, "shared_contract.%s != required value" % k)
    need("烤进" in str(shared.get("normalizer", "")),
         "normalizer must be baked into the graph")

    req = data.get("required") or {}
    cat = data.get("policy_catalog") or {}
    kq = cat.get("kissqy_v167") or {}
    off = cat.get("official_v8") or {}
    need(set(kq.get("ids") or []) == set(req.get("kissqy_roller_ids") or []),
         "kissqy roller id set != required set")
    need(set(off.get("ids") or []) == set(req.get("official_roller_ids") or []),
         "official roller id set != required set")
    need(kq.get("servos") == "HD1910", "kissqy entries must be HD1910")
    need(off.get("servos") == "XL330", "official entries must be XL330")
    need("hardware_tested=false" in str(kq.get("verification", "")),
         "kissqy verification must state hardware_tested=false")
    entries = kq.get("entries") or []
    need(len(entries) == len(req.get("kissqy_roller_ids") or []),
         "kissqy catalog entries count mismatch")
    for e in entries:
        need(e.get("id") in set(kq.get("ids") or []),
             "catalog entry %r not in kissqy id set" % e.get("id"))
        need(len(str(e.get("sha256", ""))) == 64,
             "catalog entry %s has no sha256" % e.get("id"))
        need(isinstance(e.get("size_bytes"), int) and e["size_bytes"] > 0,
             "catalog entry %s has no positive size" % e.get("id"))
        need(str(e.get("model_file", "")).startswith("roller/"),
             "catalog entry %s model_file is not in the roller bundle" % e.get("id"))
    other = cat.get("other_source_five_names") or {}
    need(len(other.get("names") or []) == 5,
         "the OTHER source's 5 names must be recorded separately, not merged")
    # Structured assertion, not a Chinese-phrase substring match: a wording
    # edit must not silently flip this boundary (project rule on bare `in`).
    need(other.get("different_source") is True,
         "must explicitly declare the two catalogs are different sources")

    dep = data.get("deploy_chain") or {}
    need(set(dep.get("forbidden_commands") or [])
         == set(req.get("forbidden_commands") or []),
         "forbidden command set != required set")
    need(any("R17 V167" in str(x) for x in dep.get("loading_path") or []),
         "loading path must name the R17 V167 console, not publish/robotctl")

    acc = data.get("acceptance") or {}
    metric = str(acc.get("metric", ""))
    need("位移跨度" in metric and "请求已发" in metric,
         "acceptance metric must be displacement span, not 'request sent'")
    need(bool(str(acc.get("negative_control", "")).strip()),
         "acceptance negative_control must be explicit")
    need(bool(acc.get("criteria")) and bool(acc.get("blocked_actions")),
         "acceptance criteria / blocked_actions must be non-empty")
    need(bool(data.get("still_owed")), "still_owed must be non-empty")

    scope = data.get("scope") or {}
    need(scope.get("live_hardware_accessed") is False,
         "scope.live_hardware_accessed must be explicitly false")
    need(bool(scope.get("not_proof_of")) and bool(scope.get("known_gaps")),
         "scope.not_proof_of / known_gaps must be non-empty")
    return p


def verify_catalog(data: dict, path: Path) -> list[str]:
    """Re-derive the roller id sets + hashes from the ONE authoritative file.

    A missing catalog is a FAIL, not a SKIP: --verify-sources is an explicit
    request for evidence and must not be silently satisfied by its absence.
    """
    if not path.is_file():
        return ["catalog source unavailable: %s" % path]
    try:
        rows = json.loads(io.open(path, encoding="utf-8").read())
    except (ValueError, OSError) as e:
        return ["catalog source unreadable: %s: %s" % (path, e)]
    if not isinstance(rows, list) or not rows:
        return ["catalog source is not a non-empty list"]
    official = {r.get("id") for r in rows
                if r.get("source_kind") == "official" and r.get("requires_rollers") is True}
    community = {r.get("id") for r in rows
                 if r.get("source_kind") == "community" and r.get("requires_rollers") is True}
    req = data.get("required") or {}
    p: list[str] = []
    if official != set(req.get("official_roller_ids") or []):
        p.append("catalog official roller ids != contract: %s" % sorted(official))
    if community != set(req.get("kissqy_roller_ids") or []):
        p.append("catalog community roller ids != contract: %s" % sorted(community))
    by_id = {r.get("id"): r for r in rows}
    for e in (data.get("policy_catalog") or {}).get("kissqy_v167", {}).get("entries", []):
        r = by_id.get(e.get("id"))
        if not r:
            p.append("catalog missing %s" % e.get("id"))
            continue
        for k in ("sha256", "size_bytes", "task_id", "model_file"):
            if r.get(k) != e.get(k):
                p.append("catalog %s.%s mismatch: %r != %r"
                         % (e.get("id"), k, r.get(k), e.get(k)))
        if r.get("servos") != "HD1910":
            p.append("catalog %s servos != HD1910" % e.get("id"))
        if "hardware_tested=false" not in str(r.get("verification", "")):
            p.append("catalog %s lost its hardware_tested=false boundary" % e.get("id"))
    return p


def report(data: dict, problems: list[str], verified: bool, src: Path) -> dict:
    return {
        "tool": "check_roller_policy.py",
        "contract_sha256": sha256_of(CONTRACT),
        "status": data.get("status"),
        "line": data.get("line"),
        "closure_ref": data.get("closure_ref"),
        "kissqy_roller_ids": (data.get("required") or {}).get("kissqy_roller_ids"),
        "action_scale": (data.get("action_scale_conflict") or {}).get("resolution"),
        "catalog_source": str(src),
        "catalog_verified": verified,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "not_proof_of": (data.get("scope") or {}).get("not_proof_of"),
        "known_gaps": (data.get("scope") or {}).get("known_gaps"),
        "scope": "轮滑策略的离线结构契约；目录存在 ≠ 文件到手 ≠ 中控可加载 ≠ 实机能走",
    }


def selftest() -> int:
    data = load()
    labels, closure, chain = (load(x) for x in (LABELS, CLOSURE, CHAIN))
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad, labels, closure, chain)))

    base = validate(data, labels, closure, chain)
    ck("盘上契约结构自校验通过", not base, "; ".join(base[:3]))
    ck("契约恒为 UNVERIFIED / NOT_SHIPPABLE",
       data["status"] == "UNVERIFIED"
       and report(data, [], False, DEFAULT_CATALOG)["ship_verdict"] == "NOT_SHIPPABLE")
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("目录级证据把『有没有策略』收窄，但仍标 hardware_tested=false",
       len(data["policy_catalog"]["kissqy_v167"]["ids"]) == 4
       and "hardware_tested=false" in data["policy_catalog"]["kissqy_v167"]["verification"])
    ck("两套清单不同源且分开记录",
       len(data["policy_catalog"]["official_v8"]["ids"]) == 2
       and len(data["policy_catalog"]["other_source_five_names"]["names"]) == 5)

    must_fail("负对照：把状态改成 PASS 必红",
              lambda d: d.update({"status": "PASS"}))
    must_fail("负对照：给出单一权威 action_scale 必红",
              lambda d: d.update({"resolved_action_scale": 0.8}))
    must_fail("负对照：擅自把冲突判为已解必红",
              lambda d: d["action_scale_conflict"].update({"resolution": "RESOLVED"}))
    must_fail("负对照：删掉 0.8 / 1.0 任一来源必红",
              lambda d: d["action_scale_conflict"]["sources"].pop())
    must_fail("负对照：线别改成 B 代必红",
              lambda d: d.update({"line": "L2_BGEN"}))
    must_fail("负对照：删一个 kissqy 策略 id 必红",
              lambda d: d["policy_catalog"]["kissqy_v167"]["ids"].pop())
    must_fail("负对照：把两套清单说成同源必红",
              lambda d: d["policy_catalog"]["other_source_five_names"].update(
                  {"different_source": False}))
    must_fail("负对照：删一条目录 sha256 记录必红",
              lambda d: d["policy_catalog"]["kissqy_v167"]["entries"][0].update({"sha256": ""}))
    must_fail("负对照：抹掉 hardware_tested=false 边界必红",
              lambda d: d["policy_catalog"]["kissqy_v167"].update({"verification": "verified"}))
    must_fail("负对照：obs 61 改成 62 必红",
              lambda d: d["shared_contract"].update({"observation_dim": 62}))
    must_fail("负对照：删掉 publish 禁用命令必红",
              lambda d: d["deploy_chain"]["forbidden_commands"].pop())
    must_fail("负对照：部署路径改回 robotctl 必红",
              lambda d: d["deploy_chain"].update(
                  {"loading_path": ["uv run publish", "robotctl policy load"]}))
    must_fail("负对照：判据改成『请求已发』必红",
              lambda d: d["acceptance"].update({"metric": "请求已发即算通过"}))
    must_fail("负对照：删掉负对照说明必红",
              lambda d: d["acceptance"].update({"negative_control": ""}))
    must_fail("负对照：closure_ref 指向不存在的悬案必红",
              lambda d: d.update({"closure_ref": "INCONCLUSIVE_GHOST"}))
    must_fail("负对照：scope 声称碰过硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    bad_labels = copy.deepcopy(labels)
    bad_labels["policy"]["current_line"] = "L2_BGEN"
    ck("负对照：line_labels 真相源被改则契约判红",
       bool(validate(data, bad_labels, closure, chain)))
    bad_closure = copy.deepcopy(closure)
    for c in bad_closure["contracts"]:
        if c["id"] == "INCONCLUSIVE_ROLLER_POLICY":
            c["status"] = "CLOSED"
    ck("负对照：悬案被擅自闭合则契约判红",
       bool(validate(data, labels, bad_closure, chain)))

    # Real CLI runs: a tampered/missing catalog must be an honest RED, a clean
    # local catalog must be green, and --ship-gate must always refuse.
    script = str(HERE / "check_roller_policy.py")
    with tempfile.TemporaryDirectory(prefix="md_roller_") as td:
        fake = Path(td) / "catalog.json"
        src = catalog_path()
        if src.is_file():
            rows = json.loads(io.open(src, encoding="utf-8").read())
            for r in rows:
                if r.get("id") == "kissqy-roller_swizzle":
                    r["sha256"] = "0" * 64
            fake.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            note = "sha256 被篡改"
        else:
            fake.write_text("[]", encoding="utf-8")
            note = "目录为空"
        bad = subprocess.run([sys.executable, script, "--check", "--verify-sources",
                              "--catalog", str(fake)], cwd=str(SOFTWARE),
                             capture_output=True, text=True)
        ck("负对照：%s 时 --verify-sources 必红" % note, bad.returncode == 1)
        good = subprocess.run([sys.executable, script, "--check", "--verify-sources"],
                              cwd=str(SOFTWARE), capture_output=True, text=True)
        if src.is_file():
            ck("真对照：本地上游目录实算与契约一致", good.returncode == 0,
               good.stdout[-160:])
        else:
            ck("负对照：上游目录缺失时 --verify-sources 不得假绿", good.returncode == 1)
    ship = subprocess.run([sys.executable, script, "--check", "--ship-gate"],
                          cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("负对照：--ship-gate 必 rc=1", ship.returncode == 1)
    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：--check --json 可读且 ship_verdict 如实",
       js.returncode == 0 and json.loads(js.stdout)["ship_verdict"] == "NOT_SHIPPABLE")

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\ncheck_roller_policy selftest: %d/%d passed"
          % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: offline policy structure only; no training, no bundle download, no robot.")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk contract")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 while the roller policy is UNVERIFIED")
    ap.add_argument("--verify-sources", action="store_true",
                    help="with --check, re-derive the catalog from upstream (missing => FAIL)")
    ap.add_argument("--catalog", default="", help="override catalog path (negative controls)")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.check:
        ap.print_help()
        return 2

    data = load()
    labels, closure, chain = (load(x) for x in (LABELS, CLOSURE, CHAIN))
    problems = validate(data, labels, closure, chain)
    src = catalog_path(args.catalog)
    verified = False
    if args.verify_sources:
        cat_problems = verify_catalog(data, src)
        problems.extend(cat_problems)
        verified = not cat_problems
    rep = report(data, problems, verified, src)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("roller_policy_contract.json sha256 = " + rep["contract_sha256"])
        print("status = %s   line = %s   closure_ref = %s"
              % (rep["status"], rep["line"], rep["closure_ref"]))
        print("kissqy V167 roller ids = %d  action_scale = %s"
              % (len(rep["kissqy_roller_ids"]), rep["action_scale"]))
        print("catalog source = %s  verified = %s" % (rep["catalog_source"], verified))
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship verdict = NOT_SHIPPABLE  (目录存在 != 中控可加载 != 实机能走)")
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate:
        if not args.json:
            print("SHIP GATE REFUSED: INCONCLUSIVE_ROLLER_POLICY is UNVERIFIED")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
