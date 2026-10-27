# SPDX-License-Identifier: Apache-2.0
"""Measure a policy in plants and control loops it was not trained in.

Why this file exists
--------------------
`eval_policy.py` answers "does it walk", always in the same plant the policy was trained in.
That number is optimistic by construction: it asks the policy to do the only thing it has
ever done. A gait that only survives its own training plant is a simulation result, not a
robot result, and the difference is exactly what sim2real work is about.

Each condition here changes one thing that is different on hardware, all of them documented
rather than invented:

  real_effort     torque ceiling at kt x 1.75 A (0.6405 N m) instead of the 0.96 stall figure
  solver_training stock MuJoCo's 100/50 iterations instead of mjlab's 10/20
  latency_*       the command reaches the motors N control periods late. The levels are a
                  stress ladder, not a claim about the robot: upstream's BAM actuator carries
                  delay_min_lag=3, delay_max_lag=6, and mjlab documents those lags as *physics*
                  timesteps ("a lag of 2 represents a 4 ms delay" at 500 Hz), so the real
                  command path is 6-12 ms, i.e. below one 20 ms control period. 20 ms is
                  therefore the first rung the quantised model can represent at all.
  obs_delay_*     the policy sees the previous observation N periods later. Upstream sets this
                  per observation term: gyro and gravity 0-1 period (+-20 ms, after a 2026-07
                  audit), joint velocity exactly 1 period (the Dynamixel firmware computes
                  velocity one control period behind).
  sensor_noise    encoder, joint-velocity and gyro noise at the levels a real servo has
  payload_*       mass added at the trunk: a hat, a battery, a repair
  mass_plus_*     the whole robot heavier, inertia scaled with it
  friction_low    a smooth floor instead of the training floor
  slope_*         the ground is not level
  push_*          a lateral velocity impulse, i.e. someone nudging the duck

What is reported is tracking ratio and falls, per condition, against the nominal run. The
drop between them is the honest measure of how much of the gait is physics and how much is
the plant.

  python tools/robustness.py --policy out/deploy61.pt --gates tools/gates.json
"""

import argparse
import collections
import json
import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
sys.path.insert(0, str(ROOT / "tools"))
import plant  # noqa: E402
import train_official as O  # noqa: E402
import train_ppo as T  # noqa: E402

# The env has to speak the checkpoint's observation dialect, not the other way round. 61-D is
# the deployable layout (train_official.Duck); 56-D is the original with privileged base
# velocity. Building the wrong one raises a shape error at the first forward pass.
ENV_BY_WIDTH = {56: T.Duck, 61: O.Duck}

# Observation layouts, as (start, stop, scale). The scale is what training multiplied the
# physical quantity by, so noise can be specified in physical units and land correctly in
# both layouts. 56-D is train_ppo's (privileged base velocity, scaled gyro and joint rate);
# 61-D is the deployable one from duck_cfg/obs.rs, where nothing is scaled.
LAYOUTS = {
  56: dict(
    vel=(0, 3, 2.0), gyro=(3, 6, 0.25), grav=(6, 9, 1.0), jpos=(9, 23, 1.0),
    jvel=(23, 37, 0.05), act=(37, 51, 0.0), cmd=(51, 56, 0.0),
  ),
  61: dict(
    gyro=(0, 3, 1.0), grav=(3, 6, 1.0), jpos=(6, 20, 1.0),
    jvel=(20, 34, 1.0), act=(34, 48, 0.0), cmd=(48, 61, 0.0),
  ),
}

# Physical noise levels. Encoder quantisation on a 12-bit magnetic encoder is ~1.5 mrad over
# 2*pi, and a servo reports more than that once gear backlash is in the loop; 5 mrad is the
# conservative end. Joint velocity is differentiated from that position, so it is noisier.
NOISE = dict(vel=0.05, gyro=0.02, grav=0.01, jpos=0.005, jvel=0.3, act=0.0, cmd=0.0)

# HD1910 no-load speed at 6 V, 92 rev/min -> rad/s. The gait's peak joint demand is reported
# against this instead of the plant enforcing it, for the reason spelled out in plant.HD1910.
HD1910_CEILING_RADPS = plant.HD1910["no_load_rpm_6v"] * 2.0 * np.pi / 60.0

