"""Trace one joy gait cycle: what the feet are told to do vs what they do.

The plateau at joy_feet ~4.4-5.6 has survived three interventions (action_rate,
exploration noise, entropy), so indirect correlation studies are exhausted. This
tool measures the four quantities that separate the remaining hypotheses in one
run:

  target(t)   z_target from mdp.joy_foot_rhythm
              0.5 mm + 24 mm * relu(+-sin p)^2 * ramp,  p = 2*pi*1.15*t
  actual(t)   foot site height from the simulation
  command(t)  foot height implied by the *commanded* servo angles, via CPU
              MuJoCo forward kinematics on a copy of the state. This is what the
              policy is asking for; the gap to actual is what the hardware
              refuses to do.

Decision table:
  command ~= 0.5 mm, actual ~= 0.5 mm      -> policy never asks for a lift
  command >= 20 mm, actual ~= 5 mm         -> torque/velocity limited
  command >= 20 mm, actual >= 20 mm        -> amplitude fine, phase must be off
  command ~ actual but both < target       -> action smoothing clips the target

Two subtleties that would otherwise produce a wrong reading:
  * `e = clamp(t / 0.8, 0, 1)` ramps the target in over the first 0.8 s of every
    episode (mdp.py:7735). Samples below the ramp are excluded from the stats,
    otherwise the first half-second looks like "cannot lift".
  * The target is 0.5 mm for *half* the cycle (relu kills the negative lobe), so
    "peak" is the only meaningful amplitude statistic and a plain mean hides the
    lift entirely.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import asdict

import numpy as np

FREQ = 1.15  # mdp.joy_phase default
TARGET_BASE = 0.0005
TARGET_AMP = 0.024
TOL = 0.009  # the 9 mm width in exp(-((z-target)/0.009)^2)


def _np(x):
    """mjlab exposes both warp arrays and torch views of the same buffer."""
    if hasattr(x, "detach"):
        return x.detach().cpu().numpy()
    if hasattr(x, "numpy"):
        return x.numpy()
    return np.asarray(x)


def build(task_id: str, checkpoint: str, num_envs: int, device: str, play: bool):
    import torch

    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(task_id, play=play)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs
    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    return env, runner.get_inference_policy(device=device)


def foot_heights(mjm, mjd_fk, qpos_row, q_adrs, site_ids, z_origin, joint_target):
    """Two foot heights from CPU forward kinematics.

    Returns ``(commanded, check)``:

    * ``commanded`` -- FK with the joints set to ``joint_target``. This is the
      pose the policy is asking for.
    * ``check`` -- FK with the joints left at the simulated ``qpos``. This is the
      negative control: it must reproduce the simulated foot height, otherwise
      the FK/origin setup itself is wrong and ``commanded`` means nothing.

    ``ctrl`` is deliberately NOT used here. For these ducks ``data.ctrl`` is the
    motor *voltage* (BamActuator edits `gear=[1,0,...]`, a direct-drive actuator,
    with `vin` in volts), not a joint angle. Writing it into `qpos` produced foot
    heights of 111 mm / 238 mm for a 24 mm target -- obvious nonsense that still
    looked plausible enough to be reported as "hardware limited". The joint
    command lives in `data.joint_pos_target`.
    """
    import mujoco

    mjd_fk.qpos[:] = qpos_row
    mujoco.mj_kinematics(mjm, mjd_fk)
    check = mjd_fk.site_xpos[site_ids, 2] - z_origin

    mjd_fk.qpos[q_adrs] = joint_target
    mujoco.mj_kinematics(mjm, mjd_fk)
    commanded = mjd_fk.site_xpos[site_ids, 2] - z_origin
    return commanded, check


def run(task: str, ckpt: str, num_envs: int, seconds: float, device: str, play: bool, out_dir):
    import mujoco
    import torch

    from mjlab.managers.scene_entity_config import SceneEntityCfg

    env, policy = build(task, ckpt, num_envs, device, play)
    u = env.unwrapped
    robot = u.scene["robot"]
    step_dt = float(u.step_dt)

    foot_names = ["left_foot", "right_foot"]
    foot_cfg = SceneEntityCfg("robot", site_names=foot_names)
    foot_cfg.resolve(u.scene)
    # Three namespaces, and mixing them silently reads the WRONG site:
    #   data.site_pos_w        entity-local site order  (foot_cfg.site_ids = [1, 6])
    #   indexing.site_ids      global mjModel site ids  ([1..7] for this entity)
    #   mj name lookup         returns -1 because mjlab prefixes names ("robot/left_foot")
    # The earlier version passed entity-local ids straight to mjd.site_xpos; -1 is the
    # last site, so BOTH feet silently resolved to right_foot and the FK control
    # "passed" while comparing right_foot with right_foot.
    site_ids_entity = np.asarray(foot_cfg.site_ids, dtype=int)
    all_site_ids = _np(robot.indexing.site_ids).astype(int)
    site_ids_mj = all_site_ids[site_ids_entity]
    if (site_ids_mj < 0).any() or site_ids_mj.max() >= u.sim.mj_model.nsite:
        raise SystemExit(f"bad site id mapping: entity {site_ids_entity} -> mj {site_ids_mj}")

    mjm = u.sim.mj_model
    mjd_fk = mujoco.MjData(mjm)
    ctrl_ids = robot.indexing.ctrl_ids
    # joint_pos_target is indexed in ENTITY joint order; joint_q_adr gives the
    # matching qpos address for each entity joint, so no actuator reverse-lookup
    # is needed (and assuming actuator i -> joint i would be wrong anyway).
    ctrl_ids_np = _np(ctrl_ids).astype(int)
    q_adr_entity = _np(robot.indexing.joint_q_adr).astype(int)
    jnt_ids = mjm.jnt_qposadr  # unused; kept out of the way
    joint_names = [
        mujoco.mj_id2name(
            mjm, mujoco.mjtObj.mjOBJ_JOINT,
            int(np.where(mjm.jnt_qposadr == a)[0][0]),
        )
        for a in q_adr_entity
    ]

    env.reset()
    n = int(round(seconds / step_dt))
    rec = {k: [] for k in ("t", "phase", "ramp", "zL", "zR", "cmdL", "cmdR", "tgtL", "tgtR")}
    target_hist, qpos_hist = [], []
    fk_err: list[float] = []  # |FK(qpos) - simulated foot height| per step

    for _ in range(n):
        with torch.no_grad():
            obs = env.get_observations()
            act = policy(obs)
            env.step(act)

        t = float(_np(u.episode_length_buf)[0]) * step_dt
        p = 2 * math.pi * FREQ * t
        ramp = min(max(t / 0.8, 0.0), 1.0)

        z = _np(robot.data.site_pos_w[0, site_ids_entity, 2]) - float(_np(u.scene.terrain.env_origins)[0, 2])
        # joint_pos_target is the firmware position target (BAM drives a voltage
        # control law whose inner loop tracks this). It shares the ENTITY joint
        # order, not the actuator order, so resolve qpos addresses from
        # indexing.joint_q_adr directly.
        jt = _np(robot.data.joint_pos_target)[0]
        jpos = _np(robot.data.joint_pos)[0]
        qpos_row = _np(u.sim.data.qpos)[0].copy()
        cmd, fk_check = foot_heights(
            mjm, mjd_fk, qpos_row, q_adr_entity, site_ids_mj,
            float(_np(u.scene.terrain.env_origins)[0, 2]), jt,
        )
        fk_err.append(float(np.max(np.abs(fk_check - z))))

        rec["t"].append(t)
        rec["phase"].append((t * FREQ) % 1.0)
        rec["ramp"].append(ramp)
        rec["zL"].append(float(z[0]))
        rec["zR"].append(float(z[1]))
        rec["cmdL"].append(float(cmd[0]))
        rec["cmdR"].append(float(cmd[1]))
        rec["tgtL"].append(TARGET_BASE + TARGET_AMP * max(math.sin(p), 0.0) ** 2 * ramp)
        rec["tgtR"].append(TARGET_BASE + TARGET_AMP * max(-math.sin(p), 0.0) ** 2 * ramp)
        target_hist.append(jt)
        qpos_hist.append(jpos)

    a = {k: np.asarray(v) for k, v in rec.items()}
    target_arr = np.asarray(target_hist)
    qpos_arr = np.asarray(qpos_hist)
    fk_err_arr = np.asarray(fk_err)

    # ---- fold onto one gait cycle: amplitude and phase are cycle statistics ----
    nb = 20
    bins = np.clip((a["phase"] * nb).astype(int), 0, nb - 1)
    valid = a["ramp"] >= 0.999

    def fold(x):
        return np.array([x[valid & (bins == b)].mean() if (valid & (bins == b)).any() else np.nan
                         for b in range(nb)])

    fold_ = {k: fold(a[k]) for k in ("zL", "cmdL", "tgtL", "zR", "cmdR", "tgtR")}

    def peak(x):
        return float(np.nanmax(x)) if np.isfinite(x).any() else float("nan")

    def peak_phase(x):
        if not np.isfinite(x).any():
            return float("nan")
        return float(np.nanargmax(x)) / nb

    report = {
        "checkpoint": ckpt,
        "num_envs": num_envs,
        "seconds": seconds,
        "valid_samples": int(valid.sum()),
        "total_samples": int(len(a["t"])),
        "left": {
            "peak_target_mm": peak(a["tgtL"]) * 1e3,
            "peak_actual_mm": peak(a["zL"]) * 1e3,
            "peak_command_mm": peak(a["cmdL"]) * 1e3,
            "actual_range_mm": float((np.max(a["zL"]) - np.min(a["zL"])) * 1e3),
            "command_range_mm": float((np.max(a["cmdL"]) - np.min(a["cmdL"])) * 1e3),
            "phase_of_actual_peak": peak_phase(fold_["zL"]),
            "phase_of_target_peak": peak_phase(fold_["tgtL"]),
            "phase_of_command_peak": peak_phase(fold_["cmdL"]),
        },
        "right": {
            "peak_target_mm": peak(a["tgtR"]) * 1e3,
            "peak_actual_mm": peak(a["zR"]) * 1e3,
            "peak_command_mm": peak(a["cmdR"]) * 1e3,
            "actual_range_mm": float((np.max(a["zR"]) - np.min(a["zR"])) * 1e3),
            "command_range_mm": float((np.max(a["cmdR"]) - np.min(a["cmdR"])) * 1e3),
            "phase_of_actual_peak": peak_phase(fold_["zR"]),
            "phase_of_target_peak": peak_phase(fold_["tgtR"]),
            "phase_of_command_peak": peak_phase(fold_["cmdR"]),
        },
        "fk_check_max_err_mm": float(np.max(fk_err_arr) * 1e3),
        "tracking": {
            name: {
                "target_range_deg": float(np.degrees(target_arr[:, i].max() - target_arr[:, i].min())),
                "qpos_range_deg": float(np.degrees(qpos_arr[:, i].max() - qpos_arr[:, i].min())),
                "rms_err_deg": float(np.degrees(np.sqrt(np.mean((target_arr[:, i] - qpos_arr[:, i]) ** 2)))),
                "peak_err_deg": float(np.degrees(np.max(np.abs(target_arr[:, i] - qpos_arr[:, i])))),
            }
            for i, name in enumerate(joint_names)
        },
    }

    left = report["left"]
    # Excursion (peak-to-peak) is the statistic that matters, not the absolute
    # peak: a constant bias in either curve (root pose, origin, standing offset)
    # cancels out, while "how far does the foot travel" does not.
    cmd_exc = left["command_range_mm"]
    act_exc = left["actual_range_mm"]
    lag = (left["phase_of_actual_peak"] - left["phase_of_target_peak"]) % 1.0
    if lag > 0.5:
        lag -= 1.0
    report["verdict"] = {
        "command_excursion_mm": cmd_exc,
        "actual_excursion_mm": act_exc,
        "target_excursion_mm": left["peak_target_mm"] - TARGET_BASE * 1e3,
        "excursion_ratio_actual_over_command": act_exc / cmd_exc if cmd_exc > 1e-6 else float("nan"),
        "phase_lag_cycles": lag,
        "phase_lag_ms": lag * 1000.0 / FREQ,
    }

    if report["fk_check_max_err_mm"] > 0.5:
        reason = (
            f"FK MISMATCH: forward kinematics from qpos reproduces the simulated foot "
            f"height only to {report['fk_check_max_err_mm']:.2f} mm -- refusing to interpret"
        )
    elif cmd_exc < 3.0:
        reason = "POLICY NOT ASKING: commanded pose keeps the foot on the ground"
    elif act_exc < 0.5 * cmd_exc:
        reason = "HARDWARE LIMITED: command asks for a lift, simulation refuses most of it"
    elif abs(lag) > 0.08:
        reason = f"PHASE OFFSET: foot peaks {lag * 1000 / FREQ:+.0f} ms off target"
    else:
        reason = "AMPLITUDE SHORT: commanded and tracked, but below the 24 mm target"
    report["verdict"]["reason"] = reason

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "joy_foot_phase.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        _plot(a, fold_, nb, out_dir / "joy_foot_phase.png", reason)
    except Exception as exc:  # noqa: BLE001
        print(f"[plot] skipped: {exc}", file=sys.stderr)

    return report, reason


def _plot(a, fold_, nb, path, reason):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [2, 1]})

    ax = axes[0]
    t = a["t"]
    ax.plot(t, a["tgtL"] * 1e3, "--", color="#c0392b", lw=1.2, label="target L")
    ax.plot(t, a["zL"] * 1e3, color="#c0392b", lw=1.6, label="actual L")
    ax.plot(t, a["cmdL"] * 1e3, color="#e67e22", lw=1.2, alpha=0.9, label="commanded L (FK)")
    ax.plot(t, a["zR"] * 1e3, color="#2c73d2", lw=1.4, label="actual R")
    ax.plot(t, a["tgtR"] * 1e3, "--", color="#2c73d2", lw=1.0, alpha=0.7, label="target R")
    ax.axhline(0.5, color="#7f8c8d", lw=0.8, ls=":")
    ax.set_ylabel("foot height above ground [mm]")
    ax.set_xlabel("time [s]")
    ax.set_title(f"joy gait: what the feet are told vs what they do\n{reason}", fontsize=10)
    ax.legend(fontsize=8, ncol=3, loc="upper right")
    ax.grid(alpha=0.25)

    ax2 = axes[1]
    centers = (np.arange(nb) + 0.5) / nb
    for k, c, lab in (("tgtL", "#c0392b", "target"), ("cmdL", "#e67e22", "commanded"),
                      ("zL", "#1a1a1a", "actual")):
        ax2.plot(centers, fold_[k] * 1e3, "o-", color=c, lw=1.6, ms=4, label=lab)
    ax2.set_xlabel(f"gait cycle phase (cycle = {1 / FREQ * 1000:.0f} ms)")
    ax2.set_ylabel("L foot [mm]")
    ax2.set_title("left foot folded onto one cycle", fontsize=9)
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Mjlab-JoySmoothPD-Flat-MicroDuck")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--out-dir", default="out")
    args = ap.parse_args()

    report, reason = run(args.task, args.checkpoint, args.num_envs, args.seconds,
                         args.device, args.play, args.out_dir)

    L, R, V = report["left"], report["right"], report["verdict"]
    print(f"valid samples {report['valid_samples']}/{report['total_samples']} "
          f"(discarded the 0.8 s target ramp)")
    print(f"FK control |FK(qpos) - simulated| max = {report['fk_check_max_err_mm']:.4f} mm "
          f"(must be ~0; otherwise the commanded curve is meaningless)")
    print(f"{'':10s} {'target':>8} {'cmd_pk':>8} {'act_pk':>8} {'cmd_exc':>8} {'act_exc':>8}")
    for nm, d in (("left", L), ("right", R)):
        print(f"{nm:10s} {d['peak_target_mm']:8.2f} {d['peak_command_mm']:8.2f} "
              f"{d['peak_actual_mm']:8.2f} {d['command_range_mm']:8.2f} "
              f"{d['actual_range_mm']:8.2f}   [mm]")
    print(f"\nphase of L peak: target {L['phase_of_target_peak']:.2f} "
          f"command {L['phase_of_command_peak']:.2f} actual {L['phase_of_actual_peak']:.2f} cycles "
          f"-> lag {V['phase_lag_ms']:+.0f} ms")
    print(f"L excursion: command {V['command_excursion_mm']:.2f} mm, "
          f"actual {V['actual_excursion_mm']:.2f} mm, target {V['target_excursion_mm']:.2f} mm "
          f"-> actual/command {V['excursion_ratio_actual_over_command']:.2f}")
    print(f"\nVERDICT: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
