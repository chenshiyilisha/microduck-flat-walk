# E4 · 真机时变命令跟踪评测前端（把 E3 判决器接到真实时序上）

_2026-11-12。承接 E3（`microduck-时变命令跟踪评测-E3-判决2026-11-11.md`）。本文只交付「上板当天把真机时序喂进去、当场出与 E3 同口径判决」的离线前端 + 采集契约 + SOP；**不产生任何实机证据、不消任何 A2 悬案、不改 `ship_verdict=NOT_SHIPPABLE`。** `live_hardware_accessed=false`。_

## 0. 一句话

E3 已把「现行 `p8head_2999` 跟不跟得住变化命令」在**仿真侧**判死为 `PATH_3`，但真机侧 `INCONCLUSIVE_LIVE_TRACKING`（B1 `BA-X-4`）零证据。卡住的不是「不会判」，而是「上板当天没人愿意临场手搓 nRMSE」——E3 第一次真跑就连撞 4 个会改结论的自身 bug。E4 把判决器做成**可离线自证、真机一到只换数据源**的前端，让 `BA-X-4` 当天可跑、且判据与 E3 逐字段一致。

## 1. 为什么值得做（以及为什么不是「再堆一个门禁」）

按 Pass121 判决，软件/门禁线已饱和（50/50 门禁 + 240 pytest + A2 8 悬案 + D1 3 决议 + E3），纯加契约/文档边际递减。E4 不是加门禁，而是补一条**唯一缺失的证据通路**：

- A2 的 7 条 `UNVERIFIED` 全部卡在「上板 / 卡尺 / 示波器」这类物理动作；`INCONCLUSIVE_LIVE_TRACKING` 是其中**唯一**有可能由「软件侧准备到位」显著缩短闭合时间的——因为它的证据是一段**时间序列**，而序列分析器可以现在就写好并证明正确，等真机只差喂数据。
- 其余 6 条（认板 / 几何 / 载流 / 500k 位宽 / 左右标签 / 轮滑策略）无论软件准备多充分，都仍需物理测量才有证据，只能备 SOP，不产生新信息。

## 2. 交付物与「一套判决」保证

| 文件 | 作用 |
|---|---|
| `microduck-software/tools/eval_tracking.py`（本轮小改） | 把内联在 `run_one` 的 `gates`/`verdict` 抽成纯函数 `grade_period()`，`healthy` 抽成 `baseline_healthy()`；仿真侧行为不变（`--against-sim` 证明零漂移） |
| `microduck-software/tools/eval_tracking_live.py`（新增） | 真机前端：读采集时序 → 注入完整性负对照 → 调**同一份**判决函数出报告 + CSV |
| `microduck-software/tests/test_eval_tracking_live.py`（新增） | 41 条：函数对象 `is`、判决带正负对照、注入检查、CLI 真进程 |

**一套判决，不是两套**：真机前端 `grade_period is eval_tracking.grade_period`、`_axis_report`/`aggregate_axis`/`classify_sweep`/`baseline_healthy` 同理（`test_eval_tracking_live.py::TestSharedJudgementIdentity` 断言对象身份）。真机与仿真唯一不同的只有**测量完整性检查**：

- 仿真：driver 知道确切波形，用 `last_step_cmd == expected_last` 判注入；
- 真机：无此神谕，用 `command_integrity()` 判「记录里的命令序列确实在按周期变化（唯一值数 ≥8、AC 分量 ≥10% 幅度）+ 实测序列确实有响应（≥2% 幅度）+ 样本 ≥40」。`period=0` 则反过来要求命令被保持。任一 trial 的注入检查红 → 该 period `verdict=invalid`，绝不静默平均。

两者都把结果作为 `waveform_injected_ok` 喂给**同一个** `grade_period`，红则 `invalid`——语义同构，杜绝「真机另立一套放水口径」。

### 本轮顺带修掉的一个继承性静默 bug

`baseline_healthy` 原内联表达式 `(nrmse or 9.9)` 把**合法的 0.0**（完美静态保持）当「缺失」判成不健康。E3 真实产物 baseline nRMSE=0.143 恰好绕过了它，所以从未暴露；合成数据 undershoot 使 nRMSE=0 才撞出来。已修为「仅 `None` 判缺失」，四态负对照覆盖（0.0→True / 0.143→True / 0.9→False / None→False）。`--against-sim` 确认 E3 已发判决零漂移。

## 3. 采集契约（上板当天采集端按此导出）

一个 JSON 文件 = 一次扫频，顶层为 period 记录列表。每条：

