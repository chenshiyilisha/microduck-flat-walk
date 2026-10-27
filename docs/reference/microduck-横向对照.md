# Microduck 横向对照：三个参照系与一份互补地图

> 前四份报告都是拿 Microduck 自己的代码量它自己。这一份换成外部尺子：
> 谁和它做同一件事、谁做得更完整、谁的短板正好是它的长板。
> 所有数据取自 2026-10-23 的 GitHub API / raw 文件，非二手转述。

---

## 0. 结论先行

**该参考，而且必须参考。** 但要先说清一件事，否则参照系会选错：

> **Microduck 不是原创项目，是 Open Duck Mini 社区路线的产业化收编版。**
>
> - `apirrone/Open_Duck_Mini`（4371★）创建于 **2024-05-16**
> - `pollen-robotics/microduck_rl` 创建于 **2025-12-06**，晚 19 个月
> - `pollen-robotics/microduck` 创建于 **2026-07-29**，晚 26 个月
> - Open_Duck_Mini 的 README 结尾原文：*"Thanks a lot to HuggingFace and Pollen Robotics for sponsoring this project!"*

所以两者不是竞争关系，是**同一条技术血缘的两端**：ODM 是社区长出来的（乱、但硬件全开），Microduck 是公司收编后产品化的（干净、但机械只给 STL 且禁商用）。

星数 10111 : 4371 的差距，**差的是产品化与传播能力，不是技术原创性**。这句话决定了下面对照的读法。

---

## 1. 三个参照系

| 项目 | 创建 | ★ | 代码许可 | 定位 |
|---|---|---|---|---|
| `apirrone/Open_Duck_Mini` | 2024-05 | 4371 | Apache-2.0 | 同源前身，**硬件全开** |
| `HybridRobotics/berkeley-humanoid-lite` | 2025-03 | 1992 | MIT / CC BY-SA 4.0 | 方法论上游，**$5000 级人形** |
| `kabilankb/isaaclab-microduck` | — | 13 | — | **直接冲着 Microduck 短板做的移植** |
| `pollen-robotics/microduck` | 2026-07 | 10111 | Apache-2.0（代码） | 本体 |
| `Rhoban/bam` | — | 560 | Apache-2.0 | **两者共用的执行器模型库** |

`Rhoban/bam` 是被 Microduck 的 `CLAUDE.md` 反复提到、但从未在显眼位置点名的那个依赖。它是理解整件事的钥匙。

---

## 2. 参照系一：Open_Duck_Mini（同源前身）

### 2.1 硬件可复现性 —— Microduck 最大的真空

| 维度 | Open_Duck_Mini v2 | Microduck |
|---|---|---|
| 机械设计源 | **Onshape 可编辑文档**（公开链接） | **无 CAD，仅 47 个 STL** |
| 从 CAD 到仿真的路径 | `onshape-to-robot` 自动导出 URDF/MJCF | 手写 MJCF，STL 靠反推 |
| 质量标定 | 用切片软件按填充率估算，覆盖 CAD 名义值 | 未公开方法 |
| BOM | Google Sheet **+ 中文飞书镜像版** | 无公开 BOM（卖整机） |
| 装配/打印指南 | 有（`docs/print_guide.md`、`assembly_guide.md`，后者标注 incomplete） | 无 |
| 机械许可 | 随仓库 | **CC BY-SA-NC（禁商用）** |
| 整机成本 | BOM < **$400**，42 cm，**飞特 STS3215** | **$399 整机**，25 cm，XL330 |

**这一条是真正的"不足"，而且是结构性的。**

不是"少放了文件"，是**两种商业姿态的差别**：ODM 选择"你可以在 CAD 里改任何一个连杆"，Microduck 选择"你买我的成品，STL 给你修打印件就好"。加上 NC 条款，**任何基于 Microduck 机械的二次产品都走不通**，而 ODM 和 BHL 都允许（SA / MIT）。

### 2.2 执行器 —— 我上一份报告里有个判断需要修正

上一份说「飞特路线最硬的墙是 BAM 里没有对应电机模型，整个执行器要重新辨识」。**这个说法对 HD-1910 成立，但把飞特整体判死是错的。**

