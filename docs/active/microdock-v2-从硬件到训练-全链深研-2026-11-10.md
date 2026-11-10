# MicroDock v2 从硬件到训练全链深研

_2026-11-10，核对于上游 `main@052a2494`；训练奖励逐项拆解见
`microduck-v2-坐式坞深研-2026-11-10.md`（本文不重复），本文补齐硬件参数源码、仿真 harness、
磁铁/接触力模型、patch 兼容性实测与集成路线。_

## 0. 总判决

1. **`butt_walk.patch` 在我们锁定的 `microduck_rl@b02fdea` 上实测可干净应用**（干净骨架 + `git apply --check`
   PASS，不是推断）。`b02fdea → bae39f59` 只有 5 个提交、全部是「训练 bundle 分享到 Hub」功能
   （export/publish/distill），**与 sitstand/velocity/mdp/机器人模型零交集** ⇒ 我们不升级 submodule 就能复刻配方。
2. patch 触碰面只有 4 个文件：`tasks/__init__.py`（2 个小 hunk）+ `tasks/mdp.py`（3 个小 hunk 追加 import 区
   + **306 行纯追加**）+ 2 个新文件（env cfg 324 行、测试 165 行）。按我们「纯新增」铁律的转写工作量很小：
   mdp helpers 抽成自己的新文件、env cfg 原样新增、注册走我们的包装层。
3. **机械部分可以立刻动手**：全部设计参数有源码（`dock.py` Params 40 余项）、有自动校验
   （`build.py --check`）、有设计不变量测试。唯一依赖真机的是鸭背那 8 个测量值——而且是官方 XL330 鸭的背，
   我们 HD-1910 复刻壳（744 g vs 737 g）几何不同，**hood 贴背面必须按我们的壳重测**。

## 1. 硬件链

### 1.1 参数全景（`hardware/microdock/source/dock.py`）

这是**待测量清单的权威版本**——来源分两类：官方模型直接读数（`trunk_base` 系）与近期真机照片估读。

| 参数 | 值 | 来源/含义 |
|---|---|---|
| `bat_drop` | 10 mm | 近期批次电池比官方模型低 10 mm，给 USB-C 口腾位 |
| `port_above_bat` | 4.8 mm | 口中心高于电池顶（壳沿上 4.5 mm） |
| `shell_back_x` | −47.13 mm | 磁头贴合的壳背位置（切口上沿接缝棱） |
| `port_recess` | 1.0 mm | 插座面缩进壳面 |
| `notch_w` | 12.1 mm | 切口宽（11.8 mm 磁头刚好塞进） |
| `notch_above_port` | 1.85 mm | 切口上沿高于口中心 |
| `button_xy` / `button_r` | (−28, 13) / 4.6 mm | 电源键（黄帽；外圈 +1.2），滑轨从 \|y\|>22.5 外跨过它 |
| `leds_xy` | (−28,−9), (−28,−15.5) | 两颗状态灯，同样避开 |
| `skid_y` | 22.5 mm | hood 滑轨落点 |
| `trunk_half_w` / `trunk_top` | 32.3 / 40.6 mm | 壳半宽 / 滑轨接触高 |
| `tip_*` | 3.4×11.8×6.0 mm | 磁头（鸭背上的磁吸公头） |
| 板件 | T3 板 195×200 + 坡 40 + board 250 高 | 全在 P1S 256 床内 |
| `dock_x` / `z0` | 81.5 / 118.6(v1)→62(v2) mm | 入坞位姿（仿真量得） |
| hood | 侧壁内 33、壁厚 2.4、喇叭 22 长/20 外扩、前唇 7×6 | |
| `plug` | (8, 12, 14) mm | 磁吸适配器（竖/横/长） |
| `angle_plug` / `angle_elbow` | (27.6, 9.5, 6.8) / (2.7, 10.3, 5.33) | UGREEN 100W 弯头线，按商品照片量的 |

**继承关系有测试锁着**：`tests/test_microdock_v2_design.py` 断言 v2 与 v1 只差 `z0/hood_float_y/hood_drop`
三个参数、其余逐 dataclass 字段相等。

### 1.2 自动校验（复刻者最该抄的工程习惯）

