# MicroDuck / HD-1910 复刻线 — 对比官方与社区项目的缺陷清单

_日期：2026-11-07 · 对照对象：`pollen-robotics/microduck`（运行时，13.5k★）、`pollen-robotics/microduck_rl@develop`（训练）、本仓库复刻线 `.upstream/hd1910m/microduck_rl` 与 `microduck_rl-develop`。_

> **方法纪律**：所有「官方有什么 / 我们没有」结论，均先查一手源码（GitHub API + 拉取 env cfg / tests）再下结论，不靠记忆。本清单里有一条上一轮误判，已在本轮查证后**纠正并标注**（见缺陷 3）。

---

## 0. 结论摘要

- 本项目在**仿真评测严谨度**和**plant 专用重训体系**上已经做得比官方某些环节更深，不是「全面落后」。
- 真正的缺口集中在三块：**① 真机部署闭环**（硬件未到 + publish 链对 HD-1910 失效）、**② 可复现性 / provenance 基础设施**、**③ 真机时序编排 + 齿隙在正确电压下验证**。
- 上一轮我提出的「缺陷 3：站起 head-mask 防御没做」是**误判**：官方修复机制不是 head-mask，且 **HD-1910 活动上游（`hd1910m`）已经包含正确的站起修复**。本轮已纠正，该条改为「已具备」。
- 「缺陷 4：缺 tests/ 回归套件」**已于 2026-11-07 补齐**（`tests/test_hd1910_configs.py`，9 项，CPU 可跑，live kp8 实测通过）。
- **缺陷 1（真机加载自检）与缺陷 2（训练 provenance）已于 2026-11-07 当晚补齐**：conductor `pre_deploy_check.py` 串起 contract/bundle/numeric/toml 四关，实测抓到参考 `robotd_hd1910_mode0.toml` 缺 `bus.joint_ids` 的真实 blocker；provenance 已并入 `heading_meta` 与所有 `runmeta`（含给 4 个启动器补固定 seed）。
- **Pass5（2026-11-07 收口）— 新工具回归测试补齐**：前序 Pass 落地的 conductor / rehearsal 封装 / provenance 三个新工具原本无回归测试；新增 `microduck-software/tests/test_hd1910_tooling.py`（5 项，CPU-only，不烧 GPU），锁死 conductor `_classify` 返回码分类、`--selftest` 四关全绿、rehearsal 的 ONNX↔plant 跨 plant 守卫（m5@p8 告警/m5@m5 不告警）、provenance 关键键齐全。实测 `5 passed`。至此**不烧 GPU 的工程 / 部署就绪缺口全部收口**。
- **Pass6（2026-11-07 晚 · 二轮循环）—— 抓到并修掉一个真 bug：跨 plant 守卫对真实产物全面失效**。Pass5 测试只喂了理想的 preset-id 串，假绿。复检发现训练侧实际写出**两种 `plant` 格式**：runmeta 字符串（含 `hd1910_kp8`/`hd1910_kp5` 训练侧命名串）+ heading_meta 嵌套 dict（`name='hd1910' kp_fw=N`）。而 `_onnx_plant_key` 对嵌套 dict 直接 `TypeError` 崩溃、对训练侧串返回 `None`——**部署候选 p8head ONNX 彩排会整段崩溃、且跨 plant 守卫对大多数真实格式死掉**（正是它要防的 XL330↔HD1910 事故）。已加 `_normalize_plant` 统一两套命名 + kp_fw 消歧，守卫改为「能解析就查、不要求 ONNX 文件存在」，`_report_onnx` 容错缺失文件；测试扩到 6 项（覆盖全部真实格式 + 真实 p8head heading_meta 派生 ONNX 在 m5 下触发 CROSS-PLANT、在 p8 下不触发）。实测 `6 passed`（全 suite 15 passed）。**结论修正**：Pass5 称「收口」过早——守卫本身有 bug，是靠 Pass6 才真正收口。
- **Pass7（2026-11-07 末 · 三轮循环）—— 又抓到一层假绿盲区：Pass6 测试仍只喂「有 meta 的长名 ONNX」（`p8head_030_4096x3000_resume2999_it2999.onnx`），而**真正的部署候选 `p8head_2999.onnx` / `onnx_p3head030_it1600.onnx` 是短名、无 companion meta**，`_onnx_plant_key` 对它们仍返回 `None` 放行——也就是「要上机器人的模型」跨 plant 守卫反而失效**。补 `_plant_from_filename` 文件名推断兜底（只覆盖 `p8head/p3head` 这类明确承载 plant 的部署候选前缀；`deploy61`/`walk_std` 等旧模型保留 `None` 不误判）；测试改为直接对真实部署候选短名生效（去掉对 meta 的 skip 依赖）。`_onnx_plant_key` 现对全部 8 个真实 ONNX 解析正确（`p8head_2999`→p8、`onnx_p3head030`→p3、旧模型→None）；测试扩到 7 项。实测 `7 passed`（全 suite 16 passed）。**结论再修正**：Pass6 仍未真收口——守卫对真实部署候选失效，是靠 Pass7 才真正收口。
- **Pass8（2026-11-07 · 四轮循环 · 继续审计）—— 抓到 config 回归测试的环境假绿并消除**。`tests/test_hd1910_configs.py` 在模块加载时调 `apply_to_live.py --check` 探测 live plant，**非 HD-1910 就整文件 `skip`**——所以在没 `apply` HD-1910 的机器 / CI 上，这 9 项静默跳过却显示「绿」，HD-1910 配置被改坏也抓不到。机理核实：`apply_to_live` 只换 `microduck_constants.py` 里的 `_BAM_ACTUATOR_KWARGS` 块（json_path/kp_fw/motor_name），**机器人 XML / 运动学 / env-cfg 奖励·课程定义全在块外，随 plant 不变**——旧 skip 是**过度保守**。重构：**运动学测试用隔离加载器 `_load_constants_for_plant` 按源直接加载每个 HD-1910 plant（不碰 live 文件），参数化覆盖 4 个变体（hd1910/kp5/kp8/ftservo_m6）**，并新增 `test_joint_order_identical_across_hd1910_plants` 跨 plant 一致性守卫（切 kp_fw/params 不能静默重排关节）；**env-cfg 测试断言 plant 无关、去掉 blanket skip 后无条件跑**。仅保留「mjlab_microduck 不可 import」的合法 skip。**实证**：xl330-live 下旧版 9 skipped→假绿，新版 **25 passed / 0 skipped**；恢复 kp8-live 后 sha16 完全一致；全套 32 passed（25 configs + 7 tooling）。**结论**：这是上一轮标记的「环境假绿」风险，本轮真正消除。

