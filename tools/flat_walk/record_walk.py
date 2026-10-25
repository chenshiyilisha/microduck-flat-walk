"""Record a trained MicroDuck policy inside the real mjlab env (headless).

Why not `mjlab play --video`?
-----------------------------
mjlab's own `play.py` already has a `--video` path, and that path is what this
script reuses (same `load_env_cfg`, same `VideoRecorder`, same
`runner.get_inference_policy`). But `play.py` always **ends** in an interactive
viewer loop -- `NativeMujocoViewer(...).run()` / `ViserPlayViewer(...).run()`
(`mjlab/scripts/play.py:288-291`) -- so the process never returns on its own and
`--video` only decides whether the first `video_length` steps get written
(`play.py:170-179`). For "run it once and hand me the clip" that is the wrong
shape.

Upstream hit the same wall and solved it with a pure-addition recorder:
DuckEMW `docs/04-stilts-repro.md:58`
    「可信路径：`scripts/record_stilt_play.py`（纯新增）——在 mjlab 训练环境内
      无头录制，物理/观测/DR 与课程门禁完全一致。」
and `docs/04-stilts-repro.md:30` lists the artefacts it produced
(`videos/stilt_h{10..200}cm.mp4`, 6 s @ 50 fps). Their script lives in a
submodule we cannot read (404), so this is the same idea re-expressed on top of
the public mjlab API rather than a copy.

Protocol carried over from `eval_velocity_in_sim.py` (see docs/05-flat-walk.md):
  * `standing_envs` curriculum is **popped**. It rewrites `rel_standing_envs`
    every step from `common_step_counter` (mdp.py:3440-3474) and would otherwise
    tell 25% of the batch to stand still -- you would be filming a quarter of the
    ducks doing nothing while believing it is a walking clip.
  * the command is frozen to one value for the whole clip, so what you see is
    the same condition the 11 gates were measured under.
  * the curriculum counter is re-pinned every step (same reason as the evaluator:
    reproducibility that actually holds).

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/record_walk.py \
        --checkpoint logs/rsl_rl/microduck_velocity/<run>/model_1250.pt \
        --seconds 8 --width 1280 --height 720 --out out/walk_1250.mp4

On Windows the offscreen renderer goes through `mujoco.Renderer`
(`mjlab/viewer/offscreen_renderer.py:57`), i.e. OpenGL; `MUJOCO_GL=glfw` is set
by default here because `egl` is not available on Windows.
"""

# ruff: noqa: E402  (sys.path must be fixed before the sibling import)

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_velocity_in_sim import (  # noqa: E402
    drop_pushes,
    freeze_command,
    override_solver,
    pin_curriculum,
)

