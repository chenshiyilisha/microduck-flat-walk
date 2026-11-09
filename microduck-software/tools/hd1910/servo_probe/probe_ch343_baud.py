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
与「物理有应答」拆成两个字段，零应答一律不判 PASS；400000 作为已知坏值锚点
留在候选集合里（⚠️ 它只有在舵机速率也切到该值时才有区分力，见下面混淆段）。

🔴 2026-11-09 插上 URT-2 实跑后订正：零应答有两种互斥解释
------------------------------------------------------------
台架这颗舵机 **reg6=0（1 Mbps）**，而部署目标是 500 kbps。舵机根本听不懂
500k 的帧 ⇒ 零应答可能只是**速率不匹配**，不是 CH343 静默。原版把两者都写成
SILENT（「芯片可能根本没发」），会把一份「不可判」的数据留成「CH343 不行」的
证据。现在先读 reg6 建立基线，零应答且 baud != reg6 对应速率一律标
`RATE_MISMATCH` / `confounded=true`，顶层判 `INCONCLUSIVE_RATE_MISMATCH`。
**只有 baud 与舵机配置一致时的零应答，才可能是 CH343 的证据。**
⇒ 要真正消 R3，必须先把 reg6 改成 1（见 `hd1910_ident.py baud`，需断电重上电）。

🔴 判据有效性的前提：半双工不能自发自收
------------------------------------------
ping 请求帧和响应帧都是 6 字节。若 URT-2 把 TX 回环到 RX，`in_waiting >= 6`
读回来的会是**自己发的帧**，探针会假 PASS。所以用总线上不存在的 ID 253
做 ghost 负对照：ghost 有回字节 ⇒ `self_echo=true` ⇒ 整份判决作废。
（2026-11-09 实测：1 Mbps 下 ghost 零字节，真响应 `ffff0a0200f3`
≠ 发送帧 `ffff0a0201f2`，判据干净。）

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
from probe_bus_budget import BAUD_OF_REG6, frame, rx_frame_len  # noqa: E402  单一权威帧构造 + reg6 映射

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # --selftest 路径不碰硬件
    serial = None
    list_ports = None

TARGET_BAUD = 500_000
# bun-serial README 报告的「驱动接受但静默不发」值之一，用作负对照锚点。
# ⚠️ 它的区分力有前提：只有舵机 reg6 也切到这个速率时，零应答才可能是
#    「芯片静默」。在 reg6=0(1M) 的台架上，400000 和 500000 一样判
#    RATE_MISMATCH —— 实机负对照此时由 selftest 的 N1/N6/N7 承担，别看错。
KNOWN_SILENT_BAUD = 400_000
DEFAULT_BAUDS = (115_200, 250_000, KNOWN_SILENT_BAUD, TARGET_BAUD, 1_000_000)
INST_PING = 1
INST_READ = 2
REG_BAUD = 6                 # EEPROM 波特率索引（0=1M, 1=500k, ...）
GHOST_ID = 253               # 总线上不存在的 ID，自发自收回声负对照
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


def annotate(result: dict, servo_baud: int | None,
             self_echo: bool | None) -> dict:
    """把「零应答」拆成两种互斥解释：舵机速率不匹配 vs CH343 可能静默。

    🔴 负对照：若删掉 rate-match 判据，selftest 的 N6 会立刻变红。
    `classify` 的签名保持不变，好让既有回归里的「改坏 classify」仍能跑。
    """
    out = dict(result)
    # .get 而非下标：回归里会把 classify 换成「只看回显」的坏实现，
    # 那条路径必须让 selftest 变红，而不是抛 KeyError 中断。
    rate_match = None if servo_baud is None else (result.get("baud") == servo_baud)
    confounded = bool(result.get("replies", 0) == 0
                      and servo_baud is not None and rate_match is False)
    out["servo_configured_baud"] = servo_baud
    out["rate_match"] = rate_match
    out["confounded"] = confounded
    if confounded:
        out["status"] = "RATE_MISMATCH"
        out["why"] = (f"舵机 reg6 配在 {servo_baud} bps，此波特率下本就不该应答；"
                      "零应答不能归因于 CH343 静默（先改 reg6 再测）")
    out["self_echo_checked"] = self_echo is not None
    return out


