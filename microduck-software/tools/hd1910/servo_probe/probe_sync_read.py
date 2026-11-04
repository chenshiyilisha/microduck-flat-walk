#!/usr/bin/env python3
"""判定 [bus] fast_sync_read 该写 true 还是 false —— 一条包，零运动，不写寄存器。

why 需要它
----------
上游 `duck-control/src/bus.rs:467-489` 把这个开关讲得很清楚，包括为什么它**不做探测**：

  > It is all or nothing: ... a device whose firmware does not implement 0x8A does not
  > answer and the whole read times out. That is the same shape of failure a silent servo
  > already causes on a plain sync read ... Nothing here probes for support. A device that
  > does not answer looks exactly like one that is unpowered, and a startup probe would
  > have to tell those apart to say anything useful -- so the answer is a key someone
  > turns off, not a guess this code makes every boot.

这段话是对的，但它的前提是「**不知道设备是否活着**」。台架单颗场景里这个前提不成立：
PING 先过一遍，"活着" 就是已知条件，于是 0x8A 的沉默只剩一种解释 —— 固件不实现。
本脚本做的就是这个消歧。上游缺的不是方法，是那个已知条件。

两个指令码不是一回事
--------------------
  飞特 SCS v1（HD1910 走这个）  FF FF FE len 0x82 [addr, len, id...] ~sum
      —— 出处 kissqy `duck-control/src/feetech.rs:35,562-580`（SYNC_READ = 0x82）
   Dynamixel Protocol 2.0        FF FF FD 00 id len_lo len_hi 0x8A [addr_lo,addr_hi,
                                 len_lo,len_hi, id, data_len_lo,data_len_hi ...] crc16
      —— 0x8A 是 P2.0 的 FAST SYNC READ；**帧头、长度字段宽度、校验方式全都不同**

所以这不是「同一个指令的两种叫法」，是两套协议。HD1910 说 SCS，理论上只会 0x82。

判决（直接写进 robotd.toml 的 [bus] fast_sync_read）
---------------------------------------------------
  0x82 应答 ∧ 0x8A 沉默  -> false   （Feetech 正解，HD1910 预期结果）
  0x82 应答 ∧ 0x8A 应答  -> true    （意外，但那就该用 true）
  0x82 沉默              -> 中止，先修接线/波特率/供电，本脚本**不下结论**

风险是不对称的：把不该 true 的写成 true，每次读都超时、症状像接线坏（上电即全红）；
把该 true 的写成 false，只是每 tick 多一个包头和一个 turnaround。⇒ 缺证据时选 false。

用法
----
  .venv-mjlab/Scripts/python.exe tools/hd1910/servo_probe/probe_sync_read.py \
      --port COM3 --id 10            # 判决
  ... --selftest                     # 离线自检（不碰硬件，含 CRC16 已知向量 + 负对照）
前置：robotd 没占着串口（本机台架即插即用；上机后先 systemctl stop robotd）
"""
import argparse
import sys
import time

FRAME = b"\xff\xff"          # SCS v1 头
BROADCAST = 0xFE
IMU_ID = 200                 # 与 15 舵机同一个 sync_read；feetech.rs 要求它排第一

INST_PING = 0x01
INST_READ = 0x02
INST_SYNC_READ_SCS = 0x82    # 飞特，8-bit len，~sum 校验
INST_FAST_SYNC_READ_P2 = 0x8A  # Dynamixel P2.0，16-bit len，CRC16

REG_POS = 56                 # 台架读位置；与部署共用同一地址
LEN_POS = 2


# ---------------------------------------------------------------- SCS v1 (Feetech)

def scs_frame(pid: int, inst: int, params: bytes = b"") -> bytes:
    """FF FF id len inst params ~sum，len = 参数数 + 2（feetech.rs: packet()）"""
    body = bytes([pid, len(params) + 2, inst, *params])
    return FRAME + body + bytes([(~sum(body)) & 0xFF])


