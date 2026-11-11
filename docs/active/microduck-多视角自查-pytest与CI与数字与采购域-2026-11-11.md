# 多视角自查：pytest 套件 / CI YAML / 数字漂移 / 采购域证据（2026-11-11）

> 状态：**离线自查 + 一处真缺口修复**。前几轮分别审过 parity 手法（C4）、文档决议口径（D1）、门禁分类器（A3）。本轮换**从未审过的四个视角**，全部只读诊断先行、一手复核后才动手。
> 本轮是**自查 + 测试/文档卫生**，不新增门禁工具，故**没有工具 verdict 字段**；沿用的门禁体系 `ship_verdict` 恒 `NOT_SHIPPABLE`、`live_hardware_accessed=false`。**不验硬件、不消悬案、不作签收、采购域零改动。**

## 0. 本轮问法（与前几轮正交）

前几轮的隐含问题是"还能加什么门禁 / 检查者本身瞎没瞎"。本轮换问：**"我一直报的那几个绿色数字——192 passed、CI success、49/49、采购域零改动——自身可不可信？"** 四个从没被审过的对象：

1. CI 第 3 步跑的 `pytest tests/` 套件本身（192 passed 有没有假绿）
2. CI 的 `deploy-gate.yml` 这份 YAML 本身（有没有静默放行 / allow-skip 吞失败）
3. 文档声称的数字 vs 代码/契约实况（49/49、192、3 ONNX 有没有漂移）
4. "采购域零改动"这句每轮都写的断言（有没有机器证据）

做法：两个独立只读探查代理分头查全（pytest 视角 / CI+契约+数字视角），**我逐条回一手源码复核关键结论**，不只读代理一行就动手。

## 1. 视角一：pytest 套件（7 类假绿模式）

| 模式 | 判定 | 一手证据 |
|---|---|---|
| skip / xfail / skipif | **脆、诚实、非当下假绿** | `test_hd1910_configs.py:98` 模块级 `skipif(not _MJLAB_OK)` 在 lean 环境整文件 25 例 skip；`test_hd1910_viewer_mesh.py:60/189` 无 mesh / 无 matplotlib 诚实 skip。全部带 reason、CI 用 `-rs` 打印、多数资产已 `git add -f` 跟踪；完整栈 skip≈0。pytest 层无门禁把 skip 判红（工具层 `assert_ci_verdict.py` 有 SUSPECT_SKIP）——**口径落差，非假绿** |
| **只测内部不测 CLI 入口** | **🔴 机制级、当下正假绿** | **`live_viewer.py`（8 个 argparse 参数 + `__main__`）是全仓唯一既无 `--selftest`、也无任何 CLI 真跑测试的可执行入口**；49 个门禁工具逐个有 CLI 子进程测试，唯独它只被 `test_hd1910_viewer_mesh.py:44` 用 `importlib` 加载内部函数。离线实证：删 `--interval-ms` 的 `type=int` → `--interval-ms notanint` 从 rc=2 变 **rc=0**，程序照常往下走，**192 passed 一根不红** |
| 空 / 恒真断言 | **部分（死噪音）** | `test_deploy_chain.py:33` `assert "31/31" not in out or "passed" in out` 对任意串恒真（真值表已证），被相邻真校验兜底 → 死断言；`test_hd1910_viewer_mesh.py:201-203` 退化圆柱分支无 assert |
| mock / patch 掉被测对象 | **干净** | 全 tests/ 零 `MagicMock`/`patch` 命中；两处 `pc._stage=` / `monkeypatch.setattr(...,SOFTWARE,tmp_path)` 是测真实聚合/发现逻辑的正对照 |
| 测试间状态依赖 | **脆、未构造换序失败** | `rh._STATE[...]` 改全局字典无还原，但每个用它的测试开头显式重设，当下换序自洽（标"推的"，未实测换序） |
| 参数化只覆盖正例 | **干净** | `test_stream_parity`/`test_run_all_gates`/`test_deploy_chain` 等大量 tamper/corrupt 负对照，且断到具体状态词，比"只断言非0"更强 |
| 192 读数构成 | **读数真实** | AST 静态展开 = **192**；`pytest --collect-only` 实测 = **192 collected**；测试根零 `conftest`/`pytest.ini`/`addopts`/`--ignore`，无过滤注水。`.pytest_cache/nodeids=199` 是过期缓存（非当前收集） |

**192 passed 的可信度此前压在三件它自己管不到的事上**：①用对解释器（`.venv-mjlab` 完整栈，lean CI 会让 configs 25 例 + mesh 一批变 skip，故 CI 实际 passed < 192）；②49 个工具逐个有 CLI 真跑 + 命令自带负对照 selftest；③**"被覆盖的入口集合完整"——而这一条正好有个洞：`live_viewer.py` 逃逸**。

## 2. 视角二：CI YAML（7 项）

