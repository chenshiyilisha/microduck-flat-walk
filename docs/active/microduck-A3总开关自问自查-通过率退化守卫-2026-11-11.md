# A3 总开关「自问自查」：给门禁检查者本身加通过率退化守卫

_日期：2026-11-11。范围：离线门禁编排器 `run_all_gates.py` 自身的可信度审计与补强。不验证硬件、不作实机签收、不消任何悬案。采购域零改动。_

## 0. 为什么这一轮不「往外加门禁」，而是审检查者

前几轮（C4 流解析 parity、D1 工程决议台账）都是「又发现一个缺口 → 加一个门禁」。本轮用户要求「自问自查」，所以换个问法：**49/49 全绿，到底是真的在测，还是有没有一个门禁是假绿？**

本项目最惨痛的历史教训全是「检查者自己瞎了」而非被测代码错：

- 「50 个测试全绿，但 CI 那条 `--selftest` 命令 argparse rc=2」；
- 「只测内部函数不测 CLI 入口 = 假象」；
- 「自检必须有负对照：改坏必红，只见过绿色的断言不是证据」；
- 「裸子串匹配被反义复合词反噬」（准则 10）。

A3 `run_all_gates.py` 是**所有门禁的总开关**——它的 `classify()` 决定 49 个 stage 谁算 PASS。审视它本身，是「查全」的应有之义。

## 1. 查全：47 个工具真跑，33 个的结论行总开关根本读不懂

真跑全部 47 个 `--selftest` 工具，抓每个的末行结论，喂给 `conclusion_marker()` / `classify()`，两独立算法（AST 静态 + 真跑 rc）交叉印证：

| 观测量 | 读数 |
|---|---|
| 带 `--selftest` 的工具总数 | 47 |
| `classify()` 解析出**标准状态词** marker 的 | 14 |
| marker 为空、**完全靠 rc 兜底**的 | **33 / 47（70%）** |
| 结论行格式种类 | ≥ 9 种 |

33 个 rc-only 工具的末行实测样本（非穷举）：

```
selftest: ALL PASS          /  selftest passed          /  selftest: all green
15 checks, all consistent   /  全部通过                 /  SELFTEST OK (negative control is mandatory)
30/30 passed                /  39/39 passed            /  25/25 自检通过
scope: read-only capture plan; ...   ← 末行是 scope 声明，压根没有结论词
```

**AST 查全的一处自我纠偏**：初版 AST 只扫 `selftest()` 函数体，报「25 个工具无拦红守卫」。这是**读数错**——静态 main 退出链 + 真跑 rc 两来源交叉后确认，这 25 个都在 `main()` 里 `return 1 if bad else 0` / `return rc` 正确拦红。没有把它们误判成缺口，避免了一次「查一个源就下结论」。

## 2. 决定性 blind spot：总开关对「通过率退化」一概绿灯

对 `classify()` 直接喂构造输出（rc 固定为 0）：

| 喂进去的输出 | marker | `classify()` 判决 |
|---|---|---|
| `selftest: 1/5 passed` | 空 | **PASS** ❌ |
| `selftest: 0/9 passed` | 空 | **PASS** ❌ |
| `selftest: 0/0 passed` | 空 | **PASS** ❌ |
| `nothing happened, exiting clean` | 空 | **PASS** ❌ |
| `G4 ... FAIL ... \nSELFTEST OK (...)` | 空 | **PASS** ⚠️（FAIL 是故意的负对照，恰好没在结论位） |
| `selftest: FAIL` | FAIL | FAIL ✓ |
| `self-test: PARTIAL` | PARTIAL | SUSPECT_SKIP ✓ |

根因：`VERDICT_LINE` 只认 `self-test|selftest|verdict|status` **后跟固定状态词**的结论行；上面这些格式 marker 恒空，而 `classify()` 的兜底是「rc=0 且无 skip 标记 → PASS」。

