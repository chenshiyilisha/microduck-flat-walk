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
- **Pass16（2026-11-08 · 十轮循环 · 深度挖掘/对照/完善/再挖掘）—— 用完整栈真跑，戳破贯穿 Pass12–15 的错误前提「沙箱装不上 onnx/numpy/pytest」**：本轮改用 `microduck-software/.venv-mjlab/Scripts/python.exe`（此前各轮用系统 Python 3.13），实测 **torch 2.9.1+cu128 / CUDA RTX 4070 / onnx 1.23.2 / onnxruntime 1.31.0 / numpy / mjlab / mjlab_microduck / mujoco / warp / pytest 9.1.1 全部齐备**——所谓「网络受限装不上」是**找错解释器**，不是环境缺依赖（同型于记忆里「格式读不懂≠读不了」）。真跑立刻暴露两个静默漏检：**① conductor 第五关 inference 从未真正执行过**：`pre_deploy_check.py` 把 onnx 路径当**位置参数**传给 `verify_policy_inference.py`，而后者只接受 `--onnx` ⇒ argparse 用法错误退出码 **2**，被 `_classify(rc==2)` 无条件吞成「依赖缺失 SKIP」；CI 自己装了 onnxruntime 却写着「SKIP 也算 meaningful verdict」且 `set -e` 不会拦 SKIP ⇒ **Pass13–15 三轮全绿而该关一直是摆设**。修：传参改 `--onnx`；`_run` 回传完整输出，新增 `_is_argparse_usage_error` + `_stage` 护栏，使 rc=2 的用法错误判 **FAIL** 而非 SKIP（对五关通用）。真实产物验证：三个 kp8 onnx 五关全部 `PASS -- safe to load (all stages verified)`（此前 `PASS*`），inference 真执行图 `input_name=obs shape=[1,61] out_len=1`。**② CI 结构性放水**：新增 `assert_ci_verdict.py` 断言 inference 必须 PASS、只允许 contract SKIP、篡改/额外 SKIP 必 FAIL，接入 deploy-gate.yml；配 5 条负对照 selftest + 真实报告篡改测试。**③ A1 对照出机读边界缺失**：hd1910m 的 `release_validation.json` 用 `hardware_tested_this_release:False` + `gait_qualified:false` + `limits[]` 明确「没验证什么」，本项目 bundle.json 一个 `false` 都没有（全在注释/日志里）⇒ 新增 `verification_boundary` 块（硬件未测/标定未验证/运动禁止/5 条 limits），并在 `record_provenance.py --verify` 加与权威 `installation.json` 交叉核对，任何「悄悄改绿」或删块都变红。**A2 对照结论**：loco-diag 的三条诊断中，`error_vel_xy` 口径本项目**早已独立修得更彻底**（`eval_tracking.py` 明写 official 指标不作判据、`sweep_ckpt.py` 用 `freeze_command` 钉窗口、`summarize_heading_ab.py` 有 `is_true_mean` 硬守卫）；air_time 门控/侧向加权两条是**第三方独立印证的同族问题**，本项目配方已用 standing_envs curriculum + foot_clearance/swing_height + 更严 std 处理，静态对照无新缺口，不需改训练。**再挖掘**：Pass10/11 固化进 bundle 的 `rehearsal.walk=true` 首次用真实产物实跑复现（`all_gates_pass=True`）。全套测试 **52 passed**（此前各轮「手动 harness / 归档沿用」的结论首次真实 pytest 全跑）。**结论**：本轮把「绿」从「看起来合理」拉回「真执行过」；剩余 OPEN 仍是硬件端到端 + P3/P4。
- **Pass17（2026-11-08 · 十一轮循环 · 深度挖掘/对照/完善/再挖掘）—— 用 `git archive` 干净 checkout 反查 CI，戳破「Pass13–16 四轮改的 CI 从没在 CI 真正拿到的文件集上跑过」**：**深挖 A3**：读全 `.upstream/666wsp-microduck-hd1910/imu_dev_guide.md`（LSM6DSV16X SFLP、**120 Hz**、姿态延迟最坏 **8.3 ms**、ID 200、1 Mbps、`STALE`>30ms / `READER_SLOW`≥5 样本、建议读取 ≥50 Hz）+ `avanx-imu/README.md`（同款芯片、`imu_to_dxl` 挂总线冒充 ID 200、**直接引用本项目 `imu.rs` 的 `DEFAULT_MOUNT`**）+ `imu-displace/IMU-MODULE.md`（独立实现，实测 100 Hz / 0.92 ms 总线 /「50 Hz 周期不被拖慢」验收项）。用完整栈真跑 `verify_imu_chain.py`：**训练 cfg 的 IMU 延迟窗口确为 `0–1 steps = 0–20 ms`**（从 `make_microduck_velocity_env_cfg()` 实读，非记忆推断）、median ON = +20 ms / OFF = 0、13 项全 PASS、15 条负对照一致。🔑 **两处易混差异**：手册飞特紧凑块是 **15 B（含 sequence/status）**，本项目 `imu.rs` 的 `IMU_BLOCK_LEN=12` 对应手册 **Dynamixel 兼容块 addr124/12B** ⇒ `STALE`/`READER_SLOW` 位在本部署链**根本不可见**，`ready()`(25 样本=50 Hz 下 500 ms) + 全零哨兵是 robotd 自有替代；120 Hz 是芯片 SFLP 输出率、与 50 Hz 同步读不矛盾（手册明写建议 ≥50 Hz）。量化边界：median OFF ≈ 0–8.3 ms 落在训练窗口内；median ON = 20 + [0,8.3] = **20–28.3 ms**，超出窗口上界 20 ms（toml 注释「20–30 ms」是保守近似）。`audit_robotd_toml.py` R14 只判 WARN 与 checklist B20「台架见尖峰才改回 true 并记录」的人工豁免一致 ⇒ **负对照否掉「改 FAIL」的冲动，记录边界、不改代码**。
- **🔴 最大发现（干净 checkout 实测）**：`git archive HEAD` 解出 CI 真正拿到的文件集后实测：`.upstream/` **ABSENT**、三个部署 onnx **count 0**（`*.onnx` + `logs/` 双重 ignore）、`record_provenance.py --verify` **rc=1**（三条 `DRIFT onnx missing on disk` + calibration source missing）、`pre_deploy_check.py --selftest` **rc=1**、`pytest tests/` **25 failed / 18 passed / 9 skipped**；用不存在的 onnx 直跑 conductor 得四关 FAIL + 难懂的 onnxruntime `NO_SUCHFILE` traceback。⇒ **Pass13/14/15/16 四轮都在编辑 deploy-gate.yml、都跑过 selftest、都称 CI 绿，却从没验证过「真闸门」引用的产物根本不在仓库里**——四轮验证的都是「本地完整工作区自洽」。这是 Pass16「inference 关是摆设」的同族、但更底层：不是某一关摆设，而是**整个 CI 的输入前提不成立**。
- **🔴 第二发现（单一可信源自述失守）**：新探针主跑报 `robotd_toml: SHA-DIFF`——bundle 记录 **9007 B / `b71a5907`**，磁盘实际 **9520 B / `f6ebad3c`**。Pass12 改了 toml 的「Radxa line」措辞注释，bundle 里的指纹从未刷新；而 `verify_bundle()` 只 diff `provenance.per_artifact` 与 `verification_boundary`，**从不校验 `artifacts[]` 的 sha256/bytes**，故 Pass13–16 四轮 `--verify` 全绿。**「记录 hash 但不检查 hash」＝ 装饰**。
- **修（零争议、全部真跑）**：① 新增 `tools/hd1910/assert_clean_checkout.py`——机读 CI 输入就绪度探针，逐项检查存在 / **git 是否跟踪** / sha256 / bytes / `.upstream` 关键源 / 训练栈，输出 `ci_full_gate_possible` 与 problems；8 条负对照 selftest（含「文件在盘但 gitignored」这一 Pass13–16 精确陷阱）、`--strict`（缺失 rc=1）、`--github-output`，接进 CI 第一步（非阻断但打 `::warning::` + `REAL GATE NOT RUN`）。② `record_provenance.py` 新增 `verify_artifact_hashes()` 并接进 `--verify`：**先跑负对照确认守卫真的变红**，再刷新 bundle 的 toml 指纹。③ `requirements.txt` 删掉 Pass12/13「onnx 装不上、缺依赖当 SKIP 可接受」的**已被 Pass16 推翻**的注释，改写为「找错解释器 + inference SKIP 在 CI 是 BROKEN GATE」，并补 `pytest>=8`。④ 把 `verify_imu_chain.py`（13 项检查 / 15 负对照、覆盖策略最前 6 个观测数）接进 `pytest tests/`——此前它**只被 README/checklist 提及，从未被 conductor / CI / pytest 调用**，`imu_median=false` 这个部署决策却建立在它上面。⑤ deploy-gate.yml 顶部写明 PASS17 验证边界，加探针步骤；**不擅自改版本控制策略**（入库 2.3 MB onnx + 精简 `.upstream` fixture 属资产/架构决策，留待用户定）。
- **循环自身又抓到 3 个我写的 bug**：`assess()` 里 `sha_match=False` 但 `bytes_match=True`（同长度篡改，最常见 bitrot）两个分支都不进；`artifacts=[]` 时零 problems 被判 `runnable=True`；以及一处把 `assert_ci_verdict` 的 selftest 措辞复制粘贴进探针 CLI 测试。全部由负对照/CLI 层测试当场变红后修正。
- **实测收口**：`pytest tests/` **57 passed**、`conductor --selftest` PASS、三个 kp8 onnx 五关全 **PASS**（rc=0）、`provenance --verify` **rc=0** 且新增 `OK artifacts sha256/bytes match for 4 file(s)`、探针 `--selftest` PASS / `--strict` rc=1。**结论**：本轮把「CI 绿」从「看起来门禁齐全」拉回「明确知道这个 checkout 到底能验证什么」；剩余 OPEN 仍是硬件端到端 + P3/P4，并新增一条**待决策**：是否让 CI 真闸门在干净 checkout 上可执行。
- **Pass18（2026-11-08 · 十二轮循环 · 用户裁定「按最优的来」· 深度挖掘/对照/完善/再挖掘）—— 把上轮那条待决策判成「入库并打通 CI 真闸门」，而不是降级成永久显式边界**：深挖用 `git archive` 干净副本 + 逐项补齐实测出 CI 真正需要的输入闭包 = **3 个部署 onnx（2,381,098 B）+ 9 个 upstream 只读契约源（450,193 B）+ runmeta/heading_meta 伴随元数据**，合计约 2.84 MiB。🔴 **纠正 Pass17 探针自己的盲区**：`UPSTREAM_SOURCES` 只列 5 个，判据是 `verify_policy_bundle.load_contract()` 在干净副本里报 8 条 problems、退化成 `obs_len=0/action_len=0/joint_names=0`；补齐 `duck-control/src/policy.rs`、`duck-ipc-proto/src/lib.rs`、`duck-control/src/feetech.rs`、`microduck_rl-develop/src/mjlab_microduck/publish/manifest.py` 后才恢复 `61/14/15/15/'obs'、0 problems`。🔴 **纠正「干净副本 pytest 21 个 configs 失败＝资产缺失」的错误前提**：真因是 `tests/test_hd1910_configs.py` 经 `plant_spec.LIVE_CONSTANTS` 把 `.venv-mjlab/Lib/site-packages` 拼在 cwd 下，干净副本没有该目录 ⇒ `FileNotFoundError`；本地完整工作区单独跑同一条 **PASS**。改为 `importlib.util.find_spec("mjlab_microduck")` 动态定位已安装包源码，lean 环境才做诚实 skip。**对照发现项目早有证据入库惯例**：`microduck-software/out/` 已入库 283 个文件、全仓已有 2 个 force-add 的 `.onnx`（`artifacts/flat_walk/`）、`.gitignore` 已给 `!out/heading_meta_*.json` 开例外（23 个在库），唯独 `runmeta_*.json` 无例外（0 个在库）⇒ 干净副本缺 32 个伴随 meta，造成 `provenance --verify` 两条 `task stored=... recomputed=None` DRIFT 与 4 个 tooling 失败。 ⇒ 入库不是新策略，只是补齐漏掉的**主体**；降级方案会把 Pass13–16「真闸门从不在 CI 执行」永久固化。**落地**：两层 `.gitignore` 标注 force-add 证据 + 补 `!out/runmeta_*.json`；`git add -f` 12 个文件、add 34 个 runmeta；`assert_clean_checkout.py` 改成**双 verdict**（`ci_scope_gate_possible` = CI 四关 / `ci_full_gate_possible` = 五关含训练栈），`--strict` 只管已提交输入、`--strict-full` 额外管训练栈，selftest 补 4 条分层/闭包负对照；`pre_deploy_check.py` 加**默认空白名单**的 `--selftest-allow-skip`（白名单内 SKIP 打印 PARTIAL 而非 PASS，未知名字 rc=2，FAIL 仍红）；`deploy-gate.yml` 首次跑 `pytest tests/ -q -rs`、`--strict` 探针、三策略真闸门，并显式打印 `CONTRACT STAGE NOT VERIFIED IN CI`。**验证不靠推断**：pip 镜像装不上 lean venv（`onnx>=1.20.1 from versions: none`），改用 `sitecustomize.py` 精确屏蔽 `mjlab_microduck/torch/mujoco/warp/scipy`（同时让 `import` 抛错、`find_spec` 返回 None），复用本机 onnx/numpy/onnxruntime/pytest 真跑整套 CI 命令。**读数**：本地完整栈 `pytest tests/` **62 passed**；lean CI 模拟：探针 `--strict` rc=0（scope=true / full=false）、selftest **PARTIAL rc=0** 而不带白名单 **rc=1**、`pytest` **36 passed / 26 skipped**（skip 理由逐条可见）、`provenance --verify` rc=0、三策略 `PASS*`（`contract=SKIP` + 其余四关真 PASS）、`assert_ci_verdict` rc=0。**负对照**：改坏入库 onnx 的 1 字节 ⇒ 4 关 FAIL + verdict FAIL + 断言 rc=1；临时移走 `policy.rs` ⇒ 探针 `--strict` rc=1 并点名该源，恢复后 rc=0。**循环自身又抓到 2 个错**：YAML step name 里 `strict: real` 的 `: ` 被 PyYAML 判 mapping 语法错；以及负对照 B 最初在 **Pass17 旧代码的干净副本**上做（那份探针清单本就不含 policy.rs，当然不红）⇒ 换到新代码重做才变红。**结论**：CI 首次在**它自己拿到的文件集**上真跑 4/5 关；唯一无法在 lean CI 复现的 `contract` 关（需 torch/mujoco/mjlab_microduck）保留显式 SKIP + 本地 `.venv-mjlab` 五关全 PASS 作为发货前权威验证。剩余 OPEN 不变：硬件端到端（到货后逐关节复核 + 7.4 V 齿隙重测）、P3 暂缓、P4 可选。
- **🔴 Pass19（2026-11-08 · 十三轮循环 · 深度挖掘/对照/按最优完善/再挖掘）—— 戳破比 Pass17 更根本的一层：workflow 从来没被 GitHub 发现过**：`git rev-parse --show-toplevel` 证实仓库根是 `E:/WorkBuddyData/.../`，而 `deploy-gate.yml` 一直在**子目录** `microduck-software/.github/workflows/`；根目录**根本没有 `.github/`**。上网核官方文档（GitHub quickstart 原文「For GitHub to discover any GitHub Actions workflows in your repository, you must save the workflow files in a directory called `.github/workflows`」；workflow syntax「You must store workflow files in the `.github/workflows` directory of your repository」），再用 GitHub 官方 API 拿三条独立实证：`GET /repos/.../actions/workflows` → **`total_count = 0`**（已发现的 workflow 数为零）、`GET /contents/.github/workflows` → **404**、仓库根目录列表无 `.github`；`git ls-remote` + `git rev-list` 显示远端 HEAD `228933d0`、落后 **33 个提交**、`pushed_at 2026-11-07` ⇒ Pass13–18 全部只在本地提交。**即：Pass17 修的是「CI 拿到文件后能验证什么」，Pass18 修的是「输入是否在 VCS」，但 CI 本身从未被 GitHub 注册、更没跑过一次。** 判「最优」= **`git mv` 到仓库根 `.github/workflows/` + 真正推送 + 本地机读防复发**，否决「保留子目录只加说明」与「把 contract 关冻结成训练侧快照」（后者会让两个独立实时来源退化成与静态证据比对，正是 Pass17 `artifacts` hash 四轮 bitrot 的同族）。**官方 RUNTIME 对照结论**：`desk-climb/RUNTIME.md` + `runtime/policy_pair.py` + `evidence/cpu-export-parity.json` 三件套，本项目已有**等价且更强**的 `tools/check_onnx_parity.py`（独立 numpy 重建 + `--control` 强制「去掉归一化必须发散」负对照）与 4 份 parity JSON ⇒ 不新增；官方把 joint order/HOME 嵌 ONNX metadata 的路线在本代 robotd 上不适用（不读 manifest）。**落地**：`assert_clean_checkout.py` 新增 `probe_workflow()` / `workflow_problems()`（根 workflow 存在 + 文本含 `on:/jobs:/working-directory:` + 子目录孤儿扫描，纯 stdlib 不引入 PyYAML），problems 并入 `scope_problems` 使 `--strict` 变红、报告加 `workflow` 段、`GITHUB_OUTPUT` 加 `workflow_discoverable`；`tests/test_hd1910_tooling.py` +3 条（根位置/孤儿断言、纯函数 4 负对照、**真实 CLI 正+负对照**）。**诚实边界**：CI 若位置错就根本不跑，故这必须是**本地**门禁，不能自称「CI 自守」。**读数**：本地完整栈 `pytest` **65 passed**、lean CI 模拟 **39 passed / 26 skipped**、探针 selftest 15 条全 PASS、`--strict` rc=0；**文件系统级负对照**：移走根 workflow ⇒ `--strict` rc=1 且点名 `NOT DISCOVERABLE` + 位置测试红；造子目录孤儿 ⇒ rc=1 点名 `ORPHAN WORKFLOW` + 位置测试红；恢复 ⇒ rc=0。**推送后复检（§4.9.4）**：workflow 确已被 GitHub 发现（`total_count` 0→1）并触发史上首个 run，但该 run **failure** —— `core.autocrlf=true` 让 bundle 记了 CRLF 工作树字节（9520 B），而 Linux CI checkout 拿到 LF blob（9382 B）⇒ `robotd_toml SHA-DIFF`、后 9 步全 skipped；已用 `.gitattributes` 钉 LF + 指纹锚定 VCS blob + 2 条跨平台不变式测试修复。**这是「本地全绿」第四层前提错误：文件集对了、位置对了，字节却因平台换行而不同。** 第二次真实 run 又红（`bam` 顶层 import 拖垮 7 条纯逻辑测试 + 本地 lean 模拟器欠屏蔽该依赖而假绿），改为惰性导入并把模拟器纳入版本控制。**第三次真实 run `42452793362` / `1ba236e` = success**：14/14 步全绿、`44 passed / 26 skipped`（26 skip 逐个核过全是训练栈依赖）、三策略 `PASS*`、探针 `scope_gate=true / full_gate=false / workflow_discoverable=true`、显式打印 `CONTRACT STAGE NOT VERIFIED IN CI`；本地完整栈在最终 HEAD 补跑 **70 passed** + 三策略五关 `PASS`（contract 真 PASS，非 SKIP）⇒ 分层 verdict 如实、发货前 5/5 有权威兜底。**三次 run 里前两次的红都只有真实 GitHub runner 才暴露**（本地模拟两次假绿）⇒ 真实 CI 是最终验证。详见 §4.9.4。