# One change per condition. Control-loop knobs are consumed by rollout(), plant knobs by
# plant.build().
CONDITIONS = {
  "nominal": {},
  # Envelope edges, taken from microduck_velocity_env_cfg.py rather than chosen here:
  #   force        kt x 1.75 A           (duckbench PLANT.md: 0.6405 N m, not the 0.96 stall)
  #   mass         0.95..1.05            MASS_INERTIA_RANDOMIZATION_RANGE
  #   com          +-3 mm -> +-8 mm      COM_RANDOMIZATION_RANGE, ramped by curriculum
  #   foot friction 0.7..1.3             foot_friction.ranges
  #   push         0.3 m/s every 3..6 s  VELOCITY_PUSH_RANGE / VELOCITY_PUSH_INTERVAL_S
  #   tilt         pitch 10 deg, roll 5  BASE_ORIENTATION_MAX_*_DEG (defined, disabled upstream)
  #   encoder bias +-0.015 rad per env   ENCODER_BIAS_RANGE
  "real_effort": dict(force_limit=plant.FORCE_CURRENT),
  "solver_training": dict(solver=plant.SOLVER_TRAINING),
  "upstream_plant": dict(force_limit=plant.FORCE_CURRENT, solver=plant.SOLVER_TRAINING),
  "mass_plus_5pct": dict(mass_scale=1.05),
  "mass_plus_10pct": dict(mass_scale=1.10),  # outside the trained envelope, kept as slack
  "com_offset_3mm": dict(com_offset_x=0.003),
  "com_offset_8mm": dict(com_offset_x=0.008),
  "payload_100g": dict(payload_kg=0.10),  # not upstream: a hat, a repair, a bigger battery
  "friction_0.7": dict(friction_scale=0.7),
  "friction_1.3": dict(friction_scale=1.3),
  "slope_5deg": dict(slope_deg=5.0),
  "tilt_10deg": dict(init_tilt_deg=10.0),
  # Delay ladder. Upstream's actuator lag is 3-6 *physics* steps (6-12 ms at 500 Hz), i.e.
  # under one 20 ms control period, so 20 ms is the first rung this model can represent.
  "latency_20ms": dict(act_delay=1),
  "latency_40ms": dict(act_delay=2),
  "latency_60ms": dict(act_delay=3),
  "latency_80ms": dict(act_delay=4),
  "latency_100ms": dict(act_delay=5),
  "latency_120ms": dict(act_delay=6),
  # Upstream sets observation delay per term: gyro and gravity 0-1 period, joint velocity
  # exactly 1 (the firmware differentiates over the previous period). Turning the uniform
  # value up is a stress test, not a model of the robot.
  "obs_lag_official": dict(official_lag=True),
  "obs_delay_20ms": dict(obs_delay=1),   # stress: every block a period late, joint pos included
  "obs_delay_60ms": dict(obs_delay=3),
  "sensor_noise": dict(noise=1.0),
  "encoder_bias": dict(encoder_bias=0.015),
  "push_0.3mps": dict(push_dv=0.3, push_period=3.0),
  "cmd_back_0.25mps": dict(command=[-0.25, 0.0, 0.0]),
  "cmd_yaw_0.8radps": dict(command=[0.0, 0.0, 0.8]),
  # The servo actually being bought. Every checkpoint here was trained in the upstream MJCF's
  # numbers (armature 0.0018, frictionloss 0.0048), which describe a different servo family,
  # so these four conditions answer the question the purchase order depends on: does the gait
  # survive the swap? They are deliberately split one axis at a time -- a single combined row
  # that failed would not say which of the three caused it.
  #
  # force_limit is left at 0.96 for all of them. HD1910 stalls at 1.18 N m at 6 V, so the
  # torque the policy was trained against still exists with 23% to spare; raising it would
  # flatter the result. The one thing that genuinely got worse is no-load speed (123 -> 92
  # rpm at 6 V) and a stock position actuator cannot express a rate ceiling, so it is measured
  # through `peak_joint_radps` below instead of being faked into the plant.
  "hd1910_armature": dict(armature=plant.HD1910["armature"]),
  "hd1910_friction": dict(frictionloss=plant.HD1910["frictionloss"]),
  "hd1910_mass": dict(servo_mass_extra_g=plant.HD1910["mass_g"] - 18.0),
  "hd1910": dict(
    armature=plant.HD1910["armature"],
    frictionloss=plant.HD1910["frictionloss"],
    servo_mass_extra_g=plant.HD1910["mass_g"] - 18.0,
  ),
  # Deploy-side action low-pass, the shape XGO-Duck's runtime uses (leg alpha 0.45, head 0.2).
  # Unlike every other condition this one is not a model of the robot, it is a thing you can
  # turn on in the firmware, so a gain here would have been immediately deployable.
  #
  # It is not a gain. Measured on robust61_a at 0.3 m/s, 8 s x 8 envs, one seed each:
  #   nominal      0.438        lpf45  0.440        lpf70  0.801 with 62 falls, tilt 47.9 deg
  #   latency_40ms 0.383        +lpf45 0.278  (worse, still 0 falls)
  #   latency_60ms 0.218/28 fl  +lpf45 0.328/40 fl   +lpf70 0.580/73 fl
  # So the filter does not buy this policy any phase margin, and at alpha 0.7 it produces the
  # same illusion as every other crippled run: a high tracking ratio from a robot rolling on its
  # side. Why it works for XGO-Duck and not here is not answered by this measurement -- their
  # plant has 53% more stall torque, a real backlash model and a BAM actuator, and their filter
  # may exist to smooth a 100 Hz state feed rather than to recover delay margin. Recorded as a
  # negative result, not as a missing knob.
  "lpf_leg45": dict(act_alpha=0.45),
  "lpf_leg70": dict(act_alpha=0.70),
}