```json
{
  "period_s": 1.0, "waveform": "sine", "dt": 0.02,
  "cmd_vx": [0.30, 0.31, ...],        "meas_vx": [0.12, 0.13, ...],
  "cmd_wz": [...],                    "meas_wz": [...],
  "upright": [0.99, ...],             "fell": false,
  "base": {"vx": 0.30, "vy": 0.0, "wz": 0.0},
  "amp":  {"vx": 0.10, "vy": 0.0, "wz": 0.6},
  "meta": {"source":"live","ckpt":"p8head_2999","gain":8,"control_hz":50,"note":"..."}
}
```

- **`cmd_*` 是「下发并被回读确认」的命令**（不是期望值），`meas_*` 是本体**体轴**速度（odom/IMU 估计），50 Hz、与命令同长同对齐。用体轴而非世界系——E3 的判据是体轴 `root_link_lin_vel_b`（教训见用户记忆「世界系 vs 体坐标系」）。
- 同一 period 多跑几次放 `"trials": [ {...}, {...} ]`，按多 env 聚合出 spread；单条当 1 trial。
- `fell` / `upright` **强烈建议提供**：缺 `fell` 则 `terminated_frac` 不可判定，`grade_period` 的 verdict 会**拒绝给 `usable`**（没有摔倒日志的真机跑不能签字），并在报告 `degradation_notes` 显式写明，不会静默假绿也不会崩。
- `live_hardware_accessed` 由采集端在 `meta` 里如实置位；校准/回放置 `false`，真机置 `true`。

也接受 CSV：`period_s,waveform,dt,trial,cmd_vx,meas_vx[,cmd_wz,meas_wz,upright]`，同 (period, trial) 归一组。

## 4. 上板当天 SOP（B1 `BA-X-4` 闭合路径）

1. **前置**（`NEXT-p8-train.md` §判决已出 + `deploy_chain_contract.json`）：R17 V167 中控加载 `p8head_2999`，15 颗 HD-1910 `reg50=8`（`[policy] gain=8`，上电后回读 reg50 确认没被 robotd 每 tick 的 200 覆盖），先卸力、有支撑、低增益起步。
2. **扫频**：50 Hz 下发与 E3 同协议 `vx 0.30±0.10`、`wz 0±0.6`，sine/step 各扫 `period 0 / 0.5 / 1 / 2 / 5`（可加 10/20 慢周期复现 E3 负对照）；每 period 建议 ≥4 trial。
3. **导出**：按 §3 契约导出 JSON，逐 trial 附 `fell`/`upright`，命令回读值如实写 `cmd_vx`。
4. **判**：
   ```
   python tools/eval_tracking_live.py --in <采集.json> \
       --out artifacts/flat_walk/evals/live_tracking_report.json \
       --csv artifacts/flat_walk/evals/live_tracking_report.csv
   ```
   报告逐 period 给 `nRMSE_vx_best` / `lag_explains` / `gain` / `gates` / `verdict`，判据与 E3 一致（`nRMSE ≤ 0.40` 才算跟住、`lag_explains` 需高、`waveform_injected_ok` 必须真）。
5. **两种负对照（缺一不可，判据原文要求）**：
   - **命令冻结**：同一套下发改成 `period=0` 恒定命令 → 应得 `BASELINE_ONLY` 且 baseline healthy；
   - **策略未加载**：中控不挂策略（或发更安全的中止）→ 同一采集/分析链必须给出**可区分**结果（注入或响应不成立 → `invalid`）。若这两种情形与「策略在跑 + 变化命令」给不出区分，判据失效，本条不得闭合。
6. **离线自证（上板前先在 PC 跑，证明工具没坏）**：
   ```
   python tools/eval_tracking_live.py --calibrate          # 无文件无机器人，13 条含负对照
   python tools/eval_tracking_live.py --against-sim \
       ../artifacts/flat_walk/evals/tracking_p8head2999_sine.json   # 对 E3 已发判决 0 漂移
   ```
7. **签字**：报告 + 原始时序 + 两条负对照输出交人工，按 `BA-X-4` / `board_acceptance_contract.json` 判定。**工具退出码 0/1/2/3 只是分析结论，不是验收签字**；只有人工按判据签了，`INCONCLUSIVE_LIVE_TRACKING` 才可能从 `UNVERIFIED` 转 `PASS/CLOSED`，且须回写契约 + `evidence` 非空 + `signoff`。

## 5. 诚实边界（必须随结论读）

