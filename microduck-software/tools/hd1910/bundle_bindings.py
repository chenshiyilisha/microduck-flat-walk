#!/usr/bin/env python3
"""Verify the INTERNAL bindings of the HD1910 deploy bundle.

Why this exists (Pass21 / loop R5)
----------------------------------
Pass20 made ``out/hd1910_kp8_deploy_bundle.json`` the single source of truth
for CI: ci_gate_targets.py reads the three deployed .onnx paths, the toml and
--expect-kp from it. That closed the *third* copy of the input list (the
workflow). But the bundle itself still contains TWO independent path lists:

    artifacts.{walk,ground_pick,stand}.rel_path   <- what CI gates / ships
    provenance.per_artifact.<onnx path>          <- what --verify recomputes

They were never bound to each other. A tamper matrix on the real workspace
proved every guard stayed GREEN for all of these:

  C1 delete the walk provenance entry
  C3 plant.id hd1910_kp8 -> hd1910_kp5, kp_fw 8.0 -> 5.0
  C4 falsify deploy_checks / eval / bundle_audit / rehearsal
  C5/C6 point artifacts.walk at another real onnx (provenance untouched)
  C7 point artifacts.walk at the ground_pick onnx (sha/bytes synced)

C7 is the worst case: emitter then produces GATE_WALK == GATE_GROUND_PICK, so
CI gates the SAME policy twice and the walk policy is never checked, while
`record_provenance --verify`, `assert_clean_checkout --strict`, pytest and the
conductor all report PASS. Same family as Pass17 (recorded hash nobody
recomputes), Pass9 (four gates pass but the wrong policy is wired) and Pass20
(a third copy of the input list).

Official basis (SLSA v1.0, "Verifying artifacts", Step 1, verbatim):
    "The goal is to ensure that the provenance actually applies to the artifact
     in question"
    "2. Verify that statement's `subject` matches the digest of the artifact
     in question."
and "expectations are tied to a *package name*, whereas provenance is tied to
an *artifact*". Our `artifacts` block is indexed by POLICY NAME while
`per_artifact` is indexed by ARTIFACT PATH -- exactly the mismatch SLSA says
a verifier must close. We do NOT merge the two blocks (the spec does not ask
for that); we VERIFY the binding, which is the standard fix.

What this module CAN verify, from independent committed authorities:
  * subject binding: per_artifact keys == the three onnx rel_paths, no
    duplicates (two policies may never resolve to the same artifact).
  * deploy_checks: the referenced JSON report really exists, says PASS, and
    its `onnx` / `toml` fields (Windows backslashes normalised) name exactly
    the artifacts this bundle ships. Its top-level verdict is RE-DERIVED from
    its own per-stage status/rc, and its stage set must equal FULL_STAGES read
    out of the CURRENT pre_deploy_check.py source (Pass22/R6: the three
    archived reports predated the inference stage and were still accepted).
  * plant: servo/position_kp/gain vs the real robotd toml (stdlib tomllib);
    kp_fw and id vs tools/hd1910/plant_spec.py's canonical table and the
    apply_to_live.py kp->id mapping; id vs the bundle filename.
  * rehearsal/eval/bundle_audit: key sets and non-empty/True values.

HONEST BOUNDARY: `eval` and `bundle_audit.checks` are human-written prose
summaries. Their NUMERIC CONTENT cannot be recomputed from this repository,
so this module checks their structure and non-emptiness only. A deliberate
edit of the prose ("mean_reward 98.63" -> "999") is still not machine-detectable
here. Do not read a green result as "every sentence in the bundle is proven".

Stdlib only. Python >= 3.11 (tomllib). CI uses 3.12.

Usage (cwd = microduck-software):
    python tools/hd1910/bundle_bindings.py                 # verify real bundle
    python tools/hd1910/bundle_bindings.py --json
    python tools/hd1910/bundle_bindings.py --selftest     # negative controls
"""
from __future__ import annotations

import argparse
import ast
import copy
import importlib.util
import json
import sys
import tempfile
import tomllib
from pathlib import Path

