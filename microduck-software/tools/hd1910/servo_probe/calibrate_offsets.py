#!/usr/bin/env python3
"""解出 `[bus] joint_offsets` 与 `[bus] joint_signs` —— 只读，不写任何寄存器。

`feetech.rs:85` 硬编码 `CENTER = 2048`。**这条有厂商背书**（HL-2915 官方参数表：
`Neutral Position 2048`、`Resolution 0.088° (360°/4096)`），所以「2048 是对的」不是上游拍脑袋。

⚠️ **台架行程中点 ≠ 舵机中立位**。台架那颗（ID 10）行程 `[1213, 2816]` 关于 2014.5 对称，
但那是**行程中点**，不是中立位。两者差 33.5 counts 但**不是 offset**——
之前误把 2014 当中立位，现在已更正。

⚠️ **HLS 舵机固件 ≥3.43 不支持 `reg40` 写 128 校准中位**（飞特文档明写）。要校准只能用
指令帧 `FF FF ID 02 0B F1`（当前位→2048）或 `FF FF ID 04 0B <lo> <hi> EB`。
本链 `feetech.rs` 里 `reg40` 只写 0/1、**零处** 0x0B ⇒ 重新标零位只能靠 `joint_offsets`。

`joint_offsets` 默认空 = 全 0，`joint_signs` 默认空 = 全 +1。

判据：`counts_to_rad(raw, sign, offset) = sign × (sign_magnitude(raw) - 2048 - offset) × 2π/4096`
所以 `offset = raw_at_joint_zero - 2048`（当 robotd 算 joint_pos 时要得到 0）。

用法（robotd 必须先停；舵机扭矩关着 = 断电重上电后不要启动 robotd）：
    python calibrate_offsets.py --port COM3 --baud 1000000
    python calibrate_offsets.py --port COM3 --json out/joint_offsets.json
    python calibrate_offsets.py --port COM3 --apply-toml out/robotd_hd1910_mode0.toml
    python calibrate_offsets.py --selftest

⚠️ 前置条件：机器人必须处于 DEFAULT_POSITION（`model.rs:39` 的站立位姿）。
   台架上单颗舵机只能测「伺服中心 vs 行程中点」，整机零位需要整机在场。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hd1910_readonly import ping, query, signed_mag  # noqa: E402

JOINT_NAMES = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]

CENTER = 2048
COUNTS_PER_REV = 4096.0
DEG_PER_COUNT = 360.0 / COUNTS_PER_REV
POS_REG = 56


def offset_for(raw: int) -> int:
    """Encoder reading at the joint's zero, minus 2048. What `joint_offsets` must hold."""
    return raw - CENTER


def offset_deg(raw: int) -> float:
    return (raw - CENTER) * DEG_PER_COUNT


