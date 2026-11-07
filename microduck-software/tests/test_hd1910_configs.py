"""Cfg invariants for the HD-1910 (Feetech) replica line.

CPU only: builds cfgs and compiles MuJoCo models, never steps an env.
Mirrors ``microduck_rl-develop/tests/test_velstand_cfg.py`` but locks the
HD-1910-specific failure modes recorded in the project memory:

* Joint-ID remap across the two numbering systems
  (HD-1910 1-15 vs official 20-24 / 30-34). A wrong ``installation.json`` or a
  copied ``plant_spec`` silently shifts every joint and the robot still "runs"
  but with an electrically-valid, physically-wrong mapping.
* Servo collision-geom naming / count (collision integrity for sim2real).
* Reward sign conventions (penalties negative, tracking rewards positive) — a
  flipped sign is invisible until a whole training run is wasted.
* The standup "freezing on back" fix must stay present: the
  ``ground_state_mix`` reverse-curriculum that ramps ``face_up_prob`` 0 -> 0.35.

Requires an HD-1910 plant to be applied first
(``tools/hd1910/apply_to_live.py --plant hd1910|hd1910_kp5|hd1910_kp8|hd1910_ftservo_m6``).
If a non-HD-1910 plant (e.g. xl330) is live, the model/kinematics tests skip.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_configs.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mujoco
import pytest

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

HD1910_PLANTS = {"hd1910", "hd1910_kp5", "hd1910_kp8", "hd1910_ftservo_m6"}


def _live_plant() -> str | None:
    out = subprocess.run(
        [PY, str(REPO / "tools/hd1910/apply_to_live.py"), "--check", "--json"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout).get("detected")
    except Exception:
        return None


LIVE_PLANT = _live_plant()
IS_HD1910 = LIVE_PLANT in HD1910_PLANTS

pytestmark = pytest.mark.skipif(
    not IS_HD1910,
    reason=f"live plant {LIVE_PLANT!r} is not an HD-1910 variant; apply one first",
)

import mjlab_microduck.tasks  # noqa: E402,F401  (side effect: registers tasks)
from mjlab_microduck.robot.microduck_constants import (  # noqa: E402
    MICRODUCK_WALK_ROBOT_CFG,
    get_allcollisions_spec,
    get_standup_spec,
    SERVO_GEOM_SUFFIX,
)

# Canonical HD-1910 actuated joint order, free joint excluded. Locked from the
# live kp8 model on 2026-11-07. Any silent remap across the two joint-ID
# systems (HD-1910 1-15 vs official 20-24/30-34) must fail this assertion.
CANONICAL_ACTUATED_JOINTS = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]


def _joints(spec) -> list[str]:
    m = spec().compile()
    return [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(m.njnt)]


def _actuated(joint_names: list[str]) -> list[str]:
    return [n for n in joint_names if n != "trunk_base_freejoint"]


def _geom_names(model) -> list[str]:
    return [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(model.ngeom)]


# ── Kinematics / joint mapping ────────────────────────────────────────────────

def test_actuated_joint_count_is_14():
    act = _actuated(_joints(MICRODUCK_WALK_ROBOT_CFG.spec_fn))
    assert len(act) == 14, act


def test_walk_joint_order_is_canonical():
    act = _actuated(_joints(MICRODUCK_WALK_ROBOT_CFG.spec_fn))
    assert act == CANONICAL_ACTUATED_JOINTS, (
        "HD-1910 joint order drifted — this is the silent remap the project "
        "memory warns about (two joint-ID numbering systems)."
    )


def test_allcollisions_matches_walk_kinematics():
    a = _joints(get_allcollisions_spec)
    g = _joints(MICRODUCK_WALK_ROBOT_CFG.spec_fn)
    assert a == g, "allcollisions spec joint order diverges from walk spec"


def test_standup_matches_walk_kinematics():
    s = _joints(get_standup_spec)
    g = _joints(MICRODUCK_WALK_ROBOT_CFG.spec_fn)
    assert s == g, "standup spec joint order diverges from walk spec"


# ── Collision integrity ───────────────────────────────────────────────────────

def test_allcollisions_servo_geoms_are_named():
    model = get_allcollisions_spec().compile()
    servo = [n for n in _geom_names(model) if n and n.endswith(SERVO_GEOM_SUFFIX)]
    # 14 servos; one body carries a 15th xl330 housing mesh in the export.
    assert len(servo) >= 14
    for n in servo:
        g = model.geom(n)
        assert g.contype[0] or g.conaffinity[0], f"{n} is not a collision geom"


# ── Cfg builds ────────────────────────────────────────────────────────────────

def test_velocity_cfg_builds():
    from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
        make_microduck_velocity_env_cfg,
    )
    assert make_microduck_velocity_env_cfg() is not None
    assert make_microduck_velocity_env_cfg(play=True) is not None


def test_standup_cfg_builds():
    from mjlab_microduck.tasks.microduck_standup_env_cfg import (
        make_microduck_standup_env_cfg,
    )
    assert make_microduck_standup_env_cfg() is not None


# ── Reward sign conventions (penalties < 0, tracking > 0) ─────────────────────

def test_velocity_reward_signs():
    from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
        make_microduck_velocity_env_cfg,
    )
    cfg = make_microduck_velocity_env_cfg()
    positive = (
        "pose",
        "track_linear_velocity",
        "track_angular_velocity",
        "upright",
        "air_time",
    )
    negative = (
        "foot_slip",
        "self_collisions",
        "dof_pos_limits",
        "action_rate_l2",
    )
    for name in positive:
        assert name in cfg.rewards, f"expected reward term {name!r}"
        assert cfg.rewards[name].weight > 0, f"{name} should be a positive reward"
    for name in negative:
        assert name in cfg.rewards, f"expected reward term {name!r}"
        assert cfg.rewards[name].weight < 0, f"{name} should be a negative penalty"


# ── Standup "freezing on back" fix must stay present ──────────────────────────

def test_standup_has_face_up_recovery_curriculum():
    from mjlab_microduck.tasks.microduck_standup_env_cfg import (
        make_microduck_standup_env_cfg,
    )
    cfg = make_microduck_standup_env_cfg()
    assert "ground_state_mix" in cfg.curriculum, (
        "standup lost the ground_state_mix reverse-curriculum — the anti "
        "'freezing on back' fix (face_up_prob ramp) is gone."
    )
    stages = cfg.curriculum["ground_state_mix"].params["param_stages"]
    # Stage 0 starts at 0 (easy poses first); final stage biases toward the
    # hard back-recovery pose so it gets the most practice.
    assert stages[0]["params"]["face_up_prob"] == 0.0
    assert stages[-1]["params"]["face_up_prob"] > 0.0
