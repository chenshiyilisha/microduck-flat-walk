"""Enable bilateral (left-right) mirror data augmentation for the joy task.

WHY
---
`tools/probe_phase_profile.py` measured the failure as a one-leg march, not as
"both feet too low":

    phase   left      right
     0.02  20.09 mm   0.45 mm
     0.98  18.47 mm   0.56 mm
    left  r(sin p) = +0.301      right r(sin p) = -0.220

The left foot tracks the clock; the right foot is pressed to the floor and
carries the load, doing the *opposite* of what the clock asks. And every env
starts at phase 0 (`episode_length_buf` resets to 0), so the left leg is always
the first to swing -- a systematic, not a stochastic, bias.

PhoneBot (arXiv 2610.08737) reports the identical gait ("left foot leading and
the right foot supporting") on checkpoints trained *without* mirroring and
states it is an avoidable bias: "after this augmentation is enabled, the walk no
longer depends on a single support leg".

WHAT
----
Nothing in the reward, the target height or the curriculum changes. The only
change is that every collected transition is paired with its sagittal mirror,
so the batch contains both left-leading and right-leading samples with equal
weight. rsl_rl already implements the plumbing (`symmetry_cfg` + a
`data_augmentation_func`); `mjlab_microduck/tasks/symmetry.py` already has the
permutation/sign tables. Both were written for the 61-D layout.

THE TRAP THIS PATCH FIXES
-------------------------
Adding the 2-D gait clock (`tools/patch_joy_gait_clock.py`) takes the actor obs
from 61 to 63 dims. The old `_OBS_PERM` has exactly 61 entries, so
`actor_orig[:, _OBS_PERM]` silently returns a 61-wide tensor -- the gait clock
would be *dropped*, and the shape error would surface (if at all) far away, in
the actor forward pass. Measured layout (verified against
`observation_manager._group_obs_term_{names,dim}`):

    [0:3]   base_ang_vel     [48:51] command
    [3:6]   projected_gravity[51:55] head_command
    [6:20]  joint_pos        [55:61] body_command
    [20:34] joint_vel        [61:63] gait_clock   <-- new
    [34:48] actions

and the gait clock must be mirrored as (sin, cos) -> (-sin, -cos), i.e. a phase
shift of +pi, NOT left unchanged. Reason: mirroring swaps which leg is in swing,
and at phase p+pi the *other* leg is the one the clock asks for. Keeping the
clock unchanged would hand the policy two contradictory labels for the same
phase ("at sin p > 0 lift the left foot" and "at sin p > 0 lift the right
foot"), which is exactly the bias this patch is meant to remove.

The width guard added below makes any future observation change fail loudly
instead of silently truncating.

USAGE
-----
    python tools/patch_joy_symmetry.py          # apply (idempotent)
    MICRODUCK_JOY_SYMMETRY=1 bash tools/train_joy.sh smooth 2048 600 <name>
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

SYM_TARGETS = [
    ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/symmetry.py",
    ROOT / "third_party/microduck_rl/src/mjlab_microduck/tasks/symmetry.py",
]
CFG_TARGETS = [
    ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
    ROOT / "third_party/microduck_rl/src/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
]

# --- symmetry.py edits -----------------------------------------------------

PERM_OLD = """    + [55, 56, 57, 58, 59, 60]          # body command
)"""
PERM_NEW = """    + [55, 56, 57, 58, 59, 60]          # body command
    + [61, 62]                          # gait_clock (TWO dims MUST be here)
)"""

SIGN_OLD = """    + [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]  # body: negate y, roll, yaw
)"""
SIGN_NEW = """    + [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]  # body: negate y, roll, yaw
    # gait_clock (sin p, cos p): negate BOTH = phase shift by +pi. Mirroring
    # swaps which leg is in swing, and at p+pi the clock asks for the other leg,
    # so the mirrored sample is only label-consistent if the clock moves too.
    # Leaving it unchanged would teach "at sin p>0 lift the right foot" as
    # well as "...lift the left foot", i.e. the exact bias we are removing.
    + [-1.0, -1.0]
)"""

GUARD_OLD = """        actor_orig: torch.Tensor = obs["actor"]  # [B, 51]
        obs_perm, obs_sign, _, _ = _get_tensors(actor_orig.device)"""
GUARD_NEW = """        actor_orig: torch.Tensor = obs["actor"]
        # Fail loudly if the observation layout changed under us. Without this,
        # advanced indexing with a short permutation silently TRUNCATES the
        # observation instead of erroring here.
        if actor_orig.shape[-1] != len(_OBS_PERM):
            raise ValueError(
                f"microduck symmetry: actor obs is {actor_orig.shape[-1]}-D but "
                f"_OBS_PERM has {len(_OBS_PERM)} entries. Update the permutation/"
                f"sign tables in {__file__} for the new layout before enabling "
                f"symmetry (see tools/patch_joy_symmetry.py)."
            )
        obs_perm, obs_sign, _, _ = _get_tensors(actor_orig.device)"""

# --- microduck_joy_env_cfg.py edits ---------------------------------------

IMPORT_OLD = "from copy import deepcopy"
IMPORT_NEW = "import os\nfrom copy import deepcopy"

ANCHOR = "MicroduckJoySmoothPdRlCfg.algorithm.learning_rate=.0002"

SYM_BLOCK = """MicroduckJoySmoothPdRlCfg.algorithm.learning_rate=.0002
# ---- Bilateral mirror data augmentation (off unless asked for) ------------
# Symptom it targets (tools/probe_phase_profile.py, checkpoint model_400):
# a ONE-LEG march. Left foot 20 mm at the start of its own swing window, right
# foot pressed to 0.45 mm carrying the whole episode, r(sin p) = -0.220 -- the
# right leg does the opposite of what the clock asks. Every env starts at
# phase 0, so the left leg is always first: a systematic bias.
# PhoneBot (arXiv 2610.08737) reports the same gait ("left foot leading and the
# right foot supporting") for checkpoints trained without mirroring and shows it
# disappears once the collected batch is mirrored.
# Data augmentation only (use_mirror_loss stays False) so this remains a single
# variable against the joy_clock run. See tools/patch_joy_symmetry.py.
# NOTE: symmetry_cfg lives on .algorithm (PpoWithSymmetryCfg), not on the
# top-level RlCfg. Setting it on the top-level object silently does nothing --
# dataclasses accept the attribute and PPO never reads it.
if os.getenv('MICRODUCK_JOY_SYMMETRY','0')=='1':
    MicroduckJoySmoothPdRlCfg.algorithm.symmetry_cfg={
        'use_data_augmentation':True,
        'use_mirror_loss':False,
        'mirror_loss_coeff':0.5,
        'data_augmentation_func':'mjlab_microduck.tasks.symmetry.microduck_vel_symmetry',
    }"""


def swap(text: str, old: str, new: str, what: str) -> str:
    if new in text:
        print(f"  = {what}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"  ! {what}: anchor not found, refusing to guess")
    print(f"  > {what}: patched")
    return text.replace(old, new, 1)


def verify_tables(path: pathlib.Path) -> None:
    """Import the freshly written module and check the tables are coherent."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_sym_check_{abs(hash(path))}", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # tensordict/mjlab imports inside the module are heavy but available.
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    perm, sign = mod._OBS_PERM, mod._OBS_SIGN
    assert len(perm) == len(sign) == 63, f"len(perm)={len(perm)} len(sign)={len(sign)}"
    assert sorted(perm) == list(range(63)), "permutation is not a bijection over 63 dims"
    assert perm[61] == 61 and perm[62] == 62, "gait_clock must not be permuted"
    assert sign[61] == -1.0 and sign[62] == -1.0, "gait_clock must be negated"
    print(f"  > verified {path.name}: |perm|={len(perm)} bijective, gait_clock negated")


