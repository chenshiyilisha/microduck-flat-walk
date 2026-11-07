#!/usr/bin/env python3
"""Headless deployment-side evaluation of the GroundPick policy.

Why this exists
--------------
``eval_policy.py`` only measures the *velocity* task, and ``rehearse_deploy.py``
only runs the *walk* scene through BAM. Neither can tell us whether the duck
actually performs the ground-pick (mouth-to-ground approach + return to stand)
after training — they only report training-side reward terms. This script closes
that gap: it replays the trained ``.pt`` in the *same* IsaacLab GroundPick env the
policy was trained in (so the 61-D observation layout is identical to training,
not a hand-rebuilt MuJoCo approximation), and reports an objective success rate.

Success definition (the task has NO physical object in the scene — the "picked
object" is a virtual payload sampled at reset and applied as an external force to
``mouth_tip`` during the rise phase). So "pick success" is the full motion:
  * never fell over (no ``terminated`` / fell_over reset), AND
  * the mouth tip actually descended toward the ground at some point
    (min mouth height < ~0.06 m, near the floor), AND
  * the mouth rose BACK to standing height at least once during the episode
    (max mouth height > 0.9 * standing height), AND
  * the trunk reached upright at least once (max z-up > 0.9).

NOTE: metrics are phase-independent. The phase command cycles every 4 s, so an
episode end lands at a *random* phase — judging "return" from the final-step
height alone is a phase-bias artifact. We therefore use the per-episode MIN and
MAX mouth height (and MAX upright) instead of the final-step values. Standing
height is self-calibrated as the 85th percentile of all mouth heights over the
episode (the high mode of a bimodal down/up distribution) and cross-checked
against the published fidelity numbers (mouth_z_start ≈ 0.188 m,
mouth_z_end ≈ 0.216 m for the upstream recipe as-is).

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_ground_pick.py \
        --checkpoint logs/rsl_rl/microduck_groundpick_hd1910/<run>/model_4000.pt \
        --envs 64 --seeds 1 --json out/groundpick_eval.json

Phase-cutoff fidelity check (real runtime cuts the take at φ=0.7, take ~2.8 s of
the 4 s period; the upstream recipe only completes the rise at φ≈1.0). Pass
``--phase-cap 0.7`` to force a phase-0 start (like the real take) and measure how
close the duck is to standing/upright *at the instant phase first reaches 0.7* —
i.e. whether freezing there looks like "stood back up" or "frozen mid-crouch".

    .venv-mjlab/Scripts/python.exe tools/hd1910/eval_ground_pick.py \
        --checkpoint logs/rsl_rl/microduck_groundpick_hd1910/<run>/model_4000.pt \
        --envs 64 --seeds 3 --phase-cap 0.7 --json out/groundpick_cap07.json

Defaults pick the highest ``model_*.pt`` in the most recent GroundPick run dir.
"""
import argparse
import json
import os
import pathlib
import re
import sys

# Match training: IsaacLab's MuJoCo backend ran headless with glfw during training.
os.environ.setdefault("MUJOCO_GL", "glfw")

import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # microduck-software/
TASK = "Mjlab-GroundPick-Flat-MicroDuck"


