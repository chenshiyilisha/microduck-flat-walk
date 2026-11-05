#!/usr/bin/env python3
"""H6 判据：IMU 落脚乱跳台架实测（LSM6DSV16X SFLP 姿态 vs 陀螺自积分）。

判据来自 microduck-replica 的实机排障（BNO085 系列崩溃根因）：
芯片融合姿态在足部冲击的 20 ms 内跳 20–60°，而陀螺说没转 —— 物理上不可能。
我们的 SFLP 是同一族融合（LSM6DSV16X-SFLP），是否存在同类落脚乱跳未实测。

做法（不依赖加速度计，它不通过总线暴露）：
  每帧同时得到
      δ_sflp  = SFLP 姿态四元数的单帧增量角（°）
      ω_step  = |陀螺| × dt（°），陀螺说这帧转了多少
  判乱跳 = δ_sflp > 5° 且 ω_step < 2°   （姿态跳了、陀螺说没动）
  判反向 = δ_sflp > 5° 且增量轴与陀螺轴点积 < -0.3（跳的方向和角速度相反）

波形不可用作理由：真运动的同步跳 δ_sflp≈ω_step 且不触发判据（负对照 3 验证）。

用法（台架，芯片总在线）：
  python imu_jitter_bench.py --port COM3 --id 200 --dur 10 --out out.json
  python imu_jitter_bench.py --selftest          # 负对照：合成序列必须触发/不触发
前置：把 IMU 板（DuckBuddy 2S 版或 666wsp，ID 200，地址 56）接在 URT-2 上，
台架上让舵机配重保持站立姿态、机器人静止，然后人工敲击/拍击躯干、或放落地垫冲击。
"""
import argparse
import math
import sys
import time
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # verify_imu_chain.py 在 tools/hd1910/

try:
    import serial
except ImportError:
    serial = None

try:
    from hd1910_readonly import query  # 复用协议帧（inst=2 单读）
except ImportError:
    query = None

K_GYRO = 17.5 * math.pi / 180.0 / 1000.0   # rad/s per count，与 imu.rs/verify_imu_chain 一致
IMU_ADDR = 56
HZ = 50.0
DT = 1.0 / HZ

try:
    from verify_imu_chain import Sflp, pack_block  # noqa: E402
except Exception:  # noqa: BLE001
    Sflp = None
    pack_block = None


def quat_delta(q_prev, q_cur):
    """四元数增量角（度）与增量轴。conj(q_prev)⊗q_cur 的向量部分 -> 2·asin(|v|)。"""
    a0, a1, a2, a3 = q_prev
    b0, b1, b2, b3 = q_cur
    dx = a0 * b1 - a1 * b0 - a2 * b3 + a3 * b2
    dy = a0 * b2 + a1 * b3 - a2 * b0 - a3 * b1
    dz = a0 * b3 - a1 * b2 + a2 * b1 - a3 * b0
    v_norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    ang = 2.0 * math.asin(min(1.0, v_norm))
    axis = [dx / v_norm, dy / v_norm, dz / v_norm] if v_norm > 1e-12 else [0.0, 0.0, 1.0]
    return math.degrees(ang), axis