def scs_status_ok(pkt: bytes) -> bool:
    """状态帧：FF FF id len err data... chk；校验和把 id..chk **全加起来**应为 255。

    与 feetech.rs:117-124（`sum != 255` 判坏包）同一判据，不是自己定的。
    ⚠️ 上界必须是 length+4（含最后一字节 chk），写成 length+3 会漏掉 chk、恒假。
    """
    if len(pkt) < 6 or pkt[:2] != FRAME:
        return False
    length = pkt[3]
    if len(pkt) != length + 4:
        return False
    return sum(pkt[2:length + 4]) & 0xFF == 0xFF


def scs_xfer(ser, tx: bytes, want_ids, want_len: int, timeout_s=0.08):
    """发一帧，收所有状态帧。返回 {id: payload}。只收 want_ids 里的 id。"""
    ser.reset_input_buffer()
    ser.write(tx)
    ser.flush()
    deadline = time.time() + timeout_s
    buf = b""
    got = {}
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        # 逐帧切：FF FF id (len) ... 共 len+4 字节
        while len(buf) >= 4:
            i = buf.find(FRAME)
            if i < 0:
                buf = b""
                break
            buf = buf[i:]
            if len(buf) < 4:
                break
            length = buf[3]
            if length < 2 or len(buf) < length + 4:
                break
            pkt, buf = buf[:length + 4], buf[length + 4:]
            if not scs_status_ok(pkt):
                continue
            if pkt[2] in want_ids:
                got[pkt[2]] = pkt[5:5 + length - 2]
        if len(got) >= len(want_ids):
            break
        time.sleep(0.001)
    return got


def scs_ping(ser, pid: int) -> bool:
    got = scs_xfer(ser, scs_frame(pid, INST_PING), {pid}, 0, timeout_s=0.05)
    return pid in got


def scs_read(ser, pid: int, addr: int, count: int):
    got = scs_xfer(ser, scs_frame(pid, INST_READ, bytes([addr, count])),
                   {pid}, count)
    return got.get(pid)


def scs_sync_read(ser, addr: int, count: int, ids):
    """BROADCAST 0x82 [addr, count, *ids]。应答是每颗一条普通状态帧。"""
    params = bytes([addr, count, *ids])
    return scs_xfer(ser, scs_frame(BROADCAST, INST_SYNC_READ_SCS, params),
                    set(ids), count)


# ------------------------------------------------------- Dynamixel P2.0 (0x8A)

def crc16(data: bytes, crc: int = 0) -> int:
    """Robotis P2.0 CRC-16：poly 0x8005，**MSB-first**，初值 0，**从包首 FF FF FD 00 起算**。

    两个细节都踩过坑，用已知向量钉住（见 selftest）：PING id 1 的整包 CRC = 19 4E。
      - 误用 LSB-first/0xA001（MODBUS 那套）→ 3A 14
      - 误从 id 起算（跳过 4 字节头）→ 3A 14
      - 误从 FF FF 起算 → C9 4C
    即：位序、起算点、多项式三者任一错，都不会得到 19 4E。
    """
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def p2_packet(pid: int, inst: int, params: bytes = b"") -> bytes:
    """FF FF FD 00 | id | len_lo len_hi | inst | params | crc_lo crc_hi

    长度字段 = inst + params + 2（CRC），即 P2.0 定义的 LENGTH。
    CRC 覆盖**整个包（含 4 字节头）**，不含 CRC 自身 —— 这是与 SCS 最大的不同。
    """
    body = bytes([pid, (len(params) + 3) & 0xFF, (len(params) + 3) >> 8, inst]) + params
    head = b"\xff\xff\xfd\x00" + body
    crc = crc16(head)
    return head + bytes([crc & 0xFF, crc >> 8])