- **Pass20（2026-11-08 · 十四轮循环 / R4 · 深度挖掘/对照/按最优完善/再挖掘）—— 上移到「仓库治理」层，抓到 CI 真闸门的第三份硬编码清单**：深挖 GitHub 官方 API 三条实数：`branches/main/protection` → **404 `Branch not protected`**、`rulesets` → **`[]`**、`pulls?state=all` → **0 个 PR** 且前 4 次 run 的 `event` 全为 `push`；两次 failure 的提交 `dac3cf5a` / `86e6acd` 经 `git merge-base --is-ancestor` 实测**都是 main 的祖先** ⇒ 红 CI 从未阻止提交进入 main，CI 是 **post-push advisory、不是合并门禁**（实证非推断）。查官方一手语义后判**这是设计约束不是缺陷**：`about-protected-branches` 明写 required status checks 是 "before **merging**" 且 "By default ... **don't apply to people with admin permissions**"（本账号 `admin=true`）；`available-rules-for-rulesets` 把「Restrict updates（拦 push）」列为**独立**规则；`status-checks` 原文 "A job that is **skipped** will report its status as **'Success'. It will not prevent a pull request from merging, even if it is a required check**" ⇒ 加 protection 既拦不住直推、又被 admin 绕过、还引入新假绿通道，**「按最优」＝写清边界 + 强化本地门禁，不做装饰性远端配置**（未擅自改仓库设置）。🔴 **真静默漏检**：workflow 的 `Real deploy gate` 把三个 onnx 路径 + toml + `--expect-kp 16` **硬编码**成第三份清单；负对照把 groundpick 改成 `STALE_STALE.onnx` 后 `--strict rc=0`、pytest 11 passed、`provenance --verify rc=0` **三套守卫全绿**（同族 Pass17 hash bitrot / Pass9 接错策略）。**按最优消除第三份清单而非再加一份同步检查**：新增纯 stdlib `ci_gate_targets.py` 从 bundle 读目标并校验路径安全/文件存在/kp（13 条负对照，`--sh`/`--json`/`--selftest` 三 CLI），workflow 改为 `source` 其 `GATE_*` 变量；探针加 `gate_target_problems()` 文本守卫（+5 负对照共 20 条）使 `--strict` 与 pytest 在有人重新硬编码时变红；测试 +5 条（含文件系统级负对照与「两条独立算法算 `expect_kp == register_kp(200,16)`」守卫）。**修复后同样篡改 → `--strict rc=1` 且 pytest 变红**；把 bundle 的 kp 改 8 → emitter 输出 8 → toml 关 FAIL、conductor rc=1，证明值真驱动闸门而非换个地方硬编码。**读数**：本地完整栈 **75 passed** / lean 模拟 **49 passed 26 skipped** / 端到端新 gate 链三策略 `PASS*` + `gate really executed`；🔑 方法纠正：`git archive` 副本无 `.git` 会误报 5 条既有 git 依赖测试失败，改用**带 `.git` 的本地 clone** 复验得 `--strict rc=0`、49 passed 26 skipped（与真实 CI 一致）。✅ **第五次真实 run `42456241221` / `e8c1666` = success**：新增 emitter selftest 步骤真跑、三个 gate 路径从 `GATE_*` 解析、49 passed 26 skipped、治理边界打印生效。详见 §4.10。

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