class Scorer:
    """一维流式判据：每帧喂 (delta_sflp, omega_step, axis_dot)。"""

    JUMP_MIN_DEG = 5.0     # 姿态单帧跳变阈值
    STEP_MAX_DEG = 2.0     # "陀螺说没动" 的上限

    def __init__(self):
        self.n = 0
        self.delta_sflp = []
        self.omega_deg = []
        self.jumps = 0
        self.flips = 0
        self.jump_times = []

    def feed(self, delta_deg: float, omega_deg: float, axis_dot: float):
        self.n += 1
        self.delta_sflp.append(delta_deg)
        self.omega_deg.append(omega_deg)
        jumped = delta_deg > self.JUMP_MIN_DEG and omega_deg < self.STEP_MAX_DEG
        if jumped:
            self.jumps += 1
            self.jump_times.append(self.n)
        if jumped and axis_dot < -0.3:
            self.flips += 1

    def report(self) -> dict:
        ds = sorted(self.delta_sflp)
        p50 = ds[len(ds) // 2] if ds else 0.0
        return {
            "samples": self.n,
            "delta_sflp_p50_deg": round(p50, 2),
            "delta_sflp_max_deg": round(ds[-1], 2) if ds else 0.0,
            "omega_deg_per_s_mean": round(sum(self.omega_deg) / self.n if self.n else 0.0, 1),
            "jumps": self.jumps,
            "reverse_jumps": self.flips,
            "jump_times_idx": self.jump_times[:40],
        }


def sample_stream(ser, imu_id: int, n: int, duration: float | None = None,
                  dead: float | None = None) -> list:
    """从总线上逐帧读 IMU 块并解码。"""
    if Sflp is None:
        raise SystemExit("缺少 verify_imu_chain.py（Sflp 解码器），请检查 .upstream")
    sflp = Sflp(median=False)
    t0 = time.time()
    samples = []
    raw_pad = b""
    for i in range(n):
        got = query(ser, imu_id, IMU_ADDR, 12)
        if got is None:
            got = raw_pad
        else:
            raw_pad = got
        if len(got) < 12:
            continue
        now = time.time()
        dt = min(max(now - (t0 + i * DT), 0.002), 0.05)
        gyro, grav, quat = sflp.decode(got)
        samples.append((dt, list(quat), [float(v) for v in gyro]))
        if duration is not None and now - t0 >= duration:
            break
    return samples


def score_samples(samples) -> tuple:
    scorer = Scorer()
    prev_quat = None
    for dt, quat, gyro in samples:
        omega_rad = math.sqrt(sum(v * v for v in gyro))          # rad/s 模长
        omega_deg_step = omega_rad * dt * 180.0 / math.pi         # 每帧角度（°）
        if prev_quat is not None:
            delta_deg, axis = quat_delta(prev_quat, quat)
            if omega_rad > 1e-9:
                axis_dot = sum(a * g for a, g in zip(axis, gyro)) / omega_rad
            else:
                axis_dot = 0.0
            scorer.feed(delta_deg, omega_deg_step, axis_dot)
        prev_quat = quat
    return scorer, scorer.report()


def synth_block(gyro_sensor_dps, quat_xyzw, scale=K_GYRO):
    """按 verify_imu_chain.pack_block 构造一块 12 字节。"""
    counts = [int(round(v * math.pi / 180.0 / scale)) for v in gyro_sensor_dps]
    def f16(x):
        return int(np.float16(x).view(np.uint16))
    body = b"".join(int(c).to_bytes(2, "little", signed=True) for c in counts)
    body += b"".join(f16(v).to_bytes(2, "little") for v in quat_xyzw)
    return body


def _zup_quat(roll=0.0, pitch=0.0, yaw=0.0):
    """Body->world 四元数（scalar-first），scipy 缺失时用手算欧拉。"""
    try:
        from scipy.spatial.transform import Rotation
        r = Rotation.from_euler("ZYX", [yaw, pitch, roll], degrees=True)
        x, y, z, w = r.as_quat()
        return [w, x, y, z]
    except Exception:
        cy, sy = math.cos(yaw * math.pi / 360), math.sin(yaw * math.pi / 360)
        cp, sp = math.cos(pitch * math.pi / 360), math.sin(pitch * math.pi / 360)
        cr, sr = math.cos(roll * math.pi / 360), math.sin(roll * math.pi / 360)
        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy
        return [w, x, y, z]


def run_bench(port: str, imu_id: int, duration: float, out: str | None):
    if serial is None:
        sys.exit("缺 pyserial：pip install pyserial")
    if query is None:
        sys.exit("缺 hd1910_readonly.py")
    ser = serial.Serial(port, 1_000_000, bytesize=8, parity="N", stopbits=1, timeout=0.05)
    print(f"== IMU 乱跳判据台架（{port}，ID {imu_id}，addr 56，50 Hz）==")
    print("请保持机器人站立并静止，然后人工敲击躯干/制造落地冲击；Ctrl-C 停止。\n")
    samples = []
    try:
        end = time.time() + duration
        while time.time() < end:
            got = query(ser, imu_id, IMU_ADDR, 12)
            if got and len(got) >= 12:
                gyro, grav, quat = Sflp(median=False).decode(got)
                now = time.time()
                dt = DT
                samples.append((dt, list(quat), [float(v) for v in gyro]))
                d = quat_delta([1, 0, 0, 0] if len(samples) == 2 else samples[-2][1], quat) \
                    if len(samples) > 2 else (0.0, [0, 0, 0])
                omega = math.sqrt(sum(v * v for v in gyro)) * 180 / math.pi
                mark = " ⚠" if (d[0] > Scorer.JUMP_MIN_DEG and omega * dt < Scorer.STEP_MAX_DEG) else ""
                print(f"\rt={now - (end - duration):5.1f}s  δ_sflp={d[0]:6.2f}°  |ω|={omega:7.1f}°/s{mark:4}",
                      end="", flush=True)
            time.sleep(DT)
    except KeyboardInterrupt:
        pass
    ser.close()
    print()
    if not samples:
        sys.exit("没有任何有效样本——只连上了 IMU 吗？检查 500k/1M 波特率与 addr")
    scorer, rep = score_samples(samples)
    print("== 汇总 ==")
    print(json_lines(rep))
    verdict = "判乱跳（ALERT）" if scorer.jumps > 0 else "判稳定（PASS）"
    print(f"判决：{verdict}")
    if scorer.jumps:
        print("  见 replica 经验：纯软件可修（改用陀螺融合/加抗冲击滤波），先记录再改。")
    if out:
        Path(out).write_text(json_dump({"summary": rep, "verdict": verdict,
                                        "thresholds": {"jump_min_deg": Scorer.JUMP_MIN_DEG,
                                                        "step_max_deg": Scorer.STEP_MAX_DEG}}),
                              encoding="utf-8")
        print(f"已写 {out}")
    return 1 if scorer.jumps else 0


def json_lines(rep: dict) -> str:
    return "\n".join(f"  {k} = {v}" for k, v in rep.items())


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


def selftest() -> int:
    if Sflp is None or np is None:
        sys.exit("selftest 需要 numpy + verify_imu_chain")
    print("== 负对照（合成序列必须触发/不触发判据）==")
    good = True

    def run_seq(blocks, label, expect_jumps_gt, expect_flip):
        nonlocal good
        sflp = Sflp(median=False)
        samples = []
        prev = [1.0, 0.0, 0.0, 0.0]
        for b in blocks:
            gyro, grav, quat = sflp.decode(b)
            d, _ = quat_delta(prev, quat)
            omega = math.sqrt(sum(v * v for v in gyro)) * 180 / math.pi
            samples.append((DT, list(quat), [float(v) for v in gyro]))
            prev = quat
        sc, rep = score_samples(samples)
        got = (sc.jumps > 0)
        ok_jump = got == expect_jumps_gt
        ok_flip = (bool(expect_flip) == bool(sc.flips and rep["jumps"] > 0))
        mark = "ok" if ok_jump and ok_flip else "MISMATCH"
        good &= ok_jump and ok_flip
        print(f"  {mark:<9} {label}: jumps={sc.jumps} flips={sc.flips} "
              f"(expect jumps>0={expect_jumps_gt}, flips>0={expect_flip})")

    # A. 静止稳定：姿态不动、陀螺零 -> 0 乱跳
    q0 = _zup_quat(0, 5, 0)
    blocks_a = [synth_block([0, 0, 0], q0[1:])] * 40 + \
               [synth_block([2, -1, 1], q0[1:])] * 40
    run_seq(blocks_a, "A 静止+微抖动", False, False)

    # B. 落足冲击乱跳（replica 根因）：前 20 帧姿态 +20° 突跳，陀螺保持 0
    blocks_b = []
    q = q0
    for i in range(80):
        if i == 20:
            q = _zup_quat(0, 25, 0)   # 突跳 20°
        blocks_b.append(synth_block([0, 0, 0], q[1:]))
    run_seq(blocks_b, "B 姿态跳20°陀螺0", True, False)

    # C. 反向跳：姿态 yaw 反向跳 20°，陀螺给 +yaw 微动 -> axis_dot < -0.3 判为反向
    blocks_c = []
    q = q0                       # (roll=0, pitch=5, yaw=0)
    for i in range(80):
        if i == 20:
            q = _zup_quat(0.0, 5.0, -20.0)   # yaw 方向反向跳 20°
        blocks_c.append(synth_block([0.0, 0.0, 80.0], q[1:]))   # +yaw 微动（80°/s）
    run_seq(blocks_c, "C 反向突跳", True, True)

    # D. 真运动（陀螺/姿态同步）：roll 匀速扫，判据不得触发
    blocks_d = []
    roll_deg = 0.0
    for i in range(30):
        roll_deg += 6.0
        q = _zup_quat(roll_deg, 0, 0)
        blocks_d.append(synth_block([300.0, 0.0, 0.0], q[1:]))  # 300°/s 同步
    run_seq(blocks_d, "D 同步真运动", False, False)

    print()
    print("all consistent" if good else "MISMATCH")
    return 0 if good else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM3", help="URT-2 所在串口")
    ap.add_argument("--id", type=int, default=200, help="IMU 板总线 ID")
    ap.add_argument("--dur", type=float, default=10.0, help="采样秒数")
    ap.add_argument("--out", default=None, help="结果 JSON 输出")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run_bench(a.port, a.id, a.dur, a.out)


if __name__ == "__main__":
    sys.exit(main())
