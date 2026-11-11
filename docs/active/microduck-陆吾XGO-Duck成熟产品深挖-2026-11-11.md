# 陆吾 XGO-Duck「成熟产品」深挖：产品矩阵、工程外壳与可直接借的实践

_2026-11-11，Pass114。起因：用户「陆吾的已经是成熟的产品了，是不是还能深挖点什么」。_
_方法：走 GitHub 官方 API（`orgs/LuwuDynamics/repos` + 6 仓 `git/trees?recursive=1`，HTTP 200 全取）拉此前从未抓过的**组织级仓库全清单与源码文件树**，再定点 raw 抓 22 个一手文件；全程不 clone（代理 502）、不碰硬件、不改任何门禁/采购判决。_
_边界：**离线/源码/商品页 ≠ 实机验收**；陆吾硬件/几何/ID/执行器与我们路①不同，算法与工程手法可借、**权重/几何/板型不可移植**。所有新事实标出处与 sha256，查不到的不外推。_

---

## 0. 结论先行

1. **能深挖，而且此前挖的是"一个算法仓"，不是"一个成熟产品"。** 10-09 那份《开源复刻项目-参考价值》只深挖了 `xgoduck_runtime_arduino` 的**算法源码**（recovery/rl_core/calibrate/scs_bus/architecture 的时序结论），项目四源对照 §7 自己写着「**luwu 本地无源码…未抓其源码文件树**」。本轮第一次拿到 **LuwuDynamics 组织 25 个公开仓全清单 + 6 个高价值仓的完整文件树（845 条目，无截断）**，看到的是一条**产品矩阵**（鸭 / 骑行车 / 四足 / 机器狗 / 语音 AI / Robot OS / 社区平台），不是单个鸭项目。

2. **真正的新到货有 3 块**（全仓此前 0 命中或只字未提）：
   - **`xgoduck_runtime_mosaico`**：陆吾自己的**第二套 runtime**，跑 ESP32-S31（ESP-Mosaico V1.2），把行走策略导出成 **C 数组编进固件**、50 Hz 推理、UART 发关节角给下位机、**板载 BMI270 不进策略**。这是我们 10-23「只有一块 ESP32 够不够」讨论的**厂商级答案**：厂商自己也做了砍掉 Linux 的轻量线。
   - **消费级"工程/合规/售后"文档外壳**：`TROUBLESHOOTING.md` / `FAQ.md` / `BUILD_GUIDE.md` / `PRINTING.md` / `ROADMAP.md` / PCBA 生产工艺 + **反接防呆、舵机堵转测试视频**。10-09 完全没读这套"把 DIY 项目包装成可量产、可售后、可诚实声明边界的产品"的外壳——**这是本项目最该抄的一层**（我们要交付打印包 + 装配清单 + 上板验收）。
   - **`test_parity.py` + `export_policy.py`（mosaico）**：教科书级的「**编译产物与原 ONNX 逐位等价 + 坏输入必拒**」离线证明，几乎逐条命中本项目反复踩过的静默 bug（权重没接进计算路径、NaN 进舵机、IMU 无门控乱跳、流解析被污染）。可借手法、不借硬件。

3. **一条过时口径要修**：顶层 `README.md` §4 仍写「不用陆吾 `1910_m6.json`（`actuator: sts3215`）训练」——该禁用理由 2026-10-29 / 11-03 已自我更正为**误判**（`sts3215` 是 BAM 合法键；真正问题是 `max_velocity:100` 拆掉官方限速，且我们本就不用陆吾 m6 作主植物）。详见 §5。

4. **仍然不能宣布的东西一个没变**：陆吾 FAQ 自己明写**没有可购买套件**（约 US$400 是自搭估算、非报价）、「其它训练任务只是实验、未集成运行时 + 无重复硬件证据就不算能力」、「外观相似的舵机未必兼容执行器」。这些是**现成的、产品级的诚实边界措辞**，正好加固我们的 `UNVERIFIED ≠ PASS`；R3（500k 位宽）、5 条原始 `INCONCLUSIVE_*` + 第 7 条 roller 悬案仍全部 `UNVERIFIED`。

---

## 1. 产品矩阵全景（25 公开仓，本轮第一次列全）

来源：GitHub API `orgs/LuwuDynamics/repos?per_page=100&sort=pushed`，HTTP 200，25 条，抓取日 2026-11-11。按用途分组（★/许可/最后推送均为 API 一手读数）：

