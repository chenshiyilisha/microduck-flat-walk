"""Replay every upstream patch onto third_party/microduck_rl, in order.

Reproduces the exact task-package state the flat-walk numbers were produced in.
Verified 2026-10-26: after this script, every file that the `velocity` task
touches is byte-identical to the trained snapshot (see README.md for the table).

Prerequisites
-------------
- the submodule is checked out at b02fdea4902c2b93b7d34a83a6f05da4ececb7d3
  (script verifies and refuses otherwise);
- for patch_joy_symmetry.py only: an interpreter with torch (pass --python).

What it does
------------
1. prepare the site-packages skeleton the patch tools also patch (the tools
   keep the installed copy and the source tree in lockstep; on a fresh clone
   neither exists, so we materialize the skeleton from the tree first);
2. run apply_joy_patch.py  (extracts the append-only joy hunks from
   rc_joy.patch, itself trimmed from ros-claw/microduck's training patch);
3. run patch_joy_plant_and_meta.py (PD plant + joy ONNX metadata);
4. run the five joy iteration tools;
5. run patch_joy_symmetry.py with --python;
6. normalize every text file in the tree back to LF (the patch tools write
   with text mode, which translates LF to CRLF on Windows);
7. print the sha1 of the files the velocity task depends on.

Skipped on purpose: patch_joy_peak_linear / _peak_curriculum / _pair_min.
They need tools/patch_joy_foot_peak.py, which was lost; their effect is
already inside the trained snapshot, and no velocity code path reads them.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TREE = ROOT / "third_party" / "microduck_rl"
HERE = pathlib.Path(__file__).resolve().parent
B02FDEA = "b02fdea4902c2b93b7d34a83a6f05da4ececb7d3"

JOY_TOOLS = [
    "patch_joy_action_rate.py",
    "patch_joy_exploration.py",
    "patch_joy_foot_sigma.py",
    "patch_joy_gait_clock.py",
    "patch_joy_phase_rsi.py",
]

SITE_FILES = [
    "src/mjlab_microduck/tasks/mdp.py",
    "src/mjlab_microduck/tasks/__init__.py",
    "src/mjlab_microduck/tasks/symmetry.py",
    "src/mjlab_microduck/robot/microduck_constants.py",
]

# The trained snapshot has MIXED line endings: the official 249 files are LF
# (git blob), but the 5 files the original Windows-era patch tools rewrote with
# text-mode write_text came out CRLF. Byte-for-byte reproduction therefore
# needs per-file targets, not a global normalization.
CRLF_FILES = {
    "src/mjlab_microduck/tasks/mdp.py",
    "src/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
    "src/mjlab_microduck/tasks/symmetry.py",
    "src/mjlab_microduck/tasks/__init__.py",
    "tests/test_joy_cfg.py",
}

VELOCITY_FILES = [
    "src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py",
    "src/mjlab_microduck/tasks/mdp.py",
    "src/mjlab_microduck/robot/microduck_constants.py",
]


def sha1(path: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha1(path.read_bytes()).hexdigest()


def run(tool: str, python: str) -> bool:
    print(f"--- {tool}")
    rc = subprocess.run([python, str(HERE / tool)]).returncode
    if rc != 0:
        print(f"    !! {tool} exited {rc}")
    return rc == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter used for the patch tools; needs torch for symmetry")
    args = ap.parse_args()

    git = subprocess.run(["git", "-C", str(TREE), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    if git.returncode != 0:
        print(f"third_party/microduck_rl is not checked out: {git.stderr.strip()}")
        print("run: git submodule update --init third_party/microduck_rl")
        return 1
    if git.stdout.strip() != B02FDEA:
        print(f"refusing: submodule is at {git.stdout.strip()[:12]}, expected b02fdea")
        print("run: git -C third_party/microduck_rl checkout " + B02FDEA)
        return 1
    print(f"submodule at b02fdea OK")

    # 1. site skeleton (apply_joy_patch syncs these into the installed copy;
    #    the joy tools then patch both copies so they stay in lockstep)
    site = ROOT / ".venv-mjlab" / "Lib" / "site-packages" / "mjlab_microduck"
    for rel in SITE_FILES:
        dst = site / rel.split("mjlab_microduck/")[1]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copyfile(TREE / rel, dst)
    print("site skeleton ready")

    ok = True
    # 2-3.
    ok &= run("apply_joy_patch.py", args.python)
    ok &= run("patch_joy_plant_and_meta.py", args.python)
    # 4.
    for tool in JOY_TOOLS:
        ok &= run(tool, args.python)
    # 5. symmetry imports torch
    has_torch = subprocess.run([args.python, "-c", "import torch"],
                               capture_output=True).returncode == 0
    if has_torch:
        ok &= run("patch_joy_symmetry.py", args.python)
    else:
        print("--- patch_joy_symmetry.py SKIPPED: --python has no torch;"
              " rerun with --python pointing at the training venv")

    # 6. per-file EOL targets (see CRLF_FILES comment)
    n = 0
    for pattern in ("*.py", "*.md", "*.txt", "*.xml", "*.toml"):
        for p in TREE.rglob(pattern):
            rel = p.relative_to(TREE).as_posix()
            data = p.read_bytes()
            want_crlf = rel in CRLF_FILES
            if want_crlf and b"\r\n" not in data:
                p.write_bytes(data.replace(b"\n", b"\r\n")); n += 1
            elif not want_crlf and b"\r\n" in data:
                p.write_bytes(data.replace(b"\r\n", b"\n")); n += 1
    print(f"EOL-normalized {n} files (LF, except {len(CRLF_FILES)} historical CRLF files)")

    print("\nvelocity-critical file hashes:")
    for rel in VELOCITY_FILES:
        print(f"  {sha1(TREE / rel)}  {rel}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
