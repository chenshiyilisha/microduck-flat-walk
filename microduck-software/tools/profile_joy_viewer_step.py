"""Profile where one control step goes when rendering a single env in the viewer.

Motivation
----------
`viser` playback showed ~5 fps, i.e. ~200 ms per control step. MuJoCo Warp is
throughput-optimised: for one world the cost is dominated by kernel-launch and
host<->device latency, not by arithmetic. This script measures the three phases
the viewer loop runs every step so we can say which one is the 200 ms.

    obs = env.get_observations()   # sensor/observation pipeline
    act = policy(obs)              # MLP forward
    env.step(act)                  # decimation x mjw.step + reward/term

Timing is wall-clock around each phase with an explicit CUDA sync, because
warp/torch kernels are asynchronous: without the sync every phase reads ~0.

Run it *while training is running* to profile the contended case, and again
after training ends to profile the uncontended one. Comparing `--num-envs`
1 vs 64 shows whether the step is launch-bound (1 and 64 cost about the same)
or compute-bound (cost scales with envs).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import asdict


def _time(fn, sync, repeat: int):
    ts = []
    for _ in range(repeat):
        sync()
        t0 = __import__("time").perf_counter()
        out = fn()
        sync()
        ts.append((__import__("time").perf_counter() - t0) * 1e3)
    return out, ts


def profile(task_id: str, checkpoint: str, num_envs: int, device: str, repeat: int):
    import torch

    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(task_id, play=False)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs
    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    u = env.unwrapped
    step_dt = float(u.step_dt)
    decimation = getattr(u.cfg, "decimation", None)
    sync = torch.cuda.synchronize if device.startswith("cuda") else (lambda: None)

    obs, _ = env.reset()
    with torch.no_grad():
        for _ in range(10):  # warmup: cuda graph replay, allocator, JIT
            obs = env.get_observations()
            env.step(policy(obs))

    with torch.no_grad():
        obs, t_obs = _time(lambda: env.get_observations(), sync, repeat)
        act, t_act = _time(lambda: policy(obs), sync, repeat)
        _, t_step = _time(lambda: env.step(act), sync, repeat)
        # The viewer also reads foot site heights to draw / report: that is a
        # device->host copy and therefore a full pipeline sync every frame.
        robot = u.scene["robot"]
        _, t_foot = _time(
            lambda: robot.data.site_pos_w[..., 2].mean().item(), sync, repeat
        )

    def med(x):
        return statistics.median(x)

    total = med(t_obs) + med(t_act) + med(t_step) + med(t_foot)
    return {
        "num_envs": num_envs,
        "device": device,
        "step_dt": step_dt,
        "decimation": decimation,
        "ms": {
            "obs": med(t_obs),
            "policy": med(t_act),
            "env_step": med(t_step),
            "foot_readback": med(t_foot),
            "total": total,
        },
        "per_physics_substep_ms": med(t_step) / decimation if decimation else None,
        "implied_fps": 1000.0 / total,
        "implied_realtime_factor": step_dt / (total / 1e3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Mjlab-JoySmoothPD-Flat-MicroDuck")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, nargs="+", default=[1, 64])
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--repeat", type=int, default=30)
    args = ap.parse_args()

    rows = []
    for n in args.num_envs:
        r = profile(args.task, args.checkpoint, n, args.device, args.repeat)
        rows.append(r)
        m = r["ms"]
        print(
            f"envs={r['num_envs']:<5} total={m['total']:8.2f} ms "
            f"[obs {m['obs']:6.2f} | policy {m['policy']:6.2f} | "
            f"step {m['env_step']:7.2f} | readback {m['foot_readback']:5.2f}] "
            f"-> {r['implied_fps']:6.1f} fps, realtime x{r['implied_realtime_factor']:.3f}",
            flush=True,
        )

    if len(rows) >= 2:
        a, b = rows[0], rows[1]
        ratio = b["ms"]["env_step"] / a["ms"]["env_step"]
        env_ratio = b["num_envs"] / a["num_envs"]
        print(
            f"\nenv_step cost grew {ratio:.2f}x while env count grew {env_ratio:.0f}x "
            f"-> {'LAUNCH-BOUND (GPU idle, waiting on kernel dispatch)' if ratio < env_ratio / 4 else 'compute-bound'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
