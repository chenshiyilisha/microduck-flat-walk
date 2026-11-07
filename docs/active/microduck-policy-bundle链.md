# policy bundle 的加载链：两端各查什么，中间漏什么

_2026-11-04。工具 [`microduck-software/tools/hd1910/verify_policy_bundle.py`](../../microduck-software/tools/hd1910/verify_policy_bundle.py)（自检 **39 项**，含 22 条负对照）。随 `docs/active/microduck-HD1910软件方案.md` §13 一起看。_

_2026-11-06 追加：本文 §1–§5 是 **B 代**口径；文末「官方加载口径（主导）」以
`pollen-robotics/microduck@main` 一手源码为准（[`verify_official_loader.py`](../../microduck-software/tools/hd1910/verify_official_loader.py)，自检 **30/30**）。按「官方开源为主导、其他开源为辅助」的定调，**两者矛盾时以官方为准**。_

---

## 结论先行

1. **`publish` 和这台 robotd 不是同一条链。** `manifest.json`（schema 2）是**另一代** robotd（`robotctl policy load/add`）读的；`DuckBuddy-main` 这一代 `grep metadata` 零命中、`PolicyParams` 里没有 manifest 字段 ⇒ 这份 manifest 对这台机器**一个字段都不生效**。
2. **这台（B 代）robotd 对 onnx 的全部检查是两个宽度**：`check_width(inputs[-1] == 61)`、`check_width(outputs[-1] == 14)`，而且只看 `outlets.first()` 的**最后一维**。⚠️ 官方 workspace 不是这样（还查 rank / dtype / 个数 / 名字），见文末「官方加载口径（主导）」。
3. 所以 bundle 里唯一能挡住「换了模型但观测布局变了」的东西是 **onnx metadata**（`joint_names` / `default_joint_pos` / `observation_names` / `command_names`）—— **而它没有任何读者**。我们的部署候选 `deploy61` 干脆一条都没带。
4. 顺着这条线查出一个**实打实的部署缺陷**：`deploy61` 的归一化器没有下限，7 个「robotd 会真的写非零值」的槽被放大 **89866 倍**。转 5.7° 头，动作从 `-0.29` 跳到 `-35.7` rad。

---

## 两端各查什么

| 检查 | 写侧 `publish`（`microduck_rl/publish/manifest.py`） | 读侧这台 `robotd`（`duck-control/src/policy.rs`） |
|---|---|---|
| 单 input / 单 output | `check_onnx` 拒绝 | 不查（只看第一个） |
| obs 宽度 | 末维必须 = 61，**字面量**（符号维拒绝） | `check_width` 末维 == 61 |
| action 宽度 | 末维必须 = 14 | `check_width` 末维 == 14 |
| 输入名 | 不查 | `ort::inputs!["obs"]` 硬编码 ⇒ 名字不对启动即失败（fail loud） |
| dtype | 不查 | 建 `Vec<f32>` ⇒ f64 图运行期失败（fail loud） |
| 能否执行 | `smoke_run_onnx` 50 步随机输入，要求有限 + 输出**不是常数** | `open_warm`：一次 `Observation::zeroed()` 推理，失败 ⇒ unhealthy ⇒ 自动回滚 |
| 观测布局 / 关节序 | **不查** | **不查** |
| 动作语义序 | **不查** | **不查** |
| 归一化器 | **不查** | **不查**（喂原始值） |
| `action_scale` / lowpass / gain / 50 Hz | 写进 manifest（无人读） | 从 `robotd.toml` 的 `[policy]` 读 |
| `manifest.json` 本身 | 写 | **不打开** |

**差集就是静默区**：布局、动作语义、归一化器、旁挂参数、manifest —— 五样东西在两端都不产生任何判决。

---

## 实测六个样本

```
python microduck-software/tools/hd1910/verify_policy_bundle.py --toml out/robotd_hd1910_mode0.toml
```

