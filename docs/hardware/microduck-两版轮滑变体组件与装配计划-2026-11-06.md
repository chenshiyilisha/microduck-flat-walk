# 两版 MicroDuck 轮滑变体组件与装配计划（Radxa / Orange Pi）

_2026-11-06。回应「轮滑鞋组件可加到计划中」。所有条目均回一手资料核对，出处随文标注。_

## 0. 一句话结论

**轮滑变体是官方上游支持的正式形态，不是第三方改件。** 走路版（walk）与轮滑版（roller）的差别集中在**脚踝以下**：换 V1 备选踝、卸脚部、装 4 轮 2 刀片配 4 颗轴承。两版主板（Radxa / Orange Pi）机械零改动，轮滑变体对两版完全相同；软件侧用 `action_scale 0.8` + roller 专属策略，且**走路件与轮滑件不可混装**。

---

## 1. 轮滑变体存在的官方证据（先查资料，结论如下）

| 证据 | 出处 |
|---|---|
| 上游仿真模型 `robot_allcollisions_rollers.xml`（轮滑版，14 主动关节 + 4 被动轮） | 主仓 `software/training/src/mjlab_microduck/robot/microduck/` |
| 训练配置 `microduck_velocity_rollers_env_cfg.py`：注释明写 "14 actuated joints + 4 passive wheels (passive_{L,R}{F,R}wheel), two per blade"，且 "the roller_blade bodies were merged into the ankles" | 同目录 `tasks/`，2026-07 模型结构 |
| 5 个 roller 策略名：`roller` / `roller_crouch` / `roller_spin` / `roller_standup` / `roller_swizzle` | `software/training-studio/training_studio/pretrained_models.json`（48 处命中） |
| 实机演示：`assets/demos/2026-10-24-roll-and-rise.mp4`（滚行后站起，另有 walking 对照） | 主仓 `assets/demos/` |
| BOM 设「打印件与轮滑变体」专节，数量来源表指向 `robot_groundcontact_rollers.xml` | `BOM.md:425-429`、`BOM.md:449` |
| v2.1 把独立轮辋+轮胎合并为 TPU 合体轮胎 | CAD 仓 README「飞特 v2.1 改了什么（2026-09-25）」 |
| v2.1 合体轮胎 / 滚轮叶片 / 轮滑轴承「用于轮滑变体」；**走路用件和轮滑替换件不能混用** | CAD 仓 README 打印说明；`BOM.md:429` |

→ 依据充分：可以进入计划阶段。

---

## 2. 走路版 → 轮滑版替换对照（BOM 口径，57 项基线上改动）

### 2.1 脚踝以下：换件（BOM 第 20–29 项）

| BOM 项 | 名称 | 数量 | walk 版 | roller 版 | 依据 |
|---|---|---:|---|---|---|
| 24/25 | 脚踝左/右（走路踝） | 1+1 | ✅ 用 | ❌ 卸 | roller XML 无 `ankle_left/ankle_right` 体，只有 `ankle_l_v1/ankle_r_v1`（`robot_allcollisions_rollers.xml:160,336`） |
| 26/27 | 脚踝左/右（V1 备选踝） | 1+1 | ❌ 不用 | ✅ 换装 | 同上；BOM 原列「V1备选」 |
| 20/21 | 左/右脚 foot_left/foot_right | 1+1 | ✅ 用 | ❌ 卸 | roller XML 无 foot 几何（仅 2 处 `left_foot/right_foot` 框架 site，无 mesh） |
| 22/23 | 左/右脚底 sole_left/sole_right | 1+1 | ✅ 用 | ❌ 卸 | 同上，roller XML 无 sole 几何 |
| 28 | 合体轮胎 | 4 | ❌ 不用 | ✅ 用 | v2.1 由 rim+tire 合并（CAD 仓 README）；roller XML 每腿前后两轮：`tire/tire_2/tire_3/tire_4` + `rim` geom ×4 + `passive_{LF,LR,RF,RR}_wheel` 关节（axis 0 0 1） |
| 29 | 滚轮叶片 roller_blade | 2 | ❌ 不用 | ✅ 用 | 2026-07 模型起刀片合并进脚踝本体（`microduck_velocity_rollers_env_cfg.py:124` 注释）；BOM 列独立叶片 ×2 |
| 33 | 轴承滚轮 bearing_roll | 2 | ✅ 用 | ✅ 用 | ⚠️ **这是 hip roll 轴承压盖（23×3×40 mm 带 Ø≈18 孔的打印件），不是轮滑轴承**，两版都要，勿与外购件 #16 混 |
| 外购 #16 | 轴承 6×12×3 | 4 | 日常不用 | ✅ 轮滑鞋轴承，每轮 1 颗 | BOM 原备注「轮滑鞋用轴承」；roller XML 每个轮对一根过轴 |

