# HD-1910 硬件端到端复核清单（2026-11-08）

> 配套工具：`microduck-software/tools/hd1910/hardware_endtoend_check.py`
> 运行：`python tools/hd1910/hardware_endtoend_check.py`（静态 + 步骤清单）
> 负对照：`python tools/hd1910/hardware_endtoend_check.py --selftest`
> 真实硬件：`python tools/hd1910/hardware_endtoend_check.py --run-hardware --port COM3`

## 现状（已核对 HEAD）

软件/部署侧已闭环（pre_deploy_check 五关、audit_robotd_toml、IMU-median A/B 实测）。
**唯一剩下的真 OPEN 是「真机到货前的硬件端到端复核」**，本项目硬件尚未到货，所以分两层：

### ✅ 静态预验（现在就能跑，无需硬件）

脚本复用 `audit_robotd_toml` 全套检查，并直接核对 `out/robotd_hd1910_mode0.toml`：

| 项 | 结果 | 依据 |
|---|---|---|
| `bus.joint_ids`（15 个、互异、顺序） | **ok** | 与 `.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`）逐 ID 精确匹配 |
| `bus.joint_signs`（每项 ±1、15 项） | **ok** | 与 installation.json 的 `direction` 逐项吻合 |
| `airframe.zero_ticks`（CENTER） | **ok** | 15 个关节全是 2048，坐实 `offset = raw - 2048`（厂商背书） |
| `bus.imu_median` | **ok** | false —— 匹配训练延迟窗（A/B 实测：ON 致 4.7–9.4% 跌倒） |
| `battery.cells` | **ok** | `[2]`（非 `[2,3]` 默认，否则 3S 烧毁 4–8.4V 舵机） |
| `bus.position_kp=16` | **ok（文档化偏差）** | mode0/P16 ≡ mode4/P8（toml:62-65；台架 0.604 vs 0.605 @2Hz）；不是 gain=16 陷阱 |

> `position_kp=16` 被 `audit_robotd_toml` 按通用规则判 FAIL（reg50≠训练 Kp8），但本机型是**故意且台架验证过的部署**；harness 把它重分类为 ok 并写明出处，不静默删除。

### 🔴 动态复核（BLOCKED —— 必须真机在场）

| # | 项 | 预期 | 工具/步骤 |
|---|---|---|---|
| 1 | `bus.joint_ids` 逐关节扳动确认 | `[10,9,8,7,6,12,11,14,13,15,5,4,3,2,1]` | `servo_probe/identify_joints.py --port COMx`；两关节同动则报「分不清」而非猜 |
| 2 | `calibration_verified=false` → 零位杆测量 | `offset=raw@零-2048`，`sign` 取自方向 | `servo_probe/calibrate_offsets.py --port COMx --apply-toml .../robotd_hd1910_mode0.toml`；整机须在 DEFAULT_POSITION、扭矩关 |
| 3 | EEPROM reg6/reg33/reg9/11 | `{6:1, 33:0, 9:0, 11:4095}` | 台架曾留 reg6=0/reg33=4（都错）→ 总线打不开；写入时序见 `servo_probe/set_protection.py`、`eeprom_backup_id10.json` |
| 4 | 齿隙 @7.4V 重测 | ±1°（暂定值） | 4.6V 台架欠压、读数无效；`tools/hd1910/check_step_vs_sim.py --csv <7.4V>.csv --kp 8` |
| 5 | 电池识别 | 2S；reg62 在给扭矩前识别 | ≥6.0V 供电下确认 robotd 识别为 2S（4.6V 报「既非 2S 也非 3S」→ 瘫软；3S 被接受→烧毁） |

## 关键约束（来自本轮实读源码）

- **关节 ID 两套体系不能混用**：XL330 参考图是 `[20..24, 30..34, 10..14]`；HD-1910 机体是 1–15 体系。照抄别的项目 ⇒ 15 颗全错位（installation.json 已确认本机为 1–15）。
- **`deny_unknown_fields`**：不存在的键 = 整份配置加载失败。`bus.protocol` 在 DuckBuddy-main 代不存在 ⇒ 整文件 abort。
- **EEPROM 是「checked, not corrected」**：robotd 每次开机硬校验 reg6/reg33/reg9/11，不符就 **bus 不打開**，不是警告。
- **零位唯一杠杆** = `joint_offsets` / `joint_signs`；`offset = raw_at_joint_zero - 2048`，CENTER=2048 有厂商背书。

## 收口结论

硬件端到端复核的**能离线做的部分已全部预验通过（0 FAIL）**；剩下的 5 项动态复核是真机到货后才能跑的硬步骤，已编成带预期值+命令+引用的清单，到货即填表执行。
