# SPDX-License-Identifier: Apache-2.0
"""Export a trained policy to dependency-free C99, for boards like the ESP32.

  python tools/export_mcu.py --policy out/robust61_a.pt --out out/mcu

Writes:
  <out>/policy.h      self-contained, needs only <math.h>
  <out>/selftest.json reference (obs, action) pairs captured from torch

Why C and not ONNX
------------------
ONNX needs a runtime. On a 240 MHz MCU the useful question is not "which
runtime" but "how many multiply-accumulates per control period". The actor here
is three dense layers, so hand-written C is smaller and faster than any
interpreter, and there is nothing to install. The numbers this script prints
are the answer to that question.

The float32 the C does is NOT bit-identical to torch
----------------------------------------------------
torch's Linear on x86 accumulates with a different order than a plain `for`
loop (it may use FMA, blocked reductions, or double-width accumulators). So
comparing C against torch directly would hide the real uncertainty. Instead
this script compares torch against a numpy re-implementation that accumulates
in the SAME order the generated C does, and reports that gap. The C lands
within that gap because it is the same arithmetic. The selftest vectors exist
so you can confirm it on the real board rather than trusting this paragraph.

What this file deliberately does NOT do
---------------------------------------
No quantization. A 5-DOF-per-leg policy at 50 Hz has ~26 k MACs, which is
3-5% of one control period on a 240 MHz core; int8 would buy nothing and cost
accuracy on exactly the small action magnitudes that keep the robot upright.
If you later need the CPU back, quantize the FIRST layer only — that is 30% of
the work and the most forgiving to round.
"""

import argparse
import json
import pathlib
import re
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
import train_ppo as T  # noqa: E402


def extract(ckpt, device="cpu"):
  """Pull the deployment-relevant tensors out and freeze them as float32 numpy.

  Only the actor is exported. The critic exists to compute advantages during
  training and has no meaning on hardware; shipping it would cost 8 KB of flash
  and one wrong number nobody would notice.
  """
  c = torch.load(ckpt, map_location=device)
  net = T.ActorCritic(c["obs_dim"])
  net.load_state_dict(c["model"])
  net.eval()

  layers = []
  for i in (0, 2, 4):
    lin = net.actor[i]
    layers.append(
      (
        lin.weight.detach().numpy().astype(np.float32),
        lin.bias.detach().numpy().astype(np.float32),
      )
    )
  mean = net.mean.detach().numpy().astype(np.float32)
  # Baked as a reciprocal so the C side multiplies instead of divides: one
  # divide per observation element is 61 divides per 20 ms, which is noise, but
  # the multiply form also matches the graph exported to ONNX.
  inv_std = (1.0 / (net.var.sqrt().numpy() + 1e-5)).astype(np.float32)
  return layers, mean, inv_std, net


def seq_forward(obs, layers, mean, inv_std):
  """Re-implementation that accumulates in the exact order the C loop does.

  This is the whole point of the file. `w @ x` in numpy goes through BLAS and
  is NOT the same summation order as `for (i...) acc += w[i]*x[i]`, and the
  difference is what we are trying to bound. `cumsum` over [bias, term0,
  term1, ...] is a left-to-right float32 running sum, which is what the C does.
  """
  x = np.multiply(obs - mean, inv_std, dtype=np.float32).astype(np.float32)
  for idx, (w, b) in enumerate(layers):
    prod = np.multiply(w, x[None, :], dtype=np.float32)
    aug = np.concatenate([b[:, None], prod], axis=1)
    acc = np.cumsum(aug, axis=1, dtype=np.float32)[:, -1].astype(np.float32)
    if idx < len(layers) - 1:
      # ELU(alpha=1): x for x>0, exp(x)-1 otherwise.
      # Written as two masked passes rather than np.where(acc>0, acc, expm1(acc))
      # because np.where evaluates BOTH branches: expm1 of a large positive
      # pre-activation overflows float32 and raises a spurious RuntimeWarning
      # even though the value is discarded. The C ternary is genuinely lazy, so
      # this form also matches it more closely.
      out = acc.copy()
      neg = acc <= 0.0
      out[neg] = np.expm1(acc[neg])
      x = out.astype(np.float32)
    else:
      x = acc
  return x


