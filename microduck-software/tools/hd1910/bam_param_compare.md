# HD1910 BAM 参数对照（阶段 B 并行产出）

日期 2026-10-26。一手文件，禁止把陆吾当训练主植物。

| 量 | OpenMicroDuck m5 | 飞特官方 m6 | 陆吾 `l_1910_m6`（禁） |
|---|---|---|---|
| 路径 | `tools/bam_params/hd1910/m5.json` | `tools/bam_params/hd1910/ftservo_official_m6.json` | `.upstream/l_1910_m6.json` |
| `actuator` | `hd1910` | `HD1910`（本地已改大小写） | **`sts3215`（错标）** |
| `model` | m5 | m6 | m6 |
| `kt` | 0.692 | **0.564** | 0.624 |
| `R` | 3.75 | **2.966** | **4.910** |
| `armature` | 0.00224 | 0.00183 | 0.00178 |
| `command_delay` | （无字段） | 0.00098 s | 0.0060 s |
| `friction_base` | 0.0136 | 0.0120 | 0.0158 |
| `friction_viscous` | 0.00807 | 0.00477 | 0.00031 |
| 控制类 | OpenMicroDuck `HD1910Actuator`（vin 标称 5 V 辨识，`max_current=3.25`） | 飞特 `bam.feetech.HD1910Actuator`（vin=7.4，`error_gain=0.163`） | 会走 STS3215 控制律 → **禁用** |

读法：

- 飞特 vs OpenMicroDuck：电阻差 ~21%，kt 差 ~18%；官方多 `command_delay`。
- 陆吾 R=4.91 与飞特 2.97 差一截（fanhao 文档也写过堵转力矩推算分歧）；且 actuator 错标，**A/B 只比 m5↔飞特 m6**。
- 上游原版 `feetech_hd1910_7_4V/m6.json` 仍写 `actuator: hd1910`；本仓拷贝改成 `HD1910` 以匹配官方表键。

下一步：`tools/hd1910/ab_train.sh`（等 4096 结束后跑）。

## 安装纪律（2026-10-26）

| 包 | 角色 |
|---|---|
| `.upstream/bam-62bd8ce…` editable | **训练/评测用** mjlab 集成（`vin_drop_gain_range`） |
| `.upstream/ftservo-bam` clone | **只读**官方参数与 HD1910 控制类源码；勿 `pip install -e` 盖掉上一行 |
| `tools/bam_params/hd1910/ftservo_official_m6.json` | 官方 m6 数字 + `actuator=HD1910` |
