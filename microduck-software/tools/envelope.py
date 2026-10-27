# SPDX-License-Identifier: Apache-2.0
"""What command range can this policy actually hold?

`tools/robustness.py` answers "does it survive this plant/loop change at 0.3 m/s". This answers
a different question: **across the command space, where does it stop working** -- and it is the
only way to compare the 56-D and 61-D checkpoints on something other than the one nominal
condition they were both tuned near.

The distinction matters because upstream's command sampling is not symmetric. `lin_vel_x` is
sampled to 0.5 m/s forward but the reward's tracking kernel saturates, so a policy can report a
fine tracking ratio at 0.3 and be at its limit there, while 0.5 is already unreachable. A single
number hides that; a sweep does not.

Run against the nominal plant only. Anything else and the sweep stops being about the command.

  python tools/envelope.py --policy out/deploy61.pt
  python tools/envelope.py --policy out/deploy61.pt --policy out/microduck_own.pt --json
"""

import argparse
import json
import pathlib
import sys

import numpy as np
import torch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import robustness as R  # noqa: E402
import train_ppo as T  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# vx forward, vx back, vy both ways, yaw both ways. Values bracket upstream's sampling range
# (lin_vel_x 0-0.5, lin_vel_y +-0.3, ang_vel_z +-1.0) so the edges show up as a slope, not a
# cliff at the last point.
SWEEP = (
  [(v, 0.0, 0.0) for v in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)]
  + [(v, 0.0, 0.0) for v in (-0.10, -0.20, -0.30)]
  + [(0.0, v, 0.0) for v in (0.10, 0.20, -0.10, -0.20)]
  + [(0.0, 0.0, v) for v in (0.30, 0.60, 0.90, -0.30, -0.60)]
)

GATES = {"tracking_min": 0.55, "falls_max": 2}  # per point, on 8 envs x 12 s


def sweep(net, obs_dim, env, seconds, seed):
  rows = []
  for command in SWEEP:
    # Reset between points. `rollout` does not do it, and reusing the env carries the previous
    # command's terminal state into the next measurement: the robot starts the next point from
    # wherever it drifted to, or from the ground. That corruption grows with `seconds`, which
    # is why a 6 s sweep looked healthy and the same sweep at 12 s reported every forward
    # command as a failure.
    env.reset(np.arange(env.num_envs))
    r = R.rollout(net, env, obs_dim, command, seconds, seed)
    ok = r["tracking_ratio"] >= GATES["tracking_min"] and r["falls"] <= GATES["falls_max"]
    rows.append(
      dict(
        cmd=command,
        command=",".join(f"{c:+.2f}" for c in command),
        kind=r["metric"],
        tracking=round(r["tracking_ratio"], 3),
        speed=round(r["speed_mps_median"], 3),
        yaw=round(r["yaw_rate_median"], 3),
        falls=r["falls"],
        tilt=round(r["tilt_max_deg"], 1),
        hdg=round(r["heading_error_deg_median"], 0),
        ok=bool(ok),
      )
    )
  return rows


def table(rows):
  print(f"{'command':>17} {'metric':>8} {'track':>6} {'speed':>6} {'yaw/s':>6} {'falls':>5} {'tilt':>5} {'hdg':>4}  ")
  for r in rows:
    mark = "ok  " if r["ok"] else "FAIL"
    print(
      f"{r['command']:>17} {r['kind']:>8} {r['tracking']:6.3f} {r['speed']:6.3f} "
      f"{r['yaw']:6.3f} {r['falls']:5d} {r['tilt']:5.1f} {r['hdg']:4.0f}  {mark}"
    )


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", action="append", type=pathlib.Path, required=True, help="repeatable")
  ap.add_argument("--seconds", type=float, default=12.0, help="6 s is too short: the startup transient dominates net displacement and flips the sign of a backward sweep")
  ap.add_argument("--envs", type=int, default=8)
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--json", action="store_true")
  args = ap.parse_args()

  out = {}
  for path in args.policy:
    ckpt = torch.load(path, map_location="cpu")
    obs_dim = ckpt["obs_dim"]
    net = T.ActorCritic(obs_dim)
    net.load_state_dict(ckpt["model"])
    net.eval()
    env = R.ENV_BY_WIDTH[obs_dim](args.envs, seed=args.seed, timestep=T.TIMESTEP)
    rows = sweep(net, obs_dim, env, args.seconds, args.seed)
    out[str(path)] = dict(obs_dim=obs_dim, points=rows)

    if args.json:
      continue
    held = [r for r in rows if r["ok"]]
    fwd = [r["cmd"][0] for r in held if r["cmd"][1] == 0.0 and r["cmd"][2] == 0.0 and r["cmd"][0] > 0]
    print(f"\n=== {path}  ({obs_dim}-D) ===")
    table(rows)
    print(f"  held {len(held)}/{len(rows)} points; forward max {max(fwd, default=0.0):+.2f} m/s")

  if args.json:
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
  main()
