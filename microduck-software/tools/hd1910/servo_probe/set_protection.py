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

## 写入纪律（三条，每条都有一次翻车记录，2026-11-04）

被断电验证过的唯一时序（连跑两轮都活过了拔插，reg13 对照组也一起活）：

    断电重上电（此时 reg40 默认 0 = 扭矩关） → 解锁 reg55=0，等 0.25 s 并回读
    → 写值，等 0.50 s → 上锁 reg55=1，等 0.50 s 并回读 → 再断电重上电 → --verify

1. **回读 PASS ≠ 持久 PASS**。第一次 --apply 回读 13、上锁 1，看着完美；
   拔插电源再 --verify **回到 4** —— 值只进了 RAM 影子。唯一判据是断电后回读。
2. **窗口要够长**：0.10 s 那版（旧代码）两次都失败，0.35–0.50 s 才真落盘。
   而且**值没变时固件会跳过 commit**（回读 PASS、掉电回旧值，与写失败同形），
   所以本文件在值已等于目标时先写一个不同的值再写回。
3. **不许切 mode**。切 mode 会让固件**从 EEPROM 重载配置**，把刚写的值冲掉 ——
   一次 0.30 s 窗口的尝试就是毁在"临时切 mode 0 再改回"这一步上。
   连带结论：mode 4 下 reg40 关不掉扭矩（goal+60 实测仍走 58 步），
   所以只能借"**上电默认 reg40=0**"这个窗口写 —— 即断电重上电后、robotd 起来之前。
   （外部印证：juxitech 规格页写明 HD-1910 有 5 个模式，**mode 4 = 纯位置 PD (Sim2Real)，出厂默认**，
   另有 0 角度伺服 / 1 恒速 / 2 恒流 / 3 PWM —— 纯 PD 模式本来就不走"扭矩使能"这套逻辑，
   所以 reg40 在它下面无效是设计如此，不是坏。）

官方依据：reg55 原文 *"写 0 关闭写入锁，写入 EEPROM 地址的值掉电保存；写 1 打开写入锁，
写入 EEPROM 地址的值掉电不保存"* —— 锁=1 时写 EEPROM 是**静默丢弃**，ERR 照样 0。
LeRobot 文档：*"With the torque off, a motor's EEPROM can be written."*

