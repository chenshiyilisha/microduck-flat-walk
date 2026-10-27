# SPDX-License-Identifier: Apache-2.0
"""Run the invariants this project depends on, as tests rather than as comments.

Why this file exists
--------------------
Three things here are easy to break silently and impossible to notice by watching a video:

  1. `train_robust.Duck` must be *exactly* `train_official.Duck` when its randomisation is
     switched off. If the delay buffers, history shifts or noise gates are wrong, training
     starts from a slightly different environment than the one that produced the checkpoint,
     and the only symptom is a policy that is worse for no stated reason.
  2. The observation layout must stay the deployed one: 61 wide, with a unit gravity vector
     and zeros where the runtime writes zeros.
  3. An exported graph must have the input name and width the runtime loads, with the
     normaliser inside it.

A green run is not proof the policy is good. It is proof the plumbing still matches the
contract, which is the thing that silently stops being true.

  python tools/selfcheck.py --onnx out/deploy61.onnx
"""

import argparse
import contextlib
import io
import math
import pathlib
import sys
import textwrap

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
sys.path.insert(0, str(ROOT / "tools"))
import mujoco  # noqa: E402
import plant  # noqa: E402
import robustness  # noqa: E402
import train_official as O  # noqa: E402
import train_ppo as T  # noqa: E402
import train_robust as R  # noqa: E402

results = []


def check(name, ok, detail=""):
  results.append((name, bool(ok), detail))
  print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def check_env_equivalence():
  """With every randomisation off, the robust env has to reproduce the official one."""
  R.DEFAULTS.update(act_delay=(0, 0), obs_delay=(0, 0), noise=0.0, motor=(1.0, 1.0), push_dv=0.0, jvel_lag=False)
  a, b = R.Duck(6, seed=11), O.Duck(6, seed=11)
  a.command[:] = b.command[:] = [0.3, 0.0, 0.0]
  a.until[:] = b.until[:] = 1e9  # a command resample would consume different rng streams

  rng = np.random.default_rng(0)
  worst = 0.0
  for _ in range(30):
    action = rng.normal(0.0, 0.2, (6, T.ACT_DIM)).astype(np.float32)
    a.step(action)
    b.step(action)
    a.command[:] = b.command[:] = [0.3, 0.0, 0.0]
    a.until[:] = b.until[:] = 1e9
    worst = max(worst, float(np.abs(a.obs() - b.obs()).max()))
  check("robust env == official env with randomisation off", worst == 0.0, f"max |diff| {worst:.1e}")


def check_delay_advance():
  """The delay history must advance exactly once per control step.

  `train_ppo.rollout` calls `env.obs()` twice in any iteration where an environment resets:
  once for `next_obs` and once again after `env.reset(ids)`. If the buffer is pushed inside
  obs(), that second call costs *every* environment an extra frame, so d_obs=1 reads a
  two-step-old frame and the modelled sensor latency depends on other robots' fall rate.

  This is not a hypothetical: it was the behaviour until the push moved into step(). The
  fingerprints below are raw observations, so "which frame did I read" is answered by equality,
  not by counting calls.
  """
  R.DEFAULTS.update(act_delay=(0, 0), obs_delay=(1, 1), noise=0.0, motor=(1.0, 1.0), push_dv=0.0, jvel_lag=0.0)
  env = R.Duck(2, seed=3)
  f0 = O.Duck.obs(env).copy()
  check("d_obs=1 reads the current frame right after construction", np.array_equal(env.obs(), f0))

  env.step(np.full((2, T.ACT_DIM), 0.2, np.float32))
  f1 = O.Duck.obs(env).copy()
  a1 = env.obs()
  check("d_obs=1 reads the pre-step frame after one step", np.array_equal(a1, f0))
  check("a second obs() in the same step advances nothing", np.array_equal(env.obs(), a1))
  check("...and the two frames really differ", float(np.abs(f0 - f1).max()) > 1e-6, f"{np.abs(f0 - f1).max():.2e}")

  env.step(np.full((2, T.ACT_DIM), 0.2, np.float32))
  check("the next step advances exactly one frame", np.array_equal(env.obs(), f1))

  # A reset must hand the environment fresh data in every slot, not just the newest, or the
  # policy reads the fallen robot's history for d_obs steps after it stands up.
  env.reset(np.array([1]))
  check("a reset fills every history slot with fresh data", bool(np.all(env.obs_hist[:, 1] == env.obs_hist[0, 1])))


def check_foot():
  """`env.foot` must be a live read of site_xpos, not a cached copy of a zeroed buffer.

  `self.site[:, self.feet]` indexes with a LIST, which is fancy indexing and COPIES. Holding
  that expression in `__init__` froze the buffer at its pre-forward value -- `site_xpos` is
  only written by mj_forward/mj_step, so the copy was all zeros. Everything that reads foot
  height got 0.0 forever: the `gait` term's `height` (turning a weight-1.0 reward into a
  constant with no gradient, which still logged a healthy-looking 0.83), the ball task's
  `feet_mid`, and `air_time`.

  `self.rot` three lines above uses `xmat[:, self.trunk]` -- basic indexing with an int, which
  stays a view. That is why this survived: the neighbouring line looked identical and was
  correct. The third check below is the one that would have caught it.
  """
  env = R.Duck(2, seed=5)
  env.noise = 0.0
  f0 = env.foot.copy()
  check("foot positions are not an all-zero buffer",
        float(np.abs(f0).max()) > 0.01, f"max |foot| = {np.abs(f0).max():.4f}")
  check("foot agrees with site_xpos at the same ids",
        bool(np.allclose(f0, env.site[:, env.feet])),
        f"max diff {np.abs(f0 - env.site[:, env.feet]).max():.2e}")

  env.step(np.full((2, T.ACT_DIM), 0.3, np.float32))
  moved = float(np.abs(env.foot - f0).max())
  check("foot positions change across a step (live read, not a cached copy)",
        moved > 1e-4, f"{moved:.2e} m")


