# 三个项目互相印证与借鉴

日期 2026-10-23。对象：

| | microduck | live2d-pet（阿岩 2D） | ayan-3d（阿岩 3D） |
|---|---|---|---|
| 本体 | 800 g 双足机器人鸭 | Electron + pixi + Live2D | Unity 2022.3 + UniVRM |
| 决策 | RL 策略（61 维观测，50 Hz） | 状态机 + 程序化 | 状态机 + 程序化 |
| "活"从哪来 | 训练出来的 | 逐通道错峰 + 种子抖动 | 快慢双钟 + Perlin + 派生补偿 |
| 验证 | `gates.json`（先登记门槛）+ `selfcheck.py` 8 条 | 26 个 `verify-*.js`（6417 行） | 铁律 30 余条 + 逐里程碑验证报告 |
| 规矩 | 无编号 | 35 条，集中在 `MEMORY.md` | 约 30 条（含 `30b~30g`），散在 54 份文档里 |
| 研究文档 | 9 份专题报告 | `open-source-reference.md` 1434 行，分 11 轮 | 每里程碑一份"调研 + 源码核对" |

2D 与 3D 之间**已经有双向回流流程**（`ayan-3d/docs/2D版回流-可借鉴清单.md`
与 `M6-D与后续-2D项目可借鉴思路盘点.md`），并且已经反向指出"2D 从 3D 抄工程纪律"。
本报告做的是**把 microduck 接进这个环**，并且每条都先去网上找权威出处再下判断。

---

## 一、网上印证：四条被独立证实的做法

### 1.1 延迟容限 = 相位裕度 ÷ 穿越频率（解释了我们的 17 倍落差）

控制论的标准结论：

$$T_{d,\max} \approx \frac{PM_{rad}}{\omega_{gc}}$$

即**纯延迟消耗相位裕度，且穿越频率越高、能吃的延迟越少**。两处权威表述：

> "Additional pure delay consumes phase margin without changing the magnitude of an otherwise
> unchanged loop. A commonly used delay-boundary screen is $T_{d,max}\approx PM_{rad}/\omega_{gc}$."
> — <https://atlasofengineering.com/automation-and-control-engineering/phase-margin/>

> "Increasing low-frequency loop gain can improve tracking and disturbance rejection while
> **reducing phase margin near crossover**." — 同上

**这一条直接解释了上一轮的实测**（`out/ab_norm.log`）：

| | clean | official（真实传感器路径） | 落差 |
|---|---|---|---|
| 阶段 A `robust61_a` | 0.42 | 0.39 | 1.1× |
| 归一化核 `robust61_n` | **0.85** | 0.05 | **17×** |

归一化核让梯度变陡 → 策略学到**高增益** → 跟踪变好，但 $\omega_{gc}$ 抬高 → 相位裕度被吃掉 →
延迟容限变窄。**这不是"训练没收敛"，是控制论的必然。** 当时我只是凭直觉说"高增益必然对延迟敏感"，
现在有公式了。

**顺手可以反推出一个数**：我们的延迟悬崖在 40 ms（开始掉）到 60 ms（26 次摔倒）之间。
取 PM = 45° = 0.785 rad：

| 假设初崖延迟 | 反推 $\omega_{gc}$ |
|---|---|
| 40 ms | 19.6 rad/s ≈ **3.1 Hz** |
| 60 ms | 13.1 rad/s ≈ **2.1 Hz** |
| 80 ms | 9.8 rad/s ≈ **1.6 Hz** |

也就是这个 0.8 kg 鸭子的闭环带宽大约在 **1.5–3 Hz**。这个数可以**独立测**（给方波/扫频命令，
量实际速度响应），测出来能直接预测延迟容限，不必每次跑 27 项阶梯。**这是一条可证伪的捷径，
建议当作下一个实验。**

### 1.2 「高保真仿真 > 广泛随机化」——这条直接改写了我们的优先级

Tan 等人在 Ghost Minitaur 上的结论（原文摘要式表述）：

