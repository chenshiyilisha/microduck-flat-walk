# SPDX-License-Identifier: Apache-2.0
"""Export a trained checkpoint to ONNX, with observation normalization baked in.

  python tools/export_onnx.py --policy repo/microduck_policy.pt --out out/walk.onnx

Why this script exists
----------------------
The upstream microduck_rl playbook calls this out as a distinct failure mode: the policy's
observation running-mean/variance must be folded into the exported graph. If it is not, the
network sees raw observations at deploy time while it was trained on normalized ones, and the
result is a robot that behaves correctly in the viewer and not at all on hardware. The bug is
invisible inside the sim because the sim always normalizes in Python before calling the net.

ActorCritic.forward already normalizes, and `mean`/`var` are registered buffers, so tracing the
actor naturally captures them as constants. This script verifies that claim rather than assuming
it: it runs both backends on the same observations and asserts the outputs agree.

The exported graph takes (B, obs_dim) float32 and returns (B, act_dim) — the deterministic mean
action, not a sample. A deployed controller should use the mean: sampling at 50 Hz adds noise
that the torque limits then have to absorb.

This policy expects actions in normalized joint space; the target is
`ctrl = stand_pose + ACTION_SCALE * action`. That offset lives outside the graph on purpose —
it is a property of the robot's rest pose, not of the learned controller.
"""

import argparse
import pathlib
import sys

import numpy as np
import torch
from torch import nn

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
import train_ppo as T  # noqa: E402


class ActorOnly(nn.Module):
  """Trim the critic and the sampling head: deploy-time graphs should have one output."""

  def __init__(self, net):
    super().__init__()
    self.net = net

  def forward(self, obs):
    return self.net.actor((obs - self.net.mean) / (self.net.var.sqrt() + 1e-5))


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", type=pathlib.Path, default=ROOT / "repo" / "microduck_policy.pt")
  ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out" / "policy.onnx")
  ap.add_argument("--opset", type=int, default=17)
  ap.add_argument("--samples", type=int, default=256, help="observations used for the parity check")
  ap.add_argument("--seed", type=int, default=0)
  args = ap.parse_args()

  ckpt = torch.load(args.policy, map_location="cpu")
  obs_dim = ckpt.get("obs_dim", T.OBS_DIM)
  net = T.ActorCritic(obs_dim)
  net.load_state_dict(ckpt["model"])
  net.eval()

  wrapper = ActorOnly(net).eval()

  # Draw from the policy's own running distribution plus a wider band, so the parity check
  # covers the region a real controller will actually visit, not just the mean.
  rng = np.random.default_rng(args.seed)
  scale = net.var.sqrt().detach().numpy()
  obs = rng.standard_normal((args.samples, obs_dim)).astype(np.float32) * scale * 2.0 + net.mean.detach().numpy().astype(np.float32)
  x = torch.as_tensor(obs)

  args.out.parent.mkdir(parents=True, exist_ok=True)
  with torch.no_grad():
    ref = wrapper(x).numpy()

  torch.onnx.export(
    wrapper,
    (x,),
    str(args.out),
    input_names=["obs"],
    output_names=["action"],
    opset_version=args.opset,
    dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
    do_constant_folding=True,
  )

  import onnxruntime as ort

  sess = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])
  got = sess.run(None, {"obs": obs})[0]
  diff = float(np.abs(got - ref).max())

  # The normalization must be inside the graph. If it were missing, feeding already-normalized
  # input would be a no-op and raw input would be off by roughly the scale factor; compare both.
  with torch.no_grad():
    unnormalized_pred = sess.run(None, {"obs": np.zeros_like(obs)})[0]
    torch_zero = wrapper(torch.zeros_like(x)).numpy()

  print(f"checkpoint   {args.policy}")
  print(f"obs_dim      {obs_dim}   act_dim {ckpt.get('act_dim', T.ACT_DIM)}   timestep {ckpt.get('timestep', T.TIMESTEP)}")
  print(f"opset        {args.opset}")
  print(f"onnx         {args.out}  ({args.out.stat().st_size / 1024:.1f} KiB)")
  print(f"parity       max |torch - ort| = {diff:.2e}  over {args.samples} obs")
  print(f"normalized   zero-input parity = {float(np.abs(unnormalized_pred - torch_zero).max()):.2e}")

  if diff > 1e-4:
    raise SystemExit(f"FAIL: backends disagree by {diff:.2e}; do not deploy this graph")
  if np.abs(ref).max() == 0.0:
    raise SystemExit("FAIL: the actor returned all zeros; the checkpoint is probably not trained")
  print("ok           normalization is inside the graph and both backends agree")


if __name__ == "__main__":
  main()