### 2.2 其余 49 项：不动

33 项打印件中除 2.1 覆盖的 10 项（脚踝×2 对、foot×2、sole×2、合体轮胎、滚轮叶片）外，其余（躯干、腿、颈、头、壳、电机支架、电源支架、香蕉锁扣、轴承滚轮压盖等）**两版通用、数量不变**。「电机支架」「电源支架」是躯干装载件，**不是**轮滑件——曾疑此，MXDL XML 证伪，此处写明防再查。

### 2.3 量级校验（防「读数矛盾」）

BOM 全目录 33 项的实体合计 **42 是「主目录」（含两套踝件与轮滑件）**，不是一种构型的实际打印量。按构型拆：

- **走路版实际打印 = 34**：42 − V1 备选踝 2 − 合体轮胎 4 − 滚轮叶片 2 = 34（用脚踝左/右 + foot + sole）。
- **轮滑版实际打印 = 36**：42 − 走路踝 2 − foot 2 − sole 2 = 36（用 V1 备选踝 2 + 合体轮胎 4 + 滚轮叶片 2 + 其余 28 项单件）。
- 两构型差 2 件（轮滑版多 2），BOM 总项数恒为 33 / 57，**这是主目录口径不是缺件**。外购件 24 项不变（轴承已含）。装机时按各自 manifest 逐项点数。

---

## 3. 3MF / CAD 中的轮滑件对号（内容已确认，命名映射待人工核）

3MF（`microduck-飞特版-BambuStudio2026-10-20.3mf`，v2.2）43 build 实例 / 33 唯一网格，轮滑件候选已由几何特征定位：

| 3MF 网格 | 引用次数 | bbox (mm) | 特征 | 对 BOM | 置信度 |
|---|---:|---|---|---|---|
| `object_297` | **×4** | 30×30×7.6 | 轮形盘体 | 合体轮胎 ×4 | 高（数量、尺寸形态吻合） |
| `object_281` | ×2 | 23×25.8×20.5 | 带轮安装耳的踝件 | V1 备选踝 ×2 | 中（形态吻合，命名未留） |
| `object_301` | ×2 | 23×40×3.5 | 薄长板片 | 滚轮叶片 ×2 | 中（3.5 mm 薄片符合刀片形态） |

**未闭合项（不硬推）**：3MF 容器无 per-object 命名（Bambu 工程格式，已实测），三套 UUID 互不相交，**无法自动把网格映射到 BOM 中文名**。对号需拿 5 张打印盘图逐项核——沿用《两版整机装配完整性核对》§7 第 3 条的人工对号流程，`PARTS_INDEX.csv` 已给 bbox/面数/引用次数。

⚠️ **一处读数矛盾待人工核实**：CAD 仓 README 称「10-20 工程内仍保留独立轮辋 4 个、轮胎 4 个（非 v2.1 合体轮胎）」，但实测 3MF 里轮类只有 `object_297` 一个网格被引用 ×4——没有第二个 rim 网格（若独立轮辋存在应出现另一个 ×4 网格）。两种可能：① README 未同步实测；② rim 与 tire 已被并成同一网格。**装机前必须打开盘图看轮件形态再定 BOM 28 打什么文件。** 这正是「读数与实测矛盾时以实测为准、标出再核」的实例。

