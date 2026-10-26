"""Apply `training/continuous_joy.patch` (Duckverse) to our local microduck_rl checkout.

Why not `git apply` / `patch`
-----------------------------
The patch is anchored at commit `5946fd9` (2024-09-01). Our local tree is the
`develop` snapshot that already carries parkour/standup tasks, so `mdp.py` is 7706
lines where the patch expects 8248. `patch -p1` refuses every hunk.

But every hunk is either
  * an append at end-of-file (`mdp.py`, `__init__.py`), or
  * a whole new file (`microduck_joy_env_cfg.py`, `tests/test_joy_cfg.py`),
so the hunks do not actually need the missing context -- we only need the added
lines, in order. That is what this script extracts, from the patch itself rather
than retyped by hand (200 lines of hand-copied reward code is exactly how silent
bugs get in).

`scripts/export.py` is deliberately skipped: its hunk sits *inside* a function, so
appending would corrupt the file. The metadata it adds is only needed at ONNX
export time, and is applied separately.

Idempotent: re-running detects the already-applied marker and does nothing.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
UP = ROOT / "tools" / "upstream_patches"
PATCH = UP / "rc_joy.patch"
TREE = ROOT / "third_party" / "microduck_rl"

# file -> how we install it
APPEND = {
    "src/mjlab_microduck/tasks/mdp.py": "def joy_phase(",
    "src/mjlab_microduck/tasks/__init__.py": "Mjlab-Joy-Flat-MicroDuck",
}
CREATE = [
    "src/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
    "tests/test_joy_cfg.py",
]
SKIP = ["scripts/export.py"]


def parse_added(patch_text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    cur: str | None = None
    for line in patch_text.splitlines():
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            if p == "/dev/null":
                cur = None
                continue
            cur = p
            blocks.setdefault(cur, [])
            continue
        if line.startswith("@@"):
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            blocks[cur].append(line[1:])
        # context (' ') and removed ('-') lines carry nothing we need
    return blocks


def main() -> int:
    if not PATCH.exists():
        print(f"missing {PATCH}", file=sys.stderr)
        return 1
    blocks = parse_added(PATCH.read_text(encoding="utf-8"))
    print(f"parsed {len(blocks)} file blocks from {PATCH.name}")

    for rel, marker in APPEND.items():
        target = TREE / rel
        added = blocks.get(rel, [])
        if not added:
            print(f"  !! no added lines for {rel}")
            continue
        if marker in target.read_text(encoding="utf-8"):
            print(f"  = {rel}: already applied (found {marker!r})")
            continue
        body = target.read_text(encoding="utf-8")
        if not body.endswith("\n"):
            body += "\n"
        target.write_text(body + "\n" + "\n".join(added) + "\n", encoding="utf-8")
        print(f"  + {rel}: appended {len(added)} lines")

    for rel in CREATE:
        target = TREE / rel
        added = blocks.get(rel, [])
        if not added:
            print(f"  !! no added lines for {rel}")
            continue
        if target.exists():
            print(f"  = {rel}: exists, left untouched")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(added) + "\n", encoding="utf-8")
        print(f"  + {rel}: created ({len(added)} lines)")

    for rel in SKIP:
        if rel in blocks:
            print(f"  - {rel}: skipped on purpose (mid-function hunk, metadata only)")

    # The package is installed as a *copy*, so `train.exe` reads site-packages and
    # never sees the source tree. PYTHONPATH is not a fix on Windows (separator is
    # `;`, a bash-built `a:b` becomes one invalid entry -- that cost one full run:
    # train.exe listed every task except the Joy ones). Sync instead.
    site = ROOT / ".venv-mjlab" / "Lib" / "site-packages" / "mjlab_microduck"
    if site.is_dir():
        for rel in [
            "src/mjlab_microduck/tasks/mdp.py",
            "src/mjlab_microduck/tasks/__init__.py",
            "src/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
            # Mirror tables. tools/patch_joy_symmetry.py extends them to the
            # 63-D layout (gait clock). Without this line a re-sync would push
            # the 61-D tables back and the augmentation would silently truncate
            # the observation instead of mirroring it.
            "src/mjlab_microduck/tasks/symmetry.py",
            # Not a patch file: MICRODUCK_STANDUP_PD_ROBOT_CFG was reconstructed
            # here (see its note), and train.exe only ever reads the copy.
            "src/mjlab_microduck/robot/microduck_constants.py",
        ]:
            src_f = TREE / rel
            dst_f = site / src_f.parent.relative_to(TREE / "src" / "mjlab_microduck") / src_f.name
            if src_f.exists():
                dst_f.write_text(src_f.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"  > synced {src_f.name} -> site-packages")
    else:
        print(f"  ! {site} not found, skipped sync (install the package first)")

    # Upstream's joy cfg selects `MICRODUCK_STANDUP_PD_ROBOT_CFG if pd_actuators
    # else MICRODUCK_STANDUP_ROBOT_CFG`. That symbol is missing from develop, so
    # this script used to rewrite both references away — which silently ran the
    # BAM voltage plant under a task named JoySmoothPD. It is now defined in
    # microduck_constants.py, so the only job left here is to refuse to continue
    # if the substitution ever creeps back.
    joy_cfg = TREE / "src/mjlab_microduck/tasks/microduck_joy_env_cfg.py"
    if joy_cfg.exists():
        s = joy_cfg.read_text(encoding="utf-8")
        for probe in (
            "import MICRODUCK_STANDUP_ROBOT_CFG,MICRODUCK_STANDUP_PD_ROBOT_CFG",
            "MICRODUCK_STANDUP_PD_ROBOT_CFG if pd_actuators else MICRODUCK_STANDUP_ROBOT_CFG",
        ):
            if probe not in s:
                print(f"  ! joy cfg lost the PD plant selection: {probe!r}")
                return 1
        print("  = joy cfg: PD plant selection intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
