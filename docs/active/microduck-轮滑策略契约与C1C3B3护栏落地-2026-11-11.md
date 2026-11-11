# 轮滑策略契约 + C1/C3/B3 护栏落地（2026-11-11）

> 用户「按你的建议来」= 授权落地上一轮软件盘点给出的优先级清单。本轮按建议顺序执行 **C1 → C3 → B3**，并把与 C1 强耦合的 **P0-2（轮滑策略契约）** 一并落地；其余 P1（B7/B4/B6）与 P2（完整派生 `known_gaps`）留作下一批，见 §8。
> 一手基线：`run_all_gates.py --check` 原 42/42 PASS、`ship_verdict=NOT_SHIPPABLE`、40 个 `--selftest` 工具、20 个 `REPORT_ONLY` 未登记标签；上轮 `pytest` 141 passed。

## 0. 本轮判决（先看这四条）

1. 🔴 **A2 的「文档出现未登记标记必红」原本可被绕过**：`check_closure.py:scan_doc_marks()` 只扫 `ROOT/docs/**/*.md`，而用户拍板两版都做产生的 `INCONCLUSIVE_ROLLER_POLICY` 只写在 gitignored 的 `out/deliverables/` 打印包里。已改为**显式白名单多根扫描**并正式登记为第 7 条契约（`UNVERIFIED` / `evidence=[]` / `--ship-gate` 必红）。
2. 🔴🔴 **一手查全推翻了上一轮的口径**：本地上游训练台 `pretrained_models.json` 实读 20 条，除 2 条官方 XL330 滑轮策略外，还有 **4 条 kissqy V167 / HD1910 专用滑轮 ONNX**（`swizzle` / `crouch` / `spin` / `standup`），带 sha256、`size_bytes`、`model_file`，`download_url` 指向 `Microduck-Robotd-FT6-R17.tar.gz`。但 `verification` 原文是「**作者 V167 审计记录 QEMU ARM64 推理通过，`hardware_tested=false`；不是本机物理评估结果**」。⇒ 悬案从「完全不知道有没有策略」收窄为「**目录级证据已有、发布包未到手、中控实机加载未验**」，**不是**「轮滑版能跑」。
3. 🔴 **两套 roller 清单不同源，不能混算**：11-06 变体计划 §6 说的「官方 5 个 roller 策略」来自另一份 `pretrained_models.json`；本仓训练台 JSON 里官方 roller 只有 2 个 + kissqy 4 个 = 6 个条目。按「项集合绑单一权威源码」，`roller_policy_contract.json` 的 `required` 集合只绑这份本地实读文件，5 个名字单独记录并标 `different_source=true`。
4. 🔴 **CI 接入必须分层**：workflow 是 lean Python 3.12 + `requirements.txt`（onnx / onnxruntime / numpy / pytest），**没有** torch / mjlab / mujoco / scipy / bam。直接接 `run_all_gates.py --check` 会得到一片诚实的假红。正解 = 从 `line_labels.json` 派生 **9 个 stdlib-only meta guards** 逐条跑 `--selftest`，另把 `run_all_gates.py --selftest`（只跑注入 fixture 的编排器自检）单列；`--check` 全量真跑仍留本地 `.venv-mjlab`。**POST-PUSH ADVISORY、非 merge gate** 的边界不变。

## 1. C1：扩 A2 扫描范围 + 登记第 7 条契约

### 1.1 修法

`check_closure.py` 新增 `SCAN_ROOTS` 显式白名单（相对仓库根）：

| 根 | 作用 |
|---|---|
| `docs` | 原有权威文档（含子目录） |
| `out/deliverables` | 用户拍板产生的交付说明（gitignored，CI 里可缺席） |
| `microduck-software/tools/hd1910` | 工具自带 `.md` 里的一手说明 |
| `README.md` / `AGENTS.md` | 根级规范 |

`default_scan_roots()` 只返回**实际存在**的根，报告新增 `scan_roots` / `scan_excluded` / `scan_excluded_reason`，缺失的根自动跳过并在报告里如实列出 ⇒ CI（无 `out/`）与本机（有 `out/`）都能得到相同的 7 个标记集合。**刻意不全仓 rglob**：`.workbuddy/memory/**`（史料日志）与 `.upstream/**`（第三方文档）不是活的契约，扫进去会把几十个历史标记拉进「必须登记」集合，制造假红。

### 1.2 连带影响（查全，不是只改一个函数）