def target_verdict(results: list[dict], servo_baud: int | None,
                   self_echo: bool | None) -> str:
    """顶层判决：只有「速率一致」时的应答/静默才是 CH343 的证据。"""
    # .get：回归里会把 classify/annotate 换成坏实现，那条路径要让自检变红，
    # 而不是抛 KeyError 中断（否则「负对照能删红」这条就不成立）。
    t = next((r for r in results if r.get("baud") == TARGET_BAUD), None)
    if t is None:
        return "NOT_MEASURED"
    if self_echo is True:
        return "INVALID_SELF_ECHO"
    if t.get("confounded"):
        return "INCONCLUSIVE_RATE_MISMATCH"
    if t.get("rate_match") is False:
        return "INVALID_UNEXPECTED_REPLY"
    if t["status"] == "PASS":
        return "PASS"
    if servo_baud is None:
        return "NO_BASELINE"
    return "CH343_SILENT_OR_HARDWARE"


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


def _read_bytes(ser, payload: bytes, n_expect: int, timeout: float) -> bytes:
    """发一帧、收裸字节，不判内容。用于 reg6 读取与 ghost 回声检查。"""
    ser.reset_input_buffer()
    ser.write(payload)
    ser.flush()
    t0 = time.perf_counter()
    buf = b""
    while time.perf_counter() - t0 < timeout:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        if len(buf) >= n_expect:
            break
    return buf


def check_self_echo(ser, timeout: float) -> dict:
    """ping 一个总线上不存在的 ID；一旦有回字节，说明发出去的帧被回环，
    「in_waiting >= 6 == 舵机应答」这条判据就不成立。"""
    payload = frame(GHOST_ID, INST_PING)
    buf = _read_bytes(ser, payload, PING_RX_LEN, timeout)
    return {"ghost_id": GHOST_ID, "tx": payload.hex(), "rx": buf.hex(),
            "self_echo": bool(buf)}


def read_reg6(ser, pid: int, timeout: float) -> dict:
    """在**舵机能应答**的波特率下读 EEPROM reg6，建立速率基线。

    响应：FF FF ID 03 ERR DATA CHK（7 字节）。读不到就返回 None，
    绝不拿默认值冒充基线。
    """
    payload = frame(pid, INST_READ, bytes([REG_BAUD, 1]))
    buf = _read_bytes(ser, payload, rx_frame_len(1), timeout)
    for i in range(max(0, len(buf) - rx_frame_len(1) + 1)):
        if buf[i:i + 3] == b"\xff\xff" + bytes([pid]) and buf[i + 3] == 3:
            return {"reg6": int(buf[i + 5]), "err": int(buf[i + 4]),
                    "raw_rx": buf[i:i + rx_frame_len(1)].hex()}
    return {"reg6": None, "err": None, "raw_rx": buf.hex()}


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


def _find_baseline(port: str, bauds: list[int], pid: int,
                   timeout: float) -> dict:
    """找一个舵机**真能应答**的波特率，在那里读 reg6 并测 ghost 回声。

    找不到就不能建立基线：servo_baud=None，顶层判 NO_BASELINE，
    绝不拿「猜一个」冒充证据。
    """
    for baud in bauds:
        try:
            ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        except Exception:
            continue
        try:
            if _one_ping(ser, pid, timeout) is None:
                continue
            return {"baseline_baud": baud,
                    "self_echo": check_self_echo(ser, timeout),
                    "reg6_read": read_reg6(ser, pid, timeout)}
        finally:
            ser.close()
    return {"baseline_baud": None, "self_echo": None,
            "reg6_read": {"reg6": None, "err": None, "raw_rx": ""}}