`build.py --check` 干五件事，全挂失败退出：
1. board 是**单一水密实体**且在 256 mm 床内；
2. `head_fit`：弯头线头带外张手指能从下方插入 hood、插后 0.3 mm 内保持、有 `forward_travel_mm` 行程；
3. `keeper_fit`：**hood 在任意浮动位置（lift×side×roll 网格扫描）keeper 在板上支承 ≥100 mm²**
   （实测发布版 min 274 mm²）+ 两根耗材销锁死验证；
4. hood/base/keeper/tag 与 v1 `same()`（manifold 布尔差体积 <1e-3 mm³，逐实体相同）；
5. `--bambu` 时连切片验证一起跑。

`test_microdock_v2_design.py` 把设计不变量写成 5 条测试（只有 3 个参数变、hood 高度区间、浮动更大、
adapter_dz=0、三个策略随仓发布）。

### 1.3 装配与采购（相对上一轮的新增结论）

- 装配 PDF 第 2 页有 **1:1 线径校验图**，打印必须 100% 缩放——线径错则 hood 通道卡不进。
- keeper 有 2026-11-05 前的坏版本（32 mm 高、孔松，某些浮动位置 hood 会穿窗掉落）——**以上游现在的
  STL 为准重打**，`build.py --check` 会抓住。
- 磁吸件采购判据不变：24-pin + CC 直通；磁力上限 6 N（8 N 出不来，2/10）。
- 鸭背磁头是**一直留在鸭子 USB-C 口上的**（不是坞的零件）。

## 2. 仿真链

### 2.1 场景与磁铁模型（`dock.py`）

- dock 全部凸体碰撞件由参数生成（`hood_pieces`/`static_pieces`），hood 是一个 **body + 三个 slide 关节**
  （z：−drop/+lift，y：±float，刚度 4 N/m 阻尼 3；x 默认刚性贴板）；`<exclude world-hood>` 防自碰。
- **磁铁是施力不是约束**：`mj_applyFT` 对 tip 与 hood 施大小相等方向相反的力。参数：
  `MAG_F=4 N` 轴向拉力、`MAG_RANGE=4 mm` 吸合范围、`MAG_LAT=3.5 mm` 横向捕获、`MAG_K=250 N/m` 对中。
  轴向力随 gap 线性衰减（1.25−gap/4，clamp 1.0）。
- `connected()` 判据（USB 上电 = 停）：gap ∈ (−4, 2) mm 且横向/竖向 |e| < 2.5 mm。
- 鸭背改动（`modify_robot`）：电池下移 10 mm、壳背加碰撞代理盒（contype 4 独立位，腿不受影响）、
  磁头 box + `tip_face` site、电源键圆柱。

### 2.2 trial harness（`docking_seated.py`）

- 复用 MicroDock 的 `docking.py`（场景/BAM/官方策略/磁铁），只换坐姿参数 + 坐下后交接 scoot 策略。
- tag 检测 = **真值 + 噪声**（σ：5 mm 纵向、3 mm 横向、1° 航向）——不是视觉。
- `SEAT_MU=0.45` 实测点（训练范围 0.25–0.7）。
- 两种睡眠脚本：`doze`（先伸腿 1.4 s→点头 1.6 s→稳住→头歪，腿舵机 1.6 s 后断电，头舵机保持 ~0.1 W）
  与 `limp`（腿瞬间瘫软、头 0.6 s 落到机械限位，然后全舵机断电）。
- `latency.py`：舵机目标晚 3–6 物理步（每步重采样）+ 关节速度/IMU 晚 1 控制步；官方策略与 scoot 策略
  可分别开关。**出坞策略没它就挣不脱**（10 次成 1 次）。

### 2.3 训练侧的接触力模型（`mdp_butt_walk.py`，与仿真版不同的三处）

1. `magnet_axial_force`：fmax 可变（课程）+ **阻尼挡块 k=2000 N/m、c=40**——挡块算在 gap **前推 10 ms**
   （lead_s）：整控制步保持一个力时，按步首状态算的挡块会回吐能量（1D 检查 0.05 m/s 撞进 0.061 撞出），
   前推 10 ms 后只回吐不足。注释明说「真实面是刚性的，弹簧挡块绝不能值得弹」。
