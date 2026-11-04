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
    (5, 1, "id", "总线 ID"),
    (6, 1, "baud_idx", "波特率索引（0 = 1 Mbps）"),
    # reg7 = 回传延迟（地址对，官方内存表：1 B / 0x07 / 2 µs per LSB / 出厂 250）。
    # 但本机固件 3.46 上**该项不生效**，别去写它：
    #   ① 官方内存表自注「STS 此地址无功能」（ref_hl2915_bench.py:44 抄录）
    #   ② 第三方整机记录同样写「STS 系列上这项不起作用」（fanhao375 调试记录）
    #   ③ 本机实测单读 RTT 中位 289 µs —— 若 253×2=506 µs 生效，RTT 不可能低于它
    # 三个来源 + 一次测量同向，结论是「不是 8 ms 的坑，也不必写 0」。
    (7, 1, "return_delay", "回传延迟 2 µs/LSB（本固件不生效，见上）"),
    (8, 1, "response_level", "应答等级（1 = 只回 READ/PING）"),
    (13, 1, "temp_limit_C", "过温保护阈值（出厂 80）"),
    (14, 1, "volt_max_0p1V", "过压阈值（100 = 10.0 V）—— 是否生效看 reg19 的 bit0"),
    (15, 1, "volt_min_0p1V", "欠压阈值（40 = 4.0 V）—— 是否生效看 reg19 的 bit0"),
    (16, 2, "max_torque", "最大力矩（EEPROM，1000 = 100%）"),
    # reg19 才决定「保护开不开」，reg13/14/15/28 只是阈值。
    # 出厂 4 = 仅 bit2 温度 ⇒ 过压/过流/过载全关。看到阈值别当成开关（本项目已在这里写错过一次）。
    (19, 1, "unload_cond", "卸力条件位段：1电压 2磁编 4温度 8电流 32过载（出厂 4 = 只有过热开）"),
    (21, 1, "eeprom_P", "EEPROM P 上电默认增益"),
    (22, 1, "eeprom_D", "EEPROM D"),
    (23, 1, "eeprom_I", "EEPROM I"),
    (28, 1, "prot_current", "过流保护阈值（×6.5 mA；出厂 244 ≈ 1.59 A）"),
    (33, 1, "mode", "运行模式（出厂 4 = 纯位置 PD）"),
    (41, 1, "accel", "加速度（适配代码从不写入）"),
    (46, 2, "goal_speed", "目标速度（2 字节；0 = 固件解释为『零速趋向目标』= 不动）"),
    (48, 2, "torque_limit", "扭矩限制 16 位小端"),
    (50, 1, "ram_P", "运行时 P 增益（reg 50）"),
    (51, 1, "ram_D", "运行时 D 增益（reg 51）"),
    (55, 1, "lock", "EEPROM 锁（0 可写 / 1 锁定）"),
    (56, 2, "position", "当前位置（bit15 符号 + 0-4095）"),
    (58, 2, "speed", "当前速度（50 编码步/秒 每计数）"),
    (62, 1, "voltage_0p1V", "输入电压 0.1 V/LSB"),
    (63, 1, "temp_C", "温度 °C"),
    (65, 1, "status", "状态位段：BIT0 电压 BIT1 磁编 BIT2 温度 BIT3 电流 BIT5 负载（0 = 全清）"),
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