> "**high-fidelity simulation is more critical than extensive randomization; without accurate
> actuator and latency modeling, policies failed to transfer regardless of robustness training.**"
> — Sim-to-Real: Learning Agile Locomotion For Quadruped Robots
> <https://lacuna.tiptreesystems.com/work/sim-to-real-learning-agile-locomotion-for-quadruped-robots/wrk_fea30daaebfe866e43c3f515d6d93143>

他们做的是：辨识质量/惯量 → **自建执行器模型（DC 电机物理：反电动势、电压限）** →
实测 15–19 ms 通信延迟 → **把历史延迟注入训练**。注意顺序：**先有执行器模型，延迟注入才有意义。**

**对照我们现在**（`repo/train_ppo.py:87-92`）：

```python
actuator.set_to_position(kp=KP, kv=KD)          # 纯 PD
actuator.forcerange = [-FORCE_LIMIT, FORCE_LIMIT]  # 一个常数力矩上限
```

**执行器带宽是无穷大**——力矩说给就给，没有时间常数、没有反电动势、没有转速相关的力矩衰减。
我们在这样的植物上随机化"命令延迟"，再叠加噪声、推力、摩擦——**方向错了**：
延迟随机化教不会策略"力矩要等一会儿才到"，因为在这个仿真里它**立刻**就到。

这也解释了我们那个一直没想通的现象：**同样 20 ms，"哪些通道被延迟"不同，速度差 6 倍**
（只滞后关节速度 0.066 m/s，陀螺+重力一起滞后 0.395 m/s）。利用相位关系才能解释这种敏感性——
说明策略是在**依赖瞬时执行**做相位补偿，而不是在容忍延迟。

> **结论：缺失的执行器模型（BAM M6 电压模型）不是"保真度加分项"，而是这条路上的前置条件。
> 加 BAM 的期望收益高于再跑十轮奖励改造。**

旁证：上游 microduck 自己就是这么做的（`BAM_ACTUATOR_KWARGS` + `model="m6"`，见
`microduck-技术深挖.md`），且 BAM 参数库里直接有辨识好的 `feetech_sts3215_7_4V`。

### 1.3 无节奏噪声 → 去机械感（三个项目里两个已做，microduck 没做）

学术侧有直接对应的论文：

> "Cyclic motions such as running or walking are difficult to animate because ... only a small
> number of distinct cycles being produced. These few cycles are then repeated...
> **the repetitiveness of the resulting motion often appears unnatural.** This paper seeks to fix
> this problem by determining how to introduce natural-looking variability into cyclic animations."
> — The Effects of Noise on the Perception of Animated Human Running（CMU RI）
> <https://www.ri.cmu.edu/publications/the-effects-of-noise-on-the-perception-of-animated-human-running>

工业侧的做法也一致，而且给了分频经验：

> "**low-frequency noise controls large body shifts, while high-frequency noise handles small
> muscle twitches**" —— 多频段噪声映射到多关节，避免硬循环痕迹

三个项目的落地形态各不相同，但都指向同一件事：

| | 机制 | 参数 |
|---|---|---|
| live2d-pet | 每次切换抽一套**速度**因子（幅度不动） | `JITTER_RATIO=0.15`，固定种子 `74119` |
| ayan-3d | 骨盆挂 **Perlin** 漂移，打破 1.58 s 可数循环 | ±1.2° @ 0.22 Hz |
| microduck | **无**。14 个情绪是 10 Hz 定表，播两次逐帧相同 | — |

一个值得记的细节：**两个项目都栽在种子上了，但栽的方向相反。**
live2d 是主动选固定种子（为了截图复现），ayan-3d 是 `new System.Random(20261016)` 写死，
直到验证时才发现"每次开机编排一字不差，4 次大转移全倒向同一侧"。成熟形态是两者兼有：

- 生产用**开机时刻做种子**（有变化）
- 留 `--seed` / `PET_*` 开关**钉死**（取证能复现）

microduck 的评估侧目前是反过来的：`robustness.py` 用 `seed=0` 跑 8 个环境，
**每次测量都是同一批 8 条轨迹**。这适合 A/B，但意味着**从来没有方差估计**——
ayan-3d 的教训（n=19 时 11:8 是纯噪声，却差点被当成有偏）在这里同样成立。