def roundtrip_check(header, name, arr):
  """Read the emitted literals back out of the generated text and compare bits.

  This is the check that matters most and is easiest to skip: every weight in
  the header is a decimal string produced by "%.9g", and if any of them does not
  round-trip, the C silently runs a slightly different network. Comparing the
  in-memory array against a regex re-parse of the file it was just written to
  catches that — including a bug in carray() itself, which a self-consistent
  comparison would not.
  """
  m = re.search(rf"static const float {name}\[(\d+)\] = \{{(.*?)\}};", header, re.S)
  if m is None:
    raise AssertionError(f"{name} not found in generated header")
  declared = int(m.group(1))
  parsed = np.array([float(v) for v in m.group(2).replace("\n", " ").split(",") if v.strip()], np.float32)
  if declared != parsed.size:
    raise AssertionError(f"{name}: declared {declared}, found {parsed.size} literals")
  if not np.array_equal(parsed, np.asarray(arr, np.float32).ravel()):
    bad = np.flatnonzero(parsed != np.asarray(arr, np.float32).ravel())[:3]
    raise AssertionError(f"{name}: bit mismatch at {bad.tolist()}")
  return parsed.size


def cfloat(v):
  """Shortest decimal that round-trips float32. 9 significant digits is enough
  by construction (log10(2**24) = 7.2), so this asserts rather than assumes."""
  v = np.float32(v)
  if not np.isfinite(v):
    raise ValueError(f"non-finite weight {v} — refusing to emit a policy that will NaN on boot")
  s = "%.9g" % float(v)
  if np.float32(float(s)) != v:
    raise AssertionError(f"%.9g does not round-trip {v!r}")
  return s


def carray(name, arr, per_line=8):
  flat = np.asarray(arr, np.float32).ravel()
  rows = []
  for i in range(0, flat.size, per_line):
    rows.append("  " + ", ".join(cfloat(v) for v in flat[i : i + per_line]) + ",")
  return f"static const float {name}[{flat.size}] = {{\n" + "\n".join(rows) + "\n};\n"


def matrix(name, w):
  return f"#define {name}_OUT {w.shape[0]}\n#define {name}_IN {w.shape[1]}\n" + carray(
    name, w
  )


HEADER = """\
/* Generated by tools/export_mcu.py — do not edit by hand.
 *
 * Source checkpoint : {ckpt}
 * Observation width : {obs_dim}
 * Action width      : {act_dim}
 * Hidden width      : {hidden}
 * Weights           : {params} float32 = {flash_kb:.1f} KiB
 *
 * Layout of the {obs_dim}-D observation, same as duck-control's obs.rs contract:
 *   [0..3)   gyro              rad/s, body frame
 *   [3..6)    projected gravity, unit length, body frame
 *   [6..20)   joint position    14 leg joints, radians, relative to stand
 *   [20..34)  joint velocity    rad/s
 *   [34..48)  previous action   normalized, as fed back to the net
 *   [48..51)  velocity command  vx, vy, vyaw
 *   [51..55)  head command      4 slots, all zero at the home pose
 *   [55..61)  body pose command 6 slots, all zero at the nominal stance
 *
 * The last 10 slots are NOT padding. They are the head and body-pose command
 * blocks, and they were zero for every step of training (microduck_velocity_env_cfg
 * holds the head at home and the body at nominal stance). Feeding anything
 * other than zeros at deploy time moves the observation off its training
 * distribution — silently, because the net still outputs a plausible action.
 * If you later implement head tracking, those channels have to be trained, not
 * just populated.
 *
 * Output is the DETERMINISTIC MEAN action in normalized joint space. The joint
 * target is  ctrl = stand_pose[j] + ACTION_SCALE * action[j]  — that offset
 * lives outside this file because it belongs to the robot, not the controller.
 *
 * Calling convention: single-threaded, 20 ms period. The two hidden buffers are
 * static, so calling md_policy() from two tasks at once will corrupt them. If
 * you need that, pass scratch in instead.
 *
 * This file contains no floating-point literals that do not round-trip; if the
 * board answers differently from selftest.json, the bug is in your wiring,
 * your float ABI, or your ELU, in that order of likelihood.
 */
#ifndef MICRODUCK_POLICY_H
#define MICRODUCK_POLICY_H

#include <math.h>

#define MD_OBS_DIM {obs_dim}
#define MD_ACT_DIM {act_dim}
#define MD_HIDDEN {hidden}
#define MD_NLAYERS {nlayers}

#define MD_MACS {macs}  /* per forward pass */

"""