**结论**：`49/49 全绿` 的可信度，此前 100% 压在 47 个子工具各自 `main()` 里那一行 `return 1 if bad` 的**自觉**上。只要任何一个工具未来退化成「内部有 FAIL、却忘了 return 非 0」，或结论行从 `N/N` 漂成 `1/N`，总开关会照样盖章 PASS——**这正是「测试全绿、CLI 假绿」在编排器层的同型，只不过此前一直靠子工具纪律兜着，总开关自己没有独立判据。**

## 3. 反面教材：宽松判据会误伤 6 个真工具（准则 10  again）

最自然的修法是「见到 `N/M` 且 `N≠M` 就红」。我先用宽松正则 `(\d+)/(\d+)` 对 47 个真实工具的**全量输出**做误伤扫描，**6 / 47 中招**：

| 工具 | 被误抓的 `N/M` | 真实语义（不是通过率） |
|---|---|---|
| `audit_robotd_toml` | `50/200 is 0.25x`、`50/8 is 6.25x` | 比值计算 |
| `check_roller_policy` | `0.8 / 1.0` | 来源值对照 |
| `verify_pack` | `26/28 checks passed (2 FAIL)` | **故意的负对照样例** |
| `calibrate_offsets` | `只读到 3/15 → 拒绝写入` | **故意的失败路径测试** |
| `probe_bandwidth` | `100/107/100 °/s` | 角速度 |
| `probe_ch343_baud` | `N2b 10/20 应答 -> FLAKY` | **故意的 flaky 负对照** |

**用错判据的门禁比没有门禁更糟**：直接改会让 49/49 瞬间假红，且其中好几条正是别的工具辛苦写的负对照。这与 D1 抓到的「reasoning 子代理把已判不搬的事项重挖成缺口」同型——**查全不够就下结论**。

## 4. 落地：收窄判据 + 三层 fail-safe

### 4.1 收窄后的 `verdict_ratio_mismatch()`

只认**结论行形态**、且整行**不含反义上下文**：

```python
VERDICT_RATIO = re.compile(
    r"^\s*(?:self-?test|selftest|verdict|status|全部|共)?\s*[:：]?\s*"
    r"(\d+)\s*/\s*(\d+)\s*(?:checks?\s*)?"
    r"(?:passed|pass|ok|green|通过|自检通过)\b", re.I)
RATIO_ANTONYM = re.compile(
    r"FAIL|拒绝|FLAKY|负对照|期望|must|refus|is\s*\d|应答|折", re.I)
```

- 锚定**行首**结论形态（`^\s*` + 可选状态前缀），不裸扫子串 → 比值/角速度/来源值不匹配；
- 整行命中 `RATIO_ANTONYM` 直接跳过 → 负对照样例、拒绝路径、FLAKY 行不匹配；
- 只有 `total>0 且 got!=total` 才返回 `(got, total, line)`。

**验证**：47 个真实工具真跑全量输出 → 误伤 **0 / 47**；5 个 `N≠M` 合成负对照（`1/5`、`0/9`、`14/15`、`8/10`、`26/28`）**全抓**；6 个反义上下文**全跳过**；`N==M` 与 9 种 rc-only 结论行**全不红**。

### 4.2 三层 fail-safe（互补，主防线不变）

1. **rc≠0 → FAIL**（原有，主防线）；
2. **显式 `FAIL`/`PARTIAL`/`SKIP` 结论行**（原有）；
3. **通过率退化 `N/M, N≠M` → SUSPECT_SKIP**（本轮新增，独立于子工具 rc）。

层级顺序：显式状态词优先于 ratio；rc 仍是第一道。新守卫只补「rc=0 + 无标准词 + 结论却写着 `1/5`」这个此前的真空。

### 4.3 端到端证明（不是只测内部函数）