2. `hood_ceiling`：躯干高度天花板 = z0 + 6 mm×(1+ramp)，port 出 21 mm 后随 7 mm 唇缘爬升，
   出 28 mm 后天花板消失——hood 是**用接触力模拟的活动顶盖**。
3. `hood_yaw_torque`：**航向停箍**——自由域 docked 时 3°，port 每出 11 mm 开 7°，出 20 mm 完全放开；
   超域后 k=2 N·m/rad 弹簧 + c=0.03 阻尼。**没有它会作弊**：磁铁只沿轴作用，原地转 30–45° 就把 port
   （在躯干后 5 cm）滑出轴线 7–15 mm，磁铁脱开而 progress 照付——第二轮策略全学会了「拧出去」还停不下来。

这条对我们价值最大：**把机械约束建模成「力 + 防作弊判据」，是能在 GPU 训练里（不用 MuJoCo 场景）近似坞的
做法**——4096 env 并行训练没法每个 env 建完整坞场景，作者就用三个解析力场替代，并明确记录每种近似
被钻空子的方式。

## 3. 训练链（补深研文档没写的部分）

- 任务构建：`make_microduck_butt_walk_env_cfg` = sitstand cfg 派生，`pop` 10 个 posture 奖励项 +
  2 个 event + 2 个 curriculum（凡是读「坐/站 flag」的全删），换 `UniformVelocityCommand`。
- **碰撞 geom 改名链**：导出 XML 只命名了脚掌 → `_seated_spec()` 先给所有 contype=1 未命名 geom 按
  `<body>_<k>_collision` 改名 → `CollisionCfg` 里脚掌 friction 1.0、其余按 env 抽（shared_random 全 env
  同值）→ `event_param_curriculum` 按 `it×24` 步推档（因为 24 步/迭代）。
- undock 状态是挂在 env 上的 dict（`_undock_state`），reset 抽 fmax/vx、第一步记 anchor/axis/z0/yaw0。
- 终止三条：>95 mm 站起、头偏离命令 >0.8 rad、倾角 >60°。
- 训练成本：4096 envs、H200、30 it/min、2000 迭代 ≈ 67 min；三个策略（dock/undock/实验版）≈ 3.5 h GPU。
  4090D 上大概率更慢（约 1.5–2×），单策略 ≈ 2–3 h、¥5–10 量级。

## 4. 与我们集成：实测结论与路线

### 4.1 兼容性（实测，非推断）

- `git apply --check`：**PASS**。干净 b02fdea 骨架（tasks/__init__.py 11892 B + tasks/mdp.py 329208 B）+
  patch，零冲突。两处 `__init__.py` hunk 的上下文（sitstand import 块、sitstand 注册块）逐字节一致。
- 验证产物留在 `_stage/duckpg/rlcheck/`（gitignore 内），patch 原件 `files/hardware_microdock-v2_training_butt_walk.patch`。

### 4.2 纯新增转写方案（开工清单，待用户点头才动）

1. `third_party/microduck_rl` 不动、submodule 不升级。在我们的包装层（如 `train_velocity_variant.py` 同级）
   新增：`mdp_butt_walk.py`（306 行 helpers，逐字照搬，只改 import 路径指向我们的 mdp）、
   `microduck_butt_walk_env_cfg.py`（324 行，import 从 `mjlab_microduck.tasks.mdp` 改为我们的模块）、
   任务注册（我们自己的注册方式，不 patch `__init__.py`）。
2. **必须换机器人 spec**：env cfg 里 `MICRODUCK_STANDUP_ROBOT_CFG + get_standup_spec()` 是 XL330 线
   ——我们要替换成 HD-1910 复刻线的 plant（`hd1910_kp8` 部署档、飞特、无 BAM）。这一步是真正的工作量：
   坐垫 geom 改名逻辑要对我们的 XML 重做（我们的导出是否命名脚掌、坐垫在哪几个 body 上要查）。
3. 坐姿基准全部重标：SIT keyframe、`SEATED_Z=0.065`、`SEATED_Z_SOFT=0.080`、`SEATED_Z_MAX=0.095`、
   `UNDOCK_PORT_B`/`UNDOCK_TOP_B`（鸭背几何）——官方数一个不能用。
