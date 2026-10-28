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
| B5 | 固件 P（reg 50） | **= 32**（= 训练 `kp_fw`） | |
| B6 | D / 转矩 | 以**你刷到的** V167 release note 为准（V164 曾不写 D→出厂 40 发颤；V167 有修） | |

阶段 0 单颗闸门（URT-2/URT-1）未过 0.2 前不要买齐 15 颗：`urt1_bench.py` / FD。

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
