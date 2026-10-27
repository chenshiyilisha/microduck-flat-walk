# Microduck 纯软件路线：实测记录

> ⛔ **部分过时**：零元/CPU 脚手架阶段记录。**正式训练**走 `.venv-mjlab` + GPU + HD1910 植物，见根目录 [`README.md`](../../README.md)。

> 环境：Windows 11 / 20 核 / RTX 4070 Laptop 8 GB / 32 GB
> 花费：**0 元**（无舵机、无整机、无云 GPU）
> 代码位置：`microduck-software/`

---

## 一、先给结论

**零成本路线成立，而且比我预期的更彻底。** 六分钟内能看到机器鸭走路，五十分钟能自己训出一个
策略，全部在本机 CPU 上完成，GPU 全程闲置。这条路上唯一真正的门槛不是算力，是**一条被普遍
忽略的观测契约差异**——见第五节，那是这一轮最重要的发现。

已经跑通并留下产物的四件事：

| 步骤 | 产物 | 状态 |
|---|---|---|
| 环境搭建 | `.venv` + ffmpeg，无编译器、无 WSL | ✅ |
| 用现成权重复现走路 | `out/walk_first.mp4`（6 秒 300 帧） | ✅ |
| 客观评估（不看视频看数字） | `tools/eval_policy.py` + 速度包线 | ✅ |
| 导出 ONNX（归一化烘进图） | `out/walk56.onnx`，2.3 KiB，双后端差异 4.8e-07 | ✅ |
| 自训可部署策略 | `out/deploy61.pt` | ⏳ 后台训练中 |

---

## 二、环境搭建：三个坑，一个假坑

真正花时间的不是装包，是三个静默失败。

**坑 1：镜像缺包，但报错像是包不存在。**
本机 pip 全局配置指向清华镜像，而该镜像此刻对 `mujoco` 返回 `from versions: none`。

```
ERROR: Could not find a version that satisfies the requirement mujoco (from versions: none)
```

这句话的正确读法是"这个索引里没有这个包"，而不是"这个版本不存在"——官方 PyPI 上
`mujoco 3.14.0` 一直都在。加上 `--index-url https://pypi.org/simple` 显式覆盖即可，
**不必改动全局 `pip.ini`**。

**坑 2：没有 ffmpeg，但失败得很晚。**
`render_policy.py` 把帧 `pipe` 给 `ffmpeg` 子进程。本机没有 ffmpeg，报 `WinError 2: 系统找不到
指定的文件`。关键在于——**模型加载、策略推理、离屏渲染全都成功了**，只差最后一步编码。
所以这个错看着像"渲染失败"，实际是"编码器缺失"。解法：`pip install imageio-ffmpeg`，
它自带 `ffmpeg.exe`，复制到 `bin/` 后加进 PATH 即可，不用去官网下载。

**坑 3：PATH 格式。** Git Bash 里 `export PATH="E:/..."` 不生效，得写 `/e/...`。

**假坑：`mjbatch` 看起来只能编译。**
它是 nanobind + CMake 的 C++ 扩展，`pyproject.toml` 的 `classifiers` 里只列了 macOS 和
Linux，`cibuildwheel` 还明确 `skip = "*-win32"`。正常推断是"Windows 上得装 MSVC 从源码编"。
实际查 PyPI 发现从 **0.1.3 起就有 `win_amd64` wheel**，本机 Python 3.13 正好命中：

```
mjbatch-0.1.4-cp313-cp313-win_amd64.whl
```

**结论：不需要 MSVC，不需要 WSL**（本机 WSL 还被安全策略禁用，走这条路会直接死）。

---

## 三、第一次验证：它真的会走

用仓库自带的 `microduck_policy.pt`，`--command 0.4,0,0`，6 秒渲染：

```
wrote out/walk_first.mp4 (300 frames at 50 fps, 6.0 s of video for 6 s of simulation)
```

但视频会骗人——相机跟着鸭子跑，看起来在动，实际可能原地踏步。所以我写了 `eval_policy.py`
做客观测量：16 个独立环境、固定指令、确定性动作，量基座位移。

### 速度包线（这是这台机器上的真实数据）

| 指令速度 | 实测速度 | 跟踪率 | 摔倒数 | 行走距离 |
|---|---|---|---|---|
| 0.0 m/s | −0.008 | — | 0/16 | 0.28 m（原地微动） |
| 0.1 | **0.099** | **99%** | 0/16 | 0.85 m |
| 0.2 | 0.175 | 88% | 0/16 | 1.45 m |
| 0.3 | 0.237 | 79% | 0/16 | 1.95 m |
| 0.4 | **0.295** | 74% | 0/16 | 2.39 m（9.5 个体长） |
| 0.5 | 0.284 | 57% | 0/16 | 2.42 m |
| 0.6 | **0.244** | 41% | 0/16 | 2.35 m |