def p2_fast_sync_read(addr: int, length: int, ids) -> bytes:
    """0x8A FAST SYNC READ 参数：addr(2) len(2) [id data_len(2)]...

    ⚠️ 布局按 Robotis P2.0 手册写，**本仓没有可核对的一手实现**（上游走 xl330 crate，
       源码不在树内）。这处不确定**不影响判决**：预期结果是沉默，且有 PING/0x82 两个
       阳性对照在位——若 HD1910 真应答，说明它确实实现 0x8A，布局值得再查；若沉默，
       无论布局对不对都只能判 false，而 false 本来就是缺证据时的默认。
    """
    params = bytes([addr & 0xFF, addr >> 8, length & 0xFF, length >> 8])
    for i in ids:
        params += bytes([i, length & 0xFF, length >> 8])
    return p2_packet(BROADCAST, INST_FAST_SYNC_READ_P2, params)


def p2_any_reply(ser, timeout_s=0.10) -> bytes:
    """0x8A 之后读空口。P2.0 状态帧头是 FF FF FD 00；也接受任何非空字节。"""
    deadline = time.time() + timeout_s
    buf = b""
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        time.sleep(0.002)
    return buf


# ------------------------------------------------------------------ 判决

def probe(ser, sid: int, verbose=True) -> dict:
    out = {"id": sid}

    out["ping"] = scs_ping(ser, sid)
    if verbose:
        print(f"  阳性对照 PING(id {sid})          : "
              f"{'应答 ✓' if out['ping'] else '无应答 ✗'}")
    if not out["ping"]:
        out["verdict"] = None
        out["why"] = "PING 都不应答 ⇒ 接线/波特率/供电问题，本脚本不下结论"
        return out

    direct = scs_read(ser, sid, REG_POS, LEN_POS)
    out["read"] = direct
    if verbose:
        shown = f"{int.from_bytes(direct, 'little')} ✓" if direct else "无应答 ✗"
        print(f"  阳性对照 READ(56,2)              : {shown}")

    sync = scs_sync_read(ser, REG_POS, LEN_POS, [sid])
    out["sync82"] = sync.get(sid)
    ok82 = out["sync82"] is not None and out["sync82"] == direct
    if verbose:
        v = "无应答 ✗"
        if out["sync82"] is not None:
            v = (f"应答 {int.from_bytes(out['sync82'], 'little')}"
                 + ("（与单读一致 ✓）" if out["sync82"] == direct else "（与单读不一致 ✗）"))
        print(f"  被测 0x82 SYNC_READ(56,2)        : {v}")

    # 负对照：混一个不存在的 ID 进去，真 ID 仍须应答、假 ID 必须沉默。
    ghost = 0xFD
    mixed = scs_sync_read(ser, REG_POS, LEN_POS, [sid, ghost])
    out["ghost_answered"] = ghost in mixed
    if verbose:
        print(f"  负对照 0x82 掺假 id {ghost:<3}          : "
              f"{'假 id 也应答了 ✗（解码器有问题）' if out['ghost_answered'] else '假 id 沉默 ✓'}；"
              f"真 id {'仍应答 ✓' if sid in mixed else '不应答 ✗'}")

    # 被测：P2.0 0x8A
    tx = p2_fast_sync_read(REG_POS, LEN_POS, [sid])
    ser.reset_input_buffer()
    ser.write(tx)
    ser.flush()
    raw = p2_any_reply(ser)
    out["raw8a"] = raw.hex()
    out["sync8a"] = len(raw) > 0
    if verbose:
        print(f"  被测 0x8A FAST_SYNC_READ         : "
              f"{'收到 ' + str(len(raw)) + ' 字节：' + raw.hex() if raw else '沉默（0 字节）'}")

    if not ok82:
        out["verdict"] = None
        out["why"] = "0x82 不可用 ⇒ 协议层有更基础的问题，先别动这个开关"
        return out
    if out["ghost_answered"]:
        out["verdict"] = None
        out["why"] = "负对照失败（假 id 也应答）⇒ 先修读取器，结论不可用"
        return out
    out["verdict"] = bool(out["sync8a"])
    out["why"] = "固件应答 0x8A ⇒ 可以用 fast sync read" if out["sync8a"] else \
                 "固件只认 0x82 ⇒ fast_sync_read 必须 false（上游默认 true 会在上电后每读超时）"
    return out


