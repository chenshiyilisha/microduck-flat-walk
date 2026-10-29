# SPDX-License-Identifier: Apache-2.0
"""Print what a BAM params JSON *actually* resolves to — not what it claims.

Why this exists
---------------
Two indirection layers make a params file lie about the plant it produces:

1. ``"actuator"`` selects a **control law class** from ``bam.actuators``. The official
   table only carries ``sts3215`` for Feetech; ``hd1910``/``HD1910`` are names this
   repo registers itself, so those resolve to *our* class with a different law.
2. ``Model.load_parameters_from_dict`` overwrites any parameter whose name appears as
   a JSON key — including ones the actuator class set in ``initialize()``. Writing
   ``max_velocity: 100`` therefore silently disables the servo's internal speed cap.

Reading numbers off the JSON cannot catch either. This loads the model and prints what
the objects ended up holding, which is the only thing the simulation actually uses.

Usage::

    .venv-mjlab/Scripts/python.exe tools/hd1910/probe_plant_law.py \\
        --json tools/bam_params/hd1910/official_m6_stslaw.json --kp-fw 5

Exit code is 0 always; it is a measuring instrument, not a gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def probe(json_path: Path, kp_fw: float | None) -> dict:
    # The register module must be imported first: it adds the repo's own
    # actuator names to bam.actuators, otherwise those JSON keys KeyError.
    sys.path.insert(0, str(ROOT / "tools"))
    import bam_actuators  # noqa: F401

    from bam.model import load_model

    model = load_model(str(json_path))
    act = model.actuator

    if kp_fw is not None:
        act.kp = kp_fw

    def val(name: str):
        p = getattr(model, name, None)
        return getattr(p, "value", None) if p is not None else None

    return {
        "json": str(json_path),
        "json_actuator_key": json.loads(json_path.read_text(encoding="utf-8")).get(
            "actuator"
        ),
        "json_model": json.loads(json_path.read_text(encoding="utf-8")).get("model"),
        "law_class": type(act).__name__,
        "kp_effective": getattr(act, "kp", None),
        "vin": getattr(act, "vin", None),
        "max_pwm": getattr(act, "max_pwm", None),
        "max_current": getattr(act, "max_current", None),
        "error_gain": getattr(act, "error_gain", None),
        "error_gain_ratio": val("error_gain_ratio"),
        # Internal target-position speed cap (rad/s). None => no cap at all.
        "max_velocity_rad_s": val("max_velocity"),
        "has_internal_speed_cap": hasattr(act, "q_target_smooth")
        or "q_target_smooth" in type(act).__dict__.get("__annotations__", ""),
        "kt": val("kt"),
        "R": val("R"),
        "armature": val("armature"),
        "command_delay": val("command_delay") or json.loads(
            json_path.read_text(encoding="utf-8")
        ).get("command_delay"),
    }


CAP_REF = (3400 * 2 * 3.141592653589793) / 4096  # official STS3215 default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", nargs="+", required=True, type=Path)
    ap.add_argument(
        "--kp-fw",
        type=float,
        default=None,
        help="simulate mjlab's cfg.kp_fw override (actuator.kp = value)",
    )
    a = ap.parse_args()

    rows = [probe(p, a.kp_fw) for p in a.json]

    keys = [
        "law_class",
        "kp_effective",
        "vin",
        "max_pwm",
        "max_current",
        "error_gain",
        "error_gain_ratio",
        "max_velocity_rad_s",
        "kt",
        "R",
    ]
    labels = {p.name for p in a.json}
    for i, r in enumerate(rows):
        print("=" * 72)
        print(f"[{r['json']}]  ({a.json[i].name})")
        print(f"  json actuator key : {r['json_actuator_key']}  model={r['json_model']}")
        for k in keys:
            v = r[k]
            print(f"  {k:<20}: {v}")
        mv = r["max_velocity_rad_s"]
        if mv is None:
            print("  !! no max_velocity parameter — internal speed cap cannot apply")
        else:
            flag = (
                "official-cap OK" if abs(mv - CAP_REF) < 1e-6 else "NON-DEFAULT cap"
            )
            print(f"  speed cap vs official {CAP_REF:.4f} rad/s -> {flag}")

    if len(rows) > 1:
        print("=" * 72)
        print("diff (only fields that differ):")
        base = rows[0]
        for r in rows[1:]:
            print(f"  {base['json']}  vs  {r['json']}")
            for k in keys + ["has_internal_speed_cap"]:
                if base.get(k) != r.get(k):
                    print(f"    {k:<20}: {base.get(k)!r}  ->  {r.get(k)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