### 1.1 XGO-Duck 鸭线（本项目唯一相关线）
| 仓 | ★ | 许可 | 最后推送 | 本轮前认知 |
|---|---:|---|---|---|
| `xgoduck_hardware` | 1886 | 无 LICENSE（意图个人/教育、商用另授权） | 11-08 | 10-09 挖了装配/BOM 存在性，**未读 docs/ 工程外壳** |
| `xgoduck_runtime_arduino` | 145 | 无顶层许可（含 Apache/MPL 第三方） | 11-09 | 10-09 深挖算法源码（C2–C6），**未读 architecture.md 全文工程细节** |
| `xgoduck_rl` | 123 | **Apache-2.0** | 11-09 | 已知；13 个任务配方、`1910_m6.json` HLS1910 BAM、导出烤 normalizer |
| `xgoduck_runtime_mosaico` | 9 | 无 | 09-28 | 🆕 **本轮首次**，全仓此前 0 命中 |
| `xgoduck_community` | 0 | 无 | 11-07 | 仅 Studio 文档提过"是投稿站、不是控制台"，未读内容 |

### 1.2 其它产品线（与鸭线**不混**，只作"厂商工程能力"旁证）
| 仓 | ★ | 许可 | 定位（API 描述） |
|---|---:|---|---|
| `xgorider2_rl` | 1 | Apache-2.0 | 🆕「**跑在原生 ESP32 上的 RL 平衡控制器**」 |
| `xgorider2-firmware` | 0 | Apache-2.0 | XGO Rider 固件 |
| `RIG-Muse` | 4 | Apache-2.0 | 🆕 ESP32 原生固件：表情动作/动画眼/音效/摄像头/传感器 |
| `rig_omni` | 144 | 无 | 🆕 ESP32-S3 多形态固件：语音 AI / 情绪动画 / IMU 平衡 / MCP 远程工具 / OTA / 圆屏 |
| `rig_local` / `rig_local_web` | 3 / 1 | 无 | 本地烧录台（无服务器，配置后设备直连 LLM/ASR/TTS/VLM） |
| `luwu_os` | 10 | Apache-2.0 | Robot OS（CM4/CM5 桌面 OS，Qt Launcher + PySide6） |
| `luwu-ros` | 1 | MIT | XGO CM5 ROS Image |
| `luwu_mjlab` | 18 | Apache-2.0 | 🆕 陆吾**四足**训练栈（Mini2S/Mini2SW/Lite3），mjlab 1.2.0 |
| `xgo_doglib` / `xgo_android` / `xgo_ios` | 55 / 5 / 2 | 无 | 机器狗运动库 / 手机 App |
| `rdk-x3` / `RaspberryPi-CM4/CM5-*` / `xiaolu_mcp_ha` / `mcp-demo-browser` | — | 多 MIT | 边缘计算 / HomeAssistant MCP / 浏览器 MCP 示例 |

🔑 **矩阵读法**：陆吾不是"一个人做了个鸭"，而是**一家公司把 RL 训练（`xgoduck_rl`/`luwu_mjlab`）+ 双脑固件（`runtime_arduino`）+ 单 MCU 固件（`runtime_mosaico`/`xgorider2`）+ Robot OS + 语音 AI + 烧录台 + 社区平台 + 手机 App 全栈铺开**。这解释了为什么它的文档有量产级完成度。我们只借鸭线，其余作旁证，**不混进路①判决**。

---

## 2. 真正的新到货（本轮首次一手取到）

### 2.1 🆕 `xgoduck_runtime_mosaico`：单 MCU 砍掉 Linux 的厂商级答案

`main/policy_manifest.json`（sha256 `16e8b216…`）实读：

```json
{"model":"xgoduck_walk.onnx","sha256":"fcab16d7…","input":[1,61],"output":[1,14],
 "architecture":[61,512,256,128,14],"activation":"ELU alpha=1",
 "weight_floats":197896,"weight_bytes":791584}
```

- `README.md`（sha256 `c10b0bd6…`）原文要点：行走策略由 `xgoduck_rl` 训练，导出后**转成 C 数组编进固件**；ESP-IDF 6.1.0 / esp32s31；**50 Hz 推理**，网页摇杆遥控，UART 把关节角发给下位机；下位机先以 115200 要求对端切 **2,000,000 baud** 再收发；**板载 BMI270 不进策略**（策略吃下位机回传的 IMU/关节角/关节速度）。
- 网页默认端口 80（不同于 arduino runtime 的 9527）；连接断开/页面后台/反馈超时 → 推理停止回默认构型，重连需再点开始。