### 1.4 负对照：报告"全绿"之前，先证明它能变红

> "Measured baseline from one audit of 18 proof scripts: **16 stayed green in a world containing
> nothing but the script itself** — 6 asserted nothing, 10 verified artifacts they had just
> written, 1 reached outside its own scope, 1 did not reproduce."
> — <https://happyin.space/testing-qa/negative-controls-for-verification>

协议只有一步：**声明被测对象、把它藏掉或改坏、再跑一次，必须返回非零。** 这条对我们特别相关：

`tools/selfcheck.py` 的 `check_env_equivalence()` 拿 `R.Duck`（带随机化的 wrapper）和
`O.Duck`（官方）逐帧对比。它是**差分测试**——只能发现两者之间的**差异**，发现不了**共同祖先里的错**。
如果父类的物理、奖励、观测布局一起错了，两边一致，这一项照样绿。

这不是说那条检查写错了（它的契约就是"wrapper 不能改变行为"），而是说：
**8 条不变量里没有一条被证明过"能让它变红"。** 补法很便宜——故意把历史缓冲移位一格、
把观测槽对调、把 ONNX 的输入名改掉，跑 `selfcheck.py`，确认它必须 FAIL。
如果某一项仍然绿，那一项就是装饰。

顺带一个名字：这件事在测试文献里叫 **mutation testing**（变异测试），
Python 用 `mutmut` / `cosmic-ray`，JS 用 Stryker。我们不需要上工具，手改三次就够。

---

## 二、互借矩阵

行 = 拿的人，列 = 给的人。

|  | 从 live2d-pet 拿 | 从 ayan-3d 拿 | 从 microduck 拿 |
|---|---|---|---|
| **microduck** | ① 编号规矩 + 每条挂回归 ② 表情错峰与种子抖动（受音频约束，见 §3.1） ③ 研究文档的"不抄清单 / 空白清单" | ④ **派生层**而非并列常数 ⑤ 测量窗口 ≥ 一个完整周期 ⑥ 事件要单调计数 ⑦ 小样本定性警告 ⑧ 量化参考动作 | — |
| **live2d-pet** | — | ⑨ 铁律集中成册（它已有，这条是对照） ⑩ 骨架级量化给 `EMO_SPEED` 一个实证依据 | ⑪ **先登记门槛再测量**（`gates.json`） ⑫ 同一结论必须两个独立指标同屏（`ab_compare` 三表） |
| **ayan-3d** | ⑬ **铁律总表**：现在引用到 `30g` 却没有单一注册处，54 份文档里散着 ⑭ 抖动的成熟形态（比例 + 固定种子的组合） | — | ⑪⑫ 同上；⑮ "能力置换 vs 帕累托改进"这个判断框架 |

### 2.1 microduck ← ayan-3d：派生层（最重要的一条）

原文（`M8-C-髋补偿与慢钟-验证报告.md`）：

> 为什么做成**派生**而不是照抄参考实现的两个独立常数：写歪了不报错、只会脚滑；
> 派生层**结构上不可能**跟丢或残留——骨盆归零它必然跟着归零。

这句话对 microduck 直接适用，而且我们现在正犯它说的错：
`tools/plant.py` 里 `FORCE_STALL = 0.96`、`FORCE_CURRENT = 0.6405`、
`SOLVER_TRAINING = (10, 20)`、`FLOOR_FRICTION = (1.0, 0.005, 0.0001)` 是**四个并列常数**。
它们来自不同地方（数据手册 / kt×电流 / 上游训练配置 / 上游 XML），
一旦有一个偏了，表现只是"策略差一点"，**不会报错**。这正是"写歪了不报错"的形状。

可派生化的候选：
- `FORCE_CURRENT` 应当**由 kt 与电流上限算出来**，而不是写成 `0.6405` 这个已经乘完的字面量
  （现在注释里写着推导，值却是硬编码——注释一改就脱钩；live2d-pet 的硬规矩 22 说的就是
  "**少改一行注释也是「改一半」**：常量注释跟着实际值走"）
