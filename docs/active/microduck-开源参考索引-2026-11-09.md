# MicroDuck 开源参考索引（2026-11-09 全量核对）

_把 2026-11-09 两批链接 + 此前全部开源参考汇成一份索引。每仓标注：**一手/二手、什么线、能借什么、别借什么**。
元数据当日用 GitHub API / 立创页面逐仓实抓（星数/语言/许可/最近推送），非记忆值。星数会漂，判价值看线不看星。_

_⚠️ 许可提醒：`fanhao375/microduck-replica`、`kissqy/Microduck-kissqy` 仓库均**无 LICENSE（NOASSERTION）**——代码/图纸可参考学习，默认无再分发/商用权利。666wsp 厂商包许可明文禁商业再分发。_

_🔄 **2026-11-11 复核增量见 §I**（20 仓 GitHub API 全量验真 + `awesome-microduck` 查全）。§A–H 的 2026-11-09 判决保留作史料；其中 CAD 仓、fanduck、open-microduck、microduck-diy 4 仓在 §I 有实质升级，**采购口径仍以 `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md` 订正㉕为准**。 **软件侧专项见 §J**（2026-11-11 一手实抓 8 仓 + 本地 `.upstream/` 复核）；§I.3 的 `Ley-WL/microduck-observer` 描述已被一手 README 推翻，订正见 §J.3.1。_

---

## 一句话总表

| 仓 | ★ | 是什么线 | 能借 | 别借 |
|---|---|---|---|---|
| fanhao375/microduck-replica | 1624 | **HD-1910+Radxa 实机** | 训练数据清单/IMU 根因/踩坑日志/Studio | 无 LICENSE |
| kissqy/Microduck-kissqy | 462 | **HD-1910 实机** | IMU/调参、中文中控、HAT | 无 LICENSE |
| zhuoligetu123/microduck-hd1910m | 34 | Radxa+FT-SCS(=本地 .upstream/hd1910m) | 第四个模型(翻滚)、BNO08x 路径 | 开机校验/波特率两线别混 |
| Animan-AI/DuckBuddy | 87 | **B 代部署主线(=本地 .upstream/DuckBuddy-main)** | 全套 | — |
| LuwuDynamics/xgoduck_rl | 118 | **mjlab 同栈训练** | 任务定义/backlash/slope_terrain | 硬件线 |
| pollen-robotics/microduck_rl | 2849 | 官方训练仓(上游) | 全套 | — |
| pollen-robotics/microduck_yocto | 12 | 官方 OS(RK3566) | 上板 OS/RAUC 回滚 | 舵机层(XL330) |
| pollen-robotics/microduck-gst-plugins | 23 | 官方 RK MPP 插件 | aarch64 硬编解码 | Pi 上没有 |
| Vottivott/microduck-playground | 131 | 可复现实验集 | running 课程设计 | — |
| microai-lab/microduck-studio | 54 | 中控 GUI | live telemetry 交互 | — |
| fanhao375/microduck-replica-cad | 213 | 复刻 CAD | SolidWorks 图+21页装配书 | — |
| jyg9/microduck-community-kit | 28 | 官方缺的硬件/固件 | imu_to_dxl/banana_pcb | — |
| jlckfb/easyduck | 16 | 泰山派 SCS 线 | A1-A4 资产 | scs.rs 驱动(协议分支不同) |

---

## A. 同硬件路线（HD-1910 / 飞特 / Radxa-OrangePi）

### A1. fanhao375/microduck-replica — 最贴我们的一手实机记录
- `https://github.com/fanhao375/microduck-replica`（1624★，HTML，**无 LICENSE**，2026-11-09 仍活跃）
- 唯一「HD-1910 + Radxa Zero 3W + 同款 mjlab 策略线」上机记录：站立 / 行走 / **前滚翻起身**。
- 关键资产（`docs/` 60+ 篇）：
  - `HD-1910训练前数据清单.md` — 几何/质量/惯量/关节轴；**自标「全是 XL330 仿真值，换飞特四处不同」**：单只 18→21 g、34×20×23 mm、堵转 0.6→1.47 N·m@7.4V、320:1/回差≤0.5°。整机 **737.1 g**（我们记 744 g —— **2026-11-09 已判**：两者是两份不同 XL330 MJCF 的仿真质量，逐刚体加总分别得 737.1 / 744.36 g，差额是几十克级质量重分配抵消后的净 7.26 g，非「几个小零件」；电池是否含入 `trunk_base` 仍无实称。详见 `docs/active/microduck-xgoduck任务定义与整机质量口径核对-2026-11-09.md` Part B）。
  - `HD1910-20261015-IMU乱跳根因与陀螺融合上机.md` — **gyro_fusion 结论的原始出处**（我们此前只引二手）。
  - `执行器选型.md`(26KB)、`踩坑记录.md`(85KB)、`调试记录.md`(45KB)、`官方更新跟踪.md`(375KB)、`HD-1910-M6参数来源.md`。
  - **Microduck Studio 网页中控**（配网/标定/遥控）——我们只有 CLI。

### A2. kissqy/Microduck-kissqy — 单脚独立实机
- `https://github.com/kissqy/Microduck-kissqy`（462★，Rust，**无 LICENSE**，2026-11-09 活跃）
- 「飞特 HD1910 复刻：单脚独立实机、现成动作模型、中文中控、自制 HAT/IMU、三步教程、正常复刻无需训练」。
- IMU 与调参细节我们已有深度核对 → `docs/active/microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md`。

### A3. zhuoligetu123/microduck-hd1910m — 就是本仓 .upstream/hd1910m
- `https://github.com/zhuoligetu123/microduck-hd1910m`（34★，Rust，最后推 2026-10-06）
- **已确认本地 `.upstream/hd1910m` README 与远端逐字相同**，非新资料；可做的是 diff 本地副本是否落后。
- 有我们 P3 缺的**第四个模型：翻滚**；BNO085 I2C 与总线板双 IMU 路径都在这条线。
- 🔴 边界：开机硬校验/波特率(1M)/FT-SCS 与我们 B 代 DuckBuddy 线不同，见记忆「两线不能混」。

### A4. Animan-AI/DuckBuddy — 就是本仓 .upstream/DuckBuddy-main
- `https://github.com/Animan-AI/DuckBuddy`（87★，Rust，Apache-2.0，2026-11-08 活跃）
- 我们部署主线本体：B 代 Orange Pi Zero 3W/A733、`feetech_hls` 500k、`robotd/configd/tofd/updaterd/robotctl`。