**对本项目的意义**：呼应 10-23 XGO-Duck 对照里"四个策略全吃 61 维本体感觉、不吃视觉"的判断，进一步给出**厂商自己也在做"去 Linux、单 MCU、策略固化进固件"**的成品形态。它证明"61→14 的小 MLP 能在单 MCU 上 50 Hz 跑"是产业现实，不是我们推的。但它是**另一套硬件生态**（ESP-Mosaico 板 + 下位机），**不能替我们路①的 Radxa + Rust robotd 链**；价值是"部署形态的可选谱系"与下面的 parity 工程手法。

### 2.2 🆕 消费级"工程/合规/售后"文档外壳（最可借鉴的一层）

10-09 只挖算法，这批 docs 全文是首次读。逐份给出**可借的具体条目**：

**`docs/TROUBLESHOOTING.md`**（sha256 `aa50bdec…`）—— 8 行故障表，每一行都是"症状 → 先查什么 → 下一步"：
- 两个舵机同时响应 → **重复 ID** → 断开共用总线逐颗配；
- 关节反向 → 查 ID 位置/左右装反/零位 → **对比 PDF 与运行时映射，不要靠改策略顺序补偿**；
- 运动中重启 → **带载电压不足/连接器容量** → 停下查整条供电路径，**不要换更热的电源反复重试**；
- 默认位姿卡滞 → 装配朝向/关节零位/线被夹 → 支撑下卸力、先修机械原因；
- 振荡/发热 → 标定/增益/机械阻力 → 停下来对照文档配置再调；
- 无 IMU 数据 → 板朝向/焊接/I²C → 对照原理图与运行时 IMU 诊断。
- 末尾**求助边界**：附硬件版本/舵机料号固件/电池参数/清晰接线照/运行时状态抓取，且**明确要求不要公开 Wi-Fi 凭据、IP 敏感日志、个人购买信息**。

> 映射：这张表几乎逐条对上本项目已踩过的坑（重复 ID、左右装反、零位、带载掉电、无关节限位）。可直接作为我们**上机故障排查清单的骨架**（B7 采集骨架已做只读采集，这张表补"症状→处置"侧）。

**`docs/FAQ.md`**（sha256 `00fa6bb3…`）—— 产品级诚实边界的范本：
- 「要不要先训模型？」→ **不用**，运行时自带 walk/getup/pick ONNX，但仍需匹配的硬件/舵机设置/标定；
- 「能不能无机器人探索？」→ 可以看代码/在 CUDA 机跑训练仓，但**没有经过验证的浏览器模拟器**；官方 Microduck 模拟器是**上游学习参考，不是 Uno Q 变体的仿真**；
- 「成品还是套件？」→ **明确无套件/库存/零售价/交期**，约 US$400 是**自搭估算非报价**；
- 「能不能直接用 Microduck 软件/策略？」→ **不要假设**，尺寸相同不证明动力学/命令语义相同；
- 「现在能做什么？」→ 只有 walk/getup/pick 控制路径，**其它训练任务是实验，直到有匹配的运行时集成 + 可重复的硬件证据**；摄像头/语音/skating 等**不是本版本已确立能力**；
- 「改外壳/执行器？」→ **改变质量/惯量/关节限位/足底接触的机械改动就是控制改动**，重查装配与标定、评估是否需重训，**外观相似的舵机未必是兼容执行器**。

> 映射：这几条可直接升格为我们文档边界的现成措辞——尤其「尺寸相同不证明动力学/语义相同」（对治"3mf 里有轮滑件≠轮滑版能走"）、「机械改动=控制改动」（对治"换金属件/换轮滑件就当能跑"）、「实验任务未集成运行时+无硬件证据不算能力」（正是 `INCONCLUSIVE_ROLLER_POLICY` 的产品级表述）。

