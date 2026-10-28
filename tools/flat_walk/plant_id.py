"""Fingerprint the *live* actuator plant so every reading records what it measured on.

Why this exists
---------------
On 2026-10-27 the live plant was switched from XL330 m6 (``kp_fw=200``) to HD1910 m5
(``kp_fw=32``) by editing ``site-packages/mjlab_microduck/robot/microduck_constants.py``.
Nothing in the eval artifacts looked different:

* ``microduck_velocity_env_cfg.py`` sha still matched the training-time record
* ``mdp.py`` sha still matched
* ``curriculum_counter_before_pin`` still came out 30024

...because the plant lives **one import level deeper** than the two files those
hashes cover: the cfg imports ``MICRODUCK_WALK_ROBOT_CFG`` from ``microduck_constants``,
and that module builds the actuator from ``_BAM_ACTUATOR_KWARGS``. The recorded hashes
say "the cfg file is unchanged"; they say nothing about its transitive closure.

The same command therefore moved from vx 0.316 / 0% falls to vx 0.109 / 100% falls
with no visible cause, and it took half a day to find. Every evaluation now stamps
this fingerprint, so a reading can never again be ambiguous about its plant.

Usage
-----
    from plant_id import fingerprint, one_line
    meta = fingerprint()   # dict, JSON-serialisable
    print(one_line())      # short human string for console headers
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

# Values recorded 2026-10-27 by switching plants with tools/hd1910/apply_to_live.py.
KNOWN_PLANTS = {
    "xl330": {"kp_fw": 200.0, "model": "m6", "json_path": None},
    "hd1910": {"kp_fw": 32.0, "model": None, "json_path": "m5.json"},
}


def _sha_file(p: str | Path, n: int = 12) -> str | None:
    try:
        b = Path(p).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(b).hexdigest()[:n]


def _kwargs() -> dict:
    mod = importlib.import_module("mjlab_microduck.robot.microduck_constants")
    return dict(getattr(mod, "_BAM_ACTUATOR_KWARGS", {}))


def label(kw: dict | None = None) -> str:
    """Best-effort plant name: 'xl330', 'hd1910', or 'unknown'."""
    kw = _kwargs() if kw is None else kw
    json_path = kw.get("json_path")
    if json_path and "hd1910" in str(json_path).lower():
        return "hd1910"
    if kw.get("motor_name") == "xl330":
        return "xl330"
    return "unknown"


def fingerprint() -> dict:
    """Everything needed to answer later: 'which plant produced this number?'"""
    mod = importlib.import_module("mjlab_microduck.robot.microduck_constants")
    kw = _kwargs()
    name = label(kw)
    jp = kw.get("json_path")
    out = {
        "name": name,
        "source_file": getattr(getattr(mod, "__file__", None), "__str__", lambda: None)(),
        "source_sha256_12": _sha_file(mod.__file__) if getattr(mod, "__file__", None) else None,
        "kwargs": kw,
        "json_path_exists": bool(jp and Path(jp).exists()),
        "json_sha256_12": _sha_file(jp) if jp else None,
        # A policy trained on one plant is not expected to work on another;
        # record the gain explicitly because it is the number that bites.
        "kp_fw": kw.get("kp_fw"),
        "actuator_class": getattr(mod, "actuators", None).__class__.__name__
        if getattr(mod, "actuators", None) is not None else None,
    }
    return out


def one_line(fp: dict | None = None) -> str:
    fp = fingerprint() if fp is None else fp
    extra = f" kp_fw={fp['kp_fw']}" if fp.get("kp_fw") is not None else ""
    warn = ""
    if fp["name"] == "unknown":
        warn = "  <-- UNKNOWN PLANT, do not compare against any archived reading"
    return f"plant={fp['name']}{extra} (sha {fp['source_sha256_12']}){warn}"


if __name__ == "__main__":
    print(one_line())
