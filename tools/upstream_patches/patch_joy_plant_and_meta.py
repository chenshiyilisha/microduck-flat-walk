"""Re-insert the two joy-related regions no other patch tool covers.

Covers exactly what the trained snapshot adds on top of official b02fdea for:
  - microduck_constants.py: `pd_actuators` XML-position plant (30 lines) +
    `MICRODUCK_STANDUP_PD_ROBOT_CFG` (12 lines) -- the joy PD task selects it
  - export.py: `JOY_FREQUENCY_HZ_DEFAULT` + `joy_metadata_from_cfg` (53 lines)
    + the 3-line call site stamping the 5 joy contract keys onto ONNX exports

Blocks were extracted mechanically from (clean b02fdea -> trained snapshot)
and replayed verbatim; the replay check reproduces the snapshot byte for
byte (see tools/upstream_patches/README.md).

Idempotent: a block whose first line is already present is skipped. A block
whose anchor is missing or ambiguous aborts with exit 1 -- that means the
base is not b02fdea or a sibling patch changed the same region.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TREE = ROOT / "third_party" / "microduck_rl"

# (rel, mode, anchor_lines, text)
BLOCKS = [
    ('src/mjlab_microduck/robot/microduck_constants.py', 'after',
     ['backlash_actuators = BacklashEncoderBamActuatorCfg(**_BAM_ACTUATOR_KWARGS)\n', '\n'],
     '# -- Deployment position servo: the XML\'s own <position kp=0.55 kv=0> actuator --\n# Same joints, same collision set, same torque clip — only the actuator law\n# differs from `actuators`: no voltage loop, no battery sag, no load-dependent\n# friction, no 3-6 ms lag. This is the plant the shipped joy policy was audited\n# in (rc_art/audit_smooth300.json -> victory: mode continuous_joy_smooth_pd_v1,\n# "No servo overrides", feet_peak 18.5 / 20.0 mm against a 24.5 mm target, and\n# actuation-check.json -> every motor limit ±0.6405 N m).\n#\n# Why it is spelled this way\n# -------------------------\n# Upstream\'s joy cfg selects it as\n#   deepcopy(MICRODUCK_STANDUP_PD_ROBOT_CFG if pd_actuators else MICRODUCK_STANDUP_ROBOT_CFG)\n# and that symbol exists only on the patch\'s baseline commit, not on develop.\n# Reconstructing it from the commented-out block above is the faithful reading:\n#   XmlActuatorCfg(target_names_expr=(r".*",), delay_min_lag=0, delay_max_lag=3)\n# `delay_*_lag` is counted in *physics steps*, not control steps — measured\n# dead_ms = 20 ms for the BAM 3..6 case at dt = 1 ms (tools/probe_servo_step.py),\n# so 0..3 here is 0-3 ms, not 0-60 ms.\n#\n# ⚠️ Choosing it is a *plant* decision, not a tuning one. `actuators` (BAM) is\n# the closer model of the HD1910 firmware; this one is what the 18-20 mm\n# reference number was produced in. Train in this one to answer "can the task be\n# learned at all", then re-measure the resulting policy in `actuators` before\n# claiming it transfers (tools/plant.py exists for exactly that comparison).\npd_actuators = XmlActuatorCfg(\n    target_names_expr=(r"^(?!passive_).*",),\n    delay_min_lag=0,\n    delay_max_lag=3,\n)\n\n'),
    ('src/mjlab_microduck/robot/microduck_constants.py', 'before',
     ['# True full-collision model (every part collides, servo housings named — see\n'],
     "# Same robot, driven by the XML position servo instead of the BAM voltage model.\n# Selected by the joy tasks' `pd_actuators=True`; see the note at pd_actuators.\nMICRODUCK_STANDUP_PD_ROBOT_CFG = EntityCfg(\n    spec_fn=get_standup_spec,\n    init_state=HOME_FRAME,\n    collisions=(FULL_COLLISION,),\n    articulation=EntityArticulationInfoCfg(\n        actuators=(pd_actuators,),\n        soft_joint_pos_limit_factor=0.9,\n    ),\n)\n\n"),
    ('src/mjlab_microduck/export.py', 'after',
     ['    checkpoint_iteration: int | None\n'],
     '\n\n# Default of `mdp.joy_phase(frequency=...)`. The joy reward terms in\n# microduck_joy_env_cfg.py pass no override, so this is what training used.\n# It is only a fallback: if a term ever does declare `frequency`, we read that.\nJOY_FREQUENCY_HZ_DEFAULT = 1.15\n\n\ndef joy_metadata_from_cfg(env_cfg) -> dict[str, str]:\n    """The 5 extra ONNX metadata keys an official joy policy carries.\n\n    `get_base_metadata` returns exactly 8 keys, and our exports have exactly\n    those 8 in exactly that order -- so the base half was never the problem.\n    The official `continuous_joy.onnx` carries 5 more, and they are the\n    deployment contract for the *target conditioner*:\n\n        joy_target_alpha        = 0.25\n        joy_target_max_step_rad = 0.08\n        joy_frequency_hz        = 1.15\n        joy_commands            = v1\n        joy_target_conditioner  = v1\n\n    Why this is required and not cosmetic: `JoySmoothPositionAction` filters the\n    joint target during training, so the policy learned to act on a filtered\n    target. A runtime that finds no `joy_target_alpha` has no reason to filter,\n    and would run the policy on an unfiltered target -- trained-with /\n    deployed-without. That is the failure mode the third-party invariant list\n    states verbatim ("Don\'t add EMA filtering without a matched runtime flag").\n\n    Values are read from the live config rather than hardcoded, so they cannot\n    drift away from `JoySmoothPositionActionCfg`. Returns `{}` for every\n    non-joy task, because their `joint_pos` term has no `joy_*` fields.\n    """\n    action_cfg = (getattr(env_cfg, "actions", None) or {}).get("joint_pos")\n    alpha = getattr(action_cfg, "joy_alpha", None)\n    max_step = getattr(action_cfg, "joy_max_step", None)\n    if alpha is None or max_step is None:\n        return {}\n\n    frequency = JOY_FREQUENCY_HZ_DEFAULT\n    for term in (getattr(env_cfg, "rewards", None) or {}).values():\n        declared = (getattr(term, "params", None) or {}).get("frequency")\n        if declared is not None:\n            frequency = declared\n            break\n\n    return {\n        "joy_commands": "v1",\n        "joy_frequency_hz": f"{float(frequency):g}",\n        "joy_target_conditioner": "v1",\n        "joy_target_alpha": f"{float(alpha):g}",\n        "joy_target_max_step_rad": f"{float(max_step):g}",\n    }\n'),
    ('src/mjlab_microduck/export.py', 'after',
     ['    metadata = get_base_metadata(runner.env.unwrapped, run_path=cfg.checkpoint_file)\n'],
     '    # Joy tasks carry 5 extra keys: the target-conditioner contract the robot\n    # runtime needs to reproduce the training-time filter. Empty for all others.\n    metadata.update(joy_metadata_from_cfg(env_cfg))\n'),
]


def apply_block(rel: str, mode: str, anchor: list[str], text: str, path: pathlib.Path) -> bool:
    full = path.read_text(encoding="utf-8")
    first = next(l for l in text.splitlines(keepends=True) if l.strip())
    if first in full:
        print(f"  = {rel}: block present ({first.strip()[:58]!r})")
        return True
    lines = full.splitlines(keepends=True)
    seq = "".join(anchor)
    hits = [i for i in range(len(lines)) if "".join(lines[i:i+len(anchor)]) == seq]
    if len(hits) != 1:
        want = "ambiguous" if len(hits) > 1 else "missing"
        print(f"  !! anchor {want} in {rel}: {anchor[0][:58]!r} ({len(hits)} hits)")
        return False
    at = hits[0] + len(anchor) if mode == "after" else hits[0]
    lines[at:at] = text.splitlines(keepends=True)
    path.write_text("".join(lines), encoding="utf-8")
    print(f"  + {rel}: inserted {text.count(chr(10))} lines {mode} {anchor[0].strip()[:52]!r}")
    return True


def main() -> int:
    rc = 0
    for rel, mode, anchor, text in BLOCKS:
        path = TREE / rel
        if not path.exists():
            print(f"  !! missing {path}")
            rc = 1
            continue
        if not apply_block(rel, mode, anchor, text, path):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
