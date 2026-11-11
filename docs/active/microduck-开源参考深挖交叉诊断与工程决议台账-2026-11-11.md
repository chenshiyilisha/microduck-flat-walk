# 开源参考深挖：交叉诊断 + 工程决议台账 D1（2026-11-11）

_起因：用户「感觉还有bug，项目里那么多参考过的其他开源都可以深挖一下，取长补短完善本项目」。_
_方法：先按铁律「查全>查到、先找现成再造工具」把本项目参考过的开源绑到一手来源做交叉诊断，再对「别人修过的坑我们是否正踩着」逐条证真/证伪；最后只落地一个查全**实证抓到**的正交缺口。_
_边界：**采购域零改动**（SSOT / `build.py` / 两份手改 xlsx / `.ref/` 全程未碰）；本轮所有工具 `live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、不消任何 A2 悬案、不作实机签收。_

---

## §1 一句话结论

**21 组参考开源交叉诊断后，没有发现「代码层」的新缺口**——本项目对别人踩过的坑几乎都有等价甚至更强防护；两个最像缺口的候选逐条被一手推翻；我自己一个假想 bug 也被源码证伪。但**查全过程本身**暴露了一类**真实、可复现的信息一致性 bug**：一条 2026-11-09 已拍板「不搬」的工程决议没有机器主人，导致一个 very-thorough reasoning 子代理把它**重挖成 top1 新缺口**，且两份文档对读者给出相反结论。本轮落地 D1 工程决议台账（`decision_contract.json` + `check_decisions.py`）专门堵这一类，与既有 A1/A2/A3/C4 **语义正交、无重复**。

**「感觉还有bug」的直觉是对的——但 bug 不在我们以为的地方。**

---

## §2 参考开源查全（绑单一权威一手来源）

权威清单 = `docs/active/microduck-开源参考索引-2026-11-09.md`（§A–J，20+ 仓 GitHub API 实抓验真）+ `.upstream/` 第三方源码（仅作手法旁证，不算本项目已覆盖）+ `replica/docs/软件来源与我们的改动.md`。共 **21 组**，含 6 条主链路（官方 / kissqy / fanhao / luwu / DuckBuddy / hd1910m）、训练侧（xgoduck_rl / playground / loco-diag）、官方生态（yocto / gst-plugins / emotions）、中控工具（studio / community-kit / mdlab）、硬件社区（CAD 仓 / 666wsp / 三个立创开源板）与索引站。已深挖专文 ≥12 篇。

## §3 交叉诊断：「别人修过、我们是否正踩着」

判据：一手证据优先（`.upstream` 源码注释/防御/测试 → 深挖文档坑章节 → 索引作者踩坑 → 本项目 `tools/`+`tests/` 对照）。结论：

| 别人修过/警告的坑（一手） | 本项目现状（单一权威源码） | 判决 |
|---|---|---|
| 社区上电 inrush 4 次重启 / volatile P/D 漂移 / `sync_write reg40` 假释放 | `set_gains_all.py`：reg40 逐台 ACK、reg50 RAM/EEPROM 不对称建模、断电回放负对照、`readback PASS is NOT persistence` | ✅ 已强覆盖 |
| EEPROM「锁着静默不持久化、回读报成功」 | `set_gains_all.py` + `hd1910_ident.py` 断电回读显式建模 | ✅ 已覆盖 |
| BNO085 `0x08` 走路跳 20–60° 被误判成摔 | `imu_jitter_bench.py` 物理不变量（δ_sflp>5° 且 ω_step<2°）+ `verify_imu_chain.py` 姿态不变量 | ✅ 已覆盖 |
| `air_time` 门控只看指令不看前进 / 侧向等权 / 误差 3× 高估（issue #46） | `eval_velocity_in_sim.py` 加 `translates_forward`/`not_sideways`/误差 0.25 + `gate_p3_yaw.py` 冻结命令口径 | ✅ 已覆盖 |
| backlash 14 关节 13 个索引错 | `check_backlash_task.py` 断言 14 根 `passive_*`、范围、hard limit、执行器读输出侧 | ✅ 已覆盖 |
| normalizer 没烤进图 / 高跟踪率=在摔 / argparse rc=2 / CRLF / 裸子串反噬 / 读数vs算术矛盾 | `check_onnx_parity.py`（float64 独立重建+去 normalizer 负对照）、`ab_compare` 三表同屏、A3 rc=2 判 FAIL、C4 CRLF 负对照、漂移守卫 | ✅ 全部已覆盖 |
| **HostImuGate 连续重复判冻结 + 年龄门控**（fanhao 真机） | 见 §4：**已判不搬**，且无连续块流输入源 | ⛔ 已决议，见 D1 |
| **head-IMU 温度<23°C 读数≈280** | 见 §4：**不适用**（总线块无温度通道） | ⛔ 不适用，见 D1 |
| golden bit-exact 跨平台 last-ulp / 进程泄漏 / 长驻 worker | 本项目 parity 是纯 tensor 重建、门禁为一次性只读 CLI，无长驻 worker | ✅ 不适用（形态差异，非缺口） |

### §3.1 两个"最像缺口"的候选，逐条一手推翻

**候选①（探查代理报的 top1）：补 IMU `seq/status` 冻结/新鲜度判据。** 一手推翻链：
1. `docs/active/microduck-HD1910-BNO085-gyro_fusion移植执行清单-2026-11-09.md` §7 行 88/161 白纸黑字：**「❌ 不搬 `HostImuGate`（50ms 龄 / 1s 稳定 / 3 次冻结判定）…除非上板真出现『旧 sample 冒充新鲜』再立项」**。这是带可执行重开条件的**正式决议**，不是未考虑。
2. `check_imu_bridge.py` docstring 行 6-9 明写它是「接线前读一帧」的**台架验收工具**，`--port` 跑时只做一次 sync read；全仓无任何连续 `seq/status` 块流录制品（唯一的 `now-20261018.jsonl` 是 Studio robotd 回包，非 15 字节紧凑块）。**无真实输入源 ⇒ 造冻结判据只能合成数据自证**，违反「测真实入口」准则。
3. 三个 status 位常量 `NOT_READY/STALE/READER_SLOW` 已**全部**进 `--selftest`（行 371-373）。一手 C 源 `ft_imu.h`/`test_fast_sync.c` 本地**未落盘**，`check_imu_bridge.py` 是转引并明标来源——不凭空造协议细节。

**候选②：IMU 温度-读数联合守卫（低温野值）。** 一手推翻：`check_imu_bridge.py:32` 块布局 `[0..11]IMU [12]seq u8 [13]status [14]reserved`，**15 字节块内无温度通道**；head-IMU 温度 bug 属 QMI8658/BMI088 头部 IMU，与路①总线 ID200 LSM6 紧凑块不是一回事。**不适用，诚实标记，绝不凭空造工具。**

### §3.2 我自己一个假想 bug 也被源码证伪（记为方法教训）

我一度怀疑「`IMU_NOT_READY=0x01` 定义了却没进自检」。回一手源码 `check_imu_bridge.py:371` 明写 `check("IMU_NOT_READY bit", ...)`——**三个位全自检了**。这命中项目反复吃的亏：**读数与结论矛盾时，错的是读数**。不把不存在的 bug 塞进交付。

---

## §4 真正抓到的 bug：工程决议无机器主人（信息一致性）

### §4.1 实证复现

一个 `reasoning` 模型、`very thorough` 的 subagent 被要求「查全参考开源找取长补短缺口」，其 **#1 提案 = 补 HostImuGate 冻结判据**。它找到了 `docs/active/microduck-kissqy…-IMU与调参-参考价值` §7/§8 里把 `HostImuGate` 写作「门控可细化 / 顺带把 / C-IMU（新增）」的**早期评估页**，却没找到 `BNO085 移植执行清单` §7 里**已判不搬**的正式决议。⇒ 它把一条已决议事项重新挖成新缺口；同时，**人读这两份文档也会得出相反的执行结论**。

校验器上线首轮 `--check` 又独立抓到**第 4 处**：`microduck-xgoduck任务定义与整机质量口径核对` 与 `开源参考索引` §行动建议1 都正确撤销了 `roller_standup`/`sitstand`，但同样没有「唯一决议主人」标记可被机器识别（该条后被 D1 收为第 3 条决议）。

### §4.2 为什么既有机制管不到（正交性证明）

| 机制 | 管什么 | 状态词表 | 扫描标记 |
|---|---|---|---|
| A2 `closure_contract.json` / `check_closure.py` | **悬案**：证据未闭合 | `UNVERIFIED≠PASS` | `INCONCLUSIVE_*` |
| **D1 `decision_contract.json` / `check_decisions.py`（本轮）** | **主动决议**：不做/暂缓/撤销/否决 | `DEFERRED/REJECTED/WITHDRAWN≠PENDING` | `DECISION_*` |
| A1 `line_labels.json` | 工具线别 | 硬件线/非硬件线 | 路径标签 |
| C4 `check_stream_parity.py` | 协议解析双实现 parity | `OFFLINE_PARITY_ONLY` | 流用例 |

A2 的 `MARK=INCONCLUSIVE_*` 正则**扫不到** `DECISION_*`，且语义不同：A2 管「尚无一手证据、不算 PASS」，D1 管「已评估并主动决定不做、但保留重开条件」。一条事项从 `DEFERRED` 重新立项后应**转入 A2 作为 INCONCLUSIVE 悬案**，而不是留在决议台账——契约 `orthogonality` 字段把这条迁移路径写死。

---

## §5 D1 落地：工程决议唯一主人台账

**纯新增 3 件 + 1 条线别登记 + 4 份文档就地加指针（不改任何数值/结论）：**

| 文件 | 作用 |
|---|---|
| `microduck-software/tools/hd1910/decision_contract.json` | 决议唯一主人。3 条真实决议：`DECISION_HOSTIMU_GATE`（DEFERRED，本轮抓到的实证）、`DECISION_USB_MAIN_BUS`（REJECTED，总线预算否决）、`DECISION_XGODUCK_TASKS_WITHDRAWN`（WITHDRAWN，上游已实现/硬件不适用）。每条强制 `rationale` + **可执行 `reopen_when`** + `watch_terms`×`stale_terms` + `conflicts_with` + `source_refs` |
| `microduck-software/tools/hd1910/check_decisions.py` | 校验器：`--check` / `--selftest` / `--json` / `--list`。stdlib-only，可注入 roots，verdict 恒 `LOCAL_RESOLUTION_ONLY` / `ship=NOT_SHIPPABLE` |
| `microduck-software/tests/test_decisions.py` | 9 条回归（**CLI 真跑** + 口径漂移正负对照 + owner 路径归一化负对照 + 契约篡改必红） |
| `line_labels.json` | 纯追加 1 条 `META_GUARD`，coverage gap 保持 0，随 B3 派生名单自动进 lean CI |

**三条核心防御（都不靠模糊自然语言）：**
1. **集合相等**（借 `open-microduck check_book.py` / A2）：allow-list docs 里的 `DECISION_*` 集合 == 契约 id 集合。任何文档新写「我们不做 X」却没有契约主人 ⇒ 红；契约有条目却无文档引用 ⇒ 红。
2. **可执行重开条件**：`DEFERRED/REJECTED/WITHDRAWN` 必须带非空 `reopen_when`（含度量/上板/实测之一）与 `rationale`——否则是拍脑袋的永久否决，契约拒绝记录。
3. **口径漂移检测**（准则10）：只有 `watch_terms`（具名事项，如 `HostImuGate`）与 `stale_terms`（**具体复合词**，如「C-IMU（新增）」「门控可细化」，禁单字）**同现却无 `DECISION_*` 指针**才判红；正负对照证明「只提事项名讲上游架构」不误报、「补指针后转绿」。

**文档口径统一（4 份，纯追加指针）：** `kissqy-IMU与调参-参考价值` §7/§8 三处、`BNO085 移植清单` §7（owner）、`Pi4B 完整部署方案` §5 判决处（owner）、`xgoduck任务定义核对` + `开源参考索引` §行动建议1 + `仿真鸭移植` 行187（xgoduck 决议三落点）。统一后 `--check` 从首轮 **4 处 stale 冲突 + 3 个未落标记 → 全绿**。

---

## §6 本轮抓到并修掉的工具自身缺陷（真跑，非沿用归档）

1. **`--selftest` 依赖盘上文档标记落地**：首轮用 `walk_markdown()` 做结构断言，导致「文档还在编辑中间态」时所有正负对照全红。修：结构/正负对照改用**注入的干净 docs**，盘上落地状态交给 `--check` 单独判（selftest 只 `info` 行如实报告，不混入断言）。
2. **owner 检查被 Windows 反斜杠静默禁用**：`walk_markdown` 产出 `docs\active\...`，`decided_in` 写 `docs/active/...`，`rel == owner_path` 永远 False ⇒ 断言形同虚设（典型「绿色但没干活」）。修：`.replace("\\","/")` 归一化，并加**.owner doc 缺标记必红 / 带标记不红**两条正负对照证明它真会触发。
3. **负对照断言写太窄**：断言问题串含事项名 `HostImuGate`，实际校验器打印的是 `fake.md` 文件名 + `DECISION_HOSTIMU_GATE`。修：按真实输出串断言（这是断言语义差，非工具 bug）。
4. **我自己写契约 JSON 时混进单引号 + 拼错 `INSCONCLUSIVE`**：会让 `json.loads` 直接失败。当场修正。

> 这 4 条全部来自「真跑 → 看量动没动 → 定位自己那一行」，没有一条靠读代码看出来的——再次印证「验证要问量动没动，不问结果对不对」。

---

## §7 验收（全部真跑）

| 项 | 结果 |
|---|---|
| `check_decisions.py --selftest` | **31/31 PASS**，rc=0 |
| `check_decisions.py --check` | `LOCAL_RESOLUTION_ONLY / NOT_SHIPPABLE / decisions=3 doc_markers=3`，rc=0 |
| `tests/test_decisions.py` | **9 passed** |
| `line_contract --check` | verdict=PASS，**coverage gap=0**（50 条标签，新工具已登记） |
| `ci_meta_targets --names` | `check_decisions.py` **已派生进 lean CI 名单**（stdlib 判定通过） |
| 全量 `pytest tests/` | **190 passed in 168.18s**（原 181 + 新 9），rc=0 |
| `run_all_gates --check` | **49/49 ALL_PASS**（原 48 + 新工具）、`unlabelled=0`、`ship=NOT_SHIPPABLE`、A3 编排器零改动 |

## §8 Scope / 已知未闭环

- D1 是**信息一致性门禁**：它保证「不做的决议有唯一主人 + 重开条件 + 文档口径一致」，**不验证任何决议本身的正确性**，也不替代上板实测。
- 本轮**未新增 A2 悬案、未闭合任何 `INCONCLUSIVE_*`**：`LIVE_IDENTIFY`/`DIMENSION`/`CURRENT`/`RATE_MISMATCH`/`LR_LABEL`/`ROLLER_POLICY` 全部保持 `UNVERIFIED`，`ship_verdict` 如实 `NOT_SHIPPABLE`。
- 候选②（IMU 温度守卫）因总线块无温度通道**不适用**；若未来上 head-IMU（QMI8658/BMI088 输入路径）再单独立项，不在此之前造工具。
- **采购域零改动**：SSOT / `build.py` / 两份手改 xlsx / `.ref/` 全程未碰；手删 3 行不恢复、阶段0 ¥99、预算 `≈¥2,500–2,579` 一律未动。
- 一手 C 源 `ft_imu.h` / `test_fast_sync.c` 本地未落盘，status 位与块布局均为 `check_imu_bridge.py` 的转引（其 docstring 明标来源）；不据此新增协议细节。
