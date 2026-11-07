# MicroDuck 资料地图：从软件到硬件（2026-11-06 第二轮）

> 目标：以 **香橙派 Zero 3W（A733）4GB+eMMC + 15×HD-1910 + 2S** 定案为坐标，
> 把资料链从**训练配方**一路铺到**装配许可**，逐层标出「已有 / 新发现 / 会改判什么」。
>
> **方法**：GitHub 官方 API（`search/repositories`，先确认 `default_branch`）+ codeload tarball 拉全文；
> Hugging Face 走 **`hf-mirror.com`**（本环境直连 `huggingface.co` 被代理 502 挡死，见 §7）。
> 现成语义索引优先：`joeynyc/awesome-microduck`（98 KB `readme.md` + 43 条 `policies.json`）、
> `SaberOnGo/open-microduck`（40+ 篇中文分层文档）。本地副本全在
> `microduck-software/.upstream/`，已确认被 gitignore 覆盖。
>
> 上一轮见 `docs/reference/microduck-开源资料全景-2026-11-06.md`（偏硬件补件与总线协议）；
> 本轮补的是**软件侧全链 + 策略产物层 + 装配许可层**，并修正上一轮一处过度改判。

---

## 0. 一句话结论

**定案不变**（A733 / 4GB+eMMC / UART7@500k / 2S PDB / HAT+IMU / obs61-act14-50Hz /
总线只需 500k / plant 是一等坐标），但本轮找出 **6 处需要改判或新增关卡**，其中两处是
「照抄别的项目配置会 15 颗全错、且所有电气检查都通过」的静默 bug 形状：
**两套不兼容的关节 ID 编号体系**、**HOME 站姿 ≠ 编码器零位**。

另有一条**方法论层**的收获：官方生态自己也把资料分成
「实机验证 / 仿真验证 / 只读示例 / 推断」四档，而 `awesome-microduck` 开篇就写明
**机器人尚未发货（2026-12 目标），绝大多数硬件工具都是 pre-validation**。
这正好是我们「查不到就标明这是推的」纪律的外部版本。

---

## 1. 分层地图（L0 → L6）

| 层 | 我们已有 | 本轮新增 | 对我方的用处 |
|---|---|---|---|
| **L0 索引** | awesome-microduck（上轮只看了硬件章节） | 全文 483 行 / 43 条策略注册表 / `revocations.json` 撤销表 / **Ecosystem Status 证据分级**；`open-microduck` 40+ 篇分层文档与 `version-matrix.md` | 拿到「谁验过真机」的现成语义索引，不必自己造判定器 |
| **L1 训练** | `microduck_rl-develop`、`mjlab-1.3.0`、`bam@62bd8ce`、`ftservo-bam`、本仓配方 | `Qi-hub-dot/microduck-locomotion-diagnosis`（与我们项目同源的诊断）、`Datawhale` 4096×6000 完整基线、`mindthink` 官方 velstand 复现 + slowwalk patch、`mdlab`（Mac CPU）、`playground`（pin `d424a0c`）、`bsprenger/microduck-rl-torch` | 我方 `air_time` 结论获**两条独立路径**背书；拿到可复现基线与低速配方缺陷数据 |
| **L2 策略产物** | 本仓 ONNX、`export.py`、`publish`、`infer_policy.py` | 官方 10 个 ONNX 策略集 + **manifest schema 2 完整契约**、`witcheer` ±1° 齿隙 walk/standup 卡、`RemiFabre` rough-walk、`esp-duck` 量化与开机数值 gate | 解释「我们 B 代 manifest 不生效」= 版本代差；拿到策略导入自检的现成范式 |
| **L3 运行时** | B 代 robotd（`DuckBuddy-main`）、R1–R29 TOML 审计 | 官方 50 Hz 控制环 / 快读慢读地址、`zhuoligetu123/microduck-hd1910m`（Radxa + HD1910M + BNO08x 四模型 + Rust 后端）、`ft1910` SCS 版 | 两套 ID 体系、HOME 语义、只读默认模式、不自动写 EEPROM |
| **L4 总线协议** | 上一轮：DXL `0x8A` vs 飞特 `0x82`、厂商内存表 | 官方源码常量（addr124/12B、addr144/3B@1Hz、**0.229 rpm/count**、0.1V/count、timeout 30ms）与飞特侧（addr56/15B、**0.732 rpm/count**）逐项对照 | 跨链数字不可混用，又多一组实证 |
| **L5 主控/板卡/供电** | A733 定案、community-kit 三块 Gerber、HAT/IMU/PDB | `AI-FanGe/Microduck-build-tutorial`（1705★，Pi Zero 2W + OpenRB-150 + XL330×14 + BNO085 I²C + 成品 6V）、`microduck-lumi` 双供电、`replica-kit` R9 硬件状态表 | 欠压误停的软件缓解手段；「3A 端口不能当 15 舵机电源设计验证」 |
| **L6 机械/装配/许可** | 硬件清单详细接线版、两张 SVG（已降为备用） | `lingzolabs/microduck-hardware-replica`（70 网格 / 39 BOM 项 / **CC BY-NC-SA 4.0**）、`replica-kit` R9 39 件 STL、`playground/hardware` 打印件 | 官方 3D 模型衍生**带非商用限制**，不满足 OSHWA 开源硬件定义；打印件不等于可制造套件 |