DEFAULT_TASK = "Mjlab-Velocity-Flat-MicroDuck"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Headless recording of a trained policy.")
    p.add_argument("--checkpoint", required=True, help="path to model_<iter>.pt")
    p.add_argument("--out", required=True, help="output .mp4 path")
    p.add_argument("--task", default=DEFAULT_TASK)
    p.add_argument("--num-envs", type=int, default=1,
                   help="only env 0 is filmed (VideoRecorder behaviour); extra "
                        "envs are useful to see batch diversity in the same run")
    p.add_argument("--seconds", type=float, default=8.0)
    p.add_argument("--cmd-vx", type=float, default=0.4)
    p.add_argument("--cmd-vy", type=float, default=0.0)
    p.add_argument("--cmd-wz", type=float, default=0.0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    # Camera overrides. The default viewer config is built for "watch a whole
    # scene" (mjlab/viewer/viewer_config.py:30-34: distance 5.0, elevation -45),
    # which leaves a 40 cm duck as a dozen pixels. Upstream's own render script
    # exposes exactly these four knobs for the same reason (README.md:76
    # "支持 --width/--height/--seed/--duration/--fps 与 --lookat/--distance/
    # --elevation/--azimuth 机位覆盖").
    p.add_argument("--distance", type=float, default=1.6)
    p.add_argument("--elevation", type=float, default=-18.0)
    p.add_argument("--azimuth", type=float, default=100.0)
    p.add_argument("--lookat", type=float, nargs=3, default=(0.0, 0.0, 0.10),
                   metavar=("X", "Y", "Z"))
    # `reset_base` spawns the robot with `yaw: (-3.14, 3.14)` and `x`/`y` in
    # +-0.5 m (mjlab/tasks/velocity/velocity_env_cfg.py:205-210). Random yaw is
    # correct for training diversity and fatal for a *fixed world-frame camera*:
    # the same `--azimuth 180` gave a front view on one reset and a rear view on
    # the next, so "side view" was not reproducible until this was pinned.
    p.add_argument("--yaw-deg", type=float, default=0.0,
                   help="pin the spawn heading (world frame); 0 = facing +x")
    p.add_argument("--random-yaw", action="store_true",
                   help="keep the training-time random yaw (clips will not be "
                        "comparable frame-to-frame)")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--solver-iters", type=int, default=100)
    p.add_argument("--solver-ls", type=int, default=50)
    p.add_argument("--keep-envs", action="store_true",
                   help="do not pop the standing_envs curriculum (negative control)")
    p.add_argument("--dry-run", action="store_true",
                   help="build everything, print the plan, write no video")
    return p.parse_args()


def main() -> int:
    a = parse_args()

    os.environ.setdefault("MUJOCO_GL", "glfw")

    import torch

    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends
    from mjlab.utils.wrappers import VideoRecorder

    configure_torch_backends()
    torch.manual_seed(a.seed)

    ckpt = Path(a.checkpoint)
    if not ckpt.exists():
        sys.exit(f"checkpoint not found: {ckpt}")

    env_cfg = load_env_cfg(a.task)
    agent_cfg = load_rl_cfg(a.task)
    env_cfg.scene.num_envs = a.num_envs
    if hasattr(env_cfg, "seed"):
        env_cfg.seed = a.seed

    freeze_command(env_cfg, a.cmd_vx, a.cmd_vy, a.cmd_wz, a.seconds)
    if a.keep_envs:
        # Negative control: put the curriculum back. The clip should then show
        # some envs standing still even though "cmd vx 0.4" is printed below.
        env_cfg.curriculum["standing_envs"] = load_env_cfg(a.task).curriculum[
            "standing_envs"]
    dropped = drop_pushes(env_cfg)
    solver = override_solver(env_cfg, a.solver_iters, a.solver_ls, None)

    if not a.random_yaw:
        import math

        pose = env_cfg.events["reset_base"].params["pose_range"]
        pose["yaw"] = (math.radians(a.yaw_deg), math.radians(a.yaw_deg))
        pose["x"] = (0.0, 0.0)
        pose["y"] = (0.0, 0.0)

    env_cfg.viewer.width = a.width
    env_cfg.viewer.height = a.height
    env_cfg.viewer.distance = a.distance
    env_cfg.viewer.elevation = a.elevation
    env_cfg.viewer.azimuth = a.azimuth
    env_cfg.viewer.lookat = tuple(a.lookat)

    n_steps_fallback = int(round(a.seconds / 0.02))  # 50 Hz control, replaced below
    print(f"task        {a.task}")
    print(f"checkpoint  {ckpt}")
    print(f"command     vx={a.cmd_vx:+.2f} vy={a.cmd_vy:+.2f} wz={a.cmd_wz:+.2f}  "
          f"({a.num_envs} envs, filming env 0)")
    print(f"pipeline    {a.width}x{a.height}, seed {a.seed}, solver "
          f"{solver['after']['iterations']}/{solver['after']['ls_iterations']} "
          f"(upstream default {solver['before']['iterations']}/"
          f"{solver['before']['ls_iterations']})")
    print(f"camera      distance {a.distance} elev {a.elevation} azim {a.azimuth} "
          f"lookat {tuple(a.lookat)}")
    print(f"spawn       "
          f"{'random yaw (training distribution)' if a.random_yaw else f'yaw {a.yaw_deg:+.0f} deg at origin'}")
    print(f"curriculum  standing_envs "
          f"{'KEPT (negative control)' if a.keep_envs else 'popped'}; "
          f"push events dropped: {dropped or 'none'}")

    # VideoRecorder renders through the env's offscreen renderer, so the env must
    # be built in rgb_array mode (metadata render_modes at
    # mjlab/envs/manager_based_rl_env.py:171).
    env = ManagerBasedRlEnv(cfg=env_cfg, device=a.device, render_mode="rgb_array")

    u = env.unwrapped
    step_dt = float(u.step_dt)
    n_steps = int(round(a.seconds / step_dt))
    print(f"timing      step_dt={step_dt:.4f}s -> {n_steps} steps "
          f"({n_steps * step_dt:.2f}s @ {1.0 / step_dt:.0f} fps)")

    if a.dry_run:
        env.close()
        print("dry-run: nothing written")
        return 0

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="recwalk_"))

    h = VideoRecorder(
        env,
        video_folder=tmpdir,
        step_trigger=lambda step: step == 0,
        video_length=n_steps,
        name_prefix="walk",
        disable_logger=True,
    )
    h = RslRlVecEnvWrapper(h, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(a.task) or MjlabOnPolicyRunner
    runner = runner_cls(h, asdict(agent_cfg), device=a.device)
    runner.load(str(ckpt), load_cfg={"actor": True}, strict=True,
                map_location=a.device)
    policy = runner.get_inference_policy(device=a.device)

    obs, _ = h.reset()
    pin_curriculum(h)

    started = __import__("time").time()
    with torch.no_grad():
        for _ in range(n_steps):
            obs, _rew, _dones, _extras = h.step(policy(obs))
            # Same re-pin as the evaluator: the curriculum manager advances the
            # counter every step and a reset must not drag a term back.
            h.unwrapped.common_step_counter = 10**9

    produced = sorted(tmpdir.glob("*.mp4"))
    if not produced:
        h.unwrapped.close()
        sys.exit("no mp4 produced -- renderer probably failed; check MUJOCO_GL")

    shutil.move(str(produced[0]), str(out))
    shutil.rmtree(tmpdir, ignore_errors=True)
    h.unwrapped.close()

    size_mb = out.stat().st_size / 1048576
    print(f"wrote       {out}  ({size_mb:.2f} MB, {n_steps} frames, "
          f"{__import__('time').time() - started:.1f}s wall)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
