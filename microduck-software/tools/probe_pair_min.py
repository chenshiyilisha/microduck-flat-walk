"""CPU-only negative control for tools/patch_joy_pair_min.py.

Nothing here touches MuJoCo or the GPU. It feeds `joy_foot_peak` **measured foot
trajectories** and checks that `pair_min` separates the gaits where the old rule
did not.

The march trajectory is not a toy: it is the 24-point phase table from
`out/probe_phase_sym.log` (checkpoint model_599, 64 envs x 300 steps), linearly
interpolated around the cycle. Using the measured numbers rather than a
constant per foot matters -- a constant would erase the right foot's 21.9 mm arc
and with it the very reason the march outscored standing.

What the check must show
------------------------
      gait           old score   pair_min
      standing         ~0.145      0.145
      one-leg march    ~0.529      0.145    <-- the whole point
      alternating       1.000      1.000

`joy_foot_peak_mean = 0.529` was measured on that checkpoint, so the "old" column
is itself a cross-check: if the reconstructed march does not land near 0.529, the
trajectory is wrong and nothing below it means anything.

The consequence is the point: under the old rule the march (0.529) beat standing
(0.145) by 3.6x, which is why every run converged to a march -- it was the
cheapest way to buy score. Under `pair_min` the march collapses onto standing, so
the only remaining way up is to lift *both* feet.

Clock check
-----------
`joy_foot_peak` used to build its own phase; it now calls `joy_phase`, which
carries the per-episode RSI offset. The test builds an alternating trajectory on
the un-offset clock, then sets a pi offset on the env. If the reward really reads
`joy_phase` the score collapses (it is grading the wrong half-cycles); if it
still built its own phase the score would be untouched. That is the
discriminator -- "no error in the log" proves nothing.

Other checks
------------
  * `end_peak` changes only on the True->False swing edge, not every step.
  * resetting one env clears *only* that env's buffers. Two envs are given
    different trajectories so that "the other one did not move" is a real
    assertion rather than `or True`.
  * `joy_foot_stance` is ~0 for the march and for alternating, and large for a
    hop -- it brackets the alternating gait from the other side.

Run:
    .venv-mjlab/Scripts/python.exe tools/probe_pair_min.py
"""

from __future__ import annotations

import math
import os

import numpy as np
import torch

from mjlab_microduck.tasks import mdp

FREQ = 1.15
STEP_DT = 0.02
N = 64
STANCE_H = 0.0005
TARGET = 0.020
STEPS = 300
TAIL = 80  # steady state only: skips the 0.8 s command ramp and the priming cycle

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


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


# --- mock env: only the attributes joy_foot_peak / joy_foot_stance touch ----


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
        self.common_step_counter = 10**9  # pin the curriculum at 20 mm
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

    # Alternating: each foot arcs to 20 mm in its own half-cycle, flat otherwise.
    # sin(2*pi*frac) is exactly the clock the reward uses.
    s = np.sin(2 * np.pi * fr)
    alt = np.stack([0.020 * np.clip(s, 0, None), 0.020 * np.clip(-s, 0, None)], -1)

    # One-leg march: the measured table, verbatim.
    march = np.stack([_interp(fr, _BIN_LEFT), _interp(fr, _BIN_RIGHT)], -1)

    standing = np.full((STEPS, 2), 0.0029)

    out = {}
    for name, arr in (("alternating", alt), ("march", march), ("standing", standing)):
        out[name] = torch.tensor(arr, dtype=torch.float32).unsqueeze(1).expand(-1, N, -1).clone()
    return out


def roll(term, env, pair_min, record=False):
    vals = []
    peaks = []
    for _ in range(STEPS):
        v = term(env, _SiteCfg(), target_height=TARGET, pair_min=pair_min)
        vals.append(v.mean().item() if record else v.clone())
        if record:
            peaks.append(term.end_peak[0].clone())
        env.advance()
    if record:
        return vals, peaks
    return float(torch.stack(vals)[-TAIL:].mean())


def run_reward(heights, pair_min):
    env = MockEnv(heights)
    term = mdp.joy_foot_peak(cfg=_TermCfg(), env=env)
    score = roll(term, env, pair_min)
    return score, term.end_peak[0].clone()


def run_stance(heights):
    env = MockEnv(heights)
    vals = []
    for _ in range(STEPS):
        vals.append(mdp.joy_foot_stance(env, _SiteCfg(), stance_m=0.006).mean().item())
        env.advance()
    return float(np.mean(vals[-TAIL:]))


