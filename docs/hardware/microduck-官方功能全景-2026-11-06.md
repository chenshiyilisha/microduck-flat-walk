# MicroDuck 官方功能全景盘点

> 目的：回答「还有什么我不知道的功能」。本文只做**事实盘点**，每项给出一手出处与
> 验证状态（镜像搭载 / 真机验证 / 仅仿真 / 仅规划）。**与之前文档的关系见 §7**。
> 信息来源：上游主仓 `out/builds/microduck_main/`（2026-11-06 下的副本）+ 本仓此前调研。
> 核心一手资料：`software/image/overlay/usr/share/doc/microduck/模型说明.txt`、
> `software/training-studio/training_studio/pretrained_models.json`、
> `software/README.md`、`microduck-software/tools/README.md`、`software/training-studio/README.md`、
> `playground/hardware/*` 各 README。

---

## 1. 机器人本体能力：20 个策略，镜像搭载 10 个

### 1.1 镜像实际搭载（模型说明.txt，`/opt/robot/feetech-ft5-r5/{models,roller}/`）

| 目录 | 动作 | 程序内名 | 手柄键 |
|---|---|---|---|
| models/1cbf8730… | 走路 | `walk` | Start 站起来再按 Start 开走；左摇杆走、右摇杆转 |
| models/1c94934c… | 坐下/站起 | `sitstand` | 十字键下 |
| models/b14e3a8b… | 低头捡东西 | `ground_pick` | A |
| models/59e15d7b… | 前滚翻（1 秒） | `roulade`（技能） | X |
| models/ee0376c9… | 左脚踢（0.5 秒） | `kick_left`（技能） | LB |
| models/67ad09d8… | 右脚踢（0.5 秒） | `kick_right`（技能） | RB |
| roller/swizzle | 轮滑滑行 | 轮滑模式的 walk | 轮滑模式推左摇杆 |
| roller/crouch + spin | 轮滑蹲 / 原地转 | 轮滑模式的低头捡 | A；十字键左按住 2 秒在蹲/转间切 |
| roller/standup | 倒地后轮滑起身 | `roller_stand`（技能） | 左摇杆 L3 单击 |

其他键位：Y 头部模式、B 身体姿态、扳机张嘴、十字键右重启全部舵机、Select 短按急停
（马上卸力）、Select 按住 2 秒坐下+卸力+关机。

**验证状态（原文明写）**：
- ✅ 走路/坐站/低头捡/前滚翻/踢腿：作者二号鸭真机调好（镜像持续搭载）。
- ⚠️ **轮滑 3 个（swizzle/crouch/spin/standup）镜像作者明说「还没在真机上试过」**——
  装轮滑组件后要自己验证。
- ⚠️ 脚踢/前滚翻是**技能**（一段式），原地按一下就走完，需要重新按 Stand 回站立。

### 1.2 完整 20 个策略清单（`pretrained_models.json`）

- **official-v8 系 10 个（XL330 硬件）**：`walking / stand / sitstand / ground_pick /
  roulade / ball_kick_left / ball_kick_right / velstand / roller / roller_crouch`
- **kissqy 系 10 个（HD1910 硬件）**：`walk / sitstand / ground_pick / roulade /
  kick_left / kick_right / roller_crouch / roller_spin / roller_standup / roller_swizzle`

对应训练任务（JSON 内 `task_id`）：`Mjlab-Velocity-*`（走/轮滑滑行/转）、`Mjlab-SitStand`、
`Mjlab-GroundPick`、`Mjlab-Roulade`、`Mjlab-BallKick*`（踢小球）、`Mjlab-RollerStandUp`、
`Mjlab-VelStand-Rough`（粗糙地面站）、带 `Backlash` 的训练（反驱课题）。

→ 镜像装的是 kissqy 10 个里的 10 个（7 走路系 + 3 轮滑系文件，roller/crouch 与 spin 共用
文件这套是映射技巧）。其余 10 个（official-v8）是 XL330 党的，HD-1910 复刻用不上。

### 1.3 口径警示（两处数字不一致，都是原文）

- **`action_scale`**：模型说明.txt 第三节说走路 `action_scale = 0.7`（「跟模型自带建议
  不同的一处：建议值 1.0」）；`hardware-teardown.en.md` 说官方 walk=0.9 / roller=0.8。
  → 前者是**镜像 kissqy 二号鸭的部署值**，后者是**官方发布口径**。引用时必须带出处：
  「镜像实装 0.7」≠「官方建议 0.9」。
- `ROLLER_STAND_Z=0.138` 是训练侧常量（轮滑站姿根高），见
  `microduck-两版轮滑变体组件与装配计划-2026-11-06.md` §5.4，不冲突。

---

## 2. 配套软件四件套（装完镜像就有，不用自己写）

| 件 | 能力 | 出处 / 状态 |
|---|---|---|
| **Microduck Studio** | 装在鸭子上的网页中控（浏览器开 `:8000`）：状态查看、一键卸力、舵机零位标定、IMU 方向校准、写进主程序、蓝牙手柄配对、日志、热点配网 | `software/studio/README.md`；镜像预装（20261027 及之后） |
| **duck-echo 本地语音** | 手柄 R3 单击开监听，说中文「坐下」「站起来」执行；另有「听音乐」问答模式；Vosk 本地模型**无需云端 Key** | `software/duck-echo/README.md`；作者 2026-10-25 真机验收（Switch Pro 手柄）；需 **TLV320AIC3104 HAT 音频板**（额外硬件，不在 BOM） |
| **updater 网页更新** | 签名组件包、离线上传、安装与回退 | 20261027 镜像预装——以后升级不用重烧 SD 卡 |
| **复刻镜像（kissqy）** | 站姿 IMU 重标、ID 200 独立方向核验、热点恢复、手柄映射修复 | 20261104 测试版——烧卡 + 生效待现场验收 |

