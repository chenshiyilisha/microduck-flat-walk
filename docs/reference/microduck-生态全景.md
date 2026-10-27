# Microduck 生态全景：一个前硬件期的军备竞赛

> 第六份报告。前五份是拿放大镜看 Microduck 的源码，这一份是退到卫星视角看它周围。
> **结论先说：这里已经没有"要不要深挖"的问题了。我前五轮的视角是错的——我把它当成一个代码库在挖，
> 但它实际上是一个平台的引爆点。** 数据取自 2026-10-23，来源为 GitHub API 与社区清单原文。

---

## 1. 规模：240 个收录项目，46 个独立训练栈

`joeynyc/awesome-microduck`（162★，79 KB）收录 240 个条目（已排除目录项）：

| 分类 | 条目 |
|---|---|
| **Simulation and Training**（仿真与训练） | **46** |
| **Apps and Ports**（应用与移植） | **47** |
| **Policies and Skills**（策略与技能） | **39** |
| **Agent Tools and MCP** | **23** |
| **Hardware and Fabrication**（硬件复刻） | **23** |
| Official（官方） | 18 |
| Documentation | 11 |
| Datasets and Benchmarks | 7 |
| Articles / Videos / Community / Lineage | 24 |

GitHub 侧搜索 `microduck` 命中 460 个仓库（含 `in:name,description,readme` 则 774 个，其中混有大量无关项目）。**46 个训练栈移植**是不同的团队各自把同一套 mjlab 配方搬到别的后端上：

- **Isaac Lab 三套**：`5usu`（含 BAM/backlash + RSL-RL，walking/kick/parkour）、`kabilankb`（Newton MJWarp）、`dreamerarun`（PhysX，**37 个环境**，BAM M6）
- **Genesis 两套**：`Macmachi`（AMD/ROCm，actuator model **逐位对齐上游**）、`green-creeper`（TCP `duck-body` server，真 daemon 用 `--sim` 连）
- **JAX/MJX**：`noahfarr/microdux`（14 个官方任务全注册，reward 逐项对上游校验）
- **纯 CPU**：`tailong-wu/microduck-mjbatch`（C++ 线程池跑数千实例，**8 vCPU 2 小时 36 分**训出走路，零摔倒）
- **Intel 集显/Arc**：`guang384/mjlab-sycl`（一条 overlay 命令让 CUDA-only 路径跑在 Intel GPU 上）
- **Apple Silicon 两套**、**AMD ROCm 两套**、Unity/团结、Godot/Jolt、浏览器 WASM、MotrixSim、UniLab……

**这意味着我上一轮说"没有 CUDA 就堵死"是彻底错的。** 至少 7 条替代路径，其中最便宜的一条是纯 CPU 两个半小时。

---

## 2. 决定性事实：机器还没发货

清单的 "Ecosystem Status" 写得极清楚：

> **"The robot is pre-hardware: pre-orders are open, shipping is targeted for December 2026, and almost nobody outside Pollen has a physical unit yet."**
>
> "**Hardware-facing tools are pre-validation.** MCP servers, gateways and CLIs... none listed here has been exercised on a shipped unit."

今天是 2026-10-23，**发货目标是 12 月**。所以：

**整个 240 个条目里，绝大多数标着 *sim-only*。这是一个前硬件期的军备竞赛——所有人都在没有真机的情况下，在仿真里抢占位置。**

这一条解释了前面所有的现象：
- 为什么有 46 个训练栈移植 → 没有真机，只能在仿真里卷
- 为什么官方要搞 Arena + golden vectors + Docker 复测 → 在没硬件的时候建立可信度
- 为什么清单要给每条标 *sim-only* → 作者在诚实地区分"跑过"和"没跑过"

**也修正了我前几轮的一个隐含错误**：我讨论的"复刻成本""实价询价"，全部是社区自攒硬件，不是官方整机。`fanduck`、`AI-FanGe` 那些"复刻成功"是拿公开 STL + 自己设计电控做出来的，跟 12 月发的整机不是同一个东西。

---

## 3. 我上一轮说的"不足"，逐条核查

上一份报告列了 Microduck 的缺口，并用 ODM/BHL 做对照。现在看真实生态，**结论要改一半**：