**`docs/BUILD_GUIDE.md`**（sha256 `8bfda52a…`）—— 分级上电作业指导（和本项目 B1 上板验收逐条对齐，且多处更细）：
- **逐颗配 ID**：一次只接一颗，分配 `10–14/20–24/30–34`，**raw 2047 中位**，写增益后贴标签（重复 ID 会收到同一份写）；
- **装配检查点**：25 页 PDF 分阶段对照（先不装螺丝的页、线在关节封闭前先接、左右朝向不同、TPU 鞋底方向）；
- **上电前 5 项**：15 个唯一 ID 全部应答（嘴是 ID34）、装配与 PDF 一致且线不卡、极性/供电上限已确认、机器人有支撑且关节远离手、运行时报新鲜 MCU 反馈 + IMU 可用；
- **分级测试**：先 inference-only → 支撑下默认位姿 → 平地低指令行走 → 再测 pick/recovery；测 pick/recovery 前先确认**卸力行为**（会塌、要支撑）；遇方向异常/卡滞/发热/反馈不稳就停下诊断；
- **出厂零位不是你的零位**：「Factory zero values are a reference from another assembly, not a substitute for calibrating your robot」，且**逐关节机械零位照片集仍缺**、校准前要先拿到；`zero_pos.json` **私密备份**；
- **可复现台账**：记录打印机/材料/切片参数、板版本、舵机供应商/固件、电池、三仓 commit、策略 hash、标定日期、运动测试观察。

> 映射：与本项目 `DEVICE_ZERO≠编码器零位`、HOME 对齐、EEPROM 时序、`link_evidence`/`board_capture` 骨架同向；**新增可借**：分级上电顺序、"出厂零位≠你的零位"的措辞、三仓 commit + 策略 hash 台账、求助时脱敏。

**`docs/PRINTING.md`**（sha256 `a1f8f8c4…`）—— 同款 XGO-Duck 的**独立打印物料清单**，可作我们 fanhao 11-02 版 3mf 的第二来源交叉核对：
- V5 音视频版 vs V2 原始版**头部件不能混**；一份背包外壳二选一（V1 / V1.1）；
- 命名规则 `2x_`/`4x_` = 份数、左右文件不同、保留原始文件名（含拼写 `mouth_buttom_tpu.stl`）以兼容链接；
- 30 个结构件 + TPU 件（脚印 `2x_foot_bottom_tpu`、嘴 `mouth_buttom_tpu`/`mouth_up_tpu`）；
- **轮滑可选件**：`2x_tire_support` + `4x_tire` + `4x_tire_axis`（另加 4×M2×6 沉头自攻 + 8×`10×15×3` 轴承）；
- **诚实边界**：打印参数（品牌/喷嘴/层高/壁/填充/支撑/朝向/缩放/公差、TPU 硬度、打印时长、耗材质量）**全部未实测**；大批量前先打**一个舵机座 + 一个轴承座**验配合、查左右朝向与走线间隙；**"别的 revision 的切片工程不是这套 STL 的已验证 profile"**。

> 映射：与本项目"受力件改金属 ¥45、TPU 未单列、跨仓只对照清单不混几何、ToF 孔距待卡尺"同向。**新增可借**："先打舵机座+轴承座验配合再整盘"的最小验证件策略；"别版切片工程≠本版验证 profile"（对治拿 fanhao 3mf 当唯一真值却未验配合）。

**`ROADMAP.md`**（sha256 `25885d46…`）—— 「每个里程碑**要有完成证据才算完成**」「proposed sequence, not a delivery schedule」「不因仿真里有任务就捧成能力，要逐条集成+评估」——**产品级的 `UNVERIFIED ≠ PASS` 措辞**。

**PCBA 量产旁证**：`docs/BOM.md`（sha256 `97a1d6f3…`）+ `PCBA/ProductionDocuments/生产工艺.txt` + 两张测试视频 `Reverse connection foolproof test.mp4` / `Servo Stall Test.mp4` + `SilkscreenLayout/*.pdf` + Gerber 文件。⇒ 一个"能卖成品"的项目会留下**防反接测试、堵转测试、生产工艺、丝印图**；我们做整机虽不自产 PCBA，但这提示**上板验收应有对应的"防反接/带载/堵转/散热"实测项**（当前 B1 清单以通信/识别为主）。

### 2.3 🆕 `xgoduck_community`（11-07 新建）：把鸭做成平台生态

`README.md`（sha256 `bbe8f701…`）：社区作品目录，四板块 = **结构 / 整机固件 / 动作模型 / 音视频交互**；有专门的**轮足改装**示例位（`examples/demo/duck-roller.md`）、RL 训练、视觉示例；站点用原生 HTML/CSS/JS、Node 22+ 零第三方依赖、GitHub Actions 自动部署 Pages；**给 AI Agent 准备了投稿提示词**（`docs/AGENT_SUBMISSION_PROMPT.md`）。