def check_reward_formulas():
  """The pose and upright kernels must actually be tighter than the versions they replaced.

  Both were written with the normalising denominator missing, which made them decorative:

    pose     exp(-sum(err**2))                vs  exp(-mean(err**2 / std**2))
    upright  exp(-2*(up_x**2 + up_y**2))      vs  exp(-2*(...)/0.05)

  Neither raises, neither looks wrong in a log, and both report a healthy ~0.9 for a stance
  that is several degrees off. That is why they are checked numerically here rather than left
  to review: the failure mode is "the number is plausible".
  """
  err = np.full(T.LEG_IDX.size, 0.1, np.float32)
  loose_pose = float(np.exp(-np.sum(err**2)))
  tight_pose = float(np.exp(-np.mean((err / T.POSE_STD_STAND) ** 2)))
  check(
    "upstream pose kernel is stricter than exp(-sum(err^2)) at a uniform 0.1 rad error",
    tight_pose < loose_pose * 0.7,
    f"{tight_pose:.3f} vs {loose_pose:.3f}",
  )
  # The split matters on its own: upstream restricts `pose` to leg joints by regex and gives the
  # head its own 2.0-weight term. Averaging 4 head joints into a 14-wide mean weakened every
  # leg tolerance by 10/14 and gave the head a 1.0 weight instead of 2.0.
  check("pose std covers exactly the 10 leg joints", T.POSE_STD_STAND.size == T.LEG_IDX.size == 10,
        f"{T.POSE_STD_STAND.size} stds for {T.LEG_IDX.size} indices")
  check("head joints are excluded from pose", not set(T.HEAD_IDX) & set(T.LEG_IDX),
        f"legs {T.LEG_IDX.tolist()} vs head {T.HEAD_IDX.tolist()}")
  check("pose and head cover all 14 actuated joints",
        sorted(T.LEG_IDX.tolist() + T.HEAD_IDX.tolist()) == list(range(T.ACT_DIM)),
        "gap or overlap in the joint partition")
  # `head_pose_tracking`: std 0.5, mean over 4 joints, weight 2.0.
  check("head std matches upstream's head_pose_tracking std", T.HEAD_STD == 0.5, str(T.HEAD_STD))
  head_at_half = float(np.exp(-np.mean((np.full(4, 0.5) / T.HEAD_STD) ** 2)))
  check("head kernel scores exp(-1) at a uniform 0.5 rad error", abs(head_at_half - np.exp(-1)) < 1e-6,
        f"{head_at_half:.4f}")

  th = np.deg2rad(10.0)
  up_err = float(np.sin(th) ** 2)
  ours = float(np.exp(-up_err / T.UPRIGHT_STD2))
  # Upstream's kernel, transcribed from `mjlab-1.3.0/src/mjlab/tasks/velocity/mdp/rewards.py:108`:
  #     xy_squared = sum(square(quat_apply_inverse(quat, gravity_vec_w)[:, :2]))
  # with `gravity_vec_w = [0, 0, -1.0]` (`entity/entity.py:787`), i.e. `sin^2(tilt)`, divided by
  # `std**2` and NOTHING ELSE. The previous version of this line asserted against
  # `1 - cos(tilt)` -- a formula I had *inferred* rather than read -- and that bogus reference
  # let a 2x-too-permissive implementation pass a whole training run.
  upstream = float(np.exp(-np.sin(th) ** 2 / T.UPRIGHT_STD2))
  legacy = float(np.exp(-2.0 * up_err))
  check(
    "upright matches upstream's projected-gravity kernel exp(-sin^2(tilt)/std^2) at 10 deg",
    abs(ours - upstream) <= 1e-6,
    f"{ours:.4f} vs upstream {upstream:.4f}",
  )
  check(
    "upright carries no conversion factor (the 1-cos model this once assumed is 2x off)",
    abs(ours - float(np.exp(-(1.0 - np.cos(th)) / T.UPRIGHT_STD2))) > 0.15,
    f"{ours:.4f} vs the 1-cos model "
    f"{float(np.exp(-(1.0 - np.cos(th)) / T.UPRIGHT_STD2)):.4f}",
  )
  check(
    "upright is stricter than the legacy exp(-2*up_err) it replaced",
    ours < legacy - 0.30,
    f"{ours:.4f} vs legacy {legacy:.4f} (legacy was decoration)",
  )


def check_clearance():
  """`foot_clearance` must be live: quiet when planted, non-zero when the feet move.

  This guards the exact failure the foot cache had, one layer up. `clearance` is a penalty
  term, so a stale or zeroed `_prev_foot_xy` buffer makes it identically zero -- and a penalty
  that never fires reads as "no bad foot behaviour" rather than "the sensor is dead". Zero is
  also the *correct* value while standing, which is what makes it undetectable by inspection.
  """
  env = O.Duck(2, seed=7)
  env.noise = 0.0
  for _ in range(5):
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  planted = float(terms["clearance"].max())
  check("clearance is ~zero while the feet are planted", planted < 1e-3, f"{planted:.2e}")

  moving = 0.0
  for k in range(16):
    act = np.full((2, T.ACT_DIM), 0.5 * np.sin(0.7 * k), np.float32)
    _, _, _, terms = env.step(act)
    moving = max(moving, float(terms["clearance"].max()))
  check("clearance fires once the feet actually move", moving > 1e-3, f"max {moving:.2e}")
  check(
    "the foot baseline advances every step (not a frozen buffer)",
    float(np.abs(env._prev_foot_xy).max()) > 1e-3,
    f"|prev_foot_xy|max = {np.abs(env._prev_foot_xy).max():.2e}",
  )


def check_slip_and_swing():
  """`foot_slip` and `foot_swing_height` are live and charge the right thing.

  Both are penalties, so both read 0.0 when nothing is wrong -- the same blind spot
  `foot_clearance` had. And `foot_swing_height` only fires on a landing edge, which means a
  missing edge detector looks exactly like a clean landing forever.
  """
  env = O.Duck(2, seed=11)
  env.noise = 0.0
  for _ in range(5):
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  check("slip is ~zero with the feet planted", float(terms["slip"].max()) < 1e-3,
        f"{float(terms['slip'].max()):.2e}")
  check("swing_height is zero before any landing edge", float(terms["swing"].max()) == 0.0,
        f"{float(terms['swing'].max()):.2e}")

  # Drive a leg cycle hard enough to lift and replace the feet. Both terms must register.
  slip, swing, landings = 0.0, 0.0, 0
  for k in range(60):
    act = np.zeros((2, T.ACT_DIM), np.float32)
    act[:, [2, 3, 4]] = np.array([1.0, -1.6, 1.0]) * np.sin(0.35 * k)
    act[:, [7, 8, 9]] = np.array([1.0, -1.6, 1.0]) * np.sin(0.35 * k + np.pi)
    _, _, _, terms = env.step(act)
    slip = max(slip, float(terms["slip"].max()))
    swing = max(swing, float(terms["swing"].max()))
    landings += int((terms["swing"] > 0).sum())
  check("slip fires once a foot slides while loaded", slip > 1e-4, f"max {slip:.2e}")
  check("swing_height fires on landing edges", landings > 0,
        f"{landings} env-steps charged, max {swing:.3f}")


