# SPDX-License-Identifier: Apache-2.0
"""The plant a policy is measured in: one place that says which physics numbers are canon.

Why this file exists
--------------------
A policy number means nothing without the plant it was measured in. The DuckBench family
writes that lesson down as `PLANT.md`: two files both called `scene.mjb` had the same size
and different bytes, and for a while numbers from the two were being compared as if they
were the same measurement. Their fix was to declare one file canon and record why.

This tool is the same idea one level up. It does not name a file, it names the *numbers*,
because our plant is built from an MJCF plus a handful of overrides applied at load time:

  - `FORCE_STALL = 0.96` N m comes from the chosen actuator's stall figure and is what
    `train_ppo.py` has been using.
  - `FORCE_CURRENT = 0.6405` N m is kt x 1.75 A, the XL330's current limit, i.e. what the
    servo can actually hold before the driver folds back. DuckBench's PLANT.md records this
    as the number the plant should carry ("not the 0.96 stall figure").
  - `SOLVER_TRAINING = (10, 20)` is the solver mjlab trains with. Stock MuJoCo is 100/50,
    four times stiffer, which is another way the plant can quietly differ from training.

Nothing here decides which is right. It makes each choice nameable, so a measurement can say
which plant produced it, and so a policy can be evaluated in a plant it was *not* trained in.

  from plant import build, SPECS
  model = build(timestep=0.005, force_limit=SPECS["real_effort"]["force_limit"])
"""

import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
import train_ppo as T  # noqa: E402

XML = ROOT / "repo" / "microduck" / "lean" / "scene_walk.xml"

FORCE_STALL = 0.96  # train_ppo.FORCE_LIMIT: the actuator's stall figure
FORCE_CURRENT = 0.6405  # kt (0.366 N m/A) x 1.75 A, the driver's current limit
SOLVER_TRAINING = (10, 20)  # iterations, ls_iterations: what mjlab trains with
FLOOR_FRICTION = (1.0, 0.005, 0.0001)  # the value the upstream scene carries

# --- The servo actually being bought -------------------------------------------------------
# Every checkpoint in out/ was trained in the *upstream MJCF* numbers below, which describe a
# different servo family. The budget decision is HD1910, and its numbers are measured rather
# than read off a datasheet, so a "does the gait survive the servo swap" question is answerable
# before the money leaves the account.
#
# Source: JoyandAI/microduck_rl -> hd1910_calibration/params/ (bench identification on a real
# HD1910-C001: torque/current sweep for kt with r^2 = 0.99, pendulum swing for armature and
# damping, command-step for the delay). Do NOT use the Luwu 1910_m6.json numbers: that file is
# an STS3215 rename (`"actuator":"sts3215"`, max_velocity 100), not an HD1910.
XML_ARM = 0.001800  # armature in the MJCF this repo ships
XML_FRIC = 0.004800  # joint frictionloss in the same MJCF, one symmetric scalar
HD1910 = dict(
  armature=0.00224,      # +24% over the MJCF: reflected rotor inertia
  frictionloss=0.0136,   # the measured positive-direction figure; see the note below
  kt=0.692,              # N m/A, r^2 = 0.99
  resistance=3.75,       # ohm
  stall_6v=1.18,         # N m, the datasheet stall figure at 6 V
  stall_7v4=1.47,        # N m at 7.4 V
  no_load_rpm_6v=92.0,   # rev/min; the XL330 the design was written around is 123
  current_limit=3.25,    # A
  command_delay=0.0253,  # s, measured; 25.3 ms is *above* one 20 ms control period
  mass_g=22.0,           # vs the 18 g the MJCF bodies imply, so +4 g per servo
)
# Two things this plant does NOT model, stated here so no number is read as if it did:
#   1. frictionloss is asymmetric on a real gearbox (measured 0.0136 forward, 0.0081 reverse).
#      MuJoCo's dof_frictionloss is one symmetric scalar, so we carry the larger value. That
#      biases the plant toward over-damping, i.e. a pessimistic result, not an optimistic one.
#   2. No-load speed cannot be expressed by a stock position actuator: force is
#      kp*(ctrl-q) - kv*qvel clipped to forcerange, with no rate ceiling. Rather than invent
#      a fake damping that *looks* like a speed limit, the evaluator measures the joint speed
#      the policy actually reaches and compares it against the 92 rpm ceiling (9.63 rad/s).
#      If the gait never gets close, the slower servo does not matter; if it does, that is a
#      real regression and it is reported as one. Measure, then decide whether to model.