- 观测维度和槽位（3+3+14+14+14+3+...）应当由布局定义**推出** 61，而不是两处各写一遍
- 子树质量 `_recompute_subtreemass` 已经是派生的 ✅（这一处做对了，可以当范例）

### 2.2 microduck ← ayan-3d：测量窗口必须装得下一个完整周期

原文的坑：用 14.5 s 的窗去测 18 s 周期的阶跃，量到的是"这段恰好站在哪边"（假 FAIL 3.1°）。
修法是**把窗口放大到装得下 4~5 个事件，同时加一条严格更强的判据（分桶包络）**，
而不是放宽阈值。

我们的同形问题：`tools/envelope.py` 早期默认 6 s，后退命令测出负速度——
因为**启动瞬态（先压重心再反向迈一步）主导了净位移**。改成 12 s 才好。

两条合起来的通则：**任何"净量"指标（位移、平均速度、平均跟踪率）都必须声明它的测量窗，
且窗口长度要和被测现象的时间尺度挂钩。** 现在的 `robustness.py` 默认 8 s、
`envelope.py` 默认 12 s，但**没有一处把这个约束写下来**。

### 2.3 microduck ← ayan-3d：事件要单调计数

原文的坑：靠"日志文本变化"数事件，连续两次同侧 = 同一字符串 = 只数到一次。

我们的同形问题（上一轮）：`falls` 是 `falls/episodes`，早期回合没跑满 1000 步，
唯一能结束回合的原因就是摔倒，所以比值恒为 1.00——**指标没坏，但早期几乎无信息量**。
后来换成 `fall/1k`（每千环境步）才可比。这正是"计数口径要跟着状态定义走"。

### 2.4 live2d-pet ← microduck：先登记门槛，再测量

这是我们**唯一一处比另两个项目更严的地方**：`tools/gates.json` 是在跑 27 项之前写好的，
里面每条门槛都带一句为什么。改数字要留 `_revision` 说明（延迟单位那次就留了）。

另两个项目都是**测完再判断**（`verify-*.js` 断言的是"行为符合预期"，
但阈值来自实现者当时的直觉）。两者的差别在事后无法弥补：先测后定阈值，等于给自己发合格证。

### 2.5 live2d-pet ← microduck / ayan-3d：同一结论必须 ≥2 个独立指标

这是用血换的：`deploy61` 在真实传感器路径下 6 个命令的倾角**全是 45–46°**、10 秒摔 46 次，
但跟踪率表里它是 `yaw 1.63 / back 1.19 / side 0.98`——全是**翻倒过程中的位移**。
当时 15 次摔倒就印在同一份输出里，我先读了跟踪率、没读它。

`tools/ab_compare.py` 因此改成**同屏输出跟踪率 / 摔倒 / 倾角三张表**。
ayan-3d 的 9 条判据里也有同款结构（包络 + 分桶包络 + 分段均值 + 斜率），
**同一条现象用多个不相关的量去夹**，任何一个单独都能被曲解。

---

## 三、microduck 的具体清单

### 3.1 表情层：能搬，但有两个硬约束

live2d 的逐通道速度表（`profiles/hiyori.js:224-240`）：

| 眉 | 眼 | 呆毛 | 嘴 | 头 | 脸红 | 肩 | 身 |
|---|---|---|---|---|---|---|---|
| 9 | 7 | 5 | 4.5 | 3.2 | 2.8 | 2.6 | 2.2 |

快慢比 4.1×。**这一列数字有实证支持**：说话时眉毛上升**先于发声约 240 ms** 开始
（<https://pmc.ncbi.nlm.nih.gov/articles/PMC4440649/>），
面部信号多数落在话轮**头 40 ms 内**（Holler 2025，front-loading）。
"眉先到、嘴后到"不是审美偏好，是人的时序。

microduck 的 `laugh` 关键帧里，`head_yaw` 在 0.0–0.4 s 起、`mouth` 在 0.5 s 起
——**头领先嘴 100–500 ms**。方向和上面一致，量级同阶。所以它**已经做对了错峰，只是写死在数据里**。

