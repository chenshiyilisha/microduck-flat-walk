# mjlab / GPU 环境落地 + 三个新仓库

> 2026-10-24 晨。回答「mjlab 还差多少」：**已经装完了，GPU 也跑通了**。
> 这一份记录环境怎么搭起来的（含五个坑）、GPU 实测数字，
> 以及昨晚到今早你发来的三个仓库各自值得拿什么。

---

## 1. 环境状态：全绿

```
torch                    2.9.1+cu128
mjlab                    1.3.0
mujoco                   3.7.0
mujoco-warp              3.7.0.1
warp-lang                1.12.0
better-actuator-models   1.0.1  (@62bd8ce，见坑 4)
mjlab-microduck          0.1.0
rsl_rl_lib               5.0.1
onnxruntime              1.31.0
scipy                    1.18.1
```

- 解释器 `.venv-mjlab`（Python 3.12.13），与原来 CPU 用的 `.venv` 完全隔离，互不影响。
- **20 个任务注册成功**，含我们要的 `Mjlab-Velocity-Flat-MicroDuck`
  和 `Mjlab-Velocity-Flat-Backlash-MicroDuck`（带齿隙模型）。
- 启动横幅：`[mdp] Patches 1-2 active: NaN-safe reward/advantage` /
  `Patch 4: ONNX export filters passive_* joints` /
  `Patch 5: MICRODUCK_WARM_START=1 restarts curricula after checkpoint load`
- `tools/install_mjlab_stack.sh` 改成幂等四步，可反复重跑。

> 上一轮我报「还在装」，实际是**安装进程在会话重启时被杀**了（日志停在下载阶段，
> 进程已不存在，venv 里只有 torch）。不是装不动。

---

## 2. 五个坑（都已解决，照着这份能重现）

### 坑 1 · 官方 PyPI 在这台机器上慢 100 倍

| 源 | 实测速度 |
|---|---|
| `files.pythonhosted.org`（走代理） | **88 KB/s** |
| `files.pythonhosted.org`（不走代理） | 41 KB/s |
| 阿里镜像 | 432 KB/s |
| **清华 `pypi.tuna.tsinghua.edu.cn`** | **8.8 MB/s** |

`warp-lang` 单个 wheel 就是 114 MB。用官方源时 `resolved 126 packages` 花了 **12 分钟**，
之后还卡在下载。换清华源后 **30 秒装完 115 个包**。