def main() -> int:
    print(f"root {ROOT}")
    print("symmetry.py:")
    for p in SYM_TARGETS:
        if not p.exists():
            print(f"  ! {p} missing, skipped")
            continue
        txt = p.read_text(encoding="utf-8")
        txt = swap(txt, PERM_OLD, PERM_NEW, f"{p.parent.parent.parent.name}/{p.name} perm")
        txt = swap(txt, SIGN_OLD, SIGN_NEW, f"{p.parent.parent.parent.name}/{p.name} sign")
        txt = swap(txt, GUARD_OLD, GUARD_NEW, f"{p.parent.parent.parent.name}/{p.name} guard")
        p.write_text(txt, encoding="utf-8")
        verify_tables(p)

    print("joy env cfg:")
    for p in CFG_TARGETS:
        if not p.exists():
            print(f"  ! {p} missing, skipped")
            continue
        txt = p.read_text(encoding="utf-8")
        if "MICRODUCK_JOY_SYMMETRY" in txt:
            # Migrate the first draft, which set the field on the top-level RlCfg.
            if "MicroduckJoySmoothPdRlCfg.symmetry_cfg={" in txt:
                txt = txt.replace("MicroduckJoySmoothPdRlCfg.symmetry_cfg={",
                                  "MicroduckJoySmoothPdRlCfg.algorithm.symmetry_cfg={", 1)
                p.write_text(txt, encoding="utf-8")
                print(f"  > {p.name}: migrated to .algorithm.symmetry_cfg")
            else:
                print(f"  = {p.parent.parent.parent.name}/{p.name}: already applied")
            continue
        txt = swap(txt, IMPORT_OLD, IMPORT_NEW, f"{p.name} import os")
        txt = swap(txt, ANCHOR, SYM_BLOCK, f"{p.name} symmetry_cfg")
        p.write_text(txt, encoding="utf-8")

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
