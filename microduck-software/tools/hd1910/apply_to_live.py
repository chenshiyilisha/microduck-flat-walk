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
    HD1910_OFFICIAL_M6_KP8,
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
    # P8 — identical to P3 except reg 50 (bench sweet spot, 2026-11-02).
    "hd1910_kp8": "hd1910_kp8",
    "hd1910_official_m6_kp8": "hd1910_kp8",
    "p8": "hd1910_kp8",
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
    # Use a runtime-relative path (parents[4] from site-packages lands on the
    # repo root) instead of baking the absolute install-time path.
    REGISTER_DST.write_text(
        "# Auto-installed by tools/hd1910/apply_to_live.py — do not edit.\n"
        "# Registers Feetech HD1910 with bam.actuators before load_model(json_path).\n"
        "import importlib.util\n"
        "from pathlib import Path\n"
        "_src = Path(__file__).resolve().parents[4] / 'tools' / 'bam_actuators.py'\n"
        "_spec = importlib.util.spec_from_file_location('bam_actuators_hd1910', _src)\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "assert _spec.loader is not None\n"
        "_spec.loader.exec_module(_mod)\n",
        encoding="utf-8",
    )
    print(f"register {REGISTER_DST}")


def _remove_register() -> None:
    if not REGISTER_DST.exists():
        return
    # On this machine the Windows recycle-bin hook intercepts unlink (SHFileOperationW
    # 0x78), so fall back to overwriting with a no-op stub rather than leaving a
    # stale register that would still try to exec the source module.
    try:
        REGISTER_DST.unlink()
        print(f"removed  {REGISTER_DST}")
    except OSError as e:
        REGISTER_DST.write_text(
            "# Neutralised by apply_to_live.py — unlink was blocked on this host.\n"
            "# The register is a no-op so the import does not fail.\n",
            encoding="utf-8",
        )
        print(f"neutralised  {REGISTER_DST}  (unlink blocked: {type(e).__name__})")
    # Also clear the compiled bytecode so Python does not load the old module
    # from __pycache__ after the source is gone.
    pycache = REGISTER_DST.parent / "__pycache__"
    if pycache.is_dir():
        for pc in pycache.glob(REGISTER_DST.stem + ".*.pyc"):
            try:
                pc.unlink()
            except OSError:
                pass


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


