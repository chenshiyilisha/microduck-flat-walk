#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Verify a training transfer pack BEFORE it is zipped.

Why this file exists
--------------------
The 2026-10-27 pack omitted tools/train_heading_variant.py. Every P3-era
train/smoke shell script calls it, so a recipient who unzipped that pack and ran
bootstrap would get "file not found" after installing a 5 GB venv. A pack that
looks complete but cannot train is worse than no pack.

The check is derived, not a hand-written list: scan every .sh in the pack for
`tools/....py` references and require each target to exist in the pack. New
scripts therefore cannot silently add a missing dependency.

Usage:
  python tools/hd1910/server_pack/verify_pack.py --root <stage_dir>
  python tools/hd1910/server_pack/verify_pack.py --selftest   # negative controls
"""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

REF_RE = re.compile(r"tools/[A-Za-z0-9_./-]+\.py")


def refs_from_sh(text: str) -> set[str]:
    """Only real code references count, not mentions inside comments.

    explore_heading_control.sh:13 mentions check_ab_recipe.py in a prose
    comment; that file has never existed in this repo. Treating comments as
    dependencies produced a false FAIL that blocked a valid pack.
    Bash parameter expansion ${VAR#...} has no space before '#', so splitting
    on ' #' is safe.
    """
    out: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.update(REF_RE.findall(line.split(" #", 1)[0]))
    return out

# Files whose absence has already broken (or would break) a real run.
REQUIRED = [
    "tools/train_heading_variant.py",          # explore_heading.sh / smoke_heading.sh
    "tools/eval_velocity_in_sim.py",           # P3 checkpoint selection
    "tools/check_onnx_parity.py",              # verify exported ONNX matches ckpt
    "tools/gate_p3_yaw.py",                    # yaw gate used by rehearsal scripts
    "tools/hd1910/apply_to_live.py",           # plant gate
    "tools/hd1910/log_run_provenance.py",      # every explore_*.sh calls this
    "tools/plant_id.py",                       # plant fingerprint (top-level, imported by train_heading_variant.py)
    "tools/hd1910/server_pack/bootstrap.ps1",
    "tools/hd1910/server_pack/make_transfer.ps1",
    "tools/hd1910/server_pack/p3_sweep.sh",
    "tools/hd1910/server_pack/p3_select.py",
    "tools/hd1910/server_pack/verify_pack.py",
    "tools/hd1910/server_pack/patch_mjlab_win_gl.py",
    "tools/hd1910/server_pack/pins.txt",
    "tools/hd1910/server_pack/README.md",
    "tools/hd1910/explore_heading.sh",
    "tools/hd1910/explore_ground_pick.sh",
    "tools/hd1910/explore_standup.sh",
    "tools/hd1910/smoke_heading.sh",
    "tools/hd1910/eval_ground_pick.py",
    "tools/hd1910/eval_standup.py",
    "tools/bam_params/hd1910/m5.json",
    "tools/bam_params/hd1910/official_m6_stslaw.json",
    ".upstream/bam-62bd8ce12154340be97e06f7f41a0ca8f116d967/pyproject.toml",
    ".upstream/microduck_rl-develop/pyproject.toml",
]


def check(root: Path) -> list[tuple[str, bool, str]]:
    """root is the stage dir containing `microduck-software/`."""
    soft = root / "microduck-software"
    out: list[tuple[str, bool, str]] = []
    out.append(("stage has microduck-software/", soft.is_dir(), str(soft)))
    if not soft.is_dir():
        return out

    for rel in REQUIRED:
        out.append((f"required: {rel}", (soft / rel).is_file(), rel))

    sh_files = sorted(soft.rglob("*.sh"))
    refs: set[str] = set()
    for sh in sh_files:
        try:
            refs.update(refs_from_sh(sh.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    out.append(("scanned .sh files", len(sh_files) > 0, f"{len(sh_files)} scripts"))
    for ref in sorted(refs):
        out.append((f"sh ref: {ref}", (soft / ref).is_file(), ref))
    return out


def report(results: list[tuple[str, bool, str]]) -> int:
    bad = [r for r in results if not r[1]]
    for name, ok, _ in results:
        if not ok:
            print(f"FAIL  {name}")
    print(f"{len(results) - len(bad)}/{len(results)} checks passed "
          f"({len(bad)} FAIL)")
    return 1 if bad else 0


def selftest() -> int:
    """Negative controls: the checker must go red when a real dependency is gone."""
    checks: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        soft = root / "microduck-software"
        soft.mkdir()
        for rel in REQUIRED:
            p = soft / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")
        # a script referencing a REAL top-level tool (already in REQUIRED)
        fake = soft / "tools" / "hd1910" / "smoke_heading.sh"
        fake.write_text(".venv-mjlab/Scripts/python.exe tools/train_heading_variant.py\n",
                        encoding="utf-8")
        base = check(root)
        checks.append(("complete fake pack passes", report(base) == 0))

        # NEGATIVE CONTROL 1: remove the trainer entrypoint -> must go red
        (soft / "tools/train_heading_variant.py").unlink()
        broken = check(root)
        red = any(not ok and "train_heading_variant.py" in name
                  for name, ok, _ in broken)
        checks.append(("negctl missing trainer is detected", red and report(broken) == 1))

        # NEGATIVE CONTROL 2: a script referencing an unpackaged .py -> must go red
        (soft / "tools/train_heading_variant.py").write_text("# stub\n", encoding="utf-8")
        fake.write_text("python tools/not_packaged_helper.py\n", encoding="utf-8")
        broken2 = check(root)
        red2 = any(not ok and "not_packaged_helper.py" in name
                   for name, ok, _ in broken2)
        checks.append(("negctl unpackaged .py ref is detected", red2 and report(broken2) == 1))

        # Comment-only mention must NOT fail; a real ref in the same file still
        # must be scanned (the explore_heading_control.sh false positive).
        fake.write_text(
            "# see tools/hd1910/check_ab_recipe.py for the A/B recipe check\n"
            "python tools/train_heading_variant.py  # trailing comment\n",
            encoding="utf-8")
        mixed = check(root)
        checks.append(("comment-only mention is ignored", report(mixed) == 0))
        checks.append(("real ref beside comment still scanned",
                       any(name == "sh ref: tools/train_heading_variant.py"
                           for name, _, _ in mixed)))

        # NEGATIVE CONTROL 3: empty stage must fail, not silently pass
        empty = root / "empty"
        empty.mkdir()
        checks.append(("negctl empty stage fails", report(check(empty)) == 1))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    bad = sum(1 for _, ok in checks if not ok)
    print(f"{len(checks) - bad}/{len(checks)} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", help="stage dir containing microduck-software/")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.root:
        ap.error("--root is required unless --selftest")
    return report(check(Path(a.root)))


if __name__ == "__main__":
    raise SystemExit(main())
