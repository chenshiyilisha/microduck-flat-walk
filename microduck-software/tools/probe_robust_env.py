# SPDX-License-Identifier: Apache-2.0
"""Is the fine-tuning env itself hostile, or was it the learning rate?

Loads a checkpoint into `repo/train_robust.Duck` and rolls it out *without touching the
weights* (no gradient, no PPO). If the policy survives here, then `train_robust.py`'s collapse
was an optimiser problem (LR too high for a warm start), not a broken environment wrapper.

Reports per-variant: fall rate per 1000 env-steps, mean velocity-tracking of the reward term,
and the mean fall flag. `--randomisation off` turns delay/noise/push down to zero so the same
run can be compared against `tools/robustness.py`'s nominal condition.

  python tools/probe_robust_env.py --ckpt out/deploy61.pt
"""

import argparse
import pathlib
import sys

import numpy as np
import torch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "repo"))

import train_ppo as T  # noqa: E402
import train_robust as R  # noqa: E402


@torch.no_grad()
def rollout(net, env, steps):
  obs = env.obs()
  falls = 0
  track = []
  for _ in range(steps):
    mean, _ = net(torch.as_tensor(obs))
    _, done, fell, terms = env.step(mean.numpy())
    obs = env.obs()
    falls += int(fell.sum())
    track.append(terms["track"].mean())
    ids = np.flatnonzero(done)
    if ids.size:
      env.reset(ids)
      obs = env.obs()
  return falls, float(np.mean(track))


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--ckpt", type=pathlib.Path, default=pathlib.Path("out/deploy61.pt"))
  ap.add_argument("--num-envs", type=int, default=256)
  ap.add_argument("--steps", type=int, default=500)
  ap.add_argument("--timestep", type=float, default=T.TIMESTEP)
  args = ap.parse_args()

  ckpt = torch.load(args.ckpt, map_location="cpu")
  print(f"{args.ckpt}  obs_dim={ckpt['obs_dim']}  act_dim={ckpt.get('act_dim')}")

  variants = {
    # name: kwargs handed to R.Duck, overriding R.DEFAULTS
    "clean (no rand)": dict(act_delay=(0, 0), obs_delay=(0, 0), noise=0.0, push_dv=0.0, jvel_lag=False),
    "jvel_lag only": dict(act_delay=(0, 0), obs_delay=(0, 0), noise=0.0, push_dv=0.0, jvel_lag=1.0),
    "jvel lag 50%": dict(act_delay=(0, 0), obs_delay=(0, 0), noise=0.0, push_dv=0.0, jvel_lag=0.5),
    "noise only": dict(act_delay=(0, 0), obs_delay=(0, 0), noise=1.0, push_dv=0.0, jvel_lag=False),
    "act_delay 0-2": dict(act_delay=(0, 2), obs_delay=(0, 0), noise=0.0, push_dv=0.0, jvel_lag=False),
    "push only": dict(act_delay=(0, 0), obs_delay=(0, 0), noise=0.0, push_dv=0.3, jvel_lag=False),
    "full default": dict(),
  }

  print(f"\n{'variant':18} {'falls/1k':>9} {'fall%':>7} {'track':>7}")
  for name, kw in variants.items():
    env = R.Duck(args.num_envs, seed=1, timestep=args.timestep, **kw)
    net = T.ActorCritic(env.obs_dim)
    net.load_state_dict(ckpt["model"])
    net.eval()
    falls, track = rollout(net, env, args.steps)
    per_k = falls / (args.num_envs * args.steps) * 1000
    print(f"{name:18} {per_k:9.1f} {falls / args.num_envs * 100:6.1f}% {track:7.3f}")


if __name__ == "__main__":
  main()