def find_default_checkpoint() -> pathlib.Path:
    base = ROOT / "logs" / "rsl_rl" / "microduck_groundpick_hd1910"
    runs = sorted(base.glob("2026-*/"), key=lambda p: p.name, reverse=True)
    best: pathlib.Path | None = None
    best_n = -1
    for run in runs:
        for f in run.glob("model_*.pt"):
            m = re.search(r"model_(\d+)\.pt", f.name)
            if m and int(m.group(1)) > best_n:
                best_n, best = int(m.group(1)), f
    if best is None:
        raise SystemExit(f"no GroundPick checkpoint under {base}")
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless GroundPick success-rate eval")
    ap.add_argument("--checkpoint", default=None, help="formal .pt; default = newest model_*.pt")
    ap.add_argument("--envs", type=int, default=64)
    ap.add_argument("--seeds", type=int, default=1, help="independent resets for iqr")
    ap.add_argument("--device", default="cuda:0" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-steps", type=int, default=0, help="0 = env.max_episode_length")
    ap.add_argument("--phase-cap", type=float, default=None,
                    help="phase-cutoff fidelity check: if set (e.g. 0.7), force "
                         "randomize_phase=False (start at phase 0 = standing, like the "
                         "real take) and record each env's mouth height / upright at the "
                         "first step phase reaches this value. Reports how close the duck "
                         "is to standing when the real runtime cuts the take off.")
    ap.add_argument("--json", default=None, help="write JSON report here")
    args = ap.parse_args()

    ckpt = pathlib.Path(args.checkpoint) if args.checkpoint else find_default_checkpoint()
    if not ckpt.exists():
        raise SystemExit(f"checkpoint not found: {ckpt}")

    import mjlab.tasks  # noqa: F401  (populate the task registry)
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls

    device = args.device
    env_cfg = load_env_cfg(TASK, play=True)
    agent_cfg = load_rl_cfg(TASK)
    env_cfg.scene.num_envs = args.envs

    # phase-cap fidelity mode: the real take starts the cycle at phase 0 (standing)
    # and cuts off at phi=0.7 (take ~2.8 s of the 4 s period). Default training uses
    # randomize_phase=True (decorrelate envs); for this check we force phase 0 start
    # so "first time phase reaches cap" = "end of the real take".
    if args.phase_cap is not None:
        try:
            tw_cfg = env_cfg.commands["twist"]
            tw_cfg.randomize_phase = False
        except (KeyError, AttributeError):
            pass  # command name differs across forks; cap check falls back to random start

    env = None
    try:
        env = __import__("mjlab").envs.ManagerBasedRlEnv(
            cfg=env_cfg, device=device, render_mode=None
        )
    except Exception:
        # older import path
        from mjlab.envs import ManagerBasedRlEnv  # type: ignore
        env = ManagerBasedRlEnv(cfg=env_cfg, device=device, render_mode=None)

    from dataclasses import asdict
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper  # type: ignore

    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(TASK) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(str(ckpt), load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    robot = env.unwrapped.scene["robot"]
    cmd_mgr = env.unwrapped.command_manager
    try:
        mouth_idx = int(robot.site_names.index("mouth_tip"))
        trunk_idx = int(robot.body_names.index("trunk_base"))
    except (AttributeError, ValueError):
        # Some IsaacLab forks expose name->index maps under a different name.
        mouth_idx = int(robot.site_names_to_idx["mouth_tip"])
        trunk_idx = int(robot.body_names_to_idx["trunk_base"])

    max_steps = args.max_steps or int(env.max_episode_length)

    def z_up_of(quat_wxyz):
        # IsaacLab quat layout (w,x,y,z); z-up component = 1 - 2*(x^2+y^2)
        x, y = quat_wxyz[:, 1], quat_wxyz[:, 2]
        return 1.0 - 2.0 * (x * x + y * y)

    all_success, all_fell, all_descent, all_upright, all_return = [], [], [], [], []
    all_cap_ok, all_cap_mouth, all_cap_up = [], [], []
    standing_mouth_per_seed = []
    mouth_min_per_seed, mouth_max_per_seed, mouth_final_per_seed = [], [], []
    # Pooled mouth heights across all steps/envs/seeds -> self-calibrate standing.
    pooled_mouth = []

    for seed in range(args.seeds):
        torch.manual_seed(seed)
        obs, _ = env.reset()
        N = args.envs
        fell = torch.zeros(N, dtype=torch.bool, device=device)
        min_mouth = torch.full((N,), float("inf"), device=device)
        max_mouth = torch.zeros(N, device=device)
        max_up = torch.zeros(N, device=device)
        final_mouth = torch.zeros(N, device=device)
        final_up = torch.zeros(N, device=device)
        if args.phase_cap is not None:
            cap_mouth = torch.full((N,), float("nan"), device=device)
            cap_up = torch.full((N,), float("nan"), device=device)

        for _ in range(max_steps):
            mouth_w = robot.data.site_pos_w[:, mouth_idx, 2]  # z (height) per env
            trunk_q = robot.data.body_link_quat_w[:, trunk_idx, :]
            up = z_up_of(trunk_q)
            # Only accumulate for envs that have not yet fallen (avoids pollution
            # from auto-reset standing pose after a fall).
            alive = ~fell
            mh = mouth_w.float()
            min_mouth = torch.where(alive, torch.minimum(min_mouth, mh), min_mouth)
            max_mouth = torch.where(alive, torch.maximum(max_mouth, mh), max_mouth)
            max_up = torch.where(alive, torch.maximum(max_up, up.float()), max_up)
            final_mouth = torch.where(alive, mh, final_mouth)
            final_up = torch.where(alive, up.float(), final_up)
            if args.phase_cap is not None:
                # Phase is encoded as command = [cos(2π·φ), sin(2π·φ), 0] on "twist".
                # Recover φ the same way the reward functions do (mdp.py:1616).
                twist = cmd_mgr.get_command("twist")
                phase = (torch.atan2(twist[:, 1], twist[:, 0]) / (2.0 * torch.pi)) % 1.0
                reached = phase >= args.phase_cap
                grab = alive & cap_mouth.isnan() & reached
                cap_mouth = torch.where(grab, mh, cap_mouth)
                cap_up = torch.where(grab, up.float(), cap_up)
            pooled_mouth.append(mh.cpu().float())

            with torch.no_grad():
                action = policy(obs)
            obs, _rew, dones, extras = env.step(action)
            # dones = terminated | truncated (combined); extras["time_outs"] marks
            # the max-episode timeout, so (dones & ~time_out) is the real fall.
            time_outs = extras.get("time_outs", torch.zeros_like(dones))
            fell_this = (dones.bool() & ~time_outs.bool())
            fell = fell | fell_this

        # Self-calibrated standing height: the high mode of the bimodal
        # down/up distribution. Reference fidelity: mouth_z_start ≈ 0.188 m,
        # mouth_z_end ≈ 0.216 m for the upstream recipe as-is.
        import numpy as np
        pm = torch.cat(pooled_mouth).numpy()
        standing_mouth = float(np.percentile(pm, 85))
        standing_mouth_per_seed.append(standing_mouth)
        sm = standing_mouth
        descent_ok = min_mouth < 0.06          # reached near the floor
        return_ok = max_mouth > (0.9 * sm)     # rose back to standing >= once
        upright_ok = max_up > 0.9              # trunk reached upright >= once
        success = (~fell) & descent_ok & return_ok & upright_ok

        if args.phase_cap is not None:
            cm = cap_mouth.cpu().float()
            cu = cap_up.cpu().float()
            # At the real take cutoff the duck should already be (near) standing
            # and upright; otherwise it freezes mid-crouch.
            cap_ok = torch.isfinite(cm) & (cm > 0.9 * sm) & (cu > 0.9)
            all_cap_ok.append(float(cap_ok.float().mean().item()))
            all_cap_mouth.append(float(torch.nanmedian(cm).item()))
            all_cap_up.append(float(torch.nanmedian(cu).item()))

        all_success.append(float(success.float().mean().item()))
        all_fell.append(float(fell.float().mean().item()))
        all_descent.append(float(descent_ok.float().mean().item()))
        all_upright.append(float(upright_ok.float().mean().item()))
        all_return.append(float(return_ok.float().mean().item()))
        mouth_min_per_seed.append(float(min_mouth.cpu().float().median().item()))
        mouth_max_per_seed.append(float(max_mouth.cpu().float().median().item()))
        mouth_final_per_seed.append(float(final_mouth.cpu().float().median().item()))

    env.close()

    def med_iqr(xs):
        import numpy as np
        a = np.array(xs, float)
        return round(float(np.median(a)), 4), [
            round(float(np.percentile(a, 25)), 4),
            round(float(np.percentile(a, 75)), 4),
        ]

    report = {
        "checkpoint": str(ckpt),
        "task": TASK,
        "envs": args.envs,
        "seeds": args.seeds,
        "max_steps": max_steps,
        "standing_mouth_height_m": round(float(sum(standing_mouth_per_seed) / len(standing_mouth_per_seed)), 4),
        "mouth_min_height_m_median": round(float(sum(mouth_min_per_seed) / len(mouth_min_per_seed)), 4),
        "mouth_max_height_m_median": round(float(sum(mouth_max_per_seed) / len(mouth_max_per_seed)), 4),
        "mouth_final_height_m_median": round(float(sum(mouth_final_per_seed) / len(mouth_final_per_seed)), 4),
        "reference_mouth_z_start_m": 0.188,
        "reference_mouth_z_end_m": 0.216,
        "success_rate": med_iqr(all_success),
        "fall_rate": med_iqr(all_fell),
        "descent_rate": med_iqr(all_descent),
        "upright_rate": med_iqr(all_upright),
        "return_rate": med_iqr(all_return),
    }
    if args.phase_cap is not None:
        report["phase_cap"] = args.phase_cap
        report["cap_cutoff_ok_rate"] = med_iqr(all_cap_ok)
        report["cap_mouth_height_m_median"] = round(float(sum(all_cap_mouth) / len(all_cap_mouth)), 4)
        report["cap_upright_median"] = round(float(sum(all_cap_up) / len(all_cap_up)), 4)
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"checkpoint  {ckpt.name}")
    print(f"envs={args.envs}  seeds={args.seeds}  max_steps={max_steps}")
    print(f"standing mouth height (85th pct): {report['standing_mouth_height_m']:.3f} m  "
          f"[ref start 0.188 / end 0.216]")
    print(f"mouth min height  (median):        {report['mouth_min_height_m_median']:.3f} m  [ref ~0.021]")
    print(f"mouth max height  (median):        {report['mouth_max_height_m_median']:.3f} m")
    print(f"mouth final height(median, PHASE-BIASED diag): {report['mouth_final_height_m_median']:.3f} m")
    print(f"success     {report['success_rate'][0]*100:.1f}%  (iqr {[round(v*100,1) for v in report['success_rate'][1]]})")
    print(f"fall        {report['fall_rate'][0]*100:.1f}%")
    print(f"descent     {report['descent_rate'][0]*100:.1f}%  (mouth reached ground)")
    print(f"upright     {report['upright_rate'][0]*100:.1f}%  (reached upright)")
    print(f"return      {report['return_rate'][0]*100:.1f}%  (mouth rose back up)")
    if args.phase_cap is not None:
        print(f"phase-cap {args.phase_cap}: cutoff-ok {report['cap_cutoff_ok_rate'][0]*100:.1f}%  "
              f"(iqr {[round(v*100,1) for v in report['cap_cutoff_ok_rate'][1]]})  "
              f"[mouth {report['cap_mouth_height_m_median']:.3f} m / upright {report['cap_upright_median']:.3f}]")
        pct = report['cap_mouth_height_m_median'] / report['standing_mouth_height_m'] * 100
        print(f"   -> at real take cutoff duck is ~{pct:.0f}% of standing height, upright {report['cap_upright_median']:.2f}")
    if args.json:
        print(f"json -> {args.json}")


if __name__ == "__main__":
    main()