def apply(plant: str, delay_lag: tuple[int, int] | None = None) -> dict:
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
    elif plant == "hd1910_kp8":
        _install_register()
        text = _set_register_import(text, True)
        text = _replace_kwargs(text, "hd1910_kp8")
        plant_id = HD1910_OFFICIAL_M6_KP8["id"]
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

    if delay_lag is not None:
        lo, hi = delay_lag
        # Overlay on whatever preset was just written. Physics step is 5 ms
        # (sim.timestep 0.005, decimation 4), so lag 3..6 = 15..30 ms. The bench
        # found the real servo carries ~26..45 ms MORE lag than BAM models, so
        # the shipped upper bound sits exactly on the measured lower edge.
        if lo < 0 or hi < lo:
            raise SystemExit(f"bad --delay-lag {lo},{hi}: need 0 <= MIN <= MAX")
        # Count INSIDE the kwargs span only: this file also carries a
        # pd_actuators XmlActuatorCfg with its own delay_min_lag/delay_max_lag,
        # and a whole-file count would falsely refuse a legitimate rewrite.
        bstart, bend = _find_kwargs_span(text)
        btext = text[bstart:bend]
        n_sub_min = len(re.findall(r"delay_min_lag\s*=\s*-?\d+", btext))
        n_sub_max = len(re.findall(r"delay_max_lag\s*=\s*-?\d+", btext))
        if n_sub_min != 1 or n_sub_max != 1:
            raise SystemExit(
                f"expected exactly one delay_min_lag and one delay_max_lag in the "
                f"kwargs block, found {n_sub_min}/{n_sub_max} -- refusing to "
                "rewrite blindly"
            )
        btext = re.sub(r"delay_min_lag\s*=\s*-?\d+", f"delay_min_lag={lo}", btext)
        btext = re.sub(r"delay_max_lag\s*=\s*-?\d+", f"delay_max_lag={hi}", btext)
        text = text[:bstart] + btext + text[bend:]

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
    # kp first: official_m6_stslaw.json is shared by the P5 and P8 plants, so the
    # JSON name alone cannot tell them apart -- only reg 50 can.
    kp = None
    km = re.search(r"kp_fw\s*=\s*([0-9.]+)", block)
    if km:
        kp = float(km.group(1))
    # Command-delay band, in PHYSICS steps (5 ms each: sim.timestep 0.005,
    # decimation 4). Reported for every plant because a --delay-lag overlay
    # survives only until the next --plant rewrite; a reader that cannot see it
    # would compare two runs with different latency and call it the same plant.
    dmin = re.search(r"delay_min_lag\s*=\s*(\d+)", block)
    dmax = re.search(r"delay_max_lag\s*=\s*(\d+)", block)
    delay_min_lag = int(dmin.group(1)) if dmin else None
    delay_max_lag = int(dmax.group(1)) if dmax else None
    if is_official_m6_stslaw:
        detected = {
            5.0: "hd1910_kp5",
            8.0: "hd1910_kp8",
        }.get(kp, f"hd1910_official_m6_kp{kp}")
    elif is_ftservo_m6:
        detected = "hd1910_ftservo_m6"
    elif is_m5 or is_hd:
        detected = "hd1910"
    elif is_xl:
        detected = "xl330"
    else:
        detected = "unknown"
    out = {
        "live": str(LIVE_CONSTANTS),
        "sha16": _sha16(LIVE_CONSTANTS),
        "backup_exists": BACKUP.exists(),
        "register_installed": has_reg,
        "detected": detected,
        "kp_fw": kp,
        "delay_min_lag": delay_min_lag,
        "delay_max_lag": delay_max_lag,
        "delay_ms": (
            [delay_min_lag * 5, delay_max_lag * 5]
            if delay_min_lag is not None and delay_max_lag is not None
            else None
        ),
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
    elif expected_id == HD1910_OFFICIAL_M6_KP8["id"]:
        out["gate_ok"] = (
            detected == "hd1910_kp8"
            and kp == 8.0
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
            "hd1910_kp8",
            "hd1910_official_m6_kp8",
            "p8",
            "xl330",
        ),
        default=None,
    )
    ap.add_argument("--check", action="store_true", help="read back only")
    ap.add_argument(
        "--delay-lag",
        default=None,
        help="MIN,MAX command delay in PHYSICS steps (5 ms each) written on top of "
        "the chosen plant's kwargs. Benchmark 2026-11-03: the real servo carries "
        "~26-45 ms more lag than BAM models, so the shipped 3,6 (15-30 ms) barely "
        "reaches the measured lower edge. Overlay is wiped by the next --plant.",
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.check and a.plant:
        raise SystemExit("use either --check or --plant, not both")
    if not a.check and not a.plant:
        raise SystemExit(
            "need --plant hd1910|hd1910_ftservo_m6|hd1910_kp5|hd1910_kp8|xl330 or --check"
        )

    delay_lag = None
    if a.delay_lag:
        try:
            lo_s, hi_s = a.delay_lag.split(",")
            delay_lag = (int(lo_s), int(hi_s))
        except ValueError:
            raise SystemExit(
                f"--delay-lag must be MIN,MAX in physics steps (got {a.delay_lag!r})"
            ) from None
        if a.check:
            raise SystemExit("--delay-lag writes the live file; use it with --plant")

    if a.plant:
        info = apply(a.plant, delay_lag)
    else:
        info = _readback()

    if a.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"detected   {info['detected']}  kp_fw={info['kp_fw']}")
        print(
            f"delay lag  {info['delay_min_lag']}..{info['delay_max_lag']} steps "
            f"({info['delay_ms'][0]}-{info['delay_ms'][1]} ms)"
        )
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
