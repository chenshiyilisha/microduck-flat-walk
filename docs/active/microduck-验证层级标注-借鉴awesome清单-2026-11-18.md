# 借鉴 awesome-microduck：把 Sim-only 纪律收敛进单一权威

_2026-11-18。`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false`、`UNVERIFIED != PASS` 全部不变。本轮只改门禁形式，不翻任何状态。_

## 来源与定性（准则 11）

一手核验过 `joeynyc/awesome-microduck`（GitHub API：仓库真实、CC0、219★、创建 2026-08-30、push 2026-11-17）。

- **它不是技术源，是社区第三方清单**，非官方、未经 Pollen/HF 背书。唯一官方仍是 `pollen-robotics/microduck`。
- 清单里 straight 引用了一手上游红线：官方 policy-manifest 的「Absent fields are not evidence」「eval 字段记录 what was checked / in what sim」；Ecosystem Status 明写「硬件类工具多为 pre-validation，没有在零售真机跑过」；条目普遍标 `*Sim-only.*`。
- 本文借的是它的**治理机制**，不是条目内容、不是实现。

## 裁决：借什么、不借什么

| 候选 | 裁决 | 理由 |
|---|---|---|
| README 单一权威 → 脚本生成 `policies.json` → CI 校 schema/漂移 | **不借注册表本体** | 项目已有 `closure_contract.json` + `line_labels.json` + `run_all_gates.py` 三契约同源、漂移即红，等价机制已在，再造 `policies.json` 就是第二权威 |
| `revocations.json` 撤销表（id/日期/原因/替代/公告，执行前拦停） | **登记为未来项，本轮不落地** | 项目当前无对外分发的策略/功能注册表，撤销表无对象；等发布链真正存在再抄 |
| `*Sim-only.*` + pre-validation 标注 | **借，且做进机器判据** | 这是唯一能补现有体系真实缺口的：`local_verified` 是自由文本，把源码/离线/仿真/Mock/SBC/整机混在一句话里，机器分不出验证强度 |

## 落地内容（单一权威：`closure_contract.json`）

新增 `verification_tiers` 词汇表 + 每条契约两个字段：

- `verification_tier`：该条**证据实际到达**的最高层级（不是目标层级）。
  6 级由弱到强：`SOURCE_ONLY` / `OFFLINE` / `SIM` / `MOCK` / `SBC_LIVE` / `HARDWARE_FULL`。
- `verification_tier_note`：自由文本理由，绑定本条 `local_verified` 的具体内容，供人核对。

本轮逐条实标结果（按现有证据内容指派，未新做任何实验）：

| 层级 | 条数 | 契约 |
|---|---|---|
| `SOURCE_ONLY` | 3 | DIMENSION / CURRENT / PRICE(CLOSED) |
| `OFFLINE` | 4 | LIVE_IDENTIFY / RATE_MISMATCH / LR_LABEL / ROLLER_POLICY |
| `SIM` | 2 | LIVE_TRACKING / LIVE_STATE_STREAM |
| `HARDWARE_FULL` | 0 | —（最高只到 SIM） |

### 承重判据（写进 `check_closure.py:validate_tiers()`）

1. 每条 `verification_tier` 必须是词汇表声明的层级名；词汇表必须存在、`schema_version=1`、`ordered_weak_to_strong` 与 `levels` 集合严格相等、`not_equivalent` 必须含 `COLLECTED != PASS`。
2. `verification_tier_note` 非空，否则无法审计。
3. **`scope.live_hardware_accessed=false` 时，任何契约标 `HARDWARE_FULL` 即红**——这是把「仿真/Mock/源码/离线不等于整机」从文档口号变成会变红的检查，防止只改一个字段就把证据洗成整机验收。
4. `status ∈ {UNVERIFIED, FAIL}` 却标 `HARDWARE_FULL` 即红。
5. 互补正对照：`live_hardware_accessed=true` 时，CLOSED 且有 evidence 的契约标 `HARDWARE_FULL` 不被层级判据拒绝——证明判据绑的是 `scope` 字段，不是「见到 HARDWARE_FULL 就一律红」。

`check_closure.py --check` 的报告新增 `verification_tier_counts` / `verification_tier_vocabulary` / `highest_tier_reached`，门禁结论里直接可见「最高只到 SIM」。

## 验证（含环境限制，如实记录）

| 检查 | 结果 |
|---|---|
| `check_closure.py --check` | rc=0，structure PASS，`tiers={OFFLINE:4, SOURCE_ONLY:3, SIM:2}`、`highest=SIM`、`ship_verdict=NOT_SHIPPABLE` |
| `check_closure.py --selftest` | **42/42**（原 31 + 新增 11，含 8 负对照 + 2 正对照 + 1 词汇表检查） |
| `line_contract.py --check` | PASS，labelled tools 52，coverage gap 0 |
| `check_contract_status.py --check` | PASS，unlabelled 0，lean CI meta guards 17 |
| `link_evidence` / `board_acceptance` / `check_decisions` / `check_roller_policy` / `check_procurement_baseline` 的 `--selftest` | 全 rc=0，PASS（30/30、31/31、27/27 等） |
| 全量判定逻辑直调 | discover 49 工具 + 2 meta = 51 项；构造全 PASS → `ALL_PASS`，任一 FAIL → `FAILED`；`42/42` 经 classify → PASS、无 ratio mismatch |
| 🔴 `run_all_gates.py --check` 真跑 / `pytest tests/test_hd1910_tooling.py` | **本次被环境安全策略 SIGTERM 拦截（无具体资源、未返回失败输出），不是测试红**；未重试同类命令，改用上列逐项 CLI + 直调 classifier/report 覆盖，未宣称「全量真跑通过」 |

`run_all_gates.py:347` 的 `selftest: 31/31 passed` 是 classifier 自身的正对照**字符串样本**（测 N==M 不误红），与本工具真实输出数量无关；`42/42` 走通用 `VERDICT_RATIO` 正则，不需改那行。

## 边界

- 未改任何 status / evidence / signoff / `scope.live_hardware_accessed` / `ship_verdict`；未新增 INCONCLUSIVE 标记（9 markers == 9 contract ids 仍相等）。
- 未碰采购 SSOT / xlsx、未改镜像、未下单、未对板子做任何写操作。
- 本轮新增字段是**描述性证据层级**，不是新的验收动作；不会因「标了 SIM」而更接近 PASS。
- 撤销表仍为未来项：没有对外分发的注册表就没有撤销对象，不为了「抄全」而制造空机制。