def run(args) -> int:
    if args.dry_run:
        print("dry-run：只打报文，不开串口")
        print(f"  0x82  : {scs_frame(BROADCAST, INST_SYNC_READ_SCS, bytes([REG_POS, LEN_POS, args.id])).hex(' ')}")
        print(f"  0x8A  : {p2_fast_sync_read(REG_POS, LEN_POS, [args.id]).hex(' ')}")
        print(f"  （对比）PING id {args.id} : {scs_frame(args.id, INST_PING).hex(' ')}")
        return 0

    import serial
    ser = serial.Serial(args.port, args.baud, bytesize=8, parity="N",
                        stopbits=1, timeout=0.05)
    try:
        print(f"端口 {args.port} @ {args.baud}，目标 id {args.id}")
        res = probe(ser, args.id)
    finally:
        ser.close()

    print()
    if res["verdict"] is None:
        print(f"⚠️ 无法下结论：{res['why']}")
        return 2
    print(f"[bus] fast_sync_read = {'true' if res['verdict'] else 'false'}")
    print(f"  依据：{res['why']}")
    return 0


# ------------------------------------------------------------------ 自检

def selftest() -> int:
    fails = []

    def check(name, cond):
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            fails.append(name)

    # 1. CRC16 对已知向量：PING ID 1 的整包 = FF FF FD 00 01 03 00 01 19 4E
    check("CRC16 已知向量（PING id1 → 19 4E）", p2_packet(1, 0x01) == bytes.fromhex("fffffd0001030001" + "194e"))

    # 2. 负对照：改一个字节，CRC 必须变
    check("CRC16 负对照：改 id 后 CRC 不同",
          p2_packet(2, 0x01)[-2:] != p2_packet(1, 0x01)[-2:])

    # 3. SCS 校验和：单字节和 = 255（含 chk 自身）
    f = scs_frame(1, INST_READ, bytes([56, 2]))
    check("SCS 校验和 含chk求和 == 255", sum(f[2:]) & 0xFF == 0xFF)

    # 4. SCS 帧头/长度字段：len = 参数数 + 2
    check("SCS len 字段 = params + 2", f[3] == 4 and len(f) == f[3] + 4)

    # 5. 0x82 参数顺序必须是 [addr, len, *ids]（feetech.rs:562-580）
    pkt = scs_frame(BROADCAST, INST_SYNC_READ_SCS, bytes([56, 2, 10]))
    check("0x82 参数 [addr, len, id] 且广播 0xFE", pkt[2] == 0xFE and pkt[5:8] == bytes([56, 2, 10]))

    # 6. 0x8A 参数里地址/长度是 16 位小端（与 0x82 的 8 位是两套协议）
    p8a = p2_fast_sync_read(124, 12, [200])
    check("0x8A 头部是 P2.0（FF FF FD 00）", p8a[:4] == b"\xff\xff\xfd\x00")
    check("0x8A 参数 addr=124 len=12 小端", p8a[8:12] == bytes([124, 0, 12, 0]))
    # params = addr(2) + len(2) + [id(1) + data_len(2)] = 7；LENGTH = params + inst + crc = 10
    check("0x8A 长度字段 = 7 + 3", p8a[5] == 10 and len(p8a) == 4 + 4 + 7 + 2)

    # 7. 状态帧解析：造一条合法帧必须过，改校验必须挂
    base = bytes([0xFF, 0xFF, 10, 4, 0, 0x34, 0x12])
    good = base + bytes([(~sum(base[2:])) & 0xFF])
    check("状态帧解析：合法帧过", scs_status_ok(good) and good[5:7] == bytes([0x34, 0x12]))
    bad = good[:-1] + bytes([(good[-1] + 1) & 0xFF])
    check("状态帧解析负对照：坏校验必挂", not scs_status_ok(bad))
    check("状态帧解析负对照：截断必挂", not scs_status_ok(good[:-1]))

    print(f"\n{len(fails)} 项失败" if fails else "\n全部通过")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--id", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true", help="只打报文，不开串口")
    ap.add_argument("--selftest", action="store_true", help="离线自检，不碰硬件")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