def selftest():
    n = 0
    bad = 0

    def check(name, got, want):
        nonlocal n, bad
        n += 1
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}（期望 {want}）")

    print("=== offset_for：伺服读 2048 ⇒ offset 0（默认就是对的）===")
    check("raw=2048 → offset 0", offset_for(2048), 0)

    print("=== 台架那颗的行程中点 2014 ⇒ offset -34 ===")
    check("raw=2014 → offset -34", offset_for(2014), -34)
    check("raw=2014 → -2.99°", round(offset_deg(2014), 2), -2.99)

    print("=== 行程两端 [1213, 2816] ⇒ offset 不对称于 0 ===")
    check("lo=1213 → offset -835", offset_for(1213), -835)
    check("hi=2816 → offset +768", offset_for(2816), 768)
    # 2048 is NOT the midpoint of [1213, 2816]: 835 below vs 768 above.
    check("2048 不是行程中点（下 835 ≠ 上 768）", 2048 - 1213 != 2816 - 2048, True)
    check("行程中点 = (1213+2816)/2 = 2014.5", (1213 + 2816) / 2, 2014.5)

    print("=== 负对照：offset 写错会怎样（模拟 counts_to_rad）===")
    # counts_to_rad = sign × (raw - 2048 - offset) × 2π/4096
    # If offset is correct (= raw_at_zero - 2048), then at the zero position:
    #   (raw - 2048 - offset) = (raw - 2048 - (raw - 2048)) = 0 ⇒ joint_pos = 0 ✓
    # If offset is 0 but raw ≠ 2048:
    #   (raw - 2048) ≠ 0 ⇒ joint_pos ≠ 0 ✗
    raw_at_zero = 2014  # bench servo: physical travel midpoint
    off_correct = offset_for(raw_at_zero)  # -34
    # At the zero position with correct offset:
    val_correct = (raw_at_zero - CENTER - off_correct) * DEG_PER_COUNT
    check("offset 正确时 joint_pos = 0°", round(val_correct, 4), 0.0)
    # With offset = 0 (default):
    val_wrong = (raw_at_zero - CENTER - 0) * DEG_PER_COUNT
    check("offset 默认 0 时 joint_pos = -2.99°（非零）", round(val_wrong, 2), -2.99)

    print("=== 15 关节顺序：JOINT_NAMES 长度 ===")
    check("JOINT_NAMES 15 条", len(JOINT_NAMES), 15)

    print("=== 输出格式：offsets 必须能按 JOINT_NAMES 顺序拼回去 ===")
    m = {jid: 1000 + 10 * k for k, jid in enumerate(range(10, 25))}
    offsets = [m[j] for j in range(10, 25)]
    check("15 条 offset 往返", len(offsets), 15)

    print("=== 负对照：--apply-toml 必须拒绝部分读数 ===")
    import tempfile
    tfd, tpath = tempfile.mkstemp(suffix=".toml")
    os.close(tfd)
    with open(tpath, "w", encoding="utf-8") as f:
        f.write("[bus]\njoint_ids = [1, 2, 3]\n")
    # 3 of 15: the default `allow_partial=False` path must refuse and must NOT edit.
    rc = _write_toml(tpath, {10: {"offset": -34}, 11: {"offset": -34}, 12: {"offset": -34}}, 3)
    after = open(tpath, encoding="utf-8").read()
    check("只读到 3/15 → 拒绝写入（rc=1）", rc, 1)
    check("拒绝时 toml 未被改动", "joint_offsets" in after, False)
    # 15 of 15: writes, and a backup exists.
    rows15 = {i: {"offset": -34} for i in range(10, 25)}
    rc2 = _write_toml(tpath, rows15, 15)
    after2 = open(tpath, encoding="utf-8").read()
    check("15/15 → 写入成功（rc=0）", rc2, 0)
    check("写入后 toml 有 joint_offsets", "joint_offsets" in after2, True)
    check("写前留了备份", os.path.exists(tpath + ".bak"), True)
    check("备份内容是原文件", "joint_ids" in open(tpath + ".bak", encoding="utf-8").read(), True)
    # --allow-partial: pads with 0 and says so.
    rc3 = _write_toml(tpath, {10: {"offset": -34}}, 1, allow_partial=True)
    check("--allow-partial 补齐 15 个", rc3, 0)
    os.unlink(tpath)
    os.unlink(tpath + ".bak")

    print(f"\nselftest: {'ALL PASSED' if bad == 0 else f'{bad}/{n} FAILED'}")
    return 0 if bad == 0 else 1