- **Pass9（2026-11-08 · 五轮循环 · 部署闸门真收口）—— 抓到部署级致命盲区：conductor 四关「全过」却没把三个 kp8 策略接到 robotd.toml**。查一手源码确认 `robotd-params/src/lib.rs:604-733`：`[policy]` 段 `walk/stand/ground_pick` **不设路径**时，robotd 回退到发布目录默认官方 alpha 策略（`/opt/robot/daemon/current/policies/alpha_*.onnx`）——即机器人会加载官方策略，**不是**我们训练的 kp8。而 conductor 的 toml 关（`audit_robotd_toml.py`）只查 gain-scale 一致性，**从不校验 toml 里 `[policy]` 路径是否指向我们验证过的 onnx**，于是「四关全过」只是格式校验，真上机会加载错策略（静默错配，正是项目头号风险）。修法：① `robotd_hd1910_mode0.toml` 的 `[policy]` 段显式接上三个验证过的 kp8 onnx（`walk`/`stand`/`ground_pick`，仓根相对路径）+ `enabled=true`/`mode="walk"`，并注释生产须改绝对路径；② 给 `audit_robotd_toml.py` 加**策略路径接线检查**——未设必填槽位→告警（回退官方 alpha）、设了但文件不存在→FAIL（加载失败），含 4 条负对照 selftest（悬空 FAIL/未设告警/存在 ok/`"none"` 不告警），`pre_deploy_check.py --selftest` 全绿覆盖；③ 顺带抓到 Pass6/7 遗留盲区：跨 plant 守卫 `_onnx_plant_key` 对**真实导出的** groundpick/standup onnx 返回 `None`（rsl_rl 导出文件名带 `YYYY-MM-DD_HH-MM-SS_` 时间戳前缀，companion runmeta/heading_meta 不带，meta 查找整体 miss、文件名启发式也不匹配）——守卫对「要上机器人的真实产物」静默。修法：在 `_onnx_plant_key` 起步先 strip 前导时间戳，三个真实 onnx 现全部解析为 `p8`。④ 新增 `test_onnx_plant_key_real_exported_artifacts` 喂真实导出产物锁死该修复（Pass6/7 教训：测试必须喂真实产物）。⑤ 生成 `out/hd1910_kp8_deploy_bundle.json` 单一可信源（plant 指纹 + 三 onnx + toml 的 sha256 + 三份 deploy_check 结论 + 评测结果），治「publish 不打包外部权重 / 无单一可信源」风险。全套测试 **33 passed**（32→33）。**结论**：Pass8 称「工程/部署就绪缺口全部收口」仍过早——部署闸门本身有「格式过、策略没接上」的致命盲区，是靠 Pass9 才真正收口。

- **Pass12（2026-11-08 · 六轮循环 · 继续审计）—— 戳破「闸门关了就一定能复现」盲区：部署验证工具链 onnx 依赖未声明**。Pass9 把 conductor 四关接到真实 kp8 onnx 后，本轮不信任归档 JSON、直接实跑验证当前磁盘：① `sha256sum` 三 kp8 onnx + toml 与 `hd1910_kp8_deploy_bundle.json` 记录**逐字节一致**（无 bitrot）；② `audit_robotd_toml.py`（仅 stdlib，沙箱可实跑）对当前 toml 退出 0、all pass，三策略路径均存在、reg50=16 增益标度匹配，唯一 WARN 是 HD-1910 机体非 XL330 参考集（预期）；③ toml 的 `joint_ids`/`joint_signs` 与权威 `.upstream/hd1910m/radxa/installation.json` 逐条比对**完全一致**，关掉「照抄别的项目 ⇒ 15 颗全错位」风险（源 `calibration_verified=false` 仍须真机复核）。**新盲区**：`verify_policy_bundle.py`/`rehearse_hd1910.py` 需 onnx+numpy，但仓库唯一依赖清单 `repo/pyproject.toml` 是训练环境且不含 onnx——`git clone`+`uv sync` 后无法再跑 bundle/rehearsal 闸门，部署结论不可复现。修法：新增 `tools/hd1910/requirements.txt` 显式声明 onnx/numpy。另修正两处自述口径：bundle「22 negative-control self-tests」改为准确「39 断言=11 contract+1 clean+27 负对照（22 个 N 场景）」；toml「HD-1910 / Radxa line」措辞澄清——本 toml 走 DuckBuddy-main 那代 robotd（feetech_hls，会做 EEPROM 开机硬校验），radxa 只是上游目录名、非 FT-SCS 那代。**结论**：Pass9 收口在格式/策略接线层面成立，但「可复现」层面漏了工具链依赖，本轮补上。