FOOTER = """\
/* ELU(x) with alpha = 1. expm1f keeps precision near zero, where ~half the
 * pre-activations live; expf(x) - 1.0f loses ~2 digits there. */
static inline float md_elu(float x) {{ return x > 0.0f ? x : expm1f(x); }}

/* Reject an observation before it reaches the network.
 *
 * The upstream safety layer refuses non-finite actions. That catches a dead
 * IMU that reports NaN, but not the more common failure: a sensor that drops
 * out and reports zeros. Zero gyro and zero gravity are perfectly finite, and
 * the projected-gravity block being zero is physically impossible while the
 * robot is upright — |g| is 1.0 by construction. Feeding that in produces an
 * action that looks like a real command.
 *
 * The window is wide enough for the training-time gravity noise (sigma 0.01,
 * so |g| stays within 1.00 +/- 0.02) and narrow enough to catch an all-zero or
 * garbage block. Returns 1 if the observation is safe to feed. */
static inline int md_obs_ok(const float *obs) {{
  for (int i = 0; i < MD_OBS_DIM; ++i) {{
    if (!isfinite(obs[i])) return 0;
  }}
  const float g2 = obs[3] * obs[3] + obs[4] * obs[4] + obs[5] * obs[5];
  return g2 > 0.25f && g2 < 1.75f;
}}

static void md_policy(const float *obs, float *act) {{
  static float buf[2][MD_HIDDEN];
  float *y = buf[1];  /* normalisation target; the loop below ping-pongs buf[0]/buf[1] */

  /* Normalize once into y, then ping-pong. The reciprocal was folded into
   * md_inv_std at export time, so this is a subtract and a multiply. */
  for (int i = 0; i < MD_OBS_DIM; ++i) {{
    y[i] = (obs[i] - md_mean[i]) * md_inv_std[i];
  }}
  float *in = y;

  for (int l = 0; l < MD_NLAYERS; ++l) {{
    const int n_in = md_layer_in[l], n_out = md_layer_out[l];
    const float *w = md_W[l], *b = md_b[l];
    float *out = (in == buf[0]) ? buf[1] : buf[0];
    for (int o = 0; o < n_out; ++o) {{
      float acc = b[o];
      const float *row = w + (size_t)o * n_in;
      for (int i = 0; i < n_in; ++i) {{
        acc += row[i] * in[i];
      }}
      out[o] = (l + 1 < MD_NLAYERS) ? md_elu(acc) : acc;
    }}
    in = out;
  }}

  for (int i = 0; i < MD_ACT_DIM; ++i) {{
    act[i] = in[i];
  }}
}}

#endif /* MICRODUCK_POLICY_H */
"""


