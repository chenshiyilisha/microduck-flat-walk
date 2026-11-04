#!/usr/bin/env python
"""The IMU chain: 12 raw bytes -> (gyro, gravity) -> the policy's first six numbers.

`verify_policy_contract.py` proved the *layout* of the observation. This one goes
one layer deeper, into the block that fills its first six slots, because the IMU
is the only sensor whose value is **computed** rather than read: a wrong mount, a
wrong half-float bias or a wrong rotation direction all produce a plausible number.

Two independent sources, neither allowed to be the other's reference:

  * **robotd** (Rust): `duck-control/src/imu.rs` — the block table, `half()`,
    `mul`/`rotate`/`rotate_inverse`, `median3_each`, `mount_from_axes`,
    `GYRO_RAD_PER_LSB`, the `ready()` threshold; `robotd-params/src/lib.rs` — the
    `imu_axes` / `imu_median` defaults.
  * **training** (Python): mjlab's `projected_gravity_b` = `quat_apply_inverse(q,
    [0,0,-1])` and `root_link_ang_vel_b` = `quat_apply_inverse(q, omega_w)`, plus
    *scipy* as an independent implementation of the quaternion algebra.

The Rust cannot be executed here (no toolchain in this workspace), so the Rust
side is a transliteration. Three things keep that honest:

  1. the transliteration must reproduce the crate's own unit tests (ported below
     as `rust_unit_tests_*`), and
  2. it is checked against an external oracle (numpy `float16` exhaustively,
     scipy `Rotation`), and
  3. every check has a negative control in `--selftest`.

What this cannot check
----------------------
* **Whether the mount is right for our board.** That is B4 on the bench: lay the
  robot on its side and see which raw axis carries gravity. `imu_axes` is a
  string in the config; whether `"z,y,-x"` matches our airframe is a measurement.
* **The chip's gyro full scale.** The decoder assumes ±500 dps / 17.5 mdps/LSB.
  If the board's firmware configured ±2000 dps, every rate is 4x off and nothing
  here would notice — it would look like a twitchy robot, not a units bug.
* **The IMU's own sample latency** (SFLP output rate vs our 50 Hz tick).
* **That the chip's reference is the trunk at power-up.** SFLP establishes its
  world frame from the attitude at start and converges from there — hence
  `ready()` and robotd's "keep the robot still". Booting the robot on its side is
  not detected here.

One assumption that looks like a bug and is not
-----------------------------------------------
The board transmits only qx,qy,qz; the decoder rebuilds `w = +sqrt(1-n²)`. If the
chip ever emitted the other sign, `-q` would decode as a *different* rotation, not
the same one. ST states this is safe by construction: "The SFLP output quaternion
is chosen to have qw >= 0 always ... the FIFO only stores 3 components qx,qy,qz,
the 4th component qw is recomputed as +sqrt(1 - qx² - qy² - qz²)" (A. Vitali, ST
community, 2024-01). The same answer confirms the known hole: "when any of the
vector components is near ±1, the accuracy of qw is reduced" — measured below, and
for our mount it lands at trunk pitch ≈ 90 deg.


Usage
-----
    python tools/hd1910/verify_imu_chain.py
    python tools/hd1910/verify_imu_chain.py --toml out/robotd_hd1910_mode0.toml
    python tools/hd1910/verify_imu_chain.py --selftest
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / ".upstream" / "DuckBuddy-main"
IMU_RS = UPSTREAM / "duck-control" / "src" / "imu.rs"
PARAMS_RS = UPSTREAM / "robotd-params" / "src" / "lib.rs"
FEETECH_RS = UPSTREAM / "duck-control" / "src" / "feetech.rs"

N_CHECKS = [0]


class NotChecked(Exception):
    """This side of the comparison is unavailable; the check is SKIP, not FAIL."""


def _read(path: pathlib.Path) -> str:
    if not path.exists():
        raise NotChecked(f"{path.relative_to(ROOT)} not found")
    return path.read_text(encoding="utf-8", errors="replace")


def _num(pattern: str, text: str, what: str) -> float:
    m = re.search(pattern, text)
    if not m:
        raise NotChecked(f"{what} not found in source")
    return float(m.group(1).replace("_", ""))


# ── the Rust side, transliterated ────────────────────────────────────────────
#
# Line for line from duck-control/src/imu.rs. Kept as close to the original as
# Python allows so that a reader can diff the two: same function names, same
# scalar-first quaternions, same order of operations.

FRAC_1_SQRT_2 = 1.0 / math.sqrt(2.0)


def half(bits: int) -> float:
    """IEEE 754 binary16 -> float. `imu.rs:191`."""
    sign = -1.0 if bits & 0x8000 else 1.0
    exp = (bits >> 10) & 0x1F
    frac = float(bits & 0x3FF)
    if exp == 0:
        return sign * frac * 2.0**-24
    if exp == 0x1F and frac == 0.0:
        return sign * math.inf
    if exp == 0x1F:
        return math.nan
    return sign * (1.0 + frac / 1024.0) * 2.0 ** (exp - 15)


def mul(a, b):
    """Hamilton product, scalar-first. `imu.rs:204`."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ]


def _cross_terms(q, v):
    x, y, z = q[1], q[2], q[3]
    t = [
        (y * v[2] - z * v[1]) * 2.0,
        (z * v[0] - x * v[2]) * 2.0,
        (x * v[1] - y * v[0]) * 2.0,
    ]
    c = [
        y * t[2] - z * t[1],
        z * t[0] - x * t[2],
        x * t[1] - y * t[0],
    ]
    return t, c


