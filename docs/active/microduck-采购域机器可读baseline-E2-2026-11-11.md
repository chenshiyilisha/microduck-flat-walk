# E2：采购域机器可读 baseline（把"零改动"从人工声明升级为机器断言）（2026-11-11）

> 授权：用户 2026-11-11「可以做，按照最优的来」——解除了《多视角自查》§4 当初「需用户拍板、不自作主张纳入门禁」的第一条顾虑。第二条顾虑（baseline 只能证明相对时点、不能追溯历史）**未被消除、被写进契约的 `not_proof_of` 如实保留**。
> 边界：本工具**不碰采购域本体**（两份手改 xlsx / 两份 build.py / p25.tmp / SSOT 全程零改动、仍不入库），只新增一个入库的**契约 + 只读检查器**。`ship_verdict` 恒 `NOT_SHIPPABLE`、`live_hardware_accessed=false`；不验硬件、不消任何 A2 悬案、不碰 D1 决议、不作签收。

## 0. 它到底解决什么

《多视角自查-pytest与CI与数字与采购域》§4 已钉死：**"采购域零改动"此前只是 `stat` mtime + 暂存区 grep 的人工声明，三侧全缺机器证据**（`git ls-files` 采购域 = 0；无 baseline/哈希清单；CI 对 `xlsx|采购|procure|.ref` 零命中）。本轮把这句断言升级为可 diff、可 CI 回归、可本机真校验的机器契约。

**为什么不能照搬 C4/D1 直接进 CI**：采购域 6 个文件全部 git 未跟踪且未被 ignore（`git check-ignore` 零输出），GitHub 干净 checkout 上**根本没有这些文件**。若把真文件 `--check` 塞进 CI，结果必然是缺失 → 要么假绿要么假红，两者都错。故本工具**双入口分流**（见 §3）。

## 1. 三层正交（各管一件事，不互相重复）

| 门禁 | 管什么 | 状态词 |
|---|---|---|
| A2 `closure_contract.json` | 尚无一手上板证据的悬案 | `INCONCLUSIVE_*`（UNVERIFIED ≠ PASS） |
| D1 `decision_contract.json` | 已评估并主动决定不做/暂缓/撤销 | `DEFERRED/REJECTED/WITHDRAWN ≠ PENDING` |
| **E2 `procurement_baseline.json`** | **未跟踪工作副本相对 baseline 时点是否被静默改动** | **四态（见 §2）** |

状态词体系刻意不复用：A2 管"证据没闭合"，D1 管"决议已拍板"，E2 管"字节/口径被动过"。三者正交，一个事项从一种状态转到另一种应显式迁移，不留双主人。

## 2. 四态结论（绝不二值化）

| verdict | 触发 | 退出码 | 语义 |
|---|---|---|---|
| `BASELINE_MATCH` | 6 文件 hash+size 全中 **且** 7 个语义锚点全成立 | 0 | 相对 `recorded_at` 时点未变 |
| `DRIFT_UNCONFIRMED` | 字节变了但语义锚点全在 | 1 | **疑似合法手改**（勾选☑/另存/换行），不冒绿、也不判红，需人工 diff + 显式 re-baseline |
| `COVERAGE_SUSPECT` | 任一语义锚点破裂 / 文件损坏 / 跨文件不变量分叉 | 1 | **疑似 build.py 覆盖事故或口径漂移**，判红 |
| `UNVERIFIED` | 登记文件缺失（CI 干净 checkout / 工作副本未同步） | 1 | 如实报缺失，**不 PASS、也不算漂移** |

`DRIFT_UNCONFIRMED` 这一态是整个设计的枢纽：**纯 sha256 清单无法区分"用户合法手改"与"重跑 build.py 覆盖"**——两者都改 hash。若二值化，合法手改会被误报成"篡改"（违反准则 8：手改不得被当错），久而久之门禁被当成噪音关掉。四态让"字节动了"停在"需人工确认"，只有语义锚点（真正承载口径的东西）破了才判红。

## 3. 双入口分流