def build_header(ckpt, layers, mean, inv_std, obs_dim, act_dim, hidden):
  macs = sum(w.shape[0] * w.shape[1] for w, _ in layers)
  params = sum(w.size + b.size for w, b in layers) + mean.size + inv_std.size
  parts = [HEADER.format(
    ckpt=ckpt, obs_dim=obs_dim, act_dim=act_dim, hidden=hidden,
    params=params, flash_kb=params * 4 / 1024, macs=macs, nlayers=len(layers),
  )]
  parts.append(carray("md_mean", mean))
  parts.append(carray("md_inv_std", inv_std))

  # A flat pointer table keeps the inference loop free of per-layer branches,
  # which matters more for readability here than for speed.
  for i, (w, _) in enumerate(layers):
    parts.append(f"/* layer {i}: {w.shape[1]} -> {w.shape[0]} */\n")
    parts.append(f"static const float md_W{i}[{w.size}] = {{\n")
    flat = w.ravel()
    rows = []
    for j in range(0, flat.size, 8):
      rows.append("  " + ", ".join(cfloat(v) for v in flat[j : j + 8]) + ",")
    parts.append("\n".join(rows) + "\n};\n")
    parts.append(carray(f"md_b{i}", _))

  parts.append(
    "static const float *const md_W[] = {" + ", ".join(f"md_W{i}" for i in range(len(layers))) + "};\n"
  )
  parts.append(
    "static const float *const md_b[] = {" + ", ".join(f"md_b{i}" for i in range(len(layers))) + "};\n"
  )
  parts.append(
    "static const int md_layer_in[] = {" + ", ".join(str(w.shape[1]) for w, _ in layers) + "};\n"
  )
  parts.append(
    "static const int md_layer_out[] = {" + ", ".join(str(w.shape[0]) for w, _ in layers) + "};\n"
  )
  # FOOTER is a plain literal, not a format string, but it was written with the doubled
  # braces a format string needs. That emits `md_policy(...) {{ ... }}`, which is legal C
  # (a nested block) and therefore compiles, runs and produces identical numbers -- a purely
  # cosmetic defect that survived because nothing ever compiled the file. Collapsing it here
  # keeps the generator readable instead of hand-editing forty lines of C.
  parts.append(FOOTER.replace("{{", "{").replace("}}", "}"))
  return "".join(parts), params, macs