- **Pass13（2026-11-08 · 七轮循环 · 对照开源项目）—— 对照 upstream `pollen-robotics/microduck_rl` 与业界（reflex-vla / ETARS / LeRobot / lerobot_humanoid_runtime）部署验证做法，戳破「静态检查全过 = 策略能跑」盲区**：① 上游 `find_onnx_source.py` 用 bit-exact 权重匹配把部署 onnx 回溯到训练 checkpoint，且 `pyproject.toml` 显式声明 `onnxruntime>=1.24.4`+`onnx>=1.20.1`；reflex-vla 的 `reflex validate export` 做 ONNX↔PyTorch 机器精度 parity（退出码 0/1/2 供 CI）+ `--init-ci` 自动生成 GH Actions；ETARS 有 `test_compare_policies.py` 跨后端数值比对；`lerobot_humanoid_runtime` 强调「Calibration mandatory + 分阶段安全运行器」。对照暴露我们两个真缺口：**(a) bundle 只记 sha256、无训练 provenance（commit/seed/env/配置哈希）**；**(b) 验证只做静态检查（IO 宽度/权重嵌入），从不真正执行策略图**——一个导出时图层错/常量/爆炸的动作，静态闸门全过却上机「看起来走然后摔」。修：新 `record_provenance.py` 从伴随 `runmeta_*.json`/`heading_meta_*.json`（task/seed/envs/iters、`cfg_sha256_16`/`mdp_sha256_16` 环境配置哈希、created 时间戳、完整 CLI、plant 来源文件）+ 复用既有 `_provenance.capture_provenance`（git branch/dirty/`git diff HEAD` sha256 指纹）提取 provenance 注入 `hd1910_kp8_deploy_bundle.json`（不依赖 onnx）；新 `verify_policy_inference.py` **真用 onnxruntime 执行 onnx** 并断言输出 finite / 非爆炸 / 非退化常量（依赖缺失 rc=2 SKIP 而非误判失败），检查逻辑纯 Python（不依赖 numpy）故负对照 selftest 在干净环境可证；前者挂进 conductor 成第五关（inference）。另加 `.github/workflows/deploy-gate.yml` 把闸门配进 CI（reflex `--init-ci` 模式）防 bitrot；`requirements.txt` 补 `onnxruntime>=1.24.4` 并对齐上游 onnx 版本。新增 5 项回归测试（provenance 提取 3 + 推理负对照 2）。**诚实声明**：本沙箱仍装不上 onnx/onnxruntime/numpy（网络受限），故 inference「真执行 onnx」与 bundle/numeric 两关 selftest 未在沙箱实跑（CI 装好依赖后会跑）；此限制 Pass12 已记、Pass13 未引入新回归。**结论**：Pass12 收口「可复现依赖」后，Pass13 把验证从「静态」补到「执行 + 可追溯 + CI 门禁」，不烧 GPU 的软件/工程就绪缺口已到很扎实的上界。
- **Pass14（2026-11-08 · 八轮循环 · 继续循环）—— 审查 Pass13 刚加的 CI 门禁与推理工具本身，戳破两处「门禁是摆设」盲区**：① `verify_policy_inference.py` 只「优先」输入名 `obs`、且 `--expect-act` 不匹配被静默忽略——但本代 robotd **硬编码**输入名 `obs` 且从不读 manifest（已证实 `verify_official_loader.py` 的 `input_name="obs"` 契约 + 我们的 `eval_*.py` 都喂 `{"obs": x}`），且官方 `hl2915_standup` 正是 28-vs-14 元数据错乱的先例；这两种不匹配都会让 onnx「所有静态/执行闸门全过却上机加载必炸」。已改为 **FAIL**：输入名必须 `obs`、`output_len` 必须 `expect_act`，抽 `validate_inputs`/`validate_outputs` 纯 Python 负对照（空输出防 IndexError）。② `record_provenance.py` 的 CI 步骤 `record_provenance.py --print` **缺必填 `--onnx`** 实为空指令（被 `continue-on-error` 掩盖）。已把 `--onnx` 改可选、加 `--verify` 完整性闸门（重算 bundle 记录的 onnx provenance 与伴随 meta 比对，检测「onnx 改了但 provenance 没刷新」，纯 stdlib 可在 CI 跑；code git_commit 仅 WARN 不 FAIL 因提交会变）。CI 工作流改为 `--bundle ... --print` + 新增 provenance-verify 步骤。新增 4 项纯 Python 回归测试（inference 宽度不匹配 FAIL / 输入名 obs 契约 / provenance verify 一致 / verify 抓漂移）。**沙箱可证**：inference selftest 全绿、provenance `--verify` 对真实 bundle 一致（rc=0，git_commit WARN 为预期）、`--print` 不再需 `--onnx`、所有 `--help` 合法、conductor 内 inference.selftest PASS。**结论**：Pass13 把门禁搭起来了，Pass14 让门禁本身「真拦得住」，不烧 GPU 的部署就绪缺口进一步收到上界。
- **Pass15（2026-11-08 · 九轮循环 · 继续循环）—— 审计整个循环从未打开过的第一道闸门 `verify_policy_contract.py`（obs 布局/关节顺序/HOME/动作映射↔robotd obs.rs）**：精读确认它**不是「只建议」**——`check_joint_order`/`check_home_pose`/`check_block_order` 都是 `a==b`/`max|diff|>tol` 直接 FAIL，未知项 `raise NotChecked` 而非瞎猜；selftest 有 10+ 个真负对照（关节交换/HOME+1°/宽度60/块交换/action_scale 0.5/head↔body 交换/速率100Hz/省略键陷阱）。**但**发现结构性盲区：该关的 `Training` 侧必须 `import mjlab_microduck`（整训练栈 torch+mujoco），而 `tools/hd1910/requirements.txt` 不含它 → `contract.selftest` 在 CI 里 `NotChecked→rc=2→SKIP`，即**最结构化的 obs 布局/关节顺序/HOME/动作映射检查在 CI 里根本没跑**；且 conductor 原 verdict 只含糊写「see SKIPs」，易被读成绿。加固：conductor 抽出 `_verdict(any_fail, skipped)`，当有结构性闸门 SKIP 时 verdict 显式标 **PASS\*** 并列出被 SKIP 的关名（如 contract），不再含糊；JSON 报告加 `skipped_stages`；CI 工作流注释明示 contract 在 CI 跳过、发货前需本地带训练栈跑。新增 1 项测试 `test_conductor_verdict_surfaces_skips` 锁死 PASS\* 分支。**诚实声明**：contract 真执行仍需训练栈（沙箱无 mjlab_microduck，无法实跑其 selftest）；本轮未引入新回归。**结论**：整个 conductor 五关（contract/bundle/numeric/inference/toml）现已全部被审计过「是否真强制」；contract 逻辑正确，唯一缺口是它依赖训练栈、CI 跳过——已用 PASS\* 让该缺口可见而非静默。

> **2026-11-08 训练状态（与审计并列）**：P0 行走 kp8 续训完（`model_7999`，指标健康，conductor 四关过）；P1 地面拾取 kp8 评测 **96.9%** 通过（四关过）；P2 站起——官方 `hl2915_standup` 在 kp8 仿真能 100% 站起但被 bundle 关拒（metadata 28 关节名 vs 14 动作），改训 **kp8 原生站起**（4096×4000），导出 onnx 后 conductor 四关过、实测站起 **100%**，三个 kp8 技能全部训练自有/同 plant 验证/闸门全过。P3（≥3 seed sweep）用户裁定暂缓，P4 未启动。硬件未到，真机端到端验证（bus.joint_ids 逐关节复核、齿隙 7.4V 重测）待硬件。

---

## 1. 本项目已经比官方更扎实的地方（别重复造）

- **评测严谨度**：`plant_id` 指纹 + 同 plant 评测 + 负对照 + 物理量分布检查，比官方 `publish` 仅做 NaN/常量输出检查严得多。曾据此纠正「kp8 行走 82% 摔」的跨 plant 误测（实为 m5 模型错放到 kp8 评测）。
- **ONNX 契约校验**：`verify_policy_contract` / `policy_numeric_gate` 已兜住 `deploy61` 1157× 放大 bug，比官方更硬。
- **plant 一等坐标 + swap_plant**：复刻线必须、官方不需要，已闭环证明「官方策略不能直接移植 HD-1910」（groundpick 96.9% vs 官方 23.4%）。
- **plant 健康自检**：`apply_to_live.py --check` 带回读门禁（reg6/33/9/11、kp_fw、json sha），是官方没有的。

---

## 2. 缺陷清单（按严重度）

### 缺陷 1 — 真机部署闭环 ⚠️ 战略级（部署链待硬件到货端到端，但「加载自检」已补齐）
- **官方**：`pollen-robotics/microduck` 有一套 `publish → robotctl policy add/load → robotctl robot do` 部署流；`policy-manifest.md` 定义 61 维观测契约，运行时热插拔 walk/recover/trick。
- **本项目**：硬件还在下单（Radxa 线）；且本项目文档已承认 **`publish` 与这一代 HD-1910 的 robotd 不是一条链**——manifest 字段一个都不生效，`robotctl policy load` 对 HD-1910 是另一套系统。当前所有「部署」只是 `rehearse_deploy.py` 的仿真彩排。**部署链本身要等硬件到货才能端到端验证，这一半仍是 OPEN。**
- **后果**：sim 再完美，真机上 ONNX+manifest 格对不对得上、能不能跑全是未知。
- **补后（2026-11-07 当晚）——「加载自检」已补齐，部署契约已定**：
  - **契约**：`tools/hd1910/deploy_import_checklist.md` 已把 HD-1910 真机部署契约写成 B/C/H 三段（obs 61 / act 14 / 50 Hz；normaliser 下限；manifest 不生效、B 代 robotd 真实吃哪些键；reg6/33/9/11 硬校验；`joint_ids` 必需等），无需另起文档。
  - **一键加载自检 conductor**：新增 `tools/hd1910/pre_deploy_check.py`，把现有 4 道独立守卫串成**一个 verdict**：
    - `contract`（`verify_policy_contract.py`）：obs/act 布局、关节序、HOME、action 映射 ↔ robotd `obs.rs`；
    - `bundle`（`verify_policy_bundle.py`）：normaliser 下限 + 元数据 + 无 EXTERNAL 权重 + joint_names；
    - `numeric`（`policy_numeric_gate.py`）：G1–G4 绝对量级门禁（兜住 `deploy61` 1157× 放大）；
    - `toml`（`audit_robotd_toml.py`，`--expect-kp 16` 匹配项目既定 reg50）：robotd.toml 增益标度一致性。
  - **已实测验证**：`--selftest` 四关全绿；对真实策略 `hd1910_resume_5999.onnx` ONNX 三关 PASS；对已知坏策略 `deploy61.onnx` 正确 FAIL（bundle+numeric 抓到 normaliser 地板击穿）；对参考 `robotd_hd1910_mode0.toml` 抓到 **`bus.joint_ids` 为空**——飞特总线拒绝打开，是真实 pre-deploy blocker（见下）。
  - **conductor 新暴露的 blocker**：参考 `robotd_hd1910_mode0.toml` **缺 `bus.joint_ids`（15 条）**。B12/H11 已写明这是必需的（空则总线拒绝打开，`robotd/src/main.rs:5495`），但参考 toml 一直空着。硬件到货前必须按 HD-1910 映射填 15 个 ID（B 代 schema：右腿 10–14 / 左腿 20–24 / 头 30–34；或 HD-1910 1–15 体系——需先定 schema 再填，不能照抄别的项目 `installation.json`）。conductor 现在会在这步判 FAIL，挡住「看起来能加载其实起不来」的静默事故。