### A5. fanhao375/microduck-replica-cad — 装机图纸
- `https://github.com/fanhao375/microduck-replica-cad`（213★，2026-11-03）
- 可编辑 SolidWorks 三维图纸 + **21 页装配安装说明书** + BOM + 打印件（图纸作者「机械行者Robo」）。真做实体机的唯一成体系装配文档。

---

## B. 训练侧（mjlab 同栈）

### B1. LuwuDynamics/xgoduck_rl — 能直接搬的任务定义
- `https://github.com/LuwuDynamics/xgoduck_rl`（118★，Python，Apache-2.0，2026-11-09 活跃）
- mjlab + MuJoCo Warp + PPO + ONNX，与我们同一套栈。
- **BAM 参数 `params/1910_m6.json` 与本地 `.upstream/l_1910_m6.json` 字节完全一致（754 B）**——同源。
- 任务比我们 P3（walk/ground_pick/standup）多：`roller_standup`(前滚翻起身)/`sitstand`/`spin`/`roulade`/`roulette`/`ball_kick`/`velstand`/`velocity_swizzle`。
- MDP 扩展件模板：`backlash.py`（回差项，正对我们齿隙≤0.5°）、`kick_ground_contact.py`、`kick_hip_roll.py`、`standup_hip_home.py`、`slope_terrain.py`。

### B2. pollen-robotics/microduck_rl — 官方训练仓（上游本体）
- `https://github.com/pollen-robotics/microduck_rl`（2849★，Python，Apache-2.0，develop 分支）
- 我们任务包的官方上游；真东西在 `AGENTS.md` 与 `docs/*_policy.md`。

---

## C. 官方 pollen 生态（XL330 线；OS/BSP 层可借，舵机层不可借）

### C1. pollen-robotics/microduck_yocto — 上板 OS 现成答案
- `https://github.com/pollen-robotics/microduck_yocto`（12★，BitBake，Apache-2.0，2026-11-08）
- RK3566 Yocto 镜像，机种表第一行 `microduck-zero3` = **Radxa Zero 3W**。
- 装的是 `robotd/updaterd/mediad(WebRTC)/btd` + 策略集；**RAUC A/B 分区，新槽不健康自动回滚**；电机总线 UART2。
- 命中两个空白：①「上板后 OS 从哪来」；②「updater unhealthy→回滚链」我们从未跑过，镜像里现成。

### C2. pollen-robotics/microduck-gst-plugins — RK 硬编解码
- `https://github.com/pollen-robotics/microduck-gst-plugins`（23★，Shell，Apache-2.0）
- 预编译 aarch64 `libgstrockchipmpp.so`（mpph264enc/h265enc/jpegenc…）+ `webrtcsink/webrtcsrc`。
- 修正 Pi4B 文档一句：`mpph264enc` **Pi 上无，但 RK3566 上有官方预编译包**。
- 附赠一个完美「静默失败」样本：`/dev/mpp_service` 0600 root 时 MPP 插件**静默略过编码器注册**，无报错无日志；同因还产出 `mpi_enc_test` 空文件却 exit 0。

### C3. pollen-robotics/microduck_emotions（32★，Apache-2.0）— 538 MB 表情动作库，做表情再用。

### C4. Vottivott/microduck-playground（131★，Apache-2.0）— 可复现实验集：`running`(速度课程+腾空相要求，正对我们 vx 只达一半)/`parkour`/`stilts`/`swing`/`desk-climb` + 硬件附件（高跷/秋千/梯子/microdock）。**我们 third_party 已有 fork**，工作分支 `tug-of-war`。

---

## D. 中控 / 工具

| 仓 | ★ | 借什么 |
|---|---|---|
| microai-lab/microduck-studio（MIT） | 54 | FastAPI+Docker+MuJoCo 本地控制台，**live robotd telemetry**；我们缺的 GUI 层 |
| jyg9/microduck-community-kit（Apache-2.0） | 28 | 官方缺的硬件电路与固件：imu_to_dxl / banana_pcb / 复刻套件 + 测试工具 |
| avanx/microduck_imu_to_ttl（Apache-2.0） | 3 | 躯干 IMU 板固件仓（配立创 avanx 板） |
| IronSpiderMan/MicroDuckModels | 51 | Three.js 3D 预览器（我们 live_viewer 已有 mesh，重复） |
| boris721/microduck-3d | 10 | STL+MJCF 从官方仓提取（我们已有，重复） |

---

## E. 立创开源硬件（oshwhub，无 GitHub URL）

| 项目 | 协议 | 是什么 |
|---|---|---|
| `f9420/project_zdvhlzkd`「microduck-ext」 | GPL-3.0 | **Radxa Zero 3W 扩展板(HAT)**：2S 电池+AP63205 5V、3 路共用 DATA 总线舵机(半双工)+保险丝/MOS/储能电容、ES8311 音频+NS4150B 功放、UART/I²C 引出、40Pin、四层 30×65mm。未来整机的直接 HAT 参考 |
| `avanx/project_whiijerp`「MicroDuck IMU_to_DXL」 | Apache-2.0 | LSM6DSV16X + SN74LVC2G241 的总线 IMU 从板；**飞特 SCS 固件已完成、DXL 待办**；页面含从 microduck 源码推导的 IMU 安装考证（power_support 前板面、21.9×14.9mm 孔位、`imu.rs:78-83` mount 四元数）——与我们对 `DEFAULT_MOUNT` 的核对一致 |
| `team_wijnbslh/project_jhgdebrg`「imu_to_servo」 | CERN-OHL-S-2.0 | STM32G031+LSM6DSV16X「伪舵机」IMU，Feetech/Dynamixel 两版实物联调，复刻成本约 ¥40。⚠️ 固件自注：**Feetech 同步读需「舵机在前、IMU 在后 [1,200]」，反向有错**——链序是我们 16 节点总线要验的项 |

---

## F. 本地资料（无公开 URL）

- **666wsp 厂商包**：`microduck-software/.upstream/666wsp-microduck-hd1910/`（IMU_TO_DXL v1.2：原理图/固件/手册，ID200/1Mbps/120Hz/8.3ms）。GitHub/Gitee/立创均无公开仓；**许可禁商业再分发**。公开可替代：jyg9/community-kit、avanx/microduck_imu_to_ttl。
- **`.upstream/ft1910`**：本仓 vendored 快照，README 与 `pollen-robotics/microduck` 同源（链接、CI badge 一致）；含 `RemoteIo`/`robotd --sim`/`duck-sim` 脚本——是本次仿真鸭移植的协议来源线。