## 4.6 Pass16 自主审计（2026-11-08）— 完整栈真跑，纠偏「沙箱装不上依赖」

- **触发**：用户「启动循环任务：深度挖掘、对照、完善、再挖掘」，并追加「不是长时间的，可以用 GPU」。本轮先深挖 `.upstream` 全景盘点里优先级最高的 A1（hd1910m 独立部署链）/ A2（loco-diag 训练诊断），再对照本项目实现，发现真缺口就修，修完回头复检 + 再挖掘。
- **🔴 前提纠偏（本轮最大收获）**：Pass12–15 反复声明「本沙箱装不上 onnx/onnxruntime/numpy/pytest（pip 镜像 from versions: none，网络受限），故重依赖闸门只能沿用归档」。**这是找错 Python 解释器**：此前都用系统 Python 3.13；项目自带 `microduck-software/.venv-mjlab/Scripts/python.exe`，实测一手读数：

  ```
  torch 2.9.1+cu128  cuda=True  NVIDIA GeForce RTX 4070 Laptop GPU
  numpy 2.5.4 / onnx 1.23.2 / onnxruntime 1.31.0
  mjlab / mjlab_microduck / mujoco 3.7.0 / warp 1.12.0 / pytest 9.1.1  全部 OK
  ```

  ⇒ 所有「未实跑」结论本可当轮就跑。同型于记忆里「格式读不懂≠读不了」：**「装不上」≠「没有」，先查有没有现成环境/解释器**。
- **真跑立刻暴露的静默漏检 ①（inference 关是摆设）**：`pre_deploy_check.py` 调用 `verify_policy_inference.py` 时把 onnx 路径作为**位置参数**，但该脚本只接受 `--onnx`（`add_argument("--onnx", type=Path)`）⇒ argparse `unrecognized arguments` 退出码 **2**；`_classify(rc==2)` 无条件判 **SKIP「依赖缺失」**。因为此前各轮都「装不上 onnxruntime」，这个 rc=2 看起来完全合理，被连续三轮放行；Pass15 还专门把 SKIP 显式化成 PASS\*，等于给假 SKIP 发了体面通行证。根因是**参数契约错**，不是环境问题。
  - **修（两层）**：(a) conductor 传参改 `--onnx str(args.onnx)`；(b) `_run` 回传完整输出，新增 `_is_argparse_usage_error(text)`（要求同时出现 `usage:` 与 argparse error 行，避免报告里出现 "usage" 就误判）+ `_stage` 护栏：`rc==2` 但为用法错误 → **FAIL**（对五关通用，将来任何参数写错都不会再被吞成 SKIP）。
  - **真实产物验证**：三个 kp8 onnx 全部从 `PASS*` 变 **`PASS -- safe to load (all stages verified)`**，inference 真执行图 `input_name=obs shape=[1,61] out_len=1`，`skipped_stages=[]`。五关 selftest 在完整栈上全 PASS（contract/bundle 各 39/39、numeric、inference、toml 均带真实负对照）。
- **静默漏检 ②（CI 结构性放水）**：deploy-gate.yml 自己 `pip install -r requirements.txt`（含 onnxruntime），注释却写「inference SKIPs 也算 meaningful verdict」，且 `set -e` 不会拦 SKIP ⇒ 修复前 CI 永远绿。**修**：新增 `tools/hd1910/assert_ci_verdict.py`，断言 `verdict∈{PASS,PASS*}`、**inference 必须 PASS**、只允许 `contract` SKIP（训练栈故意不装）、任何额外 SKIP / FAIL / 空 stages 必红；接入 CI 每一步 `--json` 之后。5 条负对照 selftest（含「Pass13-15 那个 inference SKIP」）+ 真实 conductor 报告篡改测试。
  - **循环自身抓到一个刚写进去的 bug**：`assert_ci_verdict.py` 初版把 `report` 写成必填位置参数，`--selftest` 直接 argparse 报错；而当时全套 50 测试全绿（只测了 `check()` 函数、没测 CLI 入口）。正是「绿被误读」的现场演示 ⇒ `report` 改 `nargs="?"` + 新增 `test_ci_verdict_cli_selftest_runs`。这也反向证明 (b) 的 `_is_argparse_usage_error` 护栏确实该有。
