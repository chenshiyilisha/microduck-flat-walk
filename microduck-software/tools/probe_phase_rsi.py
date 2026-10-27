"""CPU-only negative control for tools/patch_joy_phase_rsi.py.

Checks what the RSI patch actually does to `joy_phase`, without building a MuJoCo
env (the GPU is busy training). Two arms, both required:

  OFF arm -- no `_joy_gait_phase_offset` attribute (exactly the state the env is
     in when MICRODUCK_JOY_PHASE_RSI is unset, since the reset event is then not
     registered at all). `joy_phase` must equal the pre-patch formula
     BIT-IDENTICALLY. If this fails, the patch changed the control run and every
     comparison against the ninth run is void.

  ON arm -- call the reset event on a mock env whose episode_length_buf is 0,
     then check that (a) offsets are non-zero and spread over the full [0, 2*pi)
     rather than piling up, (b) at t = 0 the phases themselves are spread, which
     is the whole point (every env used to start at p = 0), (c) a second reset of
     a subset only touches that subset -- otherwise envs would re-randomise every
     time *any* env terminates, which would make the clock non-Markovian noise
     instead of a start-phase offset.

Run:
    .venv-mjlab/Scripts/python.exe tools/probe_phase_rsi.py
"""

from __future__ import annotations

import math
import sys

import torch

from mjlab_microduck.tasks import mdp

FREQ = 1.15
STEP_DT = 0.02
N = 512


class MockEnv:
    """Minimal stand-in for ManagerBasedRlEnv: only what joy_phase touches."""

    def __init__(self, n: int = N, step_dt: float = STEP_DT) -> None:
        self.num_envs = n
        self.step_dt = step_dt
        self.device = "cpu"
        self.episode_length_buf = torch.zeros(n, dtype=torch.int64)


def pre_patch_formula(env) -> torch.Tensor:
    return 2 * math.pi * FREQ * env.episode_length_buf * env.step_dt


def main() -> int:
    failures: list[str] = []

    # ---------------- OFF arm: must be bit-identical to the old formula -----
    env = MockEnv()
    env.episode_length_buf = torch.randint(0, 400, (N,), dtype=torch.int64)
    old = pre_patch_formula(env)
    new = mdp.joy_phase(env)
    if torch.equal(old, new):
        print(f"[PASS] OFF: joy_phase bit-identical to pre-patch formula "
              f"(t range {old.min():.3f}..{old.max():.3f} rad)")
    else:
        d = (new - old).abs().max().item()
        failures.append(f"OFF arm differs from pre-patch formula by {d:.6g}")

    # ---------------- ON arm: first reset spreads the start phase -----------
    env = MockEnv()
    mdp.initialize_joy_gait_phase_offset(env, torch.arange(N, dtype=torch.int64))
    off = getattr(env, "_joy_gait_phase_offset", None)
    if off is None:
        failures.append("ON arm: reset event did not attach _joy_gait_phase_offset")
    else:
        lo, hi = off.min().item(), off.max().item()
        # Uniform on [0, 2pi): 512 draws -> min well under 0.15, max well over 6.1.
        ok_range = lo < 0.15 and hi > 2 * math.pi - 0.15
        ok_std = 1.5 < off.std().item() < 2.1  # uniform sd = 2pi/sqrt(12) = 1.814
        n_unique = len(torch.unique(off))
        print(f"[{'PASS' if ok_range and ok_std else 'FAIL'}] ON: offset "
              f"min {lo:.3f} max {hi:.3f} sd {off.std().item():.3f} "
              f"(expect uniforms sd~1.814), unique {n_unique}/{N}")
        if not ok_range:
            failures.append(f"ON arm: offsets not covering [0,2pi) ({lo:.3f}..{hi:.3f})")
        if not ok_std:
            failures.append(f"ON arm: offset sd {off.std().item():.3f} not uniform-like")
        if n_unique < N - 2:
            failures.append(f"ON arm: only {n_unique} unique offsets of {N}")

    # ---------------- ON arm: start phases are spread at t = 0 --------------
    env = MockEnv()  # episode_length_buf == 0 for every env, i.e. reset step
    mdp.initialize_joy_gait_phase_offset(env, torch.arange(N, dtype=torch.int64))
    p0 = mdp.joy_phase(env)
    # Pre-patch this is exactly 0 for every env -- the bias being removed.
    spread = p0.std().item()
    frac_away_from_zero = (p0.abs() > 0.5).float().mean().item()
    print(f"[{'PASS' if spread > 1.5 and frac_away_from_zero > 0.9 else 'FAIL'}] "
          f"ON: p(t=0) sd {spread:.3f} rad, {frac_away_from_zero*100:.1f}% of envs "
          f"start >0.5 rad from the old p=0")
    if spread <= 1.5:
        failures.append(f"ON arm: start phases barely spread (sd {spread:.3f})")
    if frac_away_from_zero <= 0.9:
        failures.append("ON arm: too many envs still start near p=0")

    # ---------------- ON arm: partial reset must not disturb others ---------
    # Re-read from the CURRENT env: `env` was rebound above, and `off` is the
    # first env's tensor. (Getting this wrong is exactly the class of silent
    # bug this file exists to catch -- the check was red for the wrong reason.)
    before = env._joy_gait_phase_offset.clone()
    sub = torch.arange(0, 16, dtype=torch.int64)
    mdp.initialize_joy_gait_phase_offset(env, sub)
    after = env._joy_gait_phase_offset
    untouched_same = torch.equal(before[16:], after[16:])
    touched_changed = not torch.equal(before[:16], after[:16])
    print(f"[{'PASS' if untouched_same else 'FAIL'}] ON: partial reset left envs "
          f"16..{N-1} untouched; the 16 reset envs "
          f"{'changed' if touched_changed else 'did NOT change (suspicious)'}")
    if not untouched_same:
        failures.append("ON arm: partial reset perturbed envs outside env_ids")

    # ---------------- Reward/obs share one clock ---------------------------
    # All four joy_* terms read joy_phase; confirm the offset shows up in each.
    env = MockEnv()
    env.episode_length_buf = torch.full((N,), 100, dtype=torch.int64)
    base_head = mdp.joy_head_command(env)
    base_clock = mdp.joy_gait_clock(env)
    mdp.initialize_joy_gait_phase_offset(env, torch.arange(N, dtype=torch.int64))
    shifted_head = mdp.joy_head_command(env)
    shifted_clock = mdp.joy_gait_clock(env)
    dh = (shifted_head - base_head).abs().mean().item()
    dc = (shifted_clock - base_clock).abs().mean().item()
    print(f"[{'PASS' if dh > 1e-4 and dc > 1e-4 else 'FAIL'}] shared clock: "
          f"head_command moved {dh:.5f}, gait_clock moved {dc:.5f}")
    if dh <= 1e-4 or dc <= 1e-4:
        failures.append("shared clock: a joy_* term ignored the RSI offset")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
