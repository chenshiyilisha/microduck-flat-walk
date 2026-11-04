# HD1910 · kissqy 上板导入清单（有板再勾）

对应 `docs/active/microduck-HD1910阶段C软件清单.md` §4。  
**不自写 robotd。** 主链：kissqy 镜像 + 本仓 ONNX（obs 61 / act 14 / 50 Hz）。

出处：清单 §1–4；`stage0_software_prep.md`；`docs/reference/microduck-mjlab-GPU与三个新仓库.md`（0.9/0.5/0.7）；fanhao 飞特方向说明。

---

## A. 镜像与版本（先记再动）

| # | 项 | 期望 / 备注 | □ |
|---|---|---|---|
| A1 | 系统镜像 | kissqy R1（`microduck-zero3w-0.15.1-R1.img.xz`） | |
| A2 | 机器人中控 | **V167**（修鸭身抖动；配套 control.43） | |
| A3 | 记下确切版本 | 镜像 tag / 中控 Vxxx / 固件 control.4x | |
| A4 | 许可 | 作者原创部分**个人非商业** | |

下载入口：`stage0_software_prep.md`。

---

## B. 总线与方向（上策略前）

| # | 项 | 期望 | □ |
|---|---|---|---|
| B1 | 协议 | `protocol = "feetech-sts"`（非 Dynamixel） | |
| B2 | `robotctl health` | bus 绿；loop **50 Hz 0 missed** | |
| B3 | 方向表 | HD1910 读数方向常与 XL330 **相反** → 多数关节 **−1**（以本机标定为准，逐颗核对） | |
| B4 | 零位 / 限位 / IMU | 关节工作台过一遍；IMU 俯仰偏差必须运行时校掉 | |
| B5 | 固件 P（RAM 50 / EEPROM 21） | **= 8**（= 训练 `kp_fw`，§22）；`set_gains_all.py --persist` 写，**断电后回读**才算数（§22.7）。**写前先确认 15 颗全应答**：脚本会预检，缺一颗就退 2 且一个字节都不写（半套配置比原样不动更糟，§22.7 末） | |
| B6 | D / 转矩 | **D = 0**（`set_gain` 自己钉 0；出厂 D=40 会阻尼内部 PID，同 kP 下明显更软）；转矩上限 1000 | |
| B7 | **`[policy] gain`** | `/etc/robot/robotd.toml` 里 `gain = 8`。**默认 200，控制环每 tick 写 RAM，会把 EEPROM 的 8 覆盖掉**（§22.8，一手源码） | |
| B8 | 跑起来后回读 reg 50 | **= 8**。读到 200 ⇒ B7 没生效；读到 50 ⇒ 刚跌倒过，`gain_limp` 还在 RAM | |
| B9 | **增益标度家族** | 改了 `gain` 之后，另外三个按 200 标定的相对量必须同步改：`[safety] gain_limp = 3`（默认 50，在 kp8 下是 **6.25× 加力**，跌倒卸力反成硬撑）、`[safety] limp_fall_pose_gain = 8`（默认 160 = **20×**，回站姿会砸）、`[policy] action_scale = 1.0`（默认 0.9 是 alpha 策略的，会让每个动作小 10%；但这是**旋钮不是常数**——kissqy 自训版用 **0.7** 也走起来了，匹配训练时才是 1.0，§8.5.6）。用 `audit_robotd_toml.py` 一条命令查（§22.10） | |
| B10 | **两个「中立」默认值其实不中立** | ① `[policy] head_lowpass / legs_lowpass` 默认 **0.5 / 0.7**——robotd 注释说这是 alpha 策略的训练值，但**本训练管线里零低通**（`grep low_pass` 在 microduck_rl + mjlab 1.3.0 + bam 全无命中，动作是 `target = current + action*scale`）⇒ 必须写 **1.0**，否则等于给策略从未见过的目标加了个 τ≈17 ms 的一阶滤波（2 Hz 处 −2%、4 Hz 处 −7%、相移 6–11°）。② `[bus] fast_sync_read` 默认 **true** 是 **Dynamixel P2.0 的 0x8A**；HD-1910 是 Feetech（0x82）。robotd 自己的警告是「不实现 0x8A 的设备不应答，**每一次读都超时**」，症状(symptom)看起来完全像接线或波特率错 ⇒ 先写 **false**（**2026-11-04 台架已实测**：ID 10 对 0x8A 返回 0 字节，而 PING / 0x82 单读 / 0x82 同步读三个对照全通，假 id 负对照沉默 ⇒ 不是"没上电"而是"不实现"）。**优先级**：① 是硬故障（每次读超时），②③ 是"能对上最好"——kissqy 自训版 `robotd-selftrained.toml` 就把 lowpass/cmd_alpha 全留了默认并走起来了（§8.5.6） | |

阶段 0 单颗闸门（URT-2/URT-1）未过 0.2 前不要买齐 15 颗：`sts_bench.py` / FD。

---

## C. 策略导入（本仓权重）

| # | 项 | 期望 | □ |
|---|---|---|---|
| C1 | 导出 | 本仓 HD1910 ONNX，**烘焙 normalizer**；parity 过 | |
| C2 | 契约 | obs **61** / act **14** / **50 Hz** — 勿改布局 | |
| C3 | 植物指纹 | runmeta / 笔记写明：`hd1910_openmicroduck_m5`（或日后 ftservo m6）+ m5 sha | |
| C4 | 热加载 | 中控「模型管理」导入自训 walk；**不要**上 XL330 `walk_std004_*` | |
| C5 | 部署缩放 | 训练侧 1/1/1；运行端常见 **基础 0.9 / 头 0.5 / 腿 0.7**（官方 Dynamixel 运行默认，**不是训练超参**）；再乘电压补偿 `7.4/V`（以当时中控说明为准） | |
| C6 | 短站立 | 先站稳再给速度指令；再谈走路 | |
| C7 | 本仓彩排 | `rehearse_hd1910.py`（仿真，m5/kp32）作对照，**不能单独宣称真机已会走** | |

---

## D. sim2real 结论必带字段

写进日记忆 / 评测 JSON：

1. 植物指纹（m5 或 ftservo m6）+ 参数 sha  
2. 镜像版本 + 中控 V + 固件 control  
3. 实测 P / D / 转矩  
4. 方向表摘要（或「与 fanhao −1 默认一致」）  
5. 部署缩放（若改过）  
6. 短走：是否不摔、体坐标大致前向（勿只报世界系 dx）

---

## E. 明确不做

- 自写飞特 daemon  
- 陆吾 `1910_m6`（STS3215 错标）当上机模型  
- 以仿真 ratio 单独宣称真机会走  
