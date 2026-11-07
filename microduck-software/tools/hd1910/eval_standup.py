#!/usr/bin/env python3
"""Headless deployment-side evaluation of the StandUp (fall-recovery) policy.

Why this exists
--------------
The duck is trained to get up from a fallen pose in ``Mjlab-StandUp-Flat-MicroDuck``.
``eval_policy.py`` only measures the *velocity* task and ``rehearse_deploy.py`` only
runs the *walk* scene, so neither can tell us whether the duck actually stands back
up after training. This script closes that gap: it replays the trained ``.pt`` in the
*same* IsaacLab StandUp env the policy was trained in (61-D obs layout identical to
training), and reports an objective stand-up success rate.

Success definition (phase-independent, like eval_ground_pick.py -- an episode may end
at a random phase, so per-episode MIN/MAX are used instead of final-step values):
  * never fell over (no ``terminated`` / fell_over reset), AND
  * the trunk reached upright at least once (max z-up > UPRIGHT_OK, default 0.90),
    AND
  * the trunk was STILL upright at episode end (final z-up > STAY_OK, default 0.85)
    -- a duck that pops up and immediately topples is not "recovered".

Plant safety
------------
StandUp trains on a *plant* (kp_fw + params JSON). A policy trained on m5 (kp_fw=32)
is NOT valid on the deploy plant kp8 (kp_fw=8), and vice versa -- this is the
XL330<->HD1910 / kp5<->kp8 incident. So the reading records the *live* plant
(read from ``apply_to_live --check --json``) alongside the metrics, exactly like
eval_velocity_in_sim.py does, so a cross-plant number is never silently comparable
with an archived one.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_standup.py \
        --checkpoint logs/rsl_rl/microduck_standup_hd1910/<run>/model_XXXX.pt \
        --envs 64 --seeds 3 --json out/standup_eval.json

    # default: newest model_*.pt under microduck_standup_hd1910
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_standup.py --envs 64 --seeds 3
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

# Match training: IsaacLab's MuJoCo backend ran headless with glfw during training.
os.environ.setdefault("MUJOCO_GL", "glfw")

import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # microduck-software/
TASK = "Mjlab-StandUp-Flat-MicroDuck"
UPRIGHT_OK = 0.90   # z-up component (1 - 2*(x^2+y^2)) above this = "upright"
STAY_OK = 0.85      # z-up at episode end above this = "still up"


def find_default_checkpoint() -> pathlib.Path:
    base = ROOT / "logs" / "rsl_rl" / "microduck_standup_hd1910"
    runs = sorted(base.glob("2026-*/"), key=lambda p: p.name, reverse=True)
    best: pathlib.Path | None = None
    best_n = -1
    for run in runs:
        for f in run.glob("model_*.pt"):
            m = re.search(r"model_(\d+)\.pt", f.name)
            if m and int(m.group(1)) > best_n:
                best_n, best = int(m.group(1)), f
    if best is None:
        raise SystemExit(f"no StandUp checkpoint under {base}")
    return best


def live_plant() -> dict:
    """Read the live plant fingerprint (detected name + kp_fw) from apply_to_live."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "hd1910" / "apply_to_live.py"),
         "--check", "--json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    try:
        return json.loads(out)
    except Exception:
        return {"detected": None, "kp_fw": None, "raw": out[-400:]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless StandUp success-rate eval")
    ap.add_argument("--checkpoint", default=None, help="formal .pt; default = newest model_*.pt")
    ap.add_argument("--envs", type=int, default=64)
    ap.add_argument("--seeds", type=int, default=3, help="independent resets for iqr")
    ap.add_argument("--device", default="cuda:0" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-steps", type=int, default=0, help="0 = env.max_episode_length")
    ap.add_argument("--upright-ok", type=float, default=UPRIGHT_OK)
    ap.add_argument("--stay-ok", type=float, default=STAY_OK)
    ap.add_argument("--json", default=None, help="write JSON report here")
    ap.add_argument("--onnx", default=None,
                    help="evaluate an ONNX policy instead of a .pt checkpoint.")
    ap.add_argument("--action-scale", type=float, default=1.0,
                    help="multiply ONNX actions by this (manifest action_scale)")
    args = ap.parse_args()

    plant = live_plant()

    if args.onnx:
        ckpt = None
    else:
        ckpt = pathlib.Path(args.checkpoint) if args.checkpoint else find_default_checkpoint()
        if not ckpt.exists():
            raise SystemExit(f"checkpoint not found: {ckpt}")

    import mjlab.tasks  # noqa: F401  (populate the task registry)
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls

    device = args.device
    env_cfg = load_env_cfg(TASK, play=True)
    agent_cfg = load_rl_cfg(TASK)
    env_cfg.scene.num_envs = args.envs

    env = None
    try:
        env = __import__("mjlab").envs.ManagerBasedRlEnv(
            cfg=env_cfg, device=device, render_mode=None
        )
    except Exception:
        from mjlab.envs import ManagerBasedRlEnv  # type: ignore
        env = ManagerBasedRlEnv(cfg=env_cfg, device=device, render_mode=None)

    from dataclasses import asdict
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper  # type: ignore

    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    if args.onnx:
        import numpy as np
        import onnxruntime as ort
        so = ort.SessionOptions()
        onnx_session = ort.InferenceSession(
            str(args.onnx), sess_options=so, providers=["CPUExecutionProvider"])
        clip = float(getattr(agent_cfg, "clip_actions", 0.0) or 0.0)

        def policy(obs_t):
            if hasattr(obs_t, "__contains__") and "actor" in obs_t:
                obs_t = obs_t["actor"]
            elif isinstance(obs_t, dict) and "policy" in obs_t:
                obs_t = obs_t["policy"]
            x = obs_t.detach().cpu().numpy().astype(np.float32)
            try:
                a = onnx_session.run(None, {"obs": x})[0]
            except Exception:
                a = np.stack([onnx_session.run(None, {"obs": x[i:i + 1]})[0][0]
                              for i in range(x.shape[0])])
            a = a * float(args.action_scale)
            t = torch.from_numpy(a).to(obs_t.device)
            if clip > 0:
                t = torch.clamp(t, -clip, clip)
            return t
        report_ckpt = str(args.onnx)
    else:
        runner_cls = load_runner_cls(TASK) or MjlabOnPolicyRunner
        runner = runner_cls(env, asdict(agent_cfg), device=device)
        runner.load(str(ckpt), load_cfg={"actor": True}, strict=True, map_location=device)
        policy = runner.get_inference_policy(device=device)
        report_ckpt = str(ckpt)

    robot = env.unwrapped.scene["robot"]
    try:
        trunk_idx = int(robot.body_names.index("trunk_base"))
    except (AttributeError, ValueError):
        trunk_idx = int(robot.body_names_to_idx["trunk_base"])

    max_steps = args.max_steps or int(env.max_episode_length)

    def z_up_of(quat_wxyz):
        x, y = quat_wxyz[:, 1], quat_wxyz[:, 2]
        return 1.0 - 2.0 * (x * x + y * y)

    all_success, all_fell, all_reached, all_stayed = [], [], [], []
    max_zup_per_seed, final_zup_per_seed = [], []

    for seed in range(args.seeds):
        torch.manual_seed(seed)
        obs, _ = env.reset()
        N = args.envs
        fell = torch.zeros(N, dtype=torch.bool, device=device)
        max_zup = torch.zeros(N, device=device)
        final_zup = torch.zeros(N, device=device)

        for _ in range(max_steps):
            trunk_q = robot.data.body_link_quat_w[:, trunk_idx, :]
            up = z_up_of(trunk_q)
            alive = ~fell
            max_zup = torch.where(alive, torch.maximum(max_zup, up.float()), max_zup)
            final_zup = torch.where(alive, up.float(), final_zup)

            with torch.no_grad():
                action = policy(obs)
            obs, _rew, dones, extras = env.step(action)
            time_outs = extras.get("time_outs", torch.zeros_like(dones))
            fell_this = (dones.bool() & ~time_outs.bool())
            fell = fell | fell_this

        reached = max_zup > args.upright_ok          # got up at least once
        stayed = final_zup > args.stay_ok            # still up at episode end
        success = (~fell) & reached & stayed

        all_success.append(float(success.float().mean().item()))
        all_fell.append(float(fell.float().mean().item()))
        all_reached.append(float(reached.float().mean().item()))
        all_stayed.append(float(stayed.float().mean().item()))
        max_zup_per_seed.append(float(max_zup.cpu().float().median().item()))
        final_zup_per_seed.append(float(final_zup.cpu().float().median().item()))

    env.close()

    def med_iqr(xs):
        import numpy as np
        a = np.array(xs, float)
        return round(float(np.median(a)), 4), [
            round(float(np.percentile(a, 25)), 4),
            round(float(np.percentile(a, 75)), 4),
        ]

    report = {
        "checkpoint": report_ckpt,
        "task": TASK,
        "policy_format": "onnx" if args.onnx else "pt",
        "envs": args.envs,
        "seeds": args.seeds,
        "max_steps": max_steps,
        "upright_ok_threshold": args.upright_ok,
        "stay_ok_threshold": args.stay_ok,
        "live_plant": {"detected": plant.get("detected"), "kp_fw": plant.get("kp_fw")},
        "trunk_max_zup_median": round(float(sum(max_zup_per_seed) / len(max_zup_per_seed)), 4),
        "trunk_final_zup_median": round(float(sum(final_zup_per_seed) / len(final_zup_per_seed)), 4),
        "success_rate": med_iqr(all_success),
        "fall_rate": med_iqr(all_fell),
        "reached_upright_rate": med_iqr(all_reached),
        "stayed_upright_rate": med_iqr(all_stayed),
    }
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"checkpoint  {report_ckpt}")
    print(f"envs={args.envs}  seeds={args.seeds}  max_steps={max_steps}")
    print(f"live plant  detected={plant.get('detected')}  kp_fw={plant.get('kp_fw')}")
    print(f"trunk max z-up  (median): {report['trunk_max_zup_median']:.3f}  [upright>{args.upright_ok}]")
    print(f"trunk final z-up(median): {report['trunk_final_zup_median']:.3f}  [stay>{args.stay_ok}]")
    print(f"success     {report['success_rate'][0]*100:.1f}%  (iqr {[round(v*100,1) for v in report['success_rate'][1]]})")
    print(f"fall        {report['fall_rate'][0]*100:.1f}%")
    print(f"reached up  {report['reached_upright_rate'][0]*100:.1f}%")
    print(f"stayed up   {report['stayed_upright_rate'][0]*100:.1f}%")
    if args.json:
        print(f"json -> {args.json}")


if __name__ == "__main__":
    main()
