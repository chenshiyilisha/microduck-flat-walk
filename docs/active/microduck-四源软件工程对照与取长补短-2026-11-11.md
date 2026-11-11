# 四源软件工程对照与取长补短（官方 / kissqy / fanhao / luwu 为主，其余开源为辅）

_2026-11-11，Pass103。起因：用户连续两问「本地拉了那么多开源项目是不是可以参考、取长补短」「官方、kissqy、fanhao、luwu 深入研究」「以这四个为主，其他开源为辅，互相对照、取长补短」。_
_方法：先穷尽本地 `microduck-software/.upstream/` 28 个上游仓的一手文件；四源中 luwu 本地无源码（只有我们自己的核对文档），补抓 GitHub 仓库页一手 README；kissqy `docs/BASELINE.md` 联网取 **404**，明标未取到，不外推其内容。_
_边界：**本文只做软件工程实践对照，不改任何采购判决**。SSOT、`build.py`、两份交付 xlsx 一律未动；阶段0 ¥99、手删 3 行、预算 `≈¥2,500–2,579` 不变。_

---

## §0 先给结论

1. **四家在「离线结果 ≠ 实机验收」上是共识**，只是说法不同：官方「Absent fields are not evidence」、kissqy「源码公开不扩大原有模型的实机验收范围」、fanhao「Verified locally / Board acceptance still required」、luwu 把测试数写进 commit 却把本地验证工具排除出源码发布。⇒ 这条可直接升格为我们门禁的 `UNVERIFIED ≠ PASS` 语义，**四源互证**。
2. **最大的互相对照冲突是发布链**：官方是 `uv run publish` → HF Hub → `robotctl policy add`；kissqy/fanhao 是 **R17→V167 中控 + 一键完整镜像，非 publish**。两者不是版本差异，是两条链。拿官方 schema-2 manifest 的字段值去判路①，正是 `deploy61` 分母差 1157× 的同型错误。
3. **四家一致指向「HD-1910 必须自己实称实量、换 plant 必重训」**：官方 MJCF 是 XL330；fanhao 训练前清单自述几何/质量/惯量全是 XL330 仿真值、训练数据也是自标 XL330 仿真值；luwu 明写几何与惯量与 MicroDuck 不同。⇒ 没有任何一家的现成模型能直接上我们的整机。
4. **取长补短不是抄代码，是抄「契约怎么组织、证据怎么记、门禁怎么拒绝、边界怎么写」**。三条落地：A1 线别护栏、A2 闭合契约、A3 统一门禁，见 §4。

---

## §1 四源身份与一手来源（先把「谁是谁」钉死）

| 源 | 本地一手位置 | 身份 | 许可 / 状态 |
|---|---|---|---|
| **官方** | `.upstream/microduck_rl-develop/AGENTS.md`（训练栈 develop）、`build-tutorial/microduck/`（教学镜像）、`ft1910|imu-displace|hd1910m/microduck/docs/policy-manifest.md`（同源官方运行时契约） | `pollen-robotics/microduck_rl` + `pollen-robotics/microduck`；XL330 / Dynamixel 2.0 / 61-14-50Hz 契约的定义者 | Apache-2.0；⚠️ **官方运行时仓本地没有完整 clone**，`policy-manifest.md` 取自三个 fork 的同名文档，措辞同源但非官方仓直取 |
| **kissqy** | `.upstream/kissqy/README.md`、`baseline_official0151.json`、`hardware.json`、`servo_references.json`、`LICENSE` | **官方 0.15.1 的飞特 HD-1910 适配**；R17 中控 + 独立训练中控；Radxa ZERO 3W / 15 颗 HD-1910 | 源码公开，**作者原创部分仅供个人非商业**；第三方保留原许可证 |
| **fanhao** | `.upstream/replica/`（1345 文件）、`replica-kit/`、`hw-replica/`；`docs/软件来源与我们的改动.md`、`docs/HD-1910训练前数据清单.md`、`docs/superpowers/verification/*.md`（27 份）、`replica/software/**/test_*.py`（131 个） | **叠在 kissqy 之上**（不是平行重写）：官方 0.15.1 → kissqy 适配 → fanhao fork（control.44 + I²C IMU + gyro_fusion + Studio） | 双许可（官方 Apache / 社区 NOASSERTION），镜像个人非商业，CAD 类 CC BY-NC-SA |
| **luwu** | 本地**无源码**；仅 `docs/active/microduck-xgoduck任务定义与整机质量口径核对-2026-11-09.md`（我们自己的核对文档，用 git blob sha 做过同源判定） | 联网一手：`LuwuDynamics/xgoduck_rl` README + commit 记录；**基于 microduck_rl 的下游**，XgoDuck 几何/惯量与 MicroDuck 不同，执行器 `params/1910_m6.json` = HLS1910 BAM | **Apache-2.0**；2026-11-09 仍有 `Fix some bugs` 提交 ⇒ 比索引里的旧状态更活跃 |

