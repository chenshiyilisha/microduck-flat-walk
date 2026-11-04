#!/usr/bin/env python3
"""解出 `[bus] joint_ids` —— 只读，不写任何寄存器、不给扭矩。

为什么需要这个：Feetech 舵机的 ID 是**装机时随便定的**，robotd 不肯猜
（`robotd/src/main.rs:1136` 的注释：「a guess drives one joint with another's targets」）。
只有两种办法知道哪个 ID 是哪个关节 —— ① 装机时贴了标签；② 扳一扳看谁在动。
本脚本做②，并且要求**每一次都只有一个关节在动**，否则判「分不清」而不是取最大。

用法（robotd 必须先停：它占着串口；扭矩最好也关掉 = 断电重上电后别启动 robotd）：
    python identify_joints.py --port COM3 --baud 1000000
    python identify_joints.py --port COM3 --joints left_hip_yaw,left_knee   # 只查两个
    python identify_joints.py --selftest                                    # 不碰硬件

输出最后一行是可以直接粘进 `out/robotd_hd1910_mode0.toml` 的 `joint_ids = [...]`。

⚠️ 波特率：出厂是索引 0 = **1 Mbps**（USB 转接板吃得下），robotd 只开 **500 kbps**
   （feetech.rs:35）。解 ID 用台架这颗的实际波特率；改完 `baud` 子命令后这里要跟着切。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hd1910_readonly import ping, query, signed_mag  # noqa: E402

# 顺序固定按 duck-ipc-proto/src/lib.rs:239 JOINT_NAMES —— 与 robotd 的 15 个关节一一对应
JOINT_NAMES = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]

# 扳哪、怎么扳。写具体到"哪个零件相对哪个零件"，因为左髋 yaw 和左髋 roll 在整机上看不出区别
JOINT_HINT = [
    "左腿绕竖直轴（整条腿像走路转身那样摆）",
    "左腿向外侧张开（大腿绕前后轴侧摆）",
    "左大腿前后摆（髋部，小腿跟着整体动）",
    "左小腿相对大腿屈伸（膝）",
    "左脚掌相对小腿上下翻（踝）",
    "脖子那节前后俯仰（躯干与头之间，头跟着整体动）",
    "头点头（俯仰，不改脖子角度）",
    "头左右转（偏航）",
    "头侧倾（滚转）",
    "下颌开合（嘴）",
    "右腿绕竖直轴（同左髋 yaw）",
    "右腿向外侧张开",
    "右大腿前后摆",
    "右小腿相对大腿屈伸",
    "右脚掌相对小腿上下翻",
]

# duck-control/src/model.rs:15 JOINT_IDS —— 原版 Duck（XL330 机身）的映射。
# 只拿来**对照**，不写进配置：我们的机关是不是同一套，正是本脚本要回答的问题。
REFERENCE_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]

POS_REG = 56
DEG_PER_COUNT = 360.0 / 4096.0


def parse_ids(spec: str):
    """'10-34' / '10,11,20' / '10-14,20-24' → [int]"""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-"))
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def p2p(values):
    """峰峰值（步）。None 读数被丢掉：丢读数和"没动"是两件事，混在一起会把通信坏判成静止。"""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return max(vals) - min(vals)


def pick(p2p_map, threshold=8, ratio=2.0):
    """从一次扳动里挑出唯一在动的舵机。

    返回 (id | None, 原因)。**不取最大就算数**：两个一起动时说"分不清"，
    因为这正是"猜错了关节"的入口 —— 上游注释里那条错误被重复读错四次。
    """
    live = {k: v for k, v in p2p_map.items() if v is not None}
    if not live:
        return None, "没有任何 ID 给出读数"
    ranked = sorted(live.items(), key=lambda kv: -kv[1])
    best_id, best_val = ranked[0]
    if best_val < threshold:
        return None, f"最大只有 {best_val} 步（< {threshold}）：没人动或动得太小"
    if len(ranked) > 1 and ranked[1][1] * ratio > best_val:
        return None, (f"ID {best_id} 动 {best_val} 步，ID {ranked[1][0]} 动 "
                      f"{ranked[1][1]} 步：不够悬殊（要 {ratio:g}×），分不清")
    return best_id, f"{best_val} 步，第二名 {ranked[1][1] if len(ranked) > 1 else 0} 步"


def read_pos(ser, sid):
    r = query(ser, sid, POS_REG, 2)
    return signed_mag(*r) if r else None


def sample(ser, ids, secs, hz=20.0):
    """在 secs 秒内轮询所有 ID 的位置（每 ID 一串样本）。"""
    acc = {i: [] for i in ids}
    t_end = time.monotonic() + secs
    while time.monotonic() < t_end:
        for sid in ids:
            acc[sid].append(read_pos(ser, sid))
        time.sleep(1.0 / hz)
    return acc


def selftest():
    """不碰硬件：验证 pick 的判决边界，含负对照。"""
    n = 0
    bad = 0

    def check(name, got, want):
        nonlocal n, bad
        n += 1
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}（期望 {want}）")

    print("=== 正例：只有一个动 ===")
    check("一个 40 步，其余 ≤2",
          pick({10: 40, 11: 2, 12: 1})[0], 10)

    print("=== 负对照：两个动得差不多 ⇒ 必须分不清 ===")
    check("35 vs 30 ⇒ 拒判",
          pick({10: 35, 11: 30})[0], None)
    check("35 vs 20 ⇒ 拒判（1.75× < 2×）",
          pick({10: 35, 11: 20})[0], None)
    check("35 vs 12 ⇒ 放行（2.9×）",
          pick({10: 35, 11: 12})[0], 10)
    check("35 vs 17 ⇒ 放行（2.06×）",
          pick({10: 35, 11: 17})[0], 10)

    print("=== 负对照：没人动 ⇒ 不能随便挑一个 ===")
    check("全 ≤5", pick({10: 5, 11: 4, 12: 0})[0], None)

    print("=== 负对照：丢读数 ≠ 静止 ===")
    check("只有一个 ID 有 2 个以上样本，其余 None",
          pick({10: None, 11: 60}, threshold=8)[0], 11)
    check("全部 None", pick({10: None})[0], None)

    print("=== p2p 口径 ===")
    check("丢 None 后算峰峰", p2p([None, 100, 104, None, 101]), 4)
    check("样本不足 ⇒ None", p2p([None, 100]), None)

    print("=== 输出格式：整表必须能按 JOINT_NAMES 顺序拼回去 ===")
    m = {jid: 1000 + 10 * k for k, jid in enumerate(REFERENCE_IDS)}
    got = [m[j] for j in REFERENCE_IDS]
    check("对照表往返", got, list(range(1000, 1150, 10)))

    print(f"\nselftest: {'ALL PASSED' if bad == 0 else f'{bad}/{n} FAILED'}")
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="解 joint_ids（只读）")
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1_000_000,
                    help="台架这颗现在是多少就是多少；robotd 部署档是 500000")
    ap.add_argument("--ids", default="10-34", help="候选 ID 区间，默认 10-34")
    ap.add_argument("--joints", default=None,
                    help="只查这几条（逗号分隔的 JOINT_NAMES 子集），默认全部 15 条")
    ap.add_argument("--secs", type=float, default=3.0, help="每条关节采样秒数")
    ap.add_argument("--threshold", type=int, default=8,
                    help="认为「动了」的最小峰峰值（步）；8 步 ≈ 0.7°")
    ap.add_argument("--ratio", type=float, default=2.0,
                    help="第一名必须比第二名大几倍才算分得清")
    ap.add_argument("--json", default=None, metavar="PATH")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    try:
        import serial
    except ImportError:
        sys.exit("缺 pyserial：pip install pyserial")

    ids = parse_ids(a.ids)
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1, timeout=0.05)

    found = [i for i in ids if ping(ser, i)]
    print(f"端口 {a.port} @ {a.baud}：扫描 {ids[0]}-{ids[-1]}，{len(found)} 只应答")
    if not found:
        ser.close()
        sys.exit("一只都没应答：先查供电/线序，再查波特率"
                 "（robotd 部署档是 500000，台架出厂是 1000000）")
    for i in found:
        p = read_pos(ser, i)
        print(f"  ID {i:>3}: pos={p} ({(p or 0) * DEG_PER_COUNT:.1f} deg)")

    todo = JOINT_NAMES if a.joints is None else [s.strip() for s in a.joints.split(",")]
    unknown = [j for j in todo if j not in JOINT_NAMES]
    if unknown:
        ser.close()
        sys.exit(f"不认识的关节名：{unknown}\n可选：{JOINT_NAMES}")

    print("\n⚠️ 手臂/手指别碰舵机，扭矩最好关着（断电重上电后不要启动 robotd）。")
    print("   每一条会说「扳哪个、怎么扳」，然后采 %.1f s。\n" % a.secs)

    mapped = {}
    unclear = []
    for name in todo:
        idx = JOINT_NAMES.index(name)
        print(f"→ 【{name}】{JOINT_HINT[idx]}")
        try:
            input("  准备好后回车开始采样…")
        except EOFError:
            pass
        acc = sample(ser, found, a.secs)
        p2p_map = {i: p2p(v) for i, v in acc.items()}
        best, why = pick(p2p_map, a.threshold, a.ratio)
        if best is None:
            unclear.append(name)
            print(f"  ✗ {why}")
            top = sorted(((v, k) for k, v in p2p_map.items() if v is not None), reverse=True)[:3]
            print(f"    前三：{[(f'ID {k}', f'{v} 步') for v, k in top]}")
        else:
            if best in mapped.values():
                prev = [k for k, v in mapped.items() if v == best]
                print(f"  ⚠️ ID {best} 已经被判给 {prev}：一次只扳一个关节，重来这条")
                unclear.append(name)
            else:
                mapped[name] = best
                print(f"  ✔ ID {best}（{why}）")
        print()

    ser.close()

    print("=" * 64)
    if unclear:
        print(f"未判定：{unclear}")
        print("这些关节不要猜。重跑对应几条（--joints 后面列出来）。")
    if mapped:
        print("已判定：")
        for name, jid in mapped.items():
            print(f"  {name:<16} → ID {jid}")
        if len(mapped) < len(JOINT_NAMES):
            print(f"\n⚠️ 只解出 {len(mapped)}/15 条，**先不要写进 robotd.toml**："
                  f"缺项的默认会让总线拒绝打开，补项则必须真测。")
    missing = [j for j in JOINT_NAMES if j not in mapped]
    if not missing:
        ids_line = [mapped[j] for j in JOINT_NAMES]
        print("\n# 可直接粘进 out/robotd_hd1910_mode0.toml:")
        print("joint_ids = [" + ", ".join(str(i) for i in ids_line) + "]")
        diff = [(JOINT_NAMES[k], ids_line[k], REFERENCE_IDS[k])
                for k in range(15) if ids_line[k] != REFERENCE_IDS[k]]
        if diff:
            print(f"\n⚠️ 与 model.rs 的 JOINT_IDS 有 {len(diff)} 处不同 —— "
                  f"这可能是真的（我们的机关不是原版），也可能是判错了：")
            for name, got, ref in diff:
                print(f"   {name:<16} 实测 {got} / 参考 {ref}")
        else:
            print("\n✔ 与 duck-control/src/model.rs:15 的 JOINT_IDS 完全一致")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"mapped": mapped, "unclear": unclear,
                       "joint_names": JOINT_NAMES}, f, ensure_ascii=False, indent=1)
        print(f"\n写到 {a.json}")
    return 0 if not unclear else 1


if __name__ == "__main__":
    sys.exit(main())