def check_curriculum():
  """All three staged schedules advance, and hold at their last stage."""
  saved = (T.REWARD["rate"], T.REWARD["head_bias"], T.STANDING_ENVS, T.CURRICULUM)
  try:
    T.CURRICULUM = True
    seen = {}
    for it in (0, 499, 600, 999, 1000, 1499, 1500, 4000):
      T.apply_curriculum(it)
      seen[it] = (T.REWARD["rate"], T.REWARD["head_bias"], T.STANDING_ENVS)
    check("curriculum starts at upstream's stage 0", seen[0] == (-0.1, 0.0, 0.02), str(seen[0]))
    check("rate is still -0.1 just before iter 500", seen[499][0] == -0.1, str(seen[499]))
    check("a 600-iter run is mid-curriculum at all three schedules",
          seen[600] == (-0.2, 1.0, 0.05), str(seen[600]))
    check("head_bias is still off just before iter 600", seen[499][1] == 0.0, str(seen[499]))
    check("head_bias reaches upstream's 2.0 at iter 1000", seen[1000][1] == 2.0,
          str(seen[1000]))
    check("rate reaches upstream's final -1.0 at iter 1500", seen[1500][0] == -1.0,
          str(seen[1500]))
    check("all schedules hold after their last stage", seen[4000] == (-1.0, 3.0, 0.25),
          str(seen[4000]))
  finally:
    T.REWARD["rate"], T.REWARD["head_bias"], T.STANDING_ENVS, T.CURRICULUM = saved


def check_termination():
  """Tilt termination must match upstream's 70 deg, not our old 45.6 deg.

  A too-tight leash is invisible in a reward log and shows up only as "the policy never learns
  to recover from a push". Upstream's reward comments budget for transient lean; a 45 deg
  cutoff deletes exactly that regime.
  """
  # `up[:, 2]` is the body-frame z of the gravity direction: `-cos(tilt)` when upright. The
  # termination is `up_z > -FELL_COS` = `-cos(tilt) > -cos(70)` = `tilt > 70`. So the threshold
  # angle is `arccos(+FELL_COS)`. (The first version of this line used `arccos(-FELL_COS)` and
  # read 110 deg -- the check was wrong, not the code.)
  check("fell threshold is upstream's 70 deg, not the old 45.6 deg",
        abs(np.degrees(np.arccos(float(T.FELL_COS))) - 70.0) < 0.01,
        f"{np.degrees(np.arccos(float(T.FELL_COS))):.2f} deg")
  check("the old -0.7 threshold was 24 deg tighter",
        abs(np.degrees(np.arccos(0.7)) - 45.57) < 0.05,
        f"{np.degrees(np.arccos(0.7)):.2f} deg")


def check_head_terms():
  """`head_pose_bias_penalty` returns a NEGATIVE value under a POSITIVE weight.

  If the sign were flipped it would read as a bonus for drooping the head, and nothing in the
  reward total would look wrong -- the term would simply be small and positive.
  """
  env = O.Duck(2, seed=5)
  env.noise = 0.0
  # Let the head settle: `reset()` scatters joints by +-0.05 rad, and the PD leaves a small
  # steady droop under the head's own weight. What matters is that this floor is SMALL, and that
  # a real bias is much larger -- see the ratio check below.
  for _ in range(80):
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  at_home = float(np.abs(terms["head_bias"]).max())
  check("head_bias has only a small floor at HOME", at_home < 5e-3, f"{at_home:.2e}")
  # Hold the head 0.3 rad off HOME and re-apply the offset every step, otherwise the PD drives
  # it back. NOTE the write-back form: `env.qpos[:, env.joints]` is a COPY (fancy indexing), so
  # `env.qpos[:, env.joints][:, idx] = x` silently edits a temporary. Same numpy trap that
  # produced the foot-cache and the POSE_STD broadcast bugs. Index the columns directly.
  head_cols = env.joints[T.HEAD_IDX]
  for _ in range(60):
    env.qpos[:, head_cols] = env.stand[T.HEAD_IDX] + 0.3
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  drooped = float(terms["head_bias"].max())
  check("head_bias is negative once the head droops", drooped < -1e-2, f"{drooped:.4f}")
  check("head_bias responds to a real bias (droop >> floor)", abs(drooped) > 5 * at_home,
        f"{abs(drooped):.2e} vs floor {at_home:.2e}")
  check("head term falls below 1 when the head is held 0.3 rad off", float(terms["head"].max()) < 1.0,
        f"{float(terms['head'].max()):.4f}")