POLICY_KEYS = ("walk", "ground_pick", "stand")
DEFAULT_BUNDLE = "out/hd1910_kp8_deploy_bundle.json"
# Authority for the deploy plant: apply_to_live.py maps 8.0 -> "hd1910_kp8",
# and the bundle filename itself encodes the plant id. Three independent
# sources must agree (the user's rule for catching axis/unit/identity bugs).
DEPLOY_PLANT_ID = "hd1910_kp8"
# B14: register_kp(gain, position_kp) == position_kp ONLY because gain=200.
# ci_gate_targets.py reuses plant.position_kp as --expect-kp on that premise.
GAIN_EXPECTED = 200


def _norm(path: object) -> str | None:
    """Normalise a Windows or POSIX relative path for cross-source comparison.

    deploy_check_*.json was generated on Windows and stores backslashes;
    bundle.json stores forward slashes. Comparing them raw would be a silent
    false mismatch. This is a UNIT normalisation, not a semantic guess.
    """
    if not isinstance(path, str) or not path:
        return None
    return path.replace("\\", "/")


def _canonical_plants(root: Path) -> tuple[dict[float, str], float | None, str | None]:
    """Read kp_fw from the committed canonical plant table (pure stdlib)."""
    src = root / "tools" / "hd1910" / "plant_spec.py"
    if not src.is_file():
        return {}, None, f"canonical plant table missing: {src}"
    name = "_hd1910_bundle_plant_spec"
    try:
        spec = importlib.util.spec_from_file_location(name, src)
        if spec is None or spec.loader is None:
            return {}, None, f"cannot load plant table: {src}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        kp5 = float(mod.HD1910_OFFICIAL_M6_KP5["kp_fw"])
        kp8 = float(mod.HD1910_OFFICIAL_M6_KP8["kp_fw"])
        # apply_to_live.py: {5.0: "hd1910_kp5", 8.0: "hd1910_kp8"}
        return {kp5: "hd1910_kp5", kp8: "hd1910_kp8"}, kp8, None
    except Exception as exc:  # noqa: BLE001 - report, never silently pass
        return {}, None, f"cannot read canonical plant table: {exc}"


def _full_stages(source: Path) -> tuple[list[str], str | None]:
    """Read FULL_STAGES out of the conductor SOURCE (ast; never import/execute).

    The expected stage set is a property of the CURRENT gate, so it must be
    derived from the gate's own source. Keeping a second literal list here
    would rot exactly like Pass20's third copy of the onnx list. Fail loud if
    the constant is missing, unparsable or not a flat list of unique names.
    """
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"),
                         filename=str(source))
    except (OSError, SyntaxError, ValueError) as exc:
        return [], f"STAGE AUTHORITY UNREADABLE: {source}: {exc}"
    raw = None
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and target.id == "FULL_STAGES" \
                and value is not None:
            raw = value
            break
    if raw is None:
        return [], (f"STAGE AUTHORITY MISSING: {source} has no module-level "
                    "FULL_STAGES constant; refusing to guess the stage set")
    try:
        stages = ast.literal_eval(raw)
    except (ValueError, TypeError, SyntaxError) as exc:
        return [], f"STAGE AUTHORITY UNPARSEABLE: {source}: {exc}"
    if not isinstance(stages, (list, tuple)) or not stages \
            or not all(isinstance(s, str) and s for s in stages) \
            or len(set(stages)) != len(stages):
        return [], (f"STAGE AUTHORITY INVALID: {source} FULL_STAGES="
                    f"{stages!r}; expected a non-empty flat list of unique names")
    return list(stages), None