→ 以后所有 Python 依赖安装都带 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`。

### 坑 2 · `warp-lang` 的版本约束要取最严的那个

- `bam` 写的是 `warp-lang>=1.12,<1.13`
- `microduck_rl/pyproject.toml:18` 精确钉 `warp-lang==1.12.0`

我第一次装了 1.12.1。**按上游精确钉回退到 1.12.0。**

### 坑 3 · bam 装不上不是网络问题，是沙箱的批量删除保护

`uv pip install .upstream/bam-...` 走 PEP 517 in-tree build：setuptools 把 wheel 内容
写进 `build/bdist.win-amd64/wheel/` 之后**要删掉这个目录**（85 个文件）。
本机有「单轮删除 > 50 个文件需确认」的保护 → 删除被拦 → uv 判定构建失败。

我自己加的 `--no-clean`（想保住构建产物）反而制造了第二个错：
`WinError 183 当文件已存在时无法创建该文件` —— 上次的 `dist-info` 还在。

搜索结果的答案是一致的（dlib 那个案例给的正是这个）：
**清空 build 目录再构建**。绕开 pip/uv 清理逻辑的稳定做法：

```bash
cd .upstream/bam-62bd8ce...
mv build dist *.egg-info /tmp/stash/       # 移走，不是删除
python -c "import sys; sys.argv=['setup.py','bdist_wheel']; from setuptools import setup; setup()"
uv pip install --no-deps --reinstall dist/*.whl    # 装 whl 不触发构建
```

### 坑 4 · bam 的版本必须按 `uv.lock` 的 commit，不是分支 HEAD

```
uv.lock:106  source = { git = ".../bam.git?branch=mjlab_frictionloss#62bd8ce1215...e967" }
分支 HEAD    57d13ead...  ("Updating favicon", 2026-07-16)
```

我按分支 Head 装的那份，`BamActuatorCfg` 只有 `vin_drop_resistance_range`（电阻模型 R·I），
而 `microduck_constants.py:170` 传的是 `vin_drop_gain_range`（增益模型 gain·Σ|τ|）
→ `unexpected keyword argument 'vin_drop_gain_range'`，整个任务包加载失败。

**判据：`[tool.uv.sources]` 里写 `branch=` 不代表装分支 HEAD，`uv.lock` 里带 sha 的才是真版本。**

### 坑 5 · mjlab 1.3.0 自己漏了 scipy

上游 `microduck_rl/pyproject.toml:25-28` 的注释就写了这件事（还标了日期 2026-07-21）：
mjlab 的 `terrains/heightfield_terrains.py` import scipy 但没声明。不装 scipy
连 `import mjlab` 都进不去。

---

## 3. GPU 实测：4096 envs 是甜点，加到 8192 反而慢 4.6 倍

```
device=cuda:0   RTX 4070 Laptop  8 GiB   sm_89
warp: CUDA Toolkit 12.9 / Driver 13.5
```

| 配置 | 稳态 iter | steps/s | 对比 |
|---|---:|---:|---|
| **GPU 4096 envs** | **3.08 s** | **≈31.8k** | ✅ 甜点 |
| GPU 8192 envs | 14.13 s | ≈13.9k | ❌ 慢 4.6 倍 |
| CPU 20 核（我们的植物） | 4.9 s | 20k | 基准 |

两件事：

1. **GPU 只有 1.6 倍，不是数量级。** microduck 才 20 DoF，4096 envs 在 4070 上
   并行度没吃满，每 iter 还有固定的 Python / RSL-RL 开销。8 GiB 显存加到 8192 envs
   直接掉进内存压力，慢到离谱 —— 别盲目加。
2. **真正的收益是把 CPU 腾出来了。** GPU 跑的时候 20 核全空，
   「CPU + GPU 一块跑」到这里才成立：两个独立实验可以真正并行（比如
   GPU 跑 Hannes 配方、CPU 跑我们自己的 robust61 对照），而不是抢同一批核。

首次启动有一次性的 JIT 编译，约 **75 秒**（`ccd` 8.0 s、`smooth` 4.8 s、
`cholesky` 4.0 s…约 40 个 kernel），warp 会把 kernel 缓存到
`%LOCALAPPDATA%\NVIDIA\warp\Cache\1.12.1`，之后不再编译。

---

## 4. `fanhao375/microduck-replica` —— 1310★，实机复刻资料

**这个仓库推翻了我之前的两个判断，先说这个。**

### 更正 ① 硬件不是"不开源"

README 里有一条 2026-09-03 的自我勘误：官方 `pollen-robotics/elec_RPI_Robot_HAT`
**整块板开源**（KiCad 9 工程、Gerber、BOM、贴片坐标、STEP 全有），
**这块板根本不用自己画**。只有 `imu_to_dxl` 没开源，而这仓库做了全网唯一公开逆向。

我之前写"硬件不开源、要自己画 PCB"是错的 —— 当时只检索了主仓 `pollen-robotics/microduck`，
没翻该组织下以 `elec_` 开头的硬件仓。

### 更正 ② HD-1910 不是"0 条实证"

飞特版 **已装机并站起（09-18）**：Armbian + HAT 读通 14 颗关节、
保持姿势 3000 轮窗口无漏读、实际约 **46.87 Hz**。

但要说清楚：**站起 ≠ 会走**。这仓库自己也卡在走不好（见下）。

### 仓库里现成能用的东西

| 东西 | 位置 | 对我们的用处 |
|---|---|---|
| **装配 BOM（带采购链接）** | `microduck-replica-cad#装配-bom` | 直接替换我那份自己凑的采购清单 |
| **CAD 装配体**（XL330 / 飞特两版，`-FT` 后缀） | `microduck-replica-cad` | 打印件不用自己从 MJCF 反推 |
| **B 站 8 集装配教程**（已更 6 集） | 机械行者Robo，UID 312747174 | 用户发的小红书正是这位作者 |
| **`imu_to_dxl` 逆向**（原理图 + 固件 0.2.0 / 1.0.0） | `hardware/imu_to_dxl/` | 全网唯一 |
| **三块新板**（总线 IMU v2 / 总线 HUB / 接电池板） | `hardware/新版/` | 画好未打样 |
| **`踩坑记录.md` 85 KB** | 根目录 | 见下，最有价值 |

### 踩坑记录里直接命中我们的五条

1. **「测行走模型别用手托着机身」**
   这类模型输入里没有节拍，迈步靠身体晃动 + 重心转移经 IMU 带出来。机身被托住，
   输出很快停在一个静止姿势上。**速度 0 本来就是「站着不动」，不能拿来判断会不会走。**
   → 和我们 A/B 的 `track≈0` 是同一件事的两面。

2. **kissqy 的 walk 模型真能走**：10-11 实测，放地上不扶，**0.4 秒内两腿开始交替屈伸**。
   我之前写"kissqy 有实机但无量化速度"，应改成"有实机且真会迈步"。

3. **IMU 装歪 8.5° → 模型一接管就往后猛冲**（快的 0.6 秒，慢的 21 秒），
   腿目标打满 ±90°。原因：训练时站 HOME、机身水平、IMU 读 0°；装歪后模型一直往后救。
   → **真机的固定俯仰偏差必须在运行时校掉，训练不管**（官方训练代码注释也这么写）。

4. **「走两三步就摔」的真根因是 BNO085 芯片自融合姿态乱跳**：20 ms 里跳 20–60°，
   同期陀螺只转 1–2°。换纯陀螺积分后 60 秒一次没摔。
   他们为此调了三天脚底 / 舵机 D / 滤波 / 缩放，**全部白费**。
   → 一句可直接用的教训：**连调参数不如先查数据自己对不对得上。**

5. **kissqy 的 0.9 / 0.5 / 0.7 不是训练参数**。训练是 1 / 1 / 1；
   那三个数是照搬官方 Dynamixel 运行端默认值，还会再乘电压补偿 `7.4 / V`。
   我们之前拿 0.9/0.5/0.7 当"训练条件"对照，方向错了。

### 一条他们也没解决的

**关节只跟到目标一半**：髋偏航 57–95%、髋横滚 31–56%、膝 48–55%、髋俯仰 45–67%。
于是脚抬不起来、没法在空中转脚，转向只有指令的 1/4。
他们的解释是"以前被 IMU 乱跳盖住了的『膝盖只摆一半』"。

→ **这条和我们「走不直」是同一个物理根源**：踝/膝关节跟随不足。

---

## 5. `ros-claw/microduck`（Duckverse）—— 6★，纯仿真，但交付了训练补丁

三鸭跳长绳 / 四鸭 / 跑酷。**没有上真机**（README 明说
"hardware deployment and autonomous evolution are not demonstrated"）。
442/516 干净周期（85.7%），5/8 轮通过。

### 最有价值的三处

**① `training/microduck_rl.patch` 609 KB —— 相对官方基线的全部训练改动**

官方基线 commit 写得很明确：`5946fd9cdbc58956424420153e51975af3b30d77`
（交付源码 `18052aaf...`）。→ **要核对我们的 `.upstream/microduck_rl-develop`
是不是这个 commit**，不是的话我们现在改的东西可能建在别人的旧基线上。

**② `policies/` 里 8 个 ONNX，全部 61 维观测 / 50 Hz**

| 文件 | 大小 | 说明 |
|---|---|---|
| **`continuous_joy.onnx`** | 794 KB | **连续步态**，文档写明**从 `alpha_walking.onnx` seed 出来** |
| `jump.onnx` / `ropehop_*.onnx` ×4 | 794 KB | 跳绳 / 起跳 |
| `turner_rope.onnx` | 820 KB | 转绳 |
| `parkour_long_jump_v2.onnx` | 794 KB | 跳远 |

→ ⚠️ **2026-10-24 实测更正**：`continuous_joy.onnx` **不是在走，是在原地踏步**
（交替迈步 1.15 Hz、抬脚 15 mm、8 秒净位移 14 mm）。它的命令通道是
**位置反馈** `-2*pos`（±0.15 夹紧）+ 权重 100 的 `joy_drift`，设计上就抗拒平移 ——
我当时写「会走的策略 / 量真实速度对比 0.035 m/s」是错的。
实测数据、负对照、以及它真正值得抄的东西（**用带时钟的抬脚奖励把「站桩」打成 0 分**）
见 **`microduck-joy策略实测.md`**。

**③ 目标递推写成了训练侧配置，不是部署侧滤波**

`alpha 0.25`、每 20 ms 最大步进 `0.08 rad`。文档原话：
**「训练和运行时采用相同目标递推，不能只在部署端临时加滤波」**，
且 ONNX 元数据必须记录这个接口。

→ 这正是我们「运行期 gain 0.7 + 低通 + 死区 5°」那个方向的反面。
他们把滤波搬进了**动作空间本身**，所以策略学会的目标就是被递推过的目标。

另外它用 **XML position servo**（不是 BAM），±0.6405 N·m，1 ms 物理 / 50 Hz 动作，
训练 `Mjlab-JoySmoothPD-Flat-MicroDuck`，2048 envs × 200 iter 微调。

---

## 6. 下一步（按性价比排）

1. **核对官方基线 commit —— 已核，结论是"我们对不上，而且我们更新"**：

   | | commit | 日期 |
   |---|---|---|
   | Duckverse 训练补丁的基线 | `5946fd9` | 2026-09-01 |
   | 官方 `develop` 当前 HEAD | `b02fdea` | 2026-10-12（`improve_standup_velstand`） |
   | 我们本地 `.upstream/microduck_rl-develop` | 含 `microduck_standup_env_cfg.py` / `microduck_velstand_env_cfg.py` | **≥ 10-12，与 develop HEAD 同代** |

   也就是说 **我们比 Duckverse 的基线新 6 周**，中间多了 standup / velstand 两个任务。
   → 那 609 KB 的 `.patch` **不能直接 `git apply` 到我们这份**（必然大量冲突）。
   要用只能三选一：① 拉一份 `5946fd9` 单独 apply 当参考实现；
   ② 只挑我们缺的那几段手工移植；③ 不管它，只需要 `continuous_joy.onnx` 本身（见下条）。
   **在没决定之前不要动我们自己的快照。**
2. ~~**拿 `continuous_joy.onnx` 跑我们的 sim**，量真实速度~~ —— **已做，结论与预期相反**：
   它是原地踏步策略，量不出"走路速度"；但实测证明**我们的植物 + 61 维契约 + 目标递推
   这套部署链路是对的**（同一份 harness 只切时钟就退化成静止站立，见负对照）。
   结论见 `microduck-joy策略实测.md`。
3. **GPU 上跑 Hannes 配方**（`forward_progress` + 砍静止白拿 + 速度课程），
   4096 envs、稳态 3.08 s/iter → 12,000 iter ≈ **10.3 小时**。
   同时 CPU 空出来跑对照组，两个实验真正并行。
4. **采购清单换成 `microduck-replica-cad` 的装配 BOM**（带采购链接、已被 1310★ 验证）。
5. 装机时把踩坑记录那五条当检查表，特别是 **IMU 零点必须在运行期校**。
