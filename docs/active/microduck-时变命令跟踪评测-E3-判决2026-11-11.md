# E3 · 时变命令跟踪评测判决（当前策略能否跟随移动指令）

> 建立：2026-11-11 ｜ 类型：**仿真判决**（非门禁、非上板）｜ 关联：`microduck-阶段3-自动跟随.md` §4（本文是其"必须先做的那个实验"的执行结果）
> 一句话判决：**现行部署候选 `p8head_2999`（HD-1910 kp8）对时变速度命令没有跟随能力——连 20 秒周期的极慢指令都不跟，且这不是"跟但慢/延迟"，是波动被完全抹平。** 结论 `PATH_3`，仿真侧已确定，不依赖硬件。

---

## 0. 这个问题为什么重要（一句话回顾）

阶段 3 自动跟随的执行层计划复用现有 walk 策略、由上层 P 控制器以 ~50 Hz 发 `(vx, vy, ωz)`。但项目**全部已有评测**都是用 `eval_velocity_in_sim.freeze_command()` 把命令**冻结成恒定值**后测的（`resampling_time_range=(duration,duration)`），而上游训练命令是每 `[3.0, 8.0] s` 才重采样一次。 ⇒ "策略能否跟住变化的指令"此前**一条证据都没有**，跟随可行性悬空。本文把它变成已知。

阶段3 §4 原本预设三条路径，并判断拦路虎是"跟随要 50 Hz，比训练分布快 150–400 倍 = OOD"。**实测推翻了这个叙事**（见 §4），真正的问题更靠前。

---

## 1. 判决（结论先行）

| 问题 | 实测回答 |
|---|---|
| 当前策略能跟住变化的命令吗？ | **不能。** sine 0.5/1/2/5 s 全 fail；step 1/5/10/20 s 全 fail。 |
| 是"跟但慢/有延迟"吗？ | **不是。** 三条独立证据都指向"根本没跟"（§3）。lag 搜索对误差改善 <8%。 |
| 是"命令太快(OOD)"吗？ | **不是。** 20 s 周期比训练分布 `[3,8] s` 还慢 2.5–6 倍，完全 in-distribution，照样 fail（§3.3）。 |
| 跟随可行性判决 | **`PATH_3`：高层无法靠发命令实现跟随，低层策略需重训或改方案。** 见 §5 的诚实边界。 |
| 摔倒风险 | step 1 s 命令突变下 **20.8% 环境摔倒**（19/24 存活）；sine 各周期 0–3.1%。突变比平滑更危险。 |

---

## 2. 仪器与口径（可复跑）

- **工具**：`microduck-software/tools/eval_tracking.py`（本次修复前已提交于 `3f56134`，但从未成功产出判决——见 §6 四个真 bug）。
- **策略 ckpt**：`logs/rsl_rl/microduck_velocity_hd1910/2026-11-03_08-33-18_p8head_030_4096x3000/model_2999.pt`（现行 HD-1910 部署候选，与 `p8head_ref`/`eval_2999_kp8_rerun` 同一文件）。
- **plant**：`--plant hd1910_kp8`（`official_m6_stslaw.json`，kp_fw=8，`FrictionDRBamActuatorCfg`）——与项目主线 plant 一致，非默认 XL330。
- **rollout 保真**：solver `100/50`（训练实际值，非 flat cfg 默认 10/20）；`step_dt=0.02 s`（50 Hz）；warmup 2 s；sine 32 envs×12 s，step 24 envs×24 s；`seed=11`；device RTX 4070 Laptop。
- **命令**：vx `0.30±0.10` m/s（刻意避开 <0.15 的低速死区）、wz `0±0.6` rad/s；波形由 `WaveDriver` 直接覆盖 `term.compute()` 注入（配置改不出 1 s 周期正弦）；`resampling_time_range` pin 到窗口使官方 metric 分母为窗口均值。
- **判据**：nRMSE = 残差 / **命令的交流分量 RMS**（见 §6 bug#1）；`usable ≤ 0.40`、`marginal ≤ 0.70`；survivors-only；`--require-baseline` 要求 period-0 基准健康否则判决无效。
- **产物（顶层权威目录 `artifacts/flat_walk/evals/`，与 `p8head_ref/` 同级）**：
  - `tracking_p8head2999_sine.json` / `.csv` — sha256 `01421815faa2b026…`，39038 B
  - `tracking_p8head2999_step.json` / `.csv` — sha256 `1520f17ae5107947…`，38292 B

### 测量完整性（先证明测的是"变化命令"）

`sine` 各周期 `n_uniq_cmd_vx = 25/25/51/125`（采样到的不同命令值数），`step = 2`（阶跃两电平），`inj_ok=True` 全绿；period-0 基准 `n_uniq=1`（恒定）。命令确实按波形驱动，且 period-0 基准 `HEALTHY`（0% 摔倒、nRMSE 0.14–0.16），仪器可用。