| 项 | 判定 | 一手证据 |
|---|---|---|
| 静默放行信号 | **如实的** | 全文件无 `continue-on-error`/`\|\| true`/`2>/dev/null`/`exit 0`/`set +e`/`if:always()`；关键步骤显式 `set -e`（`:138`、`:177`）。2 处 mutable tag（`@v4/@v5`）属常规 |
| `steps.*.outputs` 真门禁还是 echo | **如实的（信息非门禁，但如实声明）** | `scope_gate`/`full_gate`/`workflow_discoverable` 仅在 `:197-199` 三行 echo，无下游 `if:` 消费。真门禁是 readiness 步骤 exit code（`assert_clean_checkout.py:462-465` 只卡 `scope_gate`）。POST-PUSH ADVISORY 边界写在 `:43-61`、`:195-203`，未把 echo 冒充门禁 |
| `--allow-skip contract` 吞不吞真失败 | **如实的（机器负对照实测不吞）** | `deploy_stages.py:154-171` 非 allow 的 FAIL/SKIP 进 offenders；`assert_ci_verdict.py:97-101/130-136` 禁 waive MUST_PASS inference、未列名 SKIP 判红。实测 `contract SKIP + numeric/bundle/inference FAIL`、`toml 未列名 SKIP` 四种全 RED，仅单独 `contract SKIP` GREEN |
| workflow 存在性自保 | **如实的（CI+本地双挂）** | CI `:90-93/96-97`；本地 `test_hd1910_tooling.py:965-982/998-1037` 钉住根位置+删了必红。文档如实承认"CI 无法自保自身不存在、靠本地 pytest 兜底" |
| 数字漂移 | **docs 如实、唯一漂移在 run_all_gates.py 自述** | 实况 bundle=4 artifacts（3 ONNX+1 toml）、`POLICY_KEYS`=3、`FULL_STAGES`=5、`--list`=47+2meta=49、`--collect-only`=192。文档链 `48/48→49/49→49/49`、`181→190→192` 均带 2026-11-11 日期口径、与当前自洽；**`run_all_gates.py:6 "33 tools"` / `:38 "28/38..38/38"` 与同文件 `:82 "47 real tools"` 自相矛盾**（见 §4 卫生 B） |
| 依赖供应链 | **脆，不作改动** | `requirements.txt:66-69` 用 `>=`、无精确 pin/哈希/lock，注释 `:22 "pins"` 与实际 `>=` 措辞漂移。CI 每次拉当日满足下限的最新集合 → "今天绿明天可能漂"的真实风险。**本轮只报不改**（改 pin 影响 CI 行为、需单独决策，且用户诉求是自查） |
| 采购域机器证据 | **脆、无（见视角四）** | — |

**CI success 的可信度压在**：GitHub 默认 shell `-e -o pipefail`（平台默认，仓库无一手明标，属"推的"，仅两处显式 `set -e` 兜底）+ 每工具 `main()` 自觉 return 非0 + `assert_ci_verdict.py` 从 stages 重导 verdict 的独立判据 + 数字动态发现（`discover()`/`--collect-only`）。

## 3. 视角三：数字漂移（当前态断言）

把 docs/README 里所有断言式数字与代码/契约实况对照：**当前态断言全部自洽**，无"文档写 49 但代码已 50"这类过时。唯一漂移是 `run_all_gates.py` 自己的 docstring（§4 卫生 B）——**我上一轮刚审过这个文件、还自夸钉住口径，却漏了自己顶部的过时数字**，这本身就是"自查者自身口径漂移"的活例，与 D1 台账管的是同一类错。

## 4. 视角四：采购域零改动——诚实边界

三侧全缺机器证据：`git ls-files` 采购域 count=**0**（`.xlsx`/`.ref/`/`.bak_before`/`.p25.tmp` 全是未跟踪工作副本，且**未被 gitignore**）；`find` 无任何 baseline/哈希清单；CI YAML 对 `xlsx|采购|procure|.ref` 零命中。

→ **"采购域零改动"此前确实是 `stat` mtime + 暂存区 grep 的人工声明，无机器门禁。** 本轮**不为此造工具**，理由：①给采购域建哈希 baseline 会把它正式纳入工程门禁体系，触碰用户反复强调的"采购域零改动/不入库"边界，属需用户拍板的范围，不自作主张；②baseline 首次生成只能证明"相对该干净时点未变"，不能追溯证明"过去从未被改"（与 bundle provenance 同型），价值有限。**如实标为边界，不悄悄落地。**

## 5. 本轮落地：1 个真机制缺口 + 2 处卫生（其余如实标注不改）

### 主：E1 `test_live_viewer_cli.py`（纯新增，5 条测试）