---

## 2. 六处改判

### 改判 1（**修正上一轮的过度降级**）：H2「15 颗全 −1」

上一轮我把「全 −1」降成「社区共识值，不是逐颗实测值」。**这个降过头了**，三方要分开看：

| 来源 | 值 | 自述证据强度 |
|---|---|---|
| `replica/tools/servo-web/directions.json` | 15 颗全 −1 | **「2026-09-20 实机逐颗核对」**，网页 ± 按钮逐颗验证 |
| `jyg9/microduck_ft1910` `scs-bus.md` | 单一 `direction=-1` | 只手转过 3 个关节，**「Eleven joints were never watched」**，点名 `left_knee` 可疑 |
| `zhuoligetu123/microduck-hd1910m` `radxa/installation.json` | 腿 10 颗 −1，**`neck_pitch`/`head_pitch` = +1** | 文件自己标 `"calibration_verified": false`、`"purpose": "Read-only wiring/mapping example"` ⇒ **只读示例，不是实测** |

→ **精确表述**：腿部 10 颗三方一致 −1；**头部 5 颗存在分歧**，且给出 +1 的那份自标未标定。
保留 replica 的实机逐颗证据，把「先查 `left_knee`」和「头部 5 颗单独验」并列写进 H2。
（诊断方法不变：用只读工具 `janauto/microduck-calibration-guide` 搬关节看编码器变化。）

### 改判 2（新，最危险）：**两套关节 ID 编号体系不能混用**

| 体系 | 用于 | ID |
|---|---|---|
| **B 代 / 官方 / replica / open-microduck** | 我们 `DuckBuddy-main/duck-control/src/model.rs` `JOINT_IDS` | 左腿 **20–24**、头颈 **30–34**、右腿 **10–14**、IMU **200** |
| **HD-1910 复刻路线** | `hd1910m/installation.json`、`AI-FanGe/build-tutorial`、`replica-kit` | 右腿 **1–5**、左腿 **6–10**、头颈 **11–15** |

而且头部还有第二重错位：`AI-FanGe` 定义 13=`head_yaw` / 14=`head_roll`，
`hd1910m` 定义 13=`head_roll` / 14=`head_yaw`（它自己的 README 与 json 一致，但与前者相反）。

→ 把 `hd1910m` 的 `installation.json` 直接当 B 代 `[bus] joint_ids` 填进去，**15 颗全错位**，
且 ping / 读写 / 电气全过，症状只是「往错方向倒」。这是 `imu-displace` 那句
「装歪 90° 时所有电气检查都通过」的同型陷阱。→ 新增 **H11**。