# Named plants. `nominal` is the one every checkpoint in out/ was trained in, so it is the
# only one where a number is self-consistent; the others exist to be failed in.
SPECS = {
  "nominal": {},
  "real_effort": {"force_limit": FORCE_CURRENT},
  "solver_training": {"solver": SOLVER_TRAINING},
  "upstream": {"force_limit": FORCE_CURRENT, "solver": SOLVER_TRAINING},
  # Servo swap, one axis at a time, so a failure can be attributed instead of blamed on
  # "the new servo" as a whole. Force stays at 0.96 for all of them: HD1910 stalls at 1.18
  # N m @ 6 V, so the torque the policy was trained against is still available with 23%
  # headroom, and raising it would flatter the result.
  "hd1910_arm": {"armature": HD1910["armature"]},
  "hd1910_fric": {"frictionloss": HD1910["frictionloss"]},
  "hd1910_mass": {"servo_mass_extra_g": HD1910["mass_g"] - 18.0},
  "hd1910": {
    "armature": HD1910["armature"],
    "frictionloss": HD1910["frictionloss"],
    "servo_mass_extra_g": HD1910["mass_g"] - 18.0,
  },
}


def _refresh_constants(model):
  """Recompute everything MuJoCo caches at compile time after an edit to the model.

  This used to recompute `body_subtreemass` and nothing else, which is not enough. mj_setConst
  also rebuilds `body_invweight0`, `dof_invweight0` and `actuator_acc0`, and those are what the
  constraint solver uses to regularise contacts. Leaving them at their unperturbed values is a
  plant that is heavy but is solved as if it were light -- the exact "written wrong, raises no
  error" shape this file exists to prevent.

  Measured (3x mass, settled from the STAND keyframe under position actuators):

      mass   body_invweight0        settled trunk z
      1.0x   1.7166  (correct)      0.116528
      1.4x   1.7166  (should be 1.2632)  0.116393   -> 42 um from the correct value
      3.0x   1.7166  (should be 0.6434)  0.115552   -> 222 um, and 63% wrong in the weight term

  With this call the two ways of building the same plant -- editing the model here, and
  `Batch.expand("body_mass")` + `set_const` per simulation -- agree to the last bit (0.0 um,
  qpos difference 0.000000). That agreement is what makes the number trustworthy; see
  `tools/probe_expand.py`.
  """
  mujoco.mj_setConst(model, mujoco.MjData(model))


