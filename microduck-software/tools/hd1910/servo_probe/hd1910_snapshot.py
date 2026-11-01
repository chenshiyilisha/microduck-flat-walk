#!/usr/bin/env python3
"""HD-1910 只读寄存器快照 —— 把一颗舵机的关键寄存器读出来存档。

只读，不写任何寄存器。用途：
  - 装机前给每颗留一份出厂快照（改坏了对得回来）
  - 核验 P3 裁决关心的量：EEPROM P/D/I（21-23）与运行时 P/D（50-51）是不是两个数
  - 确认运行模式（33）是出厂的 4（纯位置 PD），别被"顺手改回 0"坑了

寄存器表出处（不猜地址）：
  whatled《URT2 + HD-1910-C001 接线、组装与测试指南》§6 —— 来自 kissqy
  duck-control/src/hd1910.rs 与 microduck-replica hd1910_readonly.py。
帧实现直接复用同目录 hd1910_readonly.py（飞特 SCS v1：PING=1 / READ=2 / WRITE=3）。

用法：
  python hd1910_snapshot.py --port COM3 --ids 1
  python hd1910_snapshot.py --port COM3 --ids 1 --json out/snap_id1.json
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import serial

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "hd1910_ro", _HERE / "hd1910_readonly.py"
)
_ro = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_ro)

# (地址, 长度, 名称, 说明)
FIELDS = [
    (3, 2, "model", "型号 ID（HD-1910 应为 7946）"),
    (21, 1, "eeprom_P", "EEPROM P 上电默认增益"),
    (22, 1, "eeprom_D", "EEPROM D"),
    (23, 1, "eeprom_I", "EEPROM I"),
    (33, 1, "mode", "运行模式（出厂 4 = 纯位置 PD）"),
    (41, 1, "accel", "加速度（适配代码从不写入）"),
    (48, 2, "torque_limit", "扭矩限制 16 位小端"),
    (50, 1, "ram_P", "运行时 P 增益（reg 50）"),
    (51, 1, "ram_D", "运行时 D 增益（reg 51）"),
    (56, 2, "position", "当前位置（bit15 符号 + 0-4095）"),
    (58, 2, "speed", "当前速度（50 编码步/秒 每计数）"),
    (62, 1, "voltage_0p1V", "输入电压 0.1 V/LSB"),
    (63, 1, "temp_C", "温度 °C"),
    (69, 2, "current_raw", "电流原始计数（换算 mA 需实物标定）"),
]


def _u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def snapshot(ser, pid: int) -> dict:
    out = {"id": pid}
    for addr, n, name, desc in FIELDS:
        raw = _ro.query(ser, pid, addr, n)
        if raw is None:
            out[name] = None
            continue
        if n == 1:
            out[name] = raw[0]
        else:
            out[name] = _ro.signed_mag(raw[0], raw[1])
        time.sleep(0.002)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyS2")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--ids", default="1", help="逗号分隔")
    ap.add_argument("--json", default="", help="另存 JSON 到该路径")
    a = ap.parse_args()

    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1, timeout=0.05)
    try:
        snaps = []
        for pid in ids:
            if not _ro.ping(ser, pid):
                print(f"ID {pid}: PING ✗ —— 没应答，跳过")
                continue
            s = snapshot(ser, pid)
            snaps.append(s)
            print(f"--- ID {pid} ---")
            for addr, n, name, desc in FIELDS:
                v = s.get(name)
                extra = ""
                if name == "voltage_0p1V" and v is not None:
                    extra = f"  → {v/10:.1f} V"
                if name == "position" and v is not None:
                    extra = f"  → {v/4096*360:.1f}°"
                print(f"  reg{addr:<3} {name:<15} {str(v):>8}{extra}   # {desc}")
        if a.json:
            Path(a.json).parent.mkdir(parents=True, exist_ok=True)
            Path(a.json).write_text(
                json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"\nsaved -> {a.json}")
        return 0 if snaps else 1
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