`Rhoban/bam` 的 `bam/params/` 目录下已有 **9 款**已辨识电机：

```
erob80_100   erob80_50   feetech_sts3215_7_4V
mx106        mx64        waveshare_st3025
xl320        xl330
```

**`feetech_sts3215_7_4V` 就在里面** —— 而这正是 Open_Duck_Mini 用的电机。也就是说：

- 换 **HD-1910** → 不在清单，需自行辨识（原判断成立）
- 换 **STS3215** → **官方参数现成，且 ODM 已用它跑通完整 sim2real**（判断需修正）

### 2.3 参数级对照：为什么"不能抄参数"这句话有硬证据

同一 `m1` 模型下，两款电机的辨识结果（`bam/params/*/m1.json`）：

| 参数 | XL330（Microduck） | STS3215-7.4V（ODM） | 比值 |
|---|---|---|---|
| `kt` 转矩常数 | 0.371 | 1.178 | **3.18×** |
| `R` 绕组电阻 | 3.452 | 2.479 | 0.72× |
| `armature` 转子惯量 | 1.609e-3 | 2.608e-2 | **16.2×** |
| `friction_base` 库仑摩擦 | 0.0191 | 0.0515 | 2.7× |
| `friction_viscous` 粘性摩擦 | 3.92e-3 | 5.99e-2 | **15.3×** |
| `command_delay` 指令延迟 | 5.93 ms | 1.05 ms | **0.18×** |
| `q_offset` 零点偏置 | +0.0235 | −0.0506 | **符号相反** |
| 独有字段 | — | `max_velocity=5.29`、`error_gain_ratio=1.005` | — |

三点读法：

1. **转子惯量差 16 倍、粘性摩擦差 15 倍** —— 这是完全不同的动力学系统。谁把 XL330 的参数套到 STS3215 上，训出来的策略连"仿真正确"都做不到，谈不上 sim2real。
2. **`command_delay` 差 5.7 倍** —— 飞特快得多。但注意别混淆：Microduck 配方里的 `delay_lag=3–6 个控制周期`（50 Hz 下 60–120 ms）是**整条链**的延迟，不是舵机内部这 5.93 ms。两者是不同层级的量。
3. **`q_offset` 符号相反** —— 这类东西一旦抄错，机器人第一个动作就往反方向走。**这类参数只能辨识，不能推理。**

### 2.4 奖励路线：两种范式的互补，这是最有价值的一条

| | Microduck | Open_Duck_Mini |
|---|---|---|
| 范式的核心 | **奖励工程**（人工设计步态项） | **模仿学习**（参考动作跟踪） |
| 具体做法 | 空中时间奖励、接触频率惩罚、头部姿态 EMA | Disney BDX 论文的 imitation reward |
| 需要的额外工程 | 无（纯奖励设计） | **参考动作生成器**（parametric walk engine → `polynomial_coefficients.pkl`） |
| 典型失败模式 | **策略钻空子**：躺着抖腿刷空中时间；坐着/躺平刷门控奖励 | 行为上限被参考动作框死；参考动作不好则学不出来 |
| 已知代价 | 三次被刷爆、两次整轮训练作废（见上一份报告） | 要先做一套运动生成器 |

**这一条是我对照下来觉得最该讲清楚的：**

> 两种范式的本质差别，是**你把"什么是好步态"这个知识放在哪里**。
> Microduck 把它放在**奖励函数里**——所以它必须自己堵掉所有漏洞，堵的过程就是那三次翻车。
> ODM 把它放在**参考动作里**——漏洞问题天然缓解（参考动作不是躺着的），但你能走出的样子被那个参考框住了。
> **它们不冲突，而且 Microduck 完全可以在现有 61 维观测契约上叠加 imitation reward**（观测里已经有 `head_pose(4)`、`body_pose(6)`，正好是参考动作需要的通道）。

---

## 3. 参照系二：Berkeley Humanoid Lite（方法论上游）

$5000 级、模块化 3D 打印减速箱的开源人形，有 arXiv 论文（2504.17249）。