| 上轮判断 | 实际情况 | 判定 |
|---|---|---|
| 「无机机械 CAD，只有 47 个 STL」 | `fanhao375/microduck-replica-cad`：**56 个可编辑 SolidWorks 零件/装配体 + 21 页装配手册**；`lingzolabs`、`MengyangGao` 各有 FreeCAD 版；`qianen6` 做了"证据可追溯"的分层重建 | **判断错，被人补了** |
| 「`imu_to_dxl` 板没开源」 | `avanx/microduck_imu_to_ttl`：LSM6DSV16X + 半双工总线 + 自带稳压与收发缓冲，**原理图公开，同步上 OSHWHub**；`jyg9/microduck-community-kit` 另有一套（含舵机总线 hub、飞特调试器） | **判断错，被人补了** |
| 「飞特路线要重新辨识，会堵死」 | 至少 **5 个**不同实现：`zhuoligetu123`（HD1910M + Radxa ZERO 3W + BNO08x，四模型）、`Ley-WL`（HD1910M + 公布的 1910 M6 参数，locomotion/recovery/十拍舞）、`DuckBuddy`（HL-2915 + Orange Pi，策略重训）、`microduck-s288`（S288 + Pi Zero 2W，**无自定 PCB**）、`dukki`（Unitree J288） | **判断错一半**：辨识仍要做，但路早就通了 |
| 「没有 CUDA 就堵死」 | 见第 1 节，至少 7 条路 | **判断错** |
| 「只在 MuJoCo Warp 上训练」 | Isaac Lab ×3、Genesis ×2、JAX、Unity、Godot、WASM、MotrixSim、UniLab、纯 CPU | **判断错** |
| 「无视觉/无导航」 | `quacknav`（建图/定位/命名地点）、`AlexBodner/microduck-tracking`（目标锁定追球）、`microduck-vision-soccer`（头摄前锋 vs 单目门将，98/100 进球） | **判断错** |
| 「机械 CC BY-SA-NC 不能商用」 | 清单原文：**"The hardware is not open source (no BOM, CAD or PCB files)"** | **判断对，且比我说的更硬** |
| 「表达系统是它独有的」 | 官方 `microduck-emotions` dataset 是 Apache-2.0，而且**是为了和 Reachy Mini 一起演场景**才发布的；社区有 `microquack`（程序化 droid 语音）、`Quackify`（四声部和声） | **判断对** |

**七条里错了六条。** 错的根因是同一个：我上一轮只对照了 ODM 和 BHL 两个项目，就下了"没人做"的结论。实际上这是 240 个项目的生态，我抽样了 2 个。

---

## 4. 社区发现的官方问题（本报告最有价值的部分）

这个生态最意外的一点：**社区比官方更早发现了官方的 bug，而且都写下来了。**

### 4.1 `air_time` 奖励门控错了 —— 官方违反了它自己定的原则

`Qi-hub-dot/microduck-locomotion-diagnosis` 复现了官方**至今无回复的 issue #46**（走路任务训不出来，收敛到站着不动），在单张 RTX 4070 上得到 `error_vel_xy` 0.42（报告者 0.43）。报告者用 4 张 L4 跑了 7 组对照实验都没解决，这份诊断找到了他漏掉的三条：

1. **`air_time` 奖励门控在"是否存在指令"，而不是"机器人是否真的移动"** → 被指令前进的策略可以**原地踏步**拿到它。而这是奖励集里**权重最大的正项**。改成按实际达成的运动门控后，`error_vel_xy` 从 0.43 → 0.35。
2. **横向漂移达到前进速度的两倍**，而跟踪奖励对两轴等权。横向误差加权 3 倍后，漂移降到 1/5，`error_vel_xy` → 0.21。
3. **`error_vel_xy` 指标本身有系统性偏差**：混了 5 种指令模式，还对整集平均（含 reset 爬升段）。逐帧稳态误差是 **0.07**，同 checkpoint 却记录 **0.206** —— **指标高估约 3 倍**，且无法告诉你是哪个指令模式在失败。

第 1 条最讽刺：**我上一份报告夸过的"只奖进展不奖状态"原则，官方在 `air_time` 上违反了自己定的规矩。** 这正是那份失败账本没能覆盖的一层。

第 3 条更值得记住：**arena 那套协议防住了"物理不复现"，但没防住"指标本身算错"。**

### 4.2 官方复合技能依赖私有 teacher checkpoint

`xinhuagu/my-microduck-journal` 明写：所有策略都是**在一台消费级 PC（RTX 50 系 + WSL2）上从零训出来的，不依赖官方配方所依赖的私有 teacher checkpoint**。它记录了原因：官方的 walk-and-get-up 复合技能命令，在没有 teacher checkpoint 时**返回 HTTP 403**——checkpoint 在私有项目里。

**这是"开源"最大的裂缝，比机械 NC 更实质。** NC 是法律限制（不能卖），私有 checkpoint 是**技术不可复现**（连自己训都训不出来）。一个人为此重建了整套 teacher，并且产出：
- `velstand_default` / `velstand_fast`
- **`sideroll.onnx`——官方没有的技能**：左右各侧滚一整圈再站起来，768 只鸭里 98% 成功
- 用**同一个开放考试**（256 只随机鸭 × 3 seeds）测所有策略，**官方策略也在同一张表里**
- 规则事先定死：checkpoint 由考试选而**不是"最后一个"**，成为默认策略必须过事先约定的 release gate

### 4.3 三个零散但严重的实现 bug