- **A1 对照出的机读边界缺失**：`hd1910m/docs/release_validation.json` 用 `hardware_tested_this_release: False`、`gait_qualified: false`、`hardware: false` + 5 条 `limits[]` 明确「没验证什么」；本项目 `out/hd1910_kp8_deploy_bundle.json` 里这些事实全散在 toml 注释/日志正文，**机读产物 0 个 false**。**修**：纯新增 `verification_boundary` 块（hardware_tested / calibration_verified / imu_pose_verified / mapping_confirmed / motion_permitted=false + 权威源路径 + 5 条 limits），并在 `record_provenance.py --verify` 加 `verify_boundary()` 与权威 `.upstream/hd1910m/radxa/installation.json` 交叉核对：篡改任一标志、宣称硬件已测但标定未验证、允许运动但标定未验证、删块、清空 limits **全部变红**（5 条负对照 + 真实 `--verify` 路径测试）。借鉴 hd1910m `configure.py` 的 `--allow-motion` 双真联锁语义，但不改 robotd（两线不同代，不可混用）。
- **A2 对照结论（不需改代码）**：`loco-diag`（官方 `microduck_rl` issue #46 社区诊断）三条：① `air_time` 只 gate on 指令不 gate on 实际前进；② 侧漂达前向 2×、两轴等权；③ `error_vel_xy` 混五类指令 + 整回合平均 ⇒ 高估约 3×。本项目 live 栈（`.venv-mjlab/.../tasks/`，与 `out/issue46_backup/` 逐字节同尺寸同 mtime）里 `feet_air_time_upright` 确实仍调上游模板、`command_threshold=0.01` ⇒ ① 形式仍在，但配方另有 `standing_envs` 课程（iter 2000 达 25% 站立 env）、`foot_clearance`/`foot_swing_height`（均 target 0.02）、`track_linear_velocity std=√0.1`（比 loco-diag 报的官方 0.5 更严）、`upright 2.0/std²=0.05`、`head_pose_bias` ⇒ **静态对照无新缺口，不需改训练/重训**。② 未发现显式侧向加权，但本项目评测口径独立。③ 本项目**早已发现且修得更彻底**：`tools/eval_tracking.py` 明写 official `error_vel_xy` 单位依赖 `resampling_time_range[1]`、**不作判据**（改用自带 RMSE + lag 搜索）；`sweep_ckpt.py` 用 `freeze_command` 钉窗口使 `metric_window.is_true_mean` 成立；`summarize_heading_ab.py` 有 `is_true_mean` 硬守卫「false 则不得跨 run 比较」。⇒ 第三方独立印证本项目自己的判断。loco-diag 自列「无多种子重复」局限也正好呼应 P3 铁律。
- **再挖掘（归档结论首次实跑复现）**：Pass10/11 固化进 bundle 的 `rehearsal.walk=true` 此前只是归档；本轮 `rehearse_hd1910.py --onnx <walk7999> --cmd-vx 0.3 --seconds 8` 真跑得 `all_gates_pass=True`，与归档一致。五关 selftest、全套 pytest（`tests/` 两个文件 **52 passed**）、三策略五关、provenance `--verify`、CI verdict 断言均首次在完整依赖栈上真实执行，不再「沿用归档」。
- **产物**：`tools/hd1910/pre_deploy_check.py`、`assert_ci_verdict.py`（新）、`record_provenance.py`、`tests/test_hd1910_tooling.py`、`out/hd1910_kp8_deploy_bundle.json`、`.github/workflows/deploy-gate.yml`。**结论**：本轮把「绿」从「看起来合理」拉回「真执行过」；剩余 OPEN 仍是硬件端到端（到货后逐关节复核 + 7.4V 齿隙重测）与 P3/P4（用户暂缓/可选）。

---

## 4.7 Pass17 自主审计（2026-11-08）— A3 深挖 + 干净 checkout 反查 CI

**切入点**：§7 建议里唯一还没做的「A3 用 8.3 ms / 120 Hz 核 `[bus] imu_median=false` 的延迟假设」，以及 §5 标注「未读正文」的 IMU / 观测一手源码。零 GPU、纯读源码 + 真跑。

### 4.7.1 A3 一手事实（全部标真源，不靠记忆）

| 事实 | 真源 |
|---|---|
| IMU_TO_DXL v1.2 = CH32V203 + **LSM6DSV16X**（SFLP 硬件融合）、从站 **ID 200**、**1 Mbps**、**120 Hz**、姿态延迟最坏 **8.3 ms** | `.upstream/666wsp-microduck-hd1910/imu_dev_guide.md:5-18` |
| 15 B 飞特紧凑块 addr 56（含 `sequence`@12 / `status`@13）；Dynamixel 兼容块 **addr 124 / 12 B** | 同文件 `:26-46` |
| `STALE` = 距上次新四元数 >30 ms；`READER_SLOW` = 累积 ≥5 个新样本；**建议读取频率 ≥ 50 Hz** | 同文件 `:99-110`、`:283-287` |
| 躯干 IMU 就是挂总线冒充 **ID 200** 的 `imu_to_dxl` 板、芯片同为 LSM6DSV16X；**直接引用本项目 `duck-control/src/imu.rs:78-83` 的 `DEFAULT_MOUNT`** | `.upstream/avanx-imu/README.md:2-5`、`:22`、`:66-79` |
| 另一条独立实现：100 Hz 实测 / 0.92 ms 总线 / 全零块 1–2% / `ready()` 25 帧 / 验收项「50 Hz 周期不被拖慢」 | `.upstream/imu-displace/IMU-MODULE.md:69-77`、`:128-149`、`:169-177` |

**本项目侧真跑**（`.venv-mjlab/Scripts/python.exe tools/hd1910/verify_imu_chain.py`）：13 项全 PASS，训练侧延迟窗口从 `make_microduck_velocity_env_cfg()` 实读为 **`0–1 steps = 0–20 ms`**（不是记忆推断），median ON = +1 tick (**20 ms**) / OFF = **0**，`ready()` 25 样本 = 50 Hz 下 **500 ms**；`--selftest` 15 条负对照全部一致。

**两处关键澄清**：① 手册的 15 B 块带 `status`/`sequence`，本项目 `imu.rs` 的 `IMU_BLOCK_LEN=12` 是手册的 **Dynamixel 兼容块** ⇒ `STALE`/`READER_SLOW` 三个状态位在本部署链**不可见**，`ready()` + 全零哨兵是 robotd 自己的替代，**不能把手册的状态位检查直接移植**。② 120 Hz 是芯片 SFLP 输出率，robotd 50 Hz 同步读拿「当时最新样本」，手册明写建议 ≥50 Hz、30 ms 才 STALE ⇒ **两者不矛盾**。量化：median OFF ≈ 0–8.3 ms（落在训练窗口低端）；median ON = 20 + [0, 8.3] = **20–28.3 ms**，超窗口上界 20 ms。`out/robotd_hd1910_mode0.toml:86-98` 注释写「20–30 ms」是保守近似，方向正确。

**负对照否掉一条疑似缺口**：`audit_robotd_toml.py` R14 把 `imu_median=true` 只判 **WARN**（不影响退出码），看似「已知危险配置闸门不拦」。但 checklist B20 明写「台架若真看到单块尖峰，改回 true 并记录原因」——这是**故意留的人工豁免通道**，与 Pass15/16 的「只建议不强制」不是同一类。⇒ **不改代码**，只在文档记录量化边界（ON 时 20–28.3 ms 超窗口）。同 §6 的 `bake_action_clip` 案例。

### 4.7.2 🔴 干净 checkout 实测：CI 从来没在 CI 的文件集上验证过

不靠推，用 `git archive HEAD | tar -x -C <clean>` 造出 **GitHub Actions 真正拿到的文件集**，逐条真跑：

| 检查 | 干净 checkout 读数 |
|---|---|
| `.upstream/` | **ABSENT**（`.gitignore:5` 排除） |
| 三个部署 onnx | **count 0**（`*.onnx` + `logs/` 双重 ignore，`git ls-files \| grep '\.onnx$'` = 0） |
| `record_provenance.py --verify` | **rc=1**（3× `DRIFT onnx missing on disk` + `authoritative calibration source missing`） |
| `pre_deploy_check.py --selftest` | **rc=1** |
| `pytest tests/ -q` | **25 failed / 18 passed / 9 skipped** |
| conductor 喂不存在的 onnx | contract/bundle/numeric/inference 四个 **FAIL** + onnxruntime `NO_SUCHFILE` traceback |
| 能真跑的 | `verify_policy_inference.py --selftest` rc=0、`assert_ci_verdict.py --selftest` rc=0、`record_provenance.py --print` rc=0 |

⇒ **Pass13/14/15/16 四轮都在改 `deploy-gate.yml`，四轮都跑过 selftest、都称 CI 绿，但没有一轮验证过「真闸门」引用的产物根本不在仓库里**。四轮验证的都是「本地完整工作区自洽」。这是 Pass16「inference 关是摆设」的同族且更底层：不是某一关摆设，而是**整个 workflow 的输入前提不成立**。

### 4.7.3 🔴 单一可信源自述失守（四轮漏检）

探针主跑报 `robotd_toml: SHA-DIFF`：bundle 记 **9007 B / `b71a5907…`**，磁盘 **9520 B / `f6ebad3c…`**。根因：Pass12 改了 toml 第 105 行「Radxa line」措辞注释，bundle 的 `artifacts` 指纹从未刷新；而 `verify_bundle()` 只比对 `provenance.per_artifact` 与 `verification_boundary`，**从不校验 `artifacts[]` 的 sha256/bytes** ⇒ Pass13–16 的 `--verify` 全绿。**记录 hash 却不检查 hash = 装饰**。

