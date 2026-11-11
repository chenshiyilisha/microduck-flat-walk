# C4：SCS v1 流解析双实现逐字节对拍门禁（陆吾 parity 手法，只补正交缺口）

_2026-11-11，承接 `microduck-陆吾XGO-Duck成熟产品深挖-2026-11-11.md` §3（当时「只记录、不落地，避免把新工具塞进刚 CI 转绿的链」）。用户「继续，按最优的来」。_
_方法：先查全本项目自有门禁对陆吾 8 条 parity 手法的覆盖，确认唯一机制级正交缺口，再纯新增一个 stdlib-only 工具补齐；不搬运陆吾整套 parity，不动任何既有工具/采购域。_

---

## 0. 结论先行

1. **最优下一步不是「把陆吾 mosaico 的 `test_parity.py` 搬进来」，而是查全后只补 1 条正交缺口。** 陆吾 §3 的 8 条手法，本项目自有门禁覆盖情况是 **1 条强覆盖 + 6 条部分覆盖 + 1 条机制级缺失**：第 1/2/3/5 条要么已有**更强**的同类实现（`mcu_selftest.py` 真编译 C 逐向量比、`check_onnx_parity.py` 从 checkpoint 权重独立重建 numpy 参考、512 向量带去-normalizer 负对照），要么只是「要不要挂进 CI」的集成问题（挂进去会引入 onnx/torch 重依赖 → lean CI 一片诚实假红）；第 8 条姿态/物理不变量 `verify_imu_chain.py` 已强覆盖且入门禁。**只有第 7 条「脏流双实现逐字节同解」的核心机制——两个独立解析器对同一字节流产出逐字节相同的包序列——全仓不存在。**
2. **真到货：一个工具 + 一份契约 + 8 个测试，且第一次真跑就抓出一个潜伏的 framing bug。** A = 从生产 `check_imu_bridge.py` 用 stdlib `ast` **真提取** `parse_scs`/`_scs_checksum`/`ScsPacket`（不 import、不复制、不漂移），B = 独立字节状态机（显式游标、不用 `bytes.find`、不 import A）。首轮 `--check` 报 `crlf_noise` **A=2 / B=1**：A 的包装把 `consumed` 算成帧长、漏了前导噪声长度，导致 `b"master\r\n"+ping` 里同一个 ping 被切两次。**单实现时这个 bug 永远看不见**；B 的独立路径当场抓住。
3. **边界一个没松**：`verdict=OFFLINE_PARITY_ONLY`、`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false`。这证明「两个解析器彼此一致且能拒坏输入」，**不证明**总线上 ID200 应答、R3（500k 位宽）消解、IMU 轴向/mount 正确、任何整机可签收。`UNVERIFIED != PASS`、`OFFLINE_PARITY_ONLY != SHIPPABLE`。
4. **门禁与 CI 零副作用**：`run_all_gates.py --check` **48/48 ALL_PASS**（原 47 + 新工具，A3 编排器代码零改动、靠 `discover()` 自动纳入）、`coverage gap=0`、`ci_meta_targets.py` 自动把新工具派生进 lean CI 名单（stdlib 判定通过）。

---

## 1. 查全：陆吾 8 条手法 vs 本项目自有门禁（这是「为什么不全部搬」的证据）