---

## 4. 材料与打印要求

| 件 | 材料 | 说明 |
|---|---|---|
| 合体轮胎 | **TPU**（v2.1 指定） | 原 BOM 材料栏仍写 PLA，属未同步；跑轮必须有橡胶抓地，PLA 会打滑（CAD 仓 README「打印说明」节） |
| 滚轮叶片 | PLA（原表），建议核对 CAD 仓打印说明 | 承轮载荷，原表 PLA |
| V1 备选踝 | PLA（原表） | 与走路踝同材料 |
| 轮滑轴承 | 外购 `6×12×3` ×4，BOM 备注「轮滑鞋用轴承」 | 过轮轴；roller XML 轮子为被动关节（axis Z），需轴承才能转 |
| 其余 29 项打印件 | PLA（原表） | 两版通用 |

打印通道：CAD 仓 Releases 的 **v2.1 源文件包**取合体轮胎（README 明示「若制作轮滑变体，请从 v2.1 源文件导出合体轮胎，按 TPU 切片」）；10-20 3MF 工程仅用于其余件的排盘与备料核对。

---

## 5. 装配顺序（轮滑步：在走路版 §4 的 01→15 上替换末段）

走路版说明书层级不变（01 躯干 → 左右腿 → 颈头 → 右腿末段），仅在「踝脚」步做替换：

```
01 躯干主体 …（前段 02-14 与走路版相同，至小腿装完）
05/12 踝步：装 V1 备选踝（ankle_l_v1/ankle_r_v1，替代 ankle_left/right）
06/13 叶片：滚轮叶片装入踝下（2026-07 起仿真已并入踝体，实物仍按 BOM 独立叶片装）
07/14 轮组：每腿前后两轮——先压 6×12×3 轴承入轮孔，再过轴装轮
         （左腿 passive_LF + passive_LR，右腿 passive_RF + passive_RR）
         —— 轮为被动件无舵机，装后用手转验顺滑
     （无 foot/sole 安装步）
```

硬约束（沿用说明书 + 本轮补充）：
- 每完成一关节转动测试；舵机先归中位再锁紧；
- **轮滑件与走路件分盘管理**（TPU 与 PLA 分开），防混装；
- 首次接通前查线束极性/绝缘；轮装好后整机离手推进试滚，确认无卡阻再上电。

---

## 6. 软件侧差异（换策略即用，机械零改动）

| 项 | walk | roller | 出处 |
|---|---|---|---|
| `action_scale` | 0.9 | **0.8** | `docs/hardware-teardown.en.md:564` |
| 主动/被动关节 | 14 主动 + 脚部固连 | 14 主动 + 4 被动轮（`passive_{L,R}{F,R}wheel`，每刀片 2 轮） | roller XML + `microduck_velocity_rollers_env_cfg.py:8` |
| 轮轴承摩擦 | — | 训练含 `dr.dof_frictionloss` 轴承课程（`ENABLE_WHEEL_FRICTION_RANDOMIZATION=True`），部署姿态要匹配 | 同文件 :18-19, :42 |
| 站起策略 | — | `roller_standup`：站高目标 `ROLLER_STAND_Z=0.138`（实测 0.1407 收口），腿关节索引 `[0-4, 11-15]`，已由 `test_roller_standup_cfg.py` 锁死（无轮模型的 `[0-4,9-13]` 索引在轮滑模型上会指到轮子，勿照抄） | `software/training/docs/roller_standup_policy_summary.md:15,27` |
| 可用策略 | walking 系 | `roller` / `roller_crouch` / `roller_spin` / `roller_standup` / `roller_swizzle` | `pretrained_models.json` |

部署链不变：`export.py`→ONNX→`infer_policy.py`→`publish`→`robotctl policy load`（obs 61 / act 14 / 50 Hz 相同），仅策略名与 `action_scale` 变。