两个不能照抄的地方：

1. 🔴 **不能整段时域缩放**。microduck 的 `mouth` 是**预先对好声音**的
   （报告原文："播放时不需要运行时做音画对齐——设计阶段就对齐完了"）。
   整段变速会让口型和声音脱钩。**只能抖 head / neck / body，嘴锁音频时钟。**
   live2d 没有这个约束（它口型是运行时从波形算的），所以它敢整张脸一起抖。
2. 🔴 **不能抖幅度**。幅度受平衡约束——`sad` 的 `robot_note` 写明"故意只做一半深度，
   更深的低垂会把头部质量前移，真鸭子会往前走一步来稳住自己"。
   抖幅度会吃掉这条好不容易标定出来的余量。

### 3.2 该做但要等真机的

- 表情变速/抖动：现在连一份能上机的权重都没有，做表情层是在沙上建楼
- 逐通道时间常数搬到引擎：同上，而且**数值必须往低调**——
  虚拟身体零惯性，鸭子有真实质量，物理自己已经给了一部分滞后

### 3.3 明确不搬

| 候选 | 为什么不搬 |
|---|---|
| **Picard / EMIA 情绪衰减**（live2d `verify-emotion-decay.js` 已实现） | microduck 的 14 个情绪是**自终止片段**（laugh 3.0 s、sad 7.5 s，播完回 home），不是"设定后一直保持的目标状态"。人家的病是 `[emo:xxx]` 进来后高兴一整晚；鸭子没有这个状态。给片段再加衰减 = 二次缩短 |
| 表情 Add / Multiply 混合模式 | microduck 关键帧是**相对 home 的增量**，度数上加减是唯一说得通的；混合模式会和平衡控制打架 |
| 26 个 `verify-*.js` 的规模 | 那是 30+ 功能域换来的。microduck 只有 5 个概念（观测契约/植物/门禁/ONNX/部署回路），凑数就是形式主义 |
| 全屏静默 / 番茄钟 / CPU 底座 / 自动更新 / 托盘 | 桌面应用问题域，零重叠 |
| **mood 四轴 + 轴间制衡** | 需要"持久情绪状态"作前提，鸭子是片段式；且 ayan-3d 自己那条铁律 C9 说得对：**加轴之前先回答"谁来消费它"** |

---

## 四、建议顺序（按性价比）

| | 做什么 | 为什么这个顺序 | 成本 |
|---|---|---|---|
| 1 | **给 `selfcheck.py` 加负对照**：故意改坏 3 处（历史缓冲移位 / 观测槽对调 / ONNX 输入改名），确认每一项必须变红 | 先证明仪器是活的。否则后面所有数字都可能是在读一个恒绿的仪表 | 半小时 |
| 2 | **把这几轮的坑提成编号规矩**（`RULES.md`：规矩 + 血案 + 回归命令） | 2D 有 35 条集中版、3D 有 30 条散装版。我们一条都没有，坑全靠 README 散文 | 1 小时 |
| 3 | **测量方差**：`robustness.py` 支持 `--seeds 0,1,2`，报均值±标准差 | 现在每次都是同样的 8 条轨迹，没有方差就没有"这个差异是不是噪声"的判断力 | 1 小时 |
| 4 | **反推 $\omega_{gc}$ 并验证 $T_{d,\max}=PM/\omega_{gc}$** | 如果成立，以后 10 秒能预测延迟容限，不用跑 27 项。不成立也是一个明确的知识边界 | 半天 |
| 5 | **接 BAM 执行器模型** | 网上有权威结论说这是前置条件（§1.2）。但它要改植物层，成本最高 | 天级 |

前 4 项加起来不到一天，且都是"提高以后所有判断的可信度"。
第 5 项是唯一可能真正推动"没有可交付权重"这个结论的，但也是最贵的——
**建议先做完 1~3，再决定要不要投 5。**

---

## 附：本报告的网上证据