> 意义：陆吾在**主动外的"轮足改装"纳为官方社区板块**——我们 11-11 刚拍板"本项目也做轮滑版"，说明这不是孤例、有同行生态。但示例文件自己明写「**这是虚构演示，没有实际模型文件**」⇒ 社区目录**不构成任何轮滑策略/几何的可下载证据**，不可当 `INCONCLUSIVE_ROLLER_POLICY` 的闭合材料。

---

## 3. 可直接借的工程实践：`mosaico` 的 parity 手法（不绑硬件）

`tools/export_policy.py`（sha256 `cc8aa008…`）+ `tests/test_parity.py`（sha256 `ba6c6f75…`）是**离线证明"编进固件的 C 与原 ONNX 逐位等价"**的完整实现。手法层（非硬件）逐条可映射到本项目的部署链门禁：

| mosaico 做法（一手） | 命中本项目哪个坑 | 可借的工程手法 |
|---|---|---|
| 导出时**严格图结构白名单**：节点 op 序列必须 `['Sub','Div','Gemm','Elu'×3…]`、I/O 必须 `[1,61]→[1,14]` float32、Gemm 属性只许 transB=1/alpha=beta=1、Elu alpha=1，不符直接拒 | `deploy61` 分母差 1157×、normalizer 没烤进图 | **导出即结构校验**，把"支持哪一种图"写成正向白名单，不在推理期猜 |
| 输出 `policy_manifest.json` 带 `sha256`/`input`/`output`/`architecture`/`activation`/`weight_floats`/`weight_bytes` | manifest 契约矩阵、导出与 run 同放 | manifest 结构可直接对账；导出物与来源 ONNX 绑 sha |
| **150 组 ONNX↔C 随机向量**逐位比对（rtol/atol 2e-4），打印最大绝对误差 | 我们反复强调"验证问量动没动、量级对不对" | 部署产物必须有**数量化的一致性回归**，不是"导出成功"就算过 |
| **NaN/Inf 注入必被拒**（3 个索引 × 3 类坏值，`policy_run` 必须返回 false） | ONNX 空输出/非有限值进舵机 | 有限性守卫 + 负对照 |
| **权重重定位测试**：显式指针必须控制每层**包括输出 bias**（改最后 bias 输出恰好 +0.25）；**零除子的 normalizer divisor 不得到达舵机** | `deploy61` 那类"权重没真接进计算路径"的静默 bug；`rehearse_deploy.py` 写死 XL330/kp200 | **改一个权重→输出必须按预期变**的正向断言 + 负对照，专治"参数写了没生效" |
| **IMU 新鲜度门控**：时间戳未来/过期/samples=0/error/estimate_invalid 任一即 `fresh=false` | BNO085 `0x08` 走路跳 20–60°、我们 `bno08x.rs` 无跳变门控 | 数据新鲜度 + 有效性门控，是"别信内置融合/原始报告"的工程落地 |
| **流解析抗污染**：C 与 Python 解析器对坏 CRC / NaN 载荷 / 夹杂 `DUCK_IP=…` 字符串的字节流**逐字节同解** | 裸子串匹配被反义复合词反噬、半双工尾字节截断 | 解析器**双实现交叉验证** + 脏流负对照 |
| 姿态估计**额外线加速度不得把 gravity 拉向加速度轴**、恒定 roll 积分校验 | BNO08x `gravity` 跳=摔 | 融合算法的物理不变量单测（范数=1、线性加速度不污染姿态） |

> 📌 这一节是"取长补短"里**最不需移植、最该抄**的一层：它全是 Python/ctypes/ONNXRuntime 的离线测试，与具体舵机/板子无关。可评估并入我们 `microduck-software/tools/hd1910/` 的部署链门禁（作为**纯新增**工具，带负对照、不改既有计数口径），但本轮**只记录、不落地**，避免把新依赖/新工具塞进刚 CI 转绿的链。

---

## 4. 与既有判决的交叉印证（不是新结论，是四源→五源）

