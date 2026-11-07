#!/usr/bin/env python3
"""Headless rollout of a policy on a locomotion task (e.g. Rollers).

Two policy sources, same rollout + fall-rate metric:

* ``--onnx``  : an ONNX policy (61->14, internal normalization). Used to benchmark
  the official ``pollen-robotics/microduck-policies`` ONNX (B代-trained) against
  our HD-1910 plant. The official ONNX bakes obs normalization internally (Sub/
  Div) and consumes RAW obs, which is exactly what this env's RslRlVecEnvWrapper
  emits (no wrapper-side normalization in this fork), so obs is fed unchanged.
  This is a *cross-plant stress test*, not the policy's native score. Pass
  ``--action-scale`` for policies whose manifest carries action_scale (roller=0.8).
* ``--checkpoint`` : a trained rsl_rl ``.pt`` (our HD-1910 native policy). Fed
  through the same env, so its fall-rate is apple-to-apple comparable to the
  official-ONNX baseline measured on the same plant.

Usage
-----
    # cross-plant baseline (official B代 ONNX on HD-1910)
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_roller_onnx.py \
        --task Mjlab-Velocity-Flat-MicroDuck-Rollers \
        --onnx out/official_policies/roller.onnx --action-scale 0.8 \
        --envs 32 --seeds 2 --json out/roller_eval_onnx.json

    # native HD-1910 policy (trained here)
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_roller_onnx.py \
        --task Mjlab-Velocity-Flat-MicroDuck-Rollers \
        --checkpoint logs/rsl_rl/microduck_roller_hd1910/<run>/model_4000.pt \
        --envs 32 --seeds 2 --json out/roller_eval_native.json
"""
import argparse
import json
import os
import pathlib
import re

# Match training: IsaacLab's MuJoCo backend ran headless with glfw during training.
os.environ.setdefault("MUJOCO_GL", "glfw")

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # microduck-software/


def find_default_checkpoint() -> pathlib.Path:
    base = ROOT / "logs" / "rsl_rl" / "microduck_roller_hd1910"
    runs = sorted(base.glob("2026-*/"), key=lambda p: p.name, reverse=True)
    best: pathlib.Path | None = None
    best_n = -1
    for run in runs:
        for f in run.glob("model_*.pt"):
            m = re.search(r"model_(\d+)\.pt", f.name)
            if m and int(m.group(1)) > best_n:
                best_n, best = int(m.group(1)), f
    if best is None:
        raise SystemExit(f"no roller checkpoint under {base}")
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless policy rollout + fall-rate metric")
    ap.add_argument("--task", required=True, help="registered task, e.g. Mjlab-Velocity-Flat-MicroDuck-Rollers")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--onnx", default=None, help="ONNX policy (61->14, internal normalization)")
    group.add_argument("--checkpoint", default=None, help="trained rsl_rl .pt (HD-1910 native)")
    ap.add_argument("--action-scale", type=float, default=1.0, help="manifest action_scale (roller=0.8), ONNX only")
    ap.add_argument("--envs", type=int, default=32)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--device", default="cuda:0" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-steps", type=int, default=0, help="0 = env.max_episode_length")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    import mjlab.tasks  # noqa: F401  (populate the task registry)
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.envs import ManagerBasedRlEnv
    from dataclasses import asdict

    device = args.device
    env_cfg = load_env_cfg(args.task, play=True)
    agent_cfg = load_rl_cfg(args.task)
    env_cfg.scene.num_envs = args.envs

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device, render_mode=None)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    clip = float(getattr(agent_cfg, "clip_actions", 0.0) or 0.0)

    if args.onnx:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])

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

        report_ckpt = str(args.onnx)
        policy_format = "onnx"
        note = "cross-plant: official B代 ONNX on HD-1910 env (portability stress test)"
    else:
        ckpt = pathlib.Path(args.checkpoint) if args.checkpoint else find_default_checkpoint()
        if not ckpt.exists():
            raise SystemExit(f"checkpoint not found: {ckpt}")
        runner_cls = load_runner_cls(args.task) or MjlabOnPolicyRunner
        runner = runner_cls(env, asdict(agent_cfg), device=device)
        runner.load(str(ckpt), load_cfg={"actor": True}, strict=True, map_location=device)
        # rsl_rl inference policy takes the env TensorDict obs directly
        # (it internally selects the actor obs group) — no wrapper needed.
        policy = runner.get_inference_policy(device=device)
        report_ckpt = str(ckpt)
        policy_format = "pt"
        note = "native: HD-1910 trained .pt on HD-1910 env (apple-to-apple vs ONNX baseline)"

    max_steps = args.max_steps or int(env.max_episode_length)

    all_fall, all_surv, all_rew = [], [], []
    all_ws, all_glide = [], []  # "actually rolling?" signals (reward-weighted)
    for seed in range(args.seeds):
        torch.manual_seed(seed)
        obs, _ = env.reset()
        N = args.envs
        fell = torch.zeros(N, dtype=torch.bool, device=device)
        surv = torch.zeros(N, device=device)
        step_rew = 0.0
        ws_sum = 0.0
        glide_sum = 0.0
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
            log = extras.get("log", {}) or {}
            if "Episode_Reward/wheel_speed" in log:
                ws_sum += float(torch.as_tensor(log["Episode_Reward/wheel_speed"]).float().mean().item())
            if "Episode_Reward/glide" in log:
                glide_sum += float(torch.as_tensor(log["Episode_Reward/glide"]).float().mean().item())
            n += 1
        all_fall.append(float(fell.float().mean().item()))
        all_surv.append(float(surv.float().mean().item()))
        all_rew.append(step_rew / max(n, 1))
        all_ws.append(ws_sum / max(n, 1))
        all_glide.append(glide_sum / max(n, 1))

    env.close()

    report = {
        "task": args.task,
        "policy": report_ckpt,
        "policy_format": policy_format,
        "action_scale": args.action_scale if args.onnx else None,
        "envs": args.envs,
        "seeds": args.seeds,
        "max_steps": max_steps,
        "fall_rate": round(float(np.mean(all_fall)), 4),
        "mean_survival_steps": round(float(np.mean(all_surv)), 1),
        "mean_survival_s": round(float(np.mean(all_surv)) * 0.02, 2),
        "mean_step_reward": round(float(np.mean(all_rew)), 4),
        "mean_wheel_speed_reward": round(float(np.mean(all_ws)), 4),
        "mean_glide_reward": round(float(np.mean(all_glide)), 4),
        "note": note,
    }
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"task       {args.task}")
    print(f"policy     {report_ckpt}  ({policy_format})")
    if args.onnx:
        print(f"action_scale {args.action_scale}")
    print(f"envs={args.envs}  seeds={args.seeds}  max_steps={max_steps}")
    print(f"fall_rate            {report['fall_rate']*100:.1f}%")
    print(f"mean survival        {report['mean_survival_s']:.1f} s  ({report['mean_survival_steps']:.0f} steps)")
    print(f"mean step reward     {report['mean_step_reward']:.3f}")
    print(f"mean wheel_speed rew {report['mean_wheel_speed_reward']:.3f}  (rolling signal)")
    print(f"mean glide rew       {report['mean_glide_reward']:.3f}  (rolling signal)")
    if policy_format == "onnx":
        print(f"[cross-plant] official B代 ONNX on HD-1910 plant, not the policy's native score")
    else:
        print(f"[native] HD-1910 trained .pt on HD-1910 plant — apple-to-apple vs the 17.2% ONNX baseline")
    if args.json:
        print(f"json -> {args.json}")


if __name__ == "__main__":
    main()
