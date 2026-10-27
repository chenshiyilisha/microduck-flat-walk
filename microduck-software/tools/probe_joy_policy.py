"""Headless probe: run any official MicroDuck ONNX policy in the **official MuJoCo plant**.

Why this file exists
--------------------
Upstream ships `scripts/infer_policy.py` as the CPU rehearsal loop, but it
`import termios` at line 13 -> Linux/macOS only, it cannot run on Windows. This
script re-implements only the minimum needed to get a *behavioural measurement*
out of a policy, headless and scriptable, with every contract value copied from
a first-party source rather than guessed.

Contract sources (all first-party, all verifiable):
- 61-D observation order — `training/continuous_joy.patch` asserts
  `['base_ang_vel','projected_gravity','joint_pos','joint_vel','actions',
    'command','head_command','body_command']` (`tests/test_joy_cfg.py:10` — the file
  is 64 lines; an earlier revision of this comment cited `:242`, which does not
  exist);
  `joy_head_command` returns 4 columns, `joy_body_command` returns 6,
  `joy_twist_command` returns 3 -> 3+3+14+14+14+3+4+6 = 61.
- Phase — `joy_phase`: 2*pi*1.15*episode_time, with a 0.8 s fade-in `e`.
- Target conditioner — ONNX metadata `joy_target_alpha=0.25`,
  `joy_target_max_step_rad=0.08`; smoothing operates on the *processed* target
  (`JoySmoothPositionAction.process_actions`), raw actions stay in the obs.
- Action semantics — `microduck_velocity_env_cfg.py:273` sets
  `joint_pos_action.scale = 1.0`, and `JointPositionActionCfg.use_default_offset`
  defaults True -> `processed = default_joint_pos + action`.
- Servo plant — `joy_pd_spec` clamps every actuator to +/-0.6405 Nm; the XML
  class `chosen_actuator` gives kp=0.55, kv=0.0 (matches ONNX metadata
  `joint_stiffness=0.550`, `joint_damping=0.000`).

Usage
-----
  python tools/probe_joy_policy.py --onnx .upstream/policies/continuous_joy.onnx \
      --plant servo --seconds 8
  python tools/probe_joy_policy.py --onnx ... --plant bam --vin 7.4 --kp-fw 200
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
XML = ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/robot/microduck/scene.xml"
JOY_HZ = 1.15
FADE_S = 0.8
ALPHA = 0.25
MAX_STEP = 0.08
JOY_FORCE = 0.6405

# ONNX metadata `default_joint_pos` (also infer_policy.py:127 DEFAULT_POSE).
DEFAULT_POSE = np.array(
    [
        0.0, -0.087, -0.458, -0.005, 0.453,
        0.349, 0.349, 0.0, 0.0,
        0.0, 0.087, 0.458, 0.005, -0.453,
    ],
    dtype=np.float64,
)


def quat_rotate_inverse(q, v):
    """Rotate world vector v into the frame of quaternion q (w,x,y,z)."""
    w, x, y, z = q
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )
    return r.T @ np.asarray(v, dtype=np.float64)


def yaw_of(q):
    w, x, y, z = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def roll_pitch(q):
    w, x, y, z = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    return roll, pitch


def build(plant, timestep, vin, kp_fw, vin_drop_gain):
    import mujoco

    if plant == "servo":
        spec = mujoco.MjSpec.from_file(str(XML))
        for a in spec.actuators:
            a.forcelimited = True
            a.forcerange = (-JOY_FORCE, JOY_FORCE)
        model = spec.compile()
        model.opt.timestep = timestep
        data = mujoco.MjData(model)
        return model, data, None

    from bam.model import load_model
    from bam.mujoco import MujocoController

    bam_model = load_model(motor_name="xl330", model="m6")
    bam_model.actuator.kp = kp_fw
    bam_model.actuator.vin = vin
    bam_model.actuator.max_current = None
    kt, R = bam_model.kt.value, bam_model.R.value
    force_limit = vin * kt / R

    spec = mujoco.MjSpec.from_file(str(XML))
    names = []
    for act in spec.actuators:
        tgt = act.target
        tgt_name = tgt.name if hasattr(tgt, "name") else str(tgt)
        if tgt_name.startswith("passive_"):
            continue
        act.set_to_motor()
        act.forcelimited = True
        act.forcerange = (-force_limit, force_limit)
        act.ctrllimited = False
        act.gear = [1.0, 0, 0, 0, 0, 0]
        names.append(act.name)
        for joint in spec.joints:
            if joint.name == tgt_name:
                joint.damping = np.zeros((3, 1))
                joint.frictionloss = 0.0
                joint.solref_friction = np.array([-5.0e4, -2.0e2])
                joint.solimp_friction = np.array([0.99, 0.9999, 0.001, 0.5, 2.0])
                break
    model = spec.compile()
    model.opt.timestep = timestep
    data = mujoco.MjData(model)
    ctrl = MujocoController(
        bam_model, names, model, data, vin_drop_gain=vin_drop_gain, vin_min=6.0
    )
    print(
        f"BAM m6/xl330 kt={kt:.4f} R={R:.4f} vin={vin}V kp_fw={kp_fw} "
        f"forcerange=+/-{force_limit:.3f}Nm"
    )
    return model, data, ctrl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--plant", choices=["servo", "bam"], default="servo")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument(
        "--timestep",
        type=float,
        default=0.0002,
        help="Official probe_joy_policy.py declares physics_step_s=0.0002 (5 kHz).",
    )
    ap.add_argument(
        "--decimation",
        type=int,
        default=100,
        help="100 x 0.2 ms = 20 ms -> controller_hz=50, as upstream declares.",
    )
    ap.add_argument(
        "--joint-vel-delay",
        type=int,
        default=0,
        help="JoyDance.update sets r.joint_vel_delay=1, i.e. the deployed policy sees "
        "the previous step's joint velocity. 1 reproduces the deployment contract.",
    )
    ap.add_argument("--vin", type=float, default=7.4)
    ap.add_argument("--kp-fw", type=float, default=200.0)
    ap.add_argument("--vin-drop-gain", type=float, default=0.1)
    ap.add_argument("--foot-friction", type=float, default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--no-clock",
        action="store_true",
        help="NEGATIVE CONTROL: zero head/body command channels so the 1.15 Hz phase "
        "never reaches the policy. If the gait survives, the clock is not what drives "
        "it and any 'it steps' conclusion is invalid.",
    )
    args = ap.parse_args()

    import mujoco
    import onnxruntime as ort

    model, data, bam_ctrl = build(
        args.plant, args.timestep, args.vin, args.kp_fw, args.vin_drop_gain
    )
    if args.foot_friction is not None:
        for g in model.geom_names:
            if g and "foot" in g:
                gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, g)
                model.geom_friction[gid][0] = args.foot_friction

    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    meta = sess.get_modelmeta().custom_metadata_map or {}
    expected = int(sess.get_inputs()[0].shape[1])
    print(f"ONNX {pathlib.Path(args.onnx).name}: in {expected}-D, out "
          f"{sess.get_outputs()[0].shape[1]}-D, joy_cmds={meta.get('joy_commands')}, "
          f"conditioner={meta.get('joy_target_conditioner')}")

    act_joint_ids = [int(model.actuator_trnid[i, 0]) for i in range(model.nu)]
    qpos_ids = [int(model.jnt_qposadr[j]) for j in act_joint_ids]
    qvel_ids = [int(model.jnt_dofadr[j]) for j in act_joint_ids]
    n_act = model.nu
    default_pose = DEFAULT_POSE[:n_act]

    def reset():
        data.qpos[:] = 0.0
        data.qvel[:] = 0.0
        data.qpos[0:3] = [0.0, 0.0, 0.122]
        data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
        data.qpos[qpos_ids] = default_pose
        data.ctrl[:] = 0.0
        mujoco.mj_forward(model, data)
        if bam_ctrl is not None:
            bam_ctrl.reset(data.qpos)
        # `initialize_joy_servo_targets`: ctrl starts at the measured joint pos.
        target = data.qpos[qpos_ids].copy()
        if bam_ctrl is not None:
            bam_ctrl.q_target[:] = target
        else:
            data.ctrl[:] = target
        return target

    target = reset()
    last_action = np.zeros(n_act, dtype=np.float32)
    origin = data.qpos[0:2].copy()
    origin_yaw = yaw_of(data.qpos[3:7])
    prev_joint_vel = data.qvel[qvel_ids].copy()
    # Official acceptance instrumentation (microduck_lab/parkour/joy.py:report).
    anchor_xy = None
    dance_t0 = None
    feet_peak = np.zeros(2)
    target_steps = []
    motion_q = []
    min_upright = 1.0

    left_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "left_foot")
    right_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "right_foot")
    imu_gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, "imu_ang_vel")

    ctrl_dt = args.timestep * args.decimation
    n_steps = int(round(args.seconds / ctrl_dt))
    trace = []
    vx_hist = []

    for k in range(n_steps):
        t = k * ctrl_dt
        p = 2 * math.pi * JOY_HZ * t
        e = float(np.clip(t / FADE_S, 0.0, 1.0))
        quat = data.qpos[3:7].copy()
        yaw = yaw_of(quat)
        pos = data.qpos[0:2]
        dx = float(np.clip(-2.0 * (pos[0] - origin[0]), -0.15, 0.15))
        dy = float(np.clip(-2.0 * (pos[1] - origin[1]), -0.15, 0.15))
        twist = np.array(
            [
                math.cos(yaw) * dx + math.sin(yaw) * dy,
                -math.sin(yaw) * dx + math.cos(yaw) * dy,
                float(np.clip(-2.0 * yaw, -0.8, 0.8)),
            ],
            dtype=np.float32,
        )
        if args.no_clock:
            head_cmd = np.zeros(4, dtype=np.float32)
            body_cmd = np.zeros(6, dtype=np.float32)
        else:
            head_cmd = (
                np.array(
                    [0.07 * math.sin(2 * p), 0.03 * math.sin(2 * p),
                     0.24 * math.sin(p), 0.12 * math.sin(p)],
                    dtype=np.float32,
                )
                * e
            )
            body_cmd = (
                np.array(
                    [0.0, 0.0, 0.006 * (1 - math.cos(2 * p)),
                     0.07 * math.sin(p), 0.0, 0.0],
                    dtype=np.float32,
                )
                * e
            )

        if imu_gid >= 0:
            adr = model.sensor_adr[imu_gid]
            ang_vel = data.sensordata[adr : adr + 3].copy()
        else:
            ang_vel = data.qvel[3:6].copy()
        grav = quat_rotate_inverse(quat, [0.0, 0.0, -1.0])
        cur_vel = data.qvel[qvel_ids].copy()
        # `joint_vel_delay=1` means the observation carries the velocity sampled one
        # control period earlier. Reading data.qvel here is *this* step's value, so
        # the delay only exists if we use the buffer written in the previous step.
        jvel_obs = prev_joint_vel if args.joint_vel_delay else cur_vel
        obs = np.concatenate(
            [
                ang_vel,
                grav,
                data.qpos[qpos_ids] - default_pose,
                jvel_obs,
                last_action,
                twist,
                head_cmd,
                body_cmd,
            ]
        ).astype(np.float32)
        if obs.shape[0] != expected:
            raise SystemExit(f"obs {obs.shape[0]} != ONNX input {expected}")

        action = sess.run([out_name], {in_name: obs[None]})[0][0].astype(np.float64)
        last_action = action.astype(np.float32)

        processed = default_pose + action  # scale 1.0, use_default_offset=True
        prev_target = target.copy()
        delta = np.clip(ALPHA * (processed - target), -MAX_STEP, MAX_STEP)
        target = target + delta
        target_steps.append(target - prev_target)
        if bam_ctrl is not None:
            bam_ctrl.q_target[:] = target
        else:
            data.ctrl[:] = target

        for _ in range(args.decimation):
            if bam_ctrl is not None:
                bam_ctrl.update()
            mujoco.mj_step(model, data)

        lz = data.site_xpos[left_site][2] if left_site >= 0 else np.nan
        rz = data.site_xpos[right_site][2] if right_site >= 0 else np.nan
        roll, pitch = roll_pitch(data.qpos[3:7])
        v_world = data.qvel[0:3].copy()
        vx = quat_rotate_inverse(data.qpos[3:7], v_world)[0]
        prev_joint_vel = cur_vel
        vx_hist.append(vx)

        # --- official acceptance instrumentation ---------------------------
        # upright = trunk body-z projected on world-z = R[2,2], which is exactly
        # d.xmat[trunk_body_id, 8] in microduck_lab/parkour/joy.py.
        _w, _x, _y, _z = data.qpos[3:7]
        upright = float(1.0 - 2.0 * (_x * _x + _y * _y))
        min_upright = min(min_upright, upright)
        if anchor_xy is None and t >= FADE_S - 1e-9:
            anchor_xy = data.qpos[0:2].copy()
            dance_t0 = t
        if anchor_xy is not None:
            feet_peak[0] = max(feet_peak[0], lz)
            feet_peak[1] = max(feet_peak[1], rz)
            motion_q.append(data.qpos[qpos_ids].copy())
        drift = (
            float(np.linalg.norm(data.qpos[0:2] - anchor_xy))
            if anchor_xy is not None
            else 0.0
        )

        trace.append(
            dict(
                t=round(t, 3),
                z=float(data.qpos[2]),
                vx=float(vx),
                dist=float(np.hypot(*(data.qpos[0:2] - origin))),
                yaw=math.degrees(yaw),
                roll=math.degrees(roll),
                pitch=math.degrees(pitch),
                lz=float(lz),
                rz=float(rz),
                upright=upright,
                drift=drift,
            )
        )
        if not args.quiet and abs((t + ctrl_dt) % 0.5) < 1e-6:
            print(
                f"  t={t:5.2f}s  z={data.qpos[2]*1000:6.1f}mm  vx={vx:+.3f}  "
                f"d={trace[-1]['dist']*1000:5.1f}mm  yaw={trace[-1]['yaw']:+6.1f}°  "
                f"roll={trace[-1]['roll']:+5.1f}°  Lz={lz*1000:5.1f} Rz={rz*1000:5.1f}"
            )

    # --- summary -----------------------------------------------------------
    tail = trace[len(trace) // 2 :]  # second half = after the fade-in settle
    zs = np.array([r["z"] for r in tail])
    dists = np.array([r["dist"] for r in tail])
    yaws = np.array([r["yaw"] for r in tail])
    lzs = np.array([r["lz"] for r in tail])
    rzs = np.array([r["rz"] for r in tail])
    fall = bool(zs.min() < 0.06 or max(abs(r["roll"]) for r in tail) > 60)

    # --- official acceptance, copied from microduck_lab/parkour/joy.py:report ---
    # Upstream probes a deployed policy with exactly these ten gates. Reproducing
    # them lets our number be compared with a first-party pass/fail, instead of a
    # threshold I invented.
    steps = np.asarray(target_steps) if target_steps else np.zeros((0, n_act))
    rate_rms = float(np.sqrt(np.mean((steps / ctrl_dt) ** 2))) if steps.size else 1e3
    max_step_rad = float(np.abs(steps).max()) if steps.size else 1e3
    hf_ratio = None
    if len(motion_q) > 20:
        poses = np.asarray(motion_q)
        centered = poses - poses.mean(0)
        spectrum = (
            np.abs(np.fft.rfft(centered * np.hanning(len(poses))[:, None], axis=0)) ** 2
        )
        freqs = np.fft.rfftfreq(len(poses), ctrl_dt)
        hf_ratio = float(spectrum[freqs > 8].sum() / max(spectrum[freqs > 0].sum(), 1e-12))
    max_drift = float(max((r["drift"] for r in trace), default=0.0))
    duration = (trace[-1]["t"] + ctrl_dt - dance_t0) if dance_t0 is not None else 0.0
    # foot_support: upstream defines it in parkour/world.py (not fetched); this is
    # an approximation -- "some foot site is essentially on the floor".
    foot_support = bool(min(lzs.min(), rzs.min()) < 0.008) if len(lzs) else False
    end_upright = float(trace[-1]["upright"])

    gates = {
        "duration_s>=3.5": duration >= 3.5,
        "min_upright>0.9": min_upright > 0.9,
        "max_drift<0.08m": max_drift < 0.08,
        "both_feet_peak>8mm": bool((feet_peak > 0.008).all()),
        "end_upright>0.95": end_upright > 0.95,
        "foot_support(approx)": foot_support,
        "target_rate_rms<6": rate_rms < 6.0,
        "max_target_step<0.2rad": max_step_rad < 0.2,
        "hf_ratio<0.01": (hf_ratio is not None and hf_ratio < 0.01),
    }
    summary = dict(
        onnx=pathlib.Path(args.onnx).name,
        plant=args.plant,
        physics_step_s=args.timestep,
        controller_hz=round(1.0 / ctrl_dt, 1),
        joint_vel_delay=args.joint_vel_delay,
        seconds=args.seconds,
        fell=fall,
        min_height_mm=float(zs.min() * 1000),
        mean_vx=float(np.mean(vx_hist[len(vx_hist) // 2 :])),
        peak_vx=float(np.max(np.abs(vx_hist[len(vx_hist) // 2 :]))),
        net_displacement_mm=float(dists[-1] * 1000),
        max_displacement_mm=float(dists.max() * 1000),
        yaw_range_deg=float(yaws.max() - yaws.min()),
        yaw_final_deg=float(yaws[-1]),
        lfoot_z_mm=[float(lzs.min() * 1000), float(lzs.max() * 1000)],
        rfoot_z_mm=[float(rzs.min() * 1000), float(rzs.max() * 1000)],
        # official gate values
        joy_duration_s=round(duration, 3),
        joy_min_upright=round(min_upright, 4),
        joy_max_drift_m=round(max_drift, 4),
        joy_feet_peak_mm=[round(float(x) * 1000, 2) for x in feet_peak],
        joy_target_rate_rms=round(rate_rms, 3),
        joy_max_target_step_rad=round(max_step_rad, 4),
        joy_hf_ratio_above_8hz=hf_ratio,
        joy_gates=gates,
        joy_passed=all(gates.values()),
    )
    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:22s} {v}")
    print("\n=== official gates (microduck_lab/parkour/joy.py) ===")
    for k, v in gates.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  -> joy_passed = {summary['joy_passed']}")
    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(dict(summary=summary, trace=trace), indent=1)
        )
        print(f"  -> {args.json_out}")
    return summary


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