- **"换 plant 必重训 / 几何质量惯量不适用"**：`xgoduck_rl` README（sha256 `d73b90c6…`）原文「geometry and inertia **differ from MicroDuck**」；`FAQ`「尺寸相同不证明动力学/语义相同」；`BUILD_GUIDE`「外观相似的舵机未必兼容执行器」。⇒ 与官方 MJCF=XL330、fanhao 清单全 XL330 仿真值三源**再加一源**，我们的"装机实称实量 + 换 plant 重训"是**五源互证**。
- **"离线≠实机验收"**：`ROADMAP`「里程碑要有完成证据」、`FAQ`「实验任务未集成+无硬件证据不算能力」、社区示例「虚构演示、无实际文件」⇒ 与官方「Absent fields are not evidence」、kissqy「源码公开不扩大验收范围」、fanhao「Board acceptance still required」同向。
- **"多 ONNX 技能切换"**：10-09 已记 arduino runtime 8 个 ONNX + 0.2s 预热；本轮 `architecture.md`（sha256 `f8cde5a3…`）全文补出工程细节：**准备期 0.2s 空闲预热、>0.5s 未成取消、跌倒/停止/切模式立即取消、恢复判断先于动作激活避免覆盖同周期跌倒、Roulade 1.7s / Kick 0.4s / Stand 1s 时序、逐帧翻滚记录走 `/api/roulade-timing` 而非实时写日志**、**500ms IMU 过期阈值 / 150ms 主机反馈超时 / Bridge 退避 250→2000ms / 恢复后回 `shadow` 需重新显式使能 / KP/KD 不在上电切换时自动覆盖（仅嘴 ID34 固定 KP10/KD20）**。⇒ 都是 10-09 未记的**非算法工程细节**，可作我们安全层/状态机的参考清单（阈值不照抄，按我们 plant 实测定）。

---

## 5. 自我纠错与过时口径（必须处理）

1. 🔴 **三处过时口径与本轮处理（结论/数值零改动，只盖订正指针）**：现行权威口径是 `tools/hd1910/plant_spec.py:89-93`（2026-10-29 纠正）＋ `workbuddy-history/memory/2026-10-29.md`：BAM `bam/actuators.py` 注册表里 Feetech 唯一合法键就是 `sts3215`，**"actuator 误标 sts3215"是误判**；陆吾 `1910_m6.json` 真正的问题是写了 `max_velocity=100`（≈5730°/s）**覆盖官方 ≈5.22 rad/s 内部限速**。「不用陆吾 m6 作训练主植物」（用台架 m5 / 目标飞特官方 m6）的**结论始终成立**。过时的是理由，且分散三处、彼此还会互相引用传播旧说法：
   - `README.md` §4「不用陆吾 `1910_m6.json`（`actuator: sts3215`）训练」→ 已加订正指针；
   - `tools/plant.py:54-55`「that file is an STS3215 rename…not an HD1910」→ 已加订正注释（**未动任何数值/训练行为**，该文件是训练权威源）；
   - `docs/active/microduck-HD1910软件方案.md` 行 83-87 的 11-03 注引用了上面那句旧注释、据此推"因名字误标"→ 已再加一条 2026-11-11 再订正，保留上段作史料。
   - ⚠️ **查真相链**：`plant_spec.py`（带日期纠正、是 BAM 注册表语义源头）> 引用它的 `plant.py` 旧注释 > 再引用旧注释的方案文档。三者矛盾时按 memory 准则 3「两来源互相矛盾⇒查真相、项集合绑单一权威源码」取 `plant_spec.py`。**本轮只订正理由，不改结论、不改数值、不碰采购域。**
2. 🔴 **本轮自身两个工具 bug（已当场修，记录在案）**：① `while read` 从 Windows CRLF 文件拼 URL 得 `master\r` → trees API 全 HTTP=000/rc=3，去 `\r` 后 200（**同型于 Pass112 `--names` CRLF 坑，再次命中**）；② `$REPO__$PATH1` 被 shell 当变量 `REPO__`（空）→ 5 个 README 互相覆盖，改 `${REPO}__${PATH1}` 重抓。**教训**：抓取脚本的 URL/文件名拼接必须带花括号与显式去 CR，且用 HTTP 状态码 + 逐文件 sha256 自证，不能只看"curl rc=0"。
3. ⚠️ **避免重复记功**：10-09 已深挖 `recovery.py` / `rl_core.py` / `standing_imu.py` / `calibrate.js` / `scs_bus.h` / architecture 时序总纲；本轮对这几项**不重新算贡献**，只补"全文级工程细节"与"此前未抓的仓/文档"。

---

## 6. Scope / 仍不闭合