def check_duckbuddy_terms():
  """The three terms lifted from DuckBuddy (`Animan-AI/DuckBuddy`, Apache-2.0).

  Rule for this function: every arithmetic assertion reproduces a number DuckBuddy states in its
  own source comments, computed independently here. The bug this guards against is my own --
  porting a formula, testing it against my description of the formula, and shipping it (the
  `upright` 0.5 that survived a whole run that way).
  """
  # (hl2915_tasks.py:945-946) "0.15 rad/s (8.6 deg/s) of net turn over a stride costs ~63%".
  charge = 1.0 - math.exp(-1.0)  # one std
  check("yaw_drift charges 63% of the term at one std", abs(charge - 0.632) < 5e-3, f"{charge:.3f}")
  check("yaw_drift std is the 8.6 deg/s its comment names",
        abs(math.degrees(T.YAW_DRIFT_STD) - 8.6) < 0.05, f"{math.degrees(T.YAW_DRIFT_STD):.2f} deg/s")

  # (hl2915_tasks.py:961-966) "-LinTight-: ... std^2 = 0.1, so walking 0.13 m/s against a 0.27
  # command (the robot's v9) still pays 84%. At 0.04 that miss pays 66%, a 0.2 m/s miss 37%.
  # -LinMid- (v11): halfway, a 0.13 m/s miss pays 75%."
  for std2, miss, want, label in (
    (0.10, 0.13, 0.84, "base"),
    (T.LIN_TIGHT_STD2, 0.13, 0.66, "LinTight"),
    (T.LIN_TIGHT_STD2, 0.20, 0.37, "LinTight"),
    (T.LIN_MID_STD2, 0.13, 0.75, "LinMid"),
  ):
    got = math.exp(-(miss**2) / std2)
    check(f"linear track std^2={std2:g} pays {want:.0%} for a {miss:g} m/s miss ({label})",
          abs(got - want) < 0.01, f"{got:.3f}")

  # (hl2915_tasks.py:897-900) "-YawTight-: the yaw-rate tracking reward is exp(-err^2/std^2) with
  # std^2 = 0.5, which still pays 84% for walking 17 deg/s off the commanded turn ... 0.1, the
  # linear-velocity term's value, pays 41% for it." DuckBuddy then reports that shipping this
  # made the walks WORSE, because a 17 deg/s error is inside the gait's own sway and tightening
  # the kernel turns the sway into the target. We keep SIGMA_ANG at 0.5; this check pins both
  # numbers so a future "let me tighten the yaw kernel" edit has to argue with the measurement.
  sway = math.radians(17.0)
  for std2, want in ((T.SIGMA_ANG, 0.84), (0.10, 0.41)):
    got = math.exp(-(sway**2) / std2)
    check(f"yaw track std^2={std2:g} pays {want:.0%} for a 17 deg/s error",
          abs(got - want) < 0.015, f"{got:.3f}")
  check("SIGMA_ANG stays at the upstream 0.5 (YawTight measurably hurt)", T.SIGMA_ANG == 0.5,
        f"{T.SIGMA_ANG}")

  # (hl2915_tasks.py:1016-1017) "v9 swings head yaw ~17 deg peak to peak (sim); a 0.05 rad band
  # leaves ~6 deg peak to peak free."
  free_sym = math.degrees(2.0 * T.HEAD_BAND_RAD)
  check("head band leaves ~6 deg peak-to-peak free", abs(free_sym - 5.73) < 0.05, f"{free_sym:.2f} deg")
  # The head-band curriculum is upstream's, in iterations (one iteration is 24 env steps there,
  # hence their `500 * 24`). Its stages must stay monotone: a band that loosened would let the
  # policy buy reward by swinging the head again.
  weights = [w for _, w in T.HEAD_BAND_STAGES]
  check("head band stages ramp monotonically more negative", all(b < a for a, b in zip(weights, weights[1:])),
        str(weights))

  # --- behaviour: the term has to react to a sway the way the boxcar claims ------------------
  env = T.Duck(4, seed=7)
  n = env._yaw_n
  check("drift window is one stride (1.0 s at 50 Hz)", n == 50 and env._yaw_actual.shape[1] == n,
        f"n={n}")

  zeros = np.zeros(4, np.float32)
  # A zero-mean sway: +-1 rad/s alternating, which is the p95 of the gait's own yaw sway. The
  # instantaneous `turn` kernel scores exp(-1/0.5) = 0.135 on every tick of this; the boxcar is
  # the only reason the drift term can tell it apart from a real drift.
  sway_vals = []
  for k in range(2 * n):
    sway_vals = env.yaw_drift_term(np.full(4, 1.0 if k % 2 == 0 else -1.0, np.float32), zeros)
  sway_term = float(sway_vals.min())
  instant = math.exp(-(1.0**2) / T.SIGMA_ANG)
  check("yaw_drift ignores a zero-mean sway that `turn` scores 0.14 on", sway_term > 0.9,
        f"yaw_drift {sway_term:.3f} vs turn {instant:.3f}")
  check("...and that contrast is the point (turn really is that low)", instant < 0.2, f"{instant:.3f}")

  # A constant 0.15 rad/s offset with no command: the buffer has to fill first, then read 0.368.
  env.reset(np.arange(4))
  for _ in range(n):
    got = env.yaw_drift_term(np.full(4, T.YAW_DRIFT_STD, np.float32), zeros)
  check("yaw_drift reads exp(-1) for a steady 0.15 rad/s against a zero command",
        abs(float(got.max()) - math.exp(-1.0)) < 1e-3, f"{float(got.max()):.4f}")

  # The divide-by-fill path: right after a reset only one sample is valid, so the mean must be
  # that sample, not sample/n. A wrong denominator here reads as a huge phantom drift.
  env.reset(np.arange(4))
  one = env.yaw_drift_term(np.full(4, T.YAW_DRIFT_STD, np.float32), zeros)
  check("first sample after reset is averaged over 1, not over the window",
        abs(float(one.max()) - math.exp(-1.0)) < 1e-3, f"{float(one.max()):.4f}")

  # Tracked command: matching the turn must score 1.0. This is what makes the term a tracking
  # term and not a "turn less" term -- without it the policy's cheapest move is to stop turning.
  for _ in range(n):
    got = env.yaw_drift_term(np.full(4, 0.5, np.float32), np.full(4, 0.5, np.float32))
  check("yaw_drift pays 1.0 when the turn tracks the command", float(got.min()) > 0.999,
        f"{float(got.min()):.4f}")

  # --- head band: threshold, squaring, and which joints are charged --------------------------
  env = T.Duck(2, seed=11)
  env.noise = 0.0
  for _ in range(80):  # let the PD settle at HOME
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  home = float(terms["head_band"].max())
  check("head_band is zero at HOME", home < 1e-6, f"{home:.2e}")

  # Hold head_yaw off HOME and re-apply every step; physics relaxes it within the 10 substeps, so
  # the assertion is against the q the term actually saw, not against the value I wrote.
  # Joint indices, not columns: `env.joints` maps joint index -> qpos column. 7 = head_yaw,
  # 5 = neck_pitch (the order printed by the hinge loop in plant.py).
  HEAD_YAW, NECK_PITCH = 7, 5
  yaw_col = env.joints[HEAD_YAW]
  for _ in range(40):
    env.qpos[:, yaw_col] = env.stand[HEAD_YAW] + 0.15
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  seen = np.abs(env.qpos[:, env.joints[HEAD_YAW]] - env.stand[HEAD_YAW])
  want = np.maximum(seen - T.HEAD_BAND_RAD, 0.0) ** 2
  check("head_band equals relu(|err| - band)^2 on the q it actually saw",
        float(np.abs(terms["head_band"] - want).max()) < 1e-6,
        f"got {float(terms['head_band'].max()):.5f} want {float(want.max()):.5f}")

  # Neck pitch is NOT one of the two charged joints: it is what holds the head up, so charging it
  # would fight gravity -- and DuckBuddy's previous attempt (`HeadCalm`, head joint speed) is the
  # one that fell over on the real robot. Structural check, with `head` as the contrast that
  # proves the joint really did move.
  neck_col = env.joints[NECK_PITCH]
  for _ in range(40):
    env.qpos[:, neck_col] = env.stand[NECK_PITCH] + 0.30
    env.qpos[:, yaw_col] = env.stand[HEAD_YAW]
    _, _, _, terms = env.step(np.zeros((2, T.ACT_DIM), np.float32))
  moved = float(np.abs(env.qpos[:, neck_col] - env.stand[NECK_PITCH]).max())
  check("neck pitch moved far enough to matter", moved > 0.1, f"{moved:.3f} rad")
  check("head_band does not charge neck pitch", float(terms["head_band"].max()) < 5e-3,
        f"{float(terms['head_band'].max()):.2e}")
  # The instantaneous term is the contrast that proves the neck really did move, so assert it
  # against `head_pose_tracking`'s own formula evaluated on the q the term saw -- not against a
  # threshold I picked. (My first version asserted "< 0.9" and got 0.950: the PD relaxes 0.30 rad
  # to 0.227 within the 10 substeps, and 0.227 into a mean-over-4-joints kernel at std 0.5 is
  # only a 5% charge. The threshold was wrong, not the term.)
  neck_q = env.qpos[:, env.joints[T.HEAD_IDX]]
  want_head = np.exp(-np.mean(((neck_q - env.stand[T.HEAD_IDX]) / T.HEAD_STD) ** 2, axis=1))
  check("...while the instantaneous head term does see it (matches its own formula)",
        float(np.abs(terms["head"] - want_head).max()) < 1e-6 and float(terms["head"].max()) < 0.999,
        f"{float(terms['head'].max()):.4f} vs formula {float(want_head.max()):.4f}")


