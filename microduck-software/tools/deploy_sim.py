# SPDX-License-Identifier: Apache-2.0
"""Run the exported ONNX in a loop that looks like the robot's, not like training.

Why this file exists
--------------------
`export_onnx.py` proves the graph agrees with PyTorch on identical inputs. That is an
*open-loop* check, and it cannot catch the failure that actually bites: a closed-loop policy
is a feedback system, so a 1e-7 numerical difference per tick can grow into a different gait,
and a safety clamp that was never in training can move the attractor somewhere else entirely.

So this tool closes the loop with the graph, and with the parts of the runtime that are not
the graph:

  the ONNX session   — the artifact, not the checkpoint, is what ships
  a latency buffer   — observations and actions arrive late (3-6 periods at 50 Hz upstream)
  a safety layer     — NaN guard, per-tick rate limit, joint-range clamp, all of which the
                       real `duck-control` has and training never sees

The question it answers is the one that matters before shipping: *does the deployed stack
still walk, and does it walk the same way the checkpoint did?*

  python tools/deploy_sim.py --onnx out/deploy61.onnx --policy out/deploy61.pt \\
      --conditions nominal,latency_60ms --safety
"""

import argparse
import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
sys.path.insert(0, str(ROOT / "tools"))
import plant  # noqa: E402
import robustness  # noqa: E402
import train_official as O  # noqa: E402
import train_ppo as T  # noqa: E402


class SafetyLayer:
  """The three limits `duck-control/src/safety.rs` actually applies, in its order.

  That file is explicit about what it does and does not protect, and the difference matters:

    NotFinite  a NaN or infinite target is *refused*, not clamped: the previous target stays.
    Range      targets are held inside the actuator's travel, which upstream defines as
               ACTUATOR_MIN..ACTUATOR_MAX = -pi..pi. It is the actuator's one-turn range, not a
               per-joint anatomical limit, because the robot's real limits live in the MJCF and
               are not vendored in the runtime. Upstream says so plainly rather than implying
               protection it does not have.
    Deadman    intents older than 500 ms zero the velocity. Not modelled here: this loop is a
               policy driving MuJoCo directly, with no intent channel to go stale.

  A per-tick rate limit is available but off by default, because upstream has none. When it is
  switched on it has to sit above the gait's own worst step (measured: median 0.36 rad/tick,
  p100 0.61 on the 56-D walk) or it silently becomes the controller.
  """

  ACTUATOR_MIN, ACTUATOR_MAX = -np.pi, np.pi

  def __init__(self, stand, lower=None, upper=None, pos_frac=None, max_delta=0.0, max_offset=None):
    self.stand = stand
    self.max_delta = max_delta  # 0 disables, which is the upstream behaviour
    self.max_offset = max_offset  # optional bound on the action itself; None = unbounded
    self.prev = np.zeros_like(stand)  # last accepted target, in action space
    self.lower, self.upper = lower, upper
    self.pos_frac = pos_frac
    self.counts = dict(notfinite=0, range=0, rate=0, steps=0)

  def __call__(self, action):
    self.counts["steps"] += action.shape[0]
    finite = np.isfinite(action).all(1, keepdims=True)
    self.counts["notfinite"] += int((~finite).sum())
    action = np.where(finite, action, self.prev)

    target = self.stand + action
    if self.pos_frac is not None and self.lower is not None:
      lo = self.stand + (self.lower - self.stand) * self.pos_frac
      hi = self.stand + (self.upper - self.stand) * self.pos_frac
    else:
      lo, hi = self.ACTUATOR_MIN, self.ACTUATOR_MAX
    clipped = np.clip(target, lo, hi)
    self.counts["range"] += int((np.abs(clipped - target) > 1e-9).any(1).sum())

    if self.max_delta:
      raw = clipped - (self.stand + self.prev)
      self.counts["rate"] += int((np.abs(raw) > self.max_delta).any(1).sum())
      clipped = self.stand + self.prev + np.clip(raw, -self.max_delta, self.max_delta)

    out = clipped - self.stand
    if self.max_offset:
      out = np.clip(out, -self.max_offset, self.max_offset)
    self.prev = out
    return out.astype(np.float32)


class OnnxPolicy:
  """Adapter so the robustness rollout can drive an ONNX session exactly like a torch net."""

  def __init__(self, path, safety=None, lead=0.0):
    import onnxruntime as ort

    self.sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    self.input = self.sess.get_inputs()[0].name
    self.safety = safety
    self.lead = lead
    self.prev = None

  def __call__(self, obs_tensor):
    obs = obs_tensor.numpy() if hasattr(obs_tensor, "numpy") else np.asarray(obs_tensor)
    action = self.sess.run(None, {self.input: obs.astype(np.float32)})[0]
    if self.lead and self.prev is not None:
      # Phase lead: extrapolate where the command is heading instead of where it was. A policy
      # trained with no delay reacts to the state it can see; on a loop with 60 ms of lag it is
      # always steering by old news, so the correction arrives a third of a step late. One extra
      # term proportional to the change in output is the cheapest possible fix, and unlike
      # retraining it is a number a control engineer can tune at bring-up.
      action = action + self.lead * (action - self.prev)
    self.prev = action.copy()
    if self.safety is not None:
      action = self.safety(action)
    return (action,)


