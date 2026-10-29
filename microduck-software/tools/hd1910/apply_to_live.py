#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Reversibly switch the live mjlab plant (XL330 / HD1910 m5 / Feetech m6).

Edits only ``site-packages/mjlab_microduck/robot/microduck_constants.py``.
Keeps a ``.xl330.bak`` of the first XL330 copy so ``--plant xl330`` can restore.

Usage:
  .venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910
  .venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_ftservo_m6
  .venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330
  .venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check

Do **not** switch plant while a train using the previous plant is still running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "hd1910"))
from plant_spec import (  # noqa: E402
    BACKUP,
    FTSERVO_M6_JSON,
    HD1910_FTSERVO_OFFICIAL_M6,
    HD1910_OFFICIAL_M6_KP5,
    HD1910_OPENMICRODUCK_M5,
    LIVE_CONSTANTS,
    M5_JSON,
    OFFICIAL_M6_STSLAW_JSON,
    REGISTER_DST,
    REGISTER_IMPORT,
    REGISTER_SRC,
    XL330_OFFICIAL_M6,
    kwargs_block,
)

PLANT_ALIASES = {
    "hd1910": "hd1910",
    "hd1910_ftservo_m6": "hd1910_ftservo_m6",
    "ftservo_m6": "hd1910_ftservo_m6",
    # P3 target — aligned with kissqy's train+deploy contract (kp_fw=5 + official law).
    "hd1910_kp5": "hd1910_kp5",
    "hd1910_official_m6_kp5": "hd1910_kp5",
    "p3": "hd1910_kp5",
    "xl330": "xl330",
}

REGISTER_LINE_RE = re.compile(
    r"^import mjlab_microduck\.hd1910_bam_register.*\n", re.MULTILINE
)


def _find_kwargs_span(text: str) -> tuple[int, int]:
    """Return [start, end) of `_BAM_ACTUATOR_KWARGS = dict(...)` including trailing newline."""
    anchor = "_BAM_ACTUATOR_KWARGS"
    i = text.find(anchor)
    if i < 0:
        raise SystemExit("could not find _BAM_ACTUATOR_KWARGS in live file")
    j = text.find("dict", i)
    if j < 0:
        raise SystemExit("could not find dict( after _BAM_ACTUATOR_KWARGS")
    k = text.find("(", j)
    depth = 0
    for n in range(k, len(text)):
        ch = text[n]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = n + 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return i, end
    raise SystemExit("unbalanced dict( in _BAM_ACTUATOR_KWARGS")


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _ensure_backup() -> None:
    if BACKUP.exists():
        return
    if not LIVE_CONSTANTS.exists():
        raise SystemExit(f"missing live constants: {LIVE_CONSTANTS}")
    shutil.copy2(LIVE_CONSTANTS, BACKUP)
    print(f"backup  {BACKUP}  sha16={_sha16(BACKUP)}")


def _install_register() -> None:
    if not REGISTER_SRC.exists():
        raise SystemExit(f"missing register source: {REGISTER_SRC}")
    REGISTER_DST.parent.mkdir(parents=True, exist_ok=True)
    # Thin wrapper so site-packages does not need tools/ on sys.path.
    REGISTER_DST.write_text(
        "# Auto-installed by tools/hd1910/apply_to_live.py — do not edit.\n"
        "# Registers Feetech HD1910 with bam.actuators before load_model(json_path).\n"
        f"import importlib.util\n"
        f"from pathlib import Path\n"
        f"_src = Path(r\"{REGISTER_SRC}\")\n"
        f"_spec = importlib.util.spec_from_file_location(\"bam_actuators_hd1910\", _src)\n"
        f"_mod = importlib.util.module_from_spec(_spec)\n"
        f"assert _spec.loader is not None\n"
        f"_spec.loader.exec_module(_mod)\n",
        encoding="utf-8",
    )
    print(f"register {REGISTER_DST}")


def _remove_register() -> None:
    if REGISTER_DST.exists():
        REGISTER_DST.unlink()
        print(f"removed  {REGISTER_DST}")


