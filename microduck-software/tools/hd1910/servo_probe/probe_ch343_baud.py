#!/usr/bin/env python3
"""台架零成本先验：CH343(URT-2) 在 500000 波特下是否「真的」在发 HLS 帧。

对应 `docs/active/microduck-Pi4B-完整部署方案-feetech_hls-2026-11-09.md` 的 R3 / R6。
只做只读 ping，不写任何寄存器、不动扭矩。

为什么不能只问「端口能不能以 500000 打开」
--------------------------------------------
`serial.Serial(..., baudrate=500000)` 成功、以及随后 `ser.baudrate` 回显 500000，
都**只证明驱动接受了这个数**：pyserial 回显的是它自己缓存的设置值，不是从芯片
量回来的时钟。社区实测（bun-serial README，Linux cdc_acm，Radxa ZERO 3W 上的
CH343）记录过：芯片**接受** 400000 / 1152000 / 1843200 波特却**一个字节都不发**，
250000 / 256000 / 常规值到 3M 才工作。500000 不在其已验证集合里。

⇒ 唯一能证明「芯片真发了」的证据是**舵机回了帧**。所以本探针把「驱动接受」
与「物理有应答」拆成两个字段，零应答一律判 SILENT 而不是 PASS；400000 作为
已知坏值锚点留在候选集合里当负对照。

能力边界（不要当成测了波特率精度）
----------------------------------
本探针能测的是「可用性」与「往返延迟分布」（R3 的一半 + R6）。**位宽是否精确
2 us 仍需示波器/逻辑分析仪**——纯软件测不出来，输出里明确写 needs_scope。

同目录探针复用
--------------
帧构造直接 import `probe_bus_budget.frame` / `rx_frame_len`（同一个函数对象，
selftest 里用 `is` 断言），避免另造一套帧语义。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from probe_bus_budget import frame, rx_frame_len  # noqa: E402  单一权威帧构造

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # --selftest 路径不碰硬件
    serial = None
    list_ports = None

TARGET_BAUD = 500_000
# bun-serial README 报告的「驱动接受但静默不发」值之一，用作负对照锚点。
KNOWN_SILENT_BAUD = 400_000
DEFAULT_BAUDS = (115_200, 250_000, KNOWN_SILENT_BAUD, TARGET_BAUD, 1_000_000)
INST_PING = 1
PING_RX_LEN = rx_frame_len(0)  # FF FF ID LEN ERR CHK = 6
PASS_RATIO = 0.90             # 至少 90% 的 ping 有应答才算可用


# ---------------------------------------------------------------- 帧与判定


def ping_frame(pid: int) -> bytes:
    return frame(pid, INST_PING)


def classify(*, open_ok: bool, driver_echo: int | None, baud: int,
             replies: int, repeats: int) -> dict:
    """把「驱动接受」和「物理有应答」分开判，零应答绝不因为回显正确而 PASS。

    🔴 负对照锚点：若有人把实现改成「driver_echo == baud 就 PASS」，
    selftest 的 N1 会立刻变红。
    """
    if not open_ok:
        status, why = "OPEN_FAIL", "端口打不开"
    elif driver_echo != baud:
        status, why = "ECHO_MISMATCH", "驱动回显与请求值不一致"
    elif repeats <= 0:
        status, why = "NO_SAMPLES", "没有采样"
    elif replies == 0:
        status, why = "SILENT", "驱动接受但零应答：芯片可能根本没发（见 docstring）"
    elif replies / repeats < PASS_RATIO:
        status, why = "FLAKY", "有应答但丢包率高"
    else:
        status, why = "PASS", "驱动接受且舵机稳定应答"
    return {
        "baud": baud,
        "open_ok": open_ok,
        "driver_echo": driver_echo,
        "replies": replies,
        "repeats": repeats,
        "reply_ratio": (replies / repeats) if repeats else None,
        "status": status,
        "why": why,
    }


def latency_stats(xs: list[float]) -> dict:
    """R6 要的分布：p50 / p95 / max，单位毫秒。空列表不造数字。"""
    if not xs:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None, "spread_ms": None}
    ordered = sorted(xs)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)) + 1)]
    vals = [v * 1e3 for v in ordered]
    return {
        "n": len(xs),
        "p50_ms": round(statistics.median(vals), 4),
        "p95_ms": round(p95 * 1e3, 4),
        "max_ms": round(max(vals), 4),
        "spread_ms": round(max(vals) - min(vals), 4),
    }


# ---------------------------------------------------------------- 实机测量


def _one_ping(ser, pid: int, timeout: float) -> float | None:
    """发一帧 ping，等到 6 字节响应，返回 RTT（秒）。超时返回 None。"""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write(ping_frame(pid))
    ser.flush()
    while True:
        if ser.in_waiting >= PING_RX_LEN:
            dt = time.perf_counter() - t0
            ser.read(ser.in_waiting)
            return dt
        if time.perf_counter() - t0 > timeout:
            return None


def probe_baud(ser, baud: int, pid: int, repeats: int, timeout: float) -> dict:
    """调用前端口已用目标波特率打开；只测这一个波特率。"""
    xs: list[float] = []
    for _ in range(repeats):
        dt = _one_ping(ser, pid, timeout)
        if dt is not None:
            xs.append(dt)
    out = classify(
        open_ok=True,
        driver_echo=getattr(ser, "baudrate", None),
        baud=baud,
        replies=len(xs),
        repeats=repeats,
    )
    out["latency"] = latency_stats(xs)
    return out


def run_hardware(port: str, bauds: list[int], pid: int,
                 repeats: int, timeout: float) -> dict:
    """逐波特率打开 → ping → 关。任何一个打不开都记录 OPEN_FAIL 而不是中断整轮。"""
    if serial is None:
        raise RuntimeError("pyserial 不可用；先装 pyserial 或用 --selftest")
    results = []
    for baud in bauds:
        try:
            ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        except Exception as exc:
            results.append(classify(open_ok=False, driver_echo=None, baud=baud,
                                    replies=0, repeats=repeats))
            results[-1]["error"] = f"{type(exc).__name__}: {exc}"
            continue
        try:
            results.append(probe_baud(ser, baud, pid, repeats, timeout))
        finally:
            ser.close()
    return {
        "port": port,
        "servo_id": pid,
        "repeats": repeats,
        "timeout_s": timeout,
        "results": results,
        "target_baud": TARGET_BAUD,
        "target_status": next((r["status"] for r in results
                               if r["baud"] == TARGET_BAUD), "NOT_MEASURED"),
        # 🔴 纯软件测不出位宽精度，别让这份 JSON 被当成「500k 精确」的证据
        "baud_accuracy": "needs_scope",
        "note": "PASS 只证明芯片真在发且舵机稳定应答；波特率位宽精度需示波器",
    }


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    checks: list[tuple[str, bool, object, object]] = []

    def check(name: str, got, want) -> None:
        checks.append((name, got == want, got, want))

    # 单一权威帧构造：必须 import 同一个函数对象，不是复制一份
    import probe_bus_budget as pbb
    check("帧构造与 probe_bus_budget 同源 (is)", frame is pbb.frame, True)
    check("响应长度与 probe_bus_budget 同源 (is)", rx_frame_len is pbb.rx_frame_len, True)

    # 已知帧向量：ID10 ping -> FF FF 0A 02 01 F2
    want = bytes([0xFF, 0xFF, 0x0A, 0x02, 0x01, 0xF2])
    check("ID10 ping 帧逐字节", ping_frame(10), want)
    check("ping 帧长度 6", len(ping_frame(10)), 6)
    # 负对照：改 ID 必须改校验和，不能只是换一个字节
    check("负对照 改ID后帧不同", ping_frame(10) != ping_frame(11), True)
    check("ID11 ping 校验和 F1", ping_frame(11)[-1], 0xF1)

    # 🔴 N1：驱动回显正确 + 零应答，必须判 SILENT（不能判 PASS）
    ghost = classify(open_ok=True, driver_echo=500_000, baud=500_000,
                     replies=0, repeats=20)
    check("N1 驱动回显正确但零应答 -> SILENT", ghost["status"], "SILENT")
    check("N1 且不算 PASS", ghost["status"] != "PASS", True)
    # N1 的镜像：一旦有人把「零应答」判成 PASS，这条也一并红
    check("N1b reply_ratio 为 0", ghost["reply_ratio"], 0.0)

    # N2：全应答必须 PASS；少一半必须 FLAKY
    check("N2 20/20 应答 -> PASS",
          classify(open_ok=True, driver_echo=500_000, baud=500_000,
                   replies=20, repeats=20)["status"], "PASS")
    check("N2b 10/20 应答 -> FLAKY",
          classify(open_ok=True, driver_echo=500_000, baud=500_000,
                   replies=10, repeats=20)["status"], "FLAKY")
    # N3：回显不一致、端口打不开都不许判 PASS
    check("N3 回显不一致 -> ECHO_MISMATCH",
          classify(open_ok=True, driver_echo=115_200, baud=500_000,
                   replies=20, repeats=20)["status"], "ECHO_MISMATCH")
    check("N3b 打不开 -> OPEN_FAIL",
          classify(open_ok=False, driver_echo=None, baud=500_000,
                   replies=0, repeats=20)["status"], "OPEN_FAIL")

    # 🔴 N4：已知坏值锚点必须在默认集合里（删掉它就失去负对照）
    check("N4 400000 坏值锚点在默认集合", KNOWN_SILENT_BAUD in DEFAULT_BAUDS, True)
    check("N4b 500000 是目标且在默认集合", TARGET_BAUD in DEFAULT_BAUDS, True)
    check("N4c 默认集合含 1M 台架历史基线", 1_000_000 in DEFAULT_BAUDS, True)

    # N5：延迟分布统计；负对照改数据后 p50 必须变
    fake = [0.001, 0.002, 0.003, 0.004, 0.005]
    st = latency_stats(fake)
    check("N5 p50 = 3.0 ms", st["p50_ms"], 3.0)
    check("N5 spread = 4.0 ms", st["spread_ms"], 4.0)
    check("N5 负对照 全零 p50 不为 3.0", latency_stats([0.0] * 5)["p50_ms"] != 3.0, True)
    check("N5b 空列表不造数字", latency_stats([])["p50_ms"], None)

    bad = [c for c in checks if not c[1]]
    for name, ok, got, want in checks:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    print(f"\nselftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main() -> int:
    ap = argparse.ArgumentParser(description="CH343(URT-2) 500k 可用性与 USB 延迟台架探针")
    ap.add_argument("--selftest", action="store_true", help="离线自检，不碰硬件")
    ap.add_argument("--port", default="COM3", help="URT-2 的串口，默认 COM3")
    ap.add_argument("--id", type=int, default=10, help="台架那唯一一颗舵机的 ID，默认 10")
    ap.add_argument("--bauds", default=",".join(str(b) for b in DEFAULT_BAUDS),
                    help="逗号分隔的候选波特率；默认含 400000 已知坏值锚点")
    ap.add_argument("--repeats", type=int, default=20, help="每个波特率的 ping 次数")
    ap.add_argument("--timeout", type=float, default=0.05, help="单次 ping 超时（秒）")
    ap.add_argument("--out", default="", help="结果 JSON 路径；留空则只打印")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    # 先查活动端口：没有就明确报「为什么跑不了」，绝不假装跑过
    if list_ports is not None:
        active = [p.device for p in list_ports.comports()]
        print(f"活动串口: {active if active else '(空)'}")
        if args.port not in active:
            print(f"SKIP: {args.port} 不在活动串口列表里，URT-2 可能未插好。", file=sys.stderr)
            print("      本探针需要真实硬件；请先插上 URT-2 + 舵机供电再跑。", file=sys.stderr)
            print("      （--selftest 可在无硬件时验证判定逻辑）", file=sys.stderr)
            return 2

    bauds = [int(x.strip()) for x in args.bauds.split(",") if x.strip()]
    report = run_hardware(args.port, bauds, args.id, args.repeats, args.timeout)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        path = pathlib.Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"\n写出: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