### 4.7.4 修复与验证（全部真跑，非归档沿用）

| 改动 | 内容 |
|---|---|
| `tools/hd1910/assert_clean_checkout.py`（新） | 机读 CI 输入探针：逐项检查存在 / **git 是否跟踪** / sha256 / bytes / 5 个 `.upstream` 源 / 训练栈，输出 `ci_full_gate_possible` + problems；8 条负对照 selftest（含「文件在盘但 gitignored」精确陷阱）、`--strict`（缺失 rc=1）、`--json`、`--github-output` |
| `.github/workflows/deploy-gate.yml` | 顶部写明 PASS17 边界（附干净 checkout 实测读数）；第一步加非阻断探针，打 `::warning::` + `REAL GATE NOT RUN` |
| `tools/hd1910/record_provenance.py` | 新增 `verify_artifact_hashes(bundle)` 并接进 `verify_bundle()`（放最后 + `max()`，避免被更早的 `rc=1` 赋值覆盖）；**先跑负对照确认 rc=1 / 两条 DRIFT，再刷新 bundle** |
| `out/hd1910_kp8_deploy_bundle.json` | `artifacts.robotd_toml` 刷成实际 `f6ebad3c…` / 9520 |
| `tools/hd1910/requirements.txt` | 删除 Pass12/13「onnx 装不上、inference SKIP 可接受」的**已被 Pass16 推翻**的注释，改写为「找错解释器 + CI 里 inference SKIP = BROKEN GATE」；补 `pytest>=8` |
| `tests/test_hd1910_tooling.py` | +5 项：探针 CLI selftest / `assess` 负对照 / `probe` 读 bundle 并识别未跟踪 / **`verify_imu_chain.py` 主跑 + selftest 真执行**（它终于有自动执行点）/ artifacts hash 三类负对照 |

**循环自身抓到 3 个本轮写进去的 bug**（都由负对照或 CLI 层测试当场变红）：① `assess()` 中 `sha_match=False & bytes_match=True`（同长度篡改，最常见 bitrot）两个分支都不进；② `artifacts=[]` 零 problems 被判 `runnable=True`；③ 探针 CLI 测试误抄了 `assert_ci_verdict` 的 selftest 措辞。⇒ 再次印证「静默 bug 发生在我自己那一行」与「新增 CLI 必须测 CLI 入口」。

**最终读数**：`pytest tests/` **57 passed in 91.63s**；`conductor --selftest` PASS；三个 kp8 onnx 五关全部 `PASS`（contract/bundle/numeric/inference/toml = PASS，rc=0）；`provenance --verify` **rc=0** 含 `OK artifacts sha256/bytes match for 4 file(s)`；探针 `--selftest` PASS、`--strict` rc=1；`verify_imu_chain.py` 主跑 `all pass` + selftest `all consistent`。

### 4.7.5 本轮**没做**（明确边界，不是遗漏）— ✅ 已于 Pass18 解决

CI 架构级修复需要决策：**是否把 3 个已验证 onnx（合计 2,381,098 B ≈ 2.27 MiB）与闸门依赖的少量 `.upstream` Rust 源码作为 fixture 纳入版本控制**。`git add -f` 实测可行，项目 `.gitignore` 注释也确立了「证据必须留在 VCS」原则（bundle.json / deploy_check 报告均已入库）；但第三方源码快照与二进制入库属资产策略变更，本轮**不擅自决定**。当前探针让「CI 绿 ≠ 部署已验证」机读可见，权威验证仍是**本地完整工作区**跑 `pre_deploy_check.py` + `pytest tests/`。剩余 OPEN：硬件端到端（到货后逐关节复核 + 7.4 V 齿隙重测）、P3 暂缓、P4 可选。

> **Pass18 判决（用户「按最优的来」）**：选「入库并打通」，不降级。理由与全部实测见 §4.8。

---

## 4.8 Pass18 自主审计（2026-11-08）— 按最优方案打通 CI 真闸门

### 4.8.1 深挖：用实测（不是推断）定出 CI 输入闭包

`git archive HEAD` 解出的干净副本先补候选文件、再跑到 `verify_policy_bundle.load_contract()` 不再报缺，得到最小闭包：

| 类别 | 文件 | 体积 |
|---|---|---|
| 部署策略 | 3 个 `logs/rsl_rl/*/*.onnx` | 2,381,098 B |
| robotd/RL 契约源 | `DuckBuddy-main/duck-control/src/{obs,model,policy,imu,feetech}.rs`、`duck-ipc-proto/src/lib.rs`、`robotd-params/src/lib.rs`、`microduck_rl-develop/.../publish/manifest.py`、`hd1910m/radxa/installation.json` | 450,193 B |
| 伴随元数据 | `out/runmeta_*.json` + `out/heading_meta_*.json` 中未入库的 32 个 | ≈ 93 KB |

补齐后 `load_contract()`：`obs_len=61 / action_len=14 / joint_names=15 / home=15 / input='obs' / problems=[]`。**Pass17 探针的 5 项清单漏了 4 个真正被解析的文件**——「查全比查到更重要」再次命中；探针自己漏报输入，正是 Pass13–16 的同族失效。

另纠正一条错误前提：干净副本 `pytest` 的 21 个 `test_hd1910_configs.py` 失败**不是资产缺失**，而是 `plant_spec.LIVE_CONSTANTS` 把 `<repo>/.venv-mjlab/Lib/site-packages/...` 拼在 cwd 下；本地同条 PASS。改成 `importlib.util.find_spec("mjlab_microduck")` 从已安装包解析源码位置，lean 环境才由 module-level skipif 诚实跳过。

### 4.8.2 对照：为什么「入库」比「降级为显式边界」最优

项目**早有**证据入库惯例，不是新策略：`microduck-software/out/` 已入库 **283** 个文件、全仓已有 **2** 个 force-add 的 `.onnx`（`artifacts/flat_walk/`）、`.gitignore` 已给 `!out/heading_meta_*.json` 开例外（23 个在库）；根注释明写「every bench file had to be force-added by hand」。缺的只是 `!out/runmeta_*.json`（0 个在库）与被校验的**主体**。总增量 ≈ 2.84 MiB，远小于任何训练产物。降级方案会让 CI 永久只能验证「守卫逻辑」，真闸门 `safe to load` 永远不在 CI 执行 ⇒ Pass13–16 的病根被文档化而非治愈。

唯一不可在 lean CI 复现的是 `contract` 关（需 `mjlab_microduck` + torch + mujoco）。保留**显式 SKIP**（`assert_ci_verdict.py --allow-skip contract`）+ 本地 `.venv-mjlab` 五关全 PASS 作为发货前权威验证，不伪装成 5/5。

### 4.8.3 落地改动

- 两层 `.gitignore` 标注 force-add 证据清单（父目录 ignore 无法用嵌套 `!` 反包含，沿用项目既有 `git add -f` 惯例）；子文件补 `!out/runmeta_*.json`。
- `assert_clean_checkout.py`：`UPSTREAM_SOURCES` 5 → **9**；`assess()` 拆成 `ci_scope_gate_possible`（4/5，CI）与 `ci_full_gate_possible`（5/5，含训练栈），`scope_problems` 独立；`--strict` 管前者、`--strict-full` 管后者；`--github-output` 同时写 `scope_gate` / `full_gate`；selftest 补 4 条分层与闭包负对照。
- `pre_deploy_check.py`：`run_selftest(allow_skip=())`，**默认空白名单** ⇒ 任何 SKIP 都是 FAIL；CI 必须显式传 `--selftest-allow-skip contract.selftest`，结果打印 `PARTIAL` + `GUARD SELFTEST NOT FULLY VERIFIED`；未知白名单名 rc=2，FAIL 仍红。
- `deploy-gate.yml`：探针改 `--strict`（硬门禁）、新增 `pytest tests/ -q -rs`、conductor selftest 带白名单、三策略真闸门保留、末尾显式打印验证边界。
- `requirements.txt` 写明 lean 边界；`tests/test_hd1910_tooling.py` 新增 5 条（selftest 白名单双向负对照、CLI 入口、分层 verdict、`--strict-full` 环境感断言、9 源闭包正/负对照）。

### 4.8.4 验证读数（lean CI 模拟，非归档沿用）

本机 pip 镜像装不上 `onnx>=1.20.1`（`from versions: none`）⇒ 造 lean venv 失败。改用 `sitecustomize.py` 精确屏蔽 `mjlab_microduck / mjlab / torch / mujoco / warp / scipy`：`meta_path` finder 让 `import` 抛 `ModuleNotFoundError`，同时包裹 `importlib.util.find_spec` 让判据返回 `None`；onnx / numpy / onnxruntime / pytest 全部复用本机已装版本。所有子进程通过 `PYTHONPATH` 继承该屏蔽。

| 检查 | 本地完整栈 | lean CI 模拟 |
|---|---|---|
| `pytest tests/` | **62 passed** | **36 passed / 26 skipped**（skip 理由逐条可见） |
| `assert_clean_checkout.py --strict` | rc=0，scope/full 均 true | rc=0，**scope=true / full=false** + `CONTRACT STAGE NOT VERIFIED IN CI` |
| `pre_deploy_check.py --selftest` | PASS | 带白名单 **PARTIAL rc=0**；不带白名单 **rc=1** |
| `record_provenance.py --verify` | rc=0 | rc=0 |
| 三策略真闸门 | 五关全 `PASS` | 三份 `PASS*`：`contract=SKIP`，`bundle/numeric/inference/toml=PASS`，断言 rc=0 |