def _replace_kwargs(text: str, plant: str) -> str:
    block = kwargs_block(plant) + "\n"
    start, end = _find_kwargs_span(text)
    return text[:start] + block + text[end:]


def _set_register_import(text: str, want: bool) -> str:
    text = REGISTER_LINE_RE.sub("", text)
    if not want:
        return text
    # Insert after the last import / from block near the top of actuator section.
    # Prefer right before _BAM_ACTUATOR_KWARGS.
    if "_BAM_ACTUATOR_KWARGS" not in text:
        raise SystemExit("no _BAM_ACTUATOR_KWARGS anchor for register import")
    return text.replace(
        "_BAM_ACTUATOR_KWARGS",
        REGISTER_IMPORT + "_BAM_ACTUATOR_KWARGS",
        1,
    )


def apply(plant: str) -> dict:
    plant = PLANT_ALIASES.get(plant, plant)
    if plant == "hd1910" and not M5_JSON.exists():
        raise SystemExit(f"missing HD1910 params: {M5_JSON}")
    if plant == "hd1910_ftservo_m6" and not FTSERVO_M6_JSON.exists():
        raise SystemExit(f"missing Feetech official m6: {FTSERVO_M6_JSON}")
    if plant == "hd1910_kp5" and not OFFICIAL_M6_STSLAW_JSON.exists():
        raise SystemExit(f"missing derived params: {OFFICIAL_M6_STSLAW_JSON}")
    _ensure_backup()
    text = LIVE_CONSTANTS.read_text(encoding="utf-8")

    if plant == "hd1910":
        _install_register()
        text = _set_register_import(text, True)
        text = _replace_kwargs(text, "hd1910")
        plant_id = HD1910_OPENMICRODUCK_M5["id"]
    elif plant == "hd1910_ftservo_m6":
        _install_register()
        text = _set_register_import(text, True)
        text = _replace_kwargs(text, "hd1910_ftservo_m6")
        plant_id = HD1910_FTSERVO_OFFICIAL_M6["id"]
    elif plant == "hd1910_kp5":
        _install_register()
        text = _set_register_import(text, True)
        text = _replace_kwargs(text, "hd1910_kp5")
        plant_id = HD1910_OFFICIAL_M6_KP5["id"]
    elif plant == "xl330":
        _remove_register()
        # Prefer pristine backup if present (full file restore is safer).
        if BACKUP.exists():
            shutil.copy2(BACKUP, LIVE_CONSTANTS)
            text = LIVE_CONSTANTS.read_text(encoding="utf-8")
            # Still strip any stale register import if backup was taken mid-edit.
            text = _set_register_import(text, False)
            if "json_path" in text and "hd1910" in text.lower():
                text = _replace_kwargs(text, "xl330")
            LIVE_CONSTANTS.write_text(text, encoding="utf-8")
            plant_id = XL330_OFFICIAL_M6["id"]
            return _readback(plant_id)
        text = _set_register_import(text, False)
        text = _replace_kwargs(text, "xl330")
        plant_id = XL330_OFFICIAL_M6["id"]
    else:
        raise SystemExit(f"unknown plant {plant!r}")

    LIVE_CONSTANTS.write_text(text, encoding="utf-8")
    return _readback(plant_id)


