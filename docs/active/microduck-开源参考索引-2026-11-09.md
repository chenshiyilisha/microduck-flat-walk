# MicroDuck 开源参考索引（2026-11-09 全量核对）

_把 2026-11-09 两批链接 + 此前全部开源参考汇成一份索引。每仓标注：**一手/二手、什么线、能借什么、别借什么**。
元数据当日用 GitHub API / 立创页面逐仓实抓（星数/语言/许可/最近推送），非记忆值。星数会漂，判价值看线不看星。_

_⚠️ 许可提醒：`fanhao375/microduck-replica`、`kissqy/Microduck-kissqy` 仓库均**无 LICENSE（NOASSERTION）**——代码/图纸可参考学习，默认无再分发/商用权利。666wsp 厂商包许可明文禁商业再分发。_

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
  - `HD-1910训练前数据清单.md` — 几何/质量/惯量/关节轴；**自标「全是 XL330 仿真值，换飞特四处不同」**：单只 18→21 g、34×20×23 mm、堵转 0.6→1.47 N·m@7.4V、320:1/回差≤0.5°。整机 **737.1 g**（我们记 744 g，差 7 g，**待核口径**——作者自己也标了电池是否含在 trunk_base 待核）。
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

1. **抄 xgoduck_rl 的 `roller_standup` + `sitstand`**——P3 缺这两个，「跌倒后自己起来」是整机验收硬项，fanhao375 正是靠它证明的。
2. **`backlash.py` 对照我们齿隙设定（≤0.5°）**，看是否同一量级。
3. **microduck_yocto 作为上板 OS 候选**（microduck-zero3 机种就是我们的板）；updater RAUC 回滚链值得在真机上跑一次。
4. **读 fanhao375 `踩坑记录.md`/`调试记录.md` 目录**挑未踩坑，避免重复。
5. 核 **737.1 g vs 744 g** 口径（BAM `trunk_base` 是否含电池）。