def check_command_sampling():
  """Turn-in-place and standing envs are actually produced by `resample`.

  Upstream keeps a 15% spin-on-the-spot quota because "independent uniform sampling makes
  spin-on-the-spot ~2% of data -> untrained" (`microduck_velocity_env_cfg.py:10-12`). A quota
  that is silently never drawn is indistinguishable from not having it.
  """
  saved = T.STANDING_ENVS
  saved_on = T.COMMAND_ON.copy()
  try:
    T.STANDING_ENVS = 0.25
    # Force upstream's continuous sampling first. Under the default per-axis sparsity a linear
    # channel can be zeroed *by chance*, which makes "linear is zero" not a valid test for
    # "this env was drawn as a spin-in-place" -- the first version of this check failed on
    # exactly that ambiguity (a plain env with lin=0 and a randomly tiny yaw scored 0.017).
    T.COMMAND_ON[:] = 1.0
    env = O.Duck(4096, seed=3)
    n = np.arange(4096)

    # Raw quota, with the standing draw switched off: should be ~15%.
    T.STANDING_ENVS = 0.0
    env.resample(n, keep=0.0)
    cmd = env.command
    spin = (np.abs(cmd[:, :2]).max(1) < 1e-6) & (np.abs(cmd[:, 2]) > 1e-6)
    check("turn-in-place draws land near upstream's 15% quota",
          abs(spin.mean() - T.TURN_IN_PLACE) < 0.03, f"{spin.mean():.1%}")
    check("every spin-in-place yaw is inside the upper 40-100% of the range",
          bool(np.all(np.abs(cmd[spin, 2]) >= 0.4 * T.COMMAND_RANGE[2] - 1e-6)),
          f"min |yaw| {np.abs(cmd[spin, 2]).min():.3f} of {T.COMMAND_RANGE[2]:.2f}")

    # With the standing draw on, the categories overlap and standing wins (it is applied
    # last), so the REALISED spin fraction is `TURN_IN_PLACE * (1 - rel_standing)`. Spelled
    # out here because the first version of this check asserted the raw 15% and went red at
    # 10.6% -- the code was right, the expectation was missing the overlap.
    T.STANDING_ENVS = 0.25
    env.resample(n, keep=0.0)
    cmd = env.command
    spin = (np.abs(cmd[:, :2]).max(1) < 1e-6) & (np.abs(cmd[:, 2]) > 1e-6)
    stand = np.abs(cmd).max(1) < 1e-6
    check("standing envs land near the curriculum fraction",
          abs(stand.mean() - 0.25) < 0.03, f"{stand.mean():.1%}")
    check("realised spin quota is turn_in_place * (1 - standing)",
          abs(spin.mean() - T.TURN_IN_PLACE * 0.75) < 0.03, f"{spin.mean():.1%}")
  finally:
    T.STANDING_ENVS = saved
    T.COMMAND_ON[:] = saved_on


def check_obs_noise():
  """Observation noise must be UNIFORM at upstream's half-widths, not Gaussian sigmas.

  Building the same env twice, once with `noise=0` and once with `noise=1`, and differencing
  the first observation isolates the noise exactly. The max-abs test is the one that separates
  the two distributions: a Gaussian scaled to the same width would exceed `width` on some of
  the ~2000 samples per channel, a uniform cannot.
  """
  import train_robust as R  # noqa: PLC0415

  expect = {"gyro": 0.03, "grav": 0.01, "jpos": 0.001, "jvel": 0.25}
  check("noise table matches upstream's Unoise half-widths", R.NOISE == expect, str(R.NOISE))

  quiet = R.Duck(2048, seed=17, noise=0.0)
  noisy = R.Duck(2048, seed=17, noise=1.0)
  delta = noisy.obs().astype(np.float64) - quiet.obs().astype(np.float64)
  for name, block, width in (
    ("gyro", R.GYRO, expect["gyro"]),
    ("grav", R.GRAV, expect["grav"]),
    ("jpos", R.JPOS, expect["jpos"]),
    ("jvel", R.JVEL, expect["jvel"]),
  ):
    d = delta[:, block]
    worst = float(np.abs(d).max())
    check(f"{name} noise stays inside +-{width:g} (uniform, not a Gaussian tail)",
          worst <= width * 1.001, f"max |n| = {worst:.4g}")
    check(f"{name} noise reaches its full width", worst >= 0.9 * width, f"max |n| = {worst:.4g}")
    check(f"{name} noise is zero-mean", abs(float(d.mean())) < 0.05 * width,
          f"mean {float(d.mean()):+.2e}")
  untouched = np.abs(delta[:, 34:]).max()
  check("noise leaves the action and command blocks alone", untouched == 0.0, f"{untouched:.2e}")


def check_layout():
  env = O.Duck(4, seed=0)
  obs = env.obs()
  ok_shape = obs.shape == (4, 61)
  grav = np.linalg.norm(obs[:, 3:6], axis=1)
  ok_grav = np.allclose(grav, 1.0, atol=1e-3)
  ok_tail = np.allclose(obs[:, 51:61], 0.0)  # head and body commands at home
  check("observation is 61 wide", ok_shape, str(obs.shape))
  check("projected gravity is a unit vector", ok_grav, f"norm {grav.mean():.4f}")
  check("head/body command slots are zero", ok_tail)
  ok_twist = np.all(np.abs(obs[:, 48:51]) <= np.array([0.5, 0.3, 1.2]) + 1e-6)
  check("twist command stays inside the trained range", ok_twist)