---

## G. 二手 / 索引 / 文章（引用必须回原仓）

- **joeynyc/awesome-microduck**（209★，CC0，335 条）：查重先翻它，分类含「Ports to Other Simulators」「Training Setups for Specific Machines」「Digital Twins and Benches」。
- **microduckrobot.org**：二手索引站，全部回链 fanhao375/kissqy/Open_Duck_Mini。
- **知乎 p/2080309220314977496**（2026-09-07）：XL330-M288-T 复刻流程（硬件结论不适用）；但印证 `duck-body` + `robotd --sim 127.0.0.1:7801` 是官方既有能力，另给「官方 9 个 ONNX 策略/942 测试/4096env×4000-6000iters/return_delay_time=0 吃掉约 40% 时间预算」。
- **智践行公众号系列四篇**（Sim-to-Real / 真机软件栈+仿真鸭 / 任务定义 / 俯身行礼复盘）→ 已单独落盘 `docs/active/microduck-微信智践行系列四篇-参考价值核对-2026-11-09.md`。

---

## H. 不适用（一句话判决）

_⚠️ 本节为 2026-11-09 判决。2026-11-11 复核后，`7757/fanduck`、`SaberOnGo/open-microduck`、`ScrapMeta/microduck-diy` 及 §A5 的 `fanhao375/microduck-replica-cad` 有实质增量，见 §I；其余各条维持原判。_

| 仓 | ★ | 为什么 |
|---|---|---|
| LuwuDynamics/xgoduck_hardware | 1855 | Arduino UNO Q + 15×Feetech1910：结构件/BOM/装配 PDF 可借，**软件栈不通用** |
| LuwuDynamics/xgoduck_runtime_arduino | 141 | UNO Q 上的 Python+sketch 运行时，与 Rust robotd 两条路线，价值最低 |
| kabilankb/isaaclab-microduck | 15 | Isaac Lab 3.0/Newton MJWarp，明写 14×Dynamixel XL330；栈和硬件都不同 |
| bsprenger/microduck-rl-torch | 37 | 卖点「Mac MPS/CPU 可训」；我们有 4070Ti，无价值 |
| jonathanhawkins/microduck-lab | 159 | 同上（no CUDA GPU） |
| laotawayer/microduck | 23 | 3D 模型复刻，Unofficial |
| ScrapMeta/microduck-diy | 35 | 官方生态扩展玩法（小红书/公众号向） |
| SaberOnGo/open-microduck | 31 | 独立逆向/硬件研究 |
| 7757/fanduck | 83 | 装机分享、物料清单、3D 镜像工作台 |
| TommyZihao/microduck_runtime | 5 | 2026-03 停更 |
| wslengzhicheng/microduck-diy | 15 | 中文 DIY 装机文档（对齐 sesame-robot 细度），镜像见 AI-FanGe |
| jlckfb/easyduck | 16 | 泰山派 RK3566 SCS 1M 线 → 见 `microduck-SBC选型-四板对比-2026-11-09.md` §3.2 |

---

## 行动建议（按性价比）

1. ~~抄 xgoduck_rl 的 `roller_standup` + `sitstand`~~ → **已撤销（2026-11-09 核对）**：这些任务本地训练包早已注册；`roller_standup` 是带轮版、HD-1910 不适用；`sitstand` 是坐↔站；跌倒起身 `standup` 本就在 P3。详见 `docs/active/microduck-xgoduck任务定义与整机质量口径核对-2026-11-09.md` Part A。
2. **`backlash.py` 对照我们齿隙设定（≤0.5°）**，看是否同一量级 —— 仍有效。
3. **microduck_yocto 作为上板 OS 候选**（microduck-zero3 机种就是我们的板）；updater RAUC 回滚链值得在真机上跑一次。
4. **读 fanhao375 `踩坑记录.md`/`调试记录.md` 目录**挑未踩坑，避免重复。
5. ~~核 737.1 g vs 744 g 口径~~ → **已闭环**：两份不同 XL330 MJCF 的仿真质量（744.36 / 737.1 g），「差 6.8 g = ToF+摄像头+螺丝」解释作废；电池是否含入 `trunk_base` 仍无实称。详见同一文档 Part B。

---

## I. 2026-11-11 二十仓复核 + `awesome-microduck` 查全增量

_方法：GitHub 官方 API `/repos/{owner}/{repo}` 逐个验真（**20/20 全部真实存在**，无聚合站式假名），再抓 `/readme`(base64) 与 `/git/trees/{branch}?recursive=1`。星数/许可/推送日为 2026-11-11 实抓，非记忆值。原始快照：`C:\Users\hejih\.wb_tmp\repos20_meta.json`、`repos20_detail\`。_
_**本节的定位是补证据、不改判**：采购/货源/价格判决一律仍以 SSOT 订正㉕为准，阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579` 全部未动。_

### I.1 复核结论（对照 §A–H）