---

## 3. 判决依据：三条互不依赖的证据

以 sine 为例（step 完全同型，§3.3 补慢周期）：

### 3.1 实测速度均值不随波形变化 ≈ 命令的 45%

| period | cmd 均值 | meas 均值 | meas/cmd | nRMSE | verdict |
|---|---|---|---|---|---|
| 0（基准） | 0.30 | 0.140 | 0.47 | 0.143 | usable |
| 0.5 s | 0.30 | 0.146 | 0.49 | 1.174 | fail |
| 1 s | 0.30 | 0.146 | 0.49 | 1.052 | fail |
| 2 s | 0.30 | 0.133 | 0.44 | 0.978 | fail |
| 5 s | 0.30 | 0.135 | 0.45 | 0.869 | fail |

命令在 `0.20↔0.40` 之间摆动，实测均值恒 ~0.135–0.146（≈0.30 的 45%），**纹丝不动**。这与项目既有静态读数同量级（HD-1910 kp8 在 cmd 0.4 下 vx≈0.163、跟踪≈41%，见 `HD1910软件方案.md`），是独立的**静态增益**证据，不是本次新发现——但在这里它说明：策略连"命令的均值"都只执行 45%，波动分量则被完全忽略。

### 3.2 lag 搜索解释不了误差 → 不是"跟但慢"

| period | nRMSE_lag0 | nRMSE_best | lag_explains | 最佳 lag |
|---|---|---|---|---|
| 0.5 s | 1.249 | 1.174 | 0.078 | 180 ms |
| 1 s | 1.129 | 1.052 | 0.029 | 120 ms |
| 2 s | 1.018 | 0.978 | 0.017 | 140 ms |
| 5 s | 0.878 | 0.869 | 0.006 | 170 ms |

"跟但有传输延迟"的特征是：允许一个 lag 后误差大幅下降（`lag_explains` 高）。这里全周期 `lag_explains < 0.08`——误差与延迟无关，是幅度压根没跟。5 s 周期相位只差 12°、lag 170 ms（纯传输延迟量级），若真在跟，nRMSE 不该有 0.869。

### 3.3 慢周期负对照 + 动作代价 → 排除 OOD、排除"努力但跟不上"

**step 波形 + 10/20 s 慢周期**（比训练分布 `[3,8] s` 更慢、完全 in-distribution）：

| period | nRMSE | lag_explains | meas/cmd | 动作加速度代价 vs 基准 | 存活 |
|---|---|---|---|---|---|
| 1 s | 1.050 | 0.017 | 0.39 | ×1.12 | 19/24（20.8% 摔） |
| 5 s | 0.832 | 0.021 | 0.41 | ×1.00 | 23/24 |
| 10 s | 0.760 | 0.007 | 0.45 | ×0.97 | 22/24 |
| 20 s | 0.793 | 0.005 | 0.45 | ×1.07 | 23/24 |

两条关键读数：
1. **20 s 仍 fail**：把命令放慢到训练重采样周期的 2.5–6 倍，跟踪误差依旧 0.79、`lag_explains=0.005`、meas/cmd 恒 0.45。⇒ 问题不是"50 Hz 跟随比训练快 150–400 倍的 OOD"，而是**策略对 `vx` 命令的变化本身不敏感**。阶段3 §4 的拦路虎叙事据此改判。
2. **动作加速度代价 ≈ ×1.0**：若策略在努力跟随波形，为跟随而做的额外动作必然推高 `action_acc`；这里几乎不变 ⇒ 策略**没有为跟随多做任何功**，把波形当噪声滤掉了。这是与前两条（均值不动、lag 无效）互相独立的第三条证据。

（`wz` 转向轴同型：`wz_amp=0.6` 在驱动，但增益在 −1.6～3.4 之间乱跳、nRMSE>2；因 `wz_base=0` 无 DC 基准，其 gain 数值不具稳态意义，仅作"转向轴也无稳定跟随关系"的旁证。跟随决策依赖 vx 与 ωz 两轴，两轴均不跟。）

---

## 4. 对阶段3文档的改判（D1 型指针，防口径漂移）

`microduck-阶段3-自动跟随.md` 是 2026-10-27 阶段 0 的**历史占位稿**（B6 指针已声明其采购口径过时、§4 数据栏刻意留空）。本实验执行了 §4 的协议，但结果落在 §4 判据表**最差一档之外**：

- §4 判据表预设："完全不行 = 高层降频到 3–8 s 发一次指令 ⇒ 一顿一顿 + 速度地板必过冲，基本死路"。
- **实测更差**：不是"降到 3–8 s 就行"——降到 10 s、20 s 都不跟。所以"高层降频发指令"这条退路在**当前低层策略**下也不成立。
- §4 拦路虎（"命令每 3–8 秒才换一次 / 跟随要 50 Hz 是 OOD"）被慢周期负对照**部分证伪**：真正的限制不是频率，是**低层 `vx` 命令通道响应弱**（静态 undershoot ~45% + 波动抹平）。

