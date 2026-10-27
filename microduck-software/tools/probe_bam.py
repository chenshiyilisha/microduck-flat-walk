# SPDX-License-Identifier: Apache-2.0
"""How far is our stock position actuator from the servo BAM measured?

Why this file exists
--------------------
`train_ppo.py` drives the robot with MuJoCo's stock `<position>` actuator at kp 5.0, kv 0.3,
force +-0.96 N m. Upstream `microduck_rl` does not: it replaces the actuator with
`bam.mujoco.MujocoController`, which emulates the XL330's *firmware* -- a P loop at
`kp_fw = 200` producing a PWM duty cycle, then a DC-motor torque law

    tau = kt * V / R - kt^2 * qdot / R

with a current limit expressed as a duty-cycle constraint, a battery voltage that sags under
load, and a Coulomb/Stribeck/load-dependent friction budget written into `dof_frictionloss`
every physics step (BAM paper: Duclusaud et al., ICRA 2025). Two consequences matter here:

  * kp 200 is 40x our 5.0. If the two behave alike it is only because the torque ceiling is
    doing the work, and that is a claim to test rather than assume.
  * The back-EMF term `-kt^2 * qdot / R` is a genuine speed ceiling that falls out of the
    physics: as qdot rises the available torque falls to zero. A stock position actuator has
    no such term, which is why "does the slower HD1910 servo matter" could not be answered
    by the plant we were using. It can be answered by this one.

What is measured
----------------
Each actuator drives the 14 hinges of the real walking model along the same sinusoidal target,
one joint at a time (the others held), and the script reports gain and phase lag of the
achieved trajectory against the command. Gain << 1 or lag > a control period means the plant
the policy trained in does not have the bandwidth the policy assumed.

  python tools/probe_bam.py
"""

import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
sys.path.insert(0, str(ROOT / "tools"))
import plant  # noqa: E402
import train_ppo as T  # noqa: E402

import bam_actuators  # noqa: E402,F401  registers hl2915 / hd1910 before any load_model
from bam.model import load_model  # noqa: E402
from bam.mujoco import MujocoController  # noqa: E402

FREQS = (0.5, 1.0, 2.0, 3.0)  # Hz. A 20 ms control period already cannot represent 25 Hz;
AMP = 0.25  # rad, well inside every joint's range
SETTLE = 0.3  # s of run-in before the window that gets fitted

PARAMS = ROOT / "tools" / "bam_params"
# The three servos this project has had to choose between. xl330 ships with BAM; the other
# two are fitted elsewhere (see bam_actuators.py) and loaded from our own params tree.
#
# Which identification file, and why it is not the newest one
# ----------------------------------------------------------
# HL-2915 has five fits (m1/m3/m4/m5/m6). `fit_hl2915.py` documents the m6 command line, but
# `hl2915_constants.py` -- the file that actually configures the robot -- points at **m4**,
# "BAM m4 fitted on the pendulum bench (two loads, Kp 8-32, 0.53 deg mean error)", and every
# eval script in `training/bam/` defaults to m4.json. m6 is also the wrong motor: kt 0.848
# predicts 135 rpm at 12 V where the datasheet says 110, m4's 1.086 predicts 106. So m4 is the
# deployed model and m6 is a bench fit that ran away on the free parameters.
#
# xl330 is listed at kp_fw 200 to match `microduck_constants.py`'s `_BAM_ACTUATOR_KWARGS`
# ("microduck's preserved firmware stiffness"), not the 400 in BAM's bundled m6.json.
#
# Each servo appears at the two rail voltages it would actually see, because the back-EMF
# term is what limits speed and the rail is what the battery decides:
#   xl330   @7.5 V   full charge on the stock 2S rail
#   hl2915  @12.6 V  full charge on 3S / @9.9 V DuckBuddy's `robotd` empty threshold
#   hd1910  @5.0 V   where OpenMicroDuck identified it / @7.4 V on a 2S rail
MOTORS = (
  ("xl330", lambda: load_model(motor_name="xl330", model="m6"), 7.5, 200.0),
  ("hl2915@12.6V", lambda: load_model(str(PARAMS / "hl2915" / "m4.json")), 12.6, None),
  ("hl2915@9.9V", lambda: load_model(str(PARAMS / "hl2915" / "m4.json")), 9.9, None),
  ("hd1910@5.0V", lambda: load_model(str(PARAMS / "hd1910" / "m5.json")), None, None),
  ("hd1910@7.4V", lambda: load_model(str(PARAMS / "hd1910" / "m5.json")), 7.4, None),
)


def _spec(motor: bool):
  """The walking model with either stock position actuators or plain motors for BAM."""
  spec = mujoco.MjSpec.from_file(str(plant.XML))
  spec.option.timestep = T.TIMESTEP
  for actuator in spec.actuators:
    if motor:
      actuator.set_to_motor()  # BAM writes torque into ctrl, so the actuator must be direct-drive
    else:
      actuator.set_to_position(kp=T.KP, kv=T.KD)
      actuator.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
      actuator.forcerange = [-T.FORCE_LIMIT, T.FORCE_LIMIT]
  return spec


def _actuator_names(model):
  return [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(model.nu)]


def _hinge_dofs(model):
  return [
    model.jnt_dofadr[j] for j in range(model.njnt)
    if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE
  ]


