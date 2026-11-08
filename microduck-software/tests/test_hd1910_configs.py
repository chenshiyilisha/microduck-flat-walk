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

Plant-independence (no environmental false-green)
-------------------------------------------------
These invariants describe the HD-1910 *robot* (kinematics, collision geoms,
reward signs, standup curriculum). ``apply_to_live`` only swaps the actuator
``_BAM_ACTUATOR_KWARGS`` block (json_path / kp_fw / motor_name) — it never
touches the robot XML or the env-cfg reward/curriculum definitions. So the tests
do NOT depend on which plant is currently "live":

* The kinematic tests load each HD-1910 plant's constants **in isolation**
  (``_load_constants_for_plant``), straight from the *installed package's*
  source (``_live_constants_path``), without mutating the live site-packages
  file. They therefore verify the HD-1910 robot on any host where the training
  stack is installed, regardless of ``--plant`` choice. Pass18 replaced a
  hard-coded ``<repo>/.venv-mjlab/...`` path that made all 21 of them fail in
  a clean checkout even when ``mjlab_microduck`` WAS importable.
* The env-cfg tests assert plant-independent reward/curriculum definitions and
  run unconditionally (the env-cfg module is identical across plants within this
  fork).

This replaces the old blanket ``skipif(not IS_HD1910)`` that silently skipped
the whole file whenever a non-HD-1910 plant (e.g. xl330) was live — the tests
then reported green while never having verified anything. The only remaining
skip is genuine: when ``mjlab_microduck`` itself is not importable.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_configs.py -q
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The HD-1910 robot config is produced by swapping a single kwargs block inside
# the live microduck_constants.py. We load it directly from source so the test
# never depends on which plant is currently applied on this machine.
sys.path.insert(0, str(REPO / "tools" / "hd1910"))

# Every HD-1910 variant must produce the SAME kinematics — switching kp_fw
# (P3<->P8) or the params JSON must not silently reshuffle joints or geoms.
HD1910_PLANTS = ["hd1910", "hd1910_kp5", "hd1910_kp8", "hd1910_ftservo_m6"]


def _live_constants_path() -> Path:
    """Locate microduck_constants.py through the INSTALLED package.

    Pass18: `plant_spec.LIVE_CONSTANTS` hard-codes
    `<repo>/.venv-mjlab/Lib/site-packages/...`. That path exists on the
    developer's machine but not in a `git archive` clean checkout, so every
    kinematic test died with FileNotFoundError while still looking like a
    "checkout problem". The invariant under test is the installed training
    stack's source, so resolve it via importlib instead of guessing a layout.
    """
    spec = importlib.util.find_spec("mjlab_microduck")
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError("mjlab_microduck package not importable")
    pkg = Path(next(iter(spec.submodule_search_locations)))
    path = pkg / "robot" / "microduck_constants.py"
    if not path.is_file():
        raise FileNotFoundError(f"no microduck_constants.py under {pkg}")
    return path


def _mjlab_importable() -> tuple[bool, str]:
    try:
        import mjlab_microduck.tasks  # noqa: F401  (side effect: registers tasks)
        live = _live_constants_path()
        # _load_constants_for_plant writes a temp module next to the real one.
        if not os.access(live.parent, os.W_OK):
            return False, f"cannot write temp constants next to {live}"
    except Exception as e:  # pragma: no cover - depends on install state
        return False, f"{type(e).__name__}: {e}"
    return True, ""


_MJLAB_OK, _MJLAB_ERR = _mjlab_importable()
pytestmark = pytest.mark.skipif(
    not _MJLAB_OK,
    reason=f"mjlab_microduck not importable ({_MJLAB_ERR}); install the venv first",
)