| 论点 | 出处 |
|---|---|
| $T_{d,\max}\approx PM/\omega_{gc}$；增益↑则相位裕度↓ | <https://atlasofengineering.com/automation-and-control-engineering/phase-margin/> |
| 纯延迟只加相位不加幅值，带宽被延迟上限卡死 | <https://chatwhole.com/learn/control-systems/24-time-delay-systems-and-the-smith-predictor> |
| 高保真仿真 > 广泛随机化；无执行器/延迟模型则随机化无效 | Tan et al., Sim-to-Real: Learning Agile Locomotion For Quadruped Robots |
| 多模态延迟随机化（MMDR）是延迟的标准解法 | <https://api.emergentmind.com/papers/2109.14549> |
| 循环动作重复 → 不自然；需注入自然变异性 | CMU RI, The Effects of Noise on the Perception of Animated Human Running |
| 低频噪声管大幅身体晃动、高频管小肌肉抖动 | 程序化动画工业实践（多频段噪声映射） |
| 负对照：18 个脚本里 16 个在"只有脚本自己的世界"仍全绿 | <https://happyin.space/testing-qa/negative-controls-for-verification> |
| 变异测试 / 等价变异体 / 同义反复测试 | <https://specstory.com/learning/test-quality> |
| 眉毛先于发声约 240 ms；面部信号多在话轮头 40 ms | <https://pmc.ncbi.nlm.nih.gov/articles/PMC4440649/>、Holler 2025 |
| 动态表情的三态结构：松弛 / 快速过渡 / 保持 | Cuve et al., Sci Rep 16, 15686 (2026) |

---

## 五、Fanduck 复刻站（duck.fandcode.com）核对结论 · 2026-10-24

站点是**单页**，自述「Microduck 1:1 个人复刻记录」：8 阶段全完成（2026-09-14），
承诺支出 ¥11,923.60+，宣称「官方 9 项策略全部实测通过」。

### 5.1 公开包里有/没有什么（下载并核对过）

| 包 | 大小 | 内容 | 对本项目 |
|---|---|---|---|
| 制作物料与打印件 | 12.7 MB | BOM、中文分类打印件、装配图 | 暂不需要 |
| 板件制造资料 | 31.3 MB | HAT / 触点板 / NFC 图纸 | 暂不需要 |
| 制作工具源码 | 1.1 MB | 打印修正版生成、几何检查 | 暂不需要 |
| **镜像工作台源码** | 2.6 MB | 只读关节采集 + 3D 姿态 + 可选相机 | **唯一有复用价值的** |

镜像工作台包（`43f67fc1…` SHA-256 与 manifest 一致）：32 个文件，**没有任何策略、训练
配置、checkpoint 或步态数据**。它的 `核验结果.json` 自己写着：

```json
{"unit_tests": {"passed": 34, "failed": 0, "hardware": "fake serial and mocked state only"},
 "real_hardware_tested": false}
```

所以「官方 9 项策略全通过」是**项目负责人对自己那台机器的自述**，公开包里那句
`real_hardware_tested: false` 说明**这份下载本身没做实机验收**，34 项测试全部跑在
假串口 + mock 状态上。引用这个站时不能把它当独立第三方证据。
（README 还明确：不含官网、App、产品运行时，也不含「失败的独立 IMU」方案。）

### 5.2 三条可用的实物信息

**① 官方锁定提交 `d424a0c899f6`（2026-08-27，`Merge PR #4 Add AGENTS.md`）。**
它的 3D 模型就是从这一版取的。用 GitHub API 比对：该提交比 `develop` **落后 75 个 commit**，
`develop` 后来加了 `pickup/`、`publish/`、`docs/sitstand_policy.md`、`export.py` 等 159 个文件。
→ 一个**把官方 9 项策略跑通实机的人**冻结在 8 月底这一版，不是 `develop` 头。
这条对我们有参考意义（我们用的是 `develop` 快照），但**不足以据此换版本**——差异里没有
与 joy 步态相关的东西。