**负对照**：① 改坏入库 onnx 的 1 字节 ⇒ `contract/bundle/numeric/inference` 四关 FAIL、`VERDICT: FAIL`、断言 rc=1；② 临时移走 `policy.rs` ⇒ 探针 `--strict` rc=1 且点名缺失源，恢复后 rc=0。

**循环自身抓到的 2 个错**：workflow step name 里 `strict: real` 的 `: ` 被 PyYAML 判 `mapping values are not allowed`（加引号修）；负对照 B 最初在 **Pass17 旧代码的干净副本**上做，那份探针清单本就没有 `policy.rs`，「删了不红」是验证设计错，不是守卫失效 ⇒ 换到新代码重做才变红。

**提交后权威复验（`76b0c4a`，用 `git worktree` 造**带 `.git`** 的干净 checkout —— `git archive` 没有 `.git`，会让 `_tracked()` 假红；`actions/checkout@v4` 是有 `.git` 的）**：探针 `--strict` rc=0 且 `GITHUB_OUTPUT` 写出 `scope_gate=true` / `full_gate=false`；探针 / 断言 selftest 全 PASS；conductor selftest **PARTIAL rc=0**；`pytest tests/ -q -rs` **35 passed / 27 skipped**；`provenance --print` / `--verify` rc=0；三策略 `PASS*`（四关真 PASS）+ 断言 rc=0。**同一份干净 checkout** 换回完整栈解释器，第一策略五关全 `PASS` —— 差别只来自训练栈，不来自文件集。

> **复验时「再挖掘」又抓到一条环境借口**：`test_record_provenance_absent_meta_is_honest` 因未入库的本地 `out/p8head_2999.onnx` 而在干净 checkout 上 skip。`provenance_for_onnx()` 实际只读 stem、伴随 meta 从全局 `OUT/` 查 ⇒ 改为 `tmp_path` 合成 bare onnx，同一逻辑在任何 checkout 都真跑，CI 少一个 skip。

### 4.8.5 剩余边界

CI 现可真跑 4/5 关；`contract` 关与 `tests/test_hd1910_configs.py` 的 21 条 kinematics、IMU 链真执行仍**只在本地完整栈**发生，workflow 显式打印该边界。硬件端到端（到货后逐关节复核 + 7.4 V 齿隙重测）、P3（≥3 seed sweep，用户暂缓）、P4（VelStand/手柄，可选）状态不变。

---

## 4.9 Pass19（2026-11-08）：workflow 从未被 GitHub 发现

### 4.9.1 三条独立一手证据（不是推断）

1. **官方文档**：`docs.github.com/actions/writing-workflows/quickstart` 原文
   > "For GitHub to discover any GitHub Actions workflows in your repository, you must save the workflow files in a directory called `.github/workflows`."
   
   `.../reference/workflows-and-actions/workflow-syntax` 原文
   > "You must store workflow files in the `.github/workflows` directory of your repository."
   
   即仓库根的 `.github/workflows`，子目录同名目录**不具备发现语义**。
2. **本地文件树**：`git rev-parse --show-toplevel` = `E:/WorkBuddyData/WorkBuddy/2026-10-23-08-26-15`，根目录 `ls -la .github/` → **不存在**；`git ls-files | grep '\.github/workflows'` 只有一条 `microduck-software/.github/workflows/deploy-gate.yml`。
3. **GitHub 官方 API（远端实数）**：`GET /repos/chenshiyilisha/microduck-flat-walk/contents/` 根目录列表无 `.github`；`GET /contents/.github/workflows` → **404 Not Found**；`GET /actions/workflows` → **`total_count = 0`**（已注册 workflow 数为零）。另 `git rev-list --count origin/main..HEAD = 33`、远端 HEAD `228933d0`、`pushed_at 2026-11-07T01:57:36Z` ⇒ Pass13–18 的提交**从未推送**。

⇒ Pass17 修的是「CI 拿到文件后能验证什么」，Pass18 修的是「输入是否在 VCS」；**这一轮才看见 CI 本身从来没被 GitHub 注册过**。四轮「CI 绿」全部是本地完整工作区自洽，且比 Pass16 的「某一关摆设」更底层。

### 4.9.2 对照判决表

| 候选 | 一手事实 | 判决 |
|---|---|---|
| 保留子目录 + 加说明 | 官方文档 + Actions API `total_count=0` | ❌ 否决：文件仍永不被发现 |
| **`git mv` 到仓库根 + 推送** | 根 `.gitignore` 不排除 `.github`（`git check-ignore` 实测 NOT ignored）；`defaults.run.working-directory: microduck-software` 在根位置仍成立 | ✅ **最优**：最小改动让文件集与触发条件同时成立 |
| CI 内自检 workflow 位置 | workflow 位置错 ⇒ 没有 job 运行 | ❌ 不可能自守，必须**本地**门禁 |
| contract 关在 lean CI 里用训练侧冻结快照 | `verify_policy_contract.py:190-228` 需 `MICRODUCK_WALK_ROBOT_CFG.spec_fn().compile()`（MuJoCo）+ live cfg；该关全部价值＝两个独立**实时**来源互比 | ❌ 否决：冻结快照＝退化成与静态证据比，与 Pass17 的 `artifacts` hash 四轮 bitrot 同族 |
| 照抄官方 RUNTIME 三件套 | 官方 `RUNTIME.md` + `runtime/policy_pair.py` + `cpu-export-parity.json`（2.63e-6 / 9.54e-7，300 samples，明写「not bit-exact recorded action parity」） | ⭕ **已有等价且更强**：本项目 `tools/check_onnx_parity.py` 独立 numpy 重建、`--control` 强制「去掉归一化必须发散」负对照 + 4 份 parity JSON；不新增。官方把 joint order/HOME 嵌 ONNX metadata 的路线在本代 robotd 上不适用（不读 manifest） |

### 4.9.3 落地改动

- `.github/workflows/deploy-gate.yml`：`git mv` 从子目录到仓库根；头部写明位置约束与 Pass13–18 史实；末尾边界打印加 `workflow_discoverable`。`working-directory` 仍为 `microduck-software`，无需改任何步骤。
- `tools/hd1910/assert_clean_checkout.py`：新增 `WORKFLOW_REL`、`_repo_root()`（`git rev-parse`，`git archive` 副本 fallback 到 `root.parent`）、`probe_workflow()`（根 workflow 存在 + 纯文本校验 `on:/jobs:/working-directory:`、两层子目录孤儿扫描、排除 `.upstream`/`.venv*`/`third_party`）、`workflow_problems()` 纯函数；problems 并入 `scope_problems` 使 `--strict` 变红，报告加 `workflow` / `workflow_problems` 段，`GITHUB_OUTPUT` 写 `workflow_discoverable`；selftest +4 条负对照（共 15 条）。**纯 stdlib，不引入 PyYAML。**
- `tests/test_hd1910_tooling.py` +3：根位置/孤儿结构断言、纯函数 4 负对照、**真实 CLI** 正+负对照（`tmp_path` 造无根 workflow 镜像 → rc=1 且 `NOT DISCOVERABLE`；补回有效根 workflow → `workflow_problems == []`，空 bundle 仍保持 rc=1 不假绿）。

### 4.9.4 验证读数（全部真跑）

