"""Quantify how much of the 42x `pose_power_above_8hz` gap is a *measurement*
difference rather than a policy difference.

We report 0.01264, upstream reports 0.000296 for the same task/gate. Before
touching the policy, check whether the two sides compute the same quantity:

  upstream  .upstream/rc_art/joy.py:154-165
      signal = 14 joint qpos           (self.motion_samples -> d.qpos[joint_qpos_idx])
      window = Hann
      ratio  = P(f > 8) / P(f > 0)     summed over all joints, then divided

  ours      tools/eval_joy_in_sim.py:81-100  (_fft_high_ratio)
      signal = foot height, and knee angle, each scored separately
      window = none (rectangular)
      ratio  = P(f >= 8) / P(f >= 1 bin)  per environment, then averaged over envs
      reported value = max(foot_ratio, knee_ratio)

A rectangular window has -13 dB sidelobes decaying as 1/f, so a dominant 1.15 Hz
gait leaks into the >8 Hz band. With a Hann window the same leakage is ~-31 dB
and decays as 1/f^3.

This script feeds *identical* synthetic signals through both conventions and
reports what each one returns. The true high-frequency share is known by
construction, so the one that lands near it is the one measuring what its name
claims.

Run:
    python tools/probe_8hz_metric_convention.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

DT = 0.02  # 50 Hz, both sides
OUT = Path(__file__).resolve().parent.parent / "out" / "probe_8hz_convention.json"


# --------------------------------------------------------------------------- #
# The two conventions, transcribed verbatim in behaviour.
# --------------------------------------------------------------------------- #
def ratio_upstream(sig: np.ndarray, dt: float = DT) -> float:
    """`joy.py:156-165`. sig: [T, C] -- summed over channels and frequency."""
    sig = np.asarray(sig, dtype=float)
    centered = sig - sig.mean(0)
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(sig))[:, None], axis=0)) ** 2
    frequencies = np.fft.rfftfreq(len(sig), dt)
    return float(spectrum[frequencies > 8].sum() / max(spectrum[frequencies > 0].sum(), 1e-12))


def ratio_ours_footlike(sig: np.ndarray, dt: float = DT) -> float:
    """`_fft_high_ratio` for a single channel: no window, per-channel ratio."""
    sig = np.asarray(sig, dtype=float)
    if sig.ndim == 1:
        sig = sig[:, None]
    centered = sig - sig.mean(0)
    spec = np.abs(np.fft.rfft(centered, axis=0)) ** 2
    freqs = np.fft.rfftfreq(len(sig), dt)
    total = spec[1:].sum(0)
    high = spec[freqs >= 8].sum(0)
    ratio = np.where(total > 0, high / np.maximum(total, 1e-12), 0.0)
    return float(np.mean(ratio))


def ratio_ours_max(*signals: np.ndarray) -> float:
    """What eval_joy_in_sim actually reports: max(foot_ratio, knee_ratio)."""
    return max(ratio_ours_footlike(s) for s in signals)


# --------------------------------------------------------------------------- #
# Signals with a known high-frequency share.
# --------------------------------------------------------------------------- #
def make_gait(n: int, hf_amp: float, hf_hz: float = 12.0, dt: float = DT) -> np.ndarray:
    """1.15 Hz gait + 2nd harmonic + a known amount of 12 Hz chatter.

    `hf_amp` is the chatter amplitude as a fraction of the fundamental, so the
    *intended* power share above 8 Hz is hf_amp^2 / (1 + 0.3^2 + hf_amp^2)
    (the 0.3 is the 2nd harmonic of a non-sinusoidal gait).
    """
    t = np.arange(n) * dt
    f0 = 1.15
    base = np.sin(2 * np.pi * f0 * t) + 0.3 * np.sin(2 * np.pi * 2 * f0 * t + 0.4)
    chatter = hf_amp * np.sin(2 * np.pi * hf_hz * t + 1.1)
    return base + chatter


def true_hf_share(hf_amp: float) -> float:
    p_base = 1.0 + 0.3**2
    p_hf = hf_amp**2
    return p_hf / (p_base + p_hf)


def main() -> int:
    # upstream measured on 4.4 s (its victory.duration_s); ours ran longer, so
    # report both a short and a long window -- FFT resolution is 1/T and the
    # leakage floor depends on it.
    lengths = {"4.4s (upstream)": int(4.4 / DT), "12.0s (ours)": int(12.0 / DT)}
    hf_amps = [0.0, 0.02, 0.05, 0.10, 0.20]

    rows = []
    for lname, n in lengths.items():
        for amp in hf_amps:
            # 14 channels like the real qpos vector: same gait, staggered phase,
            # different DC offsets -- mimics joints that hardly move.
            sig14 = np.stack(
                [make_gait(n, amp * (0.6 + 0.1 * k), hf_hz=12.0) for k in range(14)], axis=1
            )
            # plus one near-static joint: this is what drags upstream's summed
            # ratio down and has no counterpart in our foot/knee-only version.
            sig14[:, -1] = 0.02 * np.random.default_rng(0).standard_normal(n)

            foot = make_gait(n, amp)          # 1 channel
            knee = make_gait(n, amp * 0.8)    # 1 channel

            rows.append(
                {
                    "length": lname,
                    "n_samples": n,
                    "hf_amp": amp,
                    "true_hf_share": round(true_hf_share(amp), 6),
                    "upstream_hann_14ch": round(ratio_upstream(sig14), 6),
                    "ours_rect_foot": round(ratio_ours_footlike(foot), 6),
                    "ours_rect_max_foot_knee": round(ratio_ours_max(foot, knee), 6),
                }
            )

    # --- what a clamped policy actually produces ----------------------------
    # `max_target_step_rad` is pinned at 0.08 for both us and upstream, which
    # means the conditioner is rate-limited, not position-limited. A policy can
    # sit *inside* the clamp and still reverse direction every step; that is a
    # square wave at the Nyquist rate, and it is the plausible source of a
    # genuinely high >8 Hz share. Synthetic sines cannot test this.
    n = int(4.4 / DT)
    t = np.arange(n) * DT
    bangbang_cases = {}
    for period_steps, label in ((2, "flip every step (25 Hz)"),
                                (4, "flip every 2 steps (12.5 Hz)"),
                                (10, "flip every 5 steps (5 Hz)")):
        sq = np.sign(np.sin(2 * np.pi * t / (period_steps * DT)))[:, None]
        gait = make_gait(n, 0.0)[:, None]
        # gait + chatter riding on a clamped slew: this is the shape that
        # `dtgt_raw` shows when the step bound saturates.
        mixed = 0.5 * gait + 0.04 * sq
        bangbang_cases[label] = {
            "upstream_hann": round(ratio_upstream(mixed), 6),
            "ours_rect": round(ratio_ours_footlike(mixed), 6),
        }

    # --- negative control: the check must be able to go red -------------------
    # A pure 1.15 Hz sine has *no* real power above 8 Hz. Anything non-zero that
    # the metrics return on it is pure leakage. If both returned ~0, the whole
    # comparison above would be vacuous.
    pure = np.sin(2 * np.pi * 1.15 * t)[:, None]
    control = {
        "pure_1.15Hz_sine": {
            "true_hf_share": 0.0,
            "upstream_hann": round(ratio_upstream(pure), 6),
            "ours_rect": round(ratio_ours_footlike(pure), 6),
        }
    }

    report = {
        "dt": DT,
        "cutoff_hz": 8.0,
        "note": (
            "Same synthetic signals through both conventions. true_hf_share is "
            "known by construction; whichever metric sits near it is measuring "
            "what its name claims."
        ),
        "control": control,
        "clamped_slew_cases": bangbang_cases,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    # --- console table -------------------------------------------------------
    print(f"{'length':<16}{'hf_amp':>7}{'true':>10}{'upstream':>11}{'ours_foot':>11}{'ours_max':>10}")
    for r in rows:
        print(
            f"{r['length']:<16}{r['hf_amp']:>7.2f}{r['true_hf_share']:>10.5f}"
            f"{r['upstream_hann_14ch']:>11.5f}{r['ours_rect_foot']:>11.5f}"
            f"{r['ours_rect_max_foot_knee']:>10.5f}"
        )
    print()
    print("clamped-slew shapes (gait + square wave at the step bound):")
    for label, v in bangbang_cases.items():
        print(f"  {label:<26} upstream={v['upstream_hann']:.5f}  ours={v['ours_rect']:.5f}")
    c = control["pure_1.15Hz_sine"]
    print()
    print("negative control (pure 1.15 Hz sine, true HF share = 0):")
    print(f"  upstream_hann = {c['upstream_hann']:.6f}")
    print(f"  ours_rect     = {c['ours_rect']:.6f}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