def _hinge_qpos(model):
  return [
    model.jnt_qposadr[j] for j in range(model.njnt)
    if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE
  ]


def run(motor: bool, freq: float, bam_model=None, vin=None):
  """Drive every hinge along the same sine and return gain, lag and peak speed per joint."""
  spec = _spec(motor)
  model = spec.compile()
  data = mujoco.MjData(model)
  names = _actuator_names(model)
  dofs, qadr = _hinge_dofs(model), _hinge_qpos(model)

  # Start from the STAND keyframe so the joints are near where the policy holds them.
  mujoco.mj_resetDataKeyframe(model, data, model.key("STAND").id)

  controller = None
  if motor:
    if bam_model is None:
      raise ValueError("motor mode needs a BAM model")
    if vin is not None:
      bam_model.actuator.vin = vin
    # dof_frictionloss must be zero: BAM computes the whole friction budget itself and writes
    # it in every step. Leaving the MJCF value in place double-counts it -- upstream says this
    # explicitly ("standard MuJoCo friction is zeroed out because BAM computes it internally").
    model.dof_frictionloss[:] = 0.0
    controller = MujocoController(bam_model, names, model, data)
  else:
    # Symmetric: the stock actuator gets the same starting armature the BAM model installs,
    # so the comparison isolates the control law and friction rather than reflected inertia.
    if bam_model is not None:
      model.dof_armature[dofs] = bam_model.actuator.get_extra_inertia()

  base = data.qpos[qadr].copy()
  dt = model.opt.timestep
  n = int(round((SETTLE + 2.0 / freq) / dt))
  t = np.arange(n) * dt
  target = base[None, :] + AMP * np.sin(2 * np.pi * freq * t)[:, None]

  achieved = np.zeros((n, len(dofs)))
  for i in range(n):
    if controller is not None:
      controller.q_target = target[i]
      controller.update()
    else:
      data.ctrl[:] = target[i]
    mujoco.mj_step(model, data)
    achieved[i] = data.qpos[qadr]

  # Fit the second half of the window: the first half still carries the start-up transient.
  lo = n // 2
  tt = t[lo:]
  ref = AMP * np.sin(2 * np.pi * freq * tt)
  gain, lag = [], []
  for j in range(len(dofs)):
    y = achieved[lo:, j] - base[j]
    # Least-squares projection onto sin and cos at the drive frequency: the amplitude ratio is
    # the gain, the arctangent of the two coefficients is the phase. A plain peak-to-peak would
    # fold the start-up transient and the friction asymmetry into the answer.
    s, c = np.sin(2 * np.pi * freq * tt), np.cos(2 * np.pi * freq * tt)
    a = np.array([[s @ s, s @ c], [c @ s, c @ c]])
    b = np.array([s @ y, c @ y])
    sin_c, cos_c = np.linalg.solve(a, b)
    gain.append(np.hypot(sin_c, cos_c) / AMP)
    lag.append(-np.degrees(np.arctan2(cos_c, sin_c)))
  qvel = np.abs(np.diff(achieved, axis=0)).max(axis=0) / dt
  return np.array(gain), np.array(lag), qvel


def main():
  motors = {name: make() for name, make, _, _ in MOTORS}
  vins = {name: vin for name, _, vin, _ in MOTORS}
  kps = {name: kp for name, _, _, kp in MOTORS}
  for name, m in motors.items():
    # Set once, not per frequency: kp is a servo register, not something the sweep changes.
    if kps[name] is not None:
      m.actuator.kp = kps[name]
    eff = m.actuator.vin if vins[name] is None else vins[name]
    print(f"{name:<13} kt {m.kt.value:>7.4f} N m/A   R {m.R.value:>6.3f} ohm   "
          f"armature {m.actuator.get_extra_inertia():.6f}   vin {eff:>4.1f} V   "
          f"kp_fw {m.actuator.kp:>5.1f}   Imax {m.actuator.max_current} A   "
          f"no-load {eff / m.kt.value:>5.2f} rad/s")
  print(f"{'stock PD':<13} kp {T.KP}  kv {T.KD}  force +-{T.FORCE_LIMIT} N m   "
        f"armature {plant.build().dof_armature[_hinge_dofs(plant.build())[0]]:.6f}\n")

  print(f"{'f Hz':>5}  {'plant':<13}{'gain':>7}{'lag deg':>9}{'peak rad/s':>12}")
  rows = {}
  for f in FREQS:
    # The stock row is the plant the current checkpoint trained in -- one reference, not one
    # per servo, otherwise the comparisons would each have a different baseline.
    gain, lag, qvel = run(False, f, None)
    rows[(f, "stock PD")] = (gain, lag, qvel)
    print(f"{f:>5.1f}  {'stock PD':<13}{np.median(gain):>7.2f}{np.median(lag):>9.1f}"
          f"{qvel.max():>12.2f}")
    for name, m in motors.items():
      gain, lag, qvel = run(True, f, m, vins[name])
      rows[(f, name)] = (gain, lag, qvel)
      print(f"{'':>5}  {name:<13}{np.median(gain):>7.2f}{np.median(lag):>9.1f}"
            f"{qvel.max():>12.2f}")
    print()
  return rows


if __name__ == "__main__":
  main()