| 仓 | 11-09 判 | 11-11 复核 | 增量 |
|---|---|---|---|
| `fanhao375/microduck-replica-cad` | A5「装机图纸」 | **⬆️ 升级为最高价值一手** | 见 I.2 |
| `7757/fanduck` | H「装机分享」 | **⬆️ 升级（板件设计）** | DCHUB v1.1 全套 KiCad/Gerber/BOM（43×13 mm）+ 板件制造包（Robot HAT / 电池触点板）；作者自述「无稳压与保护电路、实物负载及 IMU 接线待验证」⇒ **只作几何对照，不进 BOM** |
| `SaberOnGo/open-microduck` | H「独立逆向」 | **⬆️ 方法论可借** | 证据标签体系（官方规格/官方源码/仿真模型/社区重建/实测/待确认，与本项目 `INCONCLUSIVE_*` 同型）、`community-bom-reconstruction.md`、`sim-to-real-parameter-reference.md`；⚠️ 2026-09-20 后停更 |
| `ScrapMeta/microduck-diy` | H「扩展玩法」 | **⬆️ 固件源码可借** | 完整 `imu_to_dxl` 固件（STM32G031F8P6 / LSM6DSV16X，含 `imu_pack.c`/`dxl_slave.c`/上位机 smoke test）+ wiki 的 IMU-to-DXL BOM 推导、`xl330-vs-feetech-servos.md` |
| `zhuoligetu123/microduck-hd1910m` | A3「本地 .upstream/hd1910m」 | 维持 + 补两条 | ①接线表「7.4~8.4V → TTL-BUS 的 V1+/G−，**不是上方 RS485 的 V2/G**」= `J13/J14=TTL` / `J3/J11=RS-485` 的**第二个独立来源**（首个为 kicad pad net + 卖家 UI）；②README 自承「原始接线初稿存在端子连线错误」⇒ 引用只用校正版表格。**⚠️ 该仓是 B 代线（ID 1–15 + BNO08x I²C4），与路①（1M 官方 ID 20–34 + 总线 IMU200）不是一条链，两线不混** |
| `jyg9/microduck-community-kit` | D「硬件/固件」 | 维持 + 补工具 | `firmware/v1/host/upgrade.py status` 是**只读认板/查固件版本**的现成工具，可用于人人 ¥80 `IMU` 的 `INCONCLUSIVE_LIVE_IDENTIFY` 初查；⚠️ 其固件是 **GD32F303CC**（`gd32f303cc_*.ipkg`），与 fanhao/replica 的 **STM32G031F8P6** 不是同一实现，**升级包绝不可混刷**。该仓接线图是「banana_pcb→dxl_hub→左腿/IMU/右腿」的信号+供电 HUB 架构，与订正㉕「不设独立信号 HUB、信号走 HAT J13/J14 菊花链」**不同，不照抄** |
| `pollen-robotics/microduck_yocto` | C1「上板 OS」 | 维持 | 官方 `microduck-zero3` 机种确实支持 Radxa Zero 3W 烧 SD；但镜像内 daemons 是 **Dynamixel 50 Hz 控制环 + 官方 XL330 策略**，HD-1910 需飞特总线补丁（见 community-kit 的 `jyg9/microduck_ft1910` 基于 0.16.0 打补丁）⇒ **不能直接刷来带我们的舵机**。可借 RAUC A/B slot-health 判据源码（准则7「自动回滚类承诺回源码」） |
| 其余 13 仓 | H 原判 | **维持** | `kabilankb`/`bsprenger`/`jonathanhawkins`/`laotawayer`/`wslengzhicheng`/`TommyZihao`/`IronSpiderMan`/`boris721`/`microduck_emotions`/`MicroDuckModels`/`microduck-gst-plugins`/`Vottivott`/`microai-lab` 均无改变我们判决的一手证据；`boris721`/`bsprenger`/`Vottivott` 的 STL 与本地 `cad/microduck-upstream-stl/` 重复 |

### I.2 CAD 仓（`fanhao375/microduck-replica-cad`）——本轮最重要增量

**🔑 身份闭环（一手 README 行 41–62）**：图纸、BOM、21 页装配说明书全部由「**机械行者Robo**」建模整理；其抖音号 `1852366168` 明写 **「人人可做机器人」**。⇒ 淘宝「人人可做机器人」店（HAT ¥140 / `IMU` ¥80 / HUB 分线板 ¥36 / 金属结构件 ¥45）与 fanhao 的 CAD、BOM、装配教程是**同一套人马/同一套设计**，不是两家供应商的巧合同名。这解释了订正㉕「都用人人的」与 fanhao 复刻线为何严丝合缝，也解释了 `probe_out.txt` 行 44–47 四样同商品页 `id=1095772009248`。

**新增可用一手资产（均 2026-11-02 版）**：
- `BOM/装配BOM-机械行者Robo-2026-11-02-带采购链接.xlsx`：**33 项打印件 + 23 项外购件**、带采购链接（本地只读副本 `docs/archive/装配BOM-机械行者Robo-2026-11-02-带采购链接(1).xlsx`）。
  - ⚠️ 作者 README 写「24 项外购件」，表尾与实际行数为 **23 项** ⇒ 按实际行数，README 笔误不改我们任何表。
- `打印/microduck-飞特版-BambuStudio2026-11-02.3mf`：飞特版排好盘打印工程（Bambu P2S / 0.4 喷嘴 / PLA Basic / 0.2 mm / **5 盘 52 个对象**）；软下巴、软嘴顶部、合体轮胎须 TPU，不能统一 PLA。
- `安装说明书/microduck装配安装说明书.pdf` 21 页 + 23 张组件/爆炸图 + B 站 8 集装配视频（已更 6 集）。
- **v2.2 SolidWorks 包内含 PCB 3D 模型 `3D_imu_to_dxl`、`3D_wire_hub`、`3D_POGP_PIN`**（418 MB Releases 附件，内嵌 10 个 STEP）⇒ 这是目前唯一可能给出「人人 HUB ¥36 板框尺寸 / 双铜柱是否对准 NP-F550 电池孔 / 是否属 34 mm 安装族 / `banana_pcb_locker` 能否沿用」的一手几何来源，对应 `INCONCLUSIVE_DIMENSION`。**尚未下载核验，仍标记未闭环。**
- `face_part` 的 **`-FT1` 变体**（2026-09-30）把摄像头孔距改成直装**瑞莎 Radxa 原版摄像头** ⇒ 我们选 IMX219 + Radxa，打印面部件**必须挑 `-FT1`**，否则孔距不对。
- 命名坑（作者自己标注）：`np_f970_NPF970电池` 实为 **NP-F550**，上游网格包围盒 **70.8×38.6×20.6 mm**（≈21 mm 厚标准壳）；真 F970 约 60 mm 厚、300 g 装不进。⇒ **从第二个独立来源印证 Pass97 判决**：`power_support` 按 21 mm 厚做，TPCELL 25.5 mm 厚壳装不进；夹座仍须按到手实物卡尺重定。
- 许可：**图纸/说明书/文档 = CC BY-NC-SA 4.0**（上游 STL 衍生，署名·非商业·相同方式共享），与软件层 Apache-2.0 分开记。我们「仅个人使用」匹配；商用须另解。

