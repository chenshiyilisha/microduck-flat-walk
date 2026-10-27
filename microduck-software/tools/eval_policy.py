# SPDX-License-Identifier: Apache-2.0
"""Objective evaluation of a Microduck policy: does it actually go where it is told?

  python tools/eval_policy.py --policy repo/microduck_policy.pt --command 0.4,0,0 --seconds 8

Unlike render_policy.py, this never touches a renderer. It runs N parallel copies of the
same fixed command, propagates each with its own jittered reset, and reports the measured
mean base velocity against the commanded one. That number is the only thing worth quoting.

Outputs one JSON line so runs can be diffed and compared across policies.

Scale note: a Microduck is 0.25 m tall and the default episode is 10 s. At 0.3 m/s that is
3 m of travel, i.e. twelve body lengths. Anything in the 0.6-0.8 ratio band is normal for
a locomotion policy trained with these rewards; see README's own "asked for 0.3, walks 0.21".
"""

import argparse
import json
import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
import train_ppo as T  # noqa: E402


def quat_up_world_z(q):
  """Vertical component of the body z-axis, from a (w,x,y,z) quaternion. 1.0 = perfectly upright."""
  w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
  return 1.0 - 2.0 * (x * x + y * y)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", type=pathlib.Path, default=ROOT / "repo" / "microduck_policy.pt")
  ap.add_argument("--command", default="0.4,0,0", help="forward m/s, sideways m/s, yaw rad/s")
  ap.add_argument("--seconds", type=float, default=8.0)
  ap.add_argument("--envs", type=int, default=16, help="independent rollouts, reported as median+iqr")
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--json", action="store_true", help="emit a single json line instead of a table")
  args = ap.parse_args()

  ckpt = torch.load(args.policy, map_location="cpu")
  timestep = ckpt.get("timestep", T.TIMESTEP)
  net = T.ActorCritic(ckpt.get("obs_dim", T.OBS_DIM))
  net.load_state_dict(ckpt["model"])
  net.eval()

  if ckpt.get("task", "velocity") == "ball-balance":
    raise SystemExit("eval_policy.py only measures the velocity task; ball-balance ends by design")

  env = T.Duck(args.envs, seed=args.seed, timestep=timestep)
  cmd = np.array([float(v) for v in args.command.split(",")], np.float32)

  # Pin the command: step() decrements `until` and resamples when it hits zero, so hold it open.
  env.command[:], env.until[:] = cmd, 1e9

  start = env.qpos[:, :3].copy()
  path_len = np.zeros(args.envs)          # integrated horizontal distance, ignores drift reversal
  prev = start[:, :2].copy()
  falls = np.zeros(args.envs, bool)
  upright_min = np.ones(args.envs)

  steps = int(args.seconds / T.CTRL_DT)
  for _ in range(steps):
    with torch.no_grad():
      action = net(torch.as_tensor(env.obs()))[0].numpy()
    _, done, _, _ = env.step(action)
    env.command[:], env.until[:] = cmd, 1e9

    xy = env.qpos[:, :2]
    path_len += np.linalg.norm(xy - prev, axis=1)
    prev = xy.copy()
    falls |= done
    upright_min = np.minimum(upright_min, quat_up_world_z(env.qpos[:, 3:7]))

  elapsed = steps * T.CTRL_DT
  disp = env.qpos[:, :2] - start[:, :2]
  # Base forward axis is +x in this MJCF; project displacement on the command's heading.
  heading = np.array([1.0, 0.0]) if abs(cmd[0]) >= abs(cmd[1]) else np.array([0.0, 1.0])
  if cmd[0] < 0 or (cmd[0] == 0 and cmd[1] < 0):
    heading = -heading
  proj = disp @ heading

  speed = proj / elapsed
  result = {
    "policy": str(args.policy),
    "command": cmd.tolist(),
    "seconds": elapsed,
    "envs": args.envs,
    "falls": int(falls.sum()),
    "speed_mps_median": round(float(np.median(speed)), 4),
    "speed_mps_iqr": [round(float(np.percentile(speed, 25)), 4), round(float(np.percentile(speed, 75)), 4)],
    "path_m_median": round(float(np.median(path_len)), 3),
    "tracking_ratio": round(float(np.median(speed) / (np.linalg.norm(cmd) or 1.0)), 3),
    "upright_min": round(float(upright_min.min()), 3),
    "final_yaw_rate_median": round(float(np.median(env.qvel[:, 5])), 3),
  }

  if args.json:
    print(json.dumps(result, ensure_ascii=False))
  else:
    print(f"policy      {result['policy']}")
    print(f"command     fwd={cmd[0]:+.2f} m/s  side={cmd[1]:+.2f}  yaw={cmd[2]:+.2f} rad/s")
    print(f"duration    {elapsed:.1f} s x {args.envs} envs")
    print(f"falls       {result['falls']}/{args.envs}")
    print(f"speed       {result['speed_mps_median']:.3f} m/s "
          f"(iqr {result['speed_mps_iqr'][0]:.3f}-{result['speed_mps_iqr'][1]:.3f})")
    print(f"tracking    {result['tracking_ratio']*100:.0f}% of commanded")
    print(f"path        {result['path_m_median']:.2f} m (integrated, {result['path_m_median']/0.25:.1f} body lengths)")
    print(f"upright     worst {result['upright_min']:.3f} (1.0 = never tilted)")


if __name__ == "__main__":
  main()