def verify_bindings(bundle: dict, root: Path,
                     bundle_path: Path | None = None,
                     stage_source: Path | None = None) -> tuple[int, list[str]]:
    """Verify the bundle's internal bindings. Pure stdlib, no file writes.

    Returns (0, ["OK ..."]) or (1, [problem, ...]). Every problem names the
    exact block so a red CI points at the edit instead of saying "drift".
    `stage_source` exists so negative controls can PROVE the binding drives
    behaviour (change the conductor's FULL_STAGES -> old reports must go red).
    """
    root = Path(root)
    problems: list[str] = []
    stage_src = (Path(stage_source) if stage_source is not None
                 else Path(__file__).resolve().parent / "pre_deploy_check.py")
    full_stages, stage_err = _full_stages(stage_src)

    def bad(msg: str) -> None:
        problems.append(msg)

    if stage_err:
        bad(stage_err)

    arts = bundle.get("artifacts")
    if not isinstance(arts, dict):
        bad("bundle has no 'artifacts' object")
        return 1, problems

    # ── 1. policy identities: three distinct, real, unique onnx paths ──
    rels: dict[str, str] = {}
    for key in POLICY_KEYS:
        meta = arts.get(key)
        rel = meta.get("rel_path") if isinstance(meta, dict) else None
        if not isinstance(rel, str) or not rel.endswith(".onnx"):
            bad(f"bundle.artifacts.{key}: missing/invalid onnx rel_path {rel!r}")
        else:
            rels[key] = rel
    if len(rels) == len(POLICY_KEYS):
        by_path: dict[str, list[str]] = {}
        for key, rel in rels.items():
            by_path.setdefault(rel, []).append(key)
        for rel, keys in by_path.items():
            if len(keys) > 1:
                bad(f"DUPLICATE POLICY ARTIFACT: {', '.join(keys)} both resolve to "
                    f"{rel} -- CI would gate the same onnx twice and never check "
                    f"the other policy (Pass21 C7)")
    toml_rel = (arts.get("robotd_toml") or {}).get("rel_path") \
        if isinstance(arts.get("robotd_toml"), dict) else None
    if not isinstance(toml_rel, str) or not toml_rel.endswith(".toml"):
        bad(f"bundle.artifacts.robotd_toml: missing/invalid toml rel_path {toml_rel!r}")

    # ── 2. SLSA Step 1.2: provenance subject must match the artifacts ──
    prov = (bundle.get("provenance") or {}).get("per_artifact")
    if not isinstance(prov, dict) or not prov:
        bad("bundle.provenance.per_artifact is missing/empty: no training "
            "provenance is bound to the shipped artifacts")
    elif rels:
        want = {_norm(r) for r in rels.values()}
        got = {_norm(k) for k in prov}
        if got != want:
            bad("SLSA SUBJECT MISMATCH: provenance.per_artifact keys != "
                f"artifacts onnx rel_paths (missing={sorted(want - got)}, "
                f"extra={sorted(got - want)}) -- provenance may describe a "
                "policy this bundle does not ship")
        for key, val in prov.items():
            if not isinstance(val, dict) or not val:
                bad(f"provenance.per_artifact[{key!r}] is empty")

    # ── 3. deploy_checks: recompute against the committed JSON reports ──
    dc = bundle.get("deploy_checks")
    if not isinstance(dc, dict):
        bad("bundle.deploy_checks is missing")
    else:
        if set(dc) != set(POLICY_KEYS):
            bad(f"deploy_checks keys {sorted(dc)} != {list(POLICY_KEYS)}")
        for key in POLICY_KEYS:
            entry = dc.get(key)
            if not isinstance(entry, dict):
                bad(f"deploy_checks.{key}: missing entry")
                continue
            if entry.get("verdict") != "PASS":
                bad(f"deploy_checks.{key}.verdict={entry.get('verdict')!r} "
                    "(only PASS may be claimed in a shipping bundle)")
            jrel = entry.get("json")
            if not isinstance(jrel, str):
                bad(f"deploy_checks.{key}.json: missing report path")
                continue
            report = root / jrel
            if not report.is_file():
                bad(f"deploy_checks.{key}.json: report missing: {jrel}")
                continue
            try:
                rpt = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                bad(f"deploy_checks.{key}.json: unreadable report {jrel}: {exc}")
                continue
            if rpt.get("verdict") != "PASS":
                bad(f"deploy_checks.{key}: report {jrel} verdict="
                    f"{rpt.get('verdict')!r} != PASS")
            # Two INDEPENDENT algorithms for the same quantity: re-derive the
            # verdict from the report's OWN stage list, then compare with its
            # top-level claim. GitHub's own docs explain why this is needed:
            # "When a continue-on-error step fails, the outcome is failure,
            # but the final conclusion is success", and skipped/neutral checks
            # "are treated as a success for dependent checks" -- a green
            # aggregate is not evidence that each component passed. The
            # stage set itself comes from the CURRENT conductor source, so a
            # newly added 6th stage invalidates every stale archived report
            # instead of merely printing an advisory note.
            derived = "PASS"
            stages = rpt.get("stages")
            if not isinstance(stages, list) or not stages:
                bad(f"deploy_checks.{key}: report {jrel} has no structured "
                    "stages -- its PASS cannot be re-derived")
                derived = "FAIL"
            else:
                offenders = []
                stage_names: list[str] = []
                for stage in stages:
                    if not isinstance(stage, dict):
                        offenders.append(repr(stage))
                        continue
                    name = stage.get("name")
                    stage_names.append(name if isinstance(name, str)
                                       else repr(name))
                    if (stage.get("status") != "PASS"
                            or stage.get("rc") not in (0, None)):
                        offenders.append(f"{stage.get('name')}:"
                                         f"{stage.get('status')}/rc={stage.get('rc')}")
                if offenders:
                    bad(f"deploy_checks.{key}: report {jrel} claims PASS but its "
                        f"own stages disagree: {offenders}")
                    derived = "FAIL"
                if len(set(stage_names)) != len(stage_names):
                    bad(f"deploy_checks.{key}: report {jrel} has duplicate "
                        f"stage names: {stage_names}")
                    derived = "FAIL"
                if full_stages:
                    missing = [s for s in full_stages if s not in stage_names]
                    extra = [s for s in stage_names if s not in full_stages]
                    if missing or extra:
                        bad(f"deploy_checks.{key}: report {jrel} stage set "
                            f"{stage_names} != current conductor FULL_STAGES "
                            f"{full_stages} (missing={missing}, extra={extra}); "
                            "archived evidence predates a gate change -- "
                            "regenerate it with pre_deploy_check.py --json")
                        derived = "FAIL"
            if rpt.get("verdict") != derived:
                bad(f"deploy_checks.{key}: report {jrel} verdict="
                    f"{rpt.get('verdict')!r} disagrees with its own stages "
                    f"(re-derived {derived!r})")
            if _norm(rpt.get("onnx")) != rels.get(key):
                bad(f"deploy_checks.{key}: report {jrel} names onnx "
                    f"{_norm(rpt.get('onnx'))!r}, but bundle.artifacts.{key} "
                    f"is {rels.get(key)!r} -- the PASS belongs to a different policy")
            if _norm(rpt.get("toml")) != _norm(toml_rel):
                bad(f"deploy_checks.{key}: report {jrel} names toml "
                    f"{_norm(rpt.get('toml'))!r}, bundle ships {toml_rel!r}")

    # ── 4. plant: three independent authorities must agree ──
    plant = bundle.get("plant")
    if not isinstance(plant, dict):
        bad("bundle.plant is missing: the deploy plant is a first-class coordinate")
    else:
        cfg: dict = {}
        if isinstance(toml_rel, str) and (root / toml_rel).is_file():
            try:
                cfg = tomllib.loads((root / toml_rel).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                bad(f"bundle plant: cannot parse {toml_rel}: {exc}")
        else:
            bad(f"bundle plant: cannot cross-check, toml missing: {toml_rel!r}")
        if cfg:
            bus = cfg.get("bus", {})
            gain = cfg.get("policy", {}).get("gain")
            if plant.get("servo") != bus.get("servo"):
                bad(f"PLANT DRIFT plant.servo={plant.get('servo')!r} != "
                    f"{toml_rel} bus.servo={bus.get('servo')!r}")
            if plant.get("position_kp") != bus.get("position_kp"):
                bad(f"PLANT DRIFT plant.position_kp={plant.get('position_kp')!r} "
                    f"!= {toml_rel} bus.position_kp={bus.get('position_kp')!r}")
            if gain != GAIN_EXPECTED:
                bad(f"PLANT PREMISE BROKEN: {toml_rel} policy.gain={gain!r} != "
                    f"{GAIN_EXPECTED}; ci_gate_targets.py reuses position_kp as "
                    "--expect-kp only on that equivalence (B14)")
        table, kp8, err = _canonical_plants(root)
        if err:
            bad(err)
        else:
            kpf = plant.get("kp_fw")
            if isinstance(kpf, bool) or not isinstance(kpf, (int, float)) \
                    or float(kpf) not in table:
                bad(f"PLANT DRIFT plant.kp_fw={kpf!r} is not a canonical plant "
                    "in tools/hd1910/plant_spec.py")
            if kp8 is not None and kpf != kp8:
                bad(f"DEPLOY PLANT DRIFT: plant.kp_fw={kpf!r} but this is the "
                    f"kp8 deploy bundle (canonical kp8={kp8}); P8 on kp5 falls "
                    "in 7/8 trials -- a different plant means a different task")
            expected_id = table.get(float(kpf)) if isinstance(
                kpf, (int, float)) and not isinstance(kpf, bool) else None
            if plant.get("id") != expected_id:
                bad(f"PLANT ID DRIFT: plant.id={plant.get('id')!r} but kp_fw="
                    f"{kpf!r} maps to {expected_id!r} (apply_to_live.py)")
            if plant.get("id") != DEPLOY_PLANT_ID:
                bad(f"PLANT ID DRIFT: plant.id={plant.get('id')!r} != "
                    f"deploy plant {DEPLOY_PLANT_ID!r}")
    if bundle_path is not None:
        stem = Path(bundle_path).name
        pid = plant.get("id") if isinstance(plant, dict) else None
        if not (isinstance(pid, str) and stem.startswith(pid + "_deploy_bundle")):
            bad(f"PLANT/FILENAME MISMATCH: bundle file {stem!r} does not name "
                f"plant.id={pid!r}")

    # ── 5. claim blocks: structure + boolean values (NOT prose truth) ──
    for block_name, block in (("eval", bundle.get("eval")),
                              ("bundle_audit.checks",
                               (bundle.get("bundle_audit") or {}).get("checks"))):
        if not isinstance(block, dict) or set(block) != set(POLICY_KEYS):
            bad(f"{block_name} keys "
                f"{sorted(block) if isinstance(block, dict) else None} != "
                f"{list(POLICY_KEYS)}")
            continue
        for key in POLICY_KEYS:
            if not (isinstance(block[key], str) and block[key].strip()):
                bad(f"{block_name}.{key} is empty (human-written claim; "
                    "content cannot be recomputed here)")
    rh = bundle.get("rehearsal")
    if not isinstance(rh, dict):
        bad("bundle.rehearsal is missing")
    else:
        for key in POLICY_KEYS:
            if rh.get(key) is not True:
                bad(f"rehearsal.{key}={rh.get(key)!r} is not True")

    if problems:
        return 1, problems
    return 0, ["OK bundle bindings verified: SLSA subject, distinct onnx "
               "targets, deploy_checks reports (verdict re-derived from stages "
               "AND stage set bound to the current conductor FULL_STAGES="
               f"{full_stages}), plant x3 authorities, claim structure (prose "
               "content NOT machine-verifiable)"]


def _selftest(root: Path, bundle_path: Path) -> int:
    """Negative controls on a COPY. Never writes to the real bundle."""
    if not bundle_path.is_file():
        print(f"ERROR: selftest needs the real bundle: {bundle_path}",
              file=sys.stderr)
        return 1
    base = json.loads(bundle_path.read_text(encoding="utf-8"))
    walk = base["artifacts"]["walk"]["rel_path"]
    gp = base["artifacts"]["ground_pick"]["rel_path"]
    ok = True

    def run_case(label: str, mutate, want_rc: int) -> None:
        nonlocal ok
        b = copy.deepcopy(base)
        mutate(b)
        with tempfile.TemporaryDirectory(prefix="hd1910_bindings_") as td:
            # Keep the canonical filename: plant.id is bound to it.
            p = Path(td) / bundle_path.name
            p.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
            rc, msgs = verify_bindings(b, root, p)
        good = rc == want_rc
        ok &= good
        print(f"  [{'ok' if good else 'BAD'}] {label}: rc={rc} (expect {want_rc})")
        if not good:
            for m in msgs[:4]:
                print("        ", m[:150])

    def noop(b):
        pass

    def drop_prov(b):
        b["provenance"]["per_artifact"].pop(walk, None)

    def plant_kp5(b):
        b["plant"]["id"] = "hd1910_kp5"
        b["plant"]["kp_fw"] = 5.0

    def plant_id_only(b):
        b["plant"]["id"] = "hd1910_kp5"

    def plant_wrong_kp(b):
        b["plant"]["position_kp"] = 8

    def claim_verdict(b):
        b["deploy_checks"]["walk"]["verdict"] = "FAIL"

    def claim_report_missing(b):
        b["deploy_checks"]["walk"]["json"] = "out/no_such_report.json"

    def claim_report_wrong_policy(b):
        # ground_pick's real report names the ground_pick onnx, not walk's.
        b["deploy_checks"]["walk"]["json"] = "out/deploy_check_groundpick3999.json"

    def claim_eval_removed(b):
        b["eval"].pop("walk", None)

    def claim_rehearsal_false(b):
        b["rehearsal"]["walk"] = False

    def claim_audit_removed(b):
        b["bundle_audit"]["checks"].pop("walk", None)

    def swap_walk_to_ground_pick(b):
        import hashlib
        raw = (root / gp).read_bytes()
        b["artifacts"]["walk"] = {
            "rel_path": gp,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def duplicate_ground_pick(b):
        b["artifacts"]["ground_pick"]["rel_path"] = walk

    def provenance_extra_key(b):
        b["provenance"]["per_artifact"]["logs/rsl_rl/extra/onnx.onnx"] = {"task": "x"}

    print("=== bundle_bindings selftest (negative controls) ===")
    run_case("C0 intact real bundle", noop, 0)
    for label, fn, want in (
        ("C1 drop walk provenance (SLSA subject)", drop_prov, 1),
        ("C3 plant kp8 -> kp5", plant_kp5, 1),
        ("C3b plant.id changed alone", plant_id_only, 1),
        ("C3c plant.position_kp != toml", plant_wrong_kp, 1),
        ("C4a deploy_checks verdict falsified", claim_verdict, 1),
        ("C4b deploy_checks report missing", claim_report_missing, 1),
        ("C4c deploy_checks report belongs to another policy",
         claim_report_wrong_policy, 1),
        ("C4d eval.walk removed", claim_eval_removed, 1),
        ("C4e rehearsal.walk false", claim_rehearsal_false, 1),
        ("C4f bundle_audit.checks.walk removed", claim_audit_removed, 1),
        ("C7 walk silently replaced by ground_pick",
         swap_walk_to_ground_pick, 1),
        ("C7b duplicate onnx across policies", duplicate_ground_pick, 1),
        ("C8 provenance extra subject", provenance_extra_key, 1),
    ):
        run_case(label, fn, want)

    # C9: an archived report whose top-level verdict says PASS while one of
    # its own stages says FAIL. This needs a real file on disk, so it gets a
    # dedicated case instead of going through run_case().
    with tempfile.TemporaryDirectory(prefix="hd1910_bindings_stage_") as td:
        tdp = Path(td)
        real_report = json.loads(
            (root / base["deploy_checks"]["walk"]["json"])
            .read_text(encoding="utf-8"))
        real_report["stages"][1]["status"] = "FAIL"
        real_report["stages"][1]["rc"] = 1
        bad_report = tdp / "bad_stage_report.json"
        bad_report.write_text(json.dumps(real_report), encoding="utf-8")
        b = copy.deepcopy(base)
        b["deploy_checks"]["walk"]["json"] = str(bad_report.resolve())
        bp = tdp / bundle_path.name
        bp.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
        rc, msgs = verify_bindings(b, root, bp)
        good = rc == 1 and any("own stages disagree" in m for m in msgs)
        ok &= good
        print(f"  [{'ok' if good else 'BAD'}] C9 report PASS but stage FAIL: "
              f"rc={rc} (expect 1)")
        if not good:
            for m in msgs[:4]:
                print("        ", m[:150])

    # C10-C16: the stage-set binding must DRIVE behaviour, not just print an
    # advisory note. GitHub docs: a skipped/neutral component is "treated as a
    # success for dependent checks", so an aggregate verdict is not evidence.
    # C14/C15 are the R4 lesson: changing the SINGLE authority must change the
    # verdict, otherwise we only moved the hard-coded list to another file.
    conductor = root / "tools" / "hd1910" / "pre_deploy_check.py"
    src_text = conductor.read_text(encoding="utf-8")
    marker = '    "contract", "bundle", "numeric", "inference", "toml",\n'
    with tempfile.TemporaryDirectory(prefix="hd1910_bindings_scope_") as td:
        tdp = Path(td)
        real_report = json.loads(
            (root / base["deploy_checks"]["walk"]["json"])
            .read_text(encoding="utf-8"))
        if marker not in src_text:
            ok = False
            print("  [BAD] FULL_STAGES marker missing -- cannot build controls")
        conductor6 = tdp / "conductor6.py"
        conductor4 = tdp / "conductor4.py"
        no_authority = tdp / "no_authority.py"
        conductor6.write_text(
            src_text.replace(marker, marker.replace('"toml",',
                                                    '"toml", "future_stage",')),
            encoding="utf-8")
        conductor4.write_text(
            src_text.replace(marker, marker.replace('"inference", ', '')),
            encoding="utf-8")
        no_authority.write_text("x = 1\n", encoding="utf-8")

        case_no = [0]

        def stage_case(label, mutate_report, source, want_rc, needle):
            nonlocal ok
            case_no[0] += 1
            b = copy.deepcopy(base)
            r = copy.deepcopy(real_report)
            if mutate_report is not None:
                mutate_report(r)
            rp = tdp / f"report_{case_no[0]}.json"
            rp.write_text(json.dumps(r), encoding="utf-8")
            b["deploy_checks"]["walk"]["json"] = str(rp.resolve())
            bp = tdp / bundle_path.name
            bp.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
            rc, msgs = verify_bindings(b, root, bp, stage_source=source)
            good = rc == want_rc and (needle is None or
                                      any(needle in m for m in msgs))
            ok &= good
            print(f"  [{'ok' if good else 'BAD'}] {label}: rc={rc} "
                  f"(expect {want_rc})")
            if not good:
                for m in msgs[:4]:
                    print("        ", m[:150])

        def drop_inference(r):
            r["stages"] = [s for s in r["stages"]
                           if s.get("name") != "inference"]

        def skip_one_stage(r):
            r["stages"][1]["status"] = "SKIP"
            r["stages"][1]["rc"] = 2

        def duplicate_stage(r):
            r["stages"].append(dict(r["stages"][0]))

        needle_set = "!= current conductor FULL_STAGES"
        stage_case("C10 report drops inference stage", drop_inference,
                   None, 1, needle_set)
        stage_case("C11 skipped stage still claims PASS", skip_one_stage,
                   None, 1, "own stages disagree")
        stage_case("C12 duplicate stage names", duplicate_stage,
                   None, 1, "duplicate stage names")
        stage_case("C13 current conductor + intact report = green", None,
                   None, 0, None)
        stage_case("C14 conductor gains a 6th stage -> old report red", None,
                   conductor6, 1, needle_set)
        stage_case("C15 conductor loses inference -> new report red", None,
                   conductor4, 1, needle_set)
        stage_case("C16 stage authority missing -> fail loud", None,
                   no_authority, 1, "STAGE AUTHORITY MISSING")

    print("SELFTEST: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify internal bindings of the HD1910 deploy bundle",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=Path(DEFAULT_BUNDLE),
                    help=f"bundle json (default: {DEFAULT_BUNDLE})")
    ap.add_argument("--root", type=Path, default=Path.cwd(),
                     help="checkout root the relative paths resolve against")
    ap.add_argument("--json", action="store_true",
                     help="emit a machine-readable result")
    ap.add_argument("--selftest", action="store_true",
                     help="run negative controls on a copy of the real bundle")
    ap.add_argument("--stage-source", type=Path, default=None,
                     help="override the conductor source FULL_STAGES is read "
                          "from (negative controls / staged upgrades only)")
    args = ap.parse_args()

    root = args.root.resolve()
    bundle_path = args.bundle if args.bundle.is_absolute() else root / args.bundle
    if args.selftest:
        return _selftest(root, bundle_path)
    if not bundle_path.is_file():
        print(f"ERROR: bundle not found: {bundle_path}", file=sys.stderr)
        return 1
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read bundle: {exc}", file=sys.stderr)
        return 1
    rc, msgs = verify_bindings(bundle, root, bundle_path,
                               stage_source=args.stage_source)
    if args.json:
        print(json.dumps({"verdict": "PASS" if rc == 0 else "FAIL",
                          "bundle": str(bundle_path), "problems": msgs},
                         indent=2, ensure_ascii=False))
    else:
        print(f"== bundle bindings ({bundle_path.name}) ==")
        for m in msgs:
            print("  " + m)
        print("VERDICT: " + ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