### 缺陷 2 — 训练可复现性 / provenance 基础设施缺失 ✅ 已于 2026-11-07 当晚补齐
- **官方（2026-10-27 新增）**：`share-training` 把每次训练打成 HF bundle，带 git commit + 未提交 diff + 精确命令 + 父 ckpt + wandb 配置；`export.py` 把 `run_path/task_id/checkpoint/sha256` 烤进 ONNX 元数据。
- **本项目（补前）**：训练产物是本地 `.pt`，只有 ad-hoc 的 `out/runmeta_*.json`（含 plant/kp_fw/json sha/envs/iters）。**缺 git sha / diff / 精确命令 / seed**。目标「训练完美」但无法复现一个好 run，也无法从社区 ckpt 干净起步。
- **补后（2026-11-07 当晚）**：
  - 新增共享模块 `tools/hd1910/_provenance.py`：捕获 git commit / branch / dirty / **uncommitted-diff 指纹（sha256）** / 训练 seed / 精确命令 / 依赖版本（torch·rsl_rl·mjlab·onnxruntime·onnx·numpy）。
  - **heading 路径**：`train_heading_variant.py` 在写 `heading_meta_*.json` 时直接并入 `provenance` 块（覆盖所有 heading 训练 incl. `explore_heading.sh` / `resume_heading_run.py`）。
  - **standup / roller / groundpick 路径**：新增 `tools/hd1910/log_run_provenance.py`，把 `provenance` 合并进 `out/runmeta_<RUN>.json`；已接入 `resume_standup.sh` / `explore_standup.sh` / `train_roller.sh` / `explore_ground_pick.sh`（每个 run 一行）。
  - **固定 seed**：4 个启动器原本不传 `--agent.seed`（rsl_rl 默认，不可复现）——现在统一加 `SEED="${SEED:-42}"` 并传 `--agent.seed`，provenance 因此能捕获真实 seed；历史 runmeta 也可用 `log_run_provenance.py` 回填。
  - **实测**：对一个历史 runmeta 回填，正确拿到 `git 77de78d dirty=True diff指纹` + 依赖版本；`_versions` 经 `importlib.metadata` 兜底解析到 `mjlab 1.3.0`（rsl_rl 在本 venv 不可 import，如实记 `<absent>`，运行时经 `train.exe` 仍可用）。

### 缺陷 3 — 站起「冻背」固定点防御 ✅ 已具备（上一轮误判，本轮纠正）
- **上一轮误述**：我说官方用「head-masked teacher + head 50%/SO(3) 25% 加宽 spawn」。**查证后这是错的**——官方源码里没有 head-mask teacher，也没有这些概率。
- **官方真实修复**（`microduck_standup_env_cfg.py`，`improve_standup_velstand` 提交）：
  1. `set_ground_state` 事件里 `face_up_prob`（仰面/背朝地）从 **0.00 渐进到 0.35** 的反向课程（`ground_state_mix` 课程，step 0 → 600×24 → 1500×24 → 2500×24）；
  2. `face_up_roll_max = 90°` 的部分翻滚噪声，给「平躺→俯卧」这段无梯度的恢复提供中间起点（built-in reverse curriculum）；
  3. 基于 tilt 的奖励门控（`arrival_damping`、`head_pose_bias`，`tilt_full_deg=20`、`tilt_zero_deg=45`），且权重严格在 iter 3000×24 才从 0 引入——避免运动惩罚阻断恢复动作的「发现期」。
- **关键**：本项目活动上游 **`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/tasks/microduck_standup_env_cfg.py` 已经包含以上全部**（grep 实证 `ground_state_mix`、`face_up_prob` 0→0.35、`face_up_roll_max` 均存在）。所以 **P2 的 kp8 站起从零训会直接继承这套修复，无需单独移植**。
- **本轮新增保险**：`tests/test_hd1910_configs.py::test_standup_has_face_up_recovery_curriculum` 锁死 `ground_state_mix` 存在且末态 `face_up_prob>0`，防止后续某次上游合并把它弄丢。

### 缺陷 4 — 自定义任务缺回归测试套件 ✅ 已于 2026-11-07 补齐
- **官方**：`tests/`（CPU 回归）锁死关节索引映射、奖励符号约定、servo geom 命名、NaN 守卫；如 `test_velstand_cfg.py`。
- **本项目（补前）**：80+ 个 probe/eval 脚本，但根目录无 `tests/`。「关节 ID 两套体系不能混用」恰恰是静默回归最易炸的点。
- **补后**：新增 `microduck-software/tests/test_hd1910_configs.py`（9 项，CPU-only，build cfg + compile MuJoCo，不步进 env），live `hd1910_kp8` 实测 9 passed：
  - 驱动关节数 == 14、关节顺序 == 规范 HD-1910 顺序（防跨编号体系静默 remap）；
  - allcollisions / walk / standup 三套 spec 关节运动学一致；
  - servo collision geom ≥ 14；
  - velocity 奖励符号约定（pose/track_*/upright/air_time 正，foot_slip/self_collisions/dof_pos_limits/action_rate_l2 负）；
  - velocity / standup cfg 能正常构建；
  - 站起 `ground_state_mix` 反向课程存在且末态 `face_up_prob>0`。
- **运行**：`.venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_configs.py -q`（需先 `apply_to_live --plant` 任一 HD-1910 变体；非 HD-1910 plant 时整套 skip）。

### 缺陷 5 — 齿隙（backlash）仿真未在正确电压下验证
- **官方**：齿隙建模为串联无驱动被动铰链，编码器/固件 PD 透过齿隙读数，obs 也读透过齿隙——sim2real 关键。
- **本项目**：HD-1910 是飞特舵机（非 XL330/BAM），有 `check_backlash_task.py` + Backlash 任务，但：① 是否「透过齿隙读数」未确认；② 台架是 4.6 V 欠压取的数，不可靠。
- **补法**：换 7.4 V 正确电压重测飞特齿隙，确认仿真模型与真机齿隙一致、编码器读透过齿隙。

