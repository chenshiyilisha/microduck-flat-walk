#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""HD1910 deploy rehearsal — same instrument as ``tools/rehearse_deploy.py``.

Upstream ``infer_policy.load_bam_model`` hardcodes XL330 / m6 / ``kp_fw=200``.
This wrapper keeps that file untouched and patches the loaded module so the
rehearsal plant matches an HD1910 plant spec from ``plant_spec.py``.

Which plant
-----------
``--plant live`` (the default) reads the plant actually installed in the live
``microduck_constants.py`` and rehearses against **that**. Two reasons it is the
default rather than a fixed preset:

* the policy being rehearsed was trained against the live plant, so anything
  else is a plant mismatch (the XL330<->HD1910 incident, docs/05-flat-walk §10);
* a hardcoded preset silently keeps working after the live plant changes, and
  the rehearsal numbers then describe a robot nobody trained on.

Pass ``--plant p3|m5|ftservo`` only to rehearse a plant you are NOT live on, and
read the echoed ``plant:`` line + the ``settings.plant`` block in the JSON back.

Presets (``tools/hd1910/plant_spec.py``)::

    p3      hd1910_official_m6_kp5   official STS3215 law, kp_fw=5   <- ruled target
    m5      hd1910_openmicroduck_m5  local m5.json,        kp_fw=32
    ftservo hd1910_ftservo_official_m6  official params,   kp_fw=32

Usage (from ``microduck-software/``)::

  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --sweep
  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --condition nominal
  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --plant p3 --onnx out/x.onnx

Extra argv is forwarded to ``rehearse_deploy.main`` (``--command``/``--cmd-vx``,
``--seconds``, ``--out``, …).
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
from plant_spec import (  # noqa: E402
    HD1910_FTSERVO_OFFICIAL_M6,
    HD1910_OFFICIAL_M6_KP5,
    HD1910_OPENMICRODUCK_M5,
)

DEFAULT_ONNX = ROOT / "out" / "onnx_p3head030_it1600.onnx"
DEFAULT_OUT = ROOT / "out" / "rehearse_p3head030_it1600.json"

#: Pristine copy of rehearse_deploy's parity note. _publish_parity() rewrites
#: rd.TRAINING_PARITY, so it must always build from this, never from rd's current
#: value — otherwise two calls in one process would stack annotations.
_BASE_PARITY = {
    "same": list(rd.TRAINING_PARITY["same"]),
    "differs": list(rd.TRAINING_PARITY["differs"]),
}

#: ``--plant`` value -> preset. "live" is resolved through apply_to_live._readback.
PLANTS = {
    "p3": HD1910_OFFICIAL_M6_KP5,
    "m5": HD1910_OPENMICRODUCK_M5,
    "ftservo": HD1910_FTSERVO_OFFICIAL_M6,
}

#: ``detected`` string in microduck_constants.py -> preset key.
DETECTED_TO_PRESET = {
    "hd1910_kp5": "p3",
    "hd1910": "m5",
    "hd1910_ftservo_m6": "ftservo",
}

#: Filled in by main() before rd.main() runs; _patch_upstream reads it.
_STATE: dict[str, object] = {"key": None, "plant": None}


def resolve_plant(spec: str) -> tuple[str, dict]:
    """Return (preset key, preset dict) for a --plant value, refusing mismatches."""
    if spec != "live":
        if spec not in PLANTS:
            raise SystemExit(f"--plant {spec!r} not one of: live,{','.join(PLANTS)}")
        return spec, PLANTS[spec]

    import apply_to_live as atl  # local: keeps import cost off the --help path

    info = atl._readback()
    det = info.get("detected")
    if det not in DETECTED_TO_PRESET:
        raise SystemExit(
            f"live plant is {det!r}, which is not an HD1910 plant (or the constants "
            "file could not be parsed); pass --plant p3|m5|ftservo explicitly"
        )
    key = DETECTED_TO_PRESET[det]
    want_kp = float(PLANTS[key]["kp_fw"])
    got_kp = info.get("kp_fw")
    if got_kp is None or abs(float(got_kp) - want_kp) > 1e-9:
        raise SystemExit(
            f"live plant {det} reports kp_fw={got_kp} but preset {key} says {want_kp}; "
            "the live constants file is inconsistent — fix it with apply_to_live.py "
            "before rehearsing"
        )
    return key, PLANTS[key]