- **`--selftest`（进 lean CI）**：注入临时 inlineStr xlsx + **11 条真负对照**，纯 stdlib，不读真实采购文件。经 `line_labels.json#tools[line=META_GUARD]` → `ci_meta_targets.py` AST 依赖探测（无第三方 import）→ 派生进 `deploy-gate.yml` 的 meta guards 循环。验的是"工具逻辑没坏"，不是"采购文件没变"。
- **`--check`（只本机跑）**：真读 6 个未跟踪文件 + 从 xlsx 实抽语义锚点。CI 上若被调，因文件缺失诚实返回 `UNVERIFIED`（RC=1，不误绿）。
- **`--rebaseline --confirm --reason`（显式、可审计）**：用户逐行复核合法手改后才执行。旧 hash+size+当时 verdict 写进 `baseline.history[]`；**工具只写契约 JSON，永不写一个采购文件**；若在 `COVERAGE_SUSPECT` 状态下强行 re-baseline，history 记 `anchor_broken_accepted=true` + 警告，不静默洗白。无 `--confirm`/`--reason` 一律 RC=2 拒绝（已实测）。

## 4. 两层判据：hash + 语义锚点

**字节层**：6 文件 `sha256 + size_bytes`。采集于本机 2026-11-11 16:40 的磁盘态（即用户 2026-11-10 手删 3 行 + 订正㉕ 补 3 行后的 19 行权威态）。

**语义层**：用纯 stdlib（`zipfile` + `xml.etree`）解析 xlsx（这些文件全是 `inlineStr`，无 `sharedStrings.xml`，零 openpyxl 依赖），实抽 7 个锚点：

| 锚点 | 判据 | 防的风险 |
|---|---|---|
| `A_BUY_MATERIAL_ROWS` | 照着买 sheet 物料行 = **19** | 退回 16 = 手删 3 行被 build.py 写回（准则 8 事故） |
| `A_BUY_HAND_DELETED_ABSENT` | 电源/万用表/转接线**未作为独立物料行**复活 | 恢复用户手删项 |
| `A_BUY_SKU_25` | HUB 取电/金属件/Radxa1GB/ToF/摄像头 SKU 仍在 | 订正㉕ 主线定案被抹 |
| `A_BUY_BUDGET` | `阶段与现状` 含 `2,500` 与 `2,579` | 整机预算区间被改 |
| `A_BOM_SHEETS` / `A_BOM_VERDICT` | BOM 表 5 sheet + §16 判决/电池订正仍在 | 整合表结构/判决丢失 |
| `A_SSOT_CORRECTIONS` | SSOT 顶部判决表 + 订正㉕ 标记在 | SSOT 被绕开改判 |

跨文件不变量 `X_TMP_EQUALS_BUY`：`p25.tmp` 与 `照着买主表` 当前字节相同（`bd092c19…`），二者若分叉提示人工确认（tmp 本就是历史快照，不自动判红）。

## 5. 🔴 本轮真跑抓修的自身缺陷（自指证据）

按"验证工具自身也要负对照、先问量动没动"的纪律，第一次真跑 `--check` 得到 `COVERAGE_SUSPECT` 假红，逐层回一手定位，抓出 **1 个工具真 bug + 4 个测试/契约自身 bug**，全部修掉：

1. **准则 10 同型命中（第 N 次）**：`A_BUY_HAND_DELETED_ABSENT` 用整行裸子串 `"转接线"` 判"手删行复活"，命中了真实表**第 17 行合法物料**「扬声器 3525腔体 4Ω3W（kissqy 同源）+ **配套转接线**」→ 假红。手删的是**独立采购行**「转接线 2.0→2.5 3P」（URT-2 自带），与"扬声器配套转接线"是两回事。修法不是加 exclude 词打补丁，而是把判据升级为 **`absent_as_material_subject`：只看 D 列物料主体是否以禁词开头**（独立转接线行命中、扬声器行不命中），且不依赖具体规格字符。负对照专门证明"退回顾整行裸子串必误红"（证明主体判据非冗余）。
2. **`read_xlsx` 列宽 bug**：`width = max(len(k) for k in cells)` 算的是列字母串长度（恒 1），每行只读回 A 列。`selftest` 首跑直接崩，暴露之。改为 `_col_index(k)`。
3. **fixture 列引用 bug**：造临时 xlsx 时 `ref = _col_names(j+1)[0]` 恒取 `'A'`，所有单元格塌到 A 列。改 `[-1]`。
4. **`check()` 汇总漏 file-level SUSPECT**：损坏 xlsx 的单文件 state 被设 `SUSPECT`，但汇总只看 anchor/missing/dirty → 损坏文件可能假绿 `BASELINE_MATCH`。补 `suspect_files` 升级路径，并加"损坏 xlsx 即使 hash 匹配也必须判红"负对照。
5. **测试传参错误导致的假阳性**：两处 `_inject` 误传 `{"照着买": rows}`（应为行列表），写出 1 行 sheet；其中"build.py 覆盖"用例**碰巧仍判红而假通过**——原因根本不是覆盖故障（正是"要问量动没动，不是结果对不对"）。改成传行列表，并锚定真实原因（行数 < 19 + 复活线），不再只断言 verdict。