| 样本 | 宽度 | onnx metadata | 归一化除数下限 | 结论 |
|---|---|---|---|---|
| `out/deploy61.onnx` | 61 → 14 | **0 条** | **1.113e-05（10 维）** | **不能上**，见下节 |
| `out/p8head_2999.onnx` | 61 → 14 | 0 条 | 0.01289 | 可用（缺契约） |
| `out/hd1910_resume_..._it5999.onnx` | 61 → 14 | 8 条，**joint_names 逐位对、home 差 0.0003 rad** | 0.01289 | **全绿**，正样本 |
| `out/publish/duck-walk-56d/` | **56** → 14 | 0 条 | 除数 56 宽 | 装不进（宽度），且 **`.data` 丢失、加载即失败** |
| `.upstream/.../alpha_walking.onnx`（官方） | 61 → 14 | 8 条，全对 | 0.01289 | 基准 |
| `.upstream/.../hl2915_roulade_v4bl_6999.onnx` | 61 → 14 | 8 条，但 **`joint_names` 28 个 / 14 个动作**，`command_names` 只写 `twist` | 0.010 | metadata 自相矛盾（B 代自己产线） |

三条附带结论：

- **56 维那份 bundle 是手写的**：`publish` 的 `check_onnx` 拒绝任何不是 61→14 的图，所以这份 manifest 没经过任何闸门。它的 `deployment.observation_normalizer_baked: true` 现在**无法验证**——`policy.onnx` 引用的 `walk56.onnx.data` 不在同目录，ORT 连图都加载不了。
- **`publish` 不打包外部权重**：`shutil.copyfile(onnx_path, staged / POLICY_FILE)` 只拷 `.onnx`，而 `check_onnx` 用 `load_external_data=False` 读，所以一个 split 导出会**以 3 KB 的无权重图上传成功**。我们的 `deploy61.onnx` 就是 5/8 个 initializer 在 `deploy61.onnx.data` 里 —— 单独拷这个 `.onnx` 到机器人上，加载失败。
- **B 代自己的导出把 `joint_names` 忘了筛**：`hl2915_roulade_v4bl` 的 metadata 是 28 个名字（`passive_*_backlash` 与真关节交错）配 14 个动作。任何「按名字索引动作」的消费者都会错位。

---

## 核心发现：`deploy61` 的归一化器没有下限

`deploy61` 的 `Div` 分母（`add_3`，即训练 std，61 宽）里，**10 个维 = 1.113e-05**：

```
[51..54] head[0..3]      [55] body.x      [56] body.y
[57] body.z  [58] body.roll  [59] body.pitch  [60] body.yaw
```

而同一个家族里健康导出的下限是 **0.01289**（`p8head_2999`、`resume_5999`、官方 `alpha_walking`、`hl2915_*` 全都是）—— **差 1157 倍**。前者是 `VecNorm` 的 `std + eps` 地板，后者是「running variance 本来就是 0，没有地板」。

放大 1/1.113e-05 = **89866×**。

### 哪些维真的会被写

判据取自 `obs.rs` 的 `fill(command_block, [...])`：哪些槽是 `command.*`，哪些是字面量 `0.0`。

| 槽 | 来源 | 会被写非零？ |
|---|---|---|
| `head[0..3]` | `command.head` ← `intents.set_head()` **+ chorale sway**（`main.rs:2430` 四项相加） | **是** |
| `body.z / roll / pitch` | `command.body` ← `body_ema`（pose intent） | **是** |
| `body.x / body.y / body.yaw` | `obs.rs` 里是字面量 `0.0` | 否（恒 0） |

⇒ **10 个病态维里有 7 个，robotd 真的会往里写值。**

### 实证

同一套 plausible obs（站稳、走 0.3 m/s），只改 head / body 命令：

| 策略 | 基线 `a[0]` | head_pitch 5.7° | head_pitch 17° | body_pitch 5.7° |
|---|---|---|---|---|
| `alpha_walking` | −0.088 | 0.064 | 0.196 | 0.035 |
| `p8head_2999` | −0.194 | 0.050 | 0.153 | 0.106 |
| `resume_5999` | −0.066 | 0.055 | 0.167 | 0.019 |
| **`deploy61`** | −0.293 | **77.235**（`a[0]` → **−35.708**） | **232.333**（→ −107.436） | **88.704**（→ −37.422） |

单位是 rad。−35.7 rad 的关节目标，乘 `action_scale` 加到 home 上，只会被 ±π 夹住——**接上舵机就是一记猛打限位**。

### 为什么两个现成的探针都看不见

- **`publish` 的 `smoke_run_onnx`**：它用 `N(0, 0.05)` 抖全 61 维，然后只断言 `std(outputs) != 0`。`deploy61` 在这里的 std 是 **104**（健康的 0.29–0.83）—— 抖动越大越容易通过。**它对「因为缺下限而剧烈变化」是免疫的。**
- **我自己加的 R2「真实量级」**：用真实站姿 + `head/body = 0`，`0 / 1.1e-5 = 0`，恰好安全 ⇒ `max|a| = 0.491`，看起来正常。