- 本文是**产品与工程实践深挖**，不改采购判决、不改任何门禁计数/契约、不宣布任何策略能跑。SSOT / `build.py` / 两份手改 xlsx / `.ref/` 生成源一律未动（采购域零改动）。
- 一手来源均为**联网 raw / GitHub API**（抓取日 2026-11-11）；22 个关键文件落在 `out/_tmp_luwu_src/`（`**/out/*` gitignored，不入库），主文关键文件记 sha256 供复核；6 仓完整文件树 JSON 在 `out/_tmp_tree_*.json`（同样不入库）。
- **未取得/未验证**：`Assembly_Guide.pdf` 正文、PCBA  Gerber/生产工艺文本与两张测试视频内容（仅确认存在）、`luwu_os`/`rig_omni`/`xgorider2_rl` 源码未深读（只列定位）、陆吾任何整机/套件的可购买性与实机运行证据（FAQ 明说无套件、无验证模拟器）。⇒ 全部标 `UNVERIFIED`，`UNVERIFIED != PASS`。
- 陆吾硬件是 **Arduino Uno Q + STM32U585 / ESP32-S31 + HLS1910 BAM + QMI8658/BMI270 + 自有 ID**，与路① **Radxa Zero 3W + Rust robotd + HD-1910 + 官方 ID 20-34 + 总线 IMU200** 是**不同线**；本轮所有"可借"仅限算法/工程手法/文档边界，**不构成跨线可移植性**。
- R3（`INCONCLUSIVE_RATE_MISMATCH`，500k 位宽未消）、5 条原始 `INCONCLUSIVE_*`、第 7 条 `INCONCLUSIVE_ROLLER_POLICY` 状态一律不变；社区"轮足改装"板块不构成轮滑策略可下载的证据。

---

## 7. 一手出处清单（可复核）

| # | 一手来源 | 本文用到 |
|---|---|---|
| 1 | `https://api.github.com/orgs/LuwuDynamics/repos?per_page=100&sort=pushed`（HTTP 200，25 条） | 产品矩阵全景、★/许可/推送日 |
| 2 | `.../git/trees/{master|main}?recursive=1` × 6 仓（HTTP 200，845 条目、无截断） | 首次拿到源码文件树，发现 mosaico/mjlab/community |
| 3 | `xgoduck_runtime_mosaico/README.md` `c10b0bd6…` | 单 MCU / C 数组固件 / 50Hz / 2Mbps / BMI270 不进策略 |
| 4 | `xgoduck_runtime_mosaico/main/policy_manifest.json` `16e8b216…` | 61→14 / `[61,512,256,128,14]` / ELU / 197896 权重 |
| 5 | `xgoduck_runtime_mosaico/tools/export_policy.py` `cc8aa008…` | 严格图白名单 + manifest 派生 |
| 6 | `xgoduck_runtime_mosaico/tests/test_parity.py` `ba6c6f75…` | 150 向量逐位比对 / NaN 拒绝 / 权重重定位 / IMU 门控 / 流解析交叉 |
| 7 | `xgoduck_hardware/docs/{TROUBLESHOOTING,FAQ,BUILD_GUIDE,PRINTING,BOM}.md` `aa50bdec…`/`00fa6bb3…`/`8bfda52a…`/`a1f8f8c4…`/`97a1d6f3…` | 故障表 / 诚实边界 / 分级上电 / 独立打印清单 |
| 8 | `xgoduck_hardware/ROADMAP.md` `25885d46…` + 文件树 PCBA 生产文档/测试视频 | 证据级里程碑 / 量产级验证旁证 |
| 9 | `xgoduck_runtime_arduino/docs/architecture.md` `f8cde5a3…` | 准备期/时序/500ms 阈值/退避/KP-KD 不覆盖（全文工程细节） |
| 10 | `xgoduck_community/README.md` `bbe8f701…` + `examples/demo/duck-roller.md` | 四板块平台 / 轮足改装纳为官方板块 / "虚构演示无模型" |
| 11 | `xgoduck_rl/README.md` `d73b90c6…` + `luwu_mjlab/README.md` `7397bc62…` | 几何惯量不同 / 13 任务 / 四足栈 mjlab 1.2.0 |
| 12 | 本仓 `docs/active/microduck-开源复刻项目-参考价值-2026-11-09.md` §2、四源对照 §7、`microduck-Studio借鉴…2026-11-11.md` §0 | 划清已挖(10-09)/本轮新挖边界、避免重复记功 |
