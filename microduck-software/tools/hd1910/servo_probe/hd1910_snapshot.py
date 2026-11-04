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
    # reg13 有矛盾：STS 手册写「初始 70」，但我们 2026-11-02 台架实测 80（audit_robotd_toml.py:137）。
    #   可能是固件版本差异。读出来对照，如果换了颗新的读到 70 ⇒ 是出厂值，不是改过的。
    (13, 1, "temp_limit_C", "过温保护阈值（STS 手册 70 / 本机实测 80）"),
    (14, 1, "volt_max_0p1V", "过压阈值（100 = 10.0 V）—— 是否生效看 reg19 的 bit0"),
    (15, 1, "volt_min_0p1V", "欠压阈值（40 = 4.0 V）—— 是否生效看 reg19 的 bit0"),
    (16, 2, "max_torque", "最大力矩（EEPROM，1000 = 100%）"),
    (18, 1, "phase", "相位/特殊功能字节（不解释、不改）"),
    # reg19 才决定「保护开不开」，reg13/14/15/28 只是阈值。
    # 位映射（飞特官方教程原文）：
    #   32=过载 16=空 8=过流 4=过热 2=磁编码 1=电压
    # 出厂 4 = 仅过热 ⇒ 过压/过流/过载/磁编全关。看到阈值别当成开关（本项目已在这里写错过一次）。
    # 2026-11-04 台架改成 13（=1+4+8），并有功能性 A/B 证明 bit0 真的卸力（见 set_protection.py）。
    #   ⚠️ 绝不能开 bit5 过载：判据是"指令到了但位置没到"，而 kp8（软、D=0）带载稳态误差
    #   本来就是常态 ⇒ 走两步就触发"卸力 2 s 到 20%" ⇒ 必摔。
    (19, 1, "unload_cond", "卸力条件：32过载 16空 8过流 4过热 2磁编 1电压（部署值 13）"),
    (20, 1, "led_alarm", "LED 报警条件（同 reg19 位映射；只影响灯）"),
    (21, 1, "eeprom_P", "EEPROM P 上电默认增益"),
    (22, 1, "eeprom_D", "EEPROM D"),
    (23, 1, "eeprom_I", "EEPROM I"),
    # reg28 **是 2 字节**（低字节在 28、高字节在 29）。只读 1 字节会拿到 0xF4=244，
    # 从而把 3.25 A 误算成 1.59 A —— 本项目 2026-11-04 就是这样错了一次。
    # 换算：×6.5 mA ⇒ 500 = 3.25 A（≈ 1.6× 堵转 2.0 A ⇒ 规范工况内永不触发）。
    (28, 2, "prot_current", "过流/过载阈值 2 字节（×6.5 mA；出厂 500 = 3.25 A）"),
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
    # ── STS 手册有、上面没覆盖的寄存器（2026-11-04 补，纯读）──
    # reg31 = 位置偏移（STS 手册：2B/0~8191/带符号）。零位校正的第二条通路：
    #   代码走 [bus] joint_offsets（软件偏移），从没写过 reg31。
    #   但读一下出厂值，确认它是不是 0 —— 如果非 0，说明出厂就带了偏置，
    #   joint_offsets 的实测值需要叠加这个偏置。
    (31, 2, "pos_offset", "位置偏移（STS 手册：2B/0~8191/带符号）—— 代码未使用，读出厂值"),
    # reg34/35/36 = 安全三件套（STS 手册）。全树代码从不读写，但值得知道出厂值：
    #   reg34 保持扭矩：如果被改低，静止时可能下滑
    #   reg35 保护时间：过载后多久卸力
    #   reg36 过载扭矩：过载判定阈值
    (34, 1, "hold_torque", "保持扭矩（STS 手册）—— 安全相关，代码从不读写"),
    (35, 1, "prot_time", "保护时间（STS 手册）—— 安全相关，代码从不读写"),
    (36, 1, "overload_torque", "过载扭矩（STS 手册）—— 安全相关，代码从不读写"),
    # reg40 = 扭矩开关。代码只写 0/1（卸力/上力），STS 手册说写 128 = 校准到 2048。
    #   但「HLS 固件不支持 reg40=128」（feetech.rs:57 注释），所以这条通路对 HD-1910 不可用。
    #   读一下当前值，确认是 0 还是 1。
    (40, 1, "torque_switch", "扭矩开关（0=关/1=开；写128=校准但 HLS 固件不支持）"),
    # reg60 = 当前负载（STS 手册）。诊断用。
    (60, 2, "load_raw", "当前负载（STS 手册）—— 诊断用"),
    # reg64 = 异步写标志（STS 手册）。EEPROM 写入时序诊断用。
    (64, 1, "async_write", "异步写标志（STS 手册）—— EEPROM 写入时序诊断"),
    # reg66 = 移动标志（STS 手册）。诊断用：检测卡死。
    (66, 1, "moving", "移动标志（STS 手册）—— 诊断用：检测卡死"),
    # reg67 = 目标位置（STS 手册）。诊断用：验证命令是否被接收。
    (67, 2, "target_pos", "目标位置（STS 手册）—— 诊断用：验证命令是否被接收"),
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