两个探针，一个只看「有没有变化」，一个只看「零命令下的幅值」，都绕过了这个洞。只有把**分母本身**和**谁会往这些槽写**放在一起看，才浮出来。

### 修法

**不能靠改 onnx 修。** 把 std 从 1.1e-5 抬到 1.2e-2，该维的归一化输入就从 0 变成「命令 / 0.012」，而模型权重是在 `std=1.1e-5` 下学的——等于换了一个策略。正解是**重新导出，让 `VecNorm` 带 eps 地板**（`p8head_2999` / `resume_5999` 那条路径本来就有）。

⇒ **部署候选换 `p8head_2999` 或 `resume_5999`，`deploy61` 下线。**

---

## `--stamp`：把契约写进裸图

`deploy61` / `p8head_2999` 的 metadata 是 0 条。`--stamp` 写一份新的：

```bash
python microduck-software/tools/hd1910/verify_policy_bundle.py out/p8head_2999.onnx \
    --stamp out/p8head_2999_stamped.onnx --action-scale 1.0
```

- `joint_names` / `default_joint_pos` 取自 `duck-ipc-proto::JOINT_NAMES` 与 `model.rs::DEFAULT_POSITION`（跳过 mouth），`command_names` / `observation_names` 与官方 8 键同形。
- 顺手把外部权重**内联成单文件**（`onnx.load` 读进内存后按 `save_as_external_data=False` 存），解决「拷 .onnx 忘拷 .data」。
- **它修不了 C4**，也修不了任何权重问题——只是让下一个读者有东西可以对质。

---

## 官方加载口径（主导）：`verify_official_loader.py`（2026-11-06）

> **资料与实现优先级（用户 2026-11-06 定调）：官方开源为主导，其他开源为辅助。**
> 本节每个判据都从 `pollen-robotics/microduck@main` 一手 Rust 源码解析；DuckBuddy / kissqy /
> 666wsp / fanhao375 只作对照反例与硬件侧背景，**不提供阈值、关节序或判决**。
> 工具：[`microduck-software/tools/hd1910/verify_official_loader.py`](../../microduck-software/tools/hd1910/verify_official_loader.py)，自检 **30/30**（含 15 条负对照）。

### 为什么「B 代只查两个宽度」不能当通用结论

本文 §1–§5 审计的是 **B 代**（DuckBuddy / HL-2915）读者。官方 Apache-2.0 workspace 是另一个读者，
`duck-control/src/policy.rs::open` 的闸门严得多：

| 判据 | B 代 `check_width` | 官方 `open()`（一手源码） |
|---|---|---|
| 宽度 | 取 `outlets.first()` 的**最后一维** | `check_matrix` 取 `shape[1]`，且要求 `shape.len() == 2` |
| 秩 | 不查 | **必须 rank 2** |
| batch | 不查 | `shape[0]` 必须 1 或 −1（符号维经 ORT 报 −1，允许） |
| dtype | 不查（运行期才炸） | `tensor_shape` 要求 `TensorElementType::Float32` |
| 张量个数 | 只看第一个 | `(inputs.len(), outputs.len())` 必须恰好 (1,1) 或 (3,3)（后者 LSTM） |
| 输入名 | 不查 | `outlet(path, inputs, "obs")` 按名查找，缺了直接 `Shape` 错误 |
| LSTM | 无 | (3,3) 时输出须名 `actions`，`h_in/c_in/h_out/c_out` rank 3、四者形状一致、元素数 ≤ 1 048 576 |
| `metadata_props` | 不读 | **也不读**；`Sha256::digest` 只记录不比较 |
| warm-up | `Observation::zeroed()` 一次推理 | `Policy::load` 的 `open_warm` 会跑；`validate()` 明确不跑 |

`robotctl policy load` 那一侧：`updater/src/policy.rs` 的测试原文是 *"**Absence is not evidence** …
the shape gate at load was always going to be the real check"* —— 缺 manifest 或字段省略都不构成拒绝，
manifest 只管技能时长 / `command.encoding` / `action_scale` 等。真正的 ONNX 闸门就是 `open()`。

### 实测（`.venv-mjlab`，判据 `verified=True`）