| # | 陆吾 mosaico `test_parity.py` 手法 | 本项目现状（单一权威源码，行号） | 判决 |
|---|---|---|---|
| 1 | 导出严格图白名单（op 序列 + `[1,61]→[1,14]` f32 + Gemm/Elu 属性） | `verify_policy_bundle.py:274-337 check_graph`（I/O/dtype 正向白名单 + 22 组负对照）；op 属性项缺 | 部分（形状强、属性缺；我们部署的就是同一张 FP32 ONNX，无算子替换环节） |
| 2 | manifest 带 sha/input/output/architecture/activation/weight_* | `make_manifest.py:126-178`（绑 sha + IO，缺 architecture/weight_*，且在门禁外）；`reproducible_card.py:200-215` sha 对账旁证 | 部分 |
| 3 | N 随机向量原↔部署产物逐位比对 | `check_onnx_parity.py:60-74,123-133`（512 向量、onnx↔numpy 独立参考、去-normalizer 负对照）；`export_mcu.py`+`mcu_selftest.py`（真编译 C↔torch，比陆吾更硬）。**均无 `--selftest`，在门禁外** | 部分（实现最强、集成弱；挂 CI 会引重依赖假红） |
| 4 | NaN/Inf 输入注入必拒 | 输出侧 `verify_policy_inference.py:103-105,175-177` + pytest（**入门禁**）；输入侧 `export_mcu.py:229-235` 有守卫无注入测试 | 部分（输出侧已闭合） |
| 5 | 权重重定位 / 改 bias → 输出按预期变 | 零除子 `verify_policy_bundle.py:561-610`+N20/21/22（**入门禁**）、`policy_numeric_gate.py`（deploy61 负对照）；**「改权重→输出按公式变」的正向断言缺** | 部分 |
| 6 | IMU 新鲜度多字段门控 | `verify_imu_chain.py:226-274,804-814`（ready/samples/哨兵）、`check_imu_bridge.py:106-108`（STALE 位）；本项目 IMU 来自下位机 12 字节 SFLP 块，无逐帧 timestamp/error 字段，维度本就不同 | 部分（概念有落点且带负对照） |
| 7 | **脏流双实现逐字节同解** | `check_imu_bridge.py:164-191 parse_scs` 单实现（find+切片、只取首包）+ 单帧负对照；**无第二实现、无混合脏流对拍** | 🔴 **机制级缺失 → 本轮补** |
| 8 | 姿态/物理不变量单测 | `verify_imu_chain.py:433-458`（scipy 双实现）+`:601-631,782-791`（`\|gravity\|=1`）、`:501-549`；入门禁 | **已有（强）** |

> 📌 **判据**：只补「现有工具没有、且不与现有工具重复、且能纯 stdlib 带负对照」的那一条。搬运整套 parity 会制造重复轮子 + 把重依赖塞进刚转绿的 lean CI，与深挖文档 §3 自己写的边界冲突。第 7 条是唯一同时满足「正交 / 纯 stdlib / 自然负对照 / 命中本项目反复踩的坑」的缺口。

---

## 2. 为什么第 7 条恰好命中本项目反复踩的坑

`parse_scs` 是总线读侧的前沿：其输入是半双工串口字节流。本项目反复出现的静默 bug 都发生在这一层——

- **CRLF 坑**（Pass112/114 多次命中）：`while read` 从 Windows 文件读到 `master\r`，拼进 URL 得 `HTTP=000`；裸子串匹配被反义复合词反噬。
- **半双工尾字节截断**：URT-2 `drain()` 提前 40–130ms 切向，截断尾字节；流开头可能是上一帧残留。
- **payload 内伪帧头**：Feetech SCS v1 用 `FF FF` 做帧头，若 payload 恰好含 `FF FF`，天真的「find 到 FF FF 就切」会造出幽灵包。
- **非有限值载荷**：SFLP 四元数半精度 NaN/Inf 字节进流，framing 必须当不透明字节切帧（数值拒绝是 `decode_block` 的职责）。

这些坑的共同特征是**输出落在「看起来合理」的区间**（多切一个包、少切一个包、幽灵包），单实现自测永远绿灯。第 7 条的「双实现逐字节同解 + 混合脏流负对照」正是对治。

---

## 3. 协议格式（A 从生产源码提取，不在此复制算法）

Feetech SCS v1（来源 `check_imu_bridge.py` 模块头，一手读自 kissqy `ft_protocol.c`, 2026-11-03）：

```
FF FF ID LEN INST PARAM... SUM
LEN = len(params) + 2     total = LEN + 4
SUM = ~(sum(bytes[2..end-1])) & 0xFF    验收：sum(bytes[2:]) & 0xFF == 0xFF
拒绝：ID==255（保留）、LEN<2、total 超过剩余字节（截断）
```