### 改判 3（新）：**HOME 是模型站姿，不是编码器零位**

三份独立来源一致：
- B 代 `model.rs` 注释：`DEFAULT_POSITION`「必须匹配训练环境的 `HOME_FRAME`」，否则
  **14 个观测槽上有恒定偏移**；
- `hd1910m` README §4：「HOME 是模型站姿，不是舵机编码器零位。每个 ONNX 的
  `default_joint_pos` 给出各自 HOME；输入关节位置使用 `q−HOME`」「不得把 HOME 再校成硬件零位」；
- `open-microduck` 复刻指南：「零位与站立姿态是两个概念；不能把站立角当作编码器零点」。

→ 我方 `probe_joy_policy.py` 已按 `processed = default_joint_pos + action` 处理（正确），
但 `joint_offsets` 只负责**硬件零位**，两者不能互相校准或拿一个去覆盖另一个。
多模型切换时（walk / standup / roll）各模型的 HOME 可能不同。→ 新增 **H12**。

### 改判 4（新）：官方默认 `velstand` 的低速与偏航缺陷，支持我们「heading A/B: no decision」

`mindthink/microduck-policies-repro`（Apache-2.0，官方配方独立复现，pin `bae39f5`，
**全部 sim-only、无实机**）给出 10 次随机起点 × 20 s 的数据：

| 策略 | 0.15 m/s 指令 | 0.3 m/s 速度 / yaw 漂移 |
|---|---|---|
| **官方 velstand v8** | **4/10 不走** | 0.117 m/s / +0.02 rad/s |
| 复现 velstand-2999 | 9/10 不走 | 0.124 / −0.04 |
| slowwalk-3750（加了 `anchor_lin_remap` + `track_lin_fine`） | 10/10 走，~0.07 m/s | 0.145 / **−0.26 rad/s** |

其他硬数据：**所有策略实测前向速度只有指令的 40–60%**；**没有策略能在 0.10 m/s 指令下走**；
3750 在 0.2–0.3 m/s 右漂约 0.2 rad/s（建议真机做闭环 heading 控制）；
3998 起身后卡住 12/360。官方 `velstand` 训于 **`Mjlab-VelStand-Rough-Backlash-MicroDuck`**，
v8 起才支持 yaw 跟踪与顺滑起身（官方策略集 manifest 原文）。

→ 我们此前「heading 奖励 A/B：median +5.87% 但剔除降级后 +0.18%，趋势反转 ⇒ no decision」
得到第三方独立支持：**连官方默认策略在低速下都不稳定**。
更实用的推论：**上板后不要用 0.10–0.15 m/s 的「会不会走」当验证判据**，那是配方缺陷不是硬件故障。
→ 新增 **H13**。

### 改判 5（新）：策略导入需要**数值 gate**，现成范式在 `esp-duck`

`xingxingRealzyx/esp-duck`（ESP32-S3，INT8 权重 / FP32 激活）：
- 9 个官方策略打包、**9.61 ms/pass**、50 Hz **332 ticks 0 overruns**（FP32 版 29.80 ms 只能 ~33 Hz）；
- 每次**开机**和每次**切换策略前**跑量化精度 gate：`cos ≥ 0.9951`、`maxabs ≤ 0.089 action units`，
  host / device 双分布验证；
- 但明确「Servo bus driver / joint feedback / safety layer **not done — bench only**」。

→ 两件事：① 策略推理本身只要 ~10 ms，**A733 八核对 50 Hz 余量极大**（支持我们「上板必测
50 Hz 稳态」的判断，瓶颈在总线与散热不在算力）；② 我方 C8 那个 `deploy61` 归一化分母灾难
（10 个维 1.113e-05、5.7° 头命令 → −35.7 rad 动作）正属于「固定输入跑一遍看动作幅度」
能抓住的形状，而 `publish` 的 `smoke_run_onnx` 只断言 `std(outputs)!=0`，**抖动越大越容易通过**。
→ C 段补 **C9**：导入前用固定观测（含非零 head/body 槽）跑参考实现比对，输出幅度门限 + 余弦门限，
每次开机/切换都跑。