- 本地完整栈 `pytest tests/` **65 passed**；lean CI 模拟（`sitecustomize` 屏蔽训练栈）**39 passed / 26 skipped**。
- 探针 `--selftest` 15 条全 PASS；本工作区 `--strict` **rc=0**，`workflow : DISCOVERABLE .github/workflows/deploy-gate.yml (repo root via git)`，`ci_scope/full = true/true`；YAML 解析 OK（13 steps、`working-directory: microduck-software`）、bundle JSON OK。
- **文件系统级负对照**：移走根 workflow ⇒ `--strict` **rc=1** + `NOT DISCOVERABLE` + `ci_scope=false`，`test_ci_workflow_is_at_repo_root` 变红；造 `microduck-software/.github/workflows/orphan.yml` ⇒ **rc=1** + `ORPHAN WORKFLOW` + 位置测试变红；恢复 ⇒ rc=0、位置测试 PASS。
- **🔴 远端复核：第一次真实 CI 运行是红的（本轮「再挖掘」抓到的真缺口）**。推送 `dac3cf5` 后 `GET /actions/workflows` → **`total_count = 1`**（`deploy-gate | path: .github/workflows/deploy-gate.yml | state: active`，id `410908045`），`GET /contents/.github/workflows` → `deploy-gate.yml` 6512 B，`GET /actions/runs` → **1 个 run**（`push | completed | failure | dac3cf5a`）。用已认证的 `gh run view 42450956452 --log-failed` 取到真实日志：**step 5「CI input readiness probe --strict」rc=1，后续 9 步全部 skipped**；唯一 problem 是 `artifact robotd_toml: sha256 differs from bundle`，三个 onnx 全部 `sha-ok`，`workflow: DISCOVERABLE`。⇒ **workflow 确已被发现并触发，但输入守卫仍因换行差拒绝放行**。
- 🔴 **根因（`core.autocrlf=true` + 无 `.gitattributes`）**：`git config core.autocrlf = true`；本地磁盘 `out/robotd_hd1910_mode0.toml` = **CRLF 9520 B / `f6ebad3c…`**，git blob 与 Linux CI checkout = **LF 9382 B / `2b054f78…`**（差 138 B = 138 行）。bundle 记的是**本机工作树字节**——Pass17「先负对照变红再刷新 hash」这一步没意识到刷新值本身是平台相关的。三个 onnx 是二进制、git 不做文本转换，磁盘与 blob 逐字节相同，故只有这一个文本证据漂移。
- **修（按最优＝修根因，不是改本地结论）**：① 新建仓库根 `.gitattributes`，把该 toml 钉成 `text eol=lf`、`.gitattributes` 自身也 `text eol=lf`、`*.onnx binary`；② 本地工作树重写为 VCS blob 的 LF 字节，`git add --renormalize` 后 HEAD/index 均为 9382 / `2b054f78…`；③ bundle 的 `robotd_toml` 指纹刷新为 **9382 / `2b054f7893db85f5977092dcc093eabc9a774182e2cc4a4163bf58501d83ae9a`**（锚定 VCS 规范字节）；④ 两处守卫在 sha mismatch 时新增 `EOL-ONLY difference` 诊断（`assert_clean_checkout.py::_eol_only_drift()` 与 `record_provenance.py::verify_artifact_hashes()`），避免下次把换行差误读成真 bitrot；⑤ **新增 2 条跨平台不变式测试**：`test_bundle_artifact_hashes_match_committed_blobs`（用 `git show HEAD:<path>` 逐项比对 bundle 指纹，锚定 VCS 而非本机工作树）、`test_evidence_toml_is_lf_and_pinned_by_gitattributes`（断言工作树无 CRLF、`git check-attr eol: lf`、CRLF 负对照指纹必漂移、真内容篡改不会被误判为 EOL-only）。
- **本地复验读数**：`pytest tests/` **67 passed**；lean CI 模拟 **41 passed / 26 skipped**、conductor selftest `PARTIAL rc=0`、三策略 `PASS*`（contract 显式 SKIP，其余四关真 PASS）+ 断言 rc=0；探针 `--strict` **rc=0**（`robotd_toml sha-ok`）；`provenance --verify` **rc=0**（`OK artifacts sha256/bytes match for 4 file(s)`）。
- **🔴 第二次远端 run（`42452064948` / `86e6acd`）仍红，但前移到 pytest 步骤**：EOL 修复已生效（探针与所有 selftest 全绿），`gh run view --log-failed` 显示 **`sssssssssssssssssssssssss.........FFFFFFF..............s...........`** —— 7 个 tooling 测试全部 `ModuleNotFoundError: No module named 'bam'`（`tools/bam_actuators.py:36`）。根因：`tools/hd1910/rehearse_hd1910.py:56` **顶层** `import bam_actuators`；`bam` 是本机 `.upstream/bam-62bd8ce…/` 的 gitignored 仿真快照，CI 只装 `requirements.txt` 根本没有。7 条测试验的是 `_normalize_plant` / `_onnx_plant_key` / `_plant_from_filename` 等**纯逻辑**，不该被仿真依赖拖垮。⚠️ **我们的 lean CI 模拟器本身不完整**：`sitecustomize.py` 的 `BLOCKED` 只列了训练栈，本机仍装着 `bam` ⇒ 本地模拟 41 passed 假绿，真实 CI 才暴露。这是「验证工具自己漏报输入」的又一层。
- **按最优修（不装重依赖、不宽泛 SKIP）**：把 `import bam_actuators` 从顶层移到 `_patch_upstream()` 内（真正构建 rehearsal 时才注册 actuator），缺 BAM 时抛明确 `SystemExit("rehearsal needs the BAM simulation stack … run with .venv-mjlab")`；纯逻辑函数与其 7 条回归测试在 lean CI 真跑。`sitecustomize.py` 的屏蔽名单补 `bam` 并写明「模拟器欠屏蔽＝假绿」。新增 2 条守卫：`test_rehearse_hd1910_has_no_top_level_bam_import`（AST 只查模块级 import，把顶层 import 挪回必红）、`test_rehearsal_pure_logic_imports_without_bam`（**独立子进程 + meta_path finder** 让 `import bam` 抛 `ModuleNotFoundError`，仍能加载模块并拿到 `_normalize_plant`）。`requirements.txt` 补 PASS19 边界说明。
- ✅ **第三次远端 run（`42452793362` / `1ba236e`）全绿——史上第一次真实 CI success**。推送 `1ba236e` 后 `gh run watch` 显示 14 个步骤全部 ✓（`deploy-gate` in 21s）；`GET /actions/runs` 实数 `{"conclusion":"success","headSha":"1ba236e9e5b108a64f7726e380dbd0fca2ab986e","status":"completed"}`。**从真实日志（`gh run view 42452793362 --log`）取到的读数，不是本地推断**：
  ```
  workflow      : DISCOVERABLE  .github/workflows/deploy-gate.yml (repo root via git)
  ci_scope_gate_possible = true  (4/5 stages in CI)
  39/39 passed                      # 探针 selftest
  44 passed, 26 skipped in 3.03s   # pytest（26 skip 全为训练栈依赖，见下）
  OK artifacts sha256/bytes match for 4 file(s)
  VERDICT: PASS*  stages={'contract':'SKIP','bundle':'PASS','numeric':'PASS','inference':'PASS','toml':'PASS'}   # 三策略各一份
  OK: verdict=PASS*  /  VERDICT: PASS -- gate really executed
  scope_gate=true
  full_gate=false
  workflow_discoverable=true
  CONTRACT STAGE NOT VERIFIED IN CI -- run pre_deploy_check.py and pytest tests/ with .venv-mjlab before shipping.
  ```
  - **26 个 skip 逐条核过是诚实的**（`-rs` 明细）：25 条来自 `tests/test_hd1910_configs.py`（`mjlab_microduck not importable`，即 §4.9.5 所述 21 条 kinematics + 同源配置不变量）+ 1 条 `tests/test_hd1910_tooling.py:680` IMU 链守卫（`scipy / mjlab_microduck absent`）；**没有一条是 tooling/闸门测试被静默跳过**。
  - **本地完整栈在最终 HEAD 上补跑，坐实「发货前 5/5」不是空话**：`.venv-mjlab` 下 `pytest tests/` **70 passed / 113.99s**、探针 `--strict` **rc=0**（`ci_scope_gate_possible=true`、`ci_full_gate_possible=true`、9 个 upstream 源全 present、training stack present、`workflow DISCOVERABLE`）；三策略五关全部 `PASS -- safe to load (all stages verified)`，**contract 关在完整栈真的 PASS**（不是 CI 里的 SKIP）。⇒ CI 的 `PASS*` 与本地 `PASS` 是同一套守卫在不同依赖闭包下的两种诚实结论，`full_gate=false` 不是缺陷而是分层 verdict 如实上报。
- **三次真实 run 的完整链条**：`42450956452` failure（CRLF/LF）→ `42452064948` failure（`bam` 顶层 import）→ `42452793362` **success**。⇒ 本轮「再挖掘」不是靠本地模拟收口：前两次都是推送后由**真实 GitHub runner** 才暴露的前提错误（本地 lean 模拟器两次都假绿）。**真实 CI 是最终验证，替身不是**。

### 4.9.5 剩余边界

`contract` 关（需 torch/mujoco/mjlab_microduck）与 21 条 kinematics、IMU 链真执行仍只在本地完整栈发生；workflow 显式打印。**这一边界已在最终 HEAD `1ba236e` 上实测兑现**（本地完整栈 70 passed + 三策略五关 `PASS`、contract 真 PASS、探针 `ci_full_gate_possible=true`），因此 `full_gate=false` 是分层 verdict 如实上报，不是「发货前验证从未做过」。硬件端到端、P3 暂缓、P4 可选状态不变。**workflow 位置守卫是本地门禁，不是 CI 自守**——若有人把文件挪回子目录，CI 不会报错，只有本地 `--strict` / `pytest` 会红。

## 4.10 Pass20 / 循环 R4（2026-11-08）：CI 真闸门的第三份清单 + 治理边界

### 4.10.1 深挖：从「闸门内容」上移到「仓库治理」

推送 `cbe3d98`（R3 收口）后第四次真实 run `42453745804` 也是 success。继续「再挖掘」，把视角从「CI 里验证什么」上移到「CI 的结论 gate 住什么」，用 GitHub 官方 API 取三条实数：

- `GET /repos/.../branches/main/protection` → **404 `Branch not protected`**；`GET /repos/.../rulesets` → **`[]`**；仓库 `allow_merge_commit/rebase/squash` 全开、`default_branch=main`、`private=false`。
- `GET /pulls?state=all` → **0 个 PR**；`GET /actions/runs` 的 `event` 去重 → **只有 `push`**（前 4 次 run 全是 push）。
- **两次 failure 的提交 `dac3cf5a` / `86e6acd` 都是 `main` 的祖先**（`git merge-base --is-ancestor` 实测），对应 check-run `deploy-gate: failure`。⇒ 红 CI 从未阻止提交进入 main，**CI 是 post-push advisory，不是合并门禁**，这是实证不是推断。