### 缺陷 6 — 多策略热插拔彩排工具对 HD-1910 是坏的 ✅ 已具备（纠正误判）
- 官方 `infer_policy.py` 一套键盘热插拔 walk/stand/sitstand/roulade + sim2real CSV。
- **纠正**：本项目早已不是「写死」状态——`tools/hd1910/rehearse_hd1910.py` 是 HD-1910 专用封装：patch 上游 `rehearse_deploy.load_bam_model` 用 HD-1910 plant JSON、`BAM_MOTOR_NAME="hd1910"`、`--plant live|p3|p8|m5|ftservo`，默认 `live`（实测 `hd1910_kp8 → p8, kp_fw=8.0, m6`），由 `rehearse_hd1910.sh` 驱动。**单策略 BAM sim2real 彩排对 HD-1910 可用。**
- 本轮补充（2026-11-07）：① 修 `.sh` 默认跨 plant 隐患——默认 m5 ONNX 原本没传 `--plant`，会被 live(kp8) 去彩排（= 跨 plant 陷阱）；改为默认 `--plant m5` 自洽；② 给 wrapper 加 **ONNX↔plant 守卫**：读 ONNX 同目录 runmeta 的 plant 字段，与解析出的 plant 不符则大声告警（单测通过：m5@p8 告警、m5@m5 不告警）。
- **仍 OPEN（非阻塞）**：官方那种「键盘热插拔多策略 + sim2real CSV」完整套件；且 sitstand/roulade 等策略 HD-1910 尚未训练，多策略热插拔暂无意义。可作为 P4 后的增强。

### 缺陷 7 — 真机缺 phase / 姿态 flag 的时序编排器
- 官方由 daemon 驱动「地面拾取」的相位命令和「坐↔站」的姿态 flag。
- 本项目 groundpick 在 sim 里用相位命令，但**真机上没有控制器去驱动相位/flag**——phase 类策略上真机就没人喂时序。
- **补法**：随 SitStand + VelStand 一起做真机时序编排（缺陷 8 的动作补全项）。

### 缺陷 8 — 上游非 plant 专属改进需 re-sync（元缺陷）✅ 已逐条核（2026-11-07）
- 上游 `microduck_rl@develop`（至 2026-10-27）自上次对照后新增：`share_training`（HF 训练 bundle + provenance，已在缺陷 2 落地）、`improve_standup_velstand`（已在 hd1910m，缺陷 3）、**pickup detector（PR #70，2026-10-03）**、**转向/yaw 修复（2026-10-01/12）**。
- **pickup detector — 与 plant 无关但 HD-1910 不可直接 re-sync（暂缓）**：它是 robotd 端感知特性（仿真训练的时序 CNN + 滞后状态机，读 robotd 每 tick 读数暂停策略）。但 HD-1910 用的是 **FT-SCS 原生 / Radxa 世代** robotd（`.upstream/hd1910m`），grep `duck-control/src` + `configd` 确认**完全不含** `pickup`/`p_held`/`[pickup]`/暂停逻辑——属官方 XL330/Orange Pi 另一 robotd 世代，是跨世代移植而非 re-sync。且 HD-1910 的 ground-pick 是**训练侧**动作，「拿起暂停」是**运行时**特性，两回事。→ 列为 robotd 层未来增强，非训练 re-sync。
- **转向/yaw 修复 — 是训练侧奖励改动，归 P4 velstand 训练（非现在 re-sync）**：上游 `track_yaw_rate_fine`（yaw 专用细高斯，std 0.35，weight 2，2026-10-01）+ `turn_in_place_min_frac`（原地转向最小 frac，治 0.3 rad/s 死区）。grep hd1910m `microduck_velstand_env_cfg.py` **无此两项** → HD-1910 训练 velstand（P4）时务必把这两项并入 velstand env cfg / mdp.py（hd1910m `mdp.py` 现有 `hd_track_angular_velocity_axes` 自定义 yaw 项，需对照叠加，不可直接覆盖）。
- 结论：本轮没有可立即 cherry-pick 的「与 plant 无关且能直接提升」项；re-sync 价值集中在**训练侧（P4 velstand）**与**已落地的 provenance / 站起修复**。
- 附（信息）：官方 runtime 已 0.18.9，policy set 钉 v9（= v7 velstand 逐字节），v8 机器人上更差；API_VERSION 49→50。HD-1910 不消费官方 policy set（B 代 robotd 另一套），仅作上游动态参考。

### 缺陷 9 — HD-1910 打印件许可风险 ✅ 对自用场景 N/A（2026-11-07）
- **用户裁定：不商用，自用。** CC BY-NC-SA 4.0 仅限制**商业**再分发/再利用；个人自用（打印、训练、把玩）不受限。故该缺陷对当前项目目的**不适用**，无需 mitigation。
- **查实事实（备查）**：① 官方 `pollen-robotics/microduck` 整体 Apache-2.0，但 PR #73（2026-10-09）把 **3D 模型文件单独钉死 CC BY-NC-SA 4.0**（靠单独声明，不在主 LICENSE 内）。② HD-1910 复刻线（`.upstream/hd1910m`）的 STL 资源在 `microduck_rl/src/mjlab_microduck/robot/microduck/assets/*.stl`（ankle/head_shell/foot/trunk_base 等），是**复刻线自带的机身网格**（非直接搬运官方发布包）；其 LICENSE 由 `.upstream/hd1910m/THIRD_PARTY.md` 明定：本地集成快照**不改授第三方许可**，RL 部分保留 `microduck_rl/LICENSE`（Apache-2.0），但官方 3D 模型范围按上游 PR #73 为 CC BY-NC-SA 4.0。③ HD-1910 另有自建模证据：`robot_description/microduck.urdf` + 自定 `replica_mass_20261002.json` / `reference_hd1910_profile.json`（飞特版专属质量/惯量/作动器剖面）。
- **结论**：若未来要商用，需另寻许可来源或自建模（换掉 CC BY-NC-SA 网格）；当前自用无碍。下单前仍需核的是 **CAD 来源是否可信 / 结构是否适配飞特舵机**（工程问题，非许可问题）。

---

## 3. 动作覆盖对比（官方有 / 我们没有）

| 动作 | 官方 | 本项目 | 优先级 |
|---|---|---|---|
| **SitStand**（坐↔站指令） | ✅ Flat/Rough | ❌ 无 | **高** |
| **VelStand**（走+摔倒恢复合一） | ✅ v7 + lineage | 仅注册，未训 | **高**（对应 P4，建议提前） |
| **Rough 地形变体** | ✅ 多数任务有 | ❌ 只有 Flat+DR | 中 |
| **Roulade**（前滚翻） | ✅ | ❌ | 低 |
| **BallKick**（踢球） | ✅ | ❌ | 低 |
| **Swizzle / Spin**（轮滑花样） | ✅ | 只有 plain Rollers | 低 |
| **Running**（跑） | 社区有 | ❌ | 低 |

> 本项目已注册 Rollers / RollerCrouch / RollerSlope / RollerStandUp 四个轮滑任务，但 kp8 轮滑重训 89% 摔（欠训），按用户决策延后。

---

## 4. 下一步（接 P0–P4 训练计划）