### 改判 6（方法论 + 环境）：证据分级与 HF 访问路径

- `awesome-microduck` 43 条策略里 **17 条 source-only（GitHub）+ 26 条 probe-provider（HF）**，
  并且配套 `revocations.json`；索引明写「标记 *sim-only* 的没有经过硬件验证」。
  `witcheer` 两张 ±1° 齿隙卡都写 **「Not yet tested on a real Microduck」**，
  且 standup v2 的结论是**负结果**（「齿隙成本为零，额外 3000 iter 无可测差异；从背面躺倒仍 0/3」）。
  walk-flat v2 也是作者自己说「4/5 vs 2/5 是小样本提示，训练 `fell_over` 0.496 vs 0.453 没改善」。
  → 这类诚实负对照正是我们要抄的东西，不能只抄「变好了」的数字。
- **HF 直连不通，镜像可用**：见 §7。

---

## 3. 训练侧两条独立路径撞到同一个结论（本轮最强的背书）

| | `Qi-hub-dot/microduck-locomotion-diagnosis` | 我方 `microduck-software/README.md` |
|---|---|---|
| `air_time` | 权重 **3.0**，「门控只看有没有命令，不看有没有真移动」⇒ 原地抬脚白拿分；加「实际速度达指令 30%」门控后 `error_vel_xy` 0.43→0.35 | §332：「**还缺一个 3.0 权重的项：`air_time`**」，上游要求抬脚时间落 0.125–0.3 s，我们没有 ⇒ 拖脚/蹭地/站着都不扣分 |
| 横向漂移 | 体坐标侧向达前向 **2 倍**，跟踪奖励两轴等权 ⇒ 侧向加权 3× 后 0.43→0.21 | 记忆里的「世界系 vs 体坐标系」语义差、`vy=+0.016` 与世界系 `|dy|=0.878` 并存 |
| 指标可信度 | `error_vel_xy` 混 5 种命令模式 + 含 reset ramp-up，稳态 0.07 vs 日志 0.206，**高估约 3×** | 「验证不能问结果对不对，要问这个量动没动、量级是多少」 |
| 依赖钉死 | `bam` 必须下 `uv.lock` 里的 **`62bd8ce`**，下分支 HEAD 因缺 `vin_drop_gain_range` 加载失败且报错看不出版本问题 | 本地 `.upstream/bam-62bd8ce12154340be97e06f7f41a0ca8f116d967/` |

第三方独立确认：`Datawhale/Microduck-RL-4096x6000` 在官方 commit `29e887ec`、
4096 env × 6000 iter、1 h 27 min 的完整快照，`training_summary.json` 里
**`error_vel_xy = 0.4167`**（loco-diag 复现 0.42 / issue #46 报 0.43）、
`air_time_mean = 0.1216`、`peak_height_mean = 0.0141`。三方数字吻合。
它还明写「最后一轮日志值，**不是跨种子或真机的独立 benchmark**」，
与我们「同 seed 不保证轨迹一致 ⇒ N 次重复 + sem」完全一致。

> 该项目另有 `docs/结论核对.md`：逐条标「哪条有源码或数据支撑、哪条只是推断」。
> 与我们「查不到就标明这是推的」是同一套做法，可作为写技术结论的模板。

---

## 4. 策略产物层：manifest schema 2 与版本代差

来自 `hd1910m/microduck/docs/policy-manifest.md`（官方 daemon 文档）与
HF 上 `witcheer/microduck-walk-flat/manifest.json`、官方策略集 `manifest.json` 三处互证：

- **会 gate（拒绝加载）的字段只有 4 个**：`model_api`、`obs_len`（61）、`action_len`（14）、
  `robot.model`（microduck）。
- **`robot.servos: "xl330"` 只用于 display，不 gate** ⇒ 我们 HD-1910 **不会**被这个字段拦下；
  但形状兼容 ≠ plant 兼容（官方 `kp_fw=200` XL330 vs 我们 `hd1910_kp8`），
  「换 plant 必须重训」不变。