PLANT_KEYS = {
  "force_limit", "solver", "mass_scale", "payload_kg", "friction_scale", "slope_deg",
  "damping_scale", "armature_scale", "com_offset_x",
  "armature", "frictionloss", "servo_mass_extra_g",
}


def load_policy(path):
  ckpt = torch.load(path, map_location="cpu")
  obs_dim = ckpt.get("obs_dim", T.OBS_DIM)
  net = T.ActorCritic(obs_dim)
  net.load_state_dict(ckpt["model"])
  net.eval()
  return net, ckpt, obs_dim


def noisy(obs, layout, rng, level):
  """Add physical noise to the observation blocks a real robot actually measures."""
  out = obs.copy()
  for block, sigma in NOISE.items():
    if sigma == 0.0 or block not in layout:
      continue
    lo, hi, scale = layout[block]
    out[:, lo:hi] += rng.standard_normal((obs.shape[0], hi - lo)).astype(np.float32) * sigma * scale * level
  return out


def rollout(net, env, obs_dim, command, seconds, seed, act_delay=0, obs_delay=0,
            noise=0.0, push_dv=0.0, push_period=0.0, init_tilt_deg=0.0,
            encoder_bias=0.0, official_lag=False, act_alpha=0.0, heading_hold=False):
  """Run one condition and return per-env speed, falls and orientation statistics. """
  layout = LAYOUTS[obs_dim]
  rng = np.random.default_rng(seed + 1)
  n = env.num_envs
  cmd = np.array(command, np.float32)

  # Heading-hold eval: put the deployed heading controller in the yaw slot. Worth stating what it
  # is for -- `heading_error_deg` is a PATH angle (`atan2(|lateral|, |progress|)`, see the return
  # block), not a yaw angle, so this mode asks the only question that metric can answer: does
  # closing the heading loop straighten the walk? Meaningful for a policy trained with
  # `--heading-envs`, and a zero-shot steering test for any other policy. Not meaningful for a
  # pure-turn condition: the yaw slot is replaced, so `cmd[2]` stops being what is tracked.
  #
  # The bearing is anchored ONLY at the start of an attempt and after a fall. Re-anchoring every
  # step would re-zero the error every step -- the loop would read as closed while commanding
  # nothing, which is exactly how the first version of this helper behaved.
  if heading_hold:
    env.hold_heading(anchor=True)

  def pin(ids=None, anchor=False):
    """Reassert the linear command without losing the heading controller's yaw slot.

    The previous code wrote the whole triple back after every step. In heading mode the yaw slot
    is the controller's output, so writing `cmd[2]` back would zero it before the next `obs()`
    and the policy would never see the correction.
    """
    sl = slice(None) if ids is None else ids
    env.command[sl, :2] = cmd[:2]
    env.until[sl] = 1e9
    if heading_hold:
      env.hold_heading(ids, anchor=anchor)

  if init_tilt_deg:
    # A robot put down on a floor is never perfectly level. Rotating the free joint about y
    # before the first tick is the cheapest honest version of that.
    half = np.radians(init_tilt_deg) / 2.0
    env.qpos[:, 3:7] = [np.cos(half), 0.0, np.sin(half), 0.0]
    env.batch.forward(np.arange(n))
  pin()

  steps = int(round(seconds / T.CTRL_DT))
  push_every = int(round(push_period / T.CTRL_DT)) if push_dv and push_period else 0

  obs = env.obs()
  # Two frames minimum: the official per-term lag needs the previous frame even when the
  # uniform observation delay is zero.
  depth = max(2, obs_delay + 1)
  hist = collections.deque([obs.copy() for _ in range(depth)], maxlen=depth)
  # An action delay starts from a hold-at-home buffer: the robot does not move before the
  # first command arrives, which is what happens after a policy load.
  #
  # maxlen is act_delay + 1, NOT act_delay. With maxlen == act_delay, appending into a full
  # deque evicts the oldest entry first and popleft then returns the action that was just
  # appended: every condition came out one rung short, and `latency_20ms` was bit-for-bit the
  # nominal run. The tell was that nominal and latency_20ms printed identical tracking, tilt
  # and heading error on every policy -- a delay of one whole control period cannot be free.
  # Measured after the fix, robust61_a at 0.3 m/s: 0 ms 0.458, 20 ms 0.198, 40 ms 0.127.
  acts = collections.deque(
    [np.zeros((n, T.ACT_DIM), np.float32) for _ in range(act_delay)], maxlen=max(act_delay, 1) + 1
  )
  # First-order low-pass on the action actually sent to the motors. XGO-Duck's runtime does this
  # at deploy time (leg alpha 0.45, head 0.2) and it is the one latency knob we had never tried:
  # a low-pass rolls off open-loop gain, which pushes the gain crossover down and buys phase
  # margin, at the cost of a bit more lag. `filt` is None until the first step so alpha does not
  # bias the first command toward zero.
  filt = None

  start = env.qpos[:, :3].copy()
  prev = start[:, :2].copy()
  progress = np.zeros(n)          # net travel along the command heading, while alive
  lateral = np.zeros(n)           # net travel across it: drift is a real failure mode
  alive_steps = np.zeros(n)
  falls = np.zeros(n, np.int32)
  upright_min = np.ones(n)
  heights = np.zeros(n)
  yaw_sum = np.zeros(n)
  # How fast the gait actually asks the hinges to move. This exists because the servo swap has
  # exactly one genuine regression -- no-load speed, 123 rpm on the XL330 the design assumed vs
  # 92 rpm on the HD1910 at 6 V (9.63 rad/s) -- and a stock MuJoCo position actuator cannot
  # enforce a rate ceiling (force = kp*err - kv*qvel, clipped; no velocity term in the
  # constraint). Rather than bolt on a fake damping that merely *resembles* a speed limit, we
  # measure the demand and compare it against the ceiling. Under the ceiling, the slower servo
  # is a datasheet difference; over it, it is a real loss of authority and says so.
  peak_joint = np.zeros(n)

  # A per-environment encoder calibration offset, constant for the whole run: upstream models
  # this as ENCODER_BIAS_RANGE = (-0.015, 0.015) rad. It is a different failure from noise —
  # a constant error the policy cannot average away, only learn to tolerate.
  bias = np.zeros((n, T.ACT_DIM)) if not encoder_bias else rng.uniform(-encoder_bias, encoder_bias, (n, T.ACT_DIM))
  jlo, jhi, _ = layout["jpos"]

  heading = np.array([1.0, 0.0]) if abs(cmd[0]) >= abs(cmd[1]) else np.array([0.0, 1.0])
  if cmd[0] < 0 or (cmd[0] == 0 and cmd[1] < 0):
    heading = -heading
  side = np.array([-heading[1], heading[0]])

  for t in range(steps):
    seen = hist[-1 - obs_delay]  # index from the newest frame, so 0 means current
    if official_lag:
      # Upstream delays per observation term, not the whole vector: gyro and gravity 0-1
      # control periods, joint velocity exactly 1, joint position 0. Delaying joint position
      # by a period as well is a much harder problem than the robot poses, so the uniform
      # condition above is a stress test and this one is the model.
      seen = hist[-1].copy()
      for block in ("gyro", "grav", "jvel"):
        lo, hi, _ = layout[block]
        seen[:, lo:hi] = hist[-2][:, lo:hi]
    if noise:
      seen = noisy(seen, layout, rng, noise)
    if encoder_bias:
      seen = seen.copy()
      seen[:, jlo:jhi] += bias
    with torch.no_grad():
      out = net(torch.as_tensor(seen))[0]
    action = out.numpy() if hasattr(out, "numpy") else np.asarray(out)
    if act_delay:
      acts.append(action)
      action = acts.popleft()
    if act_alpha:
      filt = action.copy() if filt is None else act_alpha * filt + (1.0 - act_alpha) * action
      action = filt

    _, done, fell, _ = env.step(action)
    pin()  # step() resamples when `until` runs out; this restores the pinned command

    xy = env.qpos[:, :2]
    live = ~fell
    delta = xy - prev
    progress += np.where(live, delta @ heading, 0.0)
    lateral += np.where(live, delta @ side, 0.0)
    # A rate has to be integrated, not summed: sum(rate)/time is rate/dt.
    yaw_sum += np.where(live, env.qvel[:, 5], 0.0) * T.CTRL_DT
    # qvel[0:6] is the freejoint; the actuated hinges start at 6. Peak is taken per env while
    # alive only -- a hinge whipping round during a fall is contact physics, not a command.
    peak_joint = np.where(
      live,
      np.maximum(peak_joint, np.max(np.abs(env.qvel[:, 6 : 6 + T.ACT_DIM]), axis=1)),
      peak_joint,
    )
    prev = xy.copy()
    alive_steps += live
    upright_min = np.where(live, np.minimum(upright_min, 1.0 - 2.0 * (env.qpos[:, 4] ** 2 + env.qpos[:, 5] ** 2)), upright_min)
    heights += np.where(live, env.qpos[:, 2], 0.0)

    if push_every and t and t % push_every == 0:
      angle = rng.uniform(0, 2 * np.pi, n)
      env.qvel[:, 0] += push_dv * np.cos(angle)
      env.qvel[:, 1] += push_dv * np.sin(angle)

    obs = env.obs()
    hist.append(obs.copy())

    ids = np.flatnonzero(fell)
    if ids.size:
      falls[ids] += 1
      env.reset(ids)
      pin(ids, anchor=True)  # a new attempt holds the bearing the robot lands on
      fresh = env.obs()
      for k in range(len(hist)):  # a reset robot reports fresh data, not the stale buffer
        hist[k][ids] = fresh[ids]
      prev[ids] = env.qpos[ids, :2]
      start[ids] = env.qpos[ids, :3]
      # A robot that just got put back on its feet does not replay the actions it was issuing
      # while it was falling over: the delay line restarts at hold-at-home, like a policy load.
      for buffered in acts:
        buffered[ids] = 0.0
      if filt is not None:  # and the low-pass state is not the fallen robot's either
        filt[ids] = 0.0

  elapsed = np.maximum(alive_steps, 1) * T.CTRL_DT
  speed = progress / elapsed
  yaw_rate = yaw_sum / elapsed
  # A pure-turn command has no linear component, so its tracking has to be measured on the
  # yaw rate. Dividing linear speed by it would report 0 for a policy that turns perfectly.
  turning = np.linalg.norm(cmd[:2]) < 1e-6 and abs(cmd[2]) > 1e-6
  # A yaw rate is signed, and the command is too: a policy that follows a -0.3 rad/s command
  # correctly produces yaw_rate ~ -0.3, so dividing by abs(cmd[2]) reports -1.0 and every
  # negative-yaw command reads as a total failure no matter how well it turns. Fold the
  # command's sign into the rate instead. The linear branch needs no such fix: `heading` above
  # is already flipped for negative commands, so `speed` is positive when the policy tracks it.
  rate = yaw_rate * np.sign(cmd[2]) if turning else speed
  denom = abs(cmd[2]) if turning else (np.linalg.norm(cmd[:2]) or 1.0)
  clean = falls == 0
  # Heading error is measured on net displacement, not on yaw: a duck that walks forward while
  # sliding sideways has a heading error even when it is facing the command direction.
  heading_error = np.degrees(np.arctan2(np.abs(lateral), np.abs(progress) + 1e-9))
  return {
    "metric": "yaw_rate" if turning else "speed",
    "speed_mps_median": float(np.median(speed)),
    "speed_p10": float(np.percentile(speed, 10)),
    "speed_p90": float(np.percentile(speed, 90)),
    "speed_clean_mean": float(speed[clean].mean()) if clean.any() else None,
    "yaw_rate_median": float(np.median(yaw_rate)),
    "tracking_ratio": float(np.median(rate) / denom),
    "falls": int(falls.sum()),
    "envs": int(n),
    "survival": float(alive_steps.sum() / (n * steps)),
    "upright_min": float(upright_min.min()),
    "tilt_max_deg": float(np.degrees(np.arccos(np.clip(upright_min.min(), -1.0, 1.0)))),
    "heading_error_deg_median": float(np.median(heading_error)),
    "lateral_m_median": float(np.median(np.abs(lateral))),
    "height_mean": float(heights.sum() / max(alive_steps.sum(), 1)),
    # Demand vs the HD1910's 9.63 rad/s no-load ceiling at 6 V. The median is the typical
    # worst joint; the max is the single worst instant any env reached, so a gate can read
    # the honest tail instead of a mean that hides it.
    "peak_joint_radps_median": float(np.median(peak_joint)),
    "peak_joint_radps_max": float(peak_joint.max()),
    "peak_joint_pct_of_ceiling": float(100.0 * peak_joint.max() / HD1910_CEILING_RADPS),
  }