**金丝雀**：同一轮顺手写 reg20（LED 报警，同构位段、只影响灯）。
断电后若 reg20 变了而 reg19 没变 ⇒ 问题在寄存器，不在机制（本次两轮都一起变/一起不变）。
"""
import argparse
import sys
import time

import hd1910_ident as ident

REG_UNLOAD = 19
REG_LED = 20
REG_LOCK = 55
REG_PROT_CURRENT = 28
REG_TORQUE = 40
REG_GOAL = 42
REG_POS = 56

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
        "torque": bus.read_u8(sid, REG_TORQUE),
        "prot_current": bus.read_u16(sid, REG_PROT_CURRENT),
        "status": bus.read_u8(sid, 65),
        "volt": bus.read_u8(sid, 62),
        "pos": bus.read_u16(sid, REG_POS),
    }


def report(sid: int, c: dict) -> bool:
    u = c["unload"]
    ok = u == TARGET
    print(f"  ID {sid}: reg19 = {u} = {'+'.join(decode(u)) if u else '全关'}"
          f"   {'✅ 等于部署值 13' if ok else f'❌ 期望 {TARGET}'}")
    print(f"          reg20 = {c['led']}（LED，金丝雀）"
          f"   reg28 = {c['prot_current']} ⇒ {c['prot_current'] * MA_PER_LSB / 1000:.2f} A "
          f"（{c['prot_current'] * MA_PER_LSB / 1000 / STALL_A:.2f}× 堵转 {STALL_A} A）")
    print(f"          lock = {c['lock']}   torque = {c['torque']}   "
          f"电压 = {c['volt'] / 10:.1f} V   status = 0b{c['status']:08b}")
    if u is not None and u & FORBIDDEN:
        print("         ⚠️⚠️ bit5 过载开着 —— kp8 带载稳态误差会被判成'挡住'，"
              "触发即卸力 2 s 到 20%，走路必摔")
        ok = False
    return ok


def _move_probe(bus, sid: int, pos0: int) -> int:
    """功能性判断扭矩到底关没关：给 goal 加 60 步，看位置跟不跟。

    60 步 ≈ 5.3°。旧版"reg40=0 拦不住运动"的结论就是靠这个观察得出的，
    这里把它固化成前置检查 —— 关不掉扭矩就别指望 EEPROM 写进去。
    """
    bus.write_u16(sid, REG_GOAL, pos0 + 60)
    time.sleep(0.35)
    pos1 = bus.read_u16(sid, REG_POS)
    bus.write_u16(sid, REG_GOAL, pos0)
    time.sleep(0.20)
    d = abs((pos1 or pos0) - pos0)
    print(f"          扭矩功能性检查：goal +60 步 → 实际动了 {d} 步 "
          f"{'⇒ 扭矩仍是开的 ❌' if d > 10 else '⇒ 确实是自由状态 ✅'}")
    return d


def _write_eeprom_u8(bus, sid: int, addr: int, target: int, name: str):
    """写一个 EEPROM 字节，并保证这次写**真的是一次变化**。

    值本来就等于 target 时，固件很可能直接跳过 EEPROM commit（"没变就不用存"），
    于是回读 PASS、掉电照样回旧值 —— 和写失败长得一模一样。
    所以先写一个不同的值，再写 target。
    """
    cur = bus.read_u8(sid, addr)
    if cur == target:
        alt = target ^ 0x08 if (target & 0x08) else target | 0x08
        bus.write_u8(sid, addr, alt)
        time.sleep(0.50)
        print(f"          {name} 本就是 {target} ⇒ 先写 {alt} 制造一次变化，再写回")
    bus.write_u8(sid, addr, target)
    time.sleep(0.50)
    return bus.read_u8(sid, addr)


def apply_one(bus, sid: int, probe: bool = True) -> bool:
    """唯一被断电验证过的写入时序（2026-11-04，连跑两轮都活过了断电）：

        解锁 reg55=0 → 等 0.25 s（回读确认） → 写值 → 等 0.50 s
        → 上锁 reg55=1 → 等 0.50 s（回读确认）

    三条硬约束，每一条都有一次失败记录：

    * **窗口要够长**：0.10 s 那版回读 PASS、断电回 4；0.35–0.50 s 才真落盘。
    * **不许切 mode**：切 mode 会让固件把配置**从 EEPROM 重载**，等于把刚写的值
      冲回旧值 —— 那次 0.30 s 窗口的尝试就是被这一步毁掉的。
    * **写的时候扭矩得是关的**（官方前置条件）。mode 4 下 reg40 关不掉，
      所以只能利用"上电默认 reg40=0"这个窗口：**断电重上电后、robotd 起来之前写**。
    """
    before = check(bus, sid)
    if before["unload"] is None:
        print(f"  ID {sid}: 无应答，跳过")
        return False
    print(f"  ID {sid}: reg19 {before['unload']} → {TARGET}，reg20 {before['led']} → {TARGET}"
          f"（金丝雀）")

    if before["torque"] != 0:
        print(f"  ID {sid}: ❌ reg40 = {before['torque']}，扭矩使能中。"
              f"\n          mode 4 下 reg40 关不掉（goal+60 实测仍走 58 步），"
              f"切 mode 0 又会把配置从 EEPROM 重载。"
              f"\n          ⇒ 断电重上电（上电默认 reg40=0），在 robotd 起来之前跑这一步。")
        return False
    print("          扭矩 reg40 = 0 ✅（上电默认值，官方要求的写入前置条件）")

    # ① goal 钉在当前位置：写 EEPROM 期间不许它动
    pos0 = before["pos"]
    if pos0 is not None:
        bus.write_u16(sid, REG_GOAL, pos0)
        time.sleep(0.20)
    if probe:
        _move_probe(bus, sid, pos0 or 0)

    # ② 解锁（等足再回读：解锁没生效时写 EEPROM 是静默丢弃，RAM 照样变）
    bus.write_u8(sid, REG_LOCK, 0)
    time.sleep(0.25)
    if bus.read_u8(sid, REG_LOCK) != 0:
        print(f"  ID {sid}: 解锁失败（reg55 仍不是 0），不写")
        return False

    # ③ 逐字节写，每包之间留一个完整 commit 窗口
    rb19 = _write_eeprom_u8(bus, sid, REG_UNLOAD, TARGET, "reg19")
    rb20 = _write_eeprom_u8(bus, sid, REG_LED, TARGET, "reg20")
    print(f"          RAM 回读 reg19={rb19} reg20={rb20}")

    # ④ 上锁前再等一个完整窗口，避免 LockEprom 自己插进 commit 里
    time.sleep(0.50)
    bus.write_u8(sid, REG_LOCK, 1)
    time.sleep(0.50)
    lk2 = bus.read_u8(sid, REG_LOCK)

    ok = (rb19 == TARGET) and (rb20 == TARGET) and (lk2 == 1)
    print(f"  ID {sid}: {'RAM 回读/上锁 PASS' if ok else '❌ RAM 回读或上锁不符'}"
          f"（reg55={lk2}）—— **拔插一次电源再 --verify 才算持久 PASS**")
    return ok



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
    ap.add_argument("--no-probe", action="store_true",
                    help="跳过'扭矩关没关'的功能性检查（它会让舵盘动约 5°）")
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
                ok &= apply_one(bus, sid, probe=not a.no_probe)
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