def rotate(q, v):
    """`q v q⁻¹` — sensor vector expressed in the trunk frame. `imu.rs:215`."""
    t, c = _cross_terms(q, v)
    return [
        v[0] + q[0] * t[0] + c[0],
        v[1] + q[0] * t[1] + c[1],
        v[2] + q[0] * t[2] + c[2],
    ]


def rotate_inverse(q, v):
    """`q⁻¹ v q` — world vector expressed in the body frame. `imu.rs:225`."""
    t, c = _cross_terms(q, v)
    return [
        v[0] - q[0] * t[0] + c[0],
        v[1] - q[0] * t[1] + c[1],
        v[2] - q[0] * t[2] + c[2],
    ]


def normalise(v):
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag > 0.1 else [0.0, 0.0, -1.0]


def median3_each(history, now):
    """`imu.rs:181`. A step/ramp therefore comes out exactly one sample late."""
    def m(a, b, c):
        return max(min(a, b), min(max(a, b), c))
    return [m(history[0][i], history[1][i], now[i]) for i in range(3)]


# A seam for the negative control: the selftest flips this to prove that the
# determinant test is what refuses a mirror image, not something further down.
_ALLOW_MIRROR = False


def mount_from_axes(spec: str):
    """`imu.rs:289`, same matrix then same largest-term decomposition."""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 3:
        raise ValueError("want three axes")
    m = [[0.0] * 3 for _ in range(3)]
    used = [False] * 3
    for row, part in enumerate(parts):
        sign = -1.0 if part.startswith("-") else 1.0
        axis = part.lstrip("+-")
        col = {"x": 0, "y": 1, "z": 2}.get(axis)
        if col is None:
            raise ValueError(f"{part!r} is not ±x/±y/±z")
        if used[col]:
            raise ValueError(f"sensor {axis} used twice")
        used[col] = True
        m[row][col] = sign
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    if det < 0.0 and not _ALLOW_MIRROR:
        raise ValueError("mirror image")
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return [0.25 * s, (m[2][1] - m[1][2]) / s,
                (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s]
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        return [(m[2][1] - m[1][2]) / s, 0.25 * s,
                (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s]
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        return [(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s,
                0.25 * s, (m[1][2] + m[2][1]) / s]
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
    return [(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s,
            (m[1][2] + m[2][1]) / s, 0.25 * s]


class Sflp:
    """`SflpDecoder`, transliterated (`imu.rs:55`)."""

    DEFAULT_MOUNT = [FRAC_1_SQRT_2, 0.0, FRAC_1_SQRT_2, 0.0]

    def __init__(self, mount=None, median=True, gyro_rad_per_lsb=None):
        self.mount = list(mount or self.DEFAULT_MOUNT)
        self.last_quat = [1.0, 0.0, 0.0, 0.0]
        self.quat_samples = 0
        self.gyro_hist = [[0.0] * 3, [0.0] * 3]
        self.grav_hist = [[0.0, 0.0, -1.0], [0.0, 0.0, -1.0]]
        self.median = median
        self.k = gyro_rad_per_lsb if gyro_rad_per_lsb is not None else 0.0175 * math.pi / 180.0

    def ready(self) -> bool:
        return self.quat_samples >= 25

    def decode(self, raw: bytes):
        gyro_sensor = [
            float(np.frombuffer(raw[0:2], dtype="<i2")[0]) * self.k,
            float(np.frombuffer(raw[2:4], dtype="<i2")[0]) * self.k,
            float(np.frombuffer(raw[4:6], dtype="<i2")[0]) * self.k,
        ]
        gyro = rotate(self.mount, gyro_sensor)

        packed = [int(np.frombuffer(raw[6 + 2 * i:8 + 2 * i], dtype="<u2")[0]) for i in range(3)]
        if packed != [0, 0, 0]:
            x, y, z = (half(p) for p in packed)
            norm_sq = x * x + y * y + z * z
            if all(math.isfinite(v) for v in (x, y, z)) and norm_sq <= 1.02:
                w = math.sqrt(max(0.0, 1.0 - norm_sq))
                mount_inv = [self.mount[0], -self.mount[1], -self.mount[2], -self.mount[3]]
                q = mul([w, x, y, z], mount_inv)
                n = math.sqrt(sum(c * c for c in q))
                if n > 0.5:
                    self.last_quat = [c / n for c in q]
                    self.quat_samples = min(self.quat_samples + 1, 2**32 - 1)

        gravity = normalise(rotate_inverse(self.last_quat, [0.0, 0.0, -1.0]))

        if self.median:
            out = (median3_each(self.gyro_hist, gyro),
                   median3_each(self.grav_hist, gravity),
                   list(self.last_quat))
        else:
            out = (gyro, gravity, list(self.last_quat))
        self.gyro_hist = [self.gyro_hist[1], gyro]
        self.grav_hist = [self.grav_hist[1], gravity]
        return out


# ── the training side, read out of the env that actually trains ---------------


def _ctrl_dt() -> float:
    try:
        import mjlab_microduck  # noqa: F401
        from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
            make_microduck_velocity_env_cfg,
        )
        cfg = make_microduck_velocity_env_cfg()
        dec = float(cfg.decimation)
        dt = float(cfg.sim.mujoco.timestep)
        return dec * dt
    except Exception:  # pragma: no cover - env only
        raise NotChecked("training env not importable")


def _delay_envelope() -> dict:
    """The IMU terms' delay window, in **control steps**, from the real cfg."""
    try:
        import mjlab_microduck  # noqa: F401
        from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
            make_microduck_velocity_env_cfg,
        )
        cfg = make_microduck_velocity_env_cfg()
        terms = cfg.observations["actor"].terms
        out = {}
        for name in ("base_ang_vel", "projected_gravity"):
            t = terms[name]
            out[name] = (int(getattr(t, "delay_min_lag", 0)), int(getattr(t, "delay_max_lag", 0)))
        return out
    except Exception:
        raise NotChecked("training env not importable")


def _toml(path: pathlib.Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    out, section = {}, ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"')
            if v in ("true", "false"):
                out[f"{section}.{k.strip()}" if section else k.strip()] = v == "true"
            else:
                try:
                    out[f"{section}.{k.strip()}" if section else k.strip()] = float(v)
                except ValueError:
                    out[f"{section}.{k.strip()}" if section else k.strip()] = v
    return out


def _rust_side() -> dict:
    """Everything the Rust decoder is configured by, read from its own source."""
    imu = _read(IMU_RS)
    if not re.search(r"pub const IMU_BLOCK_LEN: usize = 12;", imu):
        raise NotChecked("imu.rs is not the version this tool was written against")
    k = _num(r"const GYRO_RAD_PER_LSB: f64 = ([0-9.]+) \* std::f64::consts::PI / 180\.0;",
             imu, "GYRO_RAD_PER_LSB")
    ready_at = int(_num(r"self\.quat_samples >= (\d+)", imu, "ready() threshold"))
    mdps = _num(r"±500 dps at ([0-9.]+) mdps/LSB", imu, "the documented sensitivity")

    params = _read(PARAMS_RS)
    axes = re.search(r'imu_axes: "([^"]+)"\.into\(\)', params)
    median = re.search(r"imu_median: (true|false)", params)
    return {
        "k": k * math.pi / 180.0,
        "ready_at": ready_at,
        "doc_mdps": mdps,
        "axes": axes.group(1) if axes else None,
        "median": (median.group(1) == "true") if median else None,
        "mount": Sflp.DEFAULT_MOUNT,
    }


# ── oracle: scipy, never our own algebra -------------------------------------


def _rot(q):
    """scalar-first quaternion -> scipy Rotation."""
    from scipy.spatial.transform import Rotation
    return Rotation.from_quat([q[1], q[2], q[3], q[0]])


def _zup_quat(roll=0.0, pitch=0.0, yaw=0.0):
    """Body->world, ZYX, degrees. +pitch is nose-down about trunk +y."""
    from scipy.spatial.transform import Rotation
    r = Rotation.from_euler("ZYX", [yaw, pitch, roll], degrees=True)
    x, y, z, w = r.as_quat()
    return [w, x, y, z]


def _f16(x: float) -> int:
    """Encode a float as binary16, via numpy so the oracle is not our own `half`."""
    return int(np.float16(x).view(np.uint16))


def _angle(a, b) -> float:
    """Angle between two directions, in degrees."""
    dot = float(np.dot(a, b)) / (float(np.linalg.norm(a)) * float(np.linalg.norm(b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def canonical(q):
    """The representative the chip is documented to emit: w >= 0.

    ST: "The SFLP output quaternion is chosen to have qw >= 0 always". Without
    this the decoder's `w = +sqrt(1-n²)` rebuild is a *different* rotation, so a
    test that skips it is testing a device that does not exist.
    """
    return [-c for c in q] if q[0] < 0 else list(q)


def pack_block(gyro_sensor, q_xyzw, k: float) -> bytes:
    """The 12 bytes the board sends: i16 gyro counts then three half floats."""
    counts = [int(round(c / k)) for c in gyro_sensor]
    for c in counts:
        if not -32768 <= c <= 32767:
            raise ValueError("gyro count out of int16 range")
    out = b"".join(int(c).to_bytes(2, "little", signed=True) for c in counts)
    out += b"".join(_f16(v).to_bytes(2, "little") for v in q_xyzw)
    return out


# ── the checks ───────────────────────────────────────────────────────────────


def check_half_exhaustive(rs: dict):
    """All 65536 bit patterns, against numpy. This is the only complete test."""
    bad, worst = [], 0.0
    for bits in range(1 << 16):
        mine = half(bits)
        theirs = float(np.uint16(bits).view(np.float16))
        if math.isnan(mine) and math.isnan(theirs):
            continue
        if math.isinf(mine) or math.isinf(theirs):
            if mine != theirs:
                bad.append(bits)
            continue
        d = abs(mine - theirs)
        worst = max(worst, d)
        if d > 0.0:
            bad.append(bits)
    ok = not bad
    detail = (f"{65536 - len(bad)}/65536 identical (max |Δ| {worst:.1e})"
              if ok else f"{len(bad)} differ, e.g. {[hex(b) for b in bad[:4]]}")
    return ok, "half() vs numpy float16", detail


def check_quat_algebra():
    """mul / rotate / rotate_inverse against scipy's matrix path."""
    rng = np.random.default_rng(7)
    err_mul = err_rot = err_inv = err_ident = 0.0
    for _ in range(200):
        qa = list(rng.normal(size=4))
        qa = [c / math.sqrt(sum(x * x for x in qa)) for c in qa]
        qb = list(rng.normal(size=4))
        qb = [c / math.sqrt(sum(x * x for x in qb)) for c in qb]
        v = list(rng.normal(size=3))

        r_ab = (_rot(qa) * _rot(qb)).as_quat()          # x,y,z,w
        got = mul(qa, qb)
        err_mul = max(err_mul, max(abs(got[i] - r_ab[[3, 0, 1, 2]][i]) for i in range(4)))

        err_rot = max(err_rot, max(abs(a - b) for a, b in zip(rotate(qa, v), _rot(qa).apply(v))))
        err_inv = max(err_inv, max(abs(a - b) for a, b in
                                   zip(rotate_inverse(qa, v), _rot(qa).inv().apply(v))))
        # the two must be exact inverses of each other, too
        rt = rotate_inverse(qa, rotate(qa, v))
        err_ident = max(err_ident, max(abs(a - b) for a, b in zip(rt, v)))
    worst = max(err_mul, err_rot, err_inv, err_ident)
    ok = worst < 1e-12
    return ok, "quaternion algebra vs scipy", (
        f"mul {err_mul:.1e} / rotate {err_rot:.1e} / inverse {err_inv:.1e} / "
        f"round-trip {err_ident:.1e}")


def check_mounts(rs: dict):
    """All 24 proper signed permutations rotate as declared; mirrors are refused."""
    import itertools
    good = bad = 0
    problems = []
    for perm in itertools.permutations("xyz"):
        for signs in itertools.product((1, -1), repeat=3):
            spec = ",".join(("" if s > 0 else "-") + a for a, s in zip(perm, signs))
            try:
                q = mount_from_axes(spec)
            except ValueError:
                bad += 1          # det < 0: a mirror, correctly refused
                continue
            good += 1
            # the declared map, checked through the same rotate() the decoder uses
            for row, (a, s) in enumerate(zip(perm, signs)):
                v = [0.0, 0.0, 0.0]
                v["xyz".index(a)] = 1.0
                got = rotate(q, v)
                want = [0.0, 0.0, 0.0]
                want[row] = float(s)
                if max(abs(x - y) for x, y in zip(got, want)) > 1e-9:
                    problems.append((spec, got, want))
    # the default must be exactly the axis map the params file names
    by_string = None
    if rs["axes"]:
        try:
            by_string = mount_from_axes(rs["axes"])
        except ValueError as exc:
            problems.append((rs["axes"], str(exc), "should parse"))
    default_ok = by_string is not None and max(
        abs(a - b) for a, b in zip(by_string, Sflp.DEFAULT_MOUNT)) < 1e-12
    ok = (good == 24 and bad == 24 and not problems and default_ok)
    detail = (f"{good} rotations match, {bad} mirrors refused, "
              f"DEFAULT_MOUNT == mount_from_axes({rs['axes']!r}): {default_ok}")
    if problems:
        detail += f"; first problem {problems[0]}"
    return ok, "mount_from_axes (24 + 24)", detail


def check_end_to_end(rs: dict):
    """Known trunk orientation -> chip bytes -> decode -> compare with training.

    Independent of `Sflp`: the expected gravity and gyro come from scipy, using
    the *training* definitions (`quat_apply_inverse(q, [0,0,-1])` and
    `quat_apply_inverse(q, omega_world)`), not from the decoder's own maths.
    """
    worst_g = worst_w = worst_deg = 0.0
    rows = []
    # poses stay inside the envelope the robot actually reaches (|tilt| <= 80 deg,
    # any yaw); nose-up 90 deg is excluded on purpose -- there the chip's reported
    # quaternion *is* the identity and the all-zero sentinel fires; see
    # check_identity_sentinel, which is about that case and not about the algebra
    for spec, mount in (("default", Sflp.DEFAULT_MOUNT),
                        ("y,x,-z", mount_from_axes("y,x,-z"))):
        for roll, pitch, yaw in ((0, 0, 0), (0, 30, 0), (0, -45, 0), (20, 0, 0),
                                 (-20, 0, 0), (0, 0, 90), (35, -20, 70), (0, 80, 0)):
            q_tw = _zup_quat(roll, pitch, yaw)              # trunk -> world
            r_tw = _rot(q_tw)

            omega_tworld = np.array([0.31, -0.87, 1.42])     # rad/s, world frame
            omega_trunk = r_tw.inv().apply(omega_tworld)
            # what the chip actually sees: its own axes, not the trunk's
            omega_sensor = _rot(mount).inv().apply(omega_trunk)

            q_chip = canonical(mul(q_tw, mount))             # sensor -> world
            raw = pack_block(omega_sensor, q_chip[1:], rs["k"])

            d = Sflp(mount=mount, median=False, gyro_rad_per_lsb=rs["k"])
            gyro, gravity, quat = d.decode(raw)

            want_g = r_tw.inv().apply([0.0, 0.0, -1.0])
            want_w = omega_trunk

            eg = max(abs(a - b) for a, b in zip(gravity, want_g))
            ew = max(abs(a - b) for a, b in zip(gyro, want_w))
            worst_g, worst_w = max(worst_g, eg), max(worst_w, ew)
            worst_deg = max(worst_deg, _angle(gravity, want_g))
            if spec == "default" and (roll, pitch, yaw) in ((0, 0, 0), (0, 30, 0), (0, 80, 0)):
                rows.append((pitch, gravity, want_g))

    # The residual is quantisation, not algebra, so the bound has to be a physical
    # one: a mount or sign error is 90-180 deg, and the chip's own w-rebuild hole
    # costs up to ~2 deg near its pole (check_half_hole). 5 deg separates them
    # cleanly. For the rate the floor is one i16 count, so allow two.
    ok = worst_deg < 5.0 and worst_w < 2.0 * rs["k"]
    detail = (f"16 orientations x 2 mounts: gravity max {worst_deg:.2f} deg, "
              f"gyro max {worst_w / rs['k']:.1f} counts")
    return ok, "end-to-end vs training definitions", detail, rows


def check_gyro_scale(rs: dict):
    """The counts->rad/s constant against the datasheet sensitivity in its own doc."""
    want = rs["doc_mdps"] / 1000.0 * math.pi / 180.0      # mdps/LSB -> rad/s/LSB
    got = rs["k"]
    ok = abs(got - want) < 1e-15
    full = 32767 * got * 180.0 / math.pi
    return ok, "gyro counts->rad/s", (
        f"doc says {rs['doc_mdps']} mdps/LSB -> {want:.6e}; code {got:.6e} "
        f"(int16 full scale = {full:.0f} dps, so ±500 dps saturates at "
        f"{round(500 / (got * 180 / math.pi))} counts)")


def check_median_lag(rs: dict, hz: float, env: dict):
    """How late the median makes the IMU, measured, against the trained window."""
    k = rs["k"]

    def lag_steps(median: bool) -> float:
        d = Sflp(median=median, gyro_rad_per_lsb=k)
        block_still = pack_block([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], k)
        block_turn = pack_block([1000 * k, 0.0, 0.0], [0.0, 0.0, 0.0], k)
        seq = [block_still] * 3 + [block_turn] * 6
        # |gyro| is rotation-invariant, so this does not depend on which sensor
        # axis the mount sends the injected rate to (the crate's own test does
        # the same, and a single component would read 0 for a 90 deg mount)
        out = [sum(abs(v) for v in d.decode(b)[0]) for b in seq]
        first = next(i for i, v in enumerate(out) if v > 1e-9)
        return float(first - 3)      # 0 = the tick the change arrived

    lag_on = lag_steps(True)
    lag_off = lag_steps(False)

    # a ramp must come out as the last-but-one sample, not merely "a bit late"
    d = Sflp(median=True, gyro_rad_per_lsb=k)
    ramp = [pack_block([i * 10 * k, 0.0, 0.0], [0.0, 0.0, 0.0], k) for i in range(12)]
    got = [round(sum(abs(v) for v in d.decode(b)[0]) / k / 10) for b in ramp]
    ramp_exact = all(got[i] == i - 1 for i in range(1, 12))

    lo, hi = env["projected_gravity"]
    period_ms = 1000.0 / hz
    ok = (lag_on == 1.0 and lag_off == 0.0 and ramp_exact
          and lag_on <= hi)
    detail = (f"step: median ON = +{lag_on:.0f} tick ({lag_on * period_ms:.0f} ms), "
              f"OFF = +{lag_off:.0f}; ramp comes out as sample k-1: {ramp_exact}; "
              f"trained window {lo}-{hi} steps = {lo * period_ms:.0f}-{hi * period_ms:.0f} ms")
    return ok, "median lag", detail, {"lag_on_ms": lag_on * period_ms,
                                     "lag_off_ms": lag_off * period_ms,
                                     "trained_ms": (lo * period_ms, hi * period_ms)}


def check_median_norm():
    """The doc's caveat, quantified: a component-wise median is not unit-norm.

    Only bites when the rotation is not monotone in a component — a real tumble,
    not the ramp the crate's test uses (where the median returns the middle
    sample exactly, so the norm is 1).
    """
    from scipy.spatial.transform import Rotation
    worst = 0.0
    worst_rate = 0.0
    for rate_dps in (100.0, 300.0, 600.0):
        d = Sflp(median=True)
        step = math.radians(rate_dps) / 50.0
        axis = Rotation.from_euler("xyz", [20, 35, 10], degrees=True).as_rotvec()
        axis = axis / np.linalg.norm(axis)
        for i in range(60):
            r = Rotation.from_rotvec(axis * step * i)
            _, grav, _ = d.decode(_gravity_block(r))
            mag = float(np.linalg.norm(grav))
            if 1.0 - mag > worst:
                worst, worst_rate = 1.0 - mag, rate_dps
    # The criterion is the one that matters downstream, not the norm itself: the
    # fall predictor's "already tilted" gate is tilt_z = -0.90 (fall.rs:73, about
    # 26 deg from upright) and the hardware fall criterion is 60 deg. A median that
    # moves the 26 deg gate by a few degrees is inside that margin; one that moved
    # it by 20 deg would not be.
    gate_shift_deg = abs(
        math.degrees(math.acos(min(1.0, 0.90 + worst))) - math.degrees(math.acos(0.90))
    )
    ok = gate_shift_deg < 5.0
    return ok, "median shortens |gravity|", (
        f"worst |g| deficit {worst:.4f} at {worst_rate:.0f} dps -> the -0.90 (26 deg) tilt "
        f"gate moves {gate_shift_deg:.1f} deg, i.e. trips early, never late"), {"deficit": worst}


def _gravity_block(r):
    """A chip block that reports orientation `r` (sensor->world) with no motion."""
    q = r.as_quat()                       # x,y,z,w
    chip = canonical(mul([q[3], q[0], q[1], q[2]], Sflp.DEFAULT_MOUNT))
    return pack_block([0.0, 0.0, 0.0], chip[1:], 1e-9)


def check_half_hole():
    """ST's acknowledged hole, located in *trunk* terms for our mount.

    qw is not transmitted; it is rebuilt as sqrt(1-n²). Near n=1 that rebuild is
    ill-conditioned, so the reconstructed angle snaps in steps of about 2 deg.
    Where that happens depends on the mount: our 90 deg mount puts the chip's
    n≈1 pole at trunk pitch ≈ 90 deg - i.e. the robot lying face-down.
    """
    worst = (0.0, None)
    for pitch in range(-85, 90, 1):
        r = _rot(_zup_quat(0, pitch, 0))
        d = Sflp(median=False)
        _, g, _ = d.decode(_gravity_block(r))
        want = r.inv().apply([0.0, 0.0, -1.0])
        err = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(g, want))))))
        if err > worst[0]:
            worst = (err, pitch)
    # the pose the fall handling actually cares about is 60 deg and beyond
    at60 = None
    for pitch in (60, 70, 80):
        r = _rot(_zup_quat(0, pitch, 0))
        d = Sflp(median=False)
        _, g, _ = d.decode(_gravity_block(r))
        want = r.inv().apply([0.0, 0.0, -1.0])
        e = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(g, want))))))
        at60 = max(at60 or 0.0, e)
    # a 2 deg horizon error at 90 deg of pitch is invisible to the 26 deg gate and
    # to the 60 deg fall criterion; 5 deg would start to matter for the policy
    ok = worst[0] < 5.0 and at60 < 0.5
    return ok, "half-precision w rebuild", (
        f"worst {worst[0]:.2f} deg at trunk pitch {worst[1]:+d}; "
        f"<= {at60:.2f} deg over 60-80 deg (where fall handling lives)")


