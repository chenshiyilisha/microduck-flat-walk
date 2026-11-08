#!/usr/bin/env python3
"""Emit the REAL deploy-gate targets from the bundle (single source of truth).

Why this exists (Pass20 / loop R4)
----------------------------------
`deploy-gate.yml` used to hard-code the three deployed .onnx paths, the
robotd.toml path and `--expect-kp 16` in its "Real deploy gate" shell step.
That is a THIRD copy of the input list (bundle.json is the first, the
readiness probe's own closure is the second). Negative control proved the
copy could rot in silence: pointing the workflow's ground-pick path at a
stale onnx still produced `--strict rc=0`, `pytest` green and
`record_provenance --verify rc=0` -- CI would then validate a policy that is
NOT the one the bundle says ships to the robot. Same family as Pass17's
"recorded hash nobody recomputes" and Pass9's "four gates pass but the wrong
policy is wired".

Fix: the workflow sources its targets from THIS script, which reads
out/hd1910_kp8_deploy_bundle.json. There is no second list to keep in sync.
A local guard (assert_clean_checkout.py::probe_workflow) fails if anyone
ever hard-codes an .onnx path into the workflow again.

Usage (cwd = microduck-software):
    python tools/hd1910/ci_gate_targets.py --sh > "$RUNNER_TEMP/gate_targets.sh"
    . "$RUNNER_TEMP/gate_targets.sh"       # sets GATE_* variables
    python tools/hd1910/ci_gate_targets.py --json     # machine-readable
    python tools/hd1910/ci_gate_targets.py --selftest # negative controls

Stdlib only: lean CI installs nothing for this script.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

POLICY_KEYS = ("walk", "ground_pick", "stand")
SHELL_NAMES = {"walk": "GATE_WALK", "ground_pick": "GATE_GROUND_PICK",
                "stand": "GATE_STAND"}
DEFAULT_BUNDLE = "out/hd1910_kp8_deploy_bundle.json"
# Deliberately strict: these values are emitted into a shell fragment that CI
# sources. No metacharacters, no newlines, no traversal, no absolute paths.
_SAFE_REL = re.compile(r"^[A-Za-z0-9_./-]+$")


class TargetsError(ValueError):
    """The bundle cannot name a safe, real set of deploy-gate targets."""


def _check_rel(rel: object, name: str) -> str:
    if not isinstance(rel, str) or not rel:
        raise TargetsError(f"{name}: rel_path must be a non-empty string")
    if not _SAFE_REL.fullmatch(rel):
        raise TargetsError(
            f"{name}: unsafe rel_path {rel!r} (only [A-Za-z0-9_./-] allowed; "
            "the value is sourced by a shell in CI)")
    if rel.startswith("/") or ".." in rel.split("/"):
        raise TargetsError(f"{name}: rel_path must stay inside the checkout: {rel!r}")
    return rel


def load_targets(bundle_path: Path, root: Path) -> dict:
    """Read and VALIDATE the gate targets from the bundle. Never guess a path."""
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TargetsError(f"cannot read bundle {bundle_path}: {exc}") from exc

    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TargetsError("bundle has no artifacts object")

    policies: dict[str, str] = {}
    for key in POLICY_KEYS:
        meta = artifacts.get(key)
        if not isinstance(meta, dict):
            raise TargetsError(f"bundle.artifacts.{key} is missing")
        rel = _check_rel(meta.get("rel_path"), f"artifacts.{key}")
        if not rel.endswith(".onnx"):
            raise TargetsError(f"artifacts.{key}: not an .onnx policy: {rel!r}")
        if not (root / rel).is_file():
            raise TargetsError(f"artifacts.{key}: file missing on disk: {rel}")
        policies[key] = rel

    # Pass21 / R5 negative control C7: two policies resolving to the SAME
    # onnx makes CI gate that file twice and never check the missing policy.
    # The full SLSA subject binding lives in bundle_bindings.py (called by
    # record_provenance --verify); this is the gate-entry defence in depth.
    if len(set(policies.values())) != len(POLICY_KEYS):
        clashes = {r: [k for k, v in policies.items() if v == r]
                   for r in set(policies.values())}
        dup = {r: ks for r, ks in clashes.items() if len(ks) > 1}
        raise TargetsError(
            f"DUPLICATE POLICY ARTIFACT: {dup} -- CI would gate the same onnx "
            "twice and never check the other policy (Pass21 C7)")

    toml_meta = artifacts.get("robotd_toml")
    if not isinstance(toml_meta, dict):
        raise TargetsError("bundle.artifacts.robotd_toml is missing")
    toml_rel = _check_rel(toml_meta.get("rel_path"), "artifacts.robotd_toml")
    if not toml_rel.endswith(".toml"):
        raise TargetsError(f"artifacts.robotd_toml: not a .toml: {toml_rel!r}")
    if not (root / toml_rel).is_file():
        raise TargetsError(f"artifacts.robotd_toml: file missing on disk: {toml_rel}")

    plant = bundle.get("plant")
    if not isinstance(plant, dict) or "position_kp" not in plant:
        raise TargetsError("bundle.plant.position_kp is missing")
    kp = plant["position_kp"]
    # NOTE on semantics: --expect-kp is the expected reg50, while
    # plant.position_kp is bus.position_kp. They are numerically equal here
    # ONLY because gain=200 makes register_kp(200, x) == x (B14). If gain ever
    # changes, audit_robotd_toml.py's R1 recomputes reg50 and FAILs the gate;
    # this script must then read an explicit expected_reg50 instead.
    if isinstance(kp, bool) or not isinstance(kp, (int, float)) or int(kp) != kp:
        raise TargetsError(f"bundle.plant.position_kp must be an integer, got {kp!r}")
    if int(kp) <= 0:
        raise TargetsError(f"bundle.plant.position_kp must be positive, got {kp!r}")

    return {"policies": policies, "toml": toml_rel, "expect_kp": int(kp),
            "bundle": str(bundle_path)}


def render_sh(targets: dict) -> str:
    """Shell-safe fragment. Values are shlex-quoted AND pre-validated above."""
    lines = [f"# generated by ci_gate_targets.py from {targets['bundle']}",
             "# do not edit; the bundle is the single source of truth"]
    for key in POLICY_KEYS:
        lines.append(f"{SHELL_NAMES[key]}={shlex.quote(targets['policies'][key])}")
    lines.append(f"GATE_TOML={shlex.quote(targets['toml'])}")
    lines.append(f"GATE_EXPECT_KP={targets['expect_kp']}")
    lines.append(f"GATE_COUNT={len(POLICY_KEYS)}")
    return "\n".join(lines) + "\n"


def _selftest() -> int:
    """Negative controls: a broken bundle must NOT emit a usable gate."""
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        good_policies = {}
        for key in POLICY_KEYS:
            rel = f"out/{key}.onnx"
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(b"fake-onnx")
            good_policies[key] = {"rel_path": rel}
        (root / "out" / "robotd.toml").write_text("[battery]\n", encoding="utf-8")

        def bundle(**overrides) -> Path:
            data = {
                "plant": {"position_kp": 16},
                "artifacts": {**good_policies,
                               "robotd_toml": {"rel_path": "out/robotd.toml"}},
            }
            for k, v in overrides.items():
                if k in ("plant", "artifacts"):
                    data[k] = v
                else:
                    data[k] = v
            p = root / "bundle.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            return p

        def expect(label: str, path: Path, should_pass: bool):
            nonlocal ok
            try:
                t = load_targets(path, root)
                got = True
            except TargetsError as exc:
                t, got = None, False
            mark = "ok" if got == should_pass else "BAD"
            if got != should_pass:
                ok = False
            print(f"  [{mark}] {label}: accepted={got} (expect {should_pass})")
            return t

        expect("complete bundle", bundle(), True)
        expect("missing walk artifact",
               bundle(artifacts={k: v for k, v in good_policies.items()
                                  if k != "walk"}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        expect("rel_path with shell metacharacters",
               bundle(artifacts=good_policies
                      | {"ground_pick": {"rel_path": "out/x; rm -rf /.onnx"}}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        expect("rel_path with directory traversal",
               bundle(artifacts=good_policies
                      | {"stand": {"rel_path": "../outside.onnx"}}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        expect("rel_path that is not an onnx",
               bundle(artifacts=good_policies
                      | {"walk": {"rel_path": "out/walk.txt"}}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        expect("onnx file absent on disk",
               bundle(artifacts=good_policies
                      | {"walk": {"rel_path": "out/gone.onnx"}}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        # Pass21 C7: ground_pick pointing at walk's onnx -> CI gates twice.
        expect("two policies resolve to the same onnx",
               bundle(artifacts=good_policies
                      | {"ground_pick": {"rel_path": "out/walk.onnx"}}
                      | {"robotd_toml": {"rel_path": "out/robotd.toml"}}), False)
        expect("toml artifact missing", bundle(artifacts=good_policies), False)
        expect("plant.position_kp missing", bundle(plant={}), False)
        expect("plant.position_kp not an integer",
               bundle(plant={"position_kp": "16"}), False)
        expect("plant.position_kp zero", bundle(plant={"position_kp": 0}), False)
        expect("bundle is not JSON", _bad_json(root), False)

        good = load_targets(bundle(), root)
        sh = render_sh(good)
        variables = ("GATE_WALK=", "GATE_GROUND_PICK=", "GATE_STAND=",
                     "GATE_TOML=", "GATE_EXPECT_KP=16", "GATE_COUNT=3")
        complete = all(v in sh for v in variables) and "\n\n" not in sh
        ok &= complete
        print(f"  [{'ok' if complete else 'BAD'}] --sh emits all 6 GATE_* variables")

        # The emitted fragment must never contain a raw newline inside a value.
        single_line_values = all(len(l.split("=", 1)[1].splitlines()) == 1
                                 for l in sh.splitlines() if "=" in l)
        ok &= single_line_values
        print(f"  [{'ok' if single_line_values else 'BAD'}] "
              "no value spans more than one line")

    print("SELFTEST: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _bad_json(root: Path) -> Path:
    p = root / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Emit CI deploy-gate targets from the bundle (single source of truth)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=Path(DEFAULT_BUNDLE),
                    help=f"bundle json (default: {DEFAULT_BUNDLE}, relative to cwd)")
    ap.add_argument("--root", type=Path, default=Path.cwd(),
                    help="checkout root the rel_paths resolve against (default: cwd)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--sh", action="store_true",
                       help="emit a shell-safe GATE_* fragment for CI to source")
    mode.add_argument("--json", action="store_true",
                       help="emit machine-readable targets")
    mode.add_argument("--selftest", action="store_true",
                       help="run negative controls; needs no real policy")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    try:
        targets = load_targets(args.bundle, args.root)
    except TargetsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(targets, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_sh(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