def check_heading():
  """The heading-hold mode: upstream's `heading_command`, which upstream ships but never runs.

  Two independent things are being pinned. First the *geometry*: `heading()` is derived from
  `rot[:, 0]` (body x-axis in world), and a wrong index there would produce a plausible-looking
  angle that is not the yaw -- so it is compared against the quaternion's yaw, which shares no
  code with it. Second the *controller*: the yaw slot must equal `clip(k * wrap(target - yaw))`
  exactly, including the sign, and the closed loop at (k = 1, dt = 20 ms) must contract rather
  than oscillate.
  """
  saved = (T.REL_HEADING_ENVS, T.HEADING_STIFFNESS, T.HEADING_RANGE, T.STANDING_ENVS)
  try:
    got = [float(T.wrap(v)) for v in (0.0, np.pi, -np.pi, 1.5 * np.pi)]
    check("wrap maps +-pi to -pi and leaves 0 alone",
          np.allclose(got, [0.0, -np.pi, -np.pi, -0.5 * np.pi]),
          str([round(v, 3) for v in got]))

    env = O.Duck(8, seed=11)
    n = np.arange(8)
    yaws = np.linspace(-2.8, 2.8, 8)
    # Write the free-joint quaternion directly (basic indexing through np.ix_ writes in place;
    # the fancy-indexed form `qpos[:, cols] = ...` would silently write to a copy).
    env.qpos[np.ix_(n, [3, 4, 5, 6])] = np.stack(
      (np.cos(yaws / 2), np.zeros(8), np.zeros(8), np.sin(yaws / 2)), 1
    )
    env.batch.forward(n)
    err = float(np.abs(T.wrap(env.heading() - yaws)).max())
    check("heading() reproduces the quaternion yaw across +-160 deg", err < 1e-6,
          f"max error {np.degrees(err):.2e} deg")

    T.REL_HEADING_ENVS, T.STANDING_ENVS = 1.0, 0.0
    env.resample(n, keep=0.0)
    env._update_heading()
    check("rel_heading_envs = 1 flags every non-standing env", bool(env.is_heading.all()),
          f"{int(env.is_heading.sum())}/8")
    spread = float(np.abs(T.wrap(env.heading_target - env.heading())).max())
    check("targets are drawn inside +-HEADING_RANGE of the heading at resample",
          spread <= T.HEADING_RANGE + 1e-9, f"{np.degrees(spread):.1f} deg")
    want = np.clip(T.HEADING_STIFFNESS * T.wrap(env.heading_target - env.heading()),
                   -T.COMMAND_RANGE[2], T.COMMAND_RANGE[2])
    check("yaw slot is exactly clip(k * heading error)",
          np.allclose(env.command[:, 2], want, atol=1e-9),
          f"max delta {float(np.abs(env.command[:, 2] - want).max()):.2e}")

    env.heading_target[:] = env.heading() + 0.3
    env._update_heading()
    check("a left-hand target commands a positive yaw rate", bool(np.all(env.command[:, 2] > 0)),
          f"min {env.command[:, 2].min():+.3f}")
    env.heading_target[:] = env.heading() - 0.3
    env._update_heading()
    check("a right-hand target commands a negative yaw rate", bool(np.all(env.command[:, 2] < 0)),
          f"max {env.command[:, 2].max():+.3f}")
    env.heading_target[:] = env.heading() + 3.0
    env._update_heading()
    check("a 3 rad error saturates at the sampled yaw range",
          np.allclose(env.command[:, 2], T.COMMAND_RANGE[2]),
          f"{env.command[:, 2].mean():.3f} vs {T.COMMAND_RANGE[2]:.3f}")

    T.STANDING_ENVS = 1.0
    env.resample(n, keep=0.0)
    env._update_heading()
    check("a standing env is never flagged and keeps an exactly zero command",
          not bool(env.is_heading.any()) and float(np.abs(env.command).max()) == 0.0,
          f"flagged {int(env.is_heading.sum())}, |cmd| {float(np.abs(env.command).max()):.1e}")

    T.REL_HEADING_ENVS, T.STANDING_ENVS = 0.0, 0.0
    env.is_heading[:] = False
    env.command[:, 2] = 0.37
    env._update_heading()
    check("rel_heading_envs = 0 makes the whole mode a no-op",
          bool(np.all(env.command[:, 2] == 0.37)), f"{env.command[0, 2]:.3f}")

    err, trace = 0.79, []
    for _ in range(50):
      trace.append(abs(err))
      err = T.wrap(err - np.clip(T.HEADING_STIFFNESS * err, -T.COMMAND_RANGE[2],
                                 T.COMMAND_RANGE[2]) * T.CTRL_DT)
    check("at k=1, dt=20 ms the heading loop contracts instead of oscillating",
          all(b < a for a, b in zip(trace, trace[1:])) and trace[-1] < 0.45 * 0.79,
          f"0.79 -> {trace[-1]:.3f} rad over 1 s")
  finally:
    T.REL_HEADING_ENVS, T.HEADING_STIFFNESS, T.HEADING_RANGE, T.STANDING_ENVS = saved


def check_hold_heading():
  """The eval-side heading controller, and specifically that it does not re-anchor itself.

  Re-anchoring on every call is the failure this exists for: it re-zeroes the error every step,
  so the loop reads as closed while commanding nothing, and the measurement comes back
  unchanged. It has to run with `REL_HEADING_ENVS = 0`, because the point is to evaluate a
  checkpoint that never trained with the mode.
  """
  env = O.Duck(4, seed=7)
  n = np.arange(4)
  env.hold_heading(anchor=True)
  anchored = float(np.abs(env.command[:, 2]).max())
  check("an anchored bearing commands a zero yaw rate", anchored < 1e-9, f"{anchored:.2e}")

  # Face 0.3 rad past the bearing that was just anchored.
  theta = 0.3
  env.qpos[np.ix_(n, [3, 4, 5, 6])] = np.stack(
    (np.full(4, np.cos(theta / 2)), np.zeros(4), np.zeros(4), np.full(4, np.sin(theta / 2))), 1
  )
  env.batch.forward(n)
  env.hold_heading()
  first = env.command[:, 2].copy()
  check("facing 0.3 rad past the bearing commands a yaw rate back toward it",
        bool(np.all(first < -0.1)), f"{first[0]:+.3f}")
  check("that command is exactly -k * error",
        abs(first[0] + T.HEADING_STIFFNESS * theta) < 1e-9,
        f"{first[0]:+.4f} vs {-T.HEADING_STIFFNESS * theta:+.4f}")
  env.hold_heading()
  check("a second step keeps the bearing instead of re-zeroing the error",
        bool(np.allclose(env.command[:, 2], first)), f"{env.command[0, 2]:+.4f} vs {first[0]:+.4f}")

  env.step(np.zeros((4, T.ACT_DIM), np.float32))
  check("a control step with rel_heading_envs = 0 leaves the controller's yaw slot alone",
        abs(float(env.command[0, 2]) - float(first[0])) < 1e-9,
        f"{env.command[0, 2]:+.4f} vs {first[0]:+.4f}")