- **实现 A（生产参照，not a copy）**：`extract_production()` 用 stdlib `ast` 从 `check_imu_bridge.py` 选出**恰好三个**顶层定义（`_scs_checksum`/`ScsPacket`/`parse_scs`），注入 `dataclass`，在受限 namespace `exec`。**不 import 该模块**（其 `serial` 是 lazy import，`Bus`/`main` 绝不执行）、不复制算法、不漂移；源文件若改名/改 arity 直接 FAIL。`--verify-source` 另用 AST 钉住 `parse_scs` 的协议常量（ID255 拒绝、6 字节最小头、`total=LEN+4`），篡改必红。
- **实现 B（独立正交字节状态机）**：显式游标 `i` 逐字节推进找 `FF FF`，按 `LEN` 跨帧，手动 `for` 累加求校验和；**不调用 `bytes.find`、不切片 A 的 raw、不 import A**。任何 framing 语义分歧都会暴露为逐字节不等。
- **共享 framing driver**：`offset` 从 0 推进，`parse_first` 返回 `(packet|None, consumed)`；`None` 时 `offset+=1`（跳噪声），有包时 `offset+=consumed`。**驱动相同、只有 `parse_first` 不同**，保证比的是解析器本身而非跳字节策略。归一化 `(dxl_id, instruction, params.hex(), checksum_ok, raw.hex())` 逐字段逐字节比。

---

## 4. 首轮真跑抓出的真 bug（双实现价值证据）

首轮 `--check` 输出：`crlf_noise  A=2 B=1 expected=1`，`verdict=FAIL`（7 个 problems）。

- **根因**：A 的包装 `parse_first_a` 最初返回 `consumed = len(raw)`（帧长），但生产 `parse_scs` 是从 `buf.find(FF FF)` 的**帧起点**解析的；当输入 `b"master\r\n"+ping` 时帧起点偏移 8 > 帧长 6，driver 前进 6 字节后仍能看到第二个 `FF FF`，把同一个 ping **切了两次**。
- **修法**：`consumed = buf.find(HEADER) + len(raw)`（含前导噪声）。
- **教训**：这正是双实现对拍的存在意义——A 是生产真函数，但**包装层**的语义差（consumed 定义）单实现自测查不出；B 用独立游标「跳过噪声直达帧头、按 LEN 跨到帧尾」，一次命中。同型于用户记忆里「4/5 静默 bug 是我自己那一行的语义差」。

> 同轮另修 3 处校验语义差：`header "ff ff"` vs `.hex()="ffff"`、中文「不 import A」 vs 英文 token 匹配、契约重复键 `consecutive_frames`（挤掉两个 note）。每一处都是「结果落在看起来合理区间」的自红或假绿隐患。

---

## 5. 12 个混合脏流用例（全部从 `stream_parity_contract.json#required_dirty_cases` 派生）

`valid_ping_response` / `valid_status_frame` / `bad_checksum` / `nan_payload_bytes` / `embedded_ffff_in_payload` / `injected_duck_ip_string` / `crlf_noise` / `leading_stale_fragment` / `truncated_tail` / `reserved_id_255` / `len_below_two` / `consecutive_frames`。

契约对每例有非空 note，且 `required_dirty_cases == case_notes.keys() == build_cases().keys()` **三方集合相等断言**（删任一例 → validate 必红）。关键约束：

- `bad_checksum`：仍切出 1 包但 `checksum_ok=False`（坏 CRC 被**标记**而非静默吞掉），A/B 对该标志也须逐字段相同。
- `embedded_ffff_in_payload`：payload 内 `FF FF` 不得切成幽灵包（恰好 1 个）。
- `nan_payload_bytes`：NaN/Inf 半精度位型作 payload，framing 不得丢帧（恰好 1 个）。
- `truncated_tail`：末帧 `total` 超剩余字节 → 返回 `None` 而非半包（expected=0）。
- **正向断言**：`total_framed_packets >= 12`，拦住「A/B 都返回空序列也算同解」的假绿。

---

## 6. 实跑验收（全部真跑，非沿用归档）

