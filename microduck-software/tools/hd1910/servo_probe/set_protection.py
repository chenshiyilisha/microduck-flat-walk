#!/usr/bin/env python3
"""HD-1910 保护开关（reg19 卸力条件）落盘 —— 15 颗沿用同一份判决。

    python set_protection.py --port COM3 --ids 10 --verify     # 只读，断电后复核用
    python set_protection.py --port COM3 --ids 10 --apply      # 解锁→写→回读→上锁
    python set_protection.py --selftest

## 判决：reg19 = 13 = bit0 电压 + bit2 过热 + bit3 过流（2026-11-04 台架）

位映射（飞特官方教程原文，与 reg20 LED 同构）：
    32=过载  16=空  8=过流  4=过热  2=磁编码  1=电压

为什么开这三个：

* **bit2 过热（厂默认就有）**：唯一一个阈值真的落在可达工况里的保护。
  堵转 2.0 A 时外壳几分钟就到 80 ℃，这是摔倒后腿被压住的唯一兜底。
* **bit0 电压**：阈值 reg14 = 100 = **10.0 V**，2S 满电 8.4 V ⇒ 19% 余量；
  规范工况永不触发，只在接错电源（3S / 12 V 可调电源）时卸力，避免带病驱动。
  台架功能性 A/B 已证它真的卸力（同条件只差这一位：走了 59 步 vs 0 步），
  且**不因新指令解除**，要等电压回落（与过流"来新指令即解除"不同）。
* **bit3 过流**：阈值 reg28 = 500 × 6.5 mA = **3.25 A** = 1.6× 堵转 2.0 A ⇒
  规范工况永不触发；只在绕组/驱动短路这类硬故障上动作。零代价保险。

为什么**刻意不开**：

* **bit5 过载（32）—— 绝不能开**。判据是"指令到了、位置没跟上"，而 kp8（P=8、D=0、软）
  带载稳态误差本来就是走路的常态 ⇒ 走两步就"卸力 2 s 到 20%" ⇒ 必摔。
  ⚠️ STS 系列出厂默认是 **52（含 32）**，别拿"恢复出厂"当安全动作。
* **bit1 磁编码**：触发语义没有文档、没有阈值可核；一次误触发就是一次摔倒，
  而它防的"编码器彻底失效"并不是渐变失效模式。先关，靠 reg65 的 BIT1 在日志里观察。

## 写入纪律（踩过的坑）

* EEPROM 每字节 commit ~10 ms ⇒ **每包之间等 ≥50 ms**，背靠背会写进 commit 窗口（假成功）。
* 写完必须 **reg55=1 上锁 + 回读**；而**回读 PASS ≠ 持久 PASS**，
  唯一判据是**断电重上电后再读一次** —— 所以 --apply 之后要人为拔插一次电源，再 --verify。
* mode 4 下 reg40=0 不生效（停不住），所以写 EEPROM 期间不断扭矩，只选不动 goal 的地址。
"""
import argparse
import sys
import time

import hd1910_ident as ident

REG_UNLOAD = 19
REG_LED = 20
REG_LOCK = 55
REG_PROT_CURRENT = 28

BITS = {0: "电压", 1: "磁编码", 2: "过热", 3: "过流", 4: "空", 5: "过载"}
TARGET = (1 << 0) | (1 << 2) | (1 << 3)          # 13
FORBIDDEN = 1 << 5                                # 过载：开了必摔
MA_PER_LSB = 6.5
STALL_A = 2.0


def decode(v: int) -> list[str]:
    """位段 → 名称列表（未定义的高位按 0x{..} 打出来，不静默丢弃）。"""
    out = [name for bit, name in BITS.items() if v & (1 << bit)]
    if v & 0xC0:
        out.append(f"未定义位 0x{v & 0xC0:02X}")
    return out


def check(bus, sid: int) -> dict:
    return {
        "unload": bus.read_u8(sid, REG_UNLOAD),
        "led": bus.read_u8(sid, REG_LED),
        "lock": bus.read_u8(sid, REG_LOCK),
        "prot_current": bus.read_u16(sid, REG_PROT_CURRENT),
        "status": bus.read_u8(sid, 65),
        "volt": bus.read_u8(sid, 62),
    }