🔴 **必须先消的两个歧义**（准则「同名不同物 / 两线不混」）：
- 「官方」在本项目里有两种指代：官方**训练栈**（`microduck_rl-develop`）与官方**运行时**（`policy-manifest.md` 的契约主人）。本文分开标注，不混用。
- 「fanhao」与「kissqy」是**叠层**：`replica/docs/软件来源与我们的改动.md` 原文「以他的最新版为底，叠上我们的补丁，跟着他更新；不给 kissqy 提 PR」。所以 fanhao 的一切结论都带 kissqy 底座，不能当成独立第四条硬件线。

---

## §2 八维互相对照表（主表）

| 维度 | 官方 | kissqy | fanhao | luwu | 互相对照结论 |
|---|---|---|---|---|---|
| **D1 契约/唯一主人** | `AGENTS.md` 的 `Invariants — do not break these`，每条写「破坏它会怎样」；`policy-manifest.md` 自称 **this file is the contract**；`ft1910/docs/README.md`（官方风格 fork）「每个机制一页主人；两页冲突时非主人页是 bug；行为与设计文档冲突则文档是 bug」 | `firmware/BUILD.json` 与 V167 随包固件 BUILD 记录一致；两个中控源码与各自 ZIP 同步；`PUBLICATION-MANIFEST.json` 记完整来源与校验 | 「以 kissqy 最新版为底叠补丁」＝**上游是主人，补丁不另立契约** | 下游 fork，沿用 `microduck_rl` 的任务与契约，只换 `robot/xgoduck/` 与执行器参数 | 四家都**避免第二份真相**。⇒ 我们 `line_labels.json` 必须是线别唯一主人，门禁/文档都从它派生，不复制常量 |
| **D2 版本与发布配对** | schema-2 manifest：`model_api` 新于 daemon 则拒、`obs_len=61`/`action_len=14`/`robot.model` 不一致则拒；`robot.servos` 写死 `xl330` | 官方 0.15.1 · **control.43 · API40** ↔ **R17 V167（1.0.167）中控** ↔ 训练中控 **R1.5.27**；**镜像 R1 仍预装 control.40，须升 .43**；IMU 板另刷 STM32 FT6 | control.44；旧卡 R17 / 新卡 V164；换 kissqy 一键镜像 R1；Studio 版本随功能走 | 13 个任务配方表（task / terrain / experiment dir）；`*.onnx` gitignored；**导出 ONNX 与产出它的 run 同目录** | 🔴 **官方 manifest 字段值不能照搬**（`xl330`），只能借结构与拒绝语义；路① 的配对是「镜像 R1 ↔ control.43 ↔ V167 中控」 |
| **D3 验证与门禁** | `uv run publish` 内含 **ONNX shape/smoke gate**；`tests/` 为 cfg-invariant + mdp 函数回归（CPU 即可）；AGENTS 要求 **5-iter / 64-env smoke 先跑**（catch ~95% config errors） | 一键完整镜像免编译；使用顺序 **HOME → 保持 → 行走**；每台机器人自己核零位/方向/限位/IMU | **131 个 test_*.py**（studio 62 / training 24 / image 10 …）、27 份日期化 verification 记录、32 plans + 23 specs；一次 Studio 全量 **1009 passed / 4 skipped / 590s** | commit message 写验证记录：**215 tests passed, 1 skipped；Swizzle smoke 5 iterations / 64 envs；ONNX inference 与 61-input/14-output metadata checks passed** | 四家都把「shape/smoke + 回归 + 显式记录」当门禁。⇒ A3 应输出同型报告，且 **smoke/元数据检查与实机签收分开** |
| **D4 证据 / 未闭环** | 🔴 **「Everything is optional except `file`… Absent fields are not evidence: a robot refuses a policy only on a claim that is present and wrong」**；`eval` 字段写「查了什么、在什么 sim、结果如何」 | 🔴 **「本次源码公开不扩大原有模型的实机验收范围」**；`docs/BASELINE.md` 管「发布版本与验证范围」（联网 404，未取到正文，只据 README 引用） | 🔴 训练前清单每个数带【MJCF】/【规格书】/【源码】/【逆向】/【STL】/**待实测**；验证记录分 **Verified locally** 与 **Board acceptance still required**，后者写「do not claim success until … read back」「Package a new image only after board acceptance」 | 「Training checkpoints, logs, recordings, **and local validation tools are excluded from the source release**」；明写几何/惯量与 MicroDuck 不同 | **四源共识：离线/源码/仿真 ≠ 实机验收**。⇒ A2 每条契约分 `local_verified` / `board_acceptance_required`，状态 `UNVERIFIED` 绝不算 PASS |
| **D5 溯源 / 可复现** | manifest `training` 字段：`task_id, repo, commit, branch, dirty, run, checkpoint, exported` | `BUILD.json`、`PUBLICATION-MANIFEST.json`、源码与 ZIP 同步 | 日期化验证记录；我们本地核对文档用 **git blob sha**（`sha1("blob <len>\0"+bytes)`）做同源判定 | **`vendor/bam/` 钉死第三方 BAM 运行时**（含上游文档与 license）+ `uv.lock`；ARM 首装提示 `UV_HTTP_TIMEOUT=600` | 可借：`training` 溯源字段、vendor 钉版本、导出与 run 同放、sha 同源判定。⇒ A1 契约每条常量标一手出处，A3 报告钉契约 sha256 |
| **D6 许可 / 适用边界** | Apache-2.0；manifest 假定 `xl330` | 原创部分**个人非商业**；第三方保留原许可证 | 双许可；镜像个人非商业；CAD CC BY-NC-SA | **Apache-2.0**；但机器人几何不同、执行器是 HLS1910 BAM | 与本项目判决一致：**仅个人使用** ⇒ 路① 完整镜像可直接刷；**商用才切自写分支**（`p8head_2999` 8 契约 PASS） |
| **D7 硬件 / 线别** | XL330 / Dynamixel 2.0 / 官方 ID 20-34+10-14 / IMU200 | **HD-1910 + Radxa ZERO 3W + 官方骨架 + 15 颗**；**只认总线 ID200 + FT6 身份字节 `06 00 00 00 F2`**，无 I²C 路径 | 同底座 + **I²C BNO08x / LSM6DSV16X + `gyro_fusion` + `[bus] imu_protocol=auto`**；整机站立/行走/前滚翻起身跑通 | **XgoDuck 几何 + HLS1910 BAM、默认 ±24° HOME**；不是 MicroDuck | 🔴 三套 IMU/执行器路径**互不相通**；`ft1910/docs/design/scs-bus.md` 另给第三套 `scs=true`+`scs_config`（1M / `imu_id=200` / 15 个实测零位）⇒ **线别是三条不是两条**，A1 按三线建模 |
| **D8 训练 / 部署链** | `publish` → HF Hub（policy.onnx + schema-2 manifest + README）→ `robotctl policy add` / `policy load`；normalizer 烤进图；61/14/50Hz | **R17→V167 中控 + 完整镜像自带模型管理，不是 publish**；训练需 NVIDIA GPU + Linux/WSL2 + uv；14 类动作 / 35 种任务配方 | 一键镜像自带模型管理（非 publish）；训练数据自标 **全 XL330 仿真值**，≠ HD-1910 实测 | mjlab/PPO → `scripts/export.py` → ONNX（烤 normalizer）；**未描述 publish** | 🔴 最大冲突：官方 publish 链 ≠ 我们路① 中控链。MEMORY 已判「publish 与这代 robotd 非一条链、normalizer 须烤进图、不打包 EXTERNAL 权重」，本文四源对照**再次独立印证** |

---

## §3 六条「互相对照才看得见」的冲突与处理

> 准则：找两个来源互相矛盾，而不是问「结果对不对」。以下每条都是四源之间的一手矛盾，不是我们推的。

1. **发布链冲突（官方 vs kissqy/fanhao）**：官方 `publish` 把 manifest 与 ONNX 推到 Hub 由 daemon 加载；kissqy/fanhao 用中控 + 完整镜像管理模型。⇒ 处理：**路① 只走中控链**；官方 manifest 仅借「契约结构 + 缺失非证据 + 拒绝语义」，不借字段值、不接 `publish`。
2. **manifest 写死 `robot.servos: xl330` vs 我们整机 HD-1910**：⇒ 处理：官方 schema-2 的 `obs_len/action_len/control_hz` 可借，`servos` 字段值不可写进路① 契约；`rehearse_deploy.py` 写死 XL330/kp200 的教训同源。
3. **几何/质量/惯量三源一致地「不适用」**：官方 MJCF=XL330；fanhao 清单自述全是 XL330 仿真值且列出四处差异（18g→21g、20×34×26→34×20×23、0.6→1.47 N·m、320:1/≤0.5°）；luwu 明写 XgoDuck 几何/惯量不同、HLS1910 BAM。⇒ 处理：**换 plant 必重训**、装机实称实量覆盖仿真值，这条从「我们的判决」升级为「四源互证」。
4. **IMU 路径三源不同**：kissqy 仅总线 ID200+FT6 身份字节；fanhao 叠 I²C + gyro_fusion + auto 识别；官方是 Dynamixel 线。⇒ 处理：**认板仍 `INCONCLUSIVE_LIVE_IDENTIFY`**；fanhao 自述 `20261023c` 自动识别只做到伪串口 + 镜像离线核验、真实小板未上机 ⇒ 上机 `identify` 才闭环。
5. **「源码公开」的效力边界（kissqy vs 常见误读）**：kissqy 明写「源码公开不扩大原有模型的实机验收范围」，luwu 把本地验证工具排除在源码发布外，官方说「缺失字段不是证据」。⇒ 处理：我们把「本地/公开/仿真」三类一律标 `UNVERIFIED`，**不因为读得到源码就升格为已验证**。
6. **左右腿文字定义 2:1 冲突**（上一轮 §J 已记）：三来源 ID 数字集合一致、左右文字相反。fanhao 训练前清单给「左右腿 pitch/knee/ankle 轴向符号相反，镜像装配」的一手几何解释 ⇒ 处理：`INCONCLUSIVE_LR_LABEL` 保留，**装配/标定只认 ID 数字**；这份轴向表可作上机核对清单。

---

## §4 取长补短 → 落到 A1 / A2 / A3 的具体映射

| 落地件 | 借谁 | 借了什么 | 明确不借什么 |
|---|---|---|---|
| **A1 `line_labels.json` + `line_contract.py`**（路①线别护栏） | 官方 `policy-manifest.md`（`model_api`/`obs_len`/`robot.model` 不一致即拒）、`ft1910/docs/design/scs-bus.md`（`scs` 与 `scs_config` 两键不一致即拒） | **跨线拒绝语义**、三线建模、每条常量标一手出处、「共享非判据」清单（`policy.gain=200` 是 XL330 参考值，非线别判据） | 不借 `ft1910/AGENTS.md` 的「Never design around a version difference / version skew is logged and served, never refused」——我们两线是**硬件协议线不同**，不是版本差异，必须拒绝 |
| **A2 `closure_contract.json` + `check_closure.py`**（悬案闭合契约） | fanhao 训练前清单（出处标记 / 待实测 / 适用边界）、fanhao verification（Verified locally / Board acceptance still required）、官方（缺失非证据、`eval`/`training` 字段）、kissqy（不扩大验收）、luwu（commit 验证记录） | 每条契约字段：`evidence_kind` / `verification_boundary` / `local_verified` / `board_acceptance_required` / `still_owed` / `negative_control` / `blocked_actions` / `source_refs` / `signoff`；状态机 `UNVERIFIED ≠ PASS` | 不借官方 manifest 的「字段全可选」——**对外契约可宽松，内部台账必须严格**：缺负对照/缺闭合条件直接判红 |
| **A3 `run_all_gates.py`**（统一门禁） | 官方 shape/smoke gate、luwu commit 验证记录格式、`mdlab/.github/workflows/tests.yml`（pinned sha / 已知缺口显式列出）、`hd1910m/.../audit_native_observation_contract.py`（`live_hardware_accessed=false` + `note: Not proof of…`）、`open-microduck/book/tools/check_book.py`（单一权威 + 集合相等断言 + 输出 sha256 + 末尾 Scope 声明） | 报告必带 `live_hardware_accessed=false`、`not_proof_of`、`known_gaps`、`coverage_gap`、契约 sha256；复用本仓 `pre_deploy_check.py` 的 SKIP 默认 FAIL / rc=2 argparse 判 FAIL / PARTIAL≠PASS | 不宣称全绿＝可上机；`robotd --sim` 验不了总线驱动/BLE/ISP/NPU/编码器，**不能消 `INCONCLUSIVE_RATE_MISMATCH`** |

**其他开源为辅**（只作佐证，不进主线判决）：
`open-microduck`（`book/editorial/04-evidence-backlog.md` 的「问题/设备版本/预期/实际/原始记录/只改变了什么/结果/尚不能排除的解释」「不能只保存最终成功视频」、`research/source-ledger.md` 的「已发现的冲突及处理」「本轮没有取得的证据」「主张|位置|证据性质」）、`mdlab`（`contract.py`「is a DESCRIPTION, not a second source of truth」、`golden_store.py` 负对照、CI 的 pinned sha + 已知 gap）、`playground`（Invariants 破坏后果、normalizer 烤图）、`replica-kit/hardware/CURRENT_HARDWARE.md`（「验证边界」列、「商品标示 0–3A 不是实测连续输出能力」＝与拓普赛电池否决同型）、`community-kit` / `awesome-microduck`（工具索引）。

---

## §5 本轮被一手推翻的两处旧说法（自我纠错）

1. 🔴 **上一轮把 `policy.gain=200` 判成「B 代硬错配」是错的**。SSOT 行366/431、`microduck-HD1910软件方案.md` 行1055-1056、`ft1910/docs/design/scs-bus.md` 行116 三处一致：`gain=200` 是 **XL330 参考值**（`KP_REFERENCE=200`），配合 `position_kp=8` 得 `reg50=8`；**`gain=8` 才是已作废的破坏值**（reg50=1 ⇒ 瘫软）。`audit_robotd_toml.py:29` 写的 `gain=200` 是**正确**的。真正的线别判据只有波特率 / reg6 / ID 体系 / IMU 路径 / 部署链 / 板型。
2. 🔴 **上一轮说「没有一条命令跑全部门禁」不够准确**：本仓 `pre_deploy_check.py --selftest` 已跑 5 个部署守卫，且已实现 `SKIP` 默认 FAIL、`rc==2` argparse 判 `GUARD INVOCATION BROKEN`、显式 allowlist 才出 `PARTIAL`。真正缺的是「5 守卫 vs 全仓 33 个 `--selftest` 工具」的覆盖差集，以及把线别/闭合契约接成第一道门禁 ⇒ **A3 是补齐与编排，不是重复造轮子**。
3. 附带：`verify_official_loader.py` 已是**官方读侧**校验器（30/30 selftest），`verify_policy_bundle.py` 才是 B 代读侧 ⇒ A1 标签按此区分，不再提「把 B 代读侧迁过去」。

---

## §6 一手出处清单（可复核）

| # | 文件 | 本文用到的原文要点 |
|---|---|---|
| 1 | `.upstream/microduck_rl-develop/AGENTS.md` | Invariants、5-iter smoke、publish + shape/smoke gate、`policy-manifest.md` 契约指针 |
| 2 | `.upstream/ft1910/docs/policy-manifest.md` | schema-2 字段表、「Absent fields are not evidence」、`training`/`eval` 字段、`robot.servos: xl330` |
| 3 | `.upstream/ft1910/docs/design/scs-bus.md` | `scs`/`scs_config` 两键拒绝、1M、`imu_id=200`、EEPROM 写锁回读、What is verified and what is not |
| 4 | `.upstream/ft1910/AGENTS.md` | 「每个机制一页主人」「Never design around a version difference」（后者明确不借） |
| 5 | `.upstream/kissqy/README.md` | 版本配对、BUILD.json / PUBLICATION-MANIFEST.json、「源码公开不扩大实机验收范围」 |
| 6 | `.upstream/replica/docs/软件来源与我们的改动.md` | 「以 kissqy 最新版为底叠补丁」 |
| 7 | `.upstream/replica/docs/HD-1910训练前数据清单.md` | 【出处标记】、XL330 仿真值四处差异、左右腿轴向符号相反 |
| 8 | `.upstream/replica/docs/superpowers/verification/2026-10-23-imu-revalidate.md` | Verified locally / Board acceptance still required、do not claim success until read back |
| 9 | `.upstream/open-microduck/book/editorial/04-evidence-backlog.md`、`research/source-ledger.md`、`tools/check_book.py` | 证据台账字段、冲突处理、集合相等断言、Scope 声明 |
| 10 | `.upstream/mdlab/microduck_local/src/microduck_local/contract.py`、`.github/workflows/tests.yml` | 单一真相、pinned sha、已知缺口、SKIP 语义 |
| 11 | `.upstream/hd1910m/microduck_rl/scripts/audit_native_observation_contract.py` | `live_hardware_accessed=False`、`note: … Not proof of …`、空数据直接 raise |
| 12 | `.upstream/replica-kit/hardware/CURRENT_HARDWARE.md` | 「验证边界」列、广告参数≠实测 |
| 13 | GitHub `LuwuDynamics/xgoduck_rl` README + commit（联网一手） | vendor/bam、uv.lock、ONNX 与 run 同放、215 tests / 5-iter smoke / 61-14 metadata、Apache-2.0、11-09 活跃 |
| 14 | 本仓 `microduck-software/tools/hd1910/{pre_deploy_check,verify_official_loader,audit_robotd_toml}.py` | 5 守卫语义、官方读侧、`gain=200` 与 `:493` 的 500k hint |
| 15 | `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md` 行366/431 | `gain=200` 正确、`gain=8` 作废 |

---

## §7 Scope / 已知未闭环

- 本文是**软件工程实践对照**，不是硬件选型文档；所有采购判决以 SSOT 顶部判决表为准。
- kissqy `docs/BASELINE.md` 正文**未取得**（404）；文中只引用 README 对该文件的说明，不引用其内容。
- luwu 本地无源码，结论基于联网 README + commit 记录 + 我们 11-09 的 git blob sha 核对文档；**未抓其源码文件树**。
- 官方运行时仓本地无完整 clone，`policy-manifest.md` 取自三个 fork 的同名文档。
- 实物项仍未闭环：人人 `IMU` 上机认板、人人 HUB ¥36 几何/双铜柱/夹座卡尺、金属结构件「共 7 个」对应、左右腿文字定义、`INCONCLUSIVE_RATE_MISMATCH`（R3 未消）。**读得到源码不等于这些已验证。**
- 训练线 #76（各动作 ≥3 seed sweep）/ #77（可选 VelStand / 手柄遥操作）仍 pending，本文不涉及。

---

## §8 落地件与验收结果（A1 / A2 / A3，纯新增）

### 8.1 新增文件（9 个，全部纯新增；未改动任何既有工具的数字或代码）

| 文件 | 作用 |
|---|---|
| `microduck-software/tools/hd1910/line_labels.json` | **线别唯一主人**：三条线的判据常量、共享非判据、19 个工具标签与一手证据、`policy` 拒绝规则、`known_gaps` |
| `microduck-software/tools/hd1910/line_contract.py` | A1 跨线拒绝门禁：`--check` / `--selftest` / `--list` / `--tool` / `--json` |
| `microduck-software/tools/hd1910/closure_contract.json` | **悬案唯一主人**：6 个标记（5 `UNVERIFIED` + 1 `CLOSED`），每条带证据性质、适用边界、本地已验、上板验收步骤、仍欠、负对照、阻塞动作、出处、签字人 |
| `microduck-software/tools/hd1910/check_closure.py` | A2 校验器：id 集合与 `docs/` 扫描集合相等、`UNVERIFIED ≠ PASS`、`--ship-gate`、契约 sha256 |
| `microduck-software/tools/hd1910/run_all_gates.py` | A3 统一门禁：2 个 meta 自检 + 全仓 36 个 `--selftest` 逐个真跑 CLI，报告覆盖差集、**解释器事实**与 Scope |
| `microduck-software/tests/test_line_guard.py` | 6 个测试（含 CLI 真跑与跨线拒绝负对照） |
| `microduck-software/tests/test_closure_contract.py` | 4 个测试（含 ship-gate 必红与 JSON 报告） |
| `microduck-software/tests/test_run_all_gates.py` | 5 个测试（含注入坏工具让门禁翻红、删掉后转绿、解释器显式报告、空发现清单必红） |
| `docs/active/microduck-四源软件工程对照与取长补短-2026-11-11.md` | 本文 |

### 8.2 命令（cwd = `microduck-software`）

```bash
.venv-mjlab/Scripts/python.exe tools/hd1910/line_contract.py --check
.venv-mjlab/Scripts/python.exe tools/hd1910/line_contract.py --selftest
.venv-mjlab/Scripts/python.exe tools/hd1910/check_closure.py --check
.venv-mjlab/Scripts/python.exe tools/hd1910/check_closure.py --check --ship-gate
.venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --check
.venv-mjlab/Scripts/python.exe -m pytest tests/ -q
```

### 8.3 实跑验收（全部真跑，非「沿用归档」）

| 项 | 结果 |
|---|---|
| A1 `--selftest` | **16/16**，rc=0 |
| A2 `--selftest` | **17/17**，rc=0；id 集合 `docs=6 / contract=6` 相等 |
| A3 `--selftest` | **16/16**，rc=0（5 个注入假工具真作为 CLI 进程跑；含解释器与空清单负对照） |
| A3 `--check` | **38/38 PASS**（2 meta + 36 工具），`verdict=ALL_PASS`、`ship_verdict=NOT_SHIPPABLE`、rc=0；报告带 `interpreter` 段 |
| 全量 `pytest tests/` | **115 passed in 136 s**，rc=0（原 100 + 新增 15） |
| A2 `--check` | 结构 PASS、`ship_verdict=NOT_SHIPPABLE`、rc=0 |
| A2 `--check --ship-gate` | **rc=1**，`SHIP GATE REFUSED: 5 contract(s) not closed` |
| A1 未登记工具 | 20 个，按 `REPORT_ONLY` 显式列为覆盖差集，不假装全覆盖 |

### 8.4 负对照（改坏必红，逐条实跑通过）

A1：B 代工具查路① 必拒且关掉拒绝会放行；`gain=200` 塞进 risk_tokens 必红；伪造 token 必红；空工具清单必红；抹平两条线必红；`current_line` 写错必红；未登记工具不得签收。
A2：删/重复/伪造 id 必红；`UNVERIFIED` 塞证据冒充闭合必红；`CLOSED` 清空证据必红；删负对照/删上板验收步骤必红；空契约必红；`rule` 抹掉 `UNVERIFIED` 语义必红；`scope` 声称碰过硬件必红；docs 出现未登记标记必红；全闭合有证据才 `SHIPPABLE`，塞回一个 `UNVERIFIED` 立刻 `NOT_SHIPPABLE`。
A3：`rc=2` argparse 判 `GUARD INVOCATION BROKEN`（非 SKIP）；关掉严格模式会把 rc=2 放成 SKIP ⇒ 证明门禁不是空操作；结论行 `SKIP`/`PARTIAL`/`NOT_SHIPPABLE` 不算 PASS；**正文提到状态词不得误判**；注入 broken.py 让 `--check` rc=1，删掉后 rc=0；注入缺 `onnx`/`onnxruntime` 探测结果时 `heavy_deps_ok` 必为 False；**空 `--tools-dir` 的零发现清单经 CLI 真跑必 rc=1 / `FAILED`**（`build_report([])` 旧版会假绿 `ALL_PASS`）。`test_run_all_gates.py` 不再硬编码 `12/12`，改为解析 `n/n` 并断言 `n>=12`（项目已因硬编码计数吃过亏）。

### 8.5 本轮抓到并修掉的自身缺陷

🔴 **A3 第一版把 `SUSPECT` 写成全文正则**，结果 4 个全绿工具被误报：`assert_ci_verdict.py` / `assert_clean_checkout.py` 的负对照说明里含 `SKIP`、`check_closure.py` 输出 `NOT_SHIPPABLE`、`run_all_gates.py` 负对照名里含 `SKIP`。这正是准则「裸子串匹配被反义复合词反噬」。修法：只认**结论行**（`self-test:` / `verdict =` / 最后一行裸状态词），并新增 `mentions_skip.py` 假工具做负对照证明不再误判。修正后 38/38 全绿。

🔴 **提交前审阅抓到缺陷 2：`PY = sys.executable` 未作为事实报告。** 用系统 python 跑 `--check` 得到 `28/38 NOT_PASS 10 / rc=1`，换项目自带 `.venv-mjlab/Scripts/python.exe` 则 `38/38 / rc=0`；10 个 FAIL 全是 `ModuleNotFoundError: onnx / onnxruntime / mjlab_microduck`，**不是工具损坏**。这命中准则 5（「装不上/没有」先穷尽现成环境），也命中四源共识「已知 gap 要显式列出」。若照旧提交，docstring 里那句 `python tools/hd1910/run_all_gates.py --check` 会让下一个人得到一片假红，甚至可能为了「修绿」去乱改工具。修法：新增 `interpreter_info()` / `heavy_deps_ok()`，报告带 `interpreter` 段（`executable` / `heavy_deps` / `heavy_deps_ok` / `project_venv` / `child_guards_inherit`），非 `--json` 模式在缺依赖时打印 HINT 并点名项目 venv；docstring 与 usage 一律改为 venv 命令。**判定语义不放宽**：依赖缺失仍是 `rc=1 FAIL`，绝不降格为 SKIP 或 PASS；`--json` 输出保持纯 JSON，HINT 不泄漏。

🔴 **提交前审阅抓到缺陷 3：零证据假绿。** `build_report` 旧版 `verdict = "ALL_PASS" if n_bad == 0 else "FAILED"`，当 `statuses == []`（工具目录被清空 / 注入空目录）时 `n_bad=0` ⇒ 报 `ALL_PASS` 且 rc=0。修法改为 `statuses and n_bad == 0`，并在 selftest 与 pytest 各加一条 CLI 负对照（空 `--tools-dir` 真跑必 rc=1 / `FAILED`）。

### 8.6 已知缺口（显式列出，不假装全覆盖）

- 20 个 `--selftest` 工具尚未登记线别 → `REPORT_ONLY`；需要时可用 `--list` 查看并逐个补标签。
- `ship_verdict` 恒为 `NOT_SHIPPABLE`（5 个 `UNVERIFIED`），这是**如实状态**而非工具失败；`--ship-gate` 供未来整机签收时使用。
- 所有报告带 `live_hardware_accessed=false` 与 `not_proof_of`；`robotd --sim` 验不了总线驱动/BLE/ISP/NPU/编码器，**不能消 `INCONCLUSIVE_RATE_MISMATCH`**。
- 官方 `docs/BASELINE.md` 正文未取得（404）；luwu 未抓源码文件树；官方运行时仓本地无完整 clone。
- **解释器是门禁的隐含输入**：子门禁继承 `sys.executable`，必须用项目 `.venv-mjlab`（见 §8.2）。系统 python 下 10 个工具因缺 `onnx/onnxruntime` 而 rc=1；报告 `interpreter` 段如实记录该事实，但这仍是一次 **FAILED** 运行，不升格为 PASS。
- A3 的 `--check` 只验证「离线门禁能被真跑且结论诚实」，含 36 个 `--selftest`；不等于 CI 全链路、不等于上板验收。

### 8.7 零改动负对照

本轮**未碰** SSOT、`build.py`、两份交付 xlsx、`.ref/` 生成源、任何既有工具的数字或代码；阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579` 一律不变。**纯新增 + 定点追加文档**。提交范围按用户拍板：仅 §8.1 列出的 9 个新增文件；两份手改 xlsx、`.ref/` 生成源、5 个过程产物不入库。

### 8.8 提交前审阅（Pass104，真跑而非沿用归档）

审阅动作与结论：

| 检查 | 结果 |
|---|---|
| 工作树 | 18 个未跟踪项 = 9 个本轮新增 + 9 个原有约定不入库项；`git diff --stat` 为空 ⇒ 既有文件零改动 |
| 权威文件 mtime | SSOT `2026-11-10 17:36`、照着买 xlsx `17:43`、对比整合 xlsx `10:38` 全部未变 |
| 本机路径 / 密钥扫描 | 9 个文件 `NONE FOUND (clean)`；两个 JSON 合法、6 个 py 语法 OK |
| `git check-ignore` | 9 个文件全部可入库 |
| 管线吞 rc 复核 | `check_closure --check --ship-gate` 真 rc=1（`| tail` 曾把它显示成 0，已用重定向落 `$?` 重验）；`--check` 真 rc=0 |
| 门禁复跑 | `line_contract 16/16`、`check_closure 17/17`、`run_all_gates 16/16`、`pytest tests/ 115 passed` |

🔑 **解释器对照实验**（本轮最有价值的发现，见 §8.5 缺陷 2）：同一个 `--check`、同一份代码，只换解释器：

| 解释器 | 结果 | rc | 结论 |
|---|---|---|---|
| 系统 python 3.13.12 | `PASS 28 / 38 NOT_PASS 10` | 1 | 10 个 FAIL 均为 `ModuleNotFoundError: onnx / onnxruntime / mjlab_microduck` |
| 项目 `.venv-mjlab/Scripts/python.exe` | `PASS 38 / 38 NOT_PASS 0` | 0 | 依赖齐备，`ALL_PASS` |

两者都是诚实结果，但**红 ≠ 工具坏**。修复后系统 python 那一行会显式打印 `heavy_deps = MISSING` 与项目 venv 的 HINT，报告 `interpreter` 段记录 `executable` / `heavy_deps` / `heavy_deps_ok`，且仍判 `FAILED` rc=1；`build_report([])` 的零证据假绿也一并堵死。修复后复验：venv `38/38 rc=0`、系统 python `28/38 rc=1 + HINT`、空 `--tools-dir` `FAILED total=0 rc=1`、`--json` 仍是纯 JSON。

📌 本轮**仍未消**的悬案一个都没动：`INCONCLUSIVE_LIVE_IDENTIFY` / `DIMENSION` / `CURRENT` / `RATE_MISMATCH` / `LR_LABEL` 全部 `UNVERIFIED`，`ship_verdict` 如实保持 `NOT_SHIPPABLE`。离线门禁全绿不等于上板验收。