修完后：`--selftest` **31/31**、新 pytest **11 passed**、真实 `--check` = **`BASELINE_MATCH`（RC=0）**，6 文件 hash 全中、7 锚点全绿。

## 6. 验收

| 项 | 结果 |
|---|---|
| `--selftest`（含 11 负对照） | **31/31 passed**，RC=0 |
| 新 `tests/test_procurement_baseline.py` | **11 passed**（CLI 真跑 + 四态 + 准则10 实证 + 损坏 xlsx + 契约篡改） |
| 全量 `pytest tests/`（默认 basetemp） | **208 passed**（原 197 + 新 11），RC=0 |
| `run_all_gates --check` | **50/50 ALL_PASS**（49→50），`ship_verdict=NOT_SHIPPABLE`，unlabelled=0 |
| 本机真实 `--check` | **`BASELINE_MATCH`**，6 文件 hash/size 全中、7 锚点全绿、跨文件不变量成立、RC=0 |
| CI 干净 checkout 形态（`--check --root 空目录`） | `UNVERIFIED`、RC=1，不误绿 |
| `--rebaseline` 门禁 | 无 `--confirm` 或 `--reason` 均 RC=2 拒绝；契约 `recorded_at` 与采购文件 mtime 不变 |
| meta-guard 派生 | `ci_meta_targets.py --check` = PASS，16 个 META_GUARD（含本工具），AST 判 stdlib-only |
| 采购域 | **零改动**：6 文件 hash 与 11-10/11-09 基线一致，mtime 仍 `11-10 17:43` / `11-10 10:38` / `11-10 17:36`；暂存区 `??` 未入库 |

## 7. 诚实边界与未闭合

- **只证明相对 2026-11-11T16:40+08:00 时点未变**，无法追溯证明"过去从未被改"（与 bundle provenance 同型）。这是 baseline 的固有上限，写进契约 `not_proof_of`，不冒充。
- **不验证采购内容正确性**：价格是否实时结算价、链接/库存是否有效、SKU 是否买对，一概不判（那是采购实务，不是信息一致性门禁）。
- **不自动 re-baseline**：合法手改后必须人工逐行复核 + 显式 `--rebaseline --confirm --reason`；否则 `DRIFT_UNCONFIRMED` 一直挂起，不自动洗绿。
- **CI 上真文件校验仍不可能**：采购域按用户约定不入库；CI 只回归工具逻辑，真一致性只能本机 `--check`。这是"不入库"边界的必然代价，如实标注，不假装 CI 覆盖了采购文件。
- 与 §4 原结论的关系：原「三侧全缺」中的「无 baseline/哈希清单」这一侧**已闭合**（本契约即为）；另两侧（采购域未入库、CI 不含采购文件）**按边界保持不变**，不因本工具而假装改变。

## 8. 改动面与提交

- 纯新增：`tools/hd1910/check_procurement_baseline.py`、`tools/hd1910/procurement_baseline.json`、`tests/test_procurement_baseline.py`、本文档。
- 修改：`line_labels.json`（`META_GUARD` 登记 + evidence）、《多视角自查》§4 加"已由 E2 闭合一侧"指针（防 D1 型口径漂移）。
- **采购域本体零改动、不入库**；不改 CI YAML（本工具经 `ci_meta_targets` 派生名单自动进入 meta-guard 循环，无需手写步骤，避免名单腐化）。
