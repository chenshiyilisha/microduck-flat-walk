# MicroDuck 自充电 / 自主回坞 —— 官方参照与核实（2026-11-08）

> 目的：用户要求"参照官方的研究"。本文**先核实、再整理**，把"真·官方"与"既往文档里标成官方的、但查不到的"明确分开。
> 所有结论带验证状态与一手来源；查不到的明确标【无法核实】。
> 方法：拉取 `pollen-robotics/microduck` 的 main/develop/autonomous-mode 三分支全量文件树、
> 读取官方 HF 策略仓库 `pollen-robotics/microduck-policies` 的 `manifest.json` 与文件清单、
> 比对官方商店/官网 `pollen-robotics.com/microduck`、交叉多份 2026-10 媒体评测、GitHub 组织内仓库/代码检索。

---

## 0. 一句话结论（核实后）

- **官方（Pollen / HuggingFace）目前没有任何自主回坞 / 自动对接充电桩，也没有任何 dock 策略网络。**
- 官方充电模型是 **换电（NP-F550 可拆卸电池 + Charger Pack 双充）**，不是机器人自己回去充。
- 本仓 `docs/hardware/microduck-MicroDock真机可行性预研-2026-11-06.md` 里写的
  "**官方** MicroDock 自回充坞 / scoot_dock.onnx / scoot_undock.onnx"——**经本次核实，在官方任何公开来源都找不到**，
  与官方 `manifest.json` 直接矛盾（官方策略清单里没有 scoot/dock 任何一项）。
  → **该预研文档的"官方"归属【无法核实】，应降级为"来源不明 / 疑似非官方或误标"，不能再当官方方案引用。**

---

## 1. 已核实的官方事实（一手来源）

| 项 | 核实内容 | 来源 |
|---|---|---|
| 本体形态 | 25cm / ~780g **双足（biped）**鸭，15 自由度（腿/颈/头），2 个 IMU | 官网 + 多份媒体一致 |
| 电池 | **可拆卸 NP-F550 相机电池，2 串 / 标称 7.2V / 满电 8.4V / ~1 小时续航**；容量随品牌/电芯而异：官方整机口径曾标 2600mAh，🔴 **本项目采购的唯卓仕 NP-F550 小布丁实物为 2200mAh / 16.28Wh（2026-11-10 一手订正，见 SSOT）** | 多份一手规格页 + 官方；唯卓仕官方/京东规格页 |
| 充电方式 | **换电**：电池抠下外接充；官方 **Charger Pack $39 = 双槽充电器 + 2 块备用电池** | 官网商店 + 媒体（TechMoon/Applescoop/Eesel/42号电波） |
| 出厂策略 | **7 个**训练好的行为：walk / sit&stand / kick / grab / roller-skate / get-back-up（+ stand） | 官网 + manifest.json |
| 官方策略清单（HF） | 仅：`alpha_walking / velstand / alpha_stand / roller / alpha_sitstand / alpha_ground_pick / roller_crouch / roulade / ball_kick_left / ball_kick_right` | `pollen-robotics/microduck-policies` `manifest.json`（obs=61 / act=14 / xl330 / 50Hz） |
| 官方 add-on | Charger Pack（双充+2 电池）、Dev Pack（备件）、Accessory Pack（滚轮/球/激光/NFC） | 官网 + 媒体 |
| 开源范围 | **仅软件**（SDK / 仿真 / RL 训练栈，Apache-2.0）；**机械与电路设计不开源** | 官方 press kit 多份媒体明确 |
| 钓鱼站警示 | `microducks.org` 卖的 "weighted charging dock" / hard case **不在官方清单**，已确认 ≥3 个山寨域名 | Applescoop 等媒体 |

---

## 2. 本次核实的核查清单（为什么我说"官方没有 dock"）

1. **GitHub `pollen-robotics/microduck`**（软件主仓）：
   - 拉取 `main` / `develop` / `autonomous-mode` 三分支全量文件树。
   - 顶层目录只有软件 daemon（`robotd` `padd` `mediad` `robotctl` `spaces/...` 等），**无 `playground/hardware/microdock` 目录，无 `dock`/`scoot`/`charging` 硬件或策略代码**。
   - `autonomous-mode` 分支也只含软件 daemon（无 docking 逻辑）。
2. **HF 策略仓库 `pollen-robotics/microduck-policies`**：
   - 文件清单：`alpha_*.onnx` / `roller*.onnx` / `roulade.onnx` / `ball_kick_*.onnx` / `manifest.json` / `README.md`。
   - **无 `scoot_dock.onnx` / `scoot_undock.onnx` / 任何 dock 策略**。
   - `manifest.json` 明示 7 个出厂策略，未见 dock 条目。