**🔑 「金属结构件（共 7 个）¥45」对应件的推断（非卖家确认）**：BOM 打印件区 F 列有 4 类标「**建议铝合金**」，数量恰为 `颈部×2 + 躯干底座×1 + 上腿加固板×2 + 轴承滚轮×2 = 7 件`；另有 2 件标「建议改用 TPU」不计入。外购行「结构金属件」备注「一部分 3D 打印件强度不够，需要改成金属」。⇒ **7 件高度吻合，但这是按 BOM 备注数量推的，未获卖家/实物确认，不写进 SSOT、不改采购表**；到货逐件核对后再闭环。核验脚本 `C:\Users\hejih\.wb_tmp\verify_bom_p25.py`（带负对照，13/13 PASS）。

**订正㉕四样价格二次坐实**：BOM 行 39–42 分别为 HAT ¥140 / `imu_to_dxl` ¥80 / HUB(含 banana PCB) ¥36 / 结构金属件 ¥45，四行**同一商品页 id=1095772009248**，与 `probe_out.txt` 一致。⇒ SSOT 订正㉕价格与全员店主路径不动。

**作者 BOM 与我们 BOM 的差异（仅提示，不改判）**：作者列而我们的「照着买」表未列的有——盖世小鸡手柄 ¥72、三种轴承（10×15×3×3 / 16×22×4×11 / 6×12×3×4）、M2/M2.5 自攻螺丝 5 种、鞋底防滑垫 ¥16、AMP2.0 双头转接线 ¥2（作者标「调试用」）。另作者取 Radxa **2G ¥309**（注「1G 也可」）、NP-F550 **单电 ¥47**，我们取 1G ¥179 + 已有 TF、双电 ¥118。⇒ 若需补齐标准件/手柄，须**用户拍板**并回写 SSOT；**手删 3 行不恢复**的红线不变。

### I.3 经 `joeynyc/awesome-microduck` 查全：比原 20 仓更对口的 HD-1910 专用工具

_该索引 §「Community replicas / hardware」(行 410–454) 派生；~~均未实抓源码，仅索引描述~~ → **🔄 2026-11-11 按 §J 已实抓其中 8 仓一手 README，且 `Ley-WL/microduck-observer` 的本表描述被推翻（见 §J.3.1）；本表其余条目仍仅索引描述**，用前须逐仓回一手。索引自述生态状态：机器人仍是 pre-hardware（官方 2026-12 才发货），面向硬件的工具大多 pre-validation，只有少数社区复刻能用官方策略站立行走 ⇒ 别把这些仓当「已验证」。_

| 仓 | 为什么对口我们当前 `INCONCLUSIVE_*` |
|---|---|
| `JieJie-H/microduck-servo-numbering` | 3D 高亮关节 + **逐颗扫描/写入/回读舵机 ID** ⇒ 闭环「15 关节实际 ID 表仍需 `identify`」 |
| `janauto/microduck-calibration-guide` | **只读**关节方向检查（动画期望方向、手动转动看编码器变化，**从不下发指令**）⇒ 零位/方向校验的安全做法 |
| `lxm/microduck-maker` | 逐关节零位标定 + 备份/恢复 + 舵机编号/装配检查（MIT；附带 kissqy 参考码与 CAD 衍生模型保留非商业条款） |
| `Ley-WL/microduck-observer` | 只读 web 仪表盘：BNO085 姿态 + 15 舵机 + **shadow ONNX 推理对照实时数据**，永不下发运动指令 ⇒ 正好解准则6「无第三方观测者 ⇒ 没发/听不懂不可区分」，是 `INCONCLUSIVE_LIVE_IDENTIFY` 的观测者工具 ⚠️ **【2026-11-11 一手 README 推翻本行，订正见 §J.3.1】**：它并非只读、IMU 也非 BNO085，而是带实机控制的完整 Rust 平台。 |
| `Ley-WL/microduck-rl` / `Ley-WL/microduck-guide` | HD-1910 复刻 MJCF + 已发布 1910 M6 执行器参数 + locomotion/recovery/dance；15 模块装配/舵机 ID/打印清单。作者自述鲁棒性评测仍有失败、非硬件签收 ⇒ 对「HD-1910 须重训」直接有用 |
| `thejerrycheng/microduck_replication_feetech` | kissqy 风格 HD-1910 三策略，Isaac Lab 3.0 + Newton BAM，保持官方 61-in/14-out 可 `robotctl policy load`；**仅训练 clip、Sim-only**（MIT） |
| `harrysungit/microduck-software` | **fanhao375 HD-1910 复刻的软件侧**：runtime fork 修正、IMU 兼容、Studio web console，另有 `harrysungit/microduck-rl`（ROCm 额外训练任务） |
| `jaggerzhong/microduck-hub-board` | 被动 4 口总线 HUB **23×34 mm**、孔位对齐髋部舵机壳、留大电容位，Gerber/KiCad/下单说明，CERN-OHL-S-2.0 ⇒ 又一个 HUB 几何对照（与 Fanduck DCHUB 43×13、人人 HUB ¥36 三者互不相同，勿混） |
| `Juxi-Technology/imu-displace-microduck` / `MHDuck/microduck` / `AleksWolf/kryakva` | I²C ICM-42670-P / BNO085 躯干 IMU 补丁与 runtime fork；kryakva 是 15×HD-1910 + Radxa + 自绘 PCB + 为该舵机重训策略的实机（站立/行走/转向）。⚠️ Juxi 数据路径硬件验证但**未接 robotd**；均属 I²C 线，与路①总线 ID200 不同 |
| `deanxizian/MicroDuck-Replica` / `tachytelicdetonation/microduck-replica-lab` / `qianen6/microduck-replica-kit` | 精炼 HD-1910 打印件（改颈/腿/头配合、可动嘴）、装配浏览器、分阶段 BOM；几何层参考，许可多含 CC BY-NC-SA 非商业 |

### I.4 边界（避免张冠李戴）

1. **两线不混**：`zhuoligetu123/microduck-hd1910m` 与 `MHDuck` 等是 ID 1–15 + I²C IMU 的 B 代线；路①是 1M + 官方 ID 20–34 + 总线 IMU200。名字都叫 HD1910/Radxa，不可互抄 ID 表、波特率、IMU 输入路径。
2. **XL330 线不套飞特**：Fanduck、官方 Yocto、`boris721`、`Vottivott` 的 STL/策略基于 XL330；CAD 仓明写「两种舵机舵盘凸/凹不同，**8 个配合件不能混用**」。
3. **Sim-only 不算实机签收**：awesome 索引里大量策略仓明确标 sim-only；`thejerrycheng`、`Ley-WL` 作者都自述未经硬件验收。
4. **本节未改任何采购判决**：未回写 SSOT、未碰磁盘采购表与 `build.py`、未恢复手删 3 行、阶段0 ¥99 不变。
---