def make_probes(obs_dim, act_dim):
  """Observations that stress the places a hand-port usually breaks.

  Not random noise: random noise has unit-scale components everywhere and hides
  an off-by-one in the slice boundaries. These have the real block structure —
  unit gravity, small joint angles, zero previous action on some — so a wrong
  index shows up as a large error instead of a small one.
  """
  # 61 = 3 gyro + 3 gravity + 14 jpos + 14 jvel + 14 prev_action + 3 vel cmd
  #      + 4 head cmd + 6 body cmd.  HEADC/BODYC are zero during all of training.
  n_j = (obs_dim - 3 - 3 - 3 - 4 - 6) // 3
  HEAD_C, BODY_C = 4, 6

  def obs_of(gyro, grav, jpos, jvel, prev, cmd, head=None, body=None):
    o = np.zeros(obs_dim, np.float32)
    k = n_j
    o[0:3] = gyro
    o[3:6] = grav
    o[6 : 6 + k] = jpos
    o[6 + k : 6 + 2 * k] = jvel
    o[6 + 2 * k : 6 + 3 * k] = prev
    o[6 + 3 * k : 6 + 3 * k + 3] = cmd
    if head is not None:
      o[6 + 3 * k + 3 : 6 + 3 * k + 3 + HEAD_C] = head
    if body is not None:
      o[6 + 3 * k + 3 + HEAD_C :] = body
    return o

  unit_g = np.array([0.0, 0.0, -1.0], np.float32)
  # (label, obs, meaningful) — `meaningful` is false for stress vectors, whose
  # output is whatever the untrained-for-this region of the net emits. Those
  # still belong here: they exercise the expm1 branch and the overflow path,
  # which is exactly where a hand port diverges from torch.
  return [
    ("nominal_fwd_0.3", obs_of([0, 0, 0], unit_g, np.zeros(n_j), np.zeros(n_j), np.zeros(n_j), [0.3, 0, 0]), True),
    ("yaw_0.8", obs_of([0.05, -0.02, 0.31], unit_g, 0.1 * np.ones(n_j), 0.5 * np.ones(n_j), np.zeros(n_j), [0, 0, 0.8]), True),
    ("tilted_rolling", obs_of([-0.4, 0.3, -0.6], [0.09, 0.0, -0.996], -0.2 * np.ones(n_j), -1.0 * np.ones(n_j), 0.3 * np.ones(n_j), [0.5, 0, 0]), True),
    ("back_0.25", obs_of([0, 0, 0], [0.2, 0.1, -0.974], np.zeros(n_j), np.zeros(n_j), np.zeros(n_j), [-0.25, 0, 0]), True),
    # Physically reachable worst case: a fall. Gyro 4 rad/s (229 deg/s) and
    # joint velocity 8 rad/s (XL330 tops out near 10.9) both occur on impact.
    # The policy answers with a large action; the safety layer is what makes it
    # survivable, not this network.
    ("stress_fall", obs_of([2.0, -2.0, 4.0], [0.0, 0.0, -1.0], np.pi * np.ones(n_j), 8.0 * np.ones(n_j), np.ones(n_j), [0.6, 0.2, 1.0]), False),
  ]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", required=True)
  ap.add_argument("--out", default=str(ROOT / "out" / "mcu"))
  ap.add_argument("--tolerance", type=float, default=2e-5,
                  help="max allowed |seq_forward - torch| infinity norm")
  args = ap.parse_args()

  out = pathlib.Path(args.out)
  out.mkdir(parents=True, exist_ok=True)

  layers, mean, inv_std, net = extract(args.policy)
  obs_dim, act_dim = mean.size, layers[-1][0].shape[0]
  hidden = layers[0][0].shape[0]

  header, params, macs = build_header(
    pathlib.Path(args.policy).name, layers, mean, inv_std, obs_dim, act_dim, hidden
  )

  checked = 0
  checked += roundtrip_check(header, "md_mean", mean)
  checked += roundtrip_check(header, "md_inv_std", inv_std)
  for i, (w, b) in enumerate(layers):
    checked += roundtrip_check(header, f"md_W{i}", w)
    checked += roundtrip_check(header, f"md_b{i}", b)

  (out / "policy.h").write_text(header, encoding="utf-8")

  probes = make_probes(obs_dim, act_dim)
  rows, worst = [], 0.0
  for label, p, meaningful in probes:
    with torch.no_grad():
      t = net.actor(((torch.as_tensor(p)[None] - net.mean) / (net.var.sqrt() + 1e-5)))[0].numpy()
    s = seq_forward(p, layers, mean, inv_std)
    worst = max(worst, float(np.max(np.abs(t - s))))
    rows.append({
      "label": label,
      "meaningful": meaningful,
      "obs": [float(v) for v in p],
      "action": [float(v) for v in t],
    })

  (out / "selftest.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

  print(f"checkpoint  {args.policy}")
  print(f"shape       {obs_dim} -> {hidden} -> {hidden} -> {act_dim}, ELU, {len(layers)} layers")
  print(f"weights     {params} float32 = {params * 4 / 1024:.1f} KiB flash")
  print(f"compute     {macs} MACs per forward")
  for f_mhz, label in ((240, "ESP32 / S3 @240MHz"), (160, "ESP32 @160MHz")):
    # 5 cycles/MAC is a fair estimate for scalar float32 with a load and an add,
    # and it is deliberately pessimistic — if the real number is better, good.
    print(f"            {label}: {macs * 5 / (f_mhz * 1e6) * 1e3:.2f} ms"
          f"  ({macs * 5 / (f_mhz * 1e6) / 0.02 * 100:.1f}% of a 20 ms period)")
  print(f"activation  {macs * 5 / (240e6) / 0.02 * 100:.1f}% at 5 cycles/MAC, 240 MHz")

  status = "OK" if worst <= args.tolerance else "TOO LOOSE"
  print(f"literals    {checked} emitted, all round-trip bit-exact")
  print(f"\nfloat32 accumulation order gap vs torch: {worst:.2e}  [{status}]")
  if worst > args.tolerance:
    print("  -> the C will inherit this gap. Either the checkpoint is fp16-ish,")
    print("     or the layer order here disagrees with train_ppo.mlp().")
    sys.exit(1)

  print(f"\nwrote {out / 'policy.h'} ({len(header) / 1024:.0f} KiB of text)")
  print(f"wrote {out / 'selftest.json'} ({len(rows)} vectors)")
  print("\nOn the board: include policy.h, call md_policy(obs, act), and compare")
  print("against selftest.json. Do that before connecting a single servo.")


if __name__ == "__main__":
  main()
