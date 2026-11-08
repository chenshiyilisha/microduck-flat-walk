#!/usr/bin/env python3
"""Record training provenance for a deployed HD-1910 ONNX — the local analogue of
upstream ``find_onnx_source.py`` (which reconstructs the source wandb checkpoint via
bit-exact weight matching).

Why this exists
--------------
A deploy bundle that records only ``sha256`` of the artifact is *reproducible* but
not *traceable*: you can re-verify the bytes, but you cannot answer "which training
run, seed, and env config produced this policy?" That question is exactly what
upstream's ``find_onnx_source.py`` exists to answer (against wandb). We keep the same
provenance locally, for free, because every training run already wrote a companion
``runmeta_<run>.json`` / ``heading_meta_<run>.json`` next to ``out/``:

  * ``runmeta_<run>.json``   -> task, plant_arg, device, envs, iters, seed, ab_leg
  * ``heading_meta_<run>.json`` -> created (ISO), cfg_sha256_16, mdp_sha256_16
                                  (env/MDO config hashes), plant.source_file,
                                  passthrough_args (full CLI)

This script harvests those fields and merges them with the *code-side* git
fingerprint produced by the existing ``_provenance.capture_provenance`` (HEAD,
branch, dirty flag, and a sha256 of ``git diff HEAD`` — the stable fingerprint of
any uncommitted work), then (with ``--bundle``) injects the combined block into the
single-source-of-truth deploy bundle.

Division of labour (do NOT duplicate):
  * ``_provenance.py``  captures provenance AT TRAINING TIME and is folded into the
                       runmeta/heading_meta files by the training entrypoints.
  * this script       reads those files AT DEPLOY TIME and assembles the bundle's
                       per-artifact provenance + code git fingerprint.

No third-party imports: provenance is read from companion JSON + ``git`` + the
stdlib-only ``_provenance`` module, so this runs on a clean checkout. (It does NOT
need ``onnx``.)

Exit codes: 0 ok, 1 usage/IO error (or provenance DRIFT under --verify), 2 a
referenced onnx has no companion meta AND no path-parseable config (honest
"unknown", not a forged success). ``--verify`` recomputes the per-artifact block
from the onnx paths stored in the bundle and fails (rc=1) on any field drift,
catching "the onnx changed but provenance was never refreshed".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # microduck-software
OUT = ROOT / "out"

# Reuse the existing, tested code-side git fingerprint logic instead of
# re-implementing it (single source of truth for "what code built this").
sys.path.insert(0, str(HERE))
import _provenance  # noqa: E402  (stdlib-only; safe to import here)

# A training export's onnx is named "<timestamp>_<run>.onnx"; the companion meta
# files are written WITHOUT the leading "<timestamp>_" prefix.
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_")


def strip_timestamp(stem: str) -> str:
    """Drop the leading ``YYYY-MM-DD_HH-MM-SS_`` prefix (and the following ``_``)."""
    s = _TS_RE.sub("", stem, count=1)
    return s.lstrip("_")


_ITER_RE = re.compile(r"(?:resume|it|_it)(\d{2,5})\b|\b(\d{3,5})$")


def parse_iteration(stem: str) -> Optional[int]:
    """Best-effort export iteration (checkpoint step) from the onnx stem."""
    m = _ITER_RE.search(stem)
    if not m:
        return None
    val = m.group(1) or m.group(2)
    return int(val) if val else None


_ENVX_RE = re.compile(r"(\d{3,5})x(\d{3,5})")


def parse_envxiter(stem: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort (envs, iters) parsed from a ``<envs>x<iters>`` token in the stem."""
    m = _ENVX_RE.search(stem)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