→ **装机后第一件事建议是试 Studio + updater 这条路**，替代「重新烧卡」的笨办法。

---

## 3. 训练与仿真（现阶段用不上，但要知道存在）

- **Microduck Studio（训练台，与 §2 同名不同物）**：云电脑上网页训练台
  （`127.0.0.1:8093`），现成模型目录收录上述 20 个（含来源/硬件/版本/许可/上游地址），
  支持配方实验、训练、评估。本地跑要 NVIDIA GPU + WSL2，门槛不低。
- **任务清单口径**（`task_id` 反推）：走路系有 Rough（粗糙地面）、Backlash（反驱齿隙
  课程）等训练课题——解释了我们轮滑计划里「摩擦课程 0.05→0.0015」那套。
- **`start-demo` 一键体验**：Windows 双击 `start-demo.cmd` / Linux `sh start-demo.sh`
  （8093 端口），是想先看效果又不摸真机的最快路径。

---

## 4. 官方 Playground 实验硬件（上游 software 仓，**大多只在仿真里验证过**）

这些是「官方做的玩具」，**不是当前 BOM 的一部分**，列出来是防止以后误以为漏了件：

| 附件 | 内容 | 状态 |
|---|---|---|
| **MicroDock 自回充坞** | 鸭子走到 AprilTag 前转身倒车入坞，磁性 USB-C 对接背上充电口，**不换电池直接充**；全打印无螺丝；另有 v2（鸭子坐着充电） | ⚠️ **只在仿真里验证过，真机没试过**（v0.1 原型） |
| **Stilts 增高鞋** | 可拆卸脚底换成载具 + 高度模块（0.5/1/1.5/2 cm），接触面积恒定 22×32 mm；为「高度作为唯一变量」的教学课程设计 | v0.1 原型，仿真验证 |
| **Ladder 桌梯** | 模块化拼装，摩擦配合无销钉 | 仿真验证 |
| **Swing-seat 秋千座** | 模块化拼装吊座位 | 仿真验证 |

→ MicroDock 与轮滑组件是**同一批「官方 playground」产品线**，想玩可后续加购；
Stilts 与轮滑鞋都改脚底，**别同时装**（轮用轮滑 V1 踝，Stilts 换脚底载具）。

---

## 5. 调试/装机工具（microduck-software/tools/，烧卡装机阶段大概率要碰）

- **HD1910M Rust 命令行测试工具**：扫描总线 / 寄存器读写 / 监控——比飞特 FD 软件更贴
  我们研发流程（FD 是 Windows 图形界面，适合量产调参）。
- **imu200.py**：飞特地址 56 的 15 字节块协议检查（真板 + 模拟双模式）。
- **gait-analysis**：纸上分析任意 JSONL 记录的跟踪误差/颤动/脚部运动——评估走路质量
  不用等训练完，直接看线上日志就能用。
- **radxa onboard-analysis**：实机采集关节/IMU/指令记录（Radxa 版专属）。
- **Rufus 4.15 便携版**烧镜像、**飞特 FD 1.9.8.5** 舵机配置软件（官方入口都在
  `microduck-software/tools/README.md`）。

→ 与本仓衔接：fd 系列的 EEPROM 写入时序、robotd 硬校验那几条，FD 软件是图形化的
另一条操作路径；寄存器级操作仍以 HD1910M CLI + 我们的 Python 脚本为准。

---

## 6. 许可红线（必须知道的雷）

- **预训练模型是 kissqy 个人非商业许可**：可以免费分享、个人学习非商业使用；
  **不得随 HAT / 整机 / 套件产品预装或分发，不得用于收费服务**；公司或组织使用须先取得
  书面许可。全文见模型说明.txt 第五节。
- 代码 Apache-2.0（robotd/padd/mediad）；网格 CC BY-NC-SA（Pollen 官方）。
- → **自己玩、做研究没问题；卖整机套件时这 10 个模型一个都不能预装**。这是整机项目
  商业化的前提性约束，先记着。

---

## 7. 与已有文档的关系（不重复、不改之前结论）

| 本盘点章节 | 已有文档 | 关系 |
|---|---|---|
| §1 策略清单 | 轮滑计划 §5.4 | 补充：镜像实装 10 个的**完整键位图** + 20 个完整清单 + action_scale 双口径 |
| §2 软件四件套 | 双版本推进文档、部署链 | 补充：Studio/updater 运营性能力，此前只写了部署链 |
| §4 Playground | 无 | 全新：官方实验硬件，明确不属当前 BOM |
| §5 工具 | Radxa 验收清单 | 补充：装机期工具入口 |
| §6 许可 | 无 | 全新：商业化红线 |

之前的所有结论（两版装配、轮滑对照、部署链）**一字未动**。

---

## 8. 建议优先级（如果要动手）

1. **镜像 + Studio + updater 走通**（装机即用，替代重烧卡路径）
2. **轮滑组件按《两版轮滑变体计划》装机，然后真机验证镜像那 3 个 roller 动作**——
   镜像作者明说没试过，这是最有价值的开源验证机会
3. **duck-echo 语音**（需额外买 TLV320AIC3104 HAT，非 BOM 件）
4. playground 附件（MicroDock 先仿真，Stilts 是教学向）
5. 训练台（要 GPU + WSL2，现阶段知道存在即可）