**⚠️ 线别警示（读数矛盾清算后口径，详见验收清单 §6）**：轮滑变体不切机器人线——装机排错时**先判线别再查表**：

| 线别 | 主控/协议 | 开机硬校验内容 | 文档来源 |
|---|---|---|---|
| **本机器人（hd191m 线，Radxa + HD-1910）** | HD-1910 原生 FT-SCS | **不查 EEPROM reg6/reg33/reg9/reg11**；校验固件元数据快照 `row[0]==3 … row[33]==4`（"HD1910M mode-4"） | `robotd`：`hd191m/microduck` |
| DuckBuddy 线（Orange Pi A733 + HL-2915 + feetech_hls/500k） | feetech_hls | EEPROM reg6=1 / reg33=0 / reg9=0 / reg11=4095（`checked, not corrected`） | `DuckBuddy-main` robotd |

**两线 JSON 配置不通用**（hd191m 键为 `reference_native/installation/imu_bus/servo_gain_profile`；DuckBuddy 键为 `[bus] servo` 等）：串用 = 电机乱躦。两版主板（Radxa UART 1M / Orange Pi 500k）在轮滑变体上**无任何额外改动**——机械件、固件协议、上电校验清单全部沿用"本机器人线"。

---

## 7. 采购/打印增量清单（在两版 57 项基线上）

| 动作 | 件 | 数量 | 备注 |
|---|---|---:|---|
|  print 新增 | 合体轮胎.stp（TPU） | 4 | 来源：CAD 仓 v2.1 源文件，勿用 10-20 3MF 内形态（见 §3 矛盾项） |
| print 新增 | 滚轮叶片.stp | 2 | CAD 一致 |
| print 换件 | 脚踝 V1 备选 ×2 | 2 | 替代走路踝（1 对换 1 对） |
| print 停用 | foot×2、sole×2、走路踝×2 | — | 轮滑版不装；保留备件，**禁止混装** |
| 外购 | 轴承 6×12×3 | 4 | 已在 BOM 外购 #16，直接用 |
| 外购 | 其余 23 项 | — | 零变化 |

成本增量：仅 TPU 耗材 + 4 颗轴承（约 ¥4），其余零新增。

---

## 8. 待核清单（写明，不假装闭合）

1. **§3 rim/tire 合并状态**：10-20 3MF 到底是合体轮胎还是独立 rim+tire——开盘图核，编号 `object_297` 的唯一轮形网格是判据。
2. **V1 踝 `object_281`、叶片 `object_301` 与 BOM 项名的对号**——随 43 vs 42 人工对号一起做。
3. **TPU 合体轮胎的尺寸公差/过盈**：v2.1 源文件 STEP 未拆，装机首轮打样后按轴孔手感定过盈量。
4. **轮滑版 kit STL**：`cad/build_two_version_kits.py` 目前只产 walk 版两版 kit；若需轮滑版可视化 kit，在生成器里加「卸 foot/sole + 踝换 V1 + 加轮组」的变体参数（机械上是纯装配树变化，几何均已在 3MF 中）。
5. `ROLLER_STAND_Z=0.138` 是训练值，台架轮径/轴距差会漂移——实测从坐姿起立高度再校一次（与走路版 `fall_gravity_z` 同思路）。

---

## 9. 相关文档索引

- 整机核对：`microduck-两版整机装配完整性核对-2026-11-06.md`（§3 两版差异、§4 装配层级、§7 下一步）
- 上电验收：`microduck-Radxa上电验收清单-2026-11-06.md`（轮滑变体硬件零改动，直接沿用）
- 资料审计：`microduck-资料溯源与结论审计-2026-11-06.md`
- 依据：主仓 `BOM.md`、CAD 仓 `README.md`、`robot_allcollisions_rollers.xml`、`microduck_velocity_rollers_env_cfg.py`、`roller_standup_policy_summary.md`、`docs/hardware-teardown.en.md:564`