@dataclass
class Provenance:
    run: str
    source: str  # which meta file(s) supplied the data
    task: Optional[str] = None
    plant_arg: Optional[str] = None
    plant_name: Optional[str] = None
    plant_source_file: Optional[str] = None
    device: Optional[str] = None
    mujoco_gl: Optional[str] = None
    envs: Optional[int] = None
    iters: Optional[int] = None
    export_iteration: Optional[int] = None
    seed: Optional[int] = None
    ab_leg: Optional[str] = None
    created: Optional[str] = None
    cfg_sha256_16: Optional[str] = None
    mdp_sha256_16: Optional[str] = None
    passthrough_args: Optional[list] = None
    companion_meta: str = "absent"  # "runmeta" | "heading_meta" | "both" | "absent"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def provenance_for_onnx(onnx_path: Path) -> Provenance:
    stem = onnx_path.stem
    run = strip_timestamp(stem)
    pv = Provenance(run=run, source="")
    pv.export_iteration = parse_iteration(stem)
    pe, pi = parse_envxiter(stem)
    pv.envs, pv.iters = pe, pi  # path fallback; overridden by meta if present

    rm = _load_json(OUT / f"runmeta_{run}.json")
    hm = _load_json(OUT / f"heading_meta_{run}.json")

    if rm:
        pv.source = "runmeta"
        pv.companion_meta = "runmeta"
        pv.task = rm.get("task")
        pv.plant_arg = rm.get("plant_arg")
        pv.device = rm.get("device")
        pv.mujoco_gl = rm.get("mujoco_gl")
        pv.envs = rm.get("envs", pv.envs)
        pv.iters = rm.get("iters", pv.iters)
        pv.seed = rm.get("seed")
        pv.ab_leg = rm.get("ab_leg")
    if hm:
        pv.source = (pv.source + "+heading_meta") if pv.source else "heading_meta"
        pv.companion_meta = "both" if rm else "heading_meta"
        pv.created = hm.get("created")
        pv.cfg_sha256_16 = hm.get("cfg_sha256_16")
        pv.mdp_sha256_16 = hm.get("mdp_sha256_16")
        pv.task = pv.task or hm.get("task")
        pv.envs = pv.envs or hm.get("envs")
        pv.iters = pv.iters or hm.get("iters")
        pv.passthrough_args = hm.get("passthrough_args")
        plant = hm.get("plant")
        if isinstance(plant, dict):
            pv.plant_name = plant.get("name")
            pv.plant_source_file = plant.get("source_file")
        elif isinstance(plant, str):
            pv.plant_name = plant

    if pv.companion_meta == "absent":
        pv.source = "path-only (no companion meta)"
    return pv


# Provenance facts that must be stable per artifact: if the onnx (or its
# companion meta) changes, these should change too. Drift between the stored
# bundle block and a fresh recomputation means "the onnx moved but provenance
# was not refreshed" — a silent traceability gap.
_ARTIFACT_FIELDS = (
    "task", "plant_name", "cfg_sha256_16", "mdp_sha256_16", "export_iteration",
)

# Machine-readable "what was NOT verified" block. Cross-checked against the
# authoritative installation.json so the boundary cannot be quietly flipped to
# green by editing the bundle alone. Mirrors hd1910m's release_validation.json.
_BOUNDARY_FLAGS = ("calibration_verified", "imu_pose_verified", "mapping_confirmed")
_CALIBRATION_SOURCE = ROOT / ".upstream" / "hd1910m" / "radxa" / "installation.json"


def verify_boundary(bundle: dict) -> tuple[int, list[str]]:
    """Check the bundle's verification_boundary against the authoritative
    calibration file. Pure stdlib. Returns (rc, messages)."""
    b = bundle.get("verification_boundary")
    if not b:
        return 1, ["bundle has no 'verification_boundary' block: a PASS cannot "
                    "be distinguished from a hardware sign-off"]
    if not _CALIBRATION_SOURCE.is_file():
        return 2, [f"authoritative calibration source missing: {_CALIBRATION_SOURCE}"]
    src = json.loads(_CALIBRATION_SOURCE.read_text(encoding="utf-8"))
    msgs: list[str] = []
    rc = 0
    for flag in _BOUNDARY_FLAGS:
        want = src.get(flag)
        got = b.get(flag)
        if got != want:
            rc = 1
            msgs.append(
                f"BOUNDARY DRIFT {flag}: bundle={got!r} but installation.json={want!r}")
        if b.get("authoritative_flags", {}).get(flag) != want:
            rc = 1
            msgs.append(
                f"BOUNDARY DRIFT authoritative_flags.{flag}: "
                f"{b.get('authoritative_flags', {}).get(flag)!r} != {want!r}")
    # A hardware sign-off must never be claimed while calibration is unverified.
    if b.get("hardware_tested") and not (b.get("calibration_verified")
                                        and b.get("imu_pose_verified")):
        rc = 1
        msgs.append("BOUNDARY CONTRADICTION: hardware_tested=true while calibration "
                     "or IMU pose is unverified")
    if b.get("motion_permitted") and not (b.get("calibration_verified")
                                          and b.get("imu_pose_verified")):
        rc = 1
        msgs.append("BOUNDARY CONTRADICTION: motion_permitted=true without verified "
                     "calibration + IMU pose (hd1910m configure.py would refuse)")
    if not b.get("limits"):
        rc = 1
        msgs.append("BOUNDARY DRIFT: limits[] is empty; unverified scope must be listed")
    if rc == 0:
        msgs.append("OK verification_boundary consistent with installation.json")
    return rc, msgs


