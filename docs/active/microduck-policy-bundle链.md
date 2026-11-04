# policy bundle 的加载链：两端各查什么，中间漏什么

_2026-11-04。工具 [`microduck-software/tools/hd1910/verify_policy_bundle.py`](../../microduck-software/tools/hd1910/verify_policy_bundle.py)（自检 **39 项**，含 22 条负对照）。随 `docs/active/microduck-HD1910软件方案.md` §13 一起看。_

---

## 结论先行

1. **`publish` 和这台 robotd 不是同一条链。** `manifest.json`（schema 2）是**另一代** robotd（`robotctl policy load/add`）读的；`DuckBuddy-main` 这一代 `grep metadata` 零命中、`PolicyParams` 里没有 manifest 字段 ⇒ 这份 manifest 对这台机器**一个字段都不生效**。
2. **这台 robotd 对 onnx 的全部检查是两个宽度**：`check_width(inputs[-1] == 61)`、`check_width(outputs[-1] == 14)`，而且只看 `outlets.first()` 的**最后一维**。
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
python tools/hd1910/verify_policy_bundle.py --toml out/robotd_hd1910_mode0.toml
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
python tools/hd1910/verify_policy_bundle.py out/p8head_2999.onnx \
    --stamp out/p8head_2999_stamped.onnx --action-scale 1.0
```

- `joint_names` / `default_joint_pos` 取自 `duck-ipc-proto::JOINT_NAMES` 与 `model.rs::DEFAULT_POSITION`（跳过 mouth），`command_names` / `observation_names` 与官方 8 键同形。
- 顺手把外部权重**内联成单文件**（`onnx.load` 读进内存后按 `save_as_external_data=False` 存），解决「拷 .onnx 忘拷 .data」。
- **它修不了 C4**，也修不了任何权重问题——只是让下一个读者有东西可以对质。

---

## 待办

- [ ] **`deploy61` / `deploy61_iter600` 标记下线**，或重新导出后再用（导出后跑一遍 `C4`）。
- [ ] `publish` 的 `smoke_run_onnx` 加一条**分母下限**检查：`Div` 的常量 < 1e-3 即拒绝。上游也受益。
- [ ] `publish` 在 `upload_folder` 前检查 `data_location == EXTERNAL`，或直接 `onnx.save` 内联。
- [ ] B 代导出（`hl2915_*`）筛掉 `passive_*_backlash` 再写 `joint_names`。
- [ ] `robotd` 侧没有任何版本号能挡住「导出脚本换了但 cwd 没换」——如果以后要防，最小改动是 **`policy.rs::open` 里读一次 metadata 的 `joint_names` 与 `JOINT_NAMES` 对质**（约 15 行，fail loud）。