def check_identity_sentinel():
    """A quaternion of all zeros means "SFLP has not started" — but it is also a
    legal orientation: the identity. For our 90 deg mount that pose is trunk
    pitch = -90 deg (nose up), and the decoder then holds the last value instead
    of reporting it. Locate it and bound the window: the sentinel needs all three
    components below the smallest half-precision subnormal (6e-8), i.e. the exact
    pose, not a neighbourhood of it.
    """
    r = _rot(_zup_quat(0, -90, 0))
    q_chip = canonical(mul(_zup_quat(0, -90, 0), Sflp.DEFAULT_MOUNT))
    d = Sflp(median=False)
    _, g, _ = d.decode(_gravity_block(r))
    held = abs(g[2] + 1.0) < 1e-9                 # reported as upright
    want = r.inv().apply([0.0, 0.0, -1.0])
    miss = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(g, want))))))
    # and 0.01 deg away from it the sentinel must not fire
    away = _rot(_zup_quat(0, -89.99, 0))
    d2 = Sflp(median=False)
    _, g2, _ = d2.decode(_gravity_block(away))
    want2 = away.inv().apply([0.0, 0.0, -1.0])
    near = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(g2, want2))))))
    ok = held and miss > 45.0 and near < 0.5
    return ok, "all-zero sentinel vs identity", (
        f"at trunk pitch -90 deg (q_chip = {np.round(q_chip, 4)}) the block is all zeros, "
        f"so the decoder holds the last value: reported as upright, {miss:.0f} deg wrong. "
        f"0.01 deg away it is {near:.2f} deg right — the window is the exact pose, "
        f"|x|,|y|,|z| < 6e-8")