def check_plant():
  nominal = plant.build()
  stock = T.build_model()
  ok = np.allclose(nominal.body_mass, stock.body_mass) and np.allclose(
    nominal.actuator_forcerange, stock.actuator_forcerange
  )
  check("plant.build() with no overrides reproduces train_ppo's model", ok)
  weaker = plant.build(force_limit=plant.FORCE_CURRENT, mass_scale=1.1)
  check(
    "perturbations are independent (force changed, mass changed, inertia follows mass)",
    abs(weaker.actuator_forcerange[0][1] - plant.FORCE_CURRENT) < 1e-9
    and abs(weaker.body_mass.sum() / nominal.body_mass.sum() - 1.1) < 1e-9
    and np.allclose(weaker.body_inertia[1] / nominal.body_inertia[1], 1.1, atol=1e-9),
  )
  check("subtree mass is recomputed after mass edits", abs(weaker.body_subtreemass[0] - weaker.body_mass.sum()) < 1e-9)
  # body_invweight0 is what the contact solver actually consumes, and it is a *cached* constant:
  # editing body_mass without mj_setConst leaves it at the unperturbed value, so the heavy plant
  # is solved as if it were light. It must move, and it must move the right way.
  check(
    "mass edits refresh the cached solver constants (mj_setConst)",
    weaker.body_invweight0[1][0] < 0.995 * nominal.body_invweight0[1][0],
    f"{nominal.body_invweight0[1][0]:.4f} -> {weaker.body_invweight0[1][0]:.4f}",
  )

  # --- The servo swap ---------------------------------------------------------------------
  # Asserted against the bench-identified numbers themselves, not against "roughly bigger".
  # A test that only checked "armature increased" would pass for 0.0019 and for 0.02 alike.
  hd = plant.build(**plant.SPECS["hd1910"])
  hinges = [j for j in range(hd.njnt) if hd.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE]
  hd_dofs = [hd.jnt_dofadr[j] for j in hinges]
  check(
    "hd1910 plant carries the measured armature and frictionloss on every hinge",
    len(hd_dofs) == T.ACT_DIM
    and np.allclose(hd.dof_armature[hd_dofs], plant.HD1910["armature"])
    and np.allclose(hd.dof_frictionloss[hd_dofs], plant.HD1910["frictionloss"]),
    f"{len(hd_dofs)} hinges  arm {hd.dof_armature[hd_dofs[0]]:.5f} "
    f"fric {hd.dof_frictionloss[hd_dofs[0]]:.5f}",
  )
  # The freejoint must stay free. Writing armature into dof 0 would damp the floating base --
  # a robot glued to the world still "walks", which is the kind of bug that reads as a gain.
  check(
    "the servo parameters did not leak into the freejoint",
    np.allclose(hd.dof_armature[:6], 0.0) and np.allclose(hd.dof_frictionloss[:6], 0.0),
    f"arm[0:6] max {np.abs(hd.dof_armature[:6]).max():.2e}",
  )
  # Mass goes where the servo sits, so the total gain must be per-servo x hinges and the
  # trunk must be untouched: a heavier servo is not a heavier battery.
  gained = hd.body_mass.sum() - nominal.body_mass.sum()
  want = (plant.HD1910["mass_g"] - 18.0) / 1000.0 * len({hd.jnt_bodyid[j] for j in hinges})
  trunk = hd.body("trunk_base").id
  check(
    "hd1910 mass lands on the servo-carrying links, not on the trunk",
    abs(gained - want) < 1e-6 and abs(hd.body_mass[trunk] - nominal.body_mass[trunk]) < 1e-9,
    f"+{gained * 1000:.1f} g over the airframe ({100 * gained / nominal.body_mass.sum():.1f}%)",
  )
  # The rate ceiling is reported, not enforced, so the constant the report divides by has to
  # be the datasheet figure converted correctly. 92 rpm is 9.63 rad/s, not 92/60 = 1.53.
  check(
    "the HD1910 rate ceiling is 92 rev/min converted to rad/s",
    abs(robustness.HD1910_CEILING_RADPS - 92.0 * 2.0 * np.pi / 60.0) < 1e-9,
    f"{robustness.HD1910_CEILING_RADPS:.3f} rad/s",
  )


def check_onnx(path):
  if path is None:
    return
  import onnx

  model = onnx.load(str(path))
  inp, out = model.graph.input[0], model.graph.output[0]
  width = inp.type.tensor_type.shape.dim[1].dim_value
  ops = {n.op_type for n in model.graph.node}
  check("graph input is named 'obs'", inp.name == "obs", inp.name)
  check("graph width is 61", width == 61, f"{width}")
  check("graph output is 14 wide", out.type.tensor_type.shape.dim[1].dim_value == 14)
  check("normalisation is inside the graph", {"Sub", "Div"} <= ops, ",".join(sorted(ops)))
  check("batch axis is dynamic", inp.type.tensor_type.shape.dim[0].dim_value == 0)

  import onnxruntime as ort

  sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
  rng = np.random.default_rng(0)
  x = rng.standard_normal((7, width)).astype(np.float32)
  y = sess.run(None, {"obs": x})[0]
  check("onnxruntime accepts a batch of 7", y.shape == (7, 14), str(y.shape))
  check("output is finite", bool(np.isfinite(y).all()))


def _patched(obj, name, replacement):
  """Set obj.name = replacement and hand back the undo."""
  original = getattr(obj, name)
  setattr(obj, name, replacement)
  return lambda: setattr(obj, name, original)


def _expect_red(label, break_it, check_fn):
  """Run check_fn with one contract broken on purpose; it must not come back green.

  A selfcheck that has only ever been green is not evidence. A check that asserts nothing, or
  that compares the code against the same wrong value the code computes, passes exactly as
  loudly as a real one -- and the failure it is supposed to catch goes unnoticed until the
  robot does. So each mutation below re-creates a bug this project has actually had (or is one
  refactor away from having), and the check that is meant to catch it has to go red.

  The inner results are expected failures, so they are removed from the tally rather than
  counted: this run's verdict is the mutation being *detected*, and it reads PASS when it is.
  """
  mark, undo = len(results), break_it()
  buf, red, detail = io.StringIO(), [], ""
  try:
    try:
      with contextlib.redirect_stdout(buf):
        check_fn()
      inner = results[mark:]
      red = [name for name, ok, _ in inner if not ok]
      detail = f"{len(red)} of {len(inner)} checks went red"
    except Exception as exc:  # a crash is also a detection, and worth naming separately
      inner, red, detail = results[mark:], ["raised"], f"raised {type(exc).__name__}: {exc}"
    del results[mark:]
  finally:
    undo()
  print(f"  {'PASS' if red else 'FAIL'}  {label}  ({detail})")
  if not red:
    # A mutation nobody noticed is the interesting case: show what the check actually saw.
    print(textwrap.indent(buf.getvalue().rstrip(), " " * 8))
  results.append((f"negative control: {label}", bool(red), detail))