- `kind` 三值：`perpetual`（步态 / slot）、`episodic`（一次性技能）、`scripted`（可中断）；
  `command.encoding`：`constant` / `phase` / `posture_flag`，
  其中 phase / posture_flag 会被 `policy add` 拒绝，只能走 `policy load <slot>`。
- 官方策略集：10 个 ONNX（sha `665ae4e`，5.6 万下载）；`velstand` 为默认 walk（v5 起），
  `roller.action_scale=0.8`、`alpha_sitstand` 用 `posture_flag`、`ground_pick` 用 `phase`。
- **版本代差解释**：我们记忆里「`publish` 与 B 代 robotd 不是一条链，manifest 一个字段都不生效，
  对 ONNX 全部检查只有两个宽度（末维 61/14）」——B 代是**旧代读取器**，只从图推宽度；
  schema 2 是**官方新代**的契约。以后不能拿新代 manifest 字段当 B 代的安全约束。

---

## 5. 硬件侧本轮新增事实（补充，不推翻定案）

| 事实 | 来源 | 用途 |
|---|---|---|
| 官方快读 addr **124 / 12 B** @50 Hz，慢读 addr **144 / 3 B** ~1 Hz，**0.229 rpm/count**、0.1 V/count、bus timeout 30 ms | `open-microduck` `robotd-hardware-protocol.md` | 与飞特侧 addr56/15B、**0.732 rpm/count** 对照，跨链数字不可混用 |
| Dynamixel Wizard 建议 **「Shutdown 去掉输入电压错误触发项，避免电池电压波动时误停」** | `AI-FanGe/build-tutorial` BOM 段 | H8 欠压重启的另一条**软件侧**缓解（但需先确认 HLS 对应寄存器语义，未核） |
| 主控 5V 独立降压、不与舵机 7.5V 共正极；舵机 7.4–8.4V 接 **TTL-BUS V1+/G−，不是 RS485 V2/G** | `hd1910m` §1、`microduck-lumi` | 与 H7 供电一致；hd1910m 明确警告其**原始接线初稿有端子连线错误、不可照接** |
| 「3 A 端口或电池广告范围**不能**当作 15 舵机电源设计验证」「数字检查通过 ≠ 实物/电气/整机验证」 | `replica-kit/hardware/CURRENT_HARDWARE.md` | 采购与台架的证据边界 |
| 官方 3D 模型 **CC BY-NC-SA 4.0**，衍生 CAD/渲染/含图 BOM 均带非商用限制，**不满足 OSHWA 开源硬件定义**；缺官方紧固件 BOM/线束/PCB 原理图/公差/装配工艺 | `lingzolabs/microduck-hardware-replica` | 许可审计（补 `ChinaMicroDuck` 那条）；打印件不等于可制造套件 |
| `hd1910m` 默认**只读模式**（不加 `--allow-motion` 不动舵机）、部署**不覆盖已有标定**、**不自动写 EEPROM**、`fetch_models.py` 校验四个模型 SHA256 | `hd1910m` README §6–7 | 与 H9「EEPROM 永不自动写」同向；可直接抄它的安全默认 |

---

## 6. 落地动作（已同步到 checklist）

| 项 | 动作 |
|---|---|
| H2 | 改回「腿部 10 颗实机逐颗核对 + 头部 5 颗有分歧」；保留 `left_knee` 与只读工具，补 `hd1910m` 自标未标定的说明 |
| **H11**（新） | ID 体系：`joint_ids` 必须按 B 代 **20–24 / 30–34 / 10–14**，禁止照抄 HD-1910 复刻线的 1–15；头部 13/14 名称两线相反，逐颗按名字映射而非数组下标 |
| **H12**（新） | HOME ≠ 编码器零位：`DEFAULT_POSITION` 对齐训练 `HOME_FRAME`；`default_joint_pos + action` 与 `joint_offsets` 各管各的，多模型各有 HOME |
| **H13**（新） | 低速/偏航判据：不用 0.10–0.15 m/s「会不会走」验证硬件；官方 v8 本身 4/10 不走、40–60% 速度达成率、0.2 rad/s 右漂是配方特性 |
| **C9**（新） | 导入数值 gate：固定观测（含非零 head/body 槽）比对参考实现，输出幅度 + 余弦门限，每次开机/切换都跑（esp-duck 范式），补 `smoke_run_onnx` 抓不到的 C8 类灾难 |

