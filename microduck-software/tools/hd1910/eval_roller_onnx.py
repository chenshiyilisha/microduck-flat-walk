#!/usr/bin/env python3
"""Headless rollout of an ONNX policy on a locomotion task (e.g. Rollers).

Measures the headline portability signal — fall rate — plus a coarse "is it
actually moving well" proxy (mean per-step reward). Used to benchmark the
official ``pollen-robotics/microduck-policies`` ONNX (B代-trained) against our
HD-1910 plant: the official policy is trained on the production MicroDuck, so
running it on the HD-1910 env is a *cross-plant stress test*, not the policy's
native score.

The official ONNX bakes obs normalization internally (Sub/Div) and consumes RAW
obs, which is exactly what this env's RslRlVecEnvWrapper emits (no wrapper-side
normalization in this fork), so obs is fed through unchanged. Use
``--action-scale`` for policies whose manifest carries action_scale (roller=0.8).

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_roller_onnx.py \
        --task Mjlab-Velocity-Flat-MicroDuck-Rollers \
        --onnx out/official_policies/roller.onnx --action-scale 0.8 \
        --envs 32 --seeds 2 --json out/roller_eval_onnx.json
"""
import argparse
import json
import os
import pathlib

# Match training: IsaacLab's MuJoCo backend ran headless with glfw during training.
os.environ.setdefault("MUJOCO_GL", "glfw")

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # microduck-software/


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless ONNX rollout + fall-rate metric")
    ap.add_argument("--task", required=True, help="registered task, e.g. Mjlab-Velocity-Flat-MicroDuck-Rollers")
    ap.add_argument("--onnx", required=True, help="ONNX policy (61->14, internal normalization)")
    ap.add_argument("--action-scale", type=float, default=1.0, help="manifest action_scale (roller=0.8)")
    ap.add_argument("--envs", type=int, default=32)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--device", default="cuda:0" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-steps", type=int, default=0, help="0 = env.max_episode_length")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    import mjlab.tasks  # noqa: F401  (populate the task registry)
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg
    from mjlab.rl import RslRlVecEnvWrapper
    from mjlab.envs import ManagerBasedRlEnv

    device = args.device
    env_cfg = load_env_cfg(args.task, play=True)
    agent_cfg = load_rl_cfg(args.task)
    env_cfg.scene.num_envs = args.envs

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device, render_mode=None)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    import onnxruntime as ort
    sess = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    clip = float(getattr(agent_cfg, "clip_actions", 0.0) or 0.0)

    max_steps = args.max_steps or int(env.max_episode_length)

    def policy(obs_t):
        if hasattr(obs_t, "__contains__") and "actor" in obs_t:
            obs_t = obs_t["actor"]
        x = obs_t.detach().cpu().numpy().astype(np.float32)
        try:
            a = sess.run(None, {"obs": x})[0]
        except Exception:
            a = np.stack([sess.run(None, {"obs": x[i:i + 1]})[0][0] for i in range(x.shape[0])])
        a = a * float(args.action_scale)
        t = torch.from_numpy(a).to(getattr(obs_t, "device", device))
        if clip > 0:
            t = torch.clamp(t, -clip, clip)
        return t

    all_fall, all_surv, all_rew = [], [], []
    for seed in range(args.seeds):
        torch.manual_seed(seed)
        obs, _ = env.reset()
        N = args.envs
        fell = torch.zeros(N, dtype=torch.bool, device=device)
        surv = torch.zeros(N, device=device)
        step_rew = 0.0
        n = 0
        for _ in range(max_steps):
            with torch.no_grad():
                action = policy(obs)
            obs, rew, dones, extras = env.step(action)
            to = extras.get("time_outs", torch.zeros_like(dones))
            ft = dones.bool() & ~to.bool()
            fell = fell | ft
            surv = torch.where(~ft, surv + 1.0, surv)
            step_rew += float(rew.float().mean().item())
            n += 1
        all_fall.append(float(fell.float().mean().item()))
        all_surv.append(float(surv.float().mean().item()))
        all_rew.append(step_rew / max(n, 1))

    env.close()

    report = {
        "task": args.task,
        "onnx": str(args.onnx),
        "policy_format": "onnx",
        "action_scale": args.action_scale,
        "envs": args.envs,
        "seeds": args.seeds,
        "max_steps": max_steps,
        "fall_rate": round(float(np.mean(all_fall)), 4),
        "mean_survival_steps": round(float(np.mean(all_surv)), 1),
        "mean_survival_s": round(float(np.mean(all_surv)) * 0.02, 2),
        "mean_step_reward": round(float(np.mean(all_rew)), 4),
        "note": "cross-plant: official B代 ONNX on HD-1910 env (portability stress test)",
    }
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"task       {args.task}")
    print(f"onnx       {args.onnx}  (action_scale={args.action_scale})")
    print(f"envs={args.envs}  seeds={args.seeds}  max_steps={max_steps}")
    print(f"fall_rate            {report['fall_rate']*100:.1f}%")
    print(f"mean survival        {report['mean_survival_s']:.1f} s  ({report['mean_survival_steps']:.0f} steps)")
    print(f"mean step reward     {report['mean_step_reward']:.3f}")
    print(f"[cross-plant] official B代 ONNX on HD-1910 plant, not the policy's native score")
    if args.json:
        print(f"json -> {args.json}")


if __name__ == "__main__":
    main()