**② 舵机 15 台 vs 仿真 14 个关节，差额是鸭嘴。**
站点硬件表：XL330-M288-T ×16（15 台装机）；「十五台舵机整机吊架测试」。
本机模型的 hinge 关节正好 14 个：`left/right × {hip_yaw, hip_roll, hip_pitch, knee, ankle}`
（10）+ `neck_pitch, head_yaw, head_roll, head_pitch`（4）。
模型里 `jaw` 是**刚性挂在 `head_roll` 的 body 上**，没有独立关节；`jaw_soft` 那个 body 上带的
也是 `head_roll`。→ 多出来的那一路几乎肯定是鸭嘴，**策略不控制它**，`obs[6:20]` 的 14 维与
硬件 14 个「策略关节」是对齐的。别拿 15 对 14 去怀疑模型少了一个自由度。

**③ 两个 IMU 站点，仿真只读身体那个。**
`robot_groundcontact.xml` 里有 `imu`（`trunk_base` 内，`pos -0.021 0 -0.0147`）和
`head_imu`（头颅内，`pos 0.0152 0 -0.0511`）**两个** site。但 `<sensor>` 段里
6 个传感器（`orientation` framequat、`angular-velocity`、`imu_ang_vel`、`imu_lin_vel`、
`imu_accel`、`root_angmom`）**全部只挂 `imu`**；`head_imu` 在全部 7 个 xml 变体里都只是
几何 site，`grep` 整个 `src/` 没有任何代码引用它。

站点硬件表则写「BMI088 **头部** IMU 随 HAT PCBA」，另外自己打了一块
「IMU To DXL 兼容板 / 第二颗 IMU（ID 200）」——**即实机唯一的 IMU 在头上，身体 IMU 是复刻者
自己加的**；而包 README 明确说「不含…**失败的**独立 IMU」。板子电学验证成功 ≠ 方案成功。

→ 这是**部署期**的一个真实裂缝：`base_ang_vel` / `projected_gravity` 在仿真里是**躯干系**，
实机只有**头系** IMU，而 4 个头关节（`neck_pitch`/`head_yaw`/`head_roll`/`head_pitch`）是会动的，
`joy_head_command` 还在主动驱动它们。属于 sim2real 待办，**与当前「单腿踏步」无关**，
不要混进奖励问题里。

### 5.3 唯一值得抄的代码

`tools/microduck-joint-mirror/readonly_bus.py`：**只发 PING/READ/SYNC_READ，拦掉一切
运动与参数写**的只读总线读取器。几个细节是真踩过的：

- 先读 `torque`，**非 0 直接抛错**（不给扭矩开着就抓姿态的机会）；
- 读地址 **20 的长度 4** 取 Homing Offset，机械零位 = `present_position − homing_offset`
  （X 系列控制表约定）；
- 扭矩关闭时多圈计数**不回绕、不清零**，直接用。

以后要在实机上量「脚到底抬多高」，这是现成的采集端骨架；比我们自己从 dynamixel-sdk
开始写省事。其余部分（SSH 主机指纹、相机温度保护）是给他们自己的 macOS + Radxa 环境写的，
不必搬。

### 5.4 结论

- **对「单腿踏步」这个卡点零帮助**：整站没有一个步态读数、没有脚高、没有策略文件。
  它证明的是「官方权重在实机能跑」——这我们早从上游 audit（`feet_peak` 18.46 / 20.03 mm）
  就知道了，我们的问题从来是**自己重训不收敛到交替**，不是目标不存在。
  > ⚠️ **2026-10-24 更正**：`feet_peak 18.46/20.03 mm` 这个出处是错的（audit json 里没有该字段，
  > 见《microduck-joy踏步失败诊断与修法》§26.3）。可用读数是 `out/probe_joy_official.json`
  > 的 **16.36 / 17.34 mm**，工厂为 0.2 ms servo。结论方向不变（官方权重确实会抬脚）。
- **三条待用**：只读总线采集器（部署期量脚高）、两 IMU 站点的头/身系差异（sim2real）、
  以及「有人冻结在 `d424a0c` 而非 `develop` 头」这一事实。
- 引用纪律：它的实机结论属于**自述**（公开包 `real_hardware_tested: false`），
  不能记成「第三方复现」。
