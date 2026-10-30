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
# Derived in this repo from ftservo_official_m6.json: identical Feetech ID numbers, but
# "actuator" points at the *official* control law so the servo regains its internal
# speed cap. See 方案 §3 / probe_plant_law.py for what each key resolves to.
OFFICIAL_M6_STSLAW_JSON = (
    ROOT / "tools" / "bam_params" / "hd1910" / "official_m6_stslaw.json"
).resolve()
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
        # Superseded by HD1910_OFFICIAL_M6_KP5 for training; kept for reproducing
        # the archived HD1910 numbers, which were all measured under kp_fw=32.
        "forbidden": None,
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
        # 2026-10-29 纠正：BAM bam/actuators.py 的注册表里 Feetech 唯一合法键就是
        # "sts3215"，"hd1910"/"HD1910" 是本仓自己注册的。旧的「陆吾 m6 因 actuator
        # 误标 sts3215 而禁用」属误判。陆吾那份的真正问题是写了
        # max_velocity=100 rad/s，把官方 5.22 rad/s 的内部限速覆盖了（不是名字问题）。
        "forbidden": None,
    },
}

# ★ P3 target plant (2026-10-29 裁决): align with kissqy's proven train+deploy contract.
HD1910_OFFICIAL_M6_KP5 = {
    "id": "hd1910_official_m6_kp5",
    "json_path": str(OFFICIAL_M6_STSLAW_JSON).replace("\\", "/"),
    "model": "m6",
    "kp_fw": 5.0,
    "vin_range": (6.5, 8.2),
    "vin_drop_gain_range": (0.0, 0.2),
    "vin_min": 6.0,
    "delay_min_lag": 3,
    "delay_max_lag": 6,
    "provenance": {
        "why": (
            "32 is Feetech's *factory* ROM P (bam/feetech/actuator.py default, and the "
            "read-only bench readout P/D/I=32/40/0 on all 15 units); the value actually "
            "in force during train AND deploy is 5. train at 32 / deploy at 5 would be "
            "another plant mismatch (cf. the XL330<->HD1910 incident)."
        ),
        "kp_fw_source": (
            "kissqy config-diff: 12/12 tasks use kp_fw=5.0 for HD1910; V164/V167 deploy "
            "contract writes P=5/D=0; community bench settled on P3..P5/D0."
        ),
        "params_source": str(OFFICIAL_M6_STSLAW_JSON.relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "law_source": (
            "actuator=\"sts3215\" -> bam official STS3215Actuator: internal target speed "
            "cap 3400*2pi/4096=5.2155 rad/s, max_pwm=0.97, error_gain=0.166, vin=7.4."
        ),
        "note": (
            "derived from ftservo_official_m6.json by changing actuator only; the two keys "
            "max_velocity / error_gain_ratio are deliberately absent so the official "
            "defaults survive (load_parameters_from_dict overwrites any matching name)."
        ),
        "verify": "tools/hd1910/probe_plant_law.py --json <this> --kp-fw 5",
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
        _fname = M5_JSON.name
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    json_path=str(Path(__file__).resolve().parents[5] / "tools" / "bam_params" / "hd1910" / "{_fname}"),
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
        _fname = FTSERVO_M6_JSON.name
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    json_path=str(Path(__file__).resolve().parents[5] / "tools" / "bam_params" / "hd1910" / "{_fname}"),
    target_names_expr=(r"{TARGET_NAMES}",),
    kp_fw={s["kp_fw"]},  # HD1910 firmware P (reg 50); Feetech official ID @7.4V
    vin_range={s["vin_range"]},
    vin_drop_gain_range={s["vin_drop_gain_range"]},
    vin_min={s["vin_min"]},
    delay_min_lag={s["delay_min_lag"]},
    delay_max_lag={s["delay_max_lag"]},
)'''
    if plant in ("hd1910_kp5", "hd1910_official_m6_kp5", "p3"):
        s = HD1910_OFFICIAL_M6_KP5
        _fname = OFFICIAL_M6_STSLAW_JSON.name
        return f'''_BAM_ACTUATOR_KWARGS = dict(
    json_path=str(Path(__file__).resolve().parents[5] / "tools" / "bam_params" / "hd1910" / "{_fname}"),
    target_names_expr=(r"{TARGET_NAMES}",),
    kp_fw={s["kp_fw"]},  # firmware P in force at runtime (reg 50); 32 is the factory ROM default
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
        "unknown plant: %r (want hd1910|hd1910_ftservo_m6|hd1910_kp5|xl330)" % (plant,)
    )


REGISTER_IMPORT = (
    "import mjlab_microduck.hd1910_bam_register  # noqa: F401  "
    "# HD1910 plant: register bam actuator name\n"
)