3. **GitHub 组织内检索**：`pollen-robotics` 下搜 `dock` / `scoot` / `hardware` / `microduck` 仓库 → **无 microdock 相关仓库**；代码检索 `scoot_dock` / `microdock` → 空。
4. **官网 `pollen-robotics.com/microduck`**：列出 7 个训练动作 + 3 个 pack，**无充电坞**。
5. **媒体评测（多份独立，2026-10）**：均写"换电 + Charger Pack"，无官方 dock；并点名山寨站卖的 dock 非官方。

→ 结论：在**所有官方公开来源**中，MicroDuck 的充电 = 换电，**不存在官方自回充坞 / dock 策略**。

---

## 3. 既往文档里"官方 MicroDock"的具体声称 vs 核实结果

下面内容取自 `docs/hardware/microduck-MicroDock真机可行性预研-2026-11-06.md`，
**本次核实均无法在官方来源中复现，统一标【无法核实 / 疑似非官方】**：

| 既往声称 | 核实结果 |
|---|---|
| "MicroDock 是**官方** Playground 产品线，来自上游 `playground/hardware/microdock(-v2)/`" | 【无法核实】官方软件仓无此目录（见 §2.1） |
| "v2 给了 `scoot_dock.onnx` / `scoot_undock.onnx`，属于 `pollen-robotics/microduck-policies` manifest" | 【无法核实·矛盾】官方 manifest 与文件清单均无 scoot/dock 策略（见 §2.2） |
| "仿真 30/30 入坞 / 脱困成功、精度 0.4mm" | 【无法核实】源 README/results 在官方源中不存在 |
| "坞体 5 个 STL、P1S ~5h33min/241g、BOM（Auravale 适配器/弯头线/充电器 ~$35）" | 【无法核实】STL 与 BOM 在官方源中不存在 |
| "beta 板 USB-C 仅到 5V 轨不充电（官方口径）" | 【部分合理但无源】官方确实未提供充电坞；但"官方明说 beta 板不充电"这句在本次核实中未找到原文出处 |

> ⚠️ 这些技术细节（port_above_bat / notch_w / shell_back_x / z0=62 / 磁吸 4N / scoot 4cm/s 等）过于具体，
> 不像凭空编造，**疑似来自某篇社区博客 / 未合并分支 / 已删除内容 / 或 HF Space 演示**。
> 但**它不是官方发布物**，不能写进"官方参照"。如要追溯真实出处，需另查社区源（见 §5）。

---

## 4. 因此，对你 HD-1910 自充电项目的正确基线

- **官方没有现成方案可抄**：既没有 dock 硬件，也没有 dock 策略网络（scoot 权重不存在于官方）。
- **官方充电 = 换电**：多备 NP-F550（2S/7.2V）+ 双充，徒手换。对 780g 小机器人，这通常最省事。
- **若真要做自主回坞**：等于从零自建（参考 §3 那些"无法核实"的细节也**不能直接当设计方案**，因为源不明、未验证）。
  可参照的**真·公开**方向只有此前调研的第三方范式（Unitree/Spot 回坞、RoboHub 磁吸桩、Powermat 无线、AprilTag 末段对准），
  以及通用"低电→导航→对接→充电握手"分层架构（Kodo go2-autonomous-patrol 等），这些是非 MicroDuck 官方的通用方案。
- **HD-1910 复刻机的硬前提仍然成立**：beta 板 USB-C 是否带充电路径（R1）是任何自充电路线的 gate，与"官方有没有 dock"无关。

---

## 5. 下一步建议（二选一，等你定）

1. **追溯 §3 那些细节的真实出处**：可能是社区博客 / 某未合并 GitHub PR / 已删除分支 / HF Space。
   若要继续"参照"，我可再用针对性检索（如 `microduck dock STL`、`pollen microdock`、`microduck charging` 社区源）定位它，
   确认它到底是不是某人的 DIY 项目，再决定能否借鉴。
2. **直接走通用第三方范式**：不再纠结"官方 MicroDock"，把自充电作为独立新建模块（机器人侧 docking 控制器 + 充电桩），
   参照 RoboHub / Powermat / AprilTag 那批已核实的通用方案，出一份适配双足小机器人的设计草稿。

---

## 6. 纠正记录

- 本仓 `microduck-MicroDock真机可行性预研-2026-11-06.md` 与 `microduck-官方功能全景-2026-11-06.md §4`
  把 MicroDock 标为"官方 Playground 产品线"——**经 2026-11-08 核实，该归属无法在官方来源复现，降级为【无法核实】**。
- 官方实际只有"换电"充电模型，无自回充坞、无 dock 策略网络。