## J. 2026-11-11 软件侧专项（一手实抓 8 仓 + 本地 `.upstream/` 复核）

_**方法**：GitHub API core 额度本轮耗尽（`remaining=0`，09:29 reset），`raw.githubusercontent.com` 超时；改走 GitHub 仓库页一手 README + **先穷尽本地 `microduck-software/.upstream/` 已存的 28 个上游仓**。实抓 8 仓一手 README：`harrysungit/microduck-software`、`harrysungit/microduck-rl`、`Ley-WL/microduck-observer`、`digows/microduck-twin`、`JieJie-H/microduck-servo-numbering`、`janauto/microduck-calibration-guide`、`lxm/microduck-maker`、`lukegao209/microduck-remote-policy-server`；`git ls-remote` 验真不耗 API。证据核验 `C:\Users\hejih\.wb_tmp\pass101_sw_evidence.py`：55 项断言 + 4 组负对照全绿，rc=0。_

_**总判决**：这批软件仓最值得借的不是代码，是**验证契约与门禁语义**——恰好逐条对上本项目 10 条准则。所有策略/镜像/固件层的「能跑」声明一律不作实机签收；路①（1M + 官方 ID 20–34 + 总线 IMU200 + Radxa 1GB）与 B 代线不混。_

### J.1 最高价值：三套可直接搬的验证契约

| 来源 | 可借的契约 | 对上我们哪条准则/悬案 |
|---|---|---|
| **`harrysungit/microduck-rl`**（Apache-2.0） | ①训练前先定义「什么算成功」的 acceptance gate，在**导出的 ONNX** 上跑，且分 clean world / trained world 两种；②**独立 sim2sim**：同一 ONNX 放纯 MuJoCo CPU + 自带 servo loop，脱离训练世界；③判语 `ACCEPTED / FAILED / UNVERIFIED`，**UNVERIFIED 明确不算 pass**；④`--env.sim.njmax 160` 预算超了抛 `ConstraintBudgetExceeded`，不静默丢约束行；⑤`env/pins.toml` 钉死 Pollen / AMD Warp / torch / `uv.lock` 每个源 | 准则3（两独立算法互算）、准则4（门禁阈值不取自被测量、负对照）、准则7（版本混用）；直接服务训练线 #76「各动作 ≥3 seed sweep」 |
| **本地 `mdlab/microduck_local/tests/golden_store.py`**（已在盘） | bit-exact golden 只在能钉硬件的 Apple Silicon 上是契约，别处按 CPU 型号分两档 tolerance；**没有该平台录制就 SKIP 而非失败**；`MICRODUCK_GOLDEN_BITS=0` 强制关掉精确分支，专门验证「宽松分支仍能抓到真实改动」；golden 记录上游模型 sha 与库版本，模型重导出导致数字移动判为 recapture 而非 regression；文件头详录 hosted runner 同 CPU 型号但 reduction order 不同 ⇒ 11 条 bit 断言失败的 last-ulp 证据 | 准则4「自检必须带负对照」的最完整现成范本；准则3「读数与算术矛盾先查读数」 |
| **本地 `loco-diag/`**（已在盘） | 复现官方 issue #46 后找出七组对照实验漏掉的三件事：`air_time` 门控只看「有没有指令」不看「实际有没有前进」⇒ 原地踏步拿最大正奖励（加前进门控后 `error_vel_xy` 0.43→0.35）；侧向漂移达前向 2× 而误差等权（侧向×3 后漂移降到 1/5）；`error_vel_xy` 混 5 类指令模式 + 整回合累积 ⇒ 稳态逐帧实测 0.07 而日志 0.206，**高估约 3×**。作者自列 6 条局限，首条即「没有多种子重复」 | 准则3/4（验证要问量动没动、量级对不对，不问结果对不对）、准则5（世界系 vs 体坐标系教训）、`AGENTS.md`「正奖励别门控坏状态」；直接给 #76 的对照实验清单 |

⚠️ `harrysungit/microduck-rl` 自述 **「No policy from this repository has run on a robot yet」**、固件 `P = 5` / `0.82 kg` 整机，与我们 `hd1910_kp8` plant 不同 ⇒ **借门禁，不借权重、不借 plant**。

### J.2 直接解当前悬案的工具（上机前用）

**J.2.1 15 关节 ID 表 + EEPROM 写号：`JieJie-H/microduck-servo-numbering`**（代码 MIT / 3D 模型 CC BY-NC-SA 4.0）

- 给出完整路① ID 表：`10–14` / `20–24` / `30–34`；十位=部位、个位=从躯干往末端（0 髋 yaw → 4 踝）；**`200` 是 `imu_to_dxl` 板固件写死，不要配给舵机**。推荐写号顺序 `10→11→12→13→14→20→…→34`。
- 写号流程与本项目 EEPROM 判决**完全一致**：解锁 EEPROM → 写 ID → 加锁 → `0x08` 重启 → ping 新 ID、回读寄存器、确认旧 ID 消失 → **断电重启复核**；FAQ 明写「EEPROM 没锁上会变回旧 ID」「写 ID 后应答可能仍用旧 ID」。
- 安全边界：一次只接一颗（总线上多颗会一起改，工具直接拒绝）；只改 ID 和寄存器 19 的过压 bit0 / 过流 bit3，**不碰波特率、模式、PID、限位、中位**；`--fake` 起虚拟舵机 + `selftest.py` 无硬件自检；协议实现 `test_support/feetech.py` 直接来自 `fanhao375/microduck-replica`（Apache-2.0）。
- 契合当前缺口：补上「安全层温/流只观测、无关节限位」之外的**过压/过流卸载**；`harrysungit/microduck-software` 的 `tools/hd1910_protection.py`「voltage and over-current unload conditions」是第二个独立来源（但未给寄存器号，按 reg19 待实测）。

🔴 **J.2.2 三来源「左右腿」文字定义互相矛盾 ⇒ `INCONCLUSIVE_LR_LABEL`**

| 一手来源 | 10–14 | 20–24 | ID 数字集合 |
|---|---|---|---|
| `JieJie-H/microduck-servo-numbering` | 右腿 | 左腿 | 10-14 / 20-24 / 30-34 |
| `Ley-WL/microduck-observer` | 右腿 | 左腿 | 同上 |
| `janauto/microduck-calibration-guide` | **左腿** | **右腿** | 同上（自注「左右按机器人自身定义」） |