| 样本 | metadata | 官方 `open()` 静态判决 |
|---|---|---|
| `artifacts/flat_walk/checkpoints/p8head_2999.onnx` | **0 条** | **16 checks / 0 FAIL / 0 WARN** |
| `artifacts/flat_walk/checkpoints/walk_std004_1250.onnx` | 8 条 | **16 checks / 0 FAIL / 0 WARN** |
| 把 `p8head_2999` 的 shape 改成 `[1,1,61] → [1,1,14]`（权重不动） | 0 条 | **4 FAIL**（obs/action 各 `F5 rank` + `F7 width`） |

最后一行是双向负对照：**同一份 rank-3 改造图交给本文 §2 的 B 代 `check_graph`，6 项全 ok、0 FAIL**。
两个来源互相矛盾时，以官方为准 ⇒ 部署候选 `p8head_2999` 的 `obs[1,61] → actions[1,14]`、`float32`、
1 in / 1 out、10 个 initializer 全内嵌，是**官方加载器会接受**的形状。

### 两条订正

1. **B0 不是加载阻塞。** `open()` 完全不读 `metadata_props`；B0 判的是「bundle 能不能自描述」，
   不是「daemon 会不会拒绝它」。§4.3(4) 里「G4 不能写成全绿」仍成立（那是 B 代工具的报告口径，
   不抹红），但**不要据此以为官方 robotd 装不上**。缺 metadata 的真实风险只有一个：obs 一旦重排，
   链上没有任何读者能发现。要补自描述用 `--stamp`，不是为了满足加载器。
2. **「`policy load` 只查宽度」是 B 代口径，已作废为通用表述。** 官方还查 rank / batch / dtype /
   张量个数 / 输入名；`软件自写分支.md` §4.1.5 与 §5.2、`最优方案.md` §3.4 的同一句已同步订正。

### 边界

- 纯静态：不跑 ORT，因此**不覆盖** `Policy::load` 的 `open_warm` 零观测推理、`commit_from_file`
  能否真开 session、以及 ONNX Runtime 共享库是否存在。动态那一半仍由本工具 `R1` 与
  `verify_policy_contract.py --rehearsal` 覆盖（`p8head_2999` 站姿动作峰值 0.1930 rad、finite）。
- 官方源码镜像在 `out/evidence-official/official/` 与 `out/evidence-official/official-main/`（被 gitignore）；新机需重新抓，脚本
  **不给源码根时显式标 `UNVERIFIED`，不会假装全绿**。抓取走 GitHub contents API（本机
  `raw.githubusercontent.com` 被代理挡，返回 000）。

```bash
V=microduck-software/.venv-mjlab/Scripts/python.exe
S=microduck-software/tools/hd1910/verify_official_loader.py
$V $S --selftest                                  # 30/30
$V $S artifacts/flat_walk/checkpoints/p8head_2999.onnx \
    --policy-rs out/evidence-official/official/duck-control_src_policy.rs \
    --obs-rs out/evidence-official/official-main/duck-control/src/obs.rs \
    --json out/evidence-official/official_loader_p8head_2999.json
```

---

## 待办

- [ ] **`deploy61` / `deploy61_iter600` 标记下线**，或重新导出后再用（导出后跑一遍 `C4`）。
- [ ] `publish` 的 `smoke_run_onnx` 加一条**分母下限**检查：`Div` 的常量 < 1e-3 即拒绝。上游也受益。
- [ ] `publish` 在 `upload_folder` 前检查 `data_location == EXTERNAL`，或直接 `onnx.save` 内联。
- [ ] B 代导出（`hl2915_*`）筛掉 `passive_*_backlash` 再写 `joint_names`。
- [ ] `robotd` 侧没有任何版本号能挡住「导出脚本换了但 cwd 没换」——如果以后要防，最小改动是 **`policy.rs::open` 里读一次 metadata 的 `joint_names` 与 `JOINT_NAMES` 对质**（约 15 行，fail loud）。

> **路径约定**：本文档命令里的 `out/...`（如 `out/deploy61.onnx`、`out/p8head_2999*.onnx`、`out/robotd_hd1910_mode0.toml`）是**相对 `microduck-software/`** 的——脚本从该目录运行，`out/` 即 `microduck-software/out/`（权重/产物实际落点）。仓库根 `out/` 仅含 reorg 桶（`builds/` `evidence-official/` `measurements/`），**不含**上述权重。reorg 未丢失数据。


