#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""HD1910 deploy rehearsal — same instrument as ``tools/rehearse_deploy.py``.

Upstream ``infer_policy.load_bam_model`` hardcodes XL330 / m6 / ``kp_fw=200``.
This wrapper keeps that file untouched and patches the loaded module so the
rehearsal plant matches OpenMicroDuck **m5** (``kp_fw=32``), the same plant the
HD1910 explore ONNX was trained against.

Usage (from ``microduck-software/``)::

  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --sweep
  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --condition nominal

Defaults: explore ONNX + ``out/rehearse_hd1910_*.json``. Extra argv is forwarded
to ``rehearse_deploy.main`` (``--cmd-vx``, ``--seconds``, ``--out``, …).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "hd1910"))

# Register HD1910Actuator before any bam.model.load_model(json_file=…).
import bam_actuators  # noqa: E402,F401
import rehearse_deploy as rd  # noqa: E402
from plant_spec import HD1910_OPENMICRODUCK_M5, M5_JSON  # noqa: E402

DEFAULT_ONNX = ROOT / "out" / "hd1910_explore_4096x2000_1026_it1999.onnx"
DEFAULT_OUT = ROOT / "out" / "rehearse_hd1910_explore_4096x2000_1026_it1999.json"
PLANT = HD1910_OPENMICRODUCK_M5
KP_FW = float(PLANT["kp_fw"])  # 32.0 — firmware reg 50 / training contract


def _patch_upstream(mod):
    """Replace XL330 motor_name lookup with local m5.json + register."""
    json_file = str(pathlib.Path(PLANT["json_path"]).resolve())
    if not pathlib.Path(json_file).is_file():
        raise SystemExit(f"HD1910 plant JSON missing: {json_file}")

    def load_bam_model(kp_fw: float, vin: float, max_current):
        from bam.model import load_model

        # Case-insensitive actuator table key is HD1910 (see tools/bam_actuators.py).
        bam_model = load_model(json_file=json_file)
        bam_model.actuator.kp = kp_fw
        bam_model.actuator.vin = vin
        bam_model.actuator.max_current = (
            max_current if (max_current and max_current > 0) else None
        )
        return bam_model

    mod.load_bam_model = load_bam_model
    mod.BAM_MOTOR_NAME = "hd1910"
    mod.BAM_MODEL = "m5"
    mod.BAM_KP_FW = KP_FW
    return mod


_orig_load_upstream = rd.load_upstream


def _load_upstream_hd1910(path: pathlib.Path):
    return _patch_upstream(_orig_load_upstream(path))


rd.load_upstream = _load_upstream_hd1910

# Annotate JSON so readers do not confuse XL330 rehearsal numbers with HD1910.
_xl330_same = list(rd.TRAINING_PARITY["same"])
rd.TRAINING_PARITY = {
    "same": [
        f"BAM OpenMicroDuck m5 on HD1910 (json={M5_JSON.name}, kp_fw={KP_FW:g}, "
        "target_names_expr excludes passive_*) — patched via rehearse_hd1910.py",
        *_xl330_same[1:],  # obs / action scale / pose / 50 Hz / projected gravity
    ],
    "differs": [
        *rd.TRAINING_PARITY["differs"],
        "plant is HD1910 m5 (kt=0.692 R=3.75 kp_fw=32), not XL330 m6 (kp_fw=200); "
        "infer_policy.py itself is unchanged",
    ],
}


def _inject_defaults(argv: list[str]) -> list[str]:
    """Ensure --onnx / --kp-fw / --out exist; leave user overrides alone."""
    out = list(argv)
    if "--onnx" not in out:
        if not DEFAULT_ONNX.is_file():
            raise SystemExit(f"default ONNX missing: {DEFAULT_ONNX}")
        out = ["--onnx", str(DEFAULT_ONNX), *out]
    if "--kp-fw" not in out:
        # rehearse_deploy hardcodes 200 when kp_fw is None — always pin 32 here.
        out = ["--kp-fw", str(KP_FW), *out]
    if "--out" not in out:
        out = ["--out", str(DEFAULT_OUT), *out]
    return out


def main(argv: list[str] | None = None) -> int:
    # Lightweight pre-parse so ``-h`` mentions HD1910 defaults; real parse is inside
    # rehearse_deploy.main.
    pre = argparse.ArgumentParser(
        description=(
            f"HD1910 deploy rehearsal (plant m5, kp_fw={KP_FW:g}). "
            "Forwards all flags to tools/rehearse_deploy.py."
        ),
        add_help=False,
    )
    pre.add_argument("-h", "--help", action="store_true")
    known, rest = pre.parse_known_args(argv)
    if known.help:
        print(
            f"HD1910 wrapper defaults:\n"
            f"  plant   : {PLANT['id']}  ({M5_JSON})\n"
            f"  kp_fw   : {KP_FW:g}\n"
            f"  --onnx  : {DEFAULT_ONNX}\n"
            f"  --out   : {DEFAULT_OUT}\n"
            f"\nForwarded to rehearse_deploy (pass any of its flags):\n"
        )
        return rd.main(["--help"])
    return rd.main(_inject_defaults(rest))


if __name__ == "__main__":
    raise SystemExit(main())