- `check_cli(script) -> problems` 是纯函数（真起子进程），**同一套断言**跑真脚本（正对照）与 tmp_path 篡改本（负对照）。
- 真实 CLI 面：8 个参数白名单（**外部契约真值，不从被测源码抓取**，否则删参数会让两边一起缩、自证循环）+ 4 类坏值（`--mesh-mode/--renderer/--source BOGUS`、`--interval-ms notanint`）必须 rc=2 且带 `invalid` 诊断。
- **负对照（改坏必红）**：①删整段 `--mesh-mode` 声明 → `--help` 丢参数必红；②删 `type=int` → `notanint` rc=0 必红；③放宽 `choices` 加进 `BOGUS` → 坏值不再被拒必红。
- 模块级全 stdlib（渲染栈 lazy import），系统 python 3.13（lean CI 等价）直接调 `check_cli` 也 PASS → **不造假红门禁**。

### 卫生 A：`test_deploy_chain.py:33` 恒真断言 → 真断言

锚定 `NN/MM passed` 结论行、断言分子=分母、**不写死计数**（那个 31 已漂到 33），保留 rc 与 `self-test: PASS`。全仓同类排查：无其它写死通过率/恒真断言（只剩故意构造的正对照字符串）。

### 卫生 B：`run_all_gates.py` docstring 过时数字

`:6 "33 tools"` / `:38 "28/38..38/38"` 改为"动态发现、不写死计数、已漂过 33→47+"的表述。纯注释，零逻辑改动。

### 明确不改 / 排除项

| 项 | 理由 |
|---|---|
| skip 判红门禁（pytest 层） | 脆但当下非假绿；完整栈 skip≈0、CI 用 `-rs` 不隐藏。加门禁需判"哪些 skip 合法"，属新策略，不在自查最小改动内 |
| requirements 无 pin | 供应链脆点，改 pin 影响 CI 行为、需单独决策；本轮只报 |
| 采购域哈希 baseline | 触碰"不入库/不自作主张"边界 + 只能证明相对时点，如实标边界 |
| `test_hd1910_viewer_mesh.py:201` 退化路径无断言 | 属 mesh 测试（CI 恒 skip、无完整栈不执行），低优先；记入待办不改 |
| D1 三条已决议事项 | HostImuGate / USB CDC / xgoduck 任务，按 `decision_contract.json` 排除，不重挖 |
| POST-PUSH ADVISORY 非 merge gate | 前几轮已审、已如实声明，非新缺口 |

## 6. 验收（全部真跑）

| 项 | 结果 |
|---|---|
| 新 `tests/test_live_viewer_cli.py` | **5 passed**（1 正 + 4 负对照，含 token 边界专项） |
| lean 环境（系统 python 3.13）`check_cli` | PASS（8 参数在、4 坏值拒，纯 stdlib 不依赖 pytest） |
| `test_deploy_chain.py` 改后 | **8 passed** |
| 全量 `pytest tests/` | **197 passed in 256.04s, rc=0**（原 192 + 新 5，venv + 全新 basetemp） |
| `run_all_gates --check` | 49/49 ALL_PASS（本轮未增门禁工具、未改登记） |
| `ci_meta_targets` / `line_contract` | structure PASS / coverage gap=0 |
| 采购域 | 零改动，mtime 仍 11-09/11-10 基线，暂存区负对照 NONE |

## 7. 真跑抓修的自身缺陷（自查的自指证据）

本轮**又**在自己写的新代码里抓到两个错，印证"静默 bug 发生在自己那一行、外部资料覆盖不到"：

1. **裸子串反噬（准则10 第三次同型命中）**：负对照把 `--mesh-mode` 改名成 `--mesh-mode-REMOVED`，而检测用裸 `flag in help` → 复合词含原名子串 → 负对照不红。改成 **token 边界正则**（前后不得是 word/连字符），并**新增一条专项测试**钉住"加 `--mesh-mode-verbose` 不能掩盖 `--mesh-mode` 被删"。
2. **系统 python 没装 pytest**：不是测试问题，是验证方式错；改为绕过 pytest、直接 import 模块调 `check_cli` 验证 lean 行为。

## 8. 边界与提交

- 本轮无新工具 verdict；沿用的门禁 `ship_verdict` 恒 `NOT_SHIPPABLE`、`live_hardware_accessed=false`；**不证明**任何测试断言内容/被测代码/软硬件正确，**不消 R3 / 不消任何悬案 / 不碰 D1 决议 / 不作签收**。
- 只证明：`live_viewer.py` 的 CLI 面现在有回归守卫、恒真断言已换成真断言、自述数字不再过时。
- 改动面：**1 纯新增测试 + 2 处卫生（1 测试断言 + 1 docstring）**，**不新增门禁工具、不改 line_labels、不改 CI、不碰采购域**。
- 采购域（SSOT/`build.py`/两份手改 xlsx/`.ref/`）全程未碰，mtime 仍 11-09/11-10 基线。