`board_acceptance.py:validate()` 有一条硬断言：**每个 `status=UNVERIFIED` 的契约必须至少被一条 check 的 `closure_refs` 引用**。第 7 条一加，B1 会立刻变红。因此同步：

- `board_acceptance_contract.json` 新增 `BA-9-1`「R17 V167 roller 策略加载/切换与 `action_scale` 回读」，`closure_refs=["INCONCLUSIVE_ROLLER_POLICY"]`，并登记进 `required_check_ids`（23 → 24 条）；
- 权威来源说明「6 个悬案」→「7 个」、`signoff.required` 的「5 个 UNVERIFIED」→「6 个」、`not_proof_of` 增加「轮滑 roller 策略已加载或切换」；
- `check_closure.py` selftest 从 17/17 → **24/24**，新增 7 条扫描覆盖/负对照；`tests/test_closure_contract.py` 把硬编码 `"17/17 passed"` 改成解析 `n/n` 且 `n>=17`（项目已因计数硬编码吃过亏）；
- `tests/test_board_acceptance.py` 的 `"total = 23"` 改为从契约实算 —— 这条在本轮全量 pytest 里**真的报红了**，不是预防性改动。

### 1.3 负对照

向临时根注入 `INCONCLUSIVE_GHOST_MARKER` ⇒ `scan_doc_marks()` 检到、`validate()` 判红；去掉该根 ⇒ 恢复绿；白名单不得含 `.workbuddy/memory` / `.upstream`；`--check --ship-gate` 仍 rc=1（`6 UNVERIFIED + 1 CLOSED`）。B5 主文档 §8 与 `deploy_chain_contract.json#scope.known_gaps` 的过时陈述已按「保留史料 + 盖订正指针」处理。

## 2. P0-2：轮滑策略契约（离线结构，不宣布能跑）

新增 `roller_policy_contract.json` + `check_roller_policy.py` + `tests/test_roller_policy.py`，纯新增。契约运行时读取四份真相源并断言一致，**不复制常量作判据**：

| 真相源 | 用途 |
|---|---|
| `line_labels.json#policy.current_line` | 线别（本契约 `line` 必须等于它） |
| `closure_contract.json` | `INCONCLUSIVE_ROLLER_POLICY` 仍在且 `UNVERIFIED` |
| `deploy_chain_contract.json#required.chain_ids` | `L1_CONSOLE_R17_V167` 已注册 |
| 上游 `pretrained_models.json` | 策略目录（`-check --verify-sources` 实算） |

契约内容：`task=Mjlab-Velocity-Flat-MicroDuck-Rollers` / `plant=hd1910_kp8`；共享 `obs61 / act14 / 50Hz / normalizer 烤进图`；roller 专属 4 个被动轮 + 轴承摩擦课程 + `ROLLER_STAND_Z=0.138`；`action_scale` 两来源冲突（0.8 vs SSOT 行365 的 1.0）标 `UNRESOLVED`，**禁止出现 `resolved_action_scale` 字段**；部署链 `R17→V167` 中控，禁用 `uv run publish` 与 `robotctl policy load`（11-06 §6 的 B 代链已由 SSOT⑬ 覆盖）；验收判据为**位移跨度**而非「请求已发」。

🔑 `--verify-sources` 会实算上游 20 条目录：按 `source_kind` + `requires_rollers` 分组重派生两个 id 集合，逐条比对 `sha256` / `size_bytes` / `task_id` / `model_file` / `servos=HD1910` / `hardware_tested=false`。**上游文件缺失或为空判 FAIL，不判 SKIP**（显式要求证据时不许用「没有」冒充通过）。本机实算通过；CI 无 `.upstream` 时 selftest 走「缺失必红」的负对照分支。

⚠️ 目录里有 `kissqy-roller_swizzle`（对称滑行）但**没有普通 `roller` 滑行条目**；11-06 §6 列的 5 个名字属另一来源。契约 `status` 恒 `UNVERIFIED`，`--ship-gate` 必 rc=1。

## 3. C3：B1 → A2 只读证据桥接

新增 `link_evidence.py` + `tests/test_link_evidence.py`。借上游 `replica-kit/docs/open-gaps.md` 的四列表「Gap / Evidence now / Measurement / Closed when」+「Do not freeze before measurements」，把 `board_acceptance.py --record` 的 `COLLECTED` 记录接到 A2：

