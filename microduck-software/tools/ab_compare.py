# SPDX-License-Identifier: Apache-2.0
"""Compare checkpoints on a fixed set of commands, under chosen sensor models.

Why a separate tool
-------------------
`robustness.py` answers "does it survive condition X", one condition at a time, and
`envelope.py` answers "where can it go", one checkpoint at a time. Neither answers the
question that decides between two candidate weights: *on the same commands, under the
same sensor model, which one is better, and is the improvement uniform or a swap?*

That distinction matters here. A fine-tune that trades backward walking for forward speed
looks like a win if you only report the mean over the sweep, and like what it is (a
capability swap) only if you keep the per-command columns. So the output is a matrix,
never a single score.

Usage
-----
    python tools/ab_compare.py --policy out/deploy61.pt --policy out/robust61_s.pt
    python tools/ab_compare.py --policy out/a.pt --policy out/b.pt --sensor official,clean
"""
import argparse
import pathlib
import sys

import numpy as np
import torch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "repo"))

import robustness as R  # noqa: E402
import train_official as O  # noqa: E402
import train_ppo as T  # noqa: E402
import train_robust as RB  # noqa: E402

# One command per direction the duck is asked to move. Keep backward and sideways in the
# set: they are the first things a forward-speed-optimising fine-tune gives up.
COMMANDS = {
  "fwd .30": [0.30, 0.0, 0.0],
  "fwd .50": [0.50, 0.0, 0.0],
  "back .25": [-0.25, 0.0, 0.0],
  "yaw .80": [0.0, 0.0, 0.80],
  "side .15": [0.0, 0.15, 0.0],
  "slow .10": [0.10, 0.0, 0.0],
}

# The two sensor paths that matter. `official` applies upstream's per-term lags (gyro and
# gravity one control period, joint_vel always one period, joint_pos none) -- that is the
# path the real robot has. `clean` disables every lag and is therefore out of distribution
# for any policy that was trained with the lags on; it is kept only as a reference point.
SENSORS = ("clean", "official")


def make_env(sensor, n, seed):
  if sensor == "official":
    return O.Duck(n, seed=seed, timestep=T.TIMESTEP)
  return RB.Duck(n, seed=seed, timestep=T.TIMESTEP, act_delay=(0, 0), obs_delay=(0, 0),
                 noise=0.0, push_dv=0.0, jvel_lag=0.0)


def load(path):
  ckpt = torch.load(path, map_location="cpu")
  net = T.ActorCritic(ckpt["obs_dim"])
  net.load_state_dict(ckpt["model"])
  net.eval()
  return net, ckpt["obs_dim"]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", action="append", required=True, help="repeatable")
  ap.add_argument("--sensor", default=",".join(SENSORS))
  ap.add_argument("--envs", type=int, default=12)
  ap.add_argument("--seconds", type=float, default=10.0)
  ap.add_argument("--seed", type=int, default=0)
  args = ap.parse_args()

  sensors = [s.strip() for s in args.sensor.split(",") if s.strip()]
  table = []
  for path in args.policy:
    net, dim = load(path)
    for sensor in sensors:
      env = make_env(sensor, args.envs, args.seed)
      cells = {}
      for name, cmd in COMMANDS.items():
        # Fresh env per command: a shared env would carry the previous command's terminal
        # state into the next cell (this exact bug cost me a bogus sweep in envelope.py).
        r = R.rollout(net, env, dim, cmd, args.seconds, args.seed,
                      official_lag=(sensor == "official"))
        cells[name] = r
        env.reset(np.arange(args.envs))
      table.append((pathlib.Path(path).stem, sensor, cells))

  print(f"\n{'policy':22}{'sensor':>10}" + "".join(f"{k:>10}" for k in COMMANDS))
  print("-" * (32 + 10 * len(COMMANDS)))
  for name, sensor, cells in table:
    row = "".join(f"{cells[k]['tracking_ratio']:+10.2f}" for k in COMMANDS)
    print(f"{name:22}{sensor:>10}{row}")
  print("\n(figures are tracking_ratio = signed velocity along the command / command "
        "magnitude; negative means it moved the wrong way)")

  print(f"\n{'policy':22}{'sensor':>10}" + "".join(f"{k:>10}" for k in COMMANDS))
  print("-" * (32 + 10 * len(COMMANDS)))
  for name, sensor, cells in table:
    row = "".join(f"{cells[k]['speed_mps_median']:+10.3f}" for k in COMMANDS)
    print(f"{name:22}{sensor:>10}{row}")
  print("\n(m/s, signed along the command)")

  print(f"\n{'policy':22}{'sensor':>10}" + "".join(f"{k:>10}" for k in COMMANDS))
  print("-" * (32 + 10 * len(COMMANDS)))
  for name, sensor, cells in table:
    row = "".join(f"{cells[k]['falls']:10d}" for k in COMMANDS)
    print(f"{name:22}{sensor:>10}{row}")
  print(f"\n(falls per cell, {args.envs} envs x {args.seconds:.0f} s)")

  # Tilt is not decoration. A policy that is falling over converts its own flailing into
  # net displacement, so a high tracking_ratio together with a high tilt_max means the
  # number is an artefact of the fall, not locomotion. Always read the two together.
  print(f"\n{'policy':22}{'sensor':>10}" + "".join(f"{k:>10}" for k in COMMANDS))
  print("-" * (32 + 10 * len(COMMANDS)))
  for name, sensor, cells in table:
    row = "".join(f"{cells[k]['tilt_max_deg']:10.1f}" for k in COMMANDS)
    print(f"{name:22}{sensor:>10}{row}")
  print("\n(max body tilt, degrees. above ~30 means it went over; a high tracking_ratio "
        "with a high tilt is the robot falling, not walking)")


if __name__ == "__main__":
  main()