因此阶段3 §1 "能训但大概率不需要训 / 步态不要重训" 的乐观结论**对跟随场景不再成立**：若坚持做跟随，低层要么重训并显式强化"命令→速度"跟踪，要么接受"跟随不用 vx 命令通道实现"的替代方案（见 §5）。本文在阶段3 §4 加指针，不重写历史正文。

---

## 5. 对策与诚实边界

### 对策（按代价排序，供拍板，本文不擅自执行）

1. **接受判决、暂缓跟随**（推荐）：跟随不是当前整机落地的必要条件；阶段 2 先把走稳跑通，跟随作为独立课题。
2. **若坚持跟随，先做 3 维高层 + 重训低层的可行性评估**：阶段3 §5 的分层训（冻结低层当执行器）**依赖低层能跟命令**——本实验证明现低层不满足，故该方案的前置假设不成立，需先把 `resampling_time_range` 收到 `[0.1,0.5] s` **从零重训低层**（属 domain 改动，不能续训），成本与风险显著，属需拍板的范围。
3. **替代思路（未验证，仅记方向）**：不靠 `vx` 命令通道做跟随，改用航向/定点步态 + 上层 body velocity 闭环——但本实验没测这条，标 `UNVERIFIED`，不承诺。

### 边界（必须随结论一起读）

- **仿真判决，非真机**：全部在本地 MuJoCo（mjlab）完成，`live_hardware_accessed=false`。真实 HD-1910 的延迟/齿隙/摩擦只会让跟踪更难，不会更好；但真机实际能否跟随仍需上板验证，标 `INCONCLUSIVE_LIVE_TRACKING`。
- **单 seed（11）、单 ckpt（p8head_2999）、单 plant（hd1910_kp8）**：不是跨 seed 统计结论。样本内趋势极强（4+4 个周期一致、三条证据一致、慢周期负对照一致），但严格的多 seed 中位数留作后续；`ship_verdict=NOT_SHIPPABLE` 不变。
- **命令幅度限定 vx 0.20–0.40**：刻意避开 <0.15 低速死区。不排除策略在某个更窄/更低的幅值窗口里有残余响应，但那不足以支撑 50 Hz 跟随。
- **不追溯**：产物只证明本次（2026-11-11、上述 ckpt/plant/seed）的读数，可 diff、可复跑；不冒充"历史上从未跟过"。
- **测的是开环命令跟踪**：上层 P 控制器若接入本体状态反馈形成闭环，特性会变；本实验是"执行层能否忠实跟随给定命令"的下界测试，闭环跟随不在本文范围。

> **悬案登记（收尾补齐）**：本文引入的 `INCONCLUSIVE_LIVE_TRACKING` 已按 A2 铁律登记进 `microduck-software/tools/hd1910/closure_contract.json`（`status=UNVERIFIED`、`evidence=[]`，故 `ship_verdict` 仍为 `NOT_SHIPPABLE`），并在 `board_acceptance_contract.json` 新增 B1 判据 `BA-X-4`（真机按 E3 同协议实测时变命令跟随）挂接之——`link_evidence.py` 的"每个 UNVERIFIED 悬案必须有上板判据链接"由此闭合。仿真侧 `PATH_3` 判决不因登记而改变；真机侧闭合仍 `INCONCLUSIVE_LIVE_TRACKING`，待上板实测签字。

> **真机侧闭合工具已就绪（E4，2026-11-12）**：`tools/eval_tracking_live.py` 把本文判决器（`grade_period` / `_axis_report` / `classify_sweep` / `baseline_healthy`，两入口测试断言 `is` 同一对象）接上真机时序前端，上板当天按 `docs/active/microduck-真机跟踪评测前端-E4-2026-11-12.md` §4 采集并喂数即可出同口径判决，含命令注入负对照 + 冻结/策略未加载两种负对照。**工具就绪不等于有证据**：`INCONCLUSIVE_LIVE_TRACKING` 的 `status` 仍 `UNVERIFIED`、`evidence` 仍空、`live_hardware_accessed=false`，须真机实测 + 人工按 `BA-X-4` 签字才可能闭合。本轮另修掉 `baseline_healthy` 把合法 0.0 误判缺失的继承性静默 bug（`--against-sim` 证明本文已发判决零漂移）。

---

## 6. 真跑抓修的四个自身 bug（自指证据，均有负对照）