- **本工具不碰真实硬件**：它是离线分析器，不驱动 robotd、不读总线。`live_hardware_accessed=false` 恒为真直到上板当天由采集端产出真数据。喂 E3 仿真产物或合成数据只是**校准**，永远不是 `BA-X-4` 证据。
- **不重开 E3 仿真判决**：`PATH_3` 是仿真侧已定论（三条独立证据 + 20 s 慢周期负对照），本工具原样沿用，不因真机数据改动它的口径。
- **真机与仿真的 plant 保真差异属被测对象**：kp_fw、齿隙、摩擦、50 Hz 下发链路都只能由真机时序本身回答，不能由图上一致推断；真机延迟只会更难，不会更容易跟住。
- **统计强度**：E3 用 32 env、seed spread CV 1.8%；真机单次跑没有 seed 分布，<4 trial 时 `survivors_enough` 门标 `None`（可见、不假红）并在报告注明「单跑无分布」。签字人须自行判断 trial 数够不够。
- **测的是开环命令跟踪**：上层 P 控制器接本体反馈形成闭环后特性会变，闭环跟随不在本文/BA-X-4 范围。
- **改了 `eval_tracking.py` 的 `baseline_healthy` 语义**（0.0 不再误判缺失），已用 `--against-sim` + 41 条 pytest 证明 E3 已发判决与 50/50 门禁不受影响。
- 采购域零改动：未碰 SSOT / `build.py` / 两份手改 xlsx / `.ref` / `.bak` / 任何未跟踪采购文件。

## 6. 验证（本轮实跑）

- `tests/test_eval_tracking_live.py`：**41 passed**（含 5 条 shared-identity、9 条 grade_period、6 条 baseline 四态、8 条注入检查、6 条 grade_trials、2 条 against-sim、5 条 CLI 真进程）
- `--calibrate` **13/13**；`--against-sim` sine/step 各 5 period **0 漂移**
- `run_all_gates.py --list`：新工具未被 `--selftest` 发现机制误收（discover 仍 48，`eval_tracking_live.py` 不在列）——本轮一次真跑正是先抓到文档字面含该 flag 会让门禁误发现，已修
- E4-1 抽取后仿真侧 `--against-sim` 逐字段零漂移；`baseline_healthy` 四态负对照 PASS

## 7. 与 E3 / 阶段3 的指针

- E3 判决（`PATH_3`、四条自身 bug、仪器自证）见 `microduck-时变命令跟踪评测-E3-判决2026-11-11.md`，本文不改其结论。
- 阶段3「跟随可行性」的仿真侧已定；真机侧闭合路径 = 本文 §4 + B1 `BA-X-4`。跟随是否进阶段2仍属 domain 决策（见 E4-5 低层重训评估），本文不替用户拍板。

## 8. 三条「现在能做·不训练」候选的查证与决议（D1 台账）

用户「都做」授权后，对记忆里三条候选逐条查一手源码，**没有一条是值得现在动手的真缺口**。按 D1 纪律登记进 `decision_contract.json`（唯一主人），防止下次又从记忆里挖出来重做。每条带可执行 `reopen_when`。

| 决议 | 状态 | 一句话理由（一手证据见契约 `source_refs`） |
|---|---|---|
| **DECISION_SIM_TORQUE_BRINGUP** | `WITHDRAWN` | `at_powered` 早已是 robotd `--sim` 内部实现（`robotd/src/main.rs:1055` + `sim.rs:191,251-262`，2026-11-09 移植完成）；`sim_stack_check.py` 门禁**刻意不发 torque** 正是负对照，不是待补注入。记忆描述的是移植前历史。 |
| **DECISION_SIM_HEALTH_UNAVAILABLE** | `REJECTED` | daemon 未起报 `unavailable` 是协议/CLI 刻意设计的诚实行为（`duck-ipc-proto/src/lib.rs:2420-2427` 的 `Default` + `robotctl/src/main.rs:1505-1560` + `install-by-hand.md:159`），非 bug。记忆把 `health`（只问 robotd）与 `version`（列全部 daemon）混为一谈。 |
| **DECISION_MDUCK_CLI_GPU_LOCK** | `DEFERRED` | `mduck` CLI 与 `.gpu0.lock` 确实都不存在，但不产生一手上板证据、不消 A2 悬案、不改 `ship_verdict`，属边际递减便利；留「多任务抢卡 OOM 日志 / 每周重复调用量」为重开条件。 |

这三 none 碰 `ship_verdict=NOT_SHIPPABLE`，也不动采购域。**真正会动 `ship_verdict` 的只有 A2 的一手上板证据**——所以 E4 的主力是 §2–§4 的真机前端通路，而非这三条收尾。
