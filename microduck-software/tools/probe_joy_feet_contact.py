# SPDX-License-Identifier: Apache-2.0
"""Is the foot actually leaving the ground, and would an air-time reward pay?

Why this file exists
--------------------
`feet_peak_m` in `eval_joy_in_sim.py` is the foot **site height above the terrain
origin**, not the lift above the stance pose. The joy reward
(`mdp.joy_foot_rhythm`) is also written in that absolute coordinate
(`target = 0.0005 + 0.024*relu(sin p)^2`). Two different claims were floating
around -- "it lifts 6 mm" and "it lifts 0.4 mm" -- because nobody had separated
`mean height` from `lift amplitude`.

This probe reports both, plus the contact sensor, because the choice between
"fix the action-rate ramp" and "switch to an air-time reward" depends entirely
on **whether the foot ever breaks contact**. `mdp.feet_air_time` is a binary
counter on `current_air_time > 0`; if contact never breaks it is identically
zero and carries no gradient at all, no matter how the window is tuned.

Usage
-----
  .venv-mjlab/Scripts/python.exe tools/probe_joy_feet_contact.py \
      --checkpoint logs/.../model_599.pt --num-envs 64 --seconds 8 --device cpu
"""

from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import asdict

import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pct(x: torch.Tensor, qs=(0.0, 0.05, 0.5, 0.95, 1.0)):
    x = x.flatten().float()
    return [round(float(torch.quantile(x, q)), 6) for q in qs]


def run(task_id, checkpoint, num_envs, seconds, device, play, out):
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.utils.torch import configure_torch_backends
    from mjlab_microduck.tasks import mdp

    configure_torch_backends()

    env_cfg = load_env_cfg(task_id, play=play)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs
    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    obs, _ = env.reset()
    u = env.unwrapped
    robot = u.scene["robot"]
    foot_cfg = SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])
    foot_cfg.resolve(u.scene)
    sensor = u.scene["feet_ground_contact"]
    step_dt = float(u.step_dt)
    n_steps = int(round(seconds / step_dt))

    z_hist, air_hist, tgt_hist, rew_hist = [], [], [], []
    for _ in range(n_steps):
        with torch.no_grad():
            actions = policy(obs)
        obs, _r, _d, _x = env.step(actions)
        z = robot.data.site_pos_w[:, foot_cfg.site_ids, 2] - u.scene.terrain.env_origins[:, None, 2]
        z_hist.append(z.detach().clone())
        air = sensor.data.current_air_time
        air_hist.append(air.detach().clone())
        # `JoySmoothPositionAction` (upstream) keeps the buffer under the private
        # name; the base class property exists only on the stock action.
        act = u.action_manager.get_term("joint_pos")
        buf = getattr(act, "processed_actions", None)
        if buf is None:
            buf = act._processed_actions
        tgt_hist.append(buf.detach().clone())
        rew_hist.append(mdp.joy_foot_rhythm(u, foot_cfg).detach().clone())

    z = torch.stack(z_hist)          # [T, N, 2]
    air = torch.stack(air_hist)      # [T, N, 2]
    tgt = torch.stack(tgt_hist)      # [T, N, 14]
    rew = torch.stack(rew_hist)

    # Stance height = the 5th percentile over time, i.e. where the foot sits when
    # it is down. Lift amplitude is measured against that, not against zero.
    stance = torch.quantile(z.reshape(-1, 2), 0.05, dim=0)
    lift = z - stance[None, None, :]

    above = air > 0
    in_win = (air > 0.125) & (air < 0.300)
    # A "contact break" is an airborne step that follows a grounded step.
    prev_grounded = torch.cat([torch.ones_like(above[:1]), above[:-1] == 0], 0)
    break_events = (above & prev_grounded).sum(dim=0).float()

    # joint target travel per control step, radians
    dtgt = (tgt[1:] - tgt[:-1]).abs()

    res = {
        "task_id": task_id,
        "checkpoint": checkpoint,
        "num_envs": num_envs,
        "seconds": seconds,
        "play_cfg": play,
        "step_dt": step_dt,
        "foot_z_abs_m": {
            "p0_p5_p50_p95_p100": pct(z),
            "stance_p5": [round(float(v), 6) for v in stance],
        },
        "lift_above_stance_m": {"p0_p5_p50_p95_p100": pct(lift)},
        "contact": {
            "airborne_step_frac": round(float(above.float().mean()), 5),
            "in_airtime_window_frac_0.125_0.300": round(float(in_win.float().mean()), 5),
            "mean_current_air_time_when_airborne": round(
                float(air[above].mean()) if above.any() else 0.0, 5
            ),
            "contact_breaks_per_8s": [round(float(v), 3) for v in break_events.mean(dim=0)],
            "never_broke_contact_envs": int((break_events.sum(dim=-1) == 0).sum()),
        },
        "air_time_reward_if_enabled": {
            "note": "weight 3.0 per foot in window; step count in window per env",
            "steps_in_window_per_8s": round(float(in_win.sum(dim=0).sum(dim=-1).float().mean()), 2),
        },
        "joy_foot_rhythm": {
            "mean": round(float(rew.mean()), 4),
            "p0_p5_p50_p95_p100": pct(rew),
        },
        "joint_target_step_rad": {
            "p50": round(float(dtgt.median()), 5),
            "p95": round(float(torch.quantile(dtgt, 0.95)), 5),
            "max": round(float(dtgt.max()), 5),
        },
    }

    print(json.dumps(res, ensure_ascii=False, indent=1))
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    env.close()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Mjlab-JoySmoothPD-Flat-MicroDuck")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, default=64)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    run(a.task, a.checkpoint, a.num_envs, a.seconds, a.device, a.play, a.out)


if __name__ == "__main__":
    main()