def run_hardware(port: str, bauds: list[int], pid: int,
                 repeats: int, timeout: float) -> dict:
    """阶段 0 建基线（reg6 + 回声）→ 阶段 1 逐波特率 ping → 阶段 2 标注混淆。"""
    if serial is None:
        raise RuntimeError("pyserial 不可用；先装 pyserial 或用 --selftest")

    base = _find_baseline(port, bauds, pid, timeout)
    reg6 = base["reg6_read"]["reg6"]
    servo_baud = BAUD_OF_REG6.get(reg6) if reg6 is not None else None
    self_echo = base["self_echo"]["self_echo"] if base["self_echo"] else None

    raw = []
    for baud in bauds:
        try:
            ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        except Exception as exc:
            raw.append(classify(open_ok=False, driver_echo=None, baud=baud,
                                replies=0, repeats=repeats))
            raw[-1]["error"] = f"{type(exc).__name__}: {exc}"
            continue
        try:
            raw.append(probe_baud(ser, baud, pid, repeats, timeout))
        finally:
            ser.close()

    results = [annotate(r, servo_baud, self_echo) for r in raw]
    return {
        "port": port,
        "servo_id": pid,
        "repeats": repeats,
        "timeout_s": timeout,
        # ---- 阶段 0：判据的两个前提 ----
        "baseline_baud": base["baseline_baud"],
        "servo_reg6": reg6,
        "servo_configured_baud": servo_baud,
        "reg6_read": base["reg6_read"],
        "self_echo": base["self_echo"],
        # ---- 阶段 1+2 ----
        "results": results,
        "target_baud": TARGET_BAUD,
        "target_status": next((r["status"] for r in results
                               if r["baud"] == TARGET_BAUD), "NOT_MEASURED"),
        "target_verdict": target_verdict(results, servo_baud, self_echo),
        # 🔴 纯软件测不出位宽精度，别让这份 JSON 被当成「500k 精确」的证据
        "baud_accuracy": "needs_scope",
        "note": ("RATE_MISMATCH 是舵机 reg6 速率不符造成的不可判，不是 CH343 静默；"
                 "PASS 仅在 rate_match=true 且 self_echo=false 时成立；"
                 "波特率位宽精度仍需示波器"),
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

    # 🔴 N6：速率混淆判决。删掉「rate_match」这层判据，下面几条会一起变红。
    # 这是 2026-11-09 实跑踩出来的：台架 reg6=0(1M)，500k 零应答不可归咎 CH343。
    zero = classify(open_ok=True, driver_echo=500_000, baud=500_000,
                    replies=0, repeats=20)
    conf = annotate(zero, 1_000_000, False)
    check("N6 速率不符的零应答 -> RATE_MISMATCH", conf["status"], "RATE_MISMATCH")
    check("N6b confounded=True", conf["confounded"], True)
    check("N6c 顶层判「不可判」而非 CH343 静默",
          target_verdict([conf], 1_000_000, False), "INCONCLUSIVE_RATE_MISMATCH")
    same = annotate(zero, 500_000, False)
    check("N6d 同速率零应答才可归咎 CH343",
          target_verdict([same], 500_000, False), "CH343_SILENT_OR_HARDWARE")
    check("N6e 同速率零应答保持 SILENT", same["status"], "SILENT")
    # N7：半双工自发自收回声 => 整份判决作废
    check("N7 自收回声 -> INVALID_SELF_ECHO",
          target_verdict([conf], 1_000_000, True), "INVALID_SELF_ECHO")
    # N8：reg6 映射必须来自单一权威，不另抄一份
    check("N8 reg6 映射与 probe_bus_budget 同源 (is)",
          BAUD_OF_REG6 is pbb.BAUD_OF_REG6, True)
    check("N8b reg6=0 -> 1M（台架出厂）", BAUD_OF_REG6.get(0), 1_000_000)
    check("N8c reg6=1 -> 500k（robotd 部署）", BAUD_OF_REG6.get(1), 500_000)
    check("N8d ghost ID 不与装机 ID 冲突", GHOST_ID > 34, True)

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
