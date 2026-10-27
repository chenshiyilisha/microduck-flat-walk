"""Where does the foot-lift shortfall live: between envs, or between windows?

Why this exists
---------------
`Metrics/joy_peak_swing_p50` is the median of `self.peak[in_swing]` taken over
*every* control step. But `peak` on a fresh window start is just the current
foot height (~3 mm) and only reaches the true swing peak in the last frames of
the 0.435 s window. So the logged p50 sits on the rising flank and understates
the lift, while `Episode_Reward/joy_feet` (a mean) reads two to three times
higher. The two numbers are not the same statistic and neither one is the
quantity the gate reports.

This probe measures the honest one: the peak **at the end of each swing
window**, per env per foot. It then answers the question that decides the next
move:

    is the shortfall uniform across envs (a policy-wide ceiling),
    or is it a handful of envs lifting while the rest stand still (a
    bimodal population that can be mined for the successful gait)?

Also dumps joint ranges for the best and worst envs, so "what did the winners
do differently" is a measurement rather than a guess.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/probe_peak_spread.py \
        --checkpoint logs/rsl_rl/microduck_joy_smooth/<run>/model_400.pt \
        --envs 128 --seconds 6
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import asdict

import torch

TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"
FREQ = 1.15
STANCE = 0.0005
LEG_JOINTS = ("left_hip_pitch", "left_hip_roll", "left_knee", "left_ankle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--envs", type=int, default=128)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--out", default="out/peak_spread.json")
    args = ap.parse_args()

    import mjlab_microduck.tasks  # noqa: F401
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(TASK, play=False)
    agent_cfg = load_rl_cfg(TASK)
    env_cfg.scene.num_envs = args.envs
    raw = ManagerBasedRlEnv(cfg=env_cfg, device=args.device)
    env = RslRlVecEnvWrapper(raw, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(TASK) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=args.device)
    runner.load(args.checkpoint, load_cfg={"actor": True}, strict=True,
                map_location=args.device)
    policy = runner.get_inference_policy(device=args.device)

    u = env.unwrapped
    step_dt = float(u.step_dt)
    n_steps = int(round(args.seconds / step_dt))
    N = args.envs
    dev = args.device

    foot_cfg = SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])
    foot_cfg.resolve(u.scene)
    robot = u.scene["robot"]

    jnames = list(robot.joint_names)
    jidx = {n: jnames.index(n) for n in LEG_JOINTS}

    obs, _ = env.reset()
    origin_z = u.scene.terrain.env_origins[:, None, 2]

    peak = torch.zeros(N, 2, device=dev)
    window = torch.full((N, 2), -1, dtype=torch.long, device=dev)
    swung_prev = torch.zeros(N, 2, dtype=torch.bool, device=dev)
    done_peak = []      # completed windows: list of (env_ids, foot_ids, peak_mm)

    q_hist, up_hist = [], []
    fell = torch.zeros(N, dtype=torch.bool, device=dev)

    for _ in range(n_steps):
        with torch.no_grad():
            act = policy(obs)
        obs, _rew, dones, extras = env.step(act)

        t = u.episode_length_buf.to(torch.float32) * step_dt
        p = 2 * math.pi * FREQ * t
        s = torch.sin(p)
        in_swing = torch.stack((s > 0, s < 0), dim=-1)
        win = torch.floor(p / math.pi).long().unsqueeze(-1).expand(-1, 2)
        fresh = win != window

        h = robot.data.site_pos_w[:, foot_cfg.site_ids, 2] - origin_z - STANCE

        rec = fresh & swung_prev
        if bool(rec.any()):
            e_ids, f_ids = rec.nonzero(as_tuple=True)
            done_peak.append((e_ids.clone(), f_ids.clone(),
                              (peak[e_ids, f_ids] * 1000).clone()))

        peak = torch.where(fresh, h, torch.maximum(peak, h))
        swung_prev = torch.where(fresh, in_swing, swung_prev | in_swing)
        window = win

        q_hist.append(robot.data.joint_pos[:, [jidx[n] for n in LEG_JOINTS]].clone())
        q = robot.data.root_link_quat_w
        w, x, y, z = q.unbind(-1)
        up_hist.append((1.0 - 2.0 * (x * x + y * y)).clone())

        timeouts = extras.get("time_outs")
        if timeouts is not None:
            fell |= dones.bool() & ~timeouts.bool()
        else:
            fell |= dones.bool()

    if not done_peak:
        print("no completed swing window in this run -- lengthen --seconds")
        return 1

    # window_peak[e, f, k]: k-th completed window for that (env, foot)
    counts = torch.zeros(N, 2, dtype=torch.long)
    for e_ids, f_ids, _v in done_peak:
        counts.index_put_((e_ids, f_ids), torch.ones_like(e_ids), accumulate=True)
    kmax = int(counts.max())
    wp = torch.full((N, 2, kmax), float("nan"))
    cursor = torch.zeros(N, 2, dtype=torch.long)
    for e_ids, f_ids, v in done_peak:
        idx = cursor[e_ids, f_ids]
        ok = idx < kmax
        wp[e_ids[ok].cpu(), f_ids[ok].cpu(), idx[ok].cpu()] = v[ok].cpu()
        cursor.index_put_((e_ids, f_ids), torch.ones_like(e_ids), accumulate=True)

    flat = wp.reshape(-1)
    flat = flat[~torch.isnan(flat)]
    qs = [10, 25, 50, 75, 90, 95, 99]
    qv = torch.quantile(flat, torch.tensor([q / 100 for q in qs])).tolist()

    print(f"\ncheckpoint {pathlib.Path(args.checkpoint).name}   "
          f"{N} envs x {n_steps} steps   {len(done_peak)} window-batches\n")
    print("=== peak AT END OF SWING WINDOW (the honest lift) ===")
    print("  " + "  ".join(f"p{q}={v:.2f}" for q, v in zip(qs, qv)) + f"  (mm, n={flat.numel()})")

    # per-env median across its own windows -> is the population bimodal?
    env_med = torch.nanmedian(wp.reshape(N, -1), dim=-1).values
    alive = ~fell.cpu()
    em = env_med[alive]
    print(f"\n=== per-env median of window peak ({int(alive.sum())}/{N} envs never fell) ===")
    eq = torch.quantile(em, torch.tensor([0.1, 0.25, 0.5, 0.75, 0.9])).tolist()
    print("  p10={:.2f}  p25={:.2f}  p50={:.2f}  p75={:.2f}  p90={:.2f}  (mm)".format(*eq))

    # variance decomposition: between envs vs within env (across its windows)
    within = torch.nanstd(wp.reshape(N, -1), dim=-1)
    between = float(em.std())
    within_med = float(torch.nanmedian(within))
    tot = math.sqrt(between ** 2 + within_med ** 2)
    print(f"\n=== variance split ===")
    print(f"  between-env sd      {between:6.2f} mm")
    print(f"  within-env sd (med) {within_med:6.2f} mm")
    print(f"  -> between-env share {100 * between ** 2 / max(tot ** 2, 1e-9):5.1f} %")

    # what do the winners do with their joints?
    q_all = torch.stack(q_hist)                     # [T, N, 4]
    up_all = torch.stack(up_hist)                   # [T, N]
    qrng = (q_all.max(0).values - q_all.min(0).values).cpu() * 180 / math.pi
    order = torch.argsort(em, descending=True)
    top = order[: max(1, alive.sum() // 8)]
    bot = order[-max(1, alive.sum() // 8):]
    print(f"\n=== joint range (deg, peak-to-peak over the run) ===")
    print(f"{'joint':<18}{'top 12%':>10}{'bottom 12%':>12}{'ratio':>8}")
    for j, n in enumerate(LEG_JOINTS):
        a = float(qrng[top, j].mean())
        b = float(qrng[bot, j].mean())
        print(f"{n.replace('left_', ''):<18}{a:>10.1f}{b:>12.1f}{a / max(b, 1e-6):>8.2f}x")
    print(f"{'upright (min)':<18}{float(up_all[:, top].min()):>10.3f}"
          f"{float(up_all[:, bot].min()):>12.3f}")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "checkpoint": str(args.checkpoint),
        "envs": N, "steps": n_steps, "freq_hz": FREQ,
        "window_peak_mm": {f"p{q}": round(v, 3) for q, v in zip(qs, qv)},
        "window_peak_n": int(flat.numel()),
        "env_median_mm": {f"p{q}": round(v, 3)
                          for q, v in zip([10, 25, 50, 75, 90], eq)},
        "between_env_sd_mm": round(between, 3),
        "within_env_sd_mm": round(within_med, 3),
        "between_env_share": round(between ** 2 / max(tot ** 2, 1e-9), 4),
        "joint_range_deg_top": {n.replace("left_", ""): round(float(qrng[top, j].mean()), 2)
                                for j, n in enumerate(LEG_JOINTS)},
        "joint_range_deg_bottom": {n.replace("left_", ""): round(float(qrng[bot, j].mean()), 2)
                                   for j, n in enumerate(LEG_JOINTS)},
        "fell_envs": int(fell.sum()),
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