1. **硬件到货前**：真机部署契约已定 + 加载自检 conductor 已落地（缺陷 1 后半）+ rehearsal 封装已具备（缺陷 6，含 ONNX↔plant 守卫与 .sh 自洽）；剩余 = 部署链端到端验证（待硬件）。✅ **参考 `robotd_hd1910_mode0.toml` 已补 `bus.joint_ids` + `joint_signs`**：取自权威 `.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`），ID 顺序 `[10,9,8,7,6,12,11,14,13,15,5,4,3,2,1]`，**不同于** XL330 参考 `[20-24,30-34,10-14]`。审计由 FAIL(空)→WARN(非参考集，预期内)，conductor toml 关转 PASS。真机到货仍需 `servo_probe/identify_joints.py` 逐关节复核（`calibration_verified=false`）。
2. **本次已落**：tests/ 套件（缺陷 4）+ 站起修复保险（缺陷 3 的测试化）+ 加载自检 conductor（缺陷 1 后半）+ provenance（缺陷 2）。
3. **provenance（缺陷 2）**：✅ 已落 —— heading_meta 与所有 runmeta 已含 git/diff 指纹/seed（4 个启动器补固定 seed）。
4. **动作补全**：优先 SitStand + VelStand（缺陷 7 时序编排一起做），tricks 类最后。
5. **齿隙（缺陷 5）**：硬件/电源到位后换 7.4 V 重测。
6. **re-sync（缺陷 8）** ✅ 已逐条核：pickup detector 不在 HD-1910 robotd 世代（暂缓）；转向/yaw 修复归 P4 velstand 训练 re-sync。详见缺陷 8。
7. **新工具回归测试（Pass5→Pass6 真正收口）** ✅ 已落并修 bug：`tests/test_hd1910_tooling.py` 原 5 项（Pass5）；**Pass6 扩到 6 项**——发现并修掉 `_onnx_plant_key` 对真实产物（heading_meta 嵌套 dict 崩溃 + 训练侧命名串失配）全面失效的 bug，守卫现覆盖全部真实格式。覆盖 conductor 返回码分类 / `--selftest` 四关 / rehearsal 跨 plant 守卫（含真实 p8head 部署候选 ONNX）/ provenance 关键键。实测 `6 passed`（全 suite 15 passed）。
   - 剩余 OPEN（**非软件缺口**）：真机端到端验证（硬件未到货）、`bus.joint_ids` 真机逐关节复核（`calibration_verified=false`）、齿隙在 7.4 V 正确电压下重测（台架 4.6 V 欠压）、P4 训练侧转向/yaw re-sync。

---

## 4.1 Pass10 自主审计（2026-11-08）— 发布链与彩排真收口

- **publish 链真相（一手查证）**：`verify_policy_bundle.py` 文档 + `duck-control/src/policy.rs` / `robotd-params` 确认——**这代 robotd（DuckBuddy-main HL-2915 build）只做 `check_width(inputs[-1]==61)` + `check_width(outputs[-1]==14)` + `Observation::zeroed()` warm-up + input name 硬编码 `"obs"`；从不读 manifest、从不读 ONNX metadata**（grep metadata robotd/duck-control/ 返回 nothing）。`publish`（`microduck_rl` `publish/manifest.py`）写 manifest/metadata 是给「另一代 robotd」（经 robotctl）用的，本代不打开任何 manifest 字段。gap：metadata 携带的布局契约（joint_names/default_joint_pos）本可抓 obs 重排，但本代不读 → 无 metadata 与有错 metadata 对机器人外观相同。
- **权重是否烤进图（致命风险排除）**：项目记忆反复标记「`publish` 不打包外部权重 → split 导出 3KB 空图上机器人」。用 `verify_policy_bundle.py` 跑三个真实 kp8 onnx：A8 `weights in the file — 10 initializers, all embedded` **全 PASS** —— 导出即单文件，根本不走 publish，无 split 坑。26 项检查：walk/standup 0 fail 0 warn；groundpick 0 fail 1 warn（B4 自描述瑕疵：`observation_names` 列 head/body_command 而 `command_names` 只写 twist，robotd 不读 metadata 故 0 影响）。
- **rehearsal 假阴性修复**：rehearsal 从没真实跑过（Pass6/7 只修守卫崩溃）。真实跑暴露：groundpick/standup 因 rehearsal 默认喂 `Vel cmd 0.4 m/s` 而它们不响应行走命令 → `moves_forward` 门 FAIL → `all_gates_pass=False` 假阴性（tilt 仅 4.3°/3.2°、fell=n，电机侧健康）。修：`rehearse_hd1910.py` 从 companion runmeta 读 `task` 字段（`Mjlab-GroundPick`/`Mjlab-StandUp` 非行走），non-walking 自动注入 `--cmd-vx 0`，利用 `rehearse_deploy.py` 已有的 `cmd_vx<0.2 → moves_forward not_applicable` 机制消除误导。另修 `_inject_defaults` 守卫在 `_STATE["key"] is None` 时的 KeyError 防御。
- **测试**：新增 `test_rehearse_injects_cmd_vx_zero_for_nonwalk` + `test_rehearse_keeps_default_for_walk`（喂真实 groundpick/walk onnx，不喂合成名），全套 **35 passed**（33→35）。三个技能 rehearsal 现全 `all_gates_pass=True`。
- **结论**：kp8 软件栈三维度（conductor 四关 + bundle 26 项 + rehearsal 离线推演）一致确认可部署；发布链「走 publish 会丢权重」的恐惧已实证排除（只走单文件 onnx + conductor/bundle 校验 + 手动拷 toml/onnx）。真正剩余风险只剩硬件端到端（到货后 `bus.joint_ids` 逐关节复核 + 齿隙 7.4V 重测）。

---

## 4.2 Pass12 自主审计（2026-11-08）— 复现性盲区收口

- **不信任归档、实跑验证当前磁盘**：① `sha256sum` 三 kp8 onnx + `robotd_hd1910_mode0.toml` 与 `hd1910_kp8_deploy_bundle.json` 记录**逐字节一致**（无 bitrot）；② `audit_robotd_toml.py`（`--expect-kp 16`，仅 stdlib 可实跑）对当前 toml 退出 0、all pass：三策略路径均在盘、reg50=16 增益标度匹配、`imu_median=false` 等与训练侧一致，唯一 WARN 是 HD-1910 机体非 XL330 参考集（预期、非失败）；③ toml 的 `joint_ids`/`joint_signs` 与权威 `.upstream/hd1910m/radxa/installation.json` 逐条比对**完全一致**，关掉「照抄别的项目 installation.json ⇒ 15 颗全错位」风险（源 `calibration_verified=false` 仍须真机逐关节复核）。
- **新盲区（核心）**：`verify_policy_bundle.py`/`rehearse_hd1910.py` 需 `onnx`+`numpy`，但仓库唯一依赖清单 `microduck-software/repo/pyproject.toml` 是**训练环境**（microduck-mjbatch: mujoco/torch/mjbatch）且**不含 onnx**。`git clone`+`uv sync` 后无法再跑 bundle/rehearsal 闸门 → 部署「可复现」结论漏了工具链依赖。conductor `pre_deploy_check.py` 与 `audit_robotd_toml.py` 仅 stdlib 不受影响。
- **修**：新增 `microduck-software/tools/hd1910/requirements.txt` 显式声明 onnx/numpy（含安装命令 + 「本沙箱因网络受限无法 pip 安装 onnx，故声明但未在本环境验证」的诚实注记）。
- **两处口径修正**：① bundle 的 `bundle_audit.tool` 把「22 negative-control self-tests」改为准确「39 断言 = 11 contract + 1 clean + 27 负对照（跨 22 个 N1-N22 缺陷场景）」；② toml 第 105 行「HD-1910 / Radxa line」措辞澄清——本 toml 走 **DuckBuddy-main 那代 robotd**（Orange Pi A733 + HL-2915 + feetech_hls + 500 kbps，会做 EEPROM 开机硬校验 reg6/reg33/reg9/reg11），`radxa` 只是上游目录名（HD-1910 机体接线图恰好放那里），非 FT-SCS 那代；两线混淆 = 电机乱躜、判错无效。
- **沙箱限制**：本环境 Python 3.13 + pip 镜像返回 onnx「from versions: none」（网络/代理受限），无法实跑 onnx 闸门自证；以 sha256 + toml 闸门实跑 + installation.json 对照替代证明，onnx 闸门结论沿用归档（d3a94f3/d9d6b19 时实跑 PASS）。
- **结论**：Pass9 部署闸门在「格式/策略接线」层面成立，但「可复现」层面漏了工具链依赖，Pass12 补齐。剩余 OPEN 仍是硬件端到端（`bus.joint_ids` 逐关节复核 + 齿隙 7.4V 重测，台架 4.6V 欠压）与 P3/P4（暂缓/可选）。