def _load_constants_for_plant(plant: str):
    """Load a fresh microduck_constants module with ``plant``'s actuator kwargs
    injected, WITHOUT mutating the live site-packages file.

    The robot XML paths and spec functions live in the shared template *outside*
    the kwargs block, so they are identical to the live file; only the actuator
    params differ. Writing the temp module next to the real one lets ``_ROBOT_DIR``
    (derived from ``__file__``) resolve to the real robot XML. The temp file and
    any bytecode are always cleaned up.
    """
    from apply_to_live import _find_kwargs_span
    from plant_spec import kwargs_block

    live = _live_constants_path()
    src = live.read_text(encoding="utf-8")
    block = kwargs_block(plant) + "\n"
    start, end = _find_kwargs_span(src)
    new = src[:start] + block + src[end:]
    tmp = live.parent / f"_consts_{plant}_{os.getpid()}.py"
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    tmp.write_text(new, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(
            f"_hd1910_consts_{plant}", str(tmp)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev_dont_write
        try:
            tmp.unlink()
        except OSError:
            pass
    return mod


def _joints(spec_fn) -> list[str]:
    """Compile a spec *function* (e.g. ``mod.get_walk_spec``) and return its
    joint names. The function is passed, not called, so callers pick which
    spec (walk / allcollisions / standup) they want to inspect."""
    import mujoco

    m = spec_fn().compile()
    return [
        mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(m.njnt)
    ]


def _actuated(joint_names: list[str]) -> list[str]:
    return [n for n in joint_names if n != "trunk_base_freejoint"]


def _geom_names(model) -> list[str]:
    import mujoco

    return [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i)
        for i in range(model.ngeom)
    ]


# Canonical HD-1910 actuated joint order, free joint excluded. Locked from the
# live kp8 model on 2026-11-07. Any silent remap across the two joint-ID
# systems (HD-1910 1-15 vs official 20-24/30-34) must fail this assertion.
CANONICAL_ACTUATED_JOINTS = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]


# ── Kinematics / joint mapping (plant-isolated, parametrized) ────────────────

@pytest.mark.parametrize("plant", HD1910_PLANTS)
def test_actuated_joint_count_is_14(plant):
    mod = _load_constants_for_plant(plant)
    act = _actuated(_joints(mod.get_walk_spec))
    assert len(act) == 14, (plant, act)


@pytest.mark.parametrize("plant", HD1910_PLANTS)
def test_walk_joint_order_is_canonical(plant):
    mod = _load_constants_for_plant(plant)
    act = _actuated(_joints(mod.get_walk_spec))
    assert act == CANONICAL_ACTUATED_JOINTS, (
        f"{plant}: HD-1910 joint order drifted — this is the silent remap the "
        "project memory warns about (two joint-ID numbering systems)."
    )


@pytest.mark.parametrize("plant", HD1910_PLANTS)
def test_allcollisions_matches_walk_kinematics(plant):
    mod = _load_constants_for_plant(plant)
    a = _joints(mod.get_allcollisions_spec)
    g = _joints(mod.get_walk_spec)
    assert a == g, f"{plant}: allcollisions spec joint order diverges from walk"


@pytest.mark.parametrize("plant", HD1910_PLANTS)
def test_standup_matches_walk_kinematics(plant):
    mod = _load_constants_for_plant(plant)
    s = _joints(mod.get_standup_spec)
    g = _joints(mod.get_walk_spec)
    assert s == g, f"{plant}: standup spec joint order diverges from walk"


@pytest.mark.parametrize("plant", HD1910_PLANTS)
def test_allcollisions_servo_geoms_are_named(plant):
    mod = _load_constants_for_plant(plant)
    model = mod.get_allcollisions_spec().compile()
    servo = [n for n in _geom_names(model) if n and n.endswith(mod.SERVO_GEOM_SUFFIX)]
    # 14 servos; one body carries a 15th xl330 housing mesh in the export.
    assert len(servo) >= 14
    for n in servo:
        g = model.geom(n)
        assert g.contype[0] or g.conaffinity[0], f"{n} is not a collision geom"


def test_joint_order_identical_across_hd1910_plants():
    """Switching kp_fw / params JSON must NOT reshuffle joints or geoms.

    This is the real guard against the 'apply a different plant and the robot
    silently remaps' failure mode — and it is exactly the invariant the old
    blanket skip hid (the tests never ran on a machine whose live plant was
    anything but HD-1910).
    """
    orders = {}
    for plant in HD1910_PLANTS:
        mod = _load_constants_for_plant(plant)
        orders[plant] = _actuated(_joints(mod.get_walk_spec))
    ref = orders[HD1910_PLANTS[0]]
    for plant, o in orders.items():
        assert o == ref, f"joint order differs for {plant}: {o} != {ref}"


# ── Cfg builds (plant-independent; run unconditionally) ──────────────────────

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