def main() -> int:
    print("=" * 76)
    print("1. cfg switches are wired (MICRODUCK_JOY_PAIR_MIN / _JOY_DS_WEIGHT)")
    print("=" * 76)
    from mjlab_microduck.tasks.microduck_joy_env_cfg import (
        make_microduck_joy_smooth_pd_env_cfg as mk,
    )

    keys = ("MICRODUCK_JOY_PAIR_MIN", "MICRODUCK_JOY_DS_WEIGHT")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ["MICRODUCK_JOY_PAIR_MIN"] = "0"
        os.environ.pop("MICRODUCK_JOY_DS_WEIGHT", None)
        off = mk()
        check(
            "OFF: joy_feet has no pair_min key",
            "pair_min" not in off.rewards["joy_feet"].params,
            f"params={sorted(off.rewards['joy_feet'].params)}",
        )
        check("OFF: joy_ds not registered", "joy_ds" not in off.rewards)

        os.environ["MICRODUCK_JOY_PAIR_MIN"] = "1"
        on = mk()
        check(
            "ON: joy_feet.params['pair_min'] is True",
            on.rewards["joy_feet"].params.get("pair_min") is True,
        )

        os.environ["MICRODUCK_JOY_DS_WEIGHT"] = "4"
        ds = mk()
        check(
            "ON: joy_ds registered at weight 4",
            "joy_ds" in ds.rewards and abs(ds.rewards["joy_ds"].weight - 4.0) < 1e-9,
        )
        check(
            "ON: joy_ds points at joy_foot_stance",
            ds.rewards["joy_ds"].func is mdp.joy_foot_stance,
        )
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # RewardManager does `if inspect.isclass: func = func(cfg=term_cfg, env=env)`
    # then `func(self._env, **term_cfg.params)`. `joy_foot_peak` is a class, so
    # `pair_min` in `params` reaches `__call__` only through that second call.
    # Exercising both steps here is what makes "the switch is wired" a fact
    # rather than an assumption.
    import inspect

    cfg_ = _TermCfg()
    cfg_.params["pair_min"] = True
    check("joy_foot_peak is a class (so RewardManager instantiates it)",
          inspect.isclass(mdp.joy_foot_peak))
    env_ = MockEnv(torch.full((4, 2, 2), 0.0))
    term_ = mdp.joy_foot_peak(cfg=cfg_, env=env_)
    val = term_(env_, **cfg_.params)
    check(
        "params['pair_min'] reaches __call__ through the real call path",
        torch.is_tensor(val) and val.shape == (2,),
        f"shape={tuple(val.shape)}",
    )

    print()
    print("=" * 76)
    print("2. pair_min separates the three gaits (the actual claim)")
    print("=" * 76)
    gaits = make_gaits()
    table = {}
    for name, heights in gaits.items():
        old, _ = run_reward(heights, pair_min=False)
        new, end_peak = run_reward(heights, pair_min=True)
        table[name] = (old, new)
        print(
            f"  {name:12s} old={old:6.3f}  pair_min={new:6.3f}  "
            f"end_peak=[{end_peak[0]*1e3:5.1f}, {end_peak[1]*1e3:5.1f}] mm"
        )
    o_alt, n_alt = table["alternating"]
    o_mar, n_mar = table["march"]
    o_std, n_std = table["standing"]

    check(
        "reconstructed march reproduces the measured 0.529 under the old rule",
        abs(o_mar - 0.529) < 0.08,
        f"old march = {o_mar:.3f} (measured 0.529)",
    )
    check("alternating scores 1.0 under pair_min", n_alt > 0.98, f"{n_alt:.3f}")
    check(
        "march collapses onto standing under pair_min (no longer better)",
        n_mar <= n_std + 0.02,
        f"march {n_mar:.3f} vs standing {n_std:.3f}",
    )
    check(
        "NEGATIVE CONTROL: old rule let the march beat standing by >3x",
        o_mar > 3 * o_std,
        f"old march {o_mar:.3f} vs old standing {o_std:.3f}",
    )
    check(
        "old rule rated alternating barely above a march",
        o_alt - o_mar < 0.5,
        f"{o_alt:.3f} - {o_mar:.3f} = {o_alt - o_mar:.3f}",
    )
    check(
        "pair_min opens a >5x margin between alternating and a march",
        n_alt > 5 * max(n_mar, 1e-6),
        f"{n_alt:.3f} vs {n_mar:.3f}",
    )

    print()
    print("=" * 76)
    print("3. end_peak is latched per window, not per step")
    print("=" * 76)
    env = MockEnv(gaits["alternating"])
    term = mdp.joy_foot_peak(cfg=_TermCfg(), env=env)
    changes = 0
    prev = term.end_peak.clone()
    window_len = int(round((1 / FREQ / 2) / STEP_DT))
    for _ in range(STEPS):
        term(env, _SiteCfg(), target_height=TARGET, pair_min=True)
        env.advance()
        if not torch.equal(term.end_peak, prev):
            changes += 1
        prev = term.end_peak.clone()
    print(f"  half-cycle = {window_len} steps; end_peak changed {changes}x in {STEPS} steps")
    check("end_peak is not rewritten every step", changes < STEPS / 4, f"{changes}")
    check("end_peak is not a dead buffer", changes > 4, f"{changes}")

    print()
    print("=" * 76)
    print("4. resetting one env clears only that env's buffers")
    print("=" * 76)
    heights = gaits["alternating"].clone()
    heights[:, 1, :] = gaits["standing"][:, 0, :]  # env 1 stands still
    env = MockEnv(heights)
    term = mdp.joy_foot_peak(cfg=_TermCfg(), env=env)
    for _ in range(120):
        term(env, _SiteCfg(), target_height=TARGET, pair_min=True)
        env.advance()
    p0, p1 = term.end_peak[0].clone(), term.end_peak[1].clone()
    env.episode_length_buf[0] = 0  # reset env 0 only
    term(env, _SiteCfg(), target_height=TARGET, pair_min=True)
    a0, a1 = term.end_peak[0].clone(), term.end_peak[1].clone()
    print(f"  env0 before {p0.tolist()} -> after {a0.tolist()}")
    print(f"  env1 before {p1.tolist()} -> after {a1.tolist()}")
    check(
        "reset env's end_peak is cleared",
        float(a0.max()) == 0.0 and float(p0.min()) > 0.01,
        f"{a0.tolist()}",
    )
    check(
        "non-reset env keeps its end_peak unchanged",
        torch.equal(a1, p1) and float(p1.min()) > 0.0,
        f"{p1.tolist()} -> {a1.tolist()}",
    )

    print()
    print("=" * 76)
    print("5. reward reads joy_phase, so it sees the RSI offset")
    print("=" * 76)
    env = MockEnv(gaits["alternating"])
    term = mdp.joy_foot_peak(cfg=_TermCfg(), env=env)
    base = roll(term, env, pair_min=True)

    env2 = MockEnv(gaits["alternating"])
    env2._joy_gait_phase_offset = torch.full((N,), math.pi)
    term2 = mdp.joy_foot_peak(cfg=_TermCfg(), env=env2)
    shifted = roll(term2, env2, pair_min=True)

    print(f"  no offset {base:.3f}   pi offset on the env {shifted:.3f}")
    check(
        "a pi offset changes the score (the reward is not using a private clock)",
        abs(base - shifted) > 0.3,
        f"delta {abs(base - shifted):.3f}",
    )
    check("un-offset alternating still scores 1.0", base > 0.98, f"{base:.3f}")

    print()
    print("=" * 76)
    print("6. joy_foot_stance brackets the alternating gait from the other side")
    print("=" * 76)
    hop = torch.full((STEPS, N, 2), 0.020)
    c_alt, c_mar, c_hop = (run_stance(gaits["alternating"]), run_stance(gaits["march"]),
                           run_stance(hop))
    print(f"  alternating {c_alt:9.6f}   march {c_mar:9.6f}   hop {c_hop:9.6f}   (m)")
    check("alternating: no stance cost", abs(c_alt) < 1e-4, f"{c_alt:.6f}")
    check(
        "march: stance cost is negligible next to a hop",
        # Not exactly 0: in the measured table the right foot is already at
        # 8.42 mm in bin 0.48, i.e. it starts leaving the ground just before the
        # phase boundary. That is the real trajectory, not a defect.
        abs(c_mar) < 0.05 * abs(c_hop),
        f"march {c_mar:.6f} vs hop {c_hop:.6f}",
    )
    check("hop: large negative cost", c_hop < -0.01, f"{c_hop:.6f}")

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
