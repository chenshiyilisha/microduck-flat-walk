# MicroDock / MicroDock v2 打印文件（上游原样拷贝）

- **来源**: `github.com/Vottivott/microduck-playground@052a2494dd`（2026-11-10 经 GitHub contents API 拉取）
- **许可**: 硬件设计文件为 **CC BY-NC-SA 4.0**（`LICENSE-HARDWARE`）；不可商用，改版需同许可共享
- **上游校验**: `uv run hardware/microdock-v2/source/build.py --check`（水密/线头配合/keeper 支承/与 v1 同实体）

## 文件清单（5 件打印件 + 1 个切片工程）

| 文件 | 说明 | 打印方向/支撑 |
|---|---|---|
| `microdock_base.stl` | 底座 195×200×19（3 mm 板+前坡+插板槽） | 平放 |
| `microdock_v2_board.stl` | **v2 专用板**（v1 的 board 是另一块，窗口低 57 mm/浮动更大） | 背面朝下 |
| `microdock_hood.stl` | 浮动 hood（v1/v2 共用） | **倒扣 + 网格支撑**（勿用树状，销钉底面会缺料） |
| `microdock_keeper.stl` | 销扣（⚠️ 必须用上游 2026-11-05 后版本） | 平放 |
| `microdock_tag.stl` | AprilTag tag36h11 #0，1.6 mm 处黑→白换色 | 平放 |
| `microdock_v2_P1S.3mf` | Bambu P1S 三盘工程（已配好方向/支撑/换色） | 直接切 |

三盘合计约 5 h32 min / 240 g PLA（盘1 base 2h09/101g，盘2 board+hood+keeper 3h01/130g，盘3 tag 22min/9g）。

## 零件关系（2026-11-10 哈希核实）

v1 与 v2 **同为 5 件**（base/board/hood/keeper/tag）。v2 只换 board（两版 board 同为 280 三角面但几何不同，
sha256 不同）；hood/base/keeper/tag 四件与 v1 逐实体相同（`build.py --check` 用布尔差体积 <1e-3 mm³ 强制）。
装 v2 = 打 v1 四件 + v2 board；`microdock_v2_P1S.3mf` 里已是这个组合。

## ⚠️ 用于 HD-1910 复刻线的前提

尺寸链中 hood 贴鸭背的参数（口高 4.8/切口 12.1/壳半宽 32.3/滑轨高 40.6 等，见
`docs/active/microdock-v2-从硬件到训练-全链深研-2026-11-10.md` §1.1）按**官方 XL330 鸭**设计；
HD-1910 复刻壳不同，`hood`（及可能连带的 `board` 窗口位置）需按实测重生成后再打。
`base` 与 `tag` 不依赖鸭背尺寸，可直接打。
