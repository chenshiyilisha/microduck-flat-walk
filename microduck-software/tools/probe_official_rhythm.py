"""Official `joy_foot_rhythm` vs the rewards we substituted for it.

Why this exists
---------------
The official joy task (ros-claw/microduck, `training/continuous_joy.patch`,
artifacts/neon-escape-v6/training/selected-env.yaml) grades feet with

    target = 0.0005 + 0.024 * stack(relu(sin p)^2, relu(-sin p)^2) * e
    reward = exp(-((actual - target)/0.009)^2).prod(-1)        # product of BOTH feet

i.e. the stance foot's target is 0.5 mm (it is asked to stay DOWN) while the swing
foot's target is 24.5 mm, and the two factors multiply.  `tools/patch_joy_peak_linear.py`
replaced that with a linear clamp on the swing window's peak, and
`tools/patch_joy_pair_min.py` later added `min(end_peak_L, end_peak_R)` to recover the
"both feet" property by hand.

This probe puts all four scorers on the SAME measured trajectory so the difference is a
number, not an argument.  The trajectories are identical to `tools/probe_pair_min.py`:
the 24-point phase table in `out/probe_phase_sym.log` (model_599, the one-leg march),
interpolated periodically, plus an ideal alternating gait and a standing pose.

Run:  python tools/probe_official_rhythm.py
"""
from __future__ import annotations

import math
import sys

import numpy as np
import torch

from mjlab_microduck.tasks import mdp

FREQ = 1.15
STEP_DT = 0.02
STANCE_H = 0.0005
TARGET = 0.020
STEPS = 300
TAIL = 80  # steady state: skips the 0.8 s episode ramp and the priming cycle

# --- measured phase table (out/probe_phase_sym.log, model_599), mm ----------
_BIN_PHASE = [0.02, 0.06, 0.10, 0.15, 0.19, 0.23, 0.27, 0.31, 0.35, 0.40, 0.44,
              0.48, 0.52, 0.56, 0.60, 0.65, 0.69, 0.73, 0.77, 0.81, 0.85, 0.90,
              0.94, 0.98]
_BIN_LEFT = [2.89, 2.84, 2.79, 2.64, 2.30, 2.19, 1.68, 1.26, 0.90, 0.41, 0.10,
             -0.15, -0.19, -0.17, -0.29, -0.35, -0.37, -0.34, -0.23, 0.01, 0.37,
             0.97, 1.64, 2.30]
_BIN_RIGHT = [0.42, 0.15, 0.40, 0.65, 0.63, 0.56, 0.35, 0.57, 1.35, 2.90, 5.18,
              8.42, 12.63, 16.69, 20.22, 21.90, 21.45, 19.53, 16.77, 13.10, 9.30,
              5.58, 2.33, 0.79]


class _Data:
    def __init__(self, env):
        self._env = env

    @property
    def site_pos_w(self):
        out = torch.zeros(self._env.n, 2, 3)
        out[:, :, 2] = self._env.heights[self._env.t] + STANCE_H
        return out


class _Asset:
    def __init__(self, env):
        self.data = _Data(env)


class _Terrain:
    def __init__(self, n):
        self.env_origins = torch.zeros(n, 3)


class _Scene:
    def __init__(self, env):
        self._env = env
        self._asset = _Asset(env)
        self.terrain = _Terrain(env.n)

    def __getitem__(self, _key):
        return self._asset


class MockEnv:
    def __init__(self, heights):
        self.heights = heights  # [T, N, 2] metres above the stance height
        self.T, self.n, _ = heights.shape
        self.t = 0
        self.num_envs = self.n
        self.device = "cpu"
        self.step_dt = STEP_DT
        self.episode_length_buf = torch.zeros(self.n, dtype=torch.long)
        self.common_step_counter = 10**9  # pin the joy_peak curriculum at its last stage
        self.extras = {"log": {}}
        self.scene = _Scene(self)

    def advance(self):
        self.t = min(self.t + 1, self.T - 1)
        self.episode_length_buf += 1


class _SiteCfg:
    name = "robot"
    site_names = ("left_foot", "right_foot")
    site_ids = [0, 1]


class _TermCfg:
    def __init__(self):
        self.params = {"asset_cfg": _SiteCfg()}
        self.weight = 12.0


def _cycle_fracs():
    t = torch.arange(STEPS, dtype=torch.float64) * STEP_DT
    return ((t * FREQ) % 1.0).numpy()


def _interp(frac, table_mm):
    xs = _BIN_PHASE + [_BIN_PHASE[0] + 1.0]
    ys = table_mm + [table_mm[0]]
    return np.interp(frac, xs, ys) * 1e-3


def make_gaits():
    fr = _cycle_fracs()
    s = np.sin(2 * np.pi * fr)

    # Ideal alternating: each foot arcs to 20 mm inside its own half cycle.
    alt = np.stack([0.020 * np.clip(s, 0, None), 0.020 * np.clip(-s, 0, None)], -1)
    # One-leg march: the measured table, verbatim.
    march = np.stack([_interp(fr, _BIN_LEFT), _interp(fr, _BIN_RIGHT)], -1)
    standing = np.full((STEPS, 2), 0.0029)
    # Hop: both feet arc together (what `pair_min` alone would rate as perfect).
    hop = np.stack([0.020 * np.abs(np.clip(s, -1, 1)), 0.020 * np.abs(np.clip(s, -1, 1))], -1)

    out = {}
    for name, arr in (("alternating", alt), ("march", march),
                      ("standing", standing), ("hop", hop)):
        out[name] = torch.tensor(arr, dtype=torch.float32)  # [STEPS, 2]
    return out


def rollout(make_out, traj):
    """Mean per-step reward over the steady-state tail. traj: [T, 2] metres."""
    env = MockEnv(traj[:, None, :])  # [T, 1, 2]
    scores = []
    for _ in range(STEPS):
        scores.append(float(make_out(env).reshape(-1)[0]))
        env.advance()
    return float(np.mean(scores[-TAIL:]))


def main() -> int:
    gaits = make_gaits()
    peak = mdp.joy_foot_peak(_TermCfg(), MockEnv(gaits["standing"][:, None, :]))

    scorers = [
        ("official joy_foot_rhythm sigma=9mm",
         lambda e: mdp.joy_foot_rhythm(e, _SiteCfg())),
        ("official, sigma=18mm (our patch_joy_foot_sigma)",
         lambda e: mdp.joy_foot_rhythm(e, _SiteCfg(), sigma=0.018)),
        ("ours joy_foot_peak linear 20mm",
         lambda e: peak(e, _SiteCfg(), target_height=TARGET)),
        ("ours + pair_min",
         lambda e: peak(e, _SiteCfg(), target_height=TARGET, pair_min=True)),
    ]

    print(f"\n  per-step reward, steady-state mean over the last {TAIL} steps")
    print("  (weight 12 is NOT applied; multiply by 12 for the actual score)\n")
    header = f"  {'scorer':46s}" + "".join(f"{g:>12s}" for g in gaits)
    print(header)
    print("  " + "-" * (len(header) - 2))

    table = {}
    for label, fn in scorers:
        vals = [rollout(fn, traj) for traj in gaits.values()]
        table[label] = vals
        print(f"  {label:46s}" + "".join(f"{v:12.5f}" for v in vals))

    print()
    for label, (alt, mar, sta, hop) in table.items():
        print(f"  {label}")
        print(f"    alternating/march = {alt / max(mar, 1e-9):7.2f}x"
              f"   march/standing = {mar / max(sta, 1e-9):7.2f}x"
              f"   hop/standing = {hop / max(sta, 1e-9):7.2f}x")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