- **数字 ID 三来源完全一致，文字左右 2:1 冲突**；janauto 特意声明视角，很可能是「机器人自身视角 vs 观察者视角」的镜像差异，**不是谁抄错**——不武断判对错。
- 结论：**装配/标定/写文档一律只认 ID 数字，不认「左/右」文字**。这正是「15 关节实际 ID 表仍需上机 `identify`」的第二个理由（第一个是作者可能改排位；JieJie-H 自己也记「第一台机器历史上嘴用过 29，新复刻按设计表用 34」）。
- 核验：三来源 ID 数字集合差集为空、左右标签冲突检测为真；负对照「抹平冲突后检测器不再报」+「混入 B 代 ID 1–15 后一致性断言翻红」均 PASS。

**J.2.3 只读方向校验：`janauto/microduck-calibration-guide`**（原创 MIT）

- **没有任何运动 / HOME / 扭矩启用 / Zero 配置写入接口**；「确认校准」只更新本页方向映射，**导出 JSON 明确不能直接覆盖 `hd1910-calibration.toml`** ⇒ 与「用户手改配置禁止覆盖」同型。
- 门控很值得抄：非新鲜反馈、非 commissioning、任一扭矩开启、存在活动运动、配置变化、周期倒退都阻止确认；需 3 次稳定新反馈；**原始负数或跨圈计数不悄悄取模，导出标记异常**；示范的 15° 明说是视觉放大、不是实物动作目标。
- 测试分三层：采样（离线/扭矩/模式门控、伴随运动、方向推断）、几何（零姿态/下嘴隔离/回零）、服务（只读 HTTP 边界）。需 V167 中控处于 commissioning 全卸力 ⇒ 依赖 kissqy 个人非商业许可资产。

**J.2.4 零位/装配工具集：`lxm/microduck-maker`**（原创 MIT）

- `servo-debug`（USB 直连 HD-1910 搜索/微调/反馈曲线/校零/参数备份）、`calibrator`（逐关节零位 + 回零 / HOME + 备份）、`servo-guide`（15 颗 3D 对照）、`zero-fixture` 6 件 STL、颈部连接板 KiCad。
- **`--demo` 默认模拟模式**；`scripts/validate.py` 校验 69 个装配变换 + 15 个舵机编号 + 网格/静态资源哈希，**离线验证不连机器人、不操作串口、不上传程序、不改写实机**。
- 明写「**机械零位和站立 HOME 是不同概念，3D 参考按钮只改变画面**」⇒ 本项目「HOME=模型站姿非编码器零位」判决的**第二个独立来源**。
- ⚠️ **其固件是 Orange Pi Zero 3W / Allwinner A733 / 1GB / PCB V1.5 实验镜像**（基于 kissqy `d4d21c1`，作者自述「已离线校验，尚未验证实机启动」）= **路② B 代线** ⇒ **工具可借，固件不可刷**。
- 许可分层写得很清楚：MIT 不覆盖 kissqy 个人非商业参考码、CC BY-NC-SA 4.0 的 CAD 衍生模型、来源未确认的零位支架 STL；并再次署名「机械行者Robo、fanhao375、Pollen Robotics」⇒ 与 §I.2 身份闭环互证。

**J.2.5 同源软件总入口：`harrysungit/microduck-software`**（Apache-2.0）

- `components.toml` 钉死三组件：`harrysungit/microduck-rl`（训练）、`harrysungit/Microduck-kissqy`（robotd fork）、`fanhao375/microduck-replica` 的 `software/studio`（Studio）；本仓放 IMU 兼容、板级 bring-up、舵机工具。
- 7 步流程里第 2 步「acceptance gate + sim2sim 双过才上机」、第 6 步 `hd1910_protection.py` 上电前开过压/过流、`releases/` 用「一组在真机上一起跑通过的组件版本」定义发布（**目前为空：no policy from this project has run on a robot**）。
- 与本项目关系：`software/studio` 我们本地已整份持有（见 J.3.3），`features/imu/` 的认板清单可作 `INCONCLUSIVE_LIVE_IDENTIFY` 的检查表；**不是新镜像来源**。

### J.3 观测者 / 部署链

**J.3.1 ⚠️ 订正 §I.3 的 `Ley-WL/microduck-observer` 误述**（一手 README 推翻索引描述）

- 旧描述「只读 web 仪表盘、BNO085 姿态、shadow ONNX 对照、永不下发运动指令」**不成立**：它是 Vue3 + Rust(Axum/Tokio) + BLE 的**全功能控制平台**，含实机控制、坐下/站立/起身/拾取/踢球、标定、模型管理、舵机写入；IMU 是 **正点原子 MS901M UART @115200 (`/dev/ttyS9`)**，不是 BNO085；主控 **Radxa ZERO 3W 2GB**（我们锁 1GB）。
- 它是路① ID 体系（20–24 / 10–14 / 30–34、1 Mbps）但 **IMU 走独立 UART** ⇒ 又一个「共享 ID 契约 ≠ 同输入路径」的例证。
- **可借的是架构，不是部署**：①串口唯一拥有者（网页/App/推理不另开串口，串行处理）；②模型合同显式化（ONNX + metadata 核对哈希、观测维度、关节顺序、归一化、执行配置；不同模型不强套同一滤波/增益）；③遥测带时间戳/序号/有效性/过期状态，**心跳不把旧传感器数据刷成实时**；④共享标定用 revision 防并发覆盖；⑤可验证发布（候选只读核查、文件哈希、原子切换与回滚，升级保留模型/标定/增益/BLE 身份）。
- 实测记录同样诚实：998/999 帧完整但单帧缺 23/31；HTTP 中位 11.14 ms 是 **loopback 不是端到端**；明写「不能用模型数值一致或仿真通过代替运动结果」；大量功能标注「本地实现，未部署实机」。
- ⇒ **解「无第三方观测者」准则的仍不是「有个仪表盘」，而是「状态来自回读 + 带有效性/过期」这套语义**；具体工具我们本地 `replica/software/studio` 已实现（J.3.3）。

**J.3.2 `lukegao209/microduck-remote-policy-server`**（实验分支，非生产安全）