def verify_bundle(bundle_path: Path) -> tuple[int, list[str]]:
    """Recompute per-artifact provenance from the onnx paths recorded in the
    bundle and diff against the stored block. Pure stdlib (no onnx). Returns
    (rc, messages); rc=1 on any per-artifact drift. The code-side git_commit is
    compared but only WARNed (new commits are expected between runs).
    """
    if not bundle_path.exists():
        return 1, [f"bundle not found: {bundle_path}"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    prov = bundle.get("provenance")
    if not prov:
        return 1, ["bundle has no 'provenance' block to verify"]
    msgs: list[str] = []
    rc = 0

    # The "what was NOT verified" boundary is part of the same single source
    # of truth. Check it against installation.json so a PASS cannot be quietly
    # upgraded to a hardware sign-off by editing the bundle.
    brc, bmsgs = verify_boundary(bundle)
    msgs.extend(bmsgs)
    rc = max(rc, brc)

    cur_code = _provenance.capture_provenance(ROOT)
    stored_code = prov.get("code", {})
    if stored_code.get("git_commit") != cur_code.get("git_commit"):
        msgs.append(
            f"WARN code git_commit differs: stored="
            f"{str(stored_code.get('git_commit'))[:7]} current="
            f"{str(cur_code.get('git_commit'))[:7]} (expected after new commits)")

    pa = prov.get("per_artifact", {})
    if not pa:
        return 1, ["bundle provenance has no 'per_artifact' entries"]
    for rel, stored in pa.items():
        onnx = ROOT / rel
        if not onnx.exists():
            rc = 1
            msgs.append(f"DRIFT onnx missing on disk: {rel}")
            continue
        pv = provenance_for_onnx(onnx)
        for f in _ARTIFACT_FIELDS:
            sv = stored.get(f)
            cv = getattr(pv, f)
            if sv != cv:
                rc = 1
                msgs.append(
                    f"DRIFT {rel}: {f} stored={sv!r} recomputed={cv!r}")
    if rc == 0:
        msgs.append(f"OK provenance consistent for {len(pa)} artifact(s)")
    return rc, msgs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, nargs="+", default=None,
                    help="deployed policy .onnx file(s) to harvest provenance from")
    ap.add_argument("--bundle", type=Path, default=None,
                    help="deploy bundle JSON to read/inject/verify the provenance block")
    ap.add_argument("--print", action="store_true",
                    help="print the provenance JSON (from --bundle if given, else "
                         "recomputed from --onnx)")
    ap.add_argument("--verify", action="store_true",
                    help="verify the bundle's stored provenance matches the onnx "
                         "companion meta on disk (detects onnx changed but "
                         "provenance not refreshed); stdlib-only, CI-safe")
    args = ap.parse_args()

    if args.verify:
        if not args.bundle:
            print("ERROR: --verify requires --bundle", file=sys.stderr)
            return 3
        rc, msgs = verify_bundle(args.bundle)
        for m in msgs:
            print(m)
        return rc

    # Code-side fingerprint: reuse the existing _provenance git logic.
    code = _provenance.capture_provenance(ROOT)

    prov: dict[str, dict] = {}
    any_unknown = False
    if args.onnx:
        for onnx in args.onnx:
            if not onnx.exists():
                print(f"ERROR: onnx not found: {onnx}", file=sys.stderr)
                return 1
            pv = provenance_for_onnx(onnx)
            rel = str(onnx.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
            prov[rel] = pv.to_dict()
            if pv.companion_meta == "absent" and pv.export_iteration is None \
               and pv.envs is None and pv.iters is None:
                any_unknown = True
            print(f"[{pv.companion_meta:<9}] {onnx.name}")
            print(f"    task={pv.task} plant={pv.plant_name} seed={pv.seed} "
                  f"envs={pv.envs} iters={pv.iters} export_iter={pv.export_iteration}")
            if pv.cfg_sha256_16:
                print(f"    cfg_sha256_16={pv.cfg_sha256_16} mdp_sha256_16={pv.mdp_sha256_16}")
            if pv.created:
                print(f"    created={pv.created}")

    block = {
        "code": code,
        "per_artifact": prov,
    }

    if args.bundle:
        if not args.bundle.exists():
            print(f"ERROR: bundle not found: {args.bundle}", file=sys.stderr)
            return 1
        if args.onnx:
            bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
            bundle["provenance"] = block
            args.bundle.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
            print(f"\ninjected provenance into {args.bundle}")
        elif args.print:
            # Print the provenance block already stored in the bundle.
            bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
            stored = bundle.get("provenance", {})
            print(json.dumps(stored, indent=2, ensure_ascii=False))
            return 0

    if args.print:
        print(json.dumps(block, indent=2, ensure_ascii=False))

    return 2 if any_unknown else 0


if __name__ == "__main__":
    sys.exit(main())