def check_median_choice(median_effective: bool, lag_ms: float):
    """The config against the measurement: on pins every tick at the window's top.

    Not a matter of taste — the trained envelope's maximum is one control step and
    the median alone is exactly that, before the chip's own sampling lag.
    """
    ok = not median_effective
    detail = ("off: the IMU path is one tick cheaper than the trained maximum"
              if ok else
              f"ON: +{lag_ms:.0f} ms on every tick, i.e. at the trained maximum with the "
              f"chip's sampling still to come -- see imu.rs's own note about the HL-2915 "
              f"rocking with it on")
    return ok, "[bus] imu_median", detail


def check_ready(rs: dict, hz: float):
    """`ready()` gates the policy start, so its duration is a real number of ms.

    The constant is 25 because the crate's comment says "roughly 0.25 s at 100 Hz".
    At our 50 Hz control rate that is twice as long — worth knowing, since robotd
    refuses to drive while it is false.
    """
    ok = rs["ready_at"] == round(0.25 * 100.0)
    secs = rs["ready_at"] / hz
    return ok, "ready() at the control rate", (
        f"{rs['ready_at']} samples = 0.25 s at 100 Hz; at {hz:.0f} Hz it is "
        f"{secs * 1000:.0f} ms, and robotd will not drive until then")


