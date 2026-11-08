# IMU `imu_median=false` 部署决策的仿真 A/B 实测验证

_日期：2026-11-08 · 关联：`tools/eval_velocity_in_sim.py --imu-median` · 策略 `p8head_030_4096x3000/model_2999.pt`（61 维，与部署 onnx `out/p8head_2999.onnx` 同权重）_

## 背景与动机

部署配置 `[bus] imu_median = false` 一直靠一条**理论**理由支撑：训练侧 IMU 延迟窗口为
0–20 ms（`base_ang_vel` / `projected_gravity` 均 `delay_min_lag=0, delay_max_lag=1`，
ctrl_dt=0.02s）；median ON 在瞬态把陀螺/重力延迟 +1 拍 = +20 ms，叠加芯片采样滞后
0–8.3 ms 后超窗（20–28.3 ms），OFF 则落在 0–8.3 ms 窗口内。`verify_imu_chain.py` 只证明
了解码数学与延迟账，但**从未在策略层实测** median ON vs OFF。本次用仿真闭环补上实测。

## 方法（先查一手资料，再动手）

- 真读 `duck-control/src/imu.rs` 的 `median3_each`：per-component median of three
  (`history[2 past] + now`)，稳态返回当前值（no-op），瞬态取中间样 → 延迟 1 拍。
- 注入点选在部署用的 61 维 obs 空间（`robustness.LAYOUTS[61]`：gyro=(0,3), grav=(3,6)）。
  但 `robustness.py` 依赖缺失的 `mjbatch`，跑不起来；改用已验证可跑、且用 `hd1910_kp8`
  plant + 该 `.pt` 策略 + 全套 gates 的 `eval_velocity_in_sim.py`。
- 给 `eval_velocity_in_sim.py` 加 `--imu-median`（默认关，零改动现有读数）：在喂策略前对
  `actor` obs 的 ang_vel[0:3]、gravity[3:6] 注入 robotd 同款 `_median3_t`
  （`m(a,b,c)=max(min(max(a,b),c),min(a,b))`），仅这两块、含 reset 逐环境历史清理。
- 对照：`nominal`（median OFF）vs `median`（median ON），各 3 seed × 64 envs × 8s，
  cmd (0.3,0,0) m/s，GPU（RTX 4070）。证据：`out/ab_median_{off,on}_s{0,1,2}.json`。

## 结果

| 条件 | seed | imu_median_active_frac | vx 中位 | dx/expected | wz 漂移 | upright_min | 跌倒率 |
|---|---|---|---|---|---|---|---|
| OFF | 0/1/2 | None | 0.136 / 0.136 / 0.135 | 0.425 / 0.414 / 0.410 | ≈0 | 0.9959 / 0.9955 / 0.9963 | **0.0%** |
| ON  | 0/1/2 | 0.9975 | 0.134 / 0.122 / 0.120 | 0.365 / 0.337 / 0.324 | **−0.045 / −0.069 / −0.056** | 0.9786 / 0.9849 / 0.9787 | **6.2% / 4.7% / 9.4%** |

`no_fall` gate：OFF 三 seed 全 PASS；ON 三 seed 全 FAIL。

## 结论

1. **`imu_median=false` 决策实测成立**：median ON 在 3 个独立 seed 上一致地让步态崩溃
   （跌倒率 4.7–9.4%、upright_min 从 ~0.996 掉到 ~0.98、前进速度下降）。从「理论对」
   升级为「实测对」，并**反证了『median ON 无害』的假设**。
2. **机理信号清晰**：ON 组出现一致的负 wz 漂移（−0.045~−0.069 rad/s），OFF 组 wz≈0。
   median 延迟陀螺仪 → 航向/平衡控制失稳 → 偏航 → 倾覆 → 跌倒，与「策略容不下 >20 ms
   陀螺延迟」的理论窗口论证完全吻合。
3. **`active_frac=0.9975` 不是 bug**：行走是连续运动，每步陀螺/重力都在变，median 在稳态
   才返回当前值；行走时它**每一步都延迟该两块 1 拍**，故 99.75% 证明注入全程生效。OFF 组
   `active=None` 也正确（无注入）。

## 诚实边界（不是假绿，是设计约束）

- 这是 **SIM 实测**。真机 median ON 还叠加：① 芯片采样滞后 0–8.3 ms（总延迟 20–28.3 ms，
  比 sim 的纯 20 ms 更超窗）；② median 的尖峰抑制收益（sim 干净无尖峰，故 sim 是
  「median 有害」的保守下界）。两点都使真机 median ON **至少与 sim 一样差** → 结论稳健。
- 机理是「陀螺/重力瞬态延迟」本身；本 A/B 不含「纯延迟控制组」，但 median 在干净 sim 中
  等价于瞬态延迟（无尖峰可抑），故结果即延迟效应。
- **新暴露的部署风险**：kp8 策略对陀螺延迟预算很紧（~20 ms 边际）。真机任何额外陀螺延迟
  （总线抖动、IMU 桥接延迟）都可能诱发同类退化——`imu_median=false` 之所以安全，依赖
  芯片低滞后（0–8.3 ms）落在容差内，这一项应作为上机前的核对项。

## 复现

```bash
CK=logs/rsl_rl/microduck_velocity_hd1910/2026-11-03_08-33-18_p8head_030_4096x3000/model_2999.pt
for cond in off on; do for s in 0 1 2; do
  med=""; [ "$cond" = on ] && med="--imu-median"
  .venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py --checkpoint "$CK" \
    --num-envs 64 --seconds 8 --cmd-vx 0.3 --plant hd1910_kp8 --device cuda:0 $med \
    --seed $s --out out/ab_median_${cond}_s${s}.json
done; done
```
