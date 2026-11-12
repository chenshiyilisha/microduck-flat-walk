# E4-5 · 低层重训执行计划（`resampling_time_range → [0.1, 0.5] s`）

_2026-11-12。承接 E3（`PATH_3`：现行 `p8head_2999` 跟不住变化命令）与 E4（`tools/eval_tracking_live.py` 真机前端）。用户「都做、不缺时间」授权了低层重训这一 domain 改动。**本文是只读可行性评估 + Dry-run 实证 + 执行计划，未启动任何 GPU 训练、未产出任何新 ckpt、未改任何采购文件。** `live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE` 不变。_

## 0. 一句话

E3 判定跟随能力受限于「低层 `vx` 命令通道响应弱（静态 undershoot ~45% + 波动抹平）」，唯一能改变这个判决的软件动作是**把 twist 命令的重采样窗口从 `(3.0, 8.0) s` 收到 `[0.1, 0.5] s`、从零重训低层**。本文回答「这条命令到底怎么写、走哪条训练链、会踩哪些坑、训完怎么验」，并把每一条都用 Dry-run（纯 CPU、不启动训练）实证过。**重训不保证成功**，它是拿 10.3 h GPU + 重走整条验收链去换一个「低层能否跟命令」的已知答案——E3 §5 仍推荐「暂缓跟随」为首选，本计划只是把「若决定重训」的路铺平。

## 1. 目标与不变量

| 项 | 值 |
|---|---|
| 唯一改动 | `env.commands["twist"].resampling_time_range`: `(3.0, 8.0)` → `(0.1, 0.5)` |
| 训练植物 | `hd1910_official_m6_kp8`（BAM `official_m6_stslaw.json` + `kp_fw=8.0`），与现行 `p8head_030_4096x3000` 同 plant |
| 契约 | obs 61 / act 14 / 50 Hz 不变；head 5 + 双腿各 5 = 15 颗 HD-1910；normalizer 烤进图 |
| 起点 | **从零重训**（`MICRODUCK_WARM_START=0`，不接 `p8head_2999` 续训）——低层命令分布改了，续训会把旧分布带进来 |
| 判据 | 用 E3 同口径 `eval_tracking.py`（`grade_period` / `classify_sweep`）在 `hd1910_kp8` 重跑 sine/step 扫频，看能否从 `PATH_3` 升到 `PATH_1/2` |

**不变量红线**：改 `resampling_time_range` 是训练分布改动，须从零训；**任何情况下不宣布新 ckpt 替代 `p8head_2999`**，除非它在同一评测口径、同一 plant、多 seed 下胜出且整条部署链验收通过。现行部署候选冻结不动。

## 2. 成本（如实，不用"不缺时间"糊弄）

- **4096 env × 12000 iter × 3.08 s/iter ≈ 10.3 h GPU**（`check_velocity_ready.py:63` 的实测 `SEC_PER_ITER`）。P8 原跑只用了 3000 iter（≈2.6 h）就出 `model_2999`；若先用 3000 iter 探路，≈2.6 h 可先拿一个信号，再决定是否值得跑满。
- **4096 是 8 GB 单卡甜点**：8192 env 因显存饥饿跌到 14.13 s/iter（`train_velocity.sh` 头注释），别贪。
- 训完须重走：仿真 gait 门禁（50/50 现有门禁不覆盖新 ckpt）、ONNX 导出 + parity、plant 冻结、E3 同口径跟踪评测、若上板再走 `BA-X-*` 全链。**这些不是"顺手"，是新一轮验收。**

## 3. 训练链真相（记忆没写清、Dry-run 查出来的）

现行 `p8head_030_4096x3000` **不是 `train_velocity.sh` 训的**，走的是专用 heading 链：

```
explore_heading.sh p8  →  tools/train_heading_variant.py  →  mjlab TrainConfig/tyro
   PLANT_ID=hd1910_official_m6_kp8      plant 由 BAM 参数注入，不是 --plant flag
   tools/bam_params/hd1910/official_m6_stslaw.json + kp_fw=8.0
```

一手证据：
- `explore_heading.sh:59` `p8) PLANT_ID=hd1910_official_m6_kp8; ... KP_EXPECT=8.0`；`:88` 读 `bam_params/hd1910/official_m6_stslaw.json`；`:135-153` 调 `train_heading_variant.py` 并写死全部 flag。
- `out/runmeta_p8head_030_4096x3000.json` 记 `plant=hd1910_official_m6_kp8 / envs=4096 / iters=3000`。
- 训练日志 `logs/.../params/env.yaml:142-144` 记 `json_path=...official_m6_stslaw.json / kp_fw: 8.0`。
- `train_heading_variant.py:536-560` 用 argparse pretask 层剥离自定义 flag，`:576-581` 把剩余 `passthrough` 透传给 `tyro.cli`；`:560` 有 `--dry-run`。