它的价值不在"更大"，在**它把 Microduck 缺的那半条工程链补全了**：

- `source/berkeley_humanoid_lite_assets/` 里同时有 **URDF + MJCF + USD 三种描述**，以及**从 Onshape 项目导出这些文件的脚本** —— 也就是 2.1 里说的那条"可编辑"链路的完整示范
- `source/berkeley_humanoid_lite_lowlevel/` 明确界定"上真机只需要这个子模块" —— 部署边界划得比 Microduck 清楚（后者策略、安全、更新器、检测散在多个 crate）
- 目录结构直接照 Isaac Lab 约定组织，每个子模块可独立安装
- 自带 **mocap 遥操作** —— Microduck 没有遥操作数据采集能力，这意味着它无法自己生成参考动作（正好对上 2.4：Microduck 只能走奖励工程，因为它没有采集参考动作的手段）

**许可对照（最实际的一条）**：BHL 资产是 **CC BY-SA 4.0**，Microduck 机械是 **CC BY-SA-NC**。差一个 `NC`，决定了"能不能做成产品"。

---

## 4. 参照系三：isaaclab-microduck（反面证据，含金量最高）

有人把 Microduck 移植到了 Isaac Lab 3.0 + Newton（MJWarp），并留下一句极重的话：

> **"Locomotion is not working: the policies converge to standing still, and the cause is still under investigation."**
>
> **"Treat everything here as a sim milestone, not a deployable policy: the BAM actuator, observation delays and encoder bias are not yet ported."**

这是本次对照里**唯一一个受控实验**：同一个机器人、同一套任务定义，只把三样东西去掉 —— BAM 执行器模型、观测延迟、编码器偏置 —— 结果 locomotion 直接塌成"站着不动"。

**它给出的结论比任何文档都硬：**

1. 这三样不是"锦上添花的 domain randomization"，**是 locomotion 能否成立的必要条件**。我前几份报告说"执行器保真度是 sim2real gap 的大头"，这里拿到了反面验证 —— 去掉它，连仿真里都学不会走。
2. Microduck 那份 `CLAUDE.md` 里"每一条跳过都会产出在 viewer 里完美、上真机就废的策略"，实际上更严重 —— **跳过连 viewer 里都过不了**。
3. 它顺带补了 Microduck 官方没明写的观测契约细节：

```
61D = 48D 本体感知 + 13D 指令块 [twist(3), head_pose(4), body_pose(6)]
```

并且立了几条 invariant，跟前面几份报告里挖到的原则完全同源：

- **"Measure behaviour, not reward"** —— 奖励总分在站着不动时照样涨，所以必须记 `kick_success_rate` / `rally_passes` / `speed_tracking_ratio`。这正是我上一份报告总结的"只奖进展不奖状态"的工程落地形式。
- **双机器人任务用 frozen partner，不共享网络** —— 共享网络会把观测翻倍，策略直接不可部署。这个约束在官方仓库里没写明，是移植者的贡献。
- **未驱动关节命名 `passive_*`，所有选择器用 `^(?!passive_).*`** —— 呼应 Microduck 的齿隙被动铰链设计。

**它也是 Microduck 生态正在补齐的证据**：官方只支持 mjlab/MuJoCo Warp（强制 CUDA），第三方已经在往 Isaac Lab 上铺。它同时提供了 BallKick / BallRally / RunParallel 三个官方没有的任务。

---

## 5. 互补地图：谁缺什么