def _patch_upstream(mod):
    """Replace XL330 motor_name lookup with the resolved HD1910 preset."""
    plant = _STATE["plant"]
    if plant is None:  # pragma: no cover - main() always resolves first
        raise SystemExit("bug: plant not resolved before load_upstream")
    json_file = str(pathlib.Path(plant["json_path"]).resolve())
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
    mod.BAM_MODEL = plant["model"]
    mod.BAM_KP_FW = float(plant["kp_fw"])
    return mod


_orig_load_upstream = rd.load_upstream


def _load_upstream_hd1910(path: pathlib.Path):
    return _patch_upstream(_orig_load_upstream(path))


rd.load_upstream = _load_upstream_hd1910


def _publish_parity(key: str, plant: dict) -> None:
    """Annotate the JSON so readers cannot confuse this with an XL330 rehearsal."""
    json_name = pathlib.Path(plant["json_path"]).name
    rd.TRAINING_PARITY = {
        "same": [
            f"HD1910 plant '{key}' = {plant['id']} (json={json_name}, "
            f"kp_fw={float(plant['kp_fw']):g}, model={plant['model']}, "
            "target_names_expr excludes passive_*) — patched via rehearse_hd1910.py",
            *list(_BASE_PARITY["same"][1:]),
        ],
        "differs": [
            *list(_BASE_PARITY["differs"]),
            f"plant is {plant['id']} (kp_fw={float(plant['kp_fw']):g}), not XL330 m6 "
            "(kp_fw=200); infer_policy.py itself is unchanged",
        ],
    }


def _strip_plant(argv: list[str]) -> list[str]:
    """Drop ``--plant VAL`` / ``--plant=VAL`` *including its value*.

    Stripping only the flag leaves the preset name as a stray positional in the
    argv forwarded to rehearse_deploy, which then dies on an unrecognised
    argument — so consume the value too.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--plant":
            i += 2  # flag + value
            continue
        if a.startswith("--plant="):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _inject_defaults(argv: list[str], kp_fw: float) -> list[str]:
    """Ensure --onnx / --kp-fw / --out exist; leave user overrides alone."""
    out = list(argv)
    if "--onnx" not in out:
        if not DEFAULT_ONNX.is_file():
            raise SystemExit(
                f"default ONNX missing: {DEFAULT_ONNX} (pass --onnx explicitly)"
            )
        out = ["--onnx", str(DEFAULT_ONNX), *out]
    if "--kp-fw" not in out:
        # rehearse_deploy hardcodes 200 when kp_fw is None — always pin the plant's P.
        out = ["--kp-fw", str(kp_fw), *out]
    if "--out" not in out:
        out = ["--out", str(DEFAULT_OUT), *out]
    return out


def main(argv: list[str] | None = None) -> int:
    # Lightweight pre-parse so ``-h`` mentions the defaults; real parse is inside
    # rehearse_deploy.main.
    pre = argparse.ArgumentParser(
        description="HD1910 deploy rehearsal. Forwards all flags to tools/rehearse_deploy.py.",
        add_help=False,
    )
    pre.add_argument("-h", "--help", action="store_true")
    pre.add_argument("--plant", default="live", help="live|p3|m5|ftservo")
    known, rest = pre.parse_known_args(argv)

    if known.help:
        print(
            "HD1910 wrapper defaults:\n"
            f"  --plant : {known.plant}   (p3={HD1910_OFFICIAL_M6_KP5['id']}, "
            f"m5={HD1910_OPENMICRODUCK_M5['id']}, "
            f"ftservo={HD1910_FTSERVO_OFFICIAL_M6['id']})\n"
            f"  --onnx  : {DEFAULT_ONNX}\n"
            f"  --out   : {DEFAULT_OUT}\n"
            "\nForwarded to rehearse_deploy (pass any of its flags):\n"
        )
        return rd.main(["--help"])

    # --plant was consumed above, so it must not reach the forwarded argv.
    rest = _strip_plant(rest)
    key, plant = resolve_plant(known.plant)
    _STATE["key"], _STATE["plant"] = key, plant
    kp_fw = float(plant["kp_fw"])
    _publish_parity(key, plant)

    print(
        f"plant: {key} -> {plant['id']}  json={pathlib.Path(plant['json_path']).name}  "
        f"kp_fw={kp_fw:g}"
    )
    return rd.main(_inject_defaults(rest, kp_fw))


if __name__ == "__main__":
    raise SystemExit(main())