### 4.10.2 官方一手语义（先查资料，不自己推）

| 官方文档 | 原文要点 | 对本仓库的含义 |
|---|---|---|
| `about-protected-branches` | "Require status checks **before merging**"；"By default, the restrictions of a branch protection rule **don't apply to people with admin permissions**" | 本账号 `permissions.admin=true`，默认可绕过；且这是 PR 语义 |
| `available-rules-for-rulesets` | "**Restrict updates**: only users with bypass permissions can push" 是**独立于** "Require status checks to pass before merging" 的另一条规则 | 要拦直接 push 得单独开 restrict updates，只加 required check 不拦 |
| `status-checks` | "A job that is **skipped** will report its status as **'Success'. It will not prevent a pull request from merging, even if it is a required check**"；"GitHub Actions generates **checks**, not commit statuses" | 加 required check 反而多一条假绿通道 |
| `troubleshooting-rules` | "Required status checks **do not take workflow, matrix, or event trigger types into account**" | 同名 check 来自别的 workflow 也会算满足 |
| `skipping-workflow-runs` | `[skip ci]` / `skip-checks: true` 可跳过 push 与 pull_request 的 workflow，此时 checks 保持 Pending | 单人直推工作流下无人可拦 |

⇒ **判决：治理层是设计约束，不是缺陷**。本仓库单人直推 main、0 PR、全是 push 事件、账号是 admin；加 branch protection / ruleset 既拦不住直接 push、又被 admin 默认绕过、还引入 `skipped=Success` 假绿。**「按最优」＝写清边界 + 强化本地 pre-push 门禁，而不是加装饰性远端配置**；workflow 头注释与末尾打印均写明 `CI IS A POST-PUSH ADVISORY CHECK, NOT A MERGE GATE`。未擅自改远端仓库设置（这是用户的治理决策）。

### 4.10.3 🔴 真静默漏检：workflow 里第三份硬编码清单

深挖 workflow 的 `Real deploy gate` 步骤，发现它把**三个 onnx 路径、`out/robotd_hd1910_mode0.toml`、`--expect-kp 16` 全部硬编码**在 shell 里——这是与 bundle `artifacts`、探针 `UPSTREAM_SOURCES` 并列的**第三份输入清单**，却没有任何守卫校验它与 bundle 同步。

**负对照坐实**（同族于 Pass17「记录 hash 却没人重算」、Pass9「四关全过却接错策略」）：把 groundpick 路径改成 `2026-11-06_22-17-10_STALE_STALE.onnx` 后——

```
probe --strict rc = 0          (ci_scope/full = true/true)
pytest (workflow/bundle/clean_checkout) rc = 0   11 passed
provenance --verify rc = 0
```

三套守卫**全绿**。若有人更新 bundle 换策略却忘改 workflow，CI 会继续验证旧策略并全绿，而 bundle 声明发货的是新策略。

### 4.10.4 按最优落地：单一可信源，不是「再加一份同步检查」

否决「加一条 workflow↔bundle 一致性检查」（仍是两份清单，且检查本身会漏报）。改为**消除第三份清单**：

- 新增 `tools/hd1910/ci_gate_targets.py`（纯 stdlib）：从 `out/hd1910_kp8_deploy_bundle.json` 读三个 onnx + toml + `plant.position_kp`，校验键齐全 / 路径安全（白名单 `[A-Za-z0-9_./-]`、禁 `..` 与 shell 元字符）/ 文件真实存在 / kp 为正整数，输出 shell-safe 的 `GATE_*` 变量；`--sh` / `--json` / `--selftest` 三个 CLI 出口，13 条负对照。
- `deploy-gate.yml` 的 real-gate 步骤 `source` emitter 输出，用 `$GATE_WALK/$GATE_GROUND_PICK/$GATE_STAND/$GATE_TOML/$GATE_EXPECT_KP`；新增 CI 步骤跑 emitter selftest。
- `assert_clean_checkout.py` 新增纯文本守卫 `gate_target_problems()`（过滤注释行、正则抓 `.onnx|.toml` 字面量与硬编码 `--expect-kp`、emitter 调用被删也报），problems 并入 `scope_problems` 使 `--strict` 变红；selftest +5 条负对照（共 20 条）。
- `tests/test_hd1910_tooling.py` +5 条：CLI 入口真跑、坏 bundle 必拒、真实 workflow 结构 + 3 条纯函数负对照、**文件系统级 `--strict` 负对照**、以及「两条独立算法算同一个量」守卫：`expect_kp == register_kp(gain=200, position_kp=16)`（toml 用 `tomllib` 独立解析）。该等价只在 `gain=200` 成立，emitter 注释明写「gain 改变须改用显式 `expected_reg50`」。

**修复后的负对照**（同样篡改）：`--strict rc=1` + 点名 `CI GATE TARGETS HARD-CODED`，pytest 结构测试 `1 failed`。⇒ 之前全绿的地方现在真的会红。

**「单一可信源不是换个地方硬编码」的独立验证**：把临时 bundle 的 `plant.position_kp` 改成 8 → emitter 输出 `GATE_EXPECT_KP=8` → 喂给真实 toml 关得到 `toml FAIL`、conductor `rc=1`。值真的驱动闸门。

### 4.10.5 验证读数（全部真跑 + 真实 runner）

- 本地完整栈 `pytest tests/` **75 passed / 105s**；探针 `--selftest` 20 条全 PASS、`--strict` **rc=0**（scope/full = true/true）；emitter selftest 13 条 PASS；`provenance --verify` **rc=0**（`OK artifacts sha256/bytes match for 4 file(s)`，唯一 WARN 是 git_commit 随提交变化）。
- lean CI 模拟（屏蔽训练栈 + `bam`）**49 passed / 26 skipped**、探针 `--strict` rc=0（scope=true/full=false）；emitter 用**纯系统 Python** 在干净副本跑 selftest 也 PASS ⇒ 零隐藏依赖。
- **端到端真跑 workflow 新 gate 块**：emitter → source → 三策略 conductor → `assert_ci_verdict.py --allow-skip contract`，三份 `PASS*` + `VERDICT: PASS -- gate really executed`。
- 🔑 **方法纠正**：`git archive` 副本**没有 `.git`**，探针的 `_tracked()` 与 `git show HEAD:` 测试会误报 5 条失败（全是既有 git 依赖测试，非本轮新增）。真实 CI 用 `actions/checkout`（有 `.git`），故改用**本地 `git clone` 造带 `.git` 的干净副本**：`--strict rc=0`（scope=true/full=false，与真实 CI 一致）、pytest **49 passed / 26 skipped**。
- ✅ **第五次真实 GitHub Actions run `42456241221` / `e8c1666` = success**（14+ 步全绿，新增 `CI gate targets negative-control self-test` 真跑）。真实日志读数：`39/39 passed`（探针 selftest）、`SELFTEST: PASS`（emitter）、`49 passed, 26 skipped in 2.67s`、三个 `=== gate: <GATE_* 解析出的真实路径> ===`、三份 `OK: verdict=PASS* stages={'contract':'SKIP','bundle':'PASS','numeric':'PASS','inference':'PASS','toml':'PASS'}` + `VERDICT: PASS -- gate really executed`、`scope_gate=true / full_gate=false / workflow_discoverable=true`、末尾 `CI IS A POST-PUSH ADVISORY CHECK, NOT A MERGE GATE` 与 `CONTRACT STAGE NOT VERIFIED IN CI` 均生效。
- **剩余边界不变**：`contract` 关与 21 条 kinematics、IMU 链真执行仍只在本地完整栈；硬件端到端未启、P3 暂缓、P4 可选。本轮未做长时训练。非阻断 runner 注解：Node.js 20 deprecated 被强制 Node.js 24、ubuntu-latest 未来迁移 Ubuntu 26（不影响 job conclusion）。

---

## 5. 证据索引（本轮查证）

- 官方站起修复：`pollen-robotics/microduck_rl@develop` → `src/mjlab_microduck/tasks/microduck_standup_env_cfg.py`（`set_ground_state`、`ground_state_mix`、`face_up_roll_max`）。
- HD-1910 已含修复：`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/tasks/microduck_standup_env_cfg.py` grep 命中 `ground_state_mix` / `face_up_prob` 0.00→0.35 / `face_up_roll_max=math.radians(90)`。
- 官方 tests 范式：`.upstream/microduck_rl-develop/tests/test_velstand_cfg.py`（CPU，build cfg + compile spec，锁 servo geom / joint 名 / 奖励符号）。
- 本仓库新 tests：`microduck-software/tests/test_hd1910_configs.py`（9 passed @ live hd1910_kp8）；`microduck-software/tests/test_hd1910_tooling.py`（5 passed @ CPU，覆盖 conductor/rehearsal/provenance 三个新工具）。
- 关节映射规范（14 驱动关节，free joint 除外）：live kp8 模型实测顺序已硬编码进测试。
- HD-1910 真实 bus ID 来源：`.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`，15 关节 ID 与方向）；JOINT_NAMES 顺序见 `duck-ipc-proto/src/lib.rs:368`；XL330 参考 map 见 `duck-control/src/model.rs:15`（仅参考，不适用于本机体）；`bus.joint_ids` 必填/拒绝开总线见 `robotd/src/main.rs:5495` + `audit_robotd_toml.py`。