def build(
  timestep=T.TIMESTEP,
  xml=XML,
  force_limit=None,
  solver=None,
  mass_scale=1.0,
  payload_kg=0.0,
  friction_scale=1.0,
  slope_deg=0.0,
  damping_scale=1.0,
  armature_scale=1.0,
  com_offset_x=0.0,
  armature=None,
  frictionloss=None,
  servo_mass_extra_g=0.0,
  integrator=None,
):
  """Compile the walking model with the requested physics overrides.

  mass_scale scales every body's mass *and* inertia together, then rebuilds the subtree
  masses: changing one without the other silently produces a robot that is heavy but turns
  like a light one, which is a physics bug rather than a perturbation.
  payload_kg adds mass at the trunk only, the way a battery or a hat would.

  `armature` and `frictionloss` are *absolute* values applied to the actuated hinge joints
  (the freejoint is left alone), because a servo swap is a replacement, not a scaling of the
  old servo. `armature_scale` stays for the multiplicative perturbations.
  `servo_mass_extra_g` adds that many grams to every body that carries a hinge, i.e. the
  heavier servo sits where the servo sits, not at the trunk.
  """
  spec = mujoco.MjSpec.from_file(str(xml))
  spec.option.timestep = timestep
  if solver is not None:
    spec.option.iterations, spec.option.ls_iterations = solver
  if integrator is not None:
    # Upstream's resolved config uses `implicitfast` at a 5 ms step
    # (kissqy's Mjlab-Velocity-Flat-MicroDuck.json, env.sim.mujoco.integrator).
    # Euler needs our 2 ms step to stay stable; implicitfast is what lets them use 5 ms.
    spec.option.integrator = integrator

  limit = T.FORCE_LIMIT if force_limit is None else force_limit
  for actuator in spec.actuators:
    actuator.set_to_position(kp=T.KP, kv=T.KD)
    actuator.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
    actuator.forcerange = [-limit, limit]

  if slope_deg:
    # A plane's normal is its geom frame's +z, so a rotation about y tilts the ground.
    half = np.radians(slope_deg) / 2.0
    spec.geom("floor").quat = [np.cos(half), 0.0, np.sin(half), 0.0]

  model = spec.compile()

  # Everything below edits the compiled model, because these are not MJCF fields: friction
  # lives per geom and mass/inertia are already baked by the compiler.
  floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
  if floor >= 0:
    model.geom_friction[floor] = np.array(FLOOR_FRICTION) * [friction_scale, 1.0, 1.0]

  # Hinge joints only. A freejoint has 6 dofs and writing armature into its first slot would
  # damp the floating base, which is not a servo and must stay free.
  hinges = [
    j for j in range(model.njnt) if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE
  ]
  for j in hinges:
    d = model.jnt_dofadr[j]
    if armature is not None:
      model.dof_armature[d] = armature
    if frictionloss is not None:
      model.dof_frictionloss[d] = frictionloss
  if armature is not None or frictionloss is not None:
    _refresh_constants(model)

  if servo_mass_extra_g:
    extra = servo_mass_extra_g / 1000.0
    # A body can carry two hinges; the servo is one part, so de-duplicate before adding.
    for b in sorted({model.jnt_bodyid[j] for j in hinges}):
      old = model.body_mass[b]
      model.body_mass[b] = old + extra
      model.body_inertia[b] *= (old + extra) / old
    _refresh_constants(model)

  if mass_scale != 1.0:
    model.body_mass[1:] *= mass_scale
    model.body_inertia[1:] *= mass_scale
    _refresh_constants(model)
  if payload_kg:
    trunk = model.body("trunk_base").id
    old = model.body_mass[trunk]
    model.body_mass[trunk] = old + payload_kg
    model.body_inertia[trunk] *= (old + payload_kg) / old
    _refresh_constants(model)

  if damping_scale != 1.0:
    model.dof_damping[:] *= damping_scale
  if armature_scale != 1.0:
    model.dof_armature[:] *= armature_scale
  if com_offset_x:
    # Moving a body's ipos moves its centre of mass without changing its inertia about that
    # centre, which is what a hat or a battery strapped to one side actually does.
    trunk = model.body("trunk_base").id
    model.body_ipos[trunk] = model.body_ipos[trunk] + [com_offset_x, 0.0, 0.0]
    _refresh_constants(model)
  return model


def describe(model):
  """One line saying which plant this is, so every measurement can print its own context."""
  floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
  if floor < 0:
    # Indexing -1 would silently read the *last* geom and print a confident lie.
    return f"mass {model.body_mass.sum():.4f} kg  (no geom named 'floor')"
  # geom_quat is (w, x, y, z); the slope is a rotation about y, so its sine sits in slot 2.
  tilt = 2.0 * np.degrees(np.arcsin(np.clip(model.geom_quat[floor][2], -1, 1)))
  # Report the first hinge's numbers: every actuated joint carries the same pair, so one
  # sample is the honest summary. -1 would read the freejoint's slot and print 0.
  hinge_dof = next(
    (model.jnt_dofadr[j] for j in range(model.njnt)
     if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE),
    0,
  )
  return (
    f"mass {model.body_mass.sum():.4f} kg  "
    f"force +-{model.actuator_forcerange[0][1]:.4f} N m  "
    f"arm {model.dof_armature[hinge_dof]:.5f}  "
    f"fric {model.dof_frictionloss[hinge_dof]:.5f}  "
    f"solver {model.opt.iterations}/{model.opt.ls_iterations}  "
    f"floor mu {model.geom_friction[floor][0]:.2f}  "
    f"tilt {tilt:+.1f} deg  dt {model.opt.timestep:.4f}"
  )


if __name__ == "__main__":
  for name, kwargs in SPECS.items():
    print(f"{name.ljust(16)} {describe(build(**kwargs))}")