def negative_control():
  """Break four things; require the matching check to notice."""
  def break_action_scale():
    original = R.Duck.step
    return _patched(R.Duck, "step", lambda self, action: original(self, action * 1.001))

  def break_plant_mass():
    original = plant.build
    return _patched(plant, "build", lambda **kw: original(**{k: v for k, v in kw.items() if k != "mass_scale"}))

  def break_constants():
    return _patched(plant, "_refresh_constants", lambda model: None)

  def break_delay_advance():
    original = R.Duck.obs
    def push_on_read(self):
      self.obs_hist[1:] = self.obs_hist[:-1].copy()
      self.obs_hist[0] = O.Duck.obs(self)
      return original(self)
    return _patched(R.Duck, "obs", push_on_read)

  def break_foot_cache():
    # Reproduce the real bug: a frozen all-zero buffer instead of a live read.
    return _patched(
      R.Duck, "foot",
      property(lambda self: np.zeros((self.num_envs, 2, 3), np.float32)),
    )

  def break_clearance_baseline():
    # The realistic regression: the baseline is declared but never advanced, so the finite
    # difference is measured against the world origin instead of the previous foot position.
    # Foot sites sit ~0.05 m from the origin, so this inflates the implied velocity by ~2.5 m/s
    # and the term stops measuring foot motion at all. Note a "baseline follows the current
    # pose" mutation does NOT work -- that is exactly what the real code does.
    original = T.Duck.step
    def never_advances(self, action):
      out = original(self, action)
      self._prev_foot_xy = np.zeros_like(self._prev_foot_xy)
      return out
    return _patched(T.Duck, "step", never_advances)

  def break_heading_sign():
    # The controller's sign is the kind of thing that reads fine and steers the wrong way.
    original = T.Duck._update_heading

    def flipped(self):
      original(self)
      if T.REL_HEADING_ENVS > 0.0:
        self.command[self.is_heading, 2] *= -1.0

    return _patched(T.Duck, "_update_heading", flipped)

  def break_heading_target_absolute():
    # The decision under test: the target is drawn RELATIVE to the heading at resample, not
    # absolute U(-pi, pi) as IsaacLab does. Reproduce the absolute version and the range check
    # has to notice.
    def absolute(self):
      if T.REL_HEADING_ENVS <= 0.0:
        return
      due = np.flatnonzero(self._heading_due)
      if due.size:
        self.heading_target[due] = T.wrap(self.rng.uniform(-np.pi, np.pi, due.size))
        self._heading_due[due] = False
      ids = np.flatnonzero(self.is_heading)
      if ids.size:
        self.command[ids, 2] = np.clip(
          T.HEADING_STIFFNESS * T.wrap(self.heading_target[ids] - self.heading()[ids]),
          -T.COMMAND_RANGE[2],
          T.COMMAND_RANGE[2],
        )

    return _patched(T.Duck, "_update_heading", absolute)

  def break_heading_anchor():
    # The bug the eval helper actually had: re-anchor the bearing on every call, which re-zeroes
    # the error every step and leaves the loop open while it looks closed.
    original = T.Duck.hold_heading

    def always_anchor(self, ids=None, anchor=False):
      return original(self, ids, anchor=True)

    return _patched(T.Duck, "hold_heading", always_anchor)

  def break_yaw_drift_window():
    # The mutation this term exists to avoid: price the yaw rate TICK BY TICK instead of over a
    # stride. That is not a strawman -- it is exactly what our `turn` term does, and the reason
    # the drift survived is that the gait's own +-1 rad/s sway swamps the kick inside one tick.
    # With the window gone the "ignores a zero-mean sway" check has to go red.
    def tick_only(self, yaw_rate, cmd_yaw):
      return np.exp(-((yaw_rate - cmd_yaw) ** 2) / T.YAW_DRIFT_STD**2)

    return _patched(T.Duck, "yaw_drift_term", tick_only)

  def break_head_band_joints():
    # Charging all four head joints instead of head_yaw + head_roll. Plausible-looking (it is the
    # same set `head_pose_tracking` uses) and wrong: neck and head pitch are what holds the head
    # up, so the policy would buy reward by letting the head droop.
    original = T.Duck.step

    def all_four(self, action):
      out = original(self, action)
      err = self.qpos[:, self.joints][:, T.HEAD_IDX] - self.stand[T.HEAD_IDX]
      out[3]["head_band"] = np.sum(np.maximum(np.abs(err) - T.HEAD_BAND_RAD, 0.0) ** 2, 1)
      return out

    return _patched(T.Duck, "step", all_four)

  _expect_red("action path scaled by 0.1%", break_action_scale, check_env_equivalence)
  _expect_red("plant.build ignores mass_scale", break_plant_mass, check_plant)
  _expect_red("mj_setConst removed after a mass edit", break_constants, check_plant)
  _expect_red("delay history pushed from obs() instead of step()", break_delay_advance, check_delay_advance)
  _expect_red("foot clearance baseline follows the current pose", break_clearance_baseline, check_clearance)
  _expect_red("foot cached as an all-zero buffer", break_foot_cache, check_foot)
  _expect_red("heading controller with its sign flipped", break_heading_sign, check_heading)
  _expect_red("heading target drawn absolute U(-pi, pi)", break_heading_target_absolute, check_heading)
  _expect_red("eval re-anchors the heading bearing every step", break_heading_anchor, check_hold_heading)
  _expect_red("yaw drift priced per tick instead of per stride", break_yaw_drift_window,
              check_duckbuddy_terms)
  _expect_red("head band charges all four head joints", break_head_band_joints,
              check_duckbuddy_terms)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--onnx", type=pathlib.Path, default=None)
  ap.add_argument("--no-negative-control", action="store_true", help="skip the deliberate breakage")
  args = ap.parse_args()

  print("env equivalence")
  check_env_equivalence()
  print("delay history")
  check_delay_advance()
  print("foot sites")
  check_foot()
  print("observation contract")
  check_layout()
  print("reward kernels")
  check_reward_formulas()
  print("foot clearance")
  check_clearance()
  print("foot slip / swing height")
  check_slip_and_swing()
  print("curriculum")
  check_curriculum()
  print("termination")
  check_termination()
  print("head terms")
  check_head_terms()
  print("duckbuddy terms")
  check_duckbuddy_terms()
  print("observation noise")
  check_obs_noise()
  print("command sampling")
  check_command_sampling()
  print("heading hold")
  check_heading()
  print("heading hold eval")
  check_hold_heading()
  print("plant")
  check_plant()
  if args.onnx:
    print(f"onnx {args.onnx}")
    check_onnx(args.onnx)
  if not args.no_negative_control:
    print("negative control (each of these MUST be red)")
    negative_control()

  failed = [r for r in results if not r[1]]
  print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
  if failed:
    for name, _, _ in failed:
      print(f"  failed: {name}")
    raise SystemExit(1)


if __name__ == "__main__":
  main()