- **没有第二份映射文件**：`contract_id → check_ids` 只从 `board_acceptance_contract.json#checks[].closure_refs` 派生，selftest 明确断言 `evidence_links.json` 不存在；
- 最终裁决 `import check_closure.overall_verdict()`，A2 仍是「是否闭合」的唯一主人，本工具**永不签字**；
- `COLLECTED != PASS`：即便所有 linked checks 都采证，`awaiting_signoff` 仍为 `true`、报告 `ship_verdict=NOT_SHIPPABLE`；
- 伪造 check id、记录自称 `PASS`、sha 格式错、抹掉 `record_rule` 语义、跨契约引用不存在 ⇒ 全判红；
- `--verify` 实算证据文件 sha256 + 字节数，文件被改/消失必红（漂移检测）；
- **无链接证据如实单列**：`BA-3-2`（ttyS2 存在）的 `closure_refs` 为空，报告放进 `unlinked_evidence`，不硬塞进任何悬案、也不假装闭合。

## 4. B3：CI 分层接入

新增 `ci_meta_targets.py` + `tests/test_ci_meta_targets.py`，修改 `.github/workflows/deploy-gate.yml`（新增 1 个 step + 边界 echo）：

- 名单从 `line_labels.json#tools[line=META_GUARD]` 派生，**AST 遍历所有 import（含函数内 / `import_module(...)` 动态调用）**逐个探测第三方依赖；文件缺失、无 `--selftest`、出现重依赖、目录外路径、重复名 ⇒ `--check` 判红；
- `lean_ci_dependencies` 从 `requirements.txt` **实算派生**（非文字快照），负对照：往临时 requirements 加 `torch`，派生列表必须跟着变；
- `run_all_gates.py` 被显式排除在逐条循环外（它是编排器），其 `--selftest`（只跑注入 CLI fixture）单独一步；`run_all_gates.py --check` **不进 CI**；
- workflow 末尾继续打印 `POST-PUSH ADVISORY CHECK, NOT A MERGE GATE` / `UNVERIFIED != PASS` / 「meta guards 全绿只是离线门禁」。

### 4.1 lean CI 模拟（系统 Python 3.13，无 onnx/torch/mjlab）

`for G in $(python ci_meta_targets.py --names); do python tools/hd1910/$G --selftest; done` + `run_all_gates.py --selftest` ⇒ **9/9 + 编排器全部 rc=0**。这是对「名单真的 stdlib-only」的独立实证，不是只看 AST 报告。

## 5. 自检当场抓到的 5 个真缺陷

| # | 缺陷 | 抓法 |
|---|---|---|
| 1 | `board_acceptance_contract.json` 新增 `BA-9-1` 后，测试里硬编码 `total = 23` 报红 | 全量 pytest；改成从契约实算 |
| 2 | `check_roller_policy.py` 把「两套清单不同源」判据绑在中文措辞子串上，改措辞即假红 | selftest 首跑 23/26；改为结构化 `different_source=true` 正向断言 |
| 3 | `link_evidence.py` 把「伪造 PASS 记录」校验只写在解析函数里，直接测 `validate()` 就漏了 | selftest 15/17；抽出 `validate_records()` 单一函数给两个消费链共用 |
| 4 | 同工具拿 `BA-3-2` 当「证据→悬案」真对照，但它 `closure_refs` 为空 | selftest 同轮报红；改用 `BA-4-2`（→`INCONCLUSIVE_RATE_MISMATCH`），并把 `BA-3-2` 变成「无链接证据如实单列」的新真对照 |
| 5 | `ci_meta_targets.py` 动态导入探测用文本正则，把 selftest 里当样本的 `import_module('numpy')` 字符串算成自己的依赖 | `--check` 直接判红；改为只认 AST `Call` 节点。另在 Windows 下发现 `--names` 输出 CRLF 使 shell 循环拼出 `xxx.py\r` ⇒ 8/9 门禁 rc=2，改为 `sys.stdout.buffer` 纯 LF 并加 CR 负对照 |

## 6. 验收（本机 `.venv-mjlab` / Python 3.12.13）