- **head-IMU 驱动：温度低于 23°C 时读数接近 280**（`dukki` 作者发现，并说这个 bug **也影响 Pollen 自己的机器人**）
- **backlash 模型静默索引错误：14 个关节里 13 个是错的**（`AungKaung1928` 的 CPU 版测试抓到）
- **`microduck-kick` 的评测漏洞**：PPO 踢得最狠却 3/3 摔倒，因为任务只在 **70°** 才算摔，而 PPO 稳在 **57°** —— 差 13° 就骗过了判定

### 4.4 官方隐藏的野心

`apirrone/microduck_maploc_rs`——Pollen 工程师写的 ToF submap SLAM + 重定位 + A* 规划，**目标 runtime 不公开，但 crate 公开**。对应 roadmap 的 **M9 autonomous brain**。也就是说官方正在做的自主性还没放出来。

---

## 5. 真正的空白：还没人做，或只有一个人做

排掉上面那些，剩下这些是真空白：

| 空白 | 依据 | 机会 |
|---|---|---|
| **真机验证** | 机器 12 月才发，全生态 99% 是 *sim-only* | 拿到机器的人有 3–6 个月先手 |
| **官方 bug 的系统性审计** | 上面那 5 个都是零散发现，没人做过系统审计 | 一次审计能产出 5 篇以上可复现报告 |
| **官方复合技能的公开复现** | 只有 `xinhuagu` 一个人做了 teacher 重建 | 复现路径已被验证，可扩展 |
| **跨形态迁移方法论** | 有人换舵机（5 个），但没人做"从 duck 到其他形态"的方法论 | 我那五份报告里的原则可以填这里 |
| **统一跨策略排行榜** | `arena` 是官方的、只跑官方赛道；`craigm26` 有自己的 bench，但只是个人 | 缺少中立的第三方排名 |

值得注意的是 **Agent/MCP 那一层已经有 23 个条目**（`microduck-mcp` ×2、`quackd` 269★、`meckie-duck-gateway`、OpenCastor、Strands provider），但清单明确说这一层**全部是对着设计文档和 mock 写的，没有一条在发货的机器上跑过**。这是最拥挤也最虚的一层。

---

## 6. 三条建议

### 如果目的是"学 sim2real" → 现在是最佳窗口，且不用买机器

1. **别自己搭训练栈**。46 个人已经做过了。挑一个匹配你硬件的：
   - 有 NVIDIA → 官方 mjlab
   - Mac → `jonathanhawkins/microduck-lab` 或 `keeeeenw/microduck_rl_mac`
   - AMD → `Macmachi/microduck-rl-genesis`（actuator 逐位对齐，最可信）
   - Intel 集显 → `guang384/mjlab-sycl`
   - 纯 CPU → `tailong-wu/microduck-mjbatch`（2.5 小时出走路策略）
   - 什么都想省 → `OneRobotAI/microduck`（两个脚本，RTX 5060 Ti 约 4 小时）
2. **读那 5 份 bug 报告，而不是只读官方文档**。官方文档告诉你"怎么对的"，那 5 份告诉你"哪里其实不对"——后者才是稀缺的。
3. **用 `craigm26` 的 golden vectors 校验你自己的实现**。这是唯一能证明"我复现对了"的客观方法。

### 如果目的是"做点没人做过的" → 空白很小但很清楚

- 真机到手后的**第一份实测报告**（12 月后）
- 官方 bug 的**系统审计**（现在就能做，不需要硬件）
- 官方复合技能的**第二次独立复现**（验证 `xinhuagu` 的路径是否可推广）

### 如果目的是"抄一个能跑的硬件" → 别再自己画图

`fanhao375`（56 个 SolidWorks 零件 + 21 页手册）、`avanx`（imu_to_dxl 板）、`jyg9`（社区套件）、`fanduck`（完成品）已经把这套补齐了。**唯一没解决的是许可**：机械仍是 NC，不能商用。

---

## 7. 一句话收尾

前五份报告的主题是「Microduck 做对了什么」。第五份是「它的短板是不是别人已经做了」。这一份的回答是：

> **短板全被补了，而且是 240 个项目、46 个训练栈的规模在补。**
> **真正的缺口只剩两类：一类是官方主动保留的（硬件不开源、teacher checkpoint 私有），一类是时间还没到的（12 月才发机器）。**
> **而最意外的收获是：社区发现的官方问题，比官方自己记录在 `CLAUDE.md` 里的还多。**

如果只能记住一句：**这个生态里最稀缺的不是"能训出走路策略"，是"能证明别人的数字是错的"**——那 5 份 bug 报告的价值，高于 46 个训练栈移植。

---

*数据来源：GitHub REST API、`joeynyc/awesome-microduck` readme.md（79 KB，240 条目，逐节计数）、`Qi-hub-dot/microduck-locomotion-diagnosis`、`xinhuagu/my-microduck-journal` 原文。检索日期 2026-10-23。*