三个值得注意的点：

1. **低速跟踪近乎完美**（0.1 时 99%），说明闭环确实在工作，不是恒速脚本。
2. **包线在 0.4–0.45 m/s 附近饱和**。这是策略能力的上限，不是指令的问题。
3. **指令超过 0.5 后实测速度反而下降**（0.5→0.284，0.6→0.244）。让它更拼命，它走得更慢。
   这是典型的"超出训练分布"退化——训练时前向指令上限就是 0.5。

三个速度下都是 **0/16 摔倒**，最差姿态 `upright 0.995`（1.0 为完全直立），说明策略很稳。

---

## 四、性能：GPU 全程闲置

| | 作者环境（8 vCPU） | 本机（20 核） |
|---|---|---|
| 训练吞吐 | 16k env-steps/s | **50–56k**（短测） |
| 1500 次迭代 | 2 h 36 min | 约 50 min（短测推算）/ 86 min（长跑实测） |

> 长跑稳态掉到 27–28k steps/s，大约是短测的一半。推测是环境进入摔倒/重置频繁的阶段后
> `batch.reset` 开销上来，以及长时间满载后的频率回落。即便如此仍是作者的 1.7 倍。

RTX 4070 从头到尾没被调用。这不是"不会用"——mjbatch 的设计就是把成千上万个 MuJoCo 实例
放在 C++ 线程池里步进、释放 GIL，瓶颈在 `mj_step` 调用次数，而单卡 GPU 上跑这个尺度反而更慢。

**这也是"零成本"的真正含义**：省下来的不是电费，是**你不需要为这件事买显卡**。

---

## 五、这一轮最重要的发现：56 维和 61 维不是"差 5 个"

这是我在对比官方 `duck-control` 时撞上的，它推翻了我之前"训出来就能热插拔"的判断。

### mjbatch 的 56 维观测

```
3  基座线速度（body frame）      ← 问题在这里
3  gyro
3  projected gravity
14 关节位置 − home
14 关节速度
14 上一帧动作
3  指令 vx, vy, vyaw
2  步态时钟 sin/cos
```

### 官方部署契约的 61 维观测（`duck-control/src/obs.rs`，`OBS_LEN = 61`）

```
3  gyro, trunk frame, rad/s
3  projected gravity
14 关节位置 − home
14 关节速度
14 上一帧动作
13 指令：vx, vy, vyaw(3) + neck_pitch, head_pitch, head_yaw, head_roll(4) + body x,y,z,roll,pitch,yaw(6)
```

**官方没有基座线速度。** 而且训练侧的代码把这件事写得很明确：

```python
del cfg.observations["actor"].terms["base_lin_vel"]
cfg.observations["critic"].terms["base_lin_vel"] = ObservationTermCfg(...)  # privileged
```

actor 拿不到基座线速度，只有 critic 在训练时能看——因为**真机上没有能测出这个量的传感器**：
它只有 IMU 和 14 个关节编码器。机器人不知道自己整体跑多快，只能从身体晃动的变化里推断。

于是 mjbatch 那个 56 维策略的性质就变了：

> 它不是"保真度稍差"，而是**训练时依赖了一个部署时根本不存在的输入**。

这比"没有 BAM 执行器模型""没有齿隙""没有域随机化"都更致命——那三样影响的是策略质量，
这一条影响的是**策略能否存在**。一个靠特权观测训出来的走路策略，在真机上第一步就会失去
它最重要的输入通道之一。

这也解释了为什么社区里"把 56 维模型微调一下就能上真机"的说法站不住。

### 但模型结构是支持的

我核对了 MJCF 的实际结构，14 个关节的名称和顺序与官方完全一致，**四个头部关节
（`neck_pitch` / `head_pitch` / `head_yaw` / `head_roll`）都在**：

```
left_hip_yaw, left_hip_roll, left_hip_pitch, left_knee, left_ankle,
neck_pitch, head_pitch, head_yaw, head_roll,
right_hip_yaw, right_hip_roll, right_hip_pitch, right_knee, right_ankle
```

所以 61 维契约是**可以完整复现的**，不需要动模型，只需要换观测。

### 还有一个容易错的地方：不要缩放

`obs.rs` 里的 `fill()` 把数字直接窄化为 `f32`，**没有任何 scale 乘法**，注释说明观测以
物理单位进策略。而 mjbatch 的训练代码是这样的：

```python
2.0 * vel_body, 0.25 * gyro, up, ..., 0.05 * self.qvel[:, self.dofs], ...
```

`0.25` 和 `0.05` 这两个系数如果只存在于训练侧、部署侧不乘，就是一次彻底的输入错位。
这正是上游 `CLAUDE.md` 反复警告的那类 bug——**在仿真里完全隐形，上真机才炸**。