def _readback(expected_id: str | None = None) -> dict:
    text = LIVE_CONSTANTS.read_text(encoding="utf-8")
    try:
        start, end = _find_kwargs_span(text)
        block = text[start:end]
    except SystemExit:
        block = ""
    has_reg = bool(REGISTER_LINE_RE.search(text)) and REGISTER_DST.exists()
    is_m5 = "json_path" in block and "m5.json" in block.replace("\\", "/")
    is_ftservo_m6 = (
        "json_path" in block and "ftservo_official_m6.json" in block.replace("\\", "/")
    )
    is_official_m6_stslaw = (
        "json_path" in block and "official_m6_stslaw.json" in block.replace("\\", "/")
    )
    is_hd = (
        is_official_m6_stslaw
        or is_ftservo_m6
        or "json_path" in block
        and "hd1910" in block.lower()
    )
    is_xl = 'motor_name="xl330"' in block or "motor_name='xl330'" in block
    if is_official_m6_stslaw:
        detected = "hd1910_kp5"
    elif is_ftservo_m6:
        detected = "hd1910_ftservo_m6"
    elif is_m5 or is_hd:
        detected = "hd1910"
    elif is_xl:
        detected = "xl330"
    else:
        detected = "unknown"
    kp = None
    km = re.search(r"kp_fw\s*=\s*([0-9.]+)", block)
    if km:
        kp = float(km.group(1))
    out = {
        "live": str(LIVE_CONSTANTS),
        "sha16": _sha16(LIVE_CONSTANTS),
        "backup_exists": BACKUP.exists(),
        "register_installed": has_reg,
        "detected": detected,
        "kp_fw": kp,
        "kwargs_block": block.strip(),
        "expected_id": expected_id,
        "m5_json_exists": M5_JSON.exists(),
        "m5_sha16": _sha16(M5_JSON) if M5_JSON.exists() else None,
        "ftservo_m6_exists": FTSERVO_M6_JSON.exists(),
        "ftservo_m6_sha16": _sha16(FTSERVO_M6_JSON) if FTSERVO_M6_JSON.exists() else None,
        "official_m6_stslaw_exists": OFFICIAL_M6_STSLAW_JSON.exists(),
        "official_m6_stslaw_sha16": (
            _sha16(OFFICIAL_M6_STSLAW_JSON) if OFFICIAL_M6_STSLAW_JSON.exists() else None
        ),
    }
    if expected_id == HD1910_OPENMICRODUCK_M5["id"]:
        out["gate_ok"] = (
            detected == "hd1910" and kp == 32.0 and has_reg and M5_JSON.exists()
        )
    elif expected_id == HD1910_FTSERVO_OFFICIAL_M6["id"]:
        out["gate_ok"] = (
            detected == "hd1910_ftservo_m6"
            and kp == 32.0
            and has_reg
            and FTSERVO_M6_JSON.exists()
        )
    elif expected_id == HD1910_OFFICIAL_M6_KP5["id"]:
        out["gate_ok"] = (
            detected == "hd1910_kp5"
            and kp == 5.0
            # Note: this plant does NOT need our registered actuator name — the JSON
            # asks for "sts3215", which bam ships. The register stays installed only
            # so switching back to m5 / ftservo_m6 keeps working.
            and has_reg
            and OFFICIAL_M6_STSLAW_JSON.exists()
        )
    elif expected_id == XL330_OFFICIAL_M6["id"]:
        out["gate_ok"] = is_xl and kp == 200.0 and not has_reg
    else:
        out["gate_ok"] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--plant",
        choices=(
            "hd1910",
            "hd1910_ftservo_m6",
            "ftservo_m6",
            "hd1910_kp5",
            "hd1910_official_m6_kp5",
            "p3",
            "xl330",
        ),
        default=None,
    )
    ap.add_argument("--check", action="store_true", help="read back only")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.check and a.plant:
        raise SystemExit("use either --check or --plant, not both")
    if not a.check and not a.plant:
        raise SystemExit(
            "need --plant hd1910|hd1910_ftservo_m6|hd1910_kp5|xl330 or --check"
        )

    if a.plant:
        info = apply(a.plant)
    else:
        info = _readback()

    if a.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"detected   {info['detected']}  kp_fw={info['kp_fw']}")
        print(f"register   {info['register_installed']}")
        print(f"live sha16 {info['sha16']}")
        if info.get("gate_ok") is not None:
            print(f"gate_ok    {info['gate_ok']}")
        print("--- kwargs ---")
        print(info["kwargs_block"])

    if a.plant and info.get("gate_ok") is False:
        return 1
    if a.check and info["detected"] == "unknown":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