---

## 7. 资料获取备忘（本环境实测 2026-11-06）

| 路径 | 结果 |
|---|---|
| `https://huggingface.co/...` | ❌ `curl: (7) CONNECT tunnel failed, response 502`（本地代理 `127.0.0.1:22051`）；网页抓取同样 fetch failed |
| `https://hf-mirror.com/api/models/<repo>` | ✅ HTTP 200，返回 sha / siblings / downloads / tags |
| `https://hf-mirror.com/<repo>/raw/main/README.md` | ✅ HTTP 200，模型卡全文 |
| `https://hf-mirror.com/<repo>/resolve/main/<file>` | ✅ HTTP 200，manifest / patch / training_summary 均可取 |
| GitHub `codeload.github.com/<o>/<r>/tar.gz/refs/heads/<branch>` | ✅ 可用（`git clone` 仍被 502 挡） |
| GitHub `api.github.com/search/repositories` | ⚠️ 未认证约 10 次/分钟，本轮后半程触发限流；**先查索引再逐条核** |

已保存：`microduck-software/.upstream/hf-policies/`（6 份模型卡 + API 元信息）；
新增仓库副本 `build-tutorial / hd1910m / open-microduck / replica-kit / hw-replica /
esp-duck / playground / mdlab / loco-diag`，全部被 gitignore 覆盖。

---

## 8. 未核实 / 不下的结论

| 项 | 状态 |
|---|---|
| `hd1910m` `installation.json` 里两颗 +1 是否为真实装法差异 | ✅ **已核实：不是**。`purpose: "Read-only wiring/mapping example"` + `calibration_verified:false`；README:48「示例映射仅供对照，部署使用本机实际标定文件」；+1 的只是 `neck_pitch(12)`/`head_pitch(11)`。⇒ **不构成反证**，H2 仍以 replica 2026-09-20 逐颗实机核对为准 |
| `AI-FanGe` 的「Shutdown 去输入电压错误项」在 HLS 上对应哪个寄存器 | ✅ **已核实**：教程是 DXL XL330 的 `Shutdown(63)`；飞特 HLS 对应 **reg19(0x13) 卸载条件 BIT0=电压保护**（配套 reg20 LED 报警、reg65 状态 BIT0、reg14/15 电压窗、`0x06 RECOVERY`）。**别照抄**：写 EEPROM 要按 H 段时序 + 断电回读双验 |
| `esp-duck` 的量化 gate 门限能否直接搬到 FP32 ONNX | ✅ **已核实并定量反证**：其 `maxabs ≤ 2% of S` 在我方 `p8head_2999`/`resume_5999` 上 **误杀健康**（超 5.2×/6.9×），在病态 `deploy61` 上 **反而放行**（S 被放大 128×）。已重标为 G1–G4 绝对物理量级判据并落成 `microduck-software/tools/hd1910/policy_numeric_gate.py`，`--selftest` 健康 PASS / 病态 FAIL 全绿 |
| `mindthink` / `witcheer` / `RemiFabre` 全部策略 | **sim-only，未上真机**；只作配方证据，不作 sim2real 证据 |
| `playground`（393 MB）、`mdlab`（75 MB）、`replica-kit`（63 MB） | 只读了 README 与关键文档，未逐份解析实验/打印件 |
| 官方策略 manifest 的 `training.dirty=true` 等字段对 B 代是否有影响 | 无影响（B 代不读 manifest） |