## 4. Dry-run 实证（本轮已跑，纯 CPU，未训练）

| 实验 | 结果 | 结论 |
|---|---|---|
| tyro 覆盖 `twist.resampling_time_range`，空格分隔多值 `0.1 0.5` | `SystemExit 2`（`Unrecognized options: 0.5`） | ❌ 不可用 |
| tyro 覆盖，tuple 字面量 `(0.1, 0.5)` | 直接 tyro 调用 EFFECTIVE，但经 `train_velocity.sh:151 extra.split()` 被拆碎 → FATAL | ⚠️ 有空格陷阱 |
| tyro 覆盖，**无空格逗号** `0.1,0.5` | 直接 tyro 与 `extra.split()` 两条路径均解析成 `(0.1, 0.5)`、`EFFECTIVE` | ✅ **正确语法** |
| `train_velocity.sh --no-check --check-only 4096 12000 <run>` + `EXTRA_ARGS="--env.commands.twist.resampling-time-range 0.1,0.5"` | `SCRIPT_RC=0`、runmeta 写出、无 FATAL | ✅ 配置链通（但此脚本非 P8 链，见 §3） |
| `train_heading_variant.py --dry-run --task ... --env.commands.twist.resampling-time-range 0.1,0.5` | `DRYRUN_RC=0`、`--dry-run: resolved and recorded, not launching` | ✅ **P8 链透传可行** |

> 所有 Dry-run 产物（`out/runmeta_dryrun_*`、`out/heading_meta_velocity.json`）已精确删除，未入 git、未污染仓库。

## 5. 重训前必须先解决的 4 个前置缺口（都是本轮 Dry-run 抓出来的真问题）

1. **`explore_heading.sh` 无透传位**：`:135-153` 把 flag 写死，没有 `$EXTRA_ARGS`，给脚本加 env var 不会传到 tyro。**选项 A**（推荐）：绕过 wrapper，直接调 `train_heading_variant.py`，手动对齐 `explore_heading.sh:136-152` 的全部 heading 超参 + plant（见 §6 命令骨架）。**选项 B**：给 `explore_heading.sh` 加一个 `$EXTRA_ARGS` 透传位（纯新增、低风险，但要重跑该脚本的既有门禁）。
2. **tyro tuple 语法无空格**：必须写 `0.1,0.5`，不能写 `0.1 0.5` 或带空格的 `(0.1, 0.5)`，否则 tyro 拒或 `extra.split()` 拆碎。`train_heading_variant.py` 走 `passthrough` 不经 `extra.split()`，所以 `(0.1, 0.5)` 也能过，但**统一用 `0.1,0.5` 最稳**。
3. **runmeta 只记声明、不记生效值**：`train_velocity.sh` 的 `runmeta` 与 `train_heading_variant.py` 的 `heading_meta` 都只在 `extra_args`/`passthrough_args` 里存字符串，`command_before/after` 不含解析后的 `resampling_time_range`。违反两脚本自己「a declared override is not evidence that it took effect」的原则。**重训前建议补一行**：在 `train_heading_variant.py` 的 `command_before/after` 里加 `resampling_time_range: list(cmd.resampling_time_range)`（纯新增、可被 `--dry-run` 验证），否则 10 h 后无法从 runmeta 确认这次到底训的哪个窗口。
4. **复跑日志有 historical 瑕疵**：`out/train_p8head_030_4096x3000.log:1` 有 `rain_heading_variant.py: command not found`（某 wrapper 吞首字母）后接真实训练。复跑前先确认真正的入口命令，别照抄这条日志。

## 6. 命令骨架（Dry-run 已验证透传；真跑需先解决 §5）

```bash
cd microduck-software
# 第 0 步：先补 §5.3 的 runmeta 生效值记录，再 Dry-run 一次确认 command_after 含 resampling
.venv-mjlab/Scripts/python.exe tools/train_heading_variant.py --dry-run \
  --task Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 4096 --agent.max-iterations 3000 \
  --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50 \
  --env.commands.twist.resampling-time-range 0.1,0.5 \
  # + 逐项对齐 explore_heading.sh:136-152 的 rel-heading/heading-hold/
  #   heading-tracking/ang-vel-z-clip/stage-iters/seed + plant(kp8 BAM)

# 第 1 步：短探路（3000 iter ≈2.6h）拿信号，不直接冲 12000
EXTRA/直接调用同上，去掉 --dry-run，MICRODUCK_WARM_START=0，SAVE=250
```