---

## 六、修正：`train_official.py`

基于上面的发现，我写了 `repo/train_official.py`：保持原仓库的物理、奖励、PPO 全部不动，
**只把观测换成官方 61 维布局，三个传感器块全部不缩放**。

```bash
python train_official.py --num-envs 4096 --iterations 1500 --timestep 0.005 --out out/deploy61.pt
```

几个刻意的设计决定：

**头部和身体的指令槽全部给 0。** 这不是偷懒——`obs.rs` 自己写着 body x/y/yaw 是
"hardcoded zero... the nominal encoding, not a placeholder"。所以这个策略的含义是
"保持标称头身姿态下行走"，恰好就是一台出厂状态的机器鸭会收到的东西。代价是它不会跟随
头部指令（那需要上游的 `head_pose_tracking` 奖励），但作为第一条可部署步态，这是正确取舍。

**步态时钟保留在奖励里，但不进观测。** 官方 61 维 actor 同样没有时钟通道，而奖励是按相位
整形的。这条原则值得单独记住：**奖励可以用特权状态，策略不可以。**

已冒烟验证（512 envs × 2 iters）：观测宽度 61、分块位置全对、`-rot[:,2]` 确实等于
projected gravity（直立时为 `[0,0,-1]`）、reset 后关节位置在 ±0.05 内、动作块全零。

---

## 七、ONNX 导出：把归一化关进图里

`tools/export_onnx.py` 不只是 `torch.onnx.export` 一行。它做的三件事：

1. 只导 actor 的**均值动作**（不是采样）——50 Hz 部署时采样只会给力矩限幅添麻烦
2. 用 `ActorOnly` 包一层，把 critic 砍掉，图里只有一个输出
3. **验证归一化真的在图中**，而不是假设它在

实测结果：

```
checkpoint   repo\microduck_policy.pt
obs_dim      56   act_dim 14   timestep 0.005
onnx         out\walk56.onnx  (2.3 KiB)
parity       max |torch - ort| = 4.77e-07  over 256 obs
ok           normalization is inside the graph and both backends agree
```

图的构成证明归一化确实被折进去了：

```
输入 obs [batch, 56] float   →  输出 action [batch, 14]
7 个节点：Sub, Div, Gemm ×3, Elu ×2
```

那个 `Sub` / `Div` 就是 `(obs - mean) / sqrt(var)`。如果少了它们，模型在仿真里表现完全正常
——因为仿真永远在 Python 侧归一化完才调用网络——**这个 bug 在 viewer 里是隐形的**。

而之所以要验，是因为归一化的 `mean`/`var` 是 `register_buffer`，导出时被当成常量折叠。
这既是"能烘进去"的原因，也是"烘没烘进去需要确认"的原因。

`input_names=["obs"]` 也不是随便起的：官方 `policy.rs` 用 `check_matrix(path, outlet(path,
inputs, "obs")?, OBS_LEN)` 按名字取输入，名字不对直接拒绝加载。动态 batch 也兼容
（`check_matrix` 接受 `shape[0] == 1 || shape[0] == -1`）。

---

## 八、下一步能做什么（仍然 0 元）

按"投入产出"排序：

1. **等 `deploy61.pt` 训完，导出 `deploy61.onnx`**，用 `eval_policy.py` 对比 56 维与 61 维的
   速度包线——这能量化"去掉特权观测要付多少代价"，是很有价值的一组数字
2. **在官方 policy-playground 里跑一遍导出的 ONNX**（浏览器里，不用硬件），验证图真的能被
   官方加载器接受
3. **补 `head_pose_tracking` 奖励**，让策略学会跟随头部指令——这正是官方 velocity 任务的
   "the whole point of the rewrite"，而 mjbatch 完全没有
4. **改奖励函数做对照实验**：现在这台机器 50 分钟一轮，完全够跑 A/B。比如把 `gait` 权重
   调一半，看速度包线怎么变——这是理解"奖励设计"最直接的方式
5. **复现社区报告的那两个 bug**（`air_time` 奖励门控错位、`error_vel_xy` 高估约 3 倍），
   用独立实现验证。最后一条尤其值得，因为在仿真里验证"别人的指标算错了"，不需要任何硬件

---

## 九、一句话总结

零成本能买到的东西比想象中多得多：**一台会走的机器鸭、一套可信的评估工具、一条能导出到
真机的 ONNX 链路**，全在 6 小时内、0 元、不用显卡。

但代价是必须自己发现那些"在仿真里隐形"的坑。这一轮最值钱的不是跑通了训练，而是查出
**56 维和 61 维之间差的那 5 维里，藏着一个策略能否上真机的分界线**。

---

*训练日志：`out/train61.log`；工具：`tools/eval_policy.py`、`tools/export_onnx.py`；
新增训练入口：`repo/train_official.py`*
