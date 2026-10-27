# SPDX-License-Identifier: Apache-2.0
"""Is `Batch.expand` a real per-simulation model edit, or just a per-row echo?

The first version of this probe compared trunk sag and concluded "mass does not work",
which is not a conclusion the measurement supported: 92 um of sag is also what you get
when the write never reaches the physics. A write you can read back through the same
handle proves nothing. So read back a field mjbatch *derives*, and cross-check against
`plant.build()`, which does the same edit the supported way.

  1. expand("body_mass")*1.4 + set_const -> expand("body_subtreemass") should show 1.4x.
  2. The same batch, stepped, should end where plant.build(mass_scale=1.4) ends.
  3. expand("geom_friction")*0.1 -> a shoved robot should slide much further.

  python tools/probe_expand.py
"""

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
sys.path.insert(0, str(ROOT / "tools"))
import plant  # noqa: E402
import train_ppo as T  # noqa: E402
from mjbatch import Batch  # noqa: E402

STEPS = round(T.CTRL_DT / T.TIMESTEP)


def run(model, num, setup=None, shove=0.0, steps=250):
  """Settle `num` copies of `model`, optionally perturbing rows, then shove and coast."""
  batch = Batch(model, num)
  qpos, qvel, ctrl = (batch.bind(f) for f in ("qpos", "qvel", "ctrl"))
  batch.reset(np.arange(num), keyframe=model.key("STAND").id)
  batch.forward(np.arange(num))
  if setup is not None:
    setup(batch)
    batch.forward(np.arange(num))
  ctrl[:] = T.stand_pose()[1]
  for _ in range(steps):
    batch.step(nstep=STEPS)
  settled = qpos[:, 2].copy()
  if shove:
    qvel[:, 0] += shove
    for _ in range(25):
      batch.step(nstep=STEPS)
  return settled, qpos[:, :2].copy(), batch, model


def main():
  model = plant.build()
  total = model.body_mass.sum()
  print(f"template mass {total:.5f} kg")

  def heavy(batch):
    batch.expand("body_mass")[1] *= 1.4
    batch.expand("body_inertia")[1] *= 1.4
    batch.set_const(np.array([1]))

  print("\n1. does a derived model field see the edit?")
  _, _, batch, _ = run(model, 2, heavy, steps=1)
  sub = batch.expand("body_subtreemass")
  print(f"   body_subtreemass row0 {sub[0, 0]:.5f}  row1 {sub[1, 0]:.5f}  ratio {sub[1, 0] / sub[0, 0]:.4f}")

  print("\n2. does the physics agree with plant.build(mass_scale=1.4)?")
  a, _, _, _ = run(model, 1, steps=250)
  b, _, _, _ = run(plant.build(mass_scale=1.4), 1, steps=250)
  c, _, _, _ = run(model, 2, heavy, steps=250)
  print(f"   plant.build(mass_scale=1.4) trunk z {b[0]:.6f}")
  print(f"   expand path row 1            trunk z {c[1]:.6f}   (row 0 same batch {c[0]:.6f})")
  print(f"   agreement {abs(b[0] - c[1]) * 1e6:.1f} um; row0/row1 differ by {abs(c[0] - c[1]) * 1e6:.1f} um")

  print("\n3. is the floor friction per simulation? (1.0 m/s shove, 0.5 s of coast)")
  def slick(batch):
    batch.expand("geom_friction")[1, :, 0] *= 0.1

  _, xy_n, _, _ = run(model, 1, shove=1.0, steps=120)
  _, xy_b, _, _ = run(model, 2, slick, shove=1.0, steps=120)
  print(f"   mu 1.0  slide {np.linalg.norm(xy_n[0]):.4f} m")
  print(f"   in-batch: row0 mu 1.0 {np.linalg.norm(xy_b[0]):.4f} m, row1 mu 0.1 {np.linalg.norm(xy_b[1]):.4f} m")


if __name__ == "__main__":
  main()