**plant 对齐要点**：直接调 `train_heading_variant.py` 时，必须复现 `explore_heading.sh:88-126` 对 kp8 BAM 参数与 `PLANT_ID` 的注入（该逻辑在 wrapper 里，不在 `.py` 里）——这是选项 A 的主要手工成本，也是最易漏的一步。漏了就会在默认 plant 上训，10 h 白跑。**因此更稳妥的是选项 B**（给 wrapper 加透传位），改动小且复用已验证的 plant 注入。

## 7. 训完验收链（不看总奖励，看跟踪与 gait 两条独立证据）

1. **跟踪判决（主判据）**：用 E3 同口径跑新 ckpt，`--plant hd1910_kp8`、sine/step 全周期、`--seed` 多值（≥3 seed，弥补 E3 单 seed）：
   ```
   eval_tracking.py --checkpoint <new_ckpt> --plant hd1910_kp8 \
     --waveform sine --periods 0 0.5 1 2 5 --num-envs 32 --seed <s>
   ```
   判据：能否从 `PATH_3` → `PATH_1/2`；nRMSE ≤ 0.40 的时变周期占比、`lag_explains` 是否升高、`meas/cmd` 是否随波形变。
2. **gait 不退化（副判据）**：重跑 `eval_velocity_in_sim` / 既有 gait 门禁（vx、航向、摔倒率、脚高），确认收窄 resampling 没把走路走垮——**跟随变好但走不稳 = 失败**。
3. **多 seed 中位数**：E3 是单 seed，新判决至少 3 seed 报 p50，避免又落"样本内趋势强、跨 seed 未知"。
4. **部署链**：若 1+2 胜出，才走 ONNX 导出 + parity + normalizer 烤图 + `deploy_chain_contract` 全链；**仍不宣布替代 `p8head_2999`**，除非上板 `BA-X-4`（E4 前端同口径）也胜出。
5. **真机侧**：新 ckpt 的真机跟踪适用 E4 前端 + `INCONCLUSIVE_LIVE_TRACKING` 同一悬案，不另开。

## 8. 诚实边界

- **未训练**：本文全部结论来自只读源码 + 纯 CPU `--dry-run` / tyro 重解析；没有任何新 ckpt、没有 GPU 占用、没有 gait/跟踪实测。`resampling=[0.1,0.5]` 是否真能教会低层跟命令，是**待验证假设**，不是已知结论。
- **不消悬案**：`INCONCLUSIVE_LIVE_TRACKING` 仍 `UNVERIFIED`、真机侧仍零证据；重训只可能改变仿真侧跟踪判决，真机仍需 E4 §4 上板。
- **domain 改动需担责**：这是用户明确授权的 domain 改动，但 `ship_verdict=NOT_SHIPPABLE` 不因「训了一个模型」而变；只有 A2 一手上板证据能驱动。
- **可复现性缺口未补**：§5.3 的 runmeta 生效值记录本轮**未改代码**（不属"重训"授权范围，且会动训练脚本需单独门禁回归），列为重训第一步的前置。
- 采购域零改动；Dry-run 临时产物全部精确清理。

## 9. 下一步（需用户再确认一个点）

Dry-run 证明**技术路径通**，但真跑前有一个决策点需用户拍板：**选项 A（直接调 `.py` 手工对齐 plant）还是选项 B（给 `explore_heading.sh` 加 `$EXTRA_ARGS` 透传位，推荐）**，以及**先跑 3000 iter 探路（≈2.6 h）还是直接 12000（≈10.3 h）**。这两点确认后，按 §5 补 runmeta 生效值 → 补透传位 → `--dry-run` 复验 → 真跑。在此之前不启动任何 GPU 训练。

## 10. 前置缺口已补齐（2026-11-12，Pass123；用户「都做、按最优、不缺时间」授权）

> 本节是 §5 缺口的落地记录。**仍没有启动 GPU 训练、没有新 ckpt**；本节只把 §5.1/§5.3 两个纯代码缺口补上并端到端 Dry-run 实证，真跑的算力决策见 §10.5。

### 10.1 计划内部矛盾与裁断（如实记录）
§5.1 把「选项 A（直接调 `.py` 手工对齐 plant）」标为推荐，但 §6/§79 又说「更稳妥的是选项 B」，两处自相矛盾。按「两来源矛盾⇒找更深层真相」裁断：**取 B**。理由是一手风险——选项 A 要人工复现 `explore_heading.sh:88-126` 的 kp8 BAM plant 注入（BAM JSON + `kp_fw=8.0` + `PLANT_ID`），§79 自己承认这是「最易漏的一步，漏了就在默认 plant 上训、10 h 白跑」，正是本项目反复出现的 XL330↔HD1910 plant 混淆事故类（见记忆准则3/铁律）。选项 B 让 plant 注入继续由已验证的 wrapper 持有，只在训练命令末尾追加一个 `$EXTRA_ARGS`，改动最小、不碰 plant 路径。