def check_gates(results, gates):
  """Compare against pre-registered thresholds. Gates are a lookup, not an argument."""
  rows, failed = [], 0
  for name, spec in gates.get("gates", {}).items():
    if name not in results:
      continue
    got = results[name]
    ok = got["tracking_ratio"] >= spec.get("tracking_min", 0.0) and got["falls"] <= spec.get("falls_max", 999)
    failed += not ok
    rows.append(
      dict(
        condition=name, pass_=bool(ok),
        tracking=round(got["tracking_ratio"], 3), tracking_min=spec.get("tracking_min"),
        tracking_spread=round(got.get("tracking_spread", 0.0), 3),
        tracking_worst=round(got.get("tracking_worst", got["tracking_ratio"]), 3),
        falls=got["falls"], falls_max=spec.get("falls_max"),
        seeds=got.get("seeds", 1),
      )
    )
  return rows, failed


AGGREGATE = (
  "tracking_ratio", "speed_mps_median", "speed_p10", "speed_p90", "yaw_rate_median",
  "survival", "upright_min", "tilt_max_deg", "heading_error_deg_median",
  "lateral_m_median", "height_mean", "peak_joint_radps_median",
)


def aggregate(runs):
  """Fold several seeds of the same condition into one row.

  A single seed is not a measurement, it is one draw. Eight environments over eight seconds is
  64 s of robot time, and `falls_max 0` on that sample is a statement with a wide interval
  around it -- three falls out of 64 s and zero falls out of 64 s are not distinguishable as
  "reliable" and "unreliable". The gate therefore reads the *worst* seed for falls (a failure
  that happens once is a failure) and the mean for tracking (a rate, where averaging is
  legitimate), and both the spread across seeds and the worst seed are printed so the reader
  can see how much of the verdict is the seed.
  """
  first = runs[0]
  out = {k: float(np.mean([r[k] for r in runs])) for k in AGGREGATE}
  out["metric"], out["envs"], out["seeds"] = first["metric"], first["envs"], len(runs)
  out["speed_clean_mean"] = first["speed_clean_mean"]
  out["falls"] = int(max(r["falls"] for r in runs))  # worst seed, and this is what the gate reads
  out["falls_mean"] = float(np.mean([r["falls"] for r in runs]))
  tracking = [r["tracking_ratio"] for r in runs]
  out["tracking_worst"] = float(min(tracking))
  out["tracking_spread"] = float(max(tracking) - min(tracking))
  # A peak is not a rate, so averaging it across seeds would report a number no run produced.
  out["peak_joint_radps_max"] = float(max(r["peak_joint_radps_max"] for r in runs))
  out["peak_joint_pct_of_ceiling"] = float(max(r["peak_joint_pct_of_ceiling"] for r in runs))
  return out


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", type=pathlib.Path, default=ROOT / "out" / "deploy61.pt")
  ap.add_argument("--command", default="0.3,0,0")
  ap.add_argument("--seconds", type=float, default=8.0)
  ap.add_argument("--envs", type=int, default=8)
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument(
    "--seeds", type=int, default=1,
    help="run each condition on N consecutive seeds starting at --seed and report mean "
    "(tracking) and worst-seed (falls). One seed is one draw, not a measurement.",
  )
  ap.add_argument("--conditions", default="all")
  ap.add_argument(
    "--heading-stiffness",
    type=float,
    default=T.HEADING_STIFFNESS,
    help="proportional gain of the heading loop, 1/s. Only meaningful with --heading-hold. "
    "A pure proportional loop on top of an already-lagging plant is exactly the thing delay "
    "punishes, so this is the knob to sweep against the latency conditions.",
  )
  ap.add_argument(
    "--heading-hold",
    action="store_true",
    help="replace the yaw command with a proportional heading controller aimed at the bearing "
    "each env starts on. This is the deployed form of --heading-envs during training. It makes "
    "heading_error_deg (a path angle, not a yaw angle) the quantity being minimised, and it is "
    "meaningless for pure-turn conditions.",
  )
  ap.add_argument("--gates", type=pathlib.Path, default=None)
  ap.add_argument("--out", type=pathlib.Path, default=None, help="write results as json")
  ap.add_argument("--json", action="store_true", help="print one json line instead of a table")
  ap.add_argument("--list", action="store_true", help="print the condition names and exit")
  args = ap.parse_args()

  if args.list:
    print("\n".join(CONDITIONS))
    return

  names = list(CONDITIONS) if args.conditions == "all" else [c.strip() for c in args.conditions.split(",")]
  unknown = [c for c in names if c not in CONDITIONS]
  if unknown:
    raise SystemExit(f"unknown condition(s): {unknown}; --list shows the set")

  net, ckpt, obs_dim = load_policy(args.policy)
  T.HEADING_STIFFNESS = args.heading_stiffness
  if obs_dim not in LAYOUTS:
    raise SystemExit(f"no observation layout for {obs_dim}-D checkpoints")
  env_cls = ENV_BY_WIDTH[obs_dim]
  cmd = [float(v) for v in args.command.split(",")]
  if ckpt.get("task", "velocity") == "ball-balance":
    raise SystemExit("robustness.py measures the velocity task only")

  timestep = ckpt.get("timestep", T.TIMESTEP)
  results, models = {}, {}
  for name in names:
    kwargs = dict(CONDITIONS[name])
    cond_cmd = kwargs.pop("command", cmd)
    model_kwargs = {k: v for k, v in kwargs.items() if k in PLANT_KEYS}
    loop_kwargs = {k: v for k, v in kwargs.items() if k not in PLANT_KEYS}
    loop_kwargs["heading_hold"] = args.heading_hold
    key = json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in sorted(model_kwargs.items())}, sort_keys=True)
    if key not in models:
      models[key] = plant.build(timestep=timestep, **model_kwargs)
    runs = []
    for seed in range(args.seed, args.seed + args.seeds):
      # A fresh env per seed, because the env carries per-environment state (push clock, delay
      # draws, encoder bias) that would otherwise carry over and make seed N depend on N-1.
      env = env_cls(args.envs, seed=seed, timestep=timestep, model=models[key])
      runs.append(rollout(net, env, obs_dim, cond_cmd, args.seconds, seed, **loop_kwargs))
    result = aggregate(runs)
    result["command"] = cond_cmd
    result["heading_hold"] = args.heading_hold
    result["plant"] = plant.describe(env.model)
    results[name] = result

  base = results.get("nominal", {}).get("tracking_ratio")
  for name, got in results.items():
    kwargs = CONDITIONS[name]
    # A condition that changes the command has its own baseline; comparing its tracking to
    # the nominal run's would be comparing two different questions.
    same_command = "command" not in kwargs
    got["tracking_vs_nominal"] = round(got["tracking_ratio"] / base, 3) if base and same_command else None

  payload = dict(
    policy=str(args.policy), obs_dim=obs_dim, command=cmd, seconds=args.seconds,
    envs=args.envs, seed=args.seed, seeds=args.seeds, conditions=results,
  )

  if args.json:
    print(json.dumps(payload, ensure_ascii=False))
  else:
    print(
      f"policy      {args.policy}   obs {obs_dim}   cmd {cmd}   "
      f"{args.seconds:.0f}s x {args.envs} envs x {args.seeds} seed(s)"
    )
    print(f"{'condition':<18}{'track':>7}{'sd':>6}{'vs nom':>8}{'falls':>8}{'tilt':>7}{'hdg':>7}{'surv':>7}{'pkJ':>7}  plant")
    for name, got in results.items():
      rel = f"{got['tracking_vs_nominal']:.2f}" if got["tracking_vs_nominal"] is not None else "  -"
      sd = f"{got.get('tracking_spread', 0.0):.2f}" if args.seeds > 1 else "  -"
      # A robot that fell had its tracking ratio measured partly while it was on the floor, and a
      # rolling fall produces *more* net displacement than a walk. Three separate runs in this
      # project have been misread that way. Mark the number instead of trusting the reader.
      star = "*" if got["falls"] else " "
      print(
        f"{name:<18}{star}{got['tracking_ratio']:>6.3f}{sd:>6}{rel:>8}{got['falls']:>4}/{got['envs']:<3}"
        f"{got['tilt_max_deg']:>6.1f}{got['heading_error_deg_median']:>7.0f}{got['survival']:>7.2f}"
        f"{got.get('peak_joint_radps_max', float('nan')):>7.1f}  {got['plant']}"
      )
    print("  * = this run fell, so the tracking ratio includes floor time; read falls and tilt first")
    print(
      f"  pkJ = fastest any hinge was driven while upright, rad/s. The HD1910 reaches "
      f"{HD1910_CEILING_RADPS:.2f} at 6 V no-load; above that the servo cannot keep up."
    )
    if args.seeds > 1:
      print("  sd = spread of tracking across seeds; falls column is the worst seed, which is what the gate reads")

  if args.gates:
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    rows, failed = check_gates(results, gates)
    print(f"\ngates from {args.gates}")
    for row in rows:
      mark = "PASS" if row["pass_"] else "FAIL"
      print(
        f"  {mark}  {row['condition']:<18} tracking {row['tracking']:.3f} "
        f"(min {row['tracking_min']})  falls {row['falls']} (max {row['falls_max']})"
      )
    payload["gates"] = rows
    payload["gates_failed"] = failed
    if failed:
      print(f"  {failed} gate(s) failed")

  if args.out:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {args.out}")

  if args.gates and payload.get("gates_failed"):
    raise SystemExit(1)


if __name__ == "__main__":
  main()