| 项 | 结果 |
|---|---|
| `check_stream_parity.py --check` | 12/12 用例 `A≡B` 且计数符合 expected；`all_byte_equal=true`、`total_framed=12`、`negative_control_live=true`、`verdict=OFFLINE_PARITY_ONLY` |
| `check_stream_parity.py --selftest` | **33/33 passed**，rc=0 |
| `check_stream_parity.py --check --ship-gate` | rc=1，`SHIP GATE REFUSED`（如实红） |
| `check_stream_parity.py --check --json --verify-source` | `source_files_verified=true`、协议源钉通过 |
| `pytest tests/test_stream_parity.py` | **7 passed in 2.10s** |
| `line_contract.py --check` | verdict=PASS、labelled=49、**coverage gap=0** |
| `ci_meta_targets.py --check` | `structure_verdict=PASS`，新工具**已派生进 lean CI 名单** |
| `run_all_gates.py --check --json` | **48/48 ALL_PASS**、not_pass=0、unlabelled=0、`ship_verdict=NOT_SHIPPABLE`、新工具自动发现且 PASS |
| 全量 `pytest tests/` | **181 passed in 162.58s, rc=0**（原 174 + 新 7，venv + 全新 basetemp） |

### 负对照（改坏必红，节选）

- **真 bug 回归**：`crlf_noise` 必须 A/B 都恰好 1 包（首轮 A=2 的 bug 已固化成回归测试）。
- 篡改生产源码 `total=LEN+4 → +5` → A/B 逐字节不等（parity 非空操作）。
- 给 B 注入 `total=+3` framing bug → 对拍必红，`negative_control_live=true`。
- 两个都返回空序列 → `total_framed_packets=0` 正向断言拦住。
- 契约：删一个脏流用例 / `status=PASS` / `live_hardware_accessed=true` / `empty_run_is_fail=false` / 删 case_notes / 抹 negative_controls / 改 header / 改 total_rule → validate 必红。
- CLI 真跑：`--check` rc=0、`--ship-gate` rc=1、`--json` 关键判决非 silent skip。

---

## 7. 与既有判决的正交关系

| 关系 | 说明 |
|---|---|
| 与 A1/A2/A3 | 新工具标 `META_GUARD`，靠 `run_all_gates.discover()` 自动纳入（47→48），**A3 编排器代码零改动**；线别标签纯追加 1 条，coverage gap 仍 0 |
| 与 B3 lean CI | `ci_meta_targets.py` 从 `line_labels.json` 派生 stdlib-only 名单，新工具自动进 CI 逐条 `--selftest`；`check_imu_bridge` 经 **AST 文本提取** 而非 import，规避其 lazy `serial`，故 stdlib 判定通过 |
| 与 `check_imu_bridge.py` | A **真复用其生产 `parse_scs`**（不复制、不漂移）；本工具是它的「离线双实现对拍 + 脏流」补集，不改它一个字节 |
| 与陆吾 §3 | 只借「双实现逐字节同解 + 脏流负对照」这一条**离线手法**；陆吾 C runtime / ESP-Mosaico 硬件 / 权重 / 几何 / 板型一概不移植 |
| 与 R3 / 悬案 | **不消** `INCONCLUSIVE_RATE_MISMATCH`、不碰 5 条原始 `INCONCLUSIVE_*`、不碰第 7 条 `INCONCLUSIVE_ROLLER_POLICY`；`closure_contract.json` 零改动 |

---

## 8. Scope / 采购域零改动声明

- **离线证明的边界**：本轮只证明「生产 `parse_scs` 与独立状态机对 12 个脏流用例逐字节同解、坏输入被拒」。不证明总线应答、波特率、IMU 轴向、半双工时序，不作整机签收。
- **采购域零改动**：未碰 SSOT、`build.py`、两份用户手改 xlsx、`.ref/` 生成源；阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579`、人人四样边界一律不变。打印包（gitignored `out/`）未动。
- **既有工具零改动**：除 `line_labels.json` 纯追加 1 条登记外，所有既有工具/契约/文档的数字与代码未动；本轮 4 个交付件（契约/工具/测试/本文档）全部纯新增。
- **负对照声明**：所有「绿」结论均来自真跑 CLI + 结构化断言 + 腐烂负对照，不沿用归档、不把「看起来跑完」当 PASS。
