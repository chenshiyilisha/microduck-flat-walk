#!/usr/bin/env python3
"""摇晃法验收 —— 把「扳关节看位置跟不跟手」做成可测量判据并归档。

why: 官方台架指南（whatled HD1910 Task-008/010）的摇晃法是目视法：扳输出轴，
     看位置列是否跟手。**目视法留不下证据**，15 颗验收时无法回溯哪一颗过没过。
     本脚本把它变成三段式自动判定 + JSON 存档。

协议/遥测不自己拼：frame / query / ping / signed_mag 全部 import 同仓
`hd1910_readonly.py`（现成实现；不复制 —— 两份实现会互抵）。
一次 READ 从 56 读 15 字节拿到 56..70 全部遥测，**同一帧内时间对齐**。

三段式
------
1. settle  静止基线：判「无自行运动」。位置跨度应 <= SPAN_IDLE（默认 2 计数）
2. wobble  扳动期：判「跟手」。跨度应 >= SPAN_MOVE（默认 20 计数 ≈ 1.76 deg），
           且必须**同时出现过上升段和下降段**（否则只是单向漂移，不是跟手）
3. release 松手期：判「回稳」。跨度应 <= SPAN_IDLE

只读：本脚本**不写任何寄存器**。所以扳动时会感到 PD 抵抗（P=32 较硬，越扳越紧），
这是正确行为，也顺带验证了闭环。USB 5V 档靠板上 500 mA 过流保护顶着 ⇒
脚本实时监控电流 raw，超过 --warn-cur 只告警不中止（中止会打断测试，交由人判断）。

用法
----
  python3 wobble_check.py --port COM3 --id 1                 # 默认 4/12/4 秒
  python3 wobble_check.py --port COM3 --id 1 --json out/w.json
  python3 wobble_check.py selftest                           # 不碰硬件，验判据

判据阈值可调，但**改阈值必须记进验收记录**，否则两次验收不可比。
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hd1910_readonly import frame, query, ping, signed_mag  # noqa: E402

REG_POS = 56
TELEM_LEN = 15          # 56..70
HZ = 20.0
SPAN_IDLE = 2           # 静止期允许的位置跨度（计数）
SPAN_MOVE = 20          # 扳动期最小跨度（计数）；20 计数 ≈ 1.76 deg
CUR_WARN_RAW = 70       # 约 455 mA @6.5 mA/unit（换算待实物标定，只作量级）


def telemetry(ser, sid: int) -> dict | None:
    rx = query(ser, sid, REG_POS, TELEM_LEN)
    if rx is None or len(rx) < TELEM_LEN:
        return None
    cur = signed_mag(rx[13], rx[14])
    return {
        "pos": rx[0] | (rx[1] << 8),
        "speed": signed_mag(rx[2], rx[3]),
        "load": signed_mag(rx[4], rx[5]),
        "volt": rx[6] / 10.0,
        "temp": rx[7],
        "goal": rx[11] | (rx[12] << 8),
        "cur_raw": cur,
    }


def sample(ser, sid: int, seconds: float, label: str, warn_cur: int) -> dict:
    """采样一段，实时打印；返回统计量。"""
    n_target = max(1, int(seconds * HZ))
    pos_list: list[int] = []
    cur_list: list[int] = []
    temp_list: list[int] = []
    lost = 0
    warned = False
    t0 = time.monotonic()
    print(f"  [{label}] 采样 {seconds:.0f} 秒 @ {HZ:.0f} Hz ...")
    for _ in range(n_target):
        t = telemetry(ser, sid)
        if t is None:
            lost += 1
            print("    (丢包)")
        else:
            pos_list.append(t["pos"])
            cur_list.append(t["cur_raw"])
            temp_list.append(t["temp"])
            if abs(t["cur_raw"]) >= warn_cur and not warned:
                warned = True
                print(f"    ⚠️ 电流 raw {t['cur_raw']} 已达告警线 {warn_cur}"
                      f" —— USB 档靠板上 500mA 保护顶着，轻一点扳")
        time.sleep(max(0.0, 1.0 / HZ - (time.monotonic() - t0 - len(pos_list) / HZ)))
    if not pos_list:
        return {"n": 0, "lost": lost, "span": None, "up": 0, "down": 0,
                "cur_peak": None, "temp_max": None, "warned": warned}
    ups = sum(1 for a, b in zip(pos_list, pos_list[1:]) if b - a >= 1)
    downs = sum(1 for a, b in zip(pos_list, pos_list[1:]) if b - a <= -1)
    return {
        "n": len(pos_list),
        "lost": lost,
        "span": max(pos_list) - min(pos_list),
        "pos_min": min(pos_list),
        "pos_max": max(pos_list),
        "up": ups,
        "down": downs,
        "cur_peak": max(abs(c) for c in cur_list),
        "temp_max": max(temp_list),
        "warned": warned,
    }


def judge(phases: dict) -> list[dict]:
    """三段判据。返回 [{check, ok, detail}]。"""
    s, w, r = phases["settle"], phases["wobble"], phases["release"]
    out: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        out.append({"check": name, "ok": ok, "detail": detail})

    add("链路无丢包",
        (s["lost"] + w["lost"] + r["lost"]) == 0,
        f"丢包 settle={s['lost']} wobble={w['lost']} release={r['lost']}")

    add("静止期无自行运动",
        s["span"] is not None and s["span"] <= SPAN_IDLE,
        f"跨度 {s['span']} 计数（阈值 <= {SPAN_IDLE}）")

    add("扳动期位置跟手",
        w["span"] is not None and w["span"] >= SPAN_MOVE,
        f"跨度 {w['span']} 计数（阈值 >= {SPAN_MOVE}，≈{w['span'] / 4096 * 360:.2f} deg）")

    add("扳动期有来有回（非单向漂移）",
        w["up"] >= 1 and w["down"] >= 1,
        f"上升段 {w['up']} / 下降段 {w['down']}")

    add("松手后回稳",
        r["span"] is not None and r["span"] <= SPAN_IDLE,
        f"跨度 {r['span']} 计数（阈值 <= {SPAN_IDLE}）")

    tmax = max(x["temp_max"] for x in (s, w, r) if x["temp_max"] is not None)
    add("温度无明显上升", tmax is not None and tmax <= 45,
        f"峰值 {tmax} ℃（阈值 <= 45；过热保护 80 ℃ 是兜底不是目标）")

    return out


def _wait(prompt: str, countdown: float) -> None:
    """等人准备好。非交互终端（stdin 已关）下 input 会抛 EOFError ⇒ 退化为倒计时。"""
    try:
        input(prompt)
    except EOFError:
        # input 已经把 prompt 打出来了，这里只补倒计时说明，别重复整句
        print(f"（无 stdin，改用 {countdown:.0f} 秒倒计时）", flush=True)
        for k in range(int(countdown), 0, -1):
            print(f"    {k} ...", flush=True)
            time.sleep(1.0)


def cmd_run(ser, sid: int, a) -> int:
    if not ping(ser, sid):
        print(f"✗ PING {sid} 失败 —— 先查接线/供电，别往下做")
        return 1
    print(f"✔ PING {sid} @ {a.port}")
    t = telemetry(ser, sid)
    if t is None:
        print("✗ 遥测读取失败")
        return 1
    print(f"  起始位置 {t['pos']}（{t['pos'] / 4096 * 360:.1f} deg）"
          f" 目标 {t['goal']} 电压 {t['volt']} V 温度 {t['temp']} ℃ 电流 raw {t['cur_raw']}")
    print()

    print("阶段 1/3 · 静止基线 —— 手不要碰舵机")
    settle = sample(ser, sid, a.settle, "settle", a.warn_cur)
    print(f"    跨度 {settle['span']} 计数，丢包 {settle['lost']}")
    print()

    _wait(f"阶段 2/3 · 扳动 —— 用手缓慢来回扳输出轴几度，"
          f"{a.wobble:.0f} 秒。准备好了按回车 ...", a.countdown)
    wobble = sample(ser, sid, a.wobble, "wobble", a.warn_cur)
    print(f"    跨度 {wobble['span']} 计数（{wobble['pos_min']} → {wobble['pos_max']}），"
          f"上 {wobble['up']} / 下 {wobble['down']}，电流峰值 raw {wobble['cur_peak']}")
    print()

    _wait("阶段 3/3 · 松手 —— 把手拿开，看是否回稳。准备好了按回车 ...", a.countdown)
    release = sample(ser, sid, a.release, "release", a.warn_cur)
    print(f"    跨度 {release['span']} 计数，丢包 {release['lost']}")
    print()

    phases = {"settle": settle, "wobble": wobble, "release": release}
    checks = judge(phases)
    print("=" * 62)
    for c in checks:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['check']:<22} {c['detail']}")
    all_ok = all(c["ok"] for c in checks)
    print("=" * 62)
    print(f"摇晃法验收：{'通过' if all_ok else '未通过'}"
          f"  （未通过就别给它写 ID —— 那等于把故障固化进装机清单）")

    if a.json:
        payload = {
            "tool": "wobble_check",
            "port": a.port,
            "servo_id": sid,
            "thresholds": {"span_idle": SPAN_IDLE, "span_move": SPAN_MOVE,
                           "warn_cur_raw": a.warn_cur, "hz": HZ},
            "start": t,
            "phases": phases,
            "checks": checks,
            "all_passed": all_ok,
        }
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print(f"存档 → {a.json}")
    return 0 if all_ok else 2


def cmd_selftest() -> int:
    """不碰硬件：用合成序列验判据本身（含负对照）。"""
    print("selftest：合成序列验证判据（不碰硬件）\n")
    ok_all = True

    def mk(span_idle, span_move, up, down, lost, temp):
        return {
            "settle": {"span": span_idle, "lost": lost, "up": 0, "down": 0,
                       "cur_peak": 3, "temp_max": temp},
            "wobble": {"span": span_move, "lost": lost, "up": up, "down": down,
                       "cur_peak": 40, "temp_max": temp},
            "release": {"span": span_idle, "lost": lost, "up": 0, "down": 0,
                        "cur_peak": 3, "temp_max": temp},
        }

    cases = [
        ("正常：静止 0 / 扳动 120 有来有回 / 回稳 1", mk(0, 120, 20, 18, 0, 24), True),
        ("负对照·未扳动（跨度 0）应 FAIL", mk(0, 0, 0, 0, 0, 24), False),
        ("负对照·单向漂移（只有上升段）应 FAIL", mk(0, 120, 20, 0, 0, 24), False),
        ("负对照·有丢包应 FAIL", mk(0, 120, 20, 18, 3, 24), False),
        ("负对照·过热（60 ℃）应 FAIL", mk(0, 120, 20, 18, 0, 60), False),
        ("负对照·静止期自行抖动（跨度 9）应 FAIL", mk(9, 120, 20, 18, 0, 24), False),
    ]
    for name, phases, expect in cases:
        checks = judge(phases)
        got = all(c["ok"] for c in checks)
        ok = got == expect
        ok_all &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         期望 {'通过' if expect else '未通过'} / 实测 {'通过' if got else '未通过'}")
        if not ok:
            for c in checks:
                if not c["ok"]:
                    print(f"           → {c['check']}: {c['detail']}")
    print(f"\nselftest：{'全部通过' if ok_all else '有失败'}"
          f"（判据本身必须既能放行也能拦下）")
    return 0 if ok_all else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HD-1910 摇晃法验收（只读，不写寄存器）")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "selftest"], help="run=真机验收 / selftest=不碰硬件")
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--settle", type=float, default=4.0, help="静止基线秒数")
    ap.add_argument("--wobble", type=float, default=12.0, help="扳动期秒数")
    ap.add_argument("--release", type=float, default=4.0, help="松手回稳秒数")
    ap.add_argument("--warn-cur", type=int, default=CUR_WARN_RAW,
                    help="电流 raw 告警线（约 6.5 mA/unit，换算待标定）")
    ap.add_argument("--countdown", type=float, default=3.0,
                    help="无 stdin 时改用倒计时的秒数")
    ap.add_argument("--json", default=None, help="结果存档路径")
    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return cmd_selftest()

    import serial
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1, timeout=0.05)
    try:
        return cmd_run(ser, a.id, a)
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
