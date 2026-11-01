#!/usr/bin/env python3
"""HD-1910 只读巡检 —— 15 只装机舵机 PING + 遥测（不写任何寄存器）。

协议按 kissqy firmware/imu-source/src/ft_protocol.c 的飞特 SCS v1 帧：
  FF FF id len inst params ~sum   （len = 参数数+2，~sum = 取反和）
  PING: inst=1 无参数        READ: inst=2 参数=[起始地址, 长度]

遥测地址（kissqy duck-control/src/hd1910.rs 的寄存器表）：
  56-57 位置（signed-magnitude，bit15 符号，0-4095 单圈）
  62     电压（0.1V/LSB）   63 温度（°C）   69-70 电流（bit15 符号，原始计数）

用法：
  python3 hd1910_readonly.py                # 单次巡检
  python3 hd1910_readonly.py --watch 20     # 循环 20 秒（摇晃法验收用：扳关节看位置变化）
前置：sudo systemctl stop robotd   （robotd 占着 /dev/ttyS2）
"""
import argparse, serial, sys, time

IDS = [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34]

def frame(pid: int, inst: int, params: bytes = b"") -> bytes:
    body = bytes([pid, len(params) + 2, inst, *params])
    return b"\xff\xff" + body + bytes([(~sum(body)) & 0xFF])

def query(ser, pid: int, addr: int, count: int) -> bytes | None:
    ser.reset_input_buffer()
    ser.write(frame(pid, 2, bytes([addr, count])))
    ser.flush()
    deadline = time.time() + 0.05
    buf = b""
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        if len(buf) >= count + 6:
            break
        time.sleep(0.001)
    # 响应：FF FF id len err data... chk（len = count+2）
    for i in range(len(buf) - count - 5):
        if buf[i] == 255 and buf[i+1] == 255 and buf[i+2] == pid:
            pkt = buf[i:i+count+6]
            if len(pkt) == count + 6:
                return pkt[5:5+count]
    return None

def ping(ser, pid: int) -> bool:
    ser.reset_input_buffer()
    ser.write(frame(pid, 1))
    ser.flush()
    deadline = time.time() + 0.05
    buf = b""
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        if len(buf) >= 6:
            break
        time.sleep(0.001)
    return any(buf[i:i+3] == b"\xff\xff" + bytes([pid]) for i in range(max(1, len(buf) - 2)))

def signed_mag(lo: int, hi: int) -> int:
    v = lo | (hi << 8)
    return -(v & 0x7FFF) if v & 0x8000 else v

def sweep(ser) -> None:
    print(f"{'ID':>3} {'PING':>4} {'位置raw':>8} {'角度°':>7} {'电压V':>6} {'温度°C':>6} {'电流raw':>7}")
    alive = 0
    for pid in IDS:
        p = query(ser, pid, 56, 2)
        v = query(ser, pid, 62, 1)
        t = query(ser, pid, 63, 1)
        c = query(ser, pid, 69, 2)
        ok = ping(ser, pid) or p is not None
        alive += ok
        v = v if v is not None else b"\x00"
        t = t if t is not None else b"\x00"
        c = c if c is not None else b"\x00\x00"
        pos = signed_mag(*p) if p else None
        deg = f"{pos/4096*360:7.1f}" if pos is not None else "      -"
        print(f"{pid:>3} {'✓' if ok else '✗':>4} {str(pos) if pos is not None else '-':>8} {deg} "
              f"{v[0]/10:6.1f} {t[0]:6d} {signed_mag(*c):>7d}" if ok else f"{pid:>3}   ✗")
    print(f"-- {alive}/15 应答 --")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyS2")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--ids", default=",".join(map(str, IDS)),
                    help="逗号分隔的舵机 ID（台架单只传 --ids 1）")
    ap.add_argument("--watch", type=int, default=0, help="循环秒数（摇晃法）")
    a = ap.parse_args()
    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    globals()["IDS"] = ids
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1, timeout=0.05)
    if a.watch:
        end = time.time() + a.watch
        while time.time() < end:
            sweep(ser); print(); time.sleep(0.6)
    else:
        sweep(ser)
    ser.close()

if __name__ == "__main__":
    sys.exit(main())