| 项 | 结果 |
|---|---|
| `run_all_gates.py --check` | **45/45 PASS、NOT_PASS 0、rc=0**；`--list` = 43 个 `--selftest` 工具（原 40 + 本轮 3 个新工具，A3 代码未改靠 `discover()` 自动纳入）；`verdict=ALL_PASS`、`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` |
| 全量 `pytest tests/` | **155 passed in 145.38s，rc=0**（原 141 + 本轮 14；用全新 `--basetemp` 避开本机 safe-delete 钩子） |
| 四个新/改工具 selftest | `check_closure` **24/24**、`check_roller_policy` **27/27**、`link_evidence` **19/19**、`ci_meta_targets` **20/20**；`board_acceptance` 30/30 |
| `--check --ship-gate` | A2 / B1 / P0-2 / C3 全部 **rc=1**（如实红），`UNVERIFIED != PASS` 未被放宽 |
| `check_closure.py --check` | `scan roots = AGENTS.md, README.md, docs, microduck-software/tools/hd1910, out/deliverables`；`doc markers = 7 / contract ids = 7`；`UNVERIFIED 6 / CLOSED 1` |
| `check_roller_policy.py --check --verify-sources` | rc=0，上游 20 条目录实算一致、`verified=True` |
| workflow | PyYAML 解析 OK，17 steps，新 step `Meta guards -- derived stdlib-only list (B3)` 在场 |
| lean CI 模拟 | 系统 Python 3.13 下 9 个 meta guard + 编排器 `--selftest` 全 rc=0 |

## 7. Scope / 已知缺口

- `live_hardware_accessed=false`。本轮**不证明**轮滑版能走、不证明 R17 V167 中控可加载/切换 roller 策略、不证明 4 个 kissqy ONNX 文件已到手或 sha256 已实算（`Microduck-Robotd-FT6-R17.tar.gz` 未下载）、不证明 `action_scale` 真值、不消 `INCONCLUSIVE_RATE_MISMATCH`（R3），5 个原有 `INCONCLUSIVE_*` 仍 `UNVERIFIED`。
- 离线门禁全绿**不替代上板验收**（官方 policy-manifest / kissqy / fanhao / luwu 四源共识）。
- `check_closure.py` 仍是**显式白名单**扫描，不是全仓 rglob；新交付目录必须先登记进 `SCAN_ROOTS`，否则仍可能绕过。
- `line_labels.json` 仍有 **20 个 `--selftest` 工具为 `REPORT_ONLY`**（B4 待办，名单以 `--check --json` 的 `coverage_gap.unlabelled` 为单一权威）。
- `deploy_chain_contract.json#scope.known_gaps` 中「20 个 REPORT_ONLY」等数字仍是文字快照；本轮只订正了「尚未接入 CI」那条并把 `lean_ci_dependencies` 改成派生，其余留 P2。
- 打印包 `10-` §4 的 roller 表述已加订正指针（目录级证据），但装配/打印件数口径不变。

## 8. 下一批（本轮未做）

| 项 | 内容 |
|---|---|
| B7 | 上机当天采集脚本骨架：15 关节 `identify` / `control.43` 回读 / 手柄 mapping / `p8head_2999` 加载 + 5GHz Wi-Fi；带负对照（拔 IMU 必红） |
| B4 | 补 20 个 `REPORT_ONLY` 线别标签，令覆盖差集归零 |
| B6 | 实测 12 个文件含 `L8CX`，其中 `docs/active/microduck-阶段3-自动跟随.md` 与 `docs/archive/microduck-研究报告.md` 完全未盖 L5CX / 作废指针 |
| P2 | 把 4 份契约里的 `known_gaps` 硬编码快照全部改成从 `line_labels.json` / workflow / 契约实算派生 |

**不做**：全套自写镜像/固件（上轮已判「借机制不自写全套」）；训练线 #76 多 seed sweep（用户 11-08「p3暂缓」、约 30 GPU 小时）；把 `UNVERIFIED` 改绿；把 CI 绿勾当 merge gate（GitHub 官方语义：required checks 只对 PR 生效、被 skip 的 job 报 Success）。

## 9. 边界声明

- **采购域零改动**：SSOT `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md`、`build.py`、两份用户手改 xlsx、`.ref/` 生成源一律未碰；阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579`、人人四样边界不变。
- 本轮既有文件均为**定点修改**（`check_closure.py` / `closure_contract.json` / `board_acceptance*.json` / `board_acceptance.py` / `line_labels.json` / `deploy_chain_contract.json` / `test_closure_contract.py` / `test_board_acceptance.py` / B5 主文档 / `.github/workflows/deploy-gate.yml`），其余为纯新增；打印包在 gitignored 的 `out/` 内操作。
- 用户手改 xlsx **禁止覆盖重建**（准则 8）：本轮未生成、未重跑任何采购表构建脚本。