工具 `eval_tracking.py` 虽已提交，但**从未成功产出过判决**——第一次真跑连撞四个 bug，逐个真诊断、修掉并锁进 `tests/test_eval_tracking_instrument.py`（26→32 条，纯 torch CPU，CI lean 环境自动跳过、本机 `.venv-mjlab` 真跑，不进门禁编排、不碰采购域）：

| # | bug | 后果 | 修法 | 负对照 |
|---|---|---|---|---|
| 1 | nRMSE 用**含 DC 的** `rms_cmd` 做分母（命令 base 0.30 / amp 0.10，DC 占 97.3%，虚高 4.36×） | 异频/白噪声/反相信号全得 nRMSE 0.14–0.37 < usable 0.40 → **把"完全没跟"误判成"跟得住"** | period>0 改用**去 DC 的交流分量 RMS**；period-0 基准保留 uncentred（否则除零） | 3 条参数化：异频 p7/p13、白噪声必须 > usable 才绿；真跟踪必须 usable |
| 2 | `_axis_report` 对 period-0 返回 `phase_lag_deg=None`、`lag_explains=None`，聚合层直接 `torch.tensor([None])` | **CLI 崩溃**（`TypeError`），这是工具从未出判决的直接原因 | 提取纯函数 `aggregate_axis` 跳过 None、`n` 记有效值 | all-None 字段返回空不崩；真 period-0 输出可聚合 |
| 3 | baseline-only（合法 `--periods 0`）时 `fast` 未初始化 | `UnboundLocalError`，健康基准也跑不出结论 | 提取纯函数 `classify_sweep`；空 `fast` 不触发 path① 的 vacuous truth | baseline-only ≠ PATH_1；单跑基准 RC=0 |
| 4 | `classify_sweep` 把 **period-0 基准的 `usable`** 计入"有没有周期跟住"的 `any()` | **"全周期失败"被误报 PATH_2（"慢命令能跟、降频即可"）**——会直接误导架构决策，是最危险的一条 | `any` 只在时变周期（period>0）里找，基准只做健康检查不计入 | nothing-tracks 与 all-marginal 两条必须 PATH_3；marginal≠usable |

> bug#1 与 bug#4 都是"输出落在看起来合理的区间里"的静默假绿：前者把不跟判成跟、后者把 PATH_3 判成 PATH_2。若不是先做仪器自证（合成信号：纯增益/植入 lag/噪声单调性/无关信号）再跑真实评测，这两条会带着错误结论进入阶段3决策。这正印证项目铁律：**验证要问"量动没动、量级对不对"，自检必须带负对照，改坏必红**。

对已落盘的 sine JSON（由修 bug#4 **之前**启动的进程产出，末尾打印了错误的 PATH_2），用修好的 `classify_sweep` **重算得 PATH_3**（不重跑仿真，因为数值在 `run_one` 里算、不受 classify 影响）；step 那次是修好后启动，CLI 真机运行打印 `path 3`，与重算一致。

---

## 7. 复跑命令

```bash
cd microduck-software
CKPT=logs/rsl_rl/microduck_velocity_hd1910/2026-11-03_08-33-18_p8head_030_4096x3000/model_2999.pt
# 仪器自证（纯 CPU，无 ckpt/GPU/仿真，32 条含负对照）
.venv-mjlab/Scripts/python.exe -m pytest tests/test_eval_tracking_instrument.py -q
# sine 判决
.venv-mjlab/Scripts/python.exe tools/eval_tracking.py --checkpoint $CKPT \
  --plant hd1910_kp8 --waveform sine --periods 0 0.5 1 2 5 \
  --num-envs 32 --seconds 12 --warmup 2 --solver-iters 100 --solver-ls 50 \
  --seed 11 --require-baseline --out ../artifacts/flat_walk/evals/tracking_p8head2999_sine.json
# step + 慢周期负对照
.venv-mjlab/Scripts/python.exe tools/eval_tracking.py --checkpoint $CKPT \
  --plant hd1910_kp8 --waveform step --periods 0 1 5 10 20 \
  --num-envs 24 --seconds 24 --warmup 2 --solver-iters 100 --solver-ls 50 \
  --seed 11 --require-baseline --out ../artifacts/flat_walk/evals/tracking_p8head2999_step.json
```

> ⚠️ `--out` 用 `../artifacts/...`：CLI 的 cwd 是 `microduck-software/`，产物统一落顶层权威 `artifacts/flat_walk/evals/`；本次最初误用相对 `artifacts/` 落到 `microduck-software/artifacts/`（untracked）后已移动到顶层，本文只认顶层这一处。

---

## 8. 一句话

> **未知已消：现行策略跟不住变化的命令，连 20 s 极慢指令都把它滤成恒速——问题不在频率 OOD，在低层 `vx` 命令通道响应弱。这条仿真侧判决已定；跟随要么暂缓、要么先重训低层（需拍板），真机跟踪仍 `INCONCLUSIVE_LIVE_TRACKING`。**