- 加载 ONNX 时校验**单输入 `obs [1,61]` / 单输出 `actions [1,14]`**，并明写 **normalizer 必须烤进图** ⇒ 本项目 obs61/act14 + 「normalizer 须烤进图」的**第二个独立来源**。
- 「请求了未加载的网络 ⇒ **不发任何响应** ⇒ robotd 回退本地 ONNX」：把「听不懂」编码成协议行为而不是靠猜，正对准则6「零应答先问接收方听不听得懂」；本地侧在启动/丢失/超时/畸形输出/策略切换时立即回退。
- `--fake-zero` 返回 14 个零动作偏移专测传输；Rust ORT 与 Python ORT 对同一 61 维观测输出 **bit-identical（`max_abs_error = 0`）** ⇒ 准则3「两独立实现互算」的范本；协议依赖钉死 commit `4c131a0010…`，让协议漂移变成构建期决策。
- ⚠️ 两个 backend **都不是 production-safe**，UDP 无认证无加密，作者明写「Physical two-host Wi-Fi and tethered powered-robot acceptance remain required」；`--fake-zero` 的零偏移是 HOME 不是步态。**只借契约与回退语义，不上整机**。

**J.3.3 本地已持有、最该贯彻的范本：`replica/software/studio/README.md`**

- 「页面上的一切状态都来自 robotd 的**回读**：『已卸力 ✓』要等 busStatus 里扭矩确认关了才显示，**不是『按过了』就算**」⇒ 准则6 的一手答案，就在我们主路径仓库里。
- `estop.py` 状态机 `ready → pending → confirmed / unavailable`，只认「卸力回执之后才发出的」回读；`dev/record_robotd.py` 只读录真机回包 + `fake_robotd.py` 回放 + `tests/fixtures/now-20261018.jsonl` ⇒ 无硬件也要真测 CLI/页面的范本（准则5「只测内部函数不测 CLI」）。
- `servo-session.json` 记录谁开了总线，Studio 崩溃重启后自动只读接管；每 5 秒查 robotd socket，被手动起来就记错误并关总线（不写舵机）⇒ 「还有谁写它」的第二写者处理。
- 摄像头只读 `hello` 判服务在线，**不把配置文件或测试画面当真实硬件**；ToF 的 fake/sim 明确标模拟；状态 10 秒过期清空 ⇒ 与 `INCONCLUSIVE_*` 同型。
- `deps/VERSIONS.txt` 钉死 Python 依赖；`docs/软件功能与升级总账.md` 26 个功能组逐组写「实现 / 上机 / 镜像 / 动作效果分别记录」，并自警「历史 UI 笔记存在过期状态」⇒ SSOT 思路在软件侧的对应物。

### J.4 印证既有判决、不必新借

- **`digows/microduck-twin`**（Apache-2.0）：与我们已做的 `robotd --sim` + `body_server.py` **同型且更完整**，但把「--sim 验不了什么」列得更细：Dynamixel 总线驱动、BLE、相机 ISP + rkaiq 3A、NPU、硬件编码器 + RGA 路径——「They ran a week of real bugs past the twin and it would have caught none of them」⇒ **再次坐实「仿真鸭不能消 R3」**。另有 `deadman` 500 ms（与 `deadman_ms=500` 一致）、`body_server.run` 包裹 viewer 而非 fork、unix socket 路径 ≤104 byte 的坑、`deps.env` 钉上游版本。⚠️ 官方 XL330 线、无策略重训，**不照搬策略**。
- **两个「Microduck Studio」同名不同物**：`microai-lab/microduck-studio`（MIT，电脑端 Docker + FastAPI + MuJoCo + live robotd telemetry，等 `contract probe passed` 才报 URL）vs `fanhao375/microduck-replica` 的 `software/studio`（板载网页中控，`/run/robotd.sock` 接口 v40）vs `Ley-WL` 的「模型管理」页。**认名借码必带仓名 + 部署位置**。
- 官方 `microduck_rl-develop`、`playground`、`imu-displace`、`ft1910`、`community-kit`、`hd1910m`、`open-microduck` 本地 `.upstream/` 已整份持有，§A–H 判决不变。

### J.5 边界（不改判）

1. **两线不混**：路① = 1M + 官方 ID 20–34 + 总线 IMU200 + Radxa ZERO 3W **1GB**。`lxm` 固件是 OrangePi A733（路② B 代）、`Ley-WL/observer` 是 2GB + UART MS901M、`zhuoligetu123/hd1910m` 是 ID 1–15 + BNO08x I²C ⇒ **工具/架构可借，ID 表输入路径、波特率、固件、镜像一律不互抄**。
2. **Sim-only / 未上机不作签收**：`harrysungit` 明确无策略上过真机；`lukegao209` 双机带载未完成；`janauto`/`lxm` 大量功能只有 demo + 离线验证；awesome 索引里几十个策略仓标 sim-only。
3. **许可分层**：kissqy 中控个人非商业许可、3D 模型 CC BY-NC-SA 4.0、`fanhao375/microduck-replica` 与 kissqy 仓 NOASSERTION；`lxm` 明写 MIT 不覆盖第三方资源。`harrysungit/microduck-rl` 自带模型网格来自 Pollen（非商用条款）。
4. **本轮未改任何采购判决**：未回写 SSOT、未碰 `build.py` / 两份交付 xlsx、未恢复手删 3 行、阶段0 ¥99 与预算 `≈¥2,500–2,579` 不变；新出现的 `INCONCLUSIVE_LR_LABEL` 属**软件装配侧待实测标记**，不进采购表。

### J.6 若要落地，建议按此顺序（本轮只记录，不执行）

1. 把 `UNVERIFIED ≠ PASS` 显式引入我们自己的 `INCONCLUSIVE_*` 语义（当前 4 个标记需逐个写明「什么条件下可闭合」）。
2. 用 `record_robotd.py / fake_robotd.py` 的「录真机回包 → 离线回放」模式，给我们自己的 CLI 工具补一条**真跑 CLI** 的测试与负对照。
3. 上机 `identify` 时**只按 ID 数字登记**，左右标签留空；同步核对 reg19 过压/过流位。
4. #76 多种子 sweep 直接借 `loco-diag` 的 6 条局限清单做验收表（尤其「每套配置只跑一次」「稳态只测一个 checkpoint 一次 reset」）。
5. `harrysungit/rl` 的 acceptance gate 只在我们 HD-1910 重训产出 ONNX 后接，别用它现有 5 个技能的权重。

