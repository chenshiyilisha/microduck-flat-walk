# SPDX-License-Identifier: Apache-2.0
"""Headless deployment rehearsal: run the exported ONNX through the robot's own stack.

Why this file exists
--------------------
`check_onnx_parity.py` answers "is the graph the same maths as rsl_rl". It cannot answer
"does the deployed stack still walk", because it never closes the loop and never runs the
actuator model. Upstream's own answer is `scripts/infer_policy.py`, which is exactly that
rehearsal — BAM M6 on XL330, firmware P-loop, voltage sag, friction budget — but its loop is
driven by a MuJoCo viewer window and a terminal key reader (`import termios, tty`), so it
cannot run here: Windows has no termios, and there is no headless switch.

This tool does **not** reimplement any of it. It loads the upstream module and reuses
`load_bam_model`, `load_mujoco_with_bam`, `PolicyInference.get_observations/infer/
apply_action` — the same code the robot's rehearsal uses — and replaces only the outer loop:
no viewer, no keyboard, no wall-clock sleep; fixed conditions in, JSON metrics out.

That distinction matters. A reimplementation would be a second opinion, and two independent
implementations agreeing proves nothing about the one that ships (see
`docs/05-flat-walk.md` §13.2). Reusing upstream keeps this a *measurement* of the real stack.

What it measures, and what it cannot
------------------------------------
One robot, one deterministic initial state. So the numbers are **not** comparable with
`eval_velocity_in_sim.py` (32 parallel envs, frozen command, `vx_median_of_env_means`) —
different instrument, see §12.5. This tool answers a binary question per condition: does the
deployed stack keep walking, or does it collapse. The conditions are the ones training
randomised over, so the interesting answer is at the extremes, not the nominal point:

  nominal      vin 7.4 V, sag 0.1   — training's midpoint
  low_batt     vin 6.5 V, sag 0.2   — both worst ends at once
  high_batt    vin 8.2 V, sag 0.0   — stiffest, no sag
  latency_60   3 control steps of action delay — upstream's 3-6 period envelope

Usage::

  python tools/flat_walk/rehearse_deploy.py \\
      --onnx artifacts/flat_walk/checkpoints/walk_std004_1250.onnx \\
      --cmd-vx 0.4 --seconds 8 --sweep --out out/rehearse_1250.json

Prerequisites that are NOT in this repository
---------------------------------------------
This is a loader, not a standalone simulator. It needs three things that live outside:

  * upstream `microduck_rl`'s `scripts/infer_policy.py`  -> pass `--infer-policy`
    (private submodule here; `.gitmodules` points at an unauthorised repo, see docs §7.0)
  * the `mjlab_microduck` task package (same private submodule) -> supplies the scene XML
    and is what `find_scene()` resolves against, so the asset is the one the policy was
    trained in rather than a lookalike
  * `mujoco` + `numpy` (+ the ONNX runtime that `infer_policy.PolicyInference` uses)

So the claim this tool supports is the §7.0 one: given the same task package and environment,
every number in the output can be recomputed from the `settings` / `protocol` blocks it writes.
It is *not* "clone and run" -- the point of writing that down is that this file cannot be
verified by a reader who lacks the task package, only audited.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pathlib
import statistics as st
import sys
import types

import numpy as np

# --- Fall definition: taken from the task, not chosen here -----------------------------
#
# The rehearsal must call "fallen" the same thing training calls fallen, otherwise its numbers
# describe a different question. Training terminates on `fell_over`, whose body is
# mjlab.envs.mdp.terminations.bad_orientation:
#
#     acos(-projected_gravity_b[:, 2]).abs() > limit_angle
#     limit_angle = 1.2217304763960306 rad = 70.0000 deg
#     (microduck_velocity_env_cfg.py -> cfg.terminations["fell_over"].params)
#
# `tilt_deg` below is exactly `degrees(acos(-g_z))`, so the two are the same quantity and the
# threshold is copied rather than tuned. An earlier version of this file used 60 deg, which
# silently reported "fell" for poses training treats as still-standing.
FALL_TILT_DEG = 70.0
TRAINING_FALL_LIMIT_ANGLE_RAD = 1.2217304763960306

# Height is NOT part of the training fall criterion (training has time_out / fell_over /
# out_of_terrain_bounds / nan_state only). It is kept as a diagnostic and as a NaN-adjacent
# backstop, but it no longer triggers `fell` on its own.
FALL_HEIGHT_M = 0.06
FALL_HEIGHT_TRIGGERS = False

# Why fallen runs must not contribute velocity samples: training ends the episode at
# `fell_over` and resets the env, so no post-fall state ever reaches its statistics. Keeping
# the rollout running after a fall (what this tool used to do) mixes "walking" and "lying on
# the floor twitching" into one mean. Third-party evaluation practice agrees: "Survival counts
# each env's first episode" (KNR-PW/LRT_meldog_RL docs/evaluation.md), and the standard
# convention terminates the episode on fall rather than recording through it.
TRUNCATE_AT_FALL = True

# Conditions = the DR envelope training sampled from (infer_policy.py constants).
# `delay` is in control steps; training configures delay_min_lag=3, delay_max_lag=6 in
# _BAM_ACTUATOR_KWARGS (microduck_constants.py), i.e. 60-120 ms at 50 Hz. Upstream's own
# rehearsal defaults to NO delay, and tests/test_infer_policy_bam.py does not assert it —
# so "nominal" here is *lighter* than training, not equal to it.
CONDITIONS = {
    "nominal": dict(vin=7.4, vin_drop_gain=0.1, delay=0),
    "low_batt": dict(vin=6.5, vin_drop_gain=0.2, delay=0),
    "high_batt": dict(vin=8.2, vin_drop_gain=0.0, delay=0),
    "train_lag3": dict(vin=7.4, vin_drop_gain=0.1, delay=3),
    "train_lag4": dict(vin=7.4, vin_drop_gain=0.1, delay=4),
    "train_lag6": dict(vin=7.4, vin_drop_gain=0.1, delay=6),
}

# What this instrument shares with training, and what it does not. Recorded in the output so
# the next reader cannot mistake a rehearsal number for an evaluation number (§12.5 rule:
# never mix numbers from two instruments).
TRAINING_PARITY = {
    "same": [
        "BAM M6 on xl330 (kt/R/friction budget, kp_fw=200, target_names_expr excludes passive_*)",
        "obs layout 61D: ang_vel3 + proj_grav3 + joint_pos14 + joint_vel14 + last_action14 "
        "+ twist3 + head4 + body6 (verified against the live cfg term order)",
        "joint_pos action scale 1.0 (cfg.actions['joint_pos'].scale)",
        "DEFAULT_POSE == HOME_FRAME.STAND2 (verified elementwise; actuator order == DEFAULT_POSE order)",
        "control 50 Hz = decimation 4 x timestep 0.005; MuJoCo solver iterations 100/50",
        "use_projected_gravity=True (USE_PROJECTED_GRAVITY=True in the task cfg)",
    ],
    "differs": [
        "actuator delay 3-6 steps in training, 0 by default here (upstream --delay is off by "
        "default and untested) -> pass --delay to study it, but see below: it changes the gait",
        "CPU MuJoCo (Newton/implicitfast + stiff friction constraints) vs warp/MJX at train time "
        "-> same model, different solver numerics",
        "training uses collisions=(FULL_COLLISION,): every geom pair collides; the CPU scene keeps "
        "the XML's `self_collision_only` class for the leg shells",
        "friction DR (FrictionDRBamActuatorCfg) is per-env at train time; here it is the fixed XML "
        "value (MuJoCo default sliding mu=1.0)",
        "one robot, deterministic initial state (yaw=0) vs 32 envs with reset_base yaw in (-pi, pi)",
        "no push_by_setting_velocity events here; the eval script drops them too",
    ],
}

INFER_CANDIDATES = (
    "scripts/infer_policy.py",                      # upstream repo root
    ".upstream/microduck_rl-develop/scripts/infer_policy.py",
    "../microduck_rl-develop/scripts/infer_policy.py",
)


def find_infer_policy(explicit: str | None) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"--infer-policy not found: {p}")
        return p
    here = pathlib.Path(__file__).resolve()
    for base in [pathlib.Path.cwd(), here.parent, here.parent.parent, here.parent.parent.parent]:
        for cand in INFER_CANDIDATES:
            p = (base / cand)
            if p.is_file():
                return p.resolve()
    raise SystemExit(
        "cannot locate upstream scripts/infer_policy.py; pass --infer-policy /path/to/"
        "microduck_rl/scripts/infer_policy.py"
    )


def load_upstream(path: pathlib.Path):
    """Import infer_policy even on Windows, without touching the file.

    The module does `import termios, tty` at top level for its terminal key reader. Windows
    has neither. We install inert stubs for exactly those two names before executing the
    module; nothing in the rehearsal path (BAM, PolicyInference, observations) touches them.
    """
    for name in ("termios", "tty"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.TCSANOW = 0
            stub.ICANON = 0
            stub.ECHO = 0
            stub.tcgetattr = lambda *a, **k: []
            stub.tcsetattr = lambda *a, **k: None
            stub.setraw = lambda *a, **k: None
            sys.modules[name] = stub
    spec = importlib.util.spec_from_file_location("microduck_infer_policy", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_scene(mod, explicit: str | None) -> pathlib.Path:
    """The XML infer_policy uses by default, resolved next to the installed package.

    `infer_policy.MICRODUCK_XML` is a path *relative to the microduck_rl repo root*, which is
    fine when you run it from there and useless from anywhere else. Resolve it against the
    installed `mjlab_microduck` package instead — that is the task package the policy was
    trained in, so it is the same asset, not a lookalike.
    """
    if explicit:
        p = pathlib.Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"--scene not found: {p}")
        return p
    import mjlab_microduck

    rel = getattr(mod, "MICRODUCK_XML", "src/mjlab_microduck/robot/microduck/scene.xml")
    # "src/mjlab_microduck/robot/microduck/scene.xml" -> "robot/microduck/scene.xml"
    tail = rel.split("mjlab_microduck/", 1)[-1]
    pkg = pathlib.Path(mjlab_microduck.__file__).resolve().parent.parent
    return pkg / "mjlab_microduck" / tail


def build(mod, scene: pathlib.Path, args, cond):
    """Assemble model + data + BAM controller + policy, mirroring infer_policy.main()."""
    import mujoco

    if args.no_bam:
        # Negative control: the XML's own position servos. This is the plant the *joy* policy
        # was audited against upstream; for the walk policy it is a different physics, which is
        # exactly what makes it a useful control.
        spec = mujoco.MjSpec.from_file(str(scene))
        model = spec.compile()
        model.opt.timestep = args.timestep
        data = mujoco.MjData(model)
        bam_ctrl = None
        names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(model.nu)]
    else:
        bam_model = mod.load_bam_model(args.kp_fw, cond["vin"], None)
        model, data, bam_ctrl, names = mod.load_mujoco_with_bam(
            str(scene), bam_model, args.timestep, cond["vin_drop_gain"], mod.BAM_VIN_MIN
        )
    policy = mod.PolicyInference(
        model, data,
        walking_onnx_path=str(args.onnx),
        action_scale=args.action_scale,
        bam_ctrl=bam_ctrl,
        delay_min_lag=cond["delay"],
        delay_max_lag=cond["delay"],
        new_cmd_obs=True,               # 61D obs: twist(3)+head(4)+body(6)
        use_projected_gravity=not args.raw_accelerometer,
    )

    fid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "trunk_base_freejoint")
    qpos_adr = int(model.jnt_qposadr[fid])
    qvel_adr = int(model.jnt_dofadr[fid])
    data.qpos[qpos_adr + 0] = 0.0
    data.qpos[qpos_adr + 1] = 0.0
    data.qpos[qpos_adr + 2] = args.start_height
    # Reset yaw. Training randomises it over (-pi, pi) per env (reset_base); a single-robot
    # rehearsal starts at a fixed attitude, so a bistable behaviour (the cmd<0.15 dead zone)
    # samples only one branch no matter how long it runs. Sweeping yaw is how a one-robot
    # instrument gets more than one sample of which branch the policy picks.
    hy = math.radians(getattr(args, "yaw_deg", 0.0)) * 0.5
    data.qpos[qpos_adr + 3:qpos_adr + 7] = [math.cos(hy), 0.0, 0.0, math.sin(hy)]
    for i, qi in enumerate(policy.joint_qpos_indices):
        data.qpos[qi] = policy.default_pose[i]
    if bam_ctrl is not None:
        bam_ctrl.reset(data.qpos)
    policy.set_position_targets(policy.default_pose)
    mujoco.mj_forward(model, data)

    policy.set_vel_cmd(args.cmd_vx, args.cmd_vy, args.cmd_wz)
    return model, data, bam_ctrl, policy, names, qpos_adr, qvel_adr


def run_one(mod, scene, args, cond_name, cond):
    import mujoco

    model, data, bam_ctrl, policy, names, qpos_adr, qvel_adr = build(
        mod, scene, args, cond
    )
    decimation = args.decimation
    control_dt = decimation * model.opt.timestep
    n_steps = int(round(args.seconds / control_dt))

    obs0 = policy.get_observations()
    obs_dim = int(obs0.size)
    nu = int(model.nu)

    vx_hist, x_hist, z_hist, tilt_hist, act_hist = [], [], [], [], []
    fell_at = None
    tilt_at_fall = None
    z_at_fall = None
    nan_at = None
    ctrl_path = {"probed": False}
    x0 = float(data.qpos[qpos_adr + 0])
    y0 = float(data.qpos[qpos_adr + 1])

    for k in range(n_steps):
        action = policy.infer()
        policy.apply_action(action)
        # Reference target for the actuator-path probe. set_position_targets() routes either to
        # bam_ctrl.q_target (and then update() writes TORQUE into data.ctrl) or straight into
        # data.ctrl as a joint ANGLE. So `max|ctrl - (default_pose + action*scale)|` separates
        # the two paths with a threshold of ~1e-9 vs O(0.1), instead of the old "vx looks
        # different" test, which could not fail for the right reason.
        target = policy.default_pose + action * policy.action_scale
        for _ in range(decimation):
            if bam_ctrl is not None:
                bam_ctrl.update()
            mujoco.mj_step(model, data)
        if k == 0 and cond["delay"] == 0:
            ctrl_path = {
                "probed": True,
                "max_abs_ctrl_minus_target": float(np.abs(np.asarray(data.ctrl) - target).max()),
                "ctrl_max_abs": float(np.abs(np.asarray(data.ctrl)).max()),
                "bam_flag": bam_ctrl is not None,
            }

        if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
            nan_at = k * control_dt
            break

        # Body-frame linear velocity from the free joint, rotated by the trunk attitude.
        quat = data.qpos[qpos_adr + 3:qpos_adr + 7].astype(np.float32)
        v_world = data.qvel[qvel_adr:qvel_adr + 3].astype(np.float32)
        v_body = policy.quat_rotate_inverse(quat, v_world)
        gz = float(policy.get_projected_gravity()[2])
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, -gz))))
        z = float(data.qpos[qpos_adr + 2])

        # Fall test == training's fell_over (bad_orientation, limit 70 deg). Height is a
        # diagnostic only (FALL_HEIGHT_TRIGGERS), never the criterion.
        fell_now = tilt > FALL_TILT_DEG
        if FALL_HEIGHT_TRIGGERS:
            fell_now = fell_now or z < FALL_HEIGHT_M
        if fell_now:
            if fell_at is None:
                fell_at = k * control_dt
                # The triggering sample is deliberately not appended to tilt_hist, so record
                # its values here: otherwise max_tilt_deg reports the last sample *below* the
                # threshold (66 deg for a 70 deg fall) and looks like the criterion never fired.
                tilt_at_fall = tilt
                z_at_fall = z
            # Do NOT record the sample that triggered the fall, and do NOT keep rolling:
            # training ends the episode here and resets, so post-fall states never enter its
            # statistics. Rolling through a fall is how 0.46 m/s got reported for a run that
            # was on the floor from 2.6 s onward.
            if TRUNCATE_AT_FALL:
                break

        vx_hist.append(float(v_body[0]))
        x_hist.append(float(data.qpos[qpos_adr + 0]))
        z_hist.append(z)
        tilt_hist.append(tilt)
        act_hist.append(float(np.abs(action).max()) if args.track_action else 0.0)

    # Steady-state window: skip the first 25% (startup transient / policy spin-up) OF THE VALID
    # PART. Using the nominal step count here would silently include post-fall samples.
    skip = int(0.25 * len(vx_hist))
    ss_vx = vx_hist[skip:] or vx_hist
    vx_mean = float(st.mean(ss_vx)) if ss_vx else float("nan")
    dx_world = float(data.qpos[qpos_adr + 0]) - x0
    dy_world = float(data.qpos[qpos_adr + 1]) - y0
    # Rotate world displacement into the robot's INITIAL heading. With --yaw-deg != 0 the world
    # x axis is no longer "forward", so quoting dx_world as forward travel would be wrong -- the
    # same body-vs-world mistake that made an earlier analysis read dx_mean ~ 0 as "spins in
    # place" while the body-frame velocity was clean.
    yaw0_deg = float(getattr(args, "yaw_deg", 0.0))
    _c = math.cos(math.radians(yaw0_deg))
    _s = math.sin(math.radians(yaw0_deg))
    dx = _c * dx_world + _s * dy_world
    dy = -_s * dx_world + _c * dy_world
    # End yaw from free-joint quat (wxyz). Explains moves_forward FAIL when body vx>0 but
    # dx_world<0 (robot spun ~180° while still "walking forward" in body frame).
    qw, qx, qy, qz = (float(x) for x in data.qpos[qpos_adr + 3:qpos_adr + 7])
    yaw_end_deg = math.degrees(math.atan2(2.0 * (qw * qz + qx * qy),
                                          1.0 - 2.0 * (qy * qy + qz * qz)))
    yaw_delta_deg = (yaw_end_deg - yaw0_deg + 180.0) % 360.0 - 180.0
    # How much of the requested window actually produced a measurement. A run that fell at
    # 2.6 s reports its velocity from <= 2.6 s of walking, not from 8 s.
    valid_s = (fell_at if fell_at is not None else
               (nan_at if nan_at is not None else len(vx_hist) * control_dt))

    # Negative-control gate, now measurable. Two different questions were conflated before:
    #   (a) is the BAM actuator actually in the control path? -> the ctrl probe above.
    #   (b) how does this policy behave on a different plant?     -> the --no-bam run itself.
    # (a) used to be "vx differs noticeably", but BAM 0.463 vs no-BAM 0.415 is 10% -- inside the
    # spread between conditions, so it could not fail for the right reason.
    if ctrl_path.get("probed"):
        d = ctrl_path["max_abs_ctrl_minus_target"]
        ctrl_path_ok = (d > 1e-3) if ctrl_path["bam_flag"] else (d < 1e-9)
    else:
        ctrl_path_ok = True          # delay>0 shifts the target; not probed on those runs

    gates = {
        "obs_dim_61": obs_dim == 61,
        "actuators_14": nu == 14,
        "no_nan": nan_at is None,
        "stayed_upright": fell_at is None,
        # Sign gate: a policy that tracks +vx must move forward. This is the one check that
        # cannot be passed by a broken obs layout, because a wrong layout usually produces a
        # plausible-looking but wrong action -- and then dz/dx would not follow the command.
        "moves_forward": (dx > 0.02) if args.cmd_vx >= 0.2 else True,
        "covered_window": valid_s >= 0.75 * args.seconds,
        "ctrl_path_matches_flag": ctrl_path_ok,
    }
    # At cmd < 0.2 the documented bistable dead zone (§11) means "does not move" can be the
    # policy's actual answer, not a broken obs layout. The sign gate exists to catch the latter,
    # so it is only applied where forward motion is expected; below that it is recorded, not
    # failed. (Measured here: cmd 0.12/0.15 stand still, cmd 0.20 walks at 68% of command.)
    not_applicable = []
    if args.cmd_vx < 0.2:
        not_applicable.append("moves_forward")

    return {
        "condition": cond_name,
        "settings": dict(cond, kp_fw=args.kp_fw, action_scale=args.action_scale,
                         timestep=args.timestep, decimation=decimation,
                         control_hz=round(1.0 / control_dt, 3),
                         start_height=args.start_height, yaw_deg=getattr(args, "yaw_deg", 0.0),
                         bam=bam_ctrl is not None),
        "command": {"vx": args.cmd_vx, "vy": args.cmd_vy, "wz": args.cmd_wz},
        "shape": {"obs_dim": obs_dim, "nu": nu, "actuator_names": names},
        # Measured window: velocity/displacement below cover `valid_s` seconds, not `seconds`.
        # A run that fell at 2.6 s has a 0.46 m/s figure computed from 2.6 s of walking; quoting
        # it next to an 8 s number is the mistake this field exists to prevent.
        "window": {"requested_s": args.seconds, "valid_s": valid_s,
                   "truncated_by_fall": bool(fell_at is not None and TRUNCATE_AT_FALL),
                   "control_steps": len(vx_hist),
                   "tilt_at_fall_deg": tilt_at_fall,
                   "z_at_fall": z_at_fall},
        "speed": {
            "vx_mean_steady": vx_mean,
            "vx_p50_steady": float(st.median(ss_vx)) if ss_vx else float("nan"),
            "ratio_vs_cmd": (vx_mean / args.cmd_vx) if args.cmd_vx else None,
            "vx_first_second": float(st.mean(vx_hist[:max(1, int(1.0 / control_dt))])),
            # Survivorship bias: a fallen run's mean is computed only over the sub-window in
            # which it was still upright, so it is systematically HIGHER than an equally
            # configured run that survived (measured: low_batt 0.539 vs nominal 0.463).
            # Truncation removes post-fall dilution; it does not make the number quotable.
            "comparable": fell_at is None,
            "note": None if fell_at is None else
                    f"NOT comparable: fell at {fell_at:.2f}s, value covers only the pre-fall "
                    f"window (survivorship bias inflates it)",
        },
        "displacement": {"dx_body": dx, "dy_body": dy,
                         "dx_world": dx_world, "dy_world": dy_world},
        "heading": {
            "yaw0_deg": yaw0_deg,
            "yaw_end_deg": yaw_end_deg,
            "yaw_delta_deg": yaw_delta_deg,
            "note": "moves_forward uses dx_body (initial heading). If vx_body>0 but "
                    "dx_world<0, check yaw_delta (~±180 = turned around).",
        },
        "stability": {
            "fell_at_s": fell_at,
            "fell": fell_at is not None,
            "fall_criterion": f"tilt > {FALL_TILT_DEG:g} deg (== training fell_over limit_angle "
                              f"{TRAINING_FALL_LIMIT_ANGLE_RAD:.10f} rad)",
            "nan_at_s": nan_at,
            "min_height": float(min(z_hist)) if z_hist else None,
            "final_height": float(z_hist[-1]) if z_hist else None,
            "max_tilt_deg": float(max(tilt_hist)) if tilt_hist else None,
            "mean_abs_tilt_deg": float(st.mean([abs(t) for t in tilt_hist])),
        },
        "ctrl_path": ctrl_path,
        "action": {
            "p95_abs_max": float(np.percentile(act_hist, 95)) if args.track_action and act_hist else None,
        },
        "gates": gates,
        "not_applicable": not_applicable,
        "failed": [k for k, v in gates.items() if not v and k not in not_applicable],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", required=True, help="exported policy graph (obs 61 -> act 14)")
    ap.add_argument("--cmd-vx", type=float, default=0.4)
    ap.add_argument("--cmd-vy", type=float, default=0.0)
    ap.add_argument("--cmd-wz", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=8.0, help="rehearsal length per condition")
    ap.add_argument("--sweep", action="store_true",
                    help="run all four training-DR conditions instead of just --condition")
    ap.add_argument("--condition", default="nominal", choices=sorted(CONDITIONS),
                    help="single condition when --sweep is absent")
    ap.add_argument("--vin", type=float, default=None, help="override battery voltage [V]")
    ap.add_argument("--vin-drop-gain", type=float, default=None, help="override sag gain [V/Nm]")
    ap.add_argument("--delay", type=int, default=None, help="override action delay [control steps]")
    ap.add_argument("--kp-fw", type=float, default=None, help="firmware P gain (default: upstream 200)")
    ap.add_argument("--action-scale", type=float, default=1.0)
    ap.add_argument("--decimation", type=int, default=4, help="physics steps per control step (4 -> 50 Hz)")
    ap.add_argument("--timestep", type=float, default=0.005, help="physics timestep [s]")
    ap.add_argument("--start-height", type=float, default=0.125, help="trunk z at reset [m]")
    ap.add_argument("--yaw-deg", type=float, default=0.0,
                    help="initial yaw [deg]. Training randomises yaw over (-pi, pi) per env "
                         "(reset_base), so a single fixed yaw samples only one branch of any "
                         "bistable behaviour -- sweep this to get more than one sample.")
    ap.add_argument("--raw-accelerometer", action="store_true",
                    help="feed raw accelerometer instead of projected gravity (training uses "
                         "projected gravity: USE_PROJECTED_GRAVITY=True)")
    ap.add_argument("--no-bam", action="store_true",
                    help="use the XML position actuators instead of BAM (negative control)")
    ap.add_argument("--track-action", action="store_true", help="record |action| p95")
    ap.add_argument("--infer-policy", default=None, help="path to upstream scripts/infer_policy.py")
    ap.add_argument("--scene", default=None, help="override the MuJoCo scene XML")
    ap.add_argument("--out", default=None, help="write JSON here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    onnx = pathlib.Path(args.onnx).expanduser().resolve()
    if not onnx.is_file():
        raise SystemExit(f"--onnx not found: {onnx}")
    args.onnx = onnx
    args.kp_fw = 200.0 if args.kp_fw is None else args.kp_fw
    if args.no_bam:
        args.no_bam_requested = True

    infer_path = find_infer_policy(args.infer_policy)
    mod = load_upstream(infer_path)
    if args.no_bam:
        args.kp_fw = mod.BAM_KP_FW
    scene = find_scene(mod, args.scene)
    if not scene.is_file():
        raise SystemExit(f"scene XML not found: {scene}")

    if args.sweep:
        todo = [(k, dict(v)) for k, v in CONDITIONS.items()]
    else:
        todo = [(args.condition, dict(CONDITIONS[args.condition]))]
    for name, cond in todo:
        if args.vin is not None:
            cond["vin"] = args.vin
        if args.vin_drop_gain is not None:
            cond["vin_drop_gain"] = args.vin_drop_gain
        if args.delay is not None:
            cond["delay"] = args.delay

    if not args.quiet:
        print(f"infer_policy : {infer_path}")
        print(f"scene        : {scene}")
        print(f"onnx         : {onnx}")
        print(f"conditions   : {[n for n, _ in todo]}")
        print()

    runs = []
    for name, cond in todo:
        label = name + ("+no_bam" if args.no_bam else "")
        r = run_one(mod, scene, args, label, cond)
        runs.append(r)
        if not args.quiet:
            g = r["gates"]
            vx_s = (f"vx={r['speed']['vx_mean_steady']:.4f}" if r["speed"]["comparable"]
                    else "vx=n/a(fell)")
            t = r["window"]["tilt_at_fall_deg"]
            tilt_s = f"tilt={t:.1f}deg" if t is not None else f"tilt_max={r['stability']['max_tilt_deg']:.1f}deg"
            yaw_d = r.get("heading", {}).get("yaw_delta_deg")
            yaw_s = f"yawΔ={yaw_d:+.0f}deg" if yaw_d is not None else "yawΔ=?"
            print(f"[{r['condition']:>18}] obs={r['shape']['obs_dim']} nu={r['shape']['nu']} "
                  f"{vx_s} "
                  f"dx_body={r['displacement']['dx_body']:+.3f} "
                  f"dx_w={r['displacement']['dx_world']:+.3f} "
                  f"{yaw_s} "
                  f"valid={r['window']['valid_s']:.2f}/{r['window']['requested_s']:.0f}s "
                  f"{tilt_s} "
                  f"fell={'Y@%.2fs' % r['stability']['fell_at_s'] if r['stability']['fell'] else 'n'} "
                  f"failed={r['failed']}")

    payload = {
        "tool": "rehearse_deploy",
        "onnx": str(onnx),
        "infer_policy": str(infer_path),
        "scene": str(scene),
        "training_parity": TRAINING_PARITY,
        "protocol": {
            "note": "single robot, deterministic initial state -> NOT comparable with the "
                    "32-env eval_velocity_in_sim.py numbers (different instrument).",
            "fall_criterion": f"tilt > {FALL_TILT_DEG:g} deg == training fell_over "
                              f"(bad_orientation, limit_angle={TRAINING_FALL_LIMIT_ANGLE_RAD:.10f} rad). "
                              "Height does not trigger a fall.",
            "truncate_at_fall": TRUNCATE_AT_FALL,
            "truncate_reason": "training terminates the episode on fell_over and resets, so no "
                               "post-fall state enters its statistics; rolling through a fall "
                               "fabricates a velocity for a robot that is on the floor.",
            "window": "speed/displacement cover valid_s seconds = min(requested, fell_at)",
            "steady_window": "last 75% of the VALID control steps",
        },
        "runs": runs,
        "all_gates_pass": all(not r["failed"] for r in runs),
    }
    if args.out:
        out = pathlib.Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        if not args.quiet:
            print(f"\nwrote {out}")
    if not args.quiet:
        print(f"\nall_gates_pass = {payload['all_gates_pass']}")
    return 0 if payload["all_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
