# SPDX-License-Identifier: Apache-2.0
"""Canonical HD1910 / XL330 plant numbers and provenance (single source of truth).

See ``microduck-HD1910软件方案.md``. Do not invent numbers here — every value
must point at a file or upstream doc.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # microduck-software/
M5_JSON = (ROOT / "tools" / "bam_params" / "hd1910" / "m5.json").resolve()
# Official Feetech m6 copy with actuator casing fixed to "HD1910" (see 方案阶段 B).
FTSERVO_M6_JSON = (
    ROOT / "tools" / "bam_params" / "hd1910" / "ftservo_official_m6.json"
).resolve()
FTSERVO_BAM_ROOT = (ROOT / ".upstream" / "ftservo-bam").resolve()
CHAR_JSON = (
    ROOT / ".upstream" / "j_hd1910_calibration_params_hd1910_characterization.json"
).resolve()
LIVE_CONSTANTS = (
    ROOT
    / ".venv-mjlab"
    / "Lib"
    / "site-packages"
    / "mjlab_microduck"
    / "robot"
    / "microduck_constants.py"
).resolve()
BACKUP = LIVE_CONSTANTS.with_suffix(".py.xl330.bak")
REGISTER_DST = (
    ROOT
    / ".venv-mjlab"
    / "Lib"
    / "site-packages"
    / "mjlab_microduck"
    / "hd1910_bam_register.py"
).resolve()
REGISTER_SRC = (ROOT / "tools" / "bam_actuators.py").resolve()

# OpenMicroDuck bench m5 — current runnable baseline (方案 §1 参照链).
HD1910_OPENMICRODUCK_M5 = {
    "id": "hd1910_openmicroduck_m5",
    "json_path": str(M5_JSON).replace("\\", "/"),
    "kp_fw": 32.0,
    "vin_range": (6.5, 8.2),
    "vin_drop_gain_range": (0.0, 0.2),
    "vin_min": 6.0,
    "delay_min_lag": 3,
    "delay_max_lag": 6,
    "provenance": {
        "params": str(M5_JSON.relative_to(ROOT)).replace("\\", "/"),
        "characterization": str(CHAR_JSON.relative_to(ROOT)).replace("\\", "/")
        if CHAR_JSON.exists()
        else None,
        "note": "kt=0.692 R=3.75 @5V bench; vin raised to 2S band; kp_fw=32 (reg 50)",
        "forbidden": "tools not using Luwu 1910_m6.json (actuator mislabeled sts3215)",
    },
}

# Feetech official BAM m6 @ 7.4 V — 方案阶段 B 目标植物（A/B 对照用，勿与陆吾 m6 混）。
HD1910_FTSERVO_OFFICIAL_M6 = {
    "id": "hd1910_ftservo_official_m6",
    "json_path": str(FTSERVO_M6_JSON).replace("\\", "/"),
    "motor_name": "feetech_hd1910_7_4V",
    "model": "m6",
    "kp_fw": 32.0,
    "vin_range": (6.5, 8.2),
    "vin_drop_gain_range": (0.0, 0.2),
    "vin_min": 6.0,
    "delay_min_lag": 3,
    "delay_max_lag": 6,
    "provenance": {
        "upstream": "gitee.com/ftservo/ftservo-bam",
        "params_upstream": "bam/params/feetech_hd1910_7_4V/m6.json",
        "params_local": str(FTSERVO_M6_JSON.relative_to(ROOT)).replace("\\", "/"),
        "note": (
            "kt≈0.564 R≈2.97 @7.4V official ID; local copy sets actuator=HD1910 "
            "(upstream JSON says hd1910, table key is HD1910)"
        ),
        "forbidden": "Luwu 1910_m6.json (actuator mislabeled sts3215)",
    },
}

# Upstream official defaults (byte-identical to microduck_rl-develop).
XL330_OFFICIAL_M6 = {
    "id": "xl330_official_m6",
    "motor_name": "xl330",
    "model": "m6",
    "kp_fw": 200.0,
    "vin_range": (6.5, 8.2),
    "vin_drop_gain_range": (0.0, 0.2),
    "vin_min": 6.0,
    "delay_min_lag": 3,
    "delay_max_lag": 6,
    "provenance": {
        "note": "pollen-robotics/microduck_rl develop bundled BAM M6",
    },
}

TARGET_NAMES = r"^(?!passive_).*"


def kwargs_block(plant: str) -> str:
    """Python source for `_BAM_ACTUATOR_KWARGS = dict(...)`."""
    if plant == "hd1910":
        s = HD1910_OPENMICRODUCK_M5
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    json_path=r"{s["json_path"]}",
    target_names_expr=(r"{TARGET_NAMES}",),
    kp_fw={s["kp_fw"]},  # HD1910 firmware P (reg 50); NOT xl330's 200
    vin_range={s["vin_range"]},
    vin_drop_gain_range={s["vin_drop_gain_range"]},
    vin_min={s["vin_min"]},
    delay_min_lag={s["delay_min_lag"]},
    delay_max_lag={s["delay_max_lag"]},
)'''
    if plant in ("hd1910_ftservo_m6", "ftservo_m6"):
        s = HD1910_FTSERVO_OFFICIAL_M6
        # json_path to local copy (actuator=HD1910). Prefer this over motor_name so
        # A/B does not depend on which bam package params/ tree is active.
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    json_path=r"{s["json_path"]}",
    target_names_expr=(r"{TARGET_NAMES}",),
    kp_fw={s["kp_fw"]},  # HD1910 firmware P (reg 50); Feetech official ID @7.4V
    vin_range={s["vin_range"]},
    vin_drop_gain_range={s["vin_drop_gain_range"]},
    vin_min={s["vin_min"]},
    delay_min_lag={s["delay_min_lag"]},
    delay_max_lag={s["delay_max_lag"]},
)'''
    if plant == "xl330":
        s = XL330_OFFICIAL_M6
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    motor_name="{s["motor_name"]}",
    model="{s["model"]}",
    target_names_expr=(r"{TARGET_NAMES}",),
    kp_fw={s["kp_fw"]},  # microduck's preserved firmware stiffness (microban uses 125)
    vin_range={s["vin_range"]},
    vin_drop_gain_range={s["vin_drop_gain_range"]},
    vin_min={s["vin_min"]},
    delay_min_lag={s["delay_min_lag"]},
    delay_max_lag={s["delay_max_lag"]},
)'''
    raise ValueError(
        f"unknown plant: {plant!r} (want hd1910|hd1910_ftservo_m6|xl330)"
    )


REGISTER_IMPORT = (
    "import mjlab_microduck.hd1910_bam_register  # noqa: F401  "
    "# HD1910 plant: register bam actuator name\n"
)