### 10.2 改了什么（全部纯新增，默认行为字节不变）
| 文件 | 改动 | 对应缺口 |
|---|---|---|
| `tools/train_heading_variant.py` | meta 增 `resampling_time_range_effective`（从 tyro 解析后的 `cmd` 对象直读，非声明字符串）；日志增一行 `command resampling_time_range (effective): [...]` | §5.3 生效值只记声明不记生效 |
| `tools/hd1910/explore_heading.sh` | 增 `EXTRA_ARGS` word-split 透传位（照搬 `train_velocity.sh`）；训练 flag 抽成单一 `TRAIN_FLAGS` 数组（DRY 与真跑共用，杜绝两处漂移）；增 `DRY=1`（照搬 `explore_heading_control.sh`，`--dry-run` + `dryrun_` 唯一名，不训练）；runmeta 增 `extra_args`（声明） | §5.1 无透传位 |
| `tools/hd1910/resampling_gate.py`（新） | 单一权威纯函数 `declared_window()` / `grade()` + CLI `--check`：把 EXTRA_ARGS 的**声明值**与 heading_meta 的**生效值**逐项对账，不符即 rc=6 | §5.3「声明≠生效」机器化 |
| `tests/test_lowlevel_retrain_preflight.py`（新） | 15 条：纯函数三态+负对照（mismatch/bad/missing 必红）、CLI 真进程 rc0/rc6、`--dry-run` 三态、wrapper `DRY=1` 端到端透传 | 防回归 |

**单一权威**：gate 逻辑在 `resampling_gate.py`，wrapper 的 post-run 门禁直接调它，pytest 也 import 它——对账语义只有一份，不会在 shell heredoc 与测试间漂移（准则2）。新模块**不含**门禁发现字面，`run_all_gates.discover()` 仍 48，不扰动门禁体系。

### 10.3 端到端实证（本地 `.venv-mjlab`，纯 CPU，未训练）
| 实验 | 结果 | 意义 |
|---|---|---|
| trainer `--dry-run` 无 override | log + meta 均 `[3.0, 8.0]` | 默认不变，字段纯新增 |
| trainer `--dry-run` override `0.1,0.5` | log + meta 均 `[0.1, 0.5]` | **生效值被真实记录** |
| trainer `--dry-run` 坏值 `0.1 0.5`（空格） | rc=2，tyro 拒绝 | 负对照：坏语法必红 |
| wrapper `DRY=1 PLANT=p8 EXTRA_ARGS=…` | rc=0；runmeta 记声明、heading_meta 记生效、交叉核对 PASS | 选项 B 全链通、plant gate(kp8) 过 |
| wrapper 默认 `PLANT=p3` 但 live=kp8 | rc=1，plant gate 拦截 | 正对照：既有 plant 混淆门禁仍工作 |
| 改前基线 `heading_meta_p8head_030_4096x3000.json` | 确认**无** `resampling_time_range_effective` | 新增字段是真能力，非摆设 |

### 10.4 测试分层（CI 与本地不打架）
CI 用 lean `requirements.txt`（无 mjlab/torch）跑 `pytest tests/`。故 `resampling_gate` 纯函数 + CLI 测试用纯标准库，**CI 常驻**；`--dry-run` / wrapper 端到端用 `importorskip("mjlab")`，**仅本地 `.venv-mjlab` 跑**，不在 CI 假红。新测试文件不含门禁发现字面。

### 10.5 真跑算力决策（仍未执行，交回用户拍板）
前置缺口已全闭合，本机实测 **RTX 4070 Laptop 8 GB / torch 2.9.1+cu128 / `cuda_available=True` / 无 GPU 锁**（计划 §2 的 4096-env 甜点卡，正是这台）。但按计划 §8「重训不保证成功、E3 §5 仍推荐暂缓跟随为首选」+ §9「在此之前不启动 GPU」，是否把 2.6 h（3000 iter 探路）/10.3 h（12000 iter）算力与覆盖现有候选的风险押上，**仍须用户明确拍板**。推荐路径：先 3000 iter 探路 (`PLANT=p8 ENVS=4096 ITERS=3000 MICRODUCK_WARM_START=0 EXTRA_ARGS="--env.commands.twist.resampling-time-range 0.1,0.5" bash tools/hd1910/explore_heading.sh <run>`)，按 §7 双判据（跟踪 PATH 升级 + gait 不退化、≥3 seed）验，胜出也不宣布替代 `p8head_2999`。`ship_verdict=NOT_SHIPPABLE`、`INCONCLUSIVE_LIVE_TRACKING` 不变。