class TorchPolicy:
  def __init__(self, net):
    self.net = net

  def __call__(self, obs):
    with torch.no_grad():
      return (self.net(obs)[0].numpy(),)


def run(name, policy, env, obs_dim, cmd, args, control):
  got = robustness.rollout(policy, env, obs_dim, cmd, args.seconds, args.seed, **control)
  got["condition"] = name
  return got


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--onnx", type=pathlib.Path, required=True)
  ap.add_argument("--policy", type=pathlib.Path, default=None, help="checkpoint to compare against")
  ap.add_argument("--conditions", default="nominal,latency_60ms")
  ap.add_argument("--command", default="0.3,0,0")
  ap.add_argument("--seconds", type=float, default=8.0)
  ap.add_argument("--envs", type=int, default=8)
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--safety", action="store_true", help="wrap the ONNX in the deployment clamps")
  ap.add_argument("--max-delta", type=float, default=0.0, help="rate limit, rad per tick; 0 = off, as upstream")
  ap.add_argument("--pos-frac", type=float, default=None, help="fraction of MJCF joint range; unset = upstream's +-pi actuator travel")
  ap.add_argument("--lead", type=float, default=0.0, help="phase-lead gain on the action derivative")
  ap.add_argument("--json", action="store_true")
  args = ap.parse_args()

  names = [c.strip() for c in args.conditions.split(",")]
  cmd = [float(v) for v in args.command.split(",")]

  ref = None
  if args.policy:
    ckpt = torch.load(args.policy, map_location="cpu")
    obs_dim = ckpt.get("obs_dim", T.OBS_DIM)
    ref = T.ActorCritic(obs_dim)
    ref.load_state_dict(ckpt["model"])
    ref.eval()
    ref = TorchPolicy(ref)
    timestep = ckpt.get("timestep", T.TIMESTEP)
  else:
    import onnx

    obs_dim = onnx.load(str(args.onnx)).graph.input[0].type.tensor_type.shape.dim[1].dim_value
    timestep = T.TIMESTEP

  rows = []
  for name in names:
    kwargs = dict(robustness.CONDITIONS[name])
    cond_cmd = kwargs.pop("command", cmd)
    model_kwargs = {k: v for k, v in kwargs.items() if k in robustness.PLANT_KEYS}
    control = {k: v for k, v in kwargs.items() if k not in robustness.PLANT_KEYS}

    env_cls = robustness.ENV_BY_WIDTH[obs_dim]
    env = env_cls(args.envs, seed=args.seed, timestep=timestep, model=plant.build(timestep=timestep, **model_kwargs))
    safety = None
    if args.safety:
      safety = SafetyLayer(
        env.stand.copy(), env.lower.copy(), env.upper.copy(),
        pos_frac=args.pos_frac, max_delta=args.max_delta,
      )
    onnx_got = run(name, OnnxPolicy(args.onnx, safety, lead=args.lead), env, obs_dim, cond_cmd, args, control)
    onnx_got["safety"] = safety.counts if safety else None

    row = dict(condition=name, onnx=onnx_got, torch=None)
    if ref is not None:
      env2 = env_cls(args.envs, seed=args.seed, timestep=timestep, model=plant.build(timestep=timestep, **model_kwargs))
      row["torch"] = run(name, ref, env2, obs_dim, cond_cmd, args, control)
    rows.append(row)

  if args.json:
    import json

    print(json.dumps(rows, ensure_ascii=False))
  else:
    print(f"onnx {args.onnx}   obs {obs_dim}   cmd {cmd}   {args.seconds:.0f}s x {args.envs} envs   safety={args.safety}")
    print(f"{'condition':<18}{'source':<8}{'track':>7}{'falls':>8}{'tilt':>7}{'surv':>7}")
    for row in rows:
      for source in ("torch", "onnx"):
        got = row[source]
        if got is None:
          continue
        print(
          f"{row['condition']:<18}{source:<8}{got['tracking_ratio']:>7.3f}{got['falls']:>5}/{got['envs']:<3}"
          f"{got['tilt_max_deg']:>6.1f}{got['survival']:>7.2f}"
        )
      if row["torch"] and row["onnx"]:
        d = abs(row["onnx"]["tracking_ratio"] - row["torch"]["tracking_ratio"])
        print(f"{'':<18}{'delta':<8}{d:>7.3f}  (closed-loop divergence between checkpoint and graph)")
      if row["onnx"]["safety"]:
        c = row["onnx"]["safety"]
        print(f"{'':<18}safety   notfinite {c['notfinite']}  range-clamp {c['range']}  rate-limit {c['rate']}  of {c['steps']} env-steps")


if __name__ == "__main__":
  main()
