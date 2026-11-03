#!/usr/bin/env python
"""Phase gap between the bench and BAM as a function of normalized peak speed.

Why this exists
---------------
§19 measured a 30 deg phase gap between the bench and BAM at the gait operating
point (1.89 Hz, +-16.9 deg) and two explanations were ruled out on data
(servo-internal dead time per the Feetech control table; load sag, because
holding BAM at 3.9 V moves lag only +4 deg). What was left open was whether the
gap is a *voltage* artefact of running the bench at 4.5 V -- far below the
STS3215's rated 6-7.4 V, and far below the plant's own training domain
(vin_range 6.5-8.2 V, vin_min 6.0 V after sag).

The gap turns out to be a single-valued function of
    u = peak_speed / max_speed(vin)
where max_speed(vin) is the servo's physical top speed at that voltage, i.e. the
7.4 V rated 3400 step/s scaled by vin/7.4. Two *different* (f, amp) combinations
with nearly the same u give nearly the same gap (1.0 Hz +-16.9 deg and
1.89 Hz +-8.5 deg, both ~104 deg/s of peak speed), which is the cross-check that
makes this a mechanism rather than a curve fit through unrelated points.

So the bench gap at 4.5 V is not the deployment gap. Extrapolating along u to the
training domain is how we bound the real one without a 7.4 V supply. This script
does that extrapolation and prints it, so the claim can be re-derived instead of
trusted.

Inputs are all committed under out/sine/ (bench sweeps + BAM probe output).
Run:  python tools/hd1910/phase_gap_vs_load.py [--json out/sine/phase_gap.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib
import sys

#: 3400 step/s at 7.4 V rated, from the Feetech control table (reg46 full scale)
MAX_SPEED_7V4_DEG = 3400.0 * 360.0 / 4096.0  # 298.83 deg/s
RATED_V = 7.4
#: plant's own training domain, read back from the live actuator cfg
TRAIN_VIN = (6.5, 7.4, 8.2)
GAIT_F = 1.89
GAIT_AMP = 16.9
#: bench threshold for a trustworthy fit (deg); above this the sine fit folded
MAX_RESID = 0.20


def load_bench(root: pathlib.Path) -> list[dict]:
    """Bench points as (freq, amp, lag, resid, vmin)."""
    pts: list[dict] = []
    for path in sorted(glob.glob(str(root / "sine_id10_kp5_kd0-*.json")))[-1:]:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        vlo = d.get("voltage_v") or [float("nan")] * 2
        for r in d.get("freqs") or []:
            pts.append(
                {
                    "src": pathlib.Path(path).name,
                    "freq": r["freq_hz"],
                    "amp": d["amp_deg"],
                    "lag": r["lag_deg"],
                    "resid": r["rms_resid_deg"],
                    "v_lo": vlo[0],
                }
            )
    for path in sorted(glob.glob(str(root / "sweepA_kp5_a*.json"))):
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        vlo = d.get("voltage_v") or [float("nan")] * 2
        for r in d.get("freqs") or []:
            pts.append(
                {
                    "src": pathlib.Path(path).name,
                    "freq": r["freq_hz"],
                    "amp": d["amp_deg"],
                    "lag": r["lag_deg"],
                    "resid": r["rms_resid_deg"],
                    "v_lo": vlo[0],
                }
            )
    return pts


def load_bam(root: pathlib.Path, vin: float) -> dict[tuple[float, float], dict]:
    """BAM ``(freq, amp_deg) -> row`` at ``vin`` (matched to the bench voltage).

    Field names come from ``probe_kp5_bandwidth.py``: the amplitude is stored in
    radians as ``amp_cmd_rad`` and the table is ``rows``.
    """
    out: dict[tuple[float, float], dict] = {}
    for path in glob.glob(str(root / "bam_bw_*.json")):
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if d.get("vin") is None or abs(float(d["vin"]) - vin) > 1e-6:
            continue
        for r in d.get("rows") or []:
            amp_deg = round(math.degrees(float(r["amp_cmd_rad"])), 1)
            out[(round(float(r["freq_hz"]), 3), amp_deg)] = r
    return out


def peak_speed(freq: float, amp: float) -> float:
    """deg/s of the commanded sinusoid."""
    return 2.0 * math.pi * freq * amp


def max_speed(vin: float) -> float:
    """Physical top speed of the servo at ``vin`` (rated 3400 step/s at 7.4 V)."""
    return MAX_SPEED_7V4_DEG * vin / RATED_V


def gap_ms(gap_deg: float, freq: float) -> float:
    """Equivalent pure delay of a phase gap at ``freq``."""
    return gap_deg / (360.0 * freq) * 1000.0


def interp_gap(u: float, table: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation of gap(u); ends clamped."""
    if not table:
        raise SystemExit("no data to interpolate")
    if u <= table[0][0]:
        return table[0][1]
    if u >= table[-1][0]:
        return table[-1][1]
    for (u0, g0), (u1, g1) in zip(table, table[1:]):
        if u0 <= u <= u1:
            t = (u - u0) / (u1 - u0)
            return g0 + t * (g1 - g0)
    return table[-1][1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default="out/sine")
    ap.add_argument("--vin-bench", type=float, default=4.5)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    root = pathlib.Path(a.root)
    bench = load_bench(root)
    bam = load_bam(root, a.vin_bench)

    rows = []
    for p in bench:
        key = (round(p["freq"], 3), round(float(p["amp"]), 1))
        if key not in bam:
            continue
        if p["resid"] > MAX_RESID:
            continue
        br = bam[key]
        vpk = peak_speed(p["freq"], p["amp"])
        u = vpk / max_speed(a.vin_bench)
        gap = p["lag"] - br["lag_deg"]
        rows.append(
            {
                "freq": p["freq"],
                "amp": p["amp"],
                "peak_deg_s": round(vpk, 1),
                "u": round(u, 3),
                "bench_lag": round(p["lag"], 1),
                "bam_lag": round(br["lag_deg"], 1),
                "gap_deg": round(gap, 1),
                "gap_ms": round(gap_ms(gap, p["freq"]), 1),
                # BAM's own duty cycle: if this stays far below max_pwm the model is
                # linear and cannot reproduce a saturation-driven gap by construction
                "bam_peak_duty": round(float(br.get("peak_duty", float("nan"))), 3),
                "bam_duty_sat": round(float(br.get("duty_sat_frac", float("nan"))), 3),
                "v_lo": p["v_lo"],
                "src": p["src"],
            }
        )
    rows.sort(key=lambda r: r["u"])

    print(f"bench vin={a.vin_bench} V, max_speed={max_speed(a.vin_bench):.1f} deg/s, "
          f"rated {MAX_SPEED_7V4_DEG:.1f} deg/s @ {RATED_V} V")
    print(f"plant training domain: vin_range {TRAIN_VIN} (vin_min 6.0 after sag)")
    print()
    print(f"{'f Hz':>6} {'amp':>6} {'peak d/s':>9} {'u':>6} "
          f"{'bench':>7} {'BAM':>7} {'gap':>7} {'gap ms':>7} {'BAM duty':>9} {'sat':>5}")
    for r in rows:
        print(f"{r['freq']:>6} {r['amp']:>6} {r['peak_deg_s']:>9} {r['u']:>6.3f} "
              f"{r['bench_lag']:>7.1f} {r['bam_lag']:>7.1f} {r['gap_deg']:>7.1f} "
              f"{r['gap_ms']:>7.1f} {r['bam_peak_duty']:>9.3f} {r['bam_duty_sat']:>5.2f}")

    table = [(r["u"], r["gap_deg"]) for r in rows]
    print()
    print("=== extrapolation along u to the training domain (gait point "
          f"{GAIT_F} Hz +-{GAIT_AMP} deg, peak {peak_speed(GAIT_F, GAIT_AMP):.0f} deg/s) ===")
    vpk_gait = peak_speed(GAIT_F, GAIT_AMP)
    ext = []
    for vin in (a.vin_bench, *TRAIN_VIN):
        u = vpk_gait / max_speed(vin)
        g = interp_gap(u, table)
        ext.append(
            {
                "vin": vin,
                "u": round(u, 3),
                "gap_deg_pred": round(g, 1),
                "gap_ms_pred": round(gap_ms(g, GAIT_F), 1),
            }
        )
        print(f"  vin {vin:>4} V  u={u:.3f}  gap ~{g:+6.1f} deg  = {gap_ms(g, GAIT_F):+6.1f} ms")

    print()
    print("Training delay band is lag 3..6 physics steps x 5 ms = 15..30 ms.")
    for e in ext[1:]:
        inside = 15.0 <= e["gap_ms_pred"] <= 30.0
        print(f"  vin {e['vin']} V in band? {'YES' if inside else 'NO'} "
              f"({e['gap_ms_pred']} ms)")

    print()
    print("CAVEAT: this is an extrapolation along u, not a measurement at those")
    print("voltages. It bounds the deployment gap; it does not replace one 7.4 V")
    print("sweep. What it does change is the priority: the 43 ms figure was a")
    print("4.5 V number being read as if it were a deployment number.")

    if a.json:
        p = pathlib.Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "bench_vin": a.vin_bench,
                    "max_speed_bench_deg_s": round(max_speed(a.vin_bench), 1),
                    "rated_speed_deg_s_at_7v4": round(MAX_SPEED_7V4_DEG, 1),
                    "train_domain_vin": list(TRAIN_VIN),
                    "points": rows,
                    "extrapolation": ext,
                    "delay_band_ms": [15.0, 30.0],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON -> {p}")

    if not rows:
        print("no paired points -- check that BAM vin matches the bench voltage",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