`fake_tools()` 注入一个 `print('selftest: 1/5 passed')` 且 **rc=0**（模拟 `main()` 忘了 return 非 0）的真 CLI 进程，`--check` 必须转 `FAILED`；把它换成 `5/5` 又转回 `ALL_PASS`。这条负对照证明守卫**接进了真实编排器**，不是纸面断言。

## 5. 真跑抓修的第二个自伤：测试里的裸正则被自己的负对照反噬

新 selftest 会打印断言名 `退化结论 1/5 passed 必红`（故意的负对照字面量）。既有 `tests/test_run_all_gates.py::test_cli_selftest_and_list_really_run` 用裸 `re.search(r"(\d+)/(\d+) passed")` 全文搜输出，**把这个字面量当成真结论**、`1≠5` → 假红。这与上一轮 CI 假红（文档写了负对照字面量被 A2 扫到）**完全同型、第二次复发**。

修法与 A3 判据同源：测试锚定工具**自己的结论行** `^run_all_gates selftest:\s*(\d+)/(\d+) passed`，不再裸取第一个分数。教训固化：**凡是会打印负对照字面量的输出，任何下游解析都必须锚定结论位，不能全文裸搜。**

## 6. 验收（全部真跑）

| 项 | 结果 |
|---|---|
| `run_all_gates.py --selftest` | **34 / 34**（原 20 + 新 14 条 ratio 正/负/反义/端到端对照） |
| 新回归测试 `tests/test_run_all_gates.py` | **7 passed**（原 5 + 新 2，含端到端 CLI 负对照） |
| 全量 `--check`（49 个真实工具） | **49 / 49 ALL_PASS**、零 BAD、零误伤、`unlabelled=0` |
| `line_contract.py --check` | coverage gap = **0**、verdict = PASS |
| `ci_meta_targets.py --check` | structure_verdict = PASS（本轮未改登记/依赖面） |
| 全量 `pytest tests/` | **192 passed in 185.21s**（原 190 + 新 2），rc=0 |

## 7. 与既有机制的正交关系

| 机制 | 管什么 | 本轮是否改动 |
|---|---|---|
| A2 `closure_contract` | `INCONCLUSIVE_*` 悬案证据闭合 | 否 |
| D1 `decision_contract` | `DEFERRED/REJECTED/WITHDRAWN` 主动决议唯一主人 | 否 |
| C4 `check_stream_parity` | SCS 脏流双实现逐字节同解 | 否 |
| **A3 `run_all_gates.classify`** | **门禁总开关如何判 PASS** | **本轮：补第 3 层通过率守卫** |

本轮**没有新增工具、没有新增登记**、没有契约 JSON 变更——只改 `run_all_gates.py` + 其测试两处，A3 编排器自身的代码补强。

## 8. 边界（如实）

- 离线全绿时 `verdict=ALL_PASS`（仅「所有门禁跑完且无 skip 标记」），但 `ship_verdict` 恒 `NOT_SHIPPABLE`、`live_hardware_accessed=false`——**`ALL_PASS ≠ 可签收`**；
- 本守卫**只证明**「总开关能识别结论行里的通过率退化」，**不证明**任何子工具的断言内容正确、不证明被测代码正确、不证明总线/IMU/策略/整机任何一件事；
- **不消 R3、不消任何 A2 悬案、不碰任何 D1 决议、不作实机签收**；
- 反义上下文的行**依赖各子工具自身 rc 兜底**（本轮不越过那个边界），因此三层 fail-safe 是「互补」而非「总开关全包」。

## 9. 采购域零改动声明

SSOT、`build.py`、两份手改 xlsx、`.ref/`、`.bak_before`、`.p25.tmp.xlsx` 全程未碰；采购域 xlsx mtime 仍为 11-09 / 11-10 基线；暂存区采购域负对照 = `NONE`。本轮改动精确为 2 个文件：`tools/hd1910/run_all_gates.py`、`tests/test_run_all_gates.py`（+ 本文档）。