4. 训练配置建议（按我们 AGENTS.md 分档）：探索 1024×2000（hip_limit=3、无 undock）→ dock 策略定稿；
   undock 版 4096×2000–2700 加 undock 环境变量组；选点外层 sweep（上游 iter1400/1100/2699 三个都是
   中途点，没有 best-by-eval）。
5. 磁力待定项：`UNDOCK_F` 课程上限 6 N 是「买得到的磁吸件实测」之前拍的——先买件测拉力再定课程终点。

### 4.3 风险清单（开工前必须心里有数）

- 🔴 patch 帮助函数依赖 sitstand env 的内部项名（`posture_pose_legs` 等 10 个 pop 键）——我们 plant 的
  sitstand（如果有）结构不同，pop 清单要按我们 cfg 重写；没有 sitstand env 就要先有它（官方 alpha_sitstand
  行为链需要）。
- 🔴 出坞策略对延迟敏感是**结构性**的（照训练延迟的节奏推）——我们彩排已证明延迟路径与训练不同源，
  出坞成功率必须在带延迟彩排里验。
- ⚠️ 实验版单策略「训练自检与仿真矛盾」未解释——复刻时先复刻两个分立策略，不碰实验版。
- ⚠️ 机械是按**官方 XL330 鸭**设计的：壳宽 64.6、背壳形状、电池位——我们 HD-1910 壳不同，
  hood/贴背面/滑轨落点要按我们的壳重算（`build.py --check` 的 keeper_fit/head_fit 照跑，参数改）。

## 5. 「先不训练」期间能做的事（按依赖排序）

| # | 动作 | 依赖真机？ | 产出 |
|---|---|---|---|
| 1 | 买磁吸件（24-pin+CC）+ 测拉力 | 否 | 定 `UNDOCK_F` 课程终点与 hood 磁力参数 |
| 2 | 打 `base` + `tag`（110 g，2.5 h） | 否 | 机械先动起来 |
| 3 | 量我们的 HD-1910 鸭背 8 参数（§1.1 表） | **要真机** | dock.py Params 全表替换 |
| 4 | 转写 butt walk 三件套为纯新增 + 配置测试 | 否 | 训练侧代码就绪（本地 pytest 全绿） |
| 5 | 确认/搭建我们的 sitstand env（pop 清单前提） | 否 | 坐姿交接能力 |
| 6 | 摸清我们 XML 坐垫 geom 命名现状 | 否 | 摩擦 DR 落点 |
| 7 | 打 board/hood/keeper（按替换后参数） | 依赖 #3 | 完整坞 |
| 8 | 训练三策略 + 彩排 | 用户点头 | scoot 策略（HD-1910 版） |

#1/#2/#4/#6 现在就能干；#3/#5 是真机和训练前的前置；#7/#8 等齐。

## 7. 补记：打印文件清单与零件数订正（2026-11-10 09:10）

**零件数订正（哈希核实）**：v1 与 v2 **同为 5 件**（base/board/hood/keeper/tag）——v1 的 `stl/` 里
本来就有 `microdock_board.stl`（hood 立在站立高度）。v2 是**换板**不是加板：两版 board 同为 280
三角面但几何不同（sha256 不同），hood/base/keeper/tag 四件与 v1 逐实体相同（`build.py --check`
布尔差 <1e-3 mm³ 强制）。

**打印文件已拷贝到 `cad/microdock-upstream-stl/`**（经 contents API 拉取 @052a2494dd）：

| 文件 | 大小 | 说明 |
|---|---|---|
| microdock_base.stl | 5.9 KB | 底座，平放 |
| microdock_hood.stl | 64 KB | 浮动 hood，**倒扣+网格支撑** |
| microdock_keeper.stl | 17.9 KB | 销扣（用上游最新版） |
| microdock_tag.stl | 43.9 KB | AprilTag，1.6 mm 换色 |
| microdock_v2_board.stl | 14.1 KB | v2 专用板 |
| microdock_v2_P1S.3mf | 41 KB | P1S 三盘工程（约 5h32/240 g PLA） |

许可 **CC BY-NC-SA 4.0**（不可商用）；HD-1910 前提与打印方向见该目录 `README.md`。