---

## 4.3 Pass13 自主审计（2026-11-08）— 对照开源项目：执行 + 可追溯 + CI 门禁

- **对照对象（一手查证的资料）**：
  - upstream `pollen-robotics/microduck_rl` @ `develop`：根目录有 `scripts/export.py`/`infer_policy.py`/`find_onnx_source.py`/`testbench_sim2real.py`/`validate_bam_testbench.py`、`docs/training_checkpoints.md`、`scripts/hf`（策略传 HF）；`pyproject.toml` 显式声明 `onnxruntime>=1.24.4`、override `onnx>=1.20.1`。**关键**：上游把「部署 onnx → 训练来源」当一等公民（`find_onnx_source.py` bit-exact 权重匹配回溯 checkpoint），且 **`infer_policy.py` 真的用 onnxruntime 跑策略**（BAM 执行器模型，并用 `tests/test_infer_policy_bam.py` 把执行器常量「锁死」）。
  - `reflex-vla`（开源 VLA 部署层）：`reflex validate export` 做 ONNX↔PyTorch 机器精度 parity（退出码 0/1/2 供 CI），还能 `reflex validate --init-ci` 自动脚手架 `.github/workflows/reflex-validate.yml`。
  - `ETARS`（LeRobot 扩展）：`tests/test_compare_policies.py` 跨后端（onnxruntime vs torch）数值一致性比对。
  - `lerobot_humanoid_runtime`：**Calibration mandatory before deployment**；`deploy/run_real_policy_sequential.py` 分阶段安全运行器（state_only→检查→control→enable motors→zero pose→gains→policy）。
- **我们 vs 对照，确认的两个真缺口**：
  1. **provenance 缺失**：bundle 只记 sha256，无训练 commit/seed/env/配置哈希。上游用 wandb；我们本地每个训练 run 已写伴随 `runmeta_*.json`/`heading_meta_*.json`，含 `cfg_sha256_16`/`mdp_sha256_16`（环境/MDO 配置哈希）、`created`、`passthrough_args`（完整 CLI）、`task`、`seed`、`envs`、`iters`、`plant.source_file`。
  2. **只做静态检查，从不执行图**：`verify_policy_bundle.py` 查 IO 宽度 + 权重嵌入，但从不跑 onnx。导出时图层错/常量/爆炸的动作会漏过所有静态闸门。
- **修（新增/改动文件）**：
  - `tools/hd1910/record_provenance.py`（新增）：从伴随 meta + 复用 `_provenance.capture_provenance` 提取 provenance，注入 bundle 的 `provenance.code`（git commit/branch/dirty/diff_patch_id/toplevel）+ `provenance.per_artifact`（每个 onnx 的 task/plant/envs/iters/seed/cfg+mdp sha/created/export_iter/companion_meta）。纯 stdlib，**不依赖 onnx**。
  - `tools/hd1910/verify_policy_inference.py`（新增）：onnxruntime 真执行 onnx，断言输出 finite / 非爆炸（|a|<1e3）/ 非退化常量（WARN）。`check_inference_output` 纯 Python（不依赖 numpy），负对照 selftest 在干净环境可证；依赖缺失 rc=2 SKIP。
  - `tools/hd1910/pre_deploy_check.py`：挂 inference 成第五关（加 `INFERENCE` 常量、docstring、selftest 列表、main 流程）。
  - `tools/hd1910/requirements.txt`：补 `onnxruntime>=1.24.4`，对齐上游 onnx 版本，注明 inference 用。
  - `.github/workflows/deploy-gate.yml`（新增）：push/PR 跑 conductor selftest + inference selftest + 真实闸门（装好 requirements 后 inference 真跑）。
  - `tests/test_hd1910_tooling.py`（+5）：provenance 提取（真实 walk onnx + 无 meta 诚实标 absent + strip/parse）+ 推理负对照（NaN/Inf/explode 必抓、constant=WARN、empty=FAIL）+ inference selftest runs。
  - `out/hd1910_kp8_deploy_bundle.json`：新增 `provenance` 块。
- **沙箱限制（诚实）**：本环境装不上 onnx/onnxruntime/numpy（pip 镜像「from versions: none」），故 inference 真执行 onnx 与 bundle/numeric 两关 selftest 未在沙箱实跑；CI 装好依赖后跑。inference.selftest + toml.selftest 在 numpy-less 环境 PASS（前者纯 Python 负对照可证）。此限制 Pass12 已记、Pass13 未引入新回归。

---

## 4.4 Pass14 自主审计（2026-11-08）— 审查 CI 门禁与推理工具本身

- **触发**：Pass13 刚把「执行 + 可追溯 + CI 门禁」补上；本轮按「继续循环」指令，**不信任新门禁本身**，审查最新制品找「门禁是摆设」的盲区。
- **两个真盲区（都靠精读代码 + 与既有契约对照才暴露）**：
  1. **推理工具只「优先」不「强制」robotd 契约**：`verify_policy_inference.py` 原实现 (a) 输入名 `obs` 只在「存在才用」，否则用第一个输入名——但 robotd 硬编码 `{"obs": ...}` 且不读 manifest，输入名非 `obs` 必然加载失败；(b) `--expect-act` 不匹配分支是空 `pass`，即 28-vs-14 类元数据错乱可过关。两者都会让「所有静态/执行闸门绿」的 onnx 上机加载必炸。佐证：我们的 `eval_ground_pick.py`/`eval_standup.py` 都 `sess.run(None, {"obs": x})`；`verify_official_loader.py` 的 `BContract(input_name="obs", action_len=14)` 契约（行 171/459/511）。→ 改为 **FAIL**：`validate_inputs` 要求输入名集合含 `obs`；`validate_outputs` 在 `expect_act` 给定时要求 `len==expect_act`；空输出防 `IndexError`。
  2. **CI 步骤空指令**：`record_provenance.py --print` 缺必填 `--onnx`（原 `required=True`），被 `continue-on-error: true` 掩盖成坏步骤。
