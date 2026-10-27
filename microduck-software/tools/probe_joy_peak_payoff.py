"""Offline payoff tables for `joy_foot_rhythm` vs the swing-peak linear term.

Runs without mujoco or Isaac: the reward is a pure function of foot height and
phase, so a unit-test-shaped integrator can say exactly what each policy earns
before any training time is spent. This is the check that was missing when
sigma=18 was chosen -- the gradient story was right, the *baseline* story was
not, and only a table of policies makes that visible.

Every row is a synthetic foot-height trajectory over 12 phase cycles at 1.15 Hz:

    stance          both feet parked at the measured 5.7 mm rest height
    press(1mm)      both feet driven down onto the upstream 0.5 mm floor
    jitter          a 5 deg knee wiggle at 25 Hz -> +-2 mm of foot height
    lift60          correct low-frequency lift, 60% of the commanded bump
    lift100         perfect tracking of the commanded bump

`joy_foot_rhythm` (time-average Gaussian over both feet) cannot separate
`press` from `lift60`: both score ~0.9. The swing-peak linear term cannot
reward `press` at all, because pressing down never raises a running peak.
"""

from __future__ import annotations

import math

FREQ_HZ = 1.15
AMP = 0.024
FLOOR = 0.0005
REST = 0.0057          # measured stance foot height (site z above terrain)
TGT_OFFICIAL = 0.020   # upstream `target_height = 0.02`, audit PASS 18.46/20.03
TGT_LEGACY = 0.024     # what joy_foot_rhythm commands


# ------------------------------------------------------------------ policies
def stance(t, s):
    return REST, REST


def press(t, s):
    return 0.0010, 0.0010


def jitter(t, s):
    h = 0.0020 * math.sin(2 * math.pi * 25 * t)
    return REST + h, REST - h


def _lift(t, s, frac):
    tl = FLOOR + AMP * max(s, 0.0) ** 2
    tr = FLOOR + AMP * max(-s, 0.0) ** 2
    return REST + frac * (tl - REST), REST + frac * (tr - REST)


def lift60(t, s):
    return _lift(t, s, 0.60)


def lift100(t, s):
    return _lift(t, s, 1.00)


POLICIES = [
    ("rigid stance", stance),
    ("press foot to 1 mm", press),
    ("jitter 5deg @25Hz", jitter),
    ("correct lift 60%", lift60),
    ("perfect tracking", lift100),
]


# ------------------------------------------------------------------- rewards
def rhythm_mean(fn, sigma, n=16384, cycles=12):
    """Cycle mean of prod_over_feet exp(-((h-target)/sigma)^2)."""
    tot = 0.0
    for i in range(n):
        t = cycles * i / n
        p = 2 * math.pi * FREQ_HZ * t
        s = math.sin(p)
        tl = FLOOR + AMP * max(s, 0.0) ** 2
        tr = FLOOR + AMP * max(-s, 0.0) ** 2
        al, ar = fn(t, s)
        tot += math.exp(-((al - tl) / sigma) ** 2) * math.exp(-((ar - tr) / sigma) ** 2)
    return tot / n


def peak_linear(fn, tgt=TGT_OFFICIAL, n=8192, cycles=12):
    """Running peak per foot inside its own swing window, linear payoff."""
    peak = [0.0, 0.0]
    prev = [None, None]
    tot = 0.0
    cnt = 0
    for i in range(n):
        t = cycles * i / n
        p = 2 * math.pi * FREQ_HZ * t
        s = math.sin(p)
        a = list(fn(t, s))
        for f in range(2):
            win = math.floor(p / math.pi) + f
            if prev[f] is None or win != prev[f]:
                peak[f] = a[f]
            else:
                peak[f] = max(peak[f], a[f])
            prev[f] = win
        # Exactly one foot is in-window (relu(+s)^2 and relu(-s)^2 are exclusive).
        for f, inside in enumerate((s > 0, s < 0)):
            if inside:
                tot += min(max(peak[f] / tgt, 0.0), 1.0)
                cnt += 1
    return tot / cnt


def peak_gaussian(fn, tgt=TGT_LEGACY, sigma=0.009, n=8192, cycles=12):
    """The rejected version: Gaussian at 24 mm, product over both feet."""
    peak = [0.0, 0.0]
    prev = [None, None]
    tot = 0.0
    for i in range(n):
        t = cycles * i / n
        p = 2 * math.pi * FREQ_HZ * t
        s = math.sin(p)
        a = list(fn(t, s))
        for f in range(2):
            win = math.floor(p / math.pi) + f
            if prev[f] is None or win != prev[f]:
                peak[f] = a[f]
            else:
                peak[f] = max(peak[f], a[f])
            prev[f] = win
        o = 1.0
        for f in range(2):
            o *= math.exp(-((peak[f] - tgt) / sigma) ** 2)
        tot += o
    return tot / n


def main() -> None:
    w = 12.0
    print(f"foot rest = {REST * 1000:.1f} mm   floor = {FLOOR * 1000:.1f} mm   "
          f"time-mean target = {(FLOOR + AMP * 0.25) * 1000:.1f} mm")
    print("the last number is the whole problem: stance height ~= mean target\n")

    cols = [
        ("rhythm s=9", lambda f: rhythm_mean(f, 0.009)),
        ("rhythm s=18", lambda f: rhythm_mean(f, 0.018)),
        ("peak g9 24mm", lambda f: peak_gaussian(f)),
        ("peakLINEAR20", lambda f: peak_linear(f)),
    ]
    head = f"{'policy':<22}" + "".join(f"{c[0]:>15}" for c in cols)
    print(head)
    print("-" * len(head))
    for label, fn in POLICIES:
        row = f"{label:<22}"
        for _, get in cols:
            row += f"{get(fn) * w:>15.2f}"
        print(row)

    print("\ncontrast for lifting (perfect - stance), in points out of 12:")
    for name, get in cols:
        d = (get(lift100) - get(stance)) * w
        d6 = (get(lift60) - get(stance)) * w
        dp = (get(press) - get(stance)) * w
        print(f"  {name:<14} perfect {d:>6.2f}   60% {d6:>6.2f}   "
              f"press-down-vs-stance {dp:>+6.2f}")

    print("\ngradient d(reward)/d(height) at the 5.7 mm stance height, per mm:")
    for sigma in (0.009, 0.018):
        v = math.exp(-((REST - TGT_LEGACY) / sigma) ** 2)
        # sigma is in metres; divide the /m gradient by 1000 to report per mm.
        g = v * 2 * (TGT_LEGACY - REST) / sigma ** 2 / 1000.0
        print(f"  rhythm gaussian sigma={sigma * 1000:>2.0f} mm: "
              f"value {v:.4f}  gradient {g:.5f}")
    print(f"  peak linear @20 mm        : value {REST / TGT_OFFICIAL:.4f}  "
          f"gradient {1 / TGT_OFFICIAL / 1000.0:.5f}  (constant until saturation)")


if __name__ == "__main__":
    main()