| 能力 | Microduck | Open_Duck_Mini | Berkeley Humanoid Lite |
|---|---|---|---|
| 可编辑 CAD | ✗ 仅 STL | ✓ Onshape | ✓ Onshape + 导出脚本 |
| 公开 BOM | ✗ | ✓（含中文镜像） | ✓ |
| 机械许可可商用 | ✗ NC | ✓ | ✓ |
| 执行器物理模型 | ✓ BAM（XL330） | ✓ BAM（STS3215） | ✓ 自带辨识 |
| 硬件成本 | $399 整机 | <$400 BOM | <$5000 |
| **表达/情绪系统** | **✓ 14 套 + 参数化合成声音** | **✗ 官方自述缺** | ✗ |
| **实时运行时的工程约束** | **✓ Rust / 8 ms 硬预算 / 加载时验证** | ✗ Python on Pi Zero 2W | 部分（lowlevel 子模块） |
| 模仿学习 / 参考动作 | ✗ | ✓ Disney BDX | ✓ mocap 遥操作 |
| 多任务 / 多机器人 | ✗ | ✗ | 部分（遥操作臂） |
| 评测协议 | **✓ arena / challenges（33 跑、Docker 复测）** | ✗ | ✗ |
| 失败记录 | **✓ 注释级 + wandb run id** | ✗ | ✗ |

这张表是本报告的核心结论：

> **Microduck 的不足集中在"可复现性"（CAD、BOM、许可、成本）；它的长处集中在"可信度"（失败记录、评测协议、实时工程约束）和"表现力"（情绪系统）。**
>
> 而且这个分布不是巧合 —— **它是个产品，不是个研究平台**。产品需要的是"你信它能跑"和"它好玩"，不需要"你能改它"。

值得注意的是 ODM README 里那句自述：*"Still missing the 'expression' features"*（LED 眼、摄像头、扬声器、麦克风都还是计划）。**Microduck 唯一完全原创、且无对照物的部分，就是那套表达能力** —— 这也是为什么前四份报告里，只有"情感"那一层是它独有的。

---

## 6. 该怎么用这份对照（三条可执行路径）

### 路径 A：想改机械 / 做自己的变种
**放弃 Microduck 的机械，用 Open_Duck_Mini。** 理由不是成本，是 `NC`：
- ODM：Onshape 源 + `onshape-to-robot` 一键出 URDF/MJCF，改完直接进仿真
- Microduck：STL 不可参数化，改一个连杆长度就要重建整条运动学链，且 NC 禁商用

### 路径 B：只是想把 sim2real 跑通（本地最省）
**技术栈照抄 Microduck，电机选 BAM 清单里的。** 具体：
1. `BAM` 的 9 款电机清单是你的**选型白名单** —— 在清单里选，省掉整个系统辨识环节
2. 想省钱又要现成参数 → **STS3215**（ODM 已跑通，参数官方有）
3. 训练栈用 mjlab（官方配方完整、踩坑记录最全），**不要**急着换 Isaac Lab —— 参照系三证明了换栈会丢掉 BAM/延迟/编码器偏置，而这三样一丢 locomotion 就不成立

### 路径 C：想把步态质量提上去
**在 Microduck 现有栈上叠加 ODM 的 imitation reward**，这是两条路线里唯一"能拿两边好处"的做法：
- 观测契约已经现成：61D 里有 `head_pose(4)` + `body_pose(6)`，正好是参考动作的通道
- 参考动作生成器要自己做（`Open_Duck_reference_motion_generator` 是 ODM 的现成实现，但绑定 42 cm 尺度，25 cm 要重标）
- 好处：微杜的奖励漏洞问题（躺着抖腿刷空中时间）被参考动作天然抑制，不必再逐项打补丁

### 不要做的两件事
1. **不要把 XL330 的参数套到别的电机上** —— 2.3 那张表就是反例，惯量差 16 倍
2. **不要指望 isaaclab-microduck 现在能用** —— 作者自己标注尚未移植 BAM/延迟/偏置，locomotion 未解决；但它的 `frozen partner` 和多任务定义可以借

---

## 7. 一句话收尾

前四份报告回答的是「Microduck 做对了什么」。这份补充回答的是**「它没做的那些，是不是别人已经做了」**——

答案是：**硬件那条线（CAD / BOM / 许可）别人早就做全了，它是主动放弃的；技术那条线（BAM / 延迟 / 偏置）别人试过简化，结果直接失败，它是对的。**

一个主动放弃，一个被动验证。这两个结论都比"它很厉害"有用得多。

---

*数据来源：GitHub REST API（repos / trees / contents）、`raw.githubusercontent.com` 原文、`Rhoban/bam` 的 `bam/params/*/m1.json`。检索日期 2026-10-23。*