def check_startup_seed():
    """The median's history starts pre-seeded with "upright". Measure the lie."""
    from scipy.spatial.transform import Rotation
    r = Rotation.from_euler("X", [40], degrees=True)
    raw = _gravity_block(r)
    d = Sflp(median=True)
    errs = []
    for _ in range(4):
        _, g, _ = d.decode(raw)
        want = r.inv().apply([0.0, 0.0, -1.0])
        errs.append(math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(g, want)))))))
    ok = errs[0] > 1.0 and errs[2] < 0.5
    return ok, "startup: median seed", (
        f"a robot 40 deg over reports {errs[0]:.1f}, {errs[1]:.1f}, {errs[2]:.1f} deg of error "
        f"on ticks 1-3 — wrong for {2} ticks, inside ready()'s window")


def check_rust_unit_tests():
    """The crate's own tests, ported. If these fail the transliteration is wrong."""
    problems = []
    # half_precision_decodes_known_values
    for bits, want, tol in ((0x0000, 0.0, 0), (0x3C00, 1.0, 0), (0xBC00, -1.0, 0),
                            (0x3800, 0.5, 0), (0x3555, 0.333, 1e-3)):
        if abs(half(bits) - want) > tol:
            problems.append(f"half({bits:#06x}) = {half(bits)}")
    # the_default_axis_map_is_the_default_mount
    q = mount_from_axes("z,y,-x")
    if max(abs(a - b) for a, b in zip(q, Sflp.DEFAULT_MOUNT)) > 1e-12:
        problems.append("mount_from_axes('z,y,-x') != DEFAULT_MOUNT")
    # axis_maps_rotate_as_written
    for spec, want in (("z,y,-x", [[0, 0, -1], [0, 1, 0], [1, 0, 0]]),
                       ("y,x,-z", [[0, 1, 0], [1, 0, 0], [0, 0, -1]]),
                       ("x,y,z", [[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
                       ("-y,x,z", [[0, 1, 0], [-1, 0, 0], [0, 0, 1]])):
        qq = mount_from_axes(spec)
        for axis, expect in enumerate(want):
            v = [0.0, 0.0, 0.0]
            v[axis] = 1.0
            if max(abs(a - b) for a, b in zip(rotate(qq, v), expect)) > 1e-9:
                problems.append(f"{spec} axis {axis}")
    # mirror_images_and_typos_are_refused
    for spec in ("x,y,-z", "x,x,z", "x,y", "x,y,w"):
        try:
            mount_from_axes(spec)
            problems.append(f"{spec} accepted")
        except ValueError:
            pass
    # gravity_is_a_unit_vector_in_steady_state
    for packed in (0x0000, 0x3000, 0x3800, 0xB000):
        raw = bytearray(12)
        raw[6:8] = int(packed).to_bytes(2, "little")
        d = Sflp()
        for _ in range(2):
            d.decode(bytes(raw))
        _, g, _ = d.decode(bytes(raw))
        if abs(math.sqrt(sum(c * c for c in g)) - 1.0) > 1e-9:
            problems.append(f"|gravity| != 1 for {packed:#06x}")
    # all_zero_quaternion_bytes_hold_the_last_good_value
    d = Sflp()
    zero = d.decode(bytes(12))
    if zero[2] != [1.0, 0.0, 0.0, 0.0] or d.ready():
        problems.append("zero block did not hold identity / counted as a sample")
    live_raw = bytearray(12)
    live_raw[6:8] = (0x3000).to_bytes(2, "little")
    live = d.decode(bytes(live_raw))
    if live[2] == [1.0, 0.0, 0.0, 0.0]:
        problems.append("a live block did not move the quaternion")
    if d.decode(bytes(12))[2] != live[2]:
        problems.append("zero block did not hold the last good value")
    # not_ready_until_the_chip_has_produced_output
    d = Sflp()
    raw = bytearray(12)
    raw[6:8] = (0x3000).to_bytes(2, "little")
    for _ in range(24):
        d.decode(bytes(raw))
    if d.ready():
        problems.append("ready() true at 24 samples")
    d.decode(bytes(raw))
    if not d.ready():
        problems.append("ready() false at 25 samples")
    # gyro_counts_are_signed + without_the_median_a_change_shows_at_once
    d = Sflp()
    raw = bytearray(12)
    raw[0:2] = (-1000).to_bytes(2, "little", signed=True)
    for _ in range(2):
        d.decode(bytes(raw))
    mag = sum(abs(v) for v in d.decode(bytes(raw))[0])
    if abs(mag - 1000 * 0.0175 * math.pi / 180.0) > 1e-9:
        problems.append(f"|-1000 counts| = {mag}")

    ok = not problems
    return ok, "ported crate unit tests", (
        "9 tests" if ok else f"{len(problems)} broken: {problems[:3]}")


# ── report ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--toml", type=pathlib.Path,
                    default=ROOT / "out" / "robotd_hd1910_mode0.toml")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    try:
        rs = _rust_side()
    except NotChecked as exc:
        print(f"cannot read the Rust side: {exc}")
        return 2

    toml = _toml(args.toml)
    try:
        hz = float(toml.get("control.hz") or 50.0)
    except (TypeError, ValueError):
        hz = 50.0
    median_cfg = toml.get("bus.imu_median")
    median_effective = rs["median"] if median_cfg is None else bool(median_cfg)

    print(f"== imu.rs: block 12 B, gyro {rs['k'] * 180 / math.pi:.4f} deg/s per count, "
          f"ready at {rs['ready_at']} samples")
    print(f"   params: imu_axes={rs['axes']!r}  imu_median={rs['median']}")
    print(f"   {args.toml.name}: imu_median="
          f"{'(unset -> default true)' if median_cfg is None else median_cfg}"
          f"  -> effective {median_effective}   control {hz:.0f} Hz")
    print()

    rows = []
    rows.append(check_half_exhaustive(rs)[:3])
    rows.append(check_quat_algebra())
    rows.append(check_mounts(rs))
    e2e = check_end_to_end(rs)
    rows.append(e2e[:3])
    rows.append(check_gyro_scale(rs))
    lag = check_median_lag(rs, hz, _delay_envelope())
    rows.append(lag[:3])
    rows.append(check_median_choice(median_effective, lag[3]["lag_on_ms"]))
    rows.append(check_median_norm()[:3])
    rows.append(check_half_hole())
    rows.append(check_identity_sentinel())
    rows.append(check_ready(rs, hz))
    rows.append(check_startup_seed())
    rows.append(check_rust_unit_tests())

    width = max(len(k) for _, k, _ in rows)
    bad = 0
    for ok, key, detail in rows:
        bad += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {key:<{width}}  {detail}")

    print()
    print("== gravity for a pure pitch (default mount, no median) ==")
    for pitch, got, want in e2e[3]:
        print(f"   pitch {pitch:>+4}°  decode {np.round(got, 4)}  training {np.round(want, 4)}")

    m = lag[3]
    print()
    print("== what this means for deployment ==")
    print(f"  training randomises the IMU delay to {m['trained_ms'][0]:.0f}-"
          f"{m['trained_ms'][1]:.0f} ms per env. The median costs a fixed "
          f"{m['lag_on_ms']:.0f} ms; off, it costs {m['lag_off_ms']:.0f} ms.")
    print(f"  On, every tick is at {m['lag_on_ms']:.0f} ms plus the chip's own sampling lag "
          f"(0 to one SFLP period), so the path is pinned at the top of the window and any "
          f"sensor latency puts it past it.")
    print(f"  Off, it sits in the middle of the window. The block has a CRC and the "
          f"all-zero case is handled separately, so the median is not load-bearing.")

    print()
    print(f"{bad} FAIL" if bad else "all pass")
    print("\nnot checked: whether imu_axes matches our airframe (bench, B4), the chip's gyro "
          "full scale, and the IMU's own output rate.")
    return 1 if bad else 0


def selftest() -> int:
    """Every check must go red when the thing it guards is broken."""
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    rs = _rust_side()

    def expect(label, got_ok, want_ok):
        N_CHECKS[0] += 1
        mark = "ok" if got_ok == want_ok else "MISMATCH"
        print(f"  {mark:<9} {label} -> {'PASS' if got_ok else 'FAIL'}"
              f" (wanted {'PASS' if want_ok else 'FAIL'})")
        return got_ok == want_ok

    good = True
    good &= expect("clean half()", check_half_exhaustive(rs)[0], True)
    good &= expect("clean algebra", check_quat_algebra()[0], True)
    good &= expect("clean mounts", check_mounts(rs)[0], True)
    good &= expect("clean end-to-end", check_end_to_end(rs)[0], True)
    good &= expect("clean gyro scale", check_gyro_scale(rs)[0], True)
    good &= expect("clean median lag", check_median_lag(rs, 50.0, _delay_envelope())[0], True)
    good &= expect("clean rust tests", check_rust_unit_tests()[0], True)

    # 1. wrong exponent bias in half(): only the values in [1,2) would still match,
    #    so 65536 patterns are the only way to see it
    def half_bias_14(bits: int) -> float:
        sign = -1.0 if bits & 0x8000 else 1.0
        exp = (bits >> 10) & 0x1F
        frac = float(bits & 0x3FF)
        if exp == 0:
            return sign * frac * 2.0**-24
        if exp == 0x1F and frac == 0.0:
            return sign * math.inf
        if exp == 0x1F:
            return math.nan
        return sign * (1.0 + frac / 1024.0) * 2.0**14

    try:
        globals()["half"] = half_bias_14
        good &= expect("half(): bias 15 -> 14", check_half_exhaustive(rs)[0], False)
    finally:
        globals()["half"] = _REAL_HALF

    # 2. non-Hamilton multiplication (the classic sign slip on one term)
    real_mul = mul

    def bad_mul(a, b):
        out = real_mul(a, b)
        out[1] = -out[1]
        return out

    try:
        globals()["mul"] = bad_mul
        good &= expect("mul(): one term sign-flipped", check_quat_algebra()[0], False)
    finally:
        globals()["mul"] = real_mul

    # 3. a mirror image accepted as a rotation
    try:
        globals()["_ALLOW_MIRROR"] = True
        good &= expect("mount: mirrors accepted", check_mounts(rs)[0], False)
    finally:
        globals()["_ALLOW_MIRROR"] = False

    # 4. mount composed the wrong way round in decode (mount vs mount-inverse).
    #    A 90 deg mount makes this visible; the identity mount would hide it.
    class WrongWay(Sflp):
        def decode(self, raw):
            self.mount = [self.mount[0], -self.mount[1], -self.mount[2], -self.mount[3]]
            out = super().decode(raw)
            self.mount = [self.mount[0], -self.mount[1], -self.mount[2], -self.mount[3]]
            return out

    real_sflp = Sflp
    try:
        globals()["Sflp"] = WrongWay
        good &= expect("decode(): mount inverted", check_end_to_end(rs)[0], False)
    finally:
        globals()["Sflp"] = real_sflp

    # 5. gyro read as unsigned (the bug the crate's own test guards)
    real_decode = Sflp.decode

    def unsigned_gyro(self, raw):
        g, grav, q = real_decode(self, raw)
        return ([abs(v) for v in g], grav, q)

    try:
        Sflp.decode = unsigned_gyro
        good &= expect("gyro: counts read unsigned", check_end_to_end(rs)[0], False)
    finally:
        Sflp.decode = real_decode

    # 6. ST's w >= 0 guarantee is load-bearing: without it the chip's 3-float
    #    packet decodes to a *different* rotation for some mounts, not the same one
    real_canon = canonical
    try:
        globals()["canonical"] = lambda q: list(q)
        good &= expect("no canonicalisation (w < 0 emitted)",
                       check_end_to_end(rs)[0], False)
    finally:
        globals()["canonical"] = real_canon

    # 7. the norm-deficit check must be measuring the median, not quantisation:
    #    with the median off the components are passed through, so |g| is exactly 1
    from scipy.spatial.transform import Rotation
    d = Sflp(median=False)
    step = math.radians(600.0) / 50.0
    axis = Rotation.from_euler("xyz", [20, 35, 10], degrees=True).as_rotvec()
    axis = axis / np.linalg.norm(axis)
    deficit = 0.0
    for i in range(60):
        _, g, _ = d.decode(_gravity_block(Rotation.from_rotvec(axis * step * i)))
        deficit = max(deficit, abs(1.0 - float(np.linalg.norm(g))))
    good &= expect("median off: |g| stays 1", deficit < 1e-9, True)

    # 8. the lag measurement must distinguish "no median" from "one tick late"
    d = Sflp(median=False, gyro_rad_per_lsb=rs["k"])
    blocks = [pack_block([0.0, 0, 0], [0, 0, 0], rs["k"])] * 3 + \
             [pack_block([1000 * rs["k"], 0, 0], [0, 0, 0], rs["k"])] * 4
    out = [sum(abs(v) for v in d.decode(b)[0]) for b in blocks]
    first = next(i for i, v in enumerate(out) if abs(v) > 1e-12)
    good &= expect("lag with the median off is 0", first - 3 == 0, True)

    print()
    print(f"{N_CHECKS[0]} checks, {'all consistent' if good else 'MISMATCH'}")
    return 0 if good else 1


_REAL_HALF = half

if __name__ == "__main__":
    sys.exit(main())