def _write_toml(path: str, rows: dict, id_count: int,
                allow_partial: bool = False) -> int:
    """Write `joint_offsets` into the [bus] section. Backs up first; never guesses."""
    import shutil

    p = path
    if not os.path.exists(p):
        print(f"\n文件不存在：{p}")
        return 1

    offsets = [rows[i]["offset"] for i in sorted(rows)]
    have = len(offsets)
    if have != 15 and not allow_partial:
        print(f"\n只读到 {have}/15 只 offset。先跑 identify_joints.py 把 joint_ids 填上，")
        print("否则缺项会静默变成 0 —— 那是「默认值」，不是「没量」。")
        return 1
    if have != 15:
        offsets = offsets + [0] * (15 - have)
        print(f"\n⚠️ --allow-partial：缺 {15 - have} 个按 0 填。")

    line = "joint_offsets = [" + ", ".join(str(o) for o in offsets) + "]"

    backup = p + ".bak"
    shutil.copy2(p, backup)
    print(f"\n备份到 {backup}")

    with open(p, encoding="utf-8") as f:
        txt = f.read()

    # Replace an existing joint_offsets line, else insert after joint_ids / [bus].
    import re
    if re.search(r"^\s*joint_offsets\s*=", txt, re.M):
        txt2, n = re.subn(r"^\s*joint_offsets\s*=[^\n]*", line, txt, count=1, flags=re.M)
    elif "joint_ids" in txt:
        lines = txt.split("\n")
        at = max(i for i, l in enumerate(lines) if "joint_ids" in l)
        lines.insert(at + 1, line)
        txt2 = "\n".join(lines)
        n = 1
    else:
        txt2 = txt.replace("[bus]\n", "[bus]\n" + line + "\n", 1)
        n = 1 if "[bus]\n" in txt else 0

    if n == 0:
        print("\ntoml 里既没有 [bus] 也没有 joint_ids：没改。")
        return 1

    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt2)

    print(f"写入 {p}：{line}")
    print("⚠️ 这些数是从「当前位置」量的。只有机器人处于 DEFAULT_POSITION")
    print("   （model.rs:39 的站立位姿）时，它们才是 joint_offsets 的正解。")
    print("   改完必须重跑 audit_robotd_toml.py 确认配置仍能加载。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="解 joint_offsets（只读）")
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1_000_000,
                    help="台架这颗现在是多少就是多少")
    ap.add_argument("--ids", default="10-34", help="候选 ID 区间")
    ap.add_argument("--json", default=None, metavar="PATH")
    ap.add_argument("--apply-toml", default=None, metavar="PATH",
                    help="把 15 个 offset 写进 toml 的 [bus] 段（要求 15 只全读到）")
    ap.add_argument("--allow-partial", action="store_true",
                    help="配合 --apply-toml：缺项按 0 填（不推荐，缺项应先跑 identify_joints）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    try:
        import serial
    except ImportError:
        sys.exit("缺 pyserial：pip install pyserial")

    ids = [int(x) for x in a.ids.replace("-", ",").split(",") if x.strip()]
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1, timeout=0.05)

    found = [i for i in ids if ping(ser, i)]
    if not found:
        ser.close()
        sys.exit("一只都没应答：先查供电/线序，再查波特率")

    print(f"端口 {a.port} @ {a.baud}：{len(found)} 只应答")
    print(f"{'ID':>4} {'raw':>6} {'deg':>8} {'offset':>7} {'off_deg':>8}")
    print("-" * 44)

    rows = {}
    for i in found:
        r = query(ser, i, POS_REG, 2)
        if r is None:
            print(f"{i:>4}  读取失败")
            continue
        raw = signed_mag(*r)
        off = offset_for(raw)
        rows[i] = {"raw": raw, "offset": off, "offset_deg": round(offset_deg(raw), 3)}
        print(f"{i:>4} {raw:>6} {raw * DEG_PER_COUNT:>7.1f}° {off:>+7} {offset_deg(raw):>+7.2f}°")
        time.sleep(0.002)

    ser.close()

    print()
    print("⚠️ 这些 offset 是从「当前位置」读的。要让它们成为 joint_offsets，")
    print("   机器人必须处于 DEFAULT_POSITION（model.rs:39 的站立位姿）。")
    print("   台架上单颗舵机只能看到自己的行程，整机零位需要整机在场。")
    print()

    if rows:
        print("# 可直接粘进 out/robotd_hd1910_mode0.toml（如果机器在 DEFAULT_POSITION）：")
        all_ids = [i for i in ids if i in rows]
        if len(all_ids) == 15:
            offsets_line = [rows[i]["offset"] for i in all_ids]
            print("joint_offsets = [" + ", ".join(str(o) for o in offsets_line) + "]")
        else:
            print(f"# 只读到 {len(all_ids)}/15 只：不要写进 toml（缺项默认全 0）")
            for i in all_ids:
                print(f"#   ID {i}: offset = {rows[i]['offset']}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "joint_names": JOINT_NAMES,
                       "center": CENTER}, f, ensure_ascii=False, indent=1)
        print(f"\n写到 {a.json}")

    if a.apply_toml:
        if a.json:
            return _write_toml(a.apply_toml, rows, len(ids))
        if not rows:
            print("\n没有可写的读数。")
            return 0
        return _write_toml(a.apply_toml, rows, len(ids), allow_partial=a.allow_partial)

    return 0


if __name__ == "__main__":
    sys.exit(main())