- **修（新增/改动文件）**：
  - `tools/hd1910/verify_policy_inference.py`：抽 `validate_inputs(names)` / `validate_outputs(values, expect_act=None)` 纯 Python（不依赖 numpy）；`run_session` 强制输入名 `obs` + 输出宽度；`check_inference_output` 保留为别名；`_selftest` 加宽度不匹配 / 输入名缺失两类负对照；docstring 写明 robotd 契约强制。
  - `tools/hd1910/record_provenance.py`：`--onnx` 改 `default=None`（可选）；新增 `--verify`：用 bundle 记录的 onnx 相对路径重算 `per_artifact`（task/plant_name/cfg_sha256_16/mdp_sha256_16/export_iteration）与存储块比对，漂移则 rc=1；code git_commit 仅 WARN（提交会变）。`--print` 在无 `--onnx` 时改读 bundle 已存块。
  - `tools/hd1910/pre_deploy_check.py`：docstring 更新 inference 阶段说明（输入名 obs + 输出宽度）。
  - `.github/workflows/deploy-gate.yml`：provenance 步骤改 `--bundle out/hd1910_kp8_deploy_bundle.json --print`；新增 `--verify` 步骤（漂移会失败构建）。
  - `tests/test_hd1910_tooling.py`（+4）：`validate_outputs` 宽度不匹配 FAIL / 正确宽度 PASS / 嵌套 batch 形式；`validate_inputs` obs 契约；`record_provenance_verify_consistent`（真实 bundle rc=0）；`record_provenance_verify_detects_drift`（字段篡改 rc=1 + 缺失 onnx rc=1）。
- **沙箱可证（本环境仍装不上 onnx/onnxruntime/numpy）**：`verify_policy_inference.py --selftest` 全绿（含 2 个新负对照）；`record_provenance.py --verify` 对真实 bundle 一致（rc=0，git_commit WARN 为预期）；`--print` 不再需 `--onnx`；四个工具 `--help` 全部合法；conductor 内 `inference.selftest=PASS`、`toml.selftest=PASS`（bundle/numeric/contract 因 numpy 缺失的 FAIL/SKIP 是 Pass12 已知限制，CI 装好依赖后过）；py_compile 全部改动文件通过。新增 4 项测试以 pytest 桩手动 harness 全 PASS，无回归。

---

## 4.5 Pass15 自主审计（2026-11-08）— 审计 contract 闸门（第一道、最结构化）

- **触发**：Pass14 审查了 Pass13 新加的推理/CI 门禁；本轮按「继续循环」把整个循环里**从没打开过**的第一道闸门 `verify_policy_contract.py` 也审一遍（同样的「只建议不强制」盲区可能重演）。
- **结论：contract 本身质量很高，不是「只建议」**：
  - `Robotd` 类直接解析 robotd 源码（`obs.rs` 的 `OBS_LEN` / `//! index width contents` 布局表 / `DEFAULT_POSITION` / `JOINT_NAMES` / `MOUTH_INDEX`）；`Training` 类从 `mjlab_microduck` 环境 cfg 实读 obs 项宽度、动作序、HOME、action_scale、ctrl_dt。
  - `check_obs_width` / `check_block_order` / `check_joint_order` / `check_home_pose` 都是 `==` / `max|diff|>tol` **直接 FAIL**；未知 obs 项 `raise NotChecked` 而非瞎猜（注释明写「a guessed width can still sum to 61 and hide a shifted block」）。
  - `selftest` 有 10+ 个真负对照：两关节交换、HOME+1°、宽度 60（含 onnx 60）、块 0↔1 交换、action_scale 0.5、head↔body 交换、速率 100Hz、省略键陷阱（官方/分支都按模式解析 walk action_scale=0.9，省略键曾当 1.0 通过，现必须红；显式 1.0 才能回绿）。
- **但暴露结构性盲区**：`Training` 侧 `import mjlab_microduck`（torch+mujoco+训练 env）；`tools/hd1910/requirements.txt` 只含 onnx/onnxruntime/numpy，**不含训练栈** → `contract.selftest` 在 CI 里 `NotChecked→rc=2→SKIP`。即**最结构化的 obs 布局/关节顺序/HOME/动作映射检查在 CI 里没跑**；且 conductor 原 verdict 只写「see SKIPs」，绿 CI 会被误读成「全验证过」。注意：obs/act **宽度**（61/14）其实被 bundle（静态）+ inference（执行）覆盖（不需训练栈）；但**关节顺序**（`policy_joints` vs `actuators`）只在 contract 查，CI 跳过。
- **修（有限、可 CI 跑）**：
  - `tools/hd1910/pre_deploy_check.py`：抽 `_verdict(any_fail, skipped)`；有结构性闸门 SKIP 时 verdict 显式 **PASS\*** 并列出 skip 关名，JSON 报告加 `skipped_stages`。不再含糊。
  - `.github/workflows/deploy-gate.yml`：在真实闸门步骤前注释明示 contract 在 CI 跳过、发货前需本地带训练栈跑。
  - `tests/test_hd1910_tooling.py`（+1）：`test_conductor_verdict_surfaces_skips` 锁死 PASS\* 分支（无 skip→PASS / fail→FAIL / 有 skip→PASS\* 且含关名）。
- **沙箱可证（本环境无 mjlab_microduck/onnxruntime/numpy）**：`_verdict` 三分支单测 PASS；`test_conductor_verdict_surfaces_skips` + `test_conductor_classify` 手动 harness 全 PASS；py_compile 改动文件通过。**contract 真执行需训练栈，沙箱无法实跑其 selftest，未引入新回归。**
- **结论**：conductor 五关现已全部被审计过「是否真强制」。contract 逻辑正确，唯一缺口是它依赖训练栈、CI 跳过——已用 PASS\* 让该缺口可见而非静默。要让 contract 在 CI 真跑，需给 CI 装训练栈（重、且本沙箱无法验证安装），故本次选择「显式可见 + 本地发货前必跑」，不盲改 CI 装重依赖。

---

## 5. 证据索引（本轮查证）

- 官方站起修复：`pollen-robotics/microduck_rl@develop` → `src/mjlab_microduck/tasks/microduck_standup_env_cfg.py`（`set_ground_state`、`ground_state_mix`、`face_up_roll_max`）。
- HD-1910 已含修复：`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/tasks/microduck_standup_env_cfg.py` grep 命中 `ground_state_mix` / `face_up_prob` 0.00→0.35 / `face_up_roll_max=math.radians(90)`。
- 官方 tests 范式：`.upstream/microduck_rl-develop/tests/test_velstand_cfg.py`（CPU，build cfg + compile spec，锁 servo geom / joint 名 / 奖励符号）。
- 本仓库新 tests：`microduck-software/tests/test_hd1910_configs.py`（9 passed @ live hd1910_kp8）；`microduck-software/tests/test_hd1910_tooling.py`（5 passed @ CPU，覆盖 conductor/rehearsal/provenance 三个新工具）。
- 关节映射规范（14 驱动关节，free joint 除外）：live kp8 模型实测顺序已硬编码进测试。
- HD-1910 真实 bus ID 来源：`.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`，15 关节 ID 与方向）；JOINT_NAMES 顺序见 `duck-ipc-proto/src/lib.rs:368`；XL330 参考 map 见 `duck-control/src/model.rs:15`（仅参考，不适用于本机体）；`bus.joint_ids` 必填/拒绝开总线见 `robotd/src/main.rs:5495` + `audit_robotd_toml.py`。
