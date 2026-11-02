#!/usr/bin/env python3
"""扫描总线上的舵机 ID，打印应答者的遥测。

用途：装新舵机时确认它当前 ID 与供电状态（USB 5V 档即可 PING/读遥测）。
协议按 kissqy firmware/imu-source/src/ft_protocol.c 的飞特 SCS v1 帧。

用法：
  python3 probe_ids.py --port COM3
  python3 probe_ids.py --port COM3 --ids 1-40
"""
import argparse
import sys

import serial

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from hd1910_readonly import ping, query, signed_mag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--ids", default="1-40", help="扫描区间，如 1-40")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.ids.split("-"))

    ser = serial.Serial(a.port, a.baud, timeout=0.05)
    found = []
    for pid in range(lo, hi + 1):
        if not ping(ser, pid):
            continue
        p = query(ser, pid, 56, 2)
        v = query(ser, pid, 62, 1)
        t = query(ser, pid, 63, 1)
        c = query(ser, pid, 69, 2)
        pos = signed_mag(*p) if p else None
        deg = pos / 4096 * 360 if pos is not None else float("nan")
        volt = v[0] / 10.0 if v else None
        temp = t[0] if t else None
        cur = signed_mag(*c) if c else None
        found.append(pid)
        print(f"ID {pid:>3}: PING ok | pos={pos} ({deg:.1f} deg) | "
              f"V={volt} | T={temp} C | cur_raw={cur}")
    ser.close()
    print("found IDs:", found)


if __name__ == "__main__":
    main()