def report(sid: int, c: dict) -> bool:
    u = c["unload"]
    ok = u == TARGET
    print(f"  ID {sid}: reg19 = {u} = {'+'.join(decode(u)) if u else '全关'}"
          f"   {'✅ 等于部署值 13' if ok else f'❌ 期望 {TARGET}'}")
    print(f"          reg28 = {c['prot_current']} ⇒ {c['prot_current'] * MA_PER_LSB / 1000:.2f} A "
          f"（{c['prot_current'] * MA_PER_LSB / 1000 / STALL_A:.2f}× 堵转 {STALL_A} A）"
          f"   lock = {c['lock']}   电压 = {c['volt'] / 10:.1f} V   status = 0b{c['status']:08b}")
    if u is not None and u & FORBIDDEN:
        print("         ⚠️⚠️ bit5 过载开着 —— kp8 带载稳态误差会被判成'挡住'，"
              "触发即卸力 2 s 到 20%，走路必摔")
        ok = False
    return ok


def apply_one(bus, sid: int) -> bool:
    before = check(bus, sid)
    if before["unload"] is None:
        print(f"  ID {sid}: 无应答，跳过")
        return False
    print(f"  ID {sid}: {before['unload']} → {TARGET}")
    bus.write_u8(sid, REG_LOCK, 0)
    time.sleep(0.05)
    if bus.read_u8(sid, REG_LOCK) != 0:
        print(f"  ID {sid}: 解锁失败（reg55 仍不是 0），不写")
        return False
    bus.write_u8(sid, REG_UNLOAD, TARGET)
    time.sleep(0.10)                       # EEPROM commit ~10 ms，留 10× 余量
    got = bus.read_u8(sid, REG_UNLOAD)
    bus.write_u8(sid, REG_LOCK, 1)
    time.sleep(0.10)
    if got != TARGET:
        print(f"  ID {sid}: ❌ 写入后回读 {got} ≠ {TARGET}")
        return False
    if bus.read_u8(sid, REG_LOCK) != 1:
        print(f"  ID {sid}: ❌ 上锁失败（reg55 ≠ 1）")
        return False
    print(f"  ID {sid}: 回读/上锁 PASS —— 但这只是 RAM 影子，"
          f"**拔插一次电源再 --verify 才算持久 PASS**")
    return True


def selftest() -> int:
    fails = 0

    def eq(name, got, want):
        nonlocal fails
        if got != want:
            fails += 1
            print(f"  ❌ {name}: {got} != {want}")
        else:
            print(f"  ✅ {name}")

    eq("decode(4) 只有过热", decode(4), ["过热"])
    eq("decode(13) 三项", sorted(decode(13)), sorted(["电压", "过热", "过流"]))
    eq("decode(0) 空", decode(0), [])
    eq("decode(52) 含过载", "过载" in decode(52), True)
    eq("TARGET 本身不含过载", bool(TARGET & FORBIDDEN), False)
    eq("TARGET 含过热", bool(TARGET & (1 << 2)), True)
    eq("TARGET == 13", TARGET, 13)
    eq("3.25 A 换算", round(500 * MA_PER_LSB / 1000, 2), 3.25)
    eq("1 字节 244 是错读（负对照）", round(244 * MA_PER_LSB / 1000, 2) < 2.0, True)
    print(f"\n{'全部通过' if not fails else f'{fails} 项失败'}")
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="HD-1910 reg19 保护开关")
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="10")
    ap.add_argument("--apply", action="store_true", help="写入（默认只读）")
    ap.add_argument("--verify", action="store_true", help="只读复核（断电后跑这个）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    if not a.verify and not a.apply:
        print("只读模式：加 --apply 才写，或 --verify 做断电后复核\n")
    bus = ident.Bus(a.port)
    try:
        ok = True
        for sid in ids:
            if a.apply:
                ok &= apply_one(bus, sid)
            else:
                ok &= report(sid, check(bus, sid))
    finally:
        bus.close()
    if a.apply and ok:
        print("\n下一步：**断开舵机电源再上电**，然后 --verify 复核 —— "
              "回读 PASS 只证明 RAM 影子改到了，不证明 EEPROM 落了盘。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
