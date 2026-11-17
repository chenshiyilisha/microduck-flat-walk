# MicroDuck Android App —— 整体重构与架构重新规划

_2026-11-16。背景：App 自 v0.3.0 后陆续加入 SSH 终端、硬件监控 3D 模型、一键休息、
OTA 更新、AI 调试通道等新功能，`MainActivity` 已达 1460 行，状态管理靠全局单例 +
1s 轮询渲染，结构开始失控。本文给出基于一手资料的重新规划，作为重构执行的单一权威。_

## 1. 现状诊断（代码事实，非感受）

### 1.1 模块盘点

| 层 | 文件 | 规模 | 职责 |
|---|---|---|---|
| core（纯 JVM） | `RobotTransport`/`RobotSession`/四后端 | 会话与传输 | JSON-RPC 会话、BLE/TCP/Mock 链路 |
| core | `DriveController`/`HeadController`/`RestController` | 域逻辑 | 驾驶/头部/休息的 RPC 封装 |
| core | `StateSnapshot`/`HealthSnapshot`/`RobotParts`/`HardwareMonitor` | 状态模型 | 状态帧、健康快照、15 舵机+系统部件、监控判定 |
| core | `DuckMesh`/`DuckModelGeometry` | 3D 几何 | 真实网格加载/投影/Lambert 光照 |
| app | `MainActivity` | **1460 行** | 四页构建 + 渲染 + 连接 + 休息/更新入口，全堆在一起 |
| app | `DriveActivity` | 757 行 | 横屏遥控页 |
| app | `SessionHolder` | 425 行 | 跨 Activity 会话单例，`@Volatile var` 状态散列 |
| app | `SshPanel`/`UpdatePanel`/`BleConnectPanel`/`DuckModelView` | 面板组件 | 各自持有局部状态，与主状态源不统一 |

### 1.2 核心问题

1. **无分层**：UI（Activity）直接持有 `RobotSession`、直接调 core 控制器，没有
   ViewModel / Repository 边界。官方架构指南（developer.android.com/topic/architecture/recommendations，
   2026-11-16 核验）「Strongly recommended: Use a clearly defined data layer」「UI 层组件
   不得直接与数据源交互」。
2. **状态散列、无单向数据流**：`SessionHolder` 用 20+ 个 `@Volatile var` 承载状态，
   两个 Activity 各调 `tick()` 轮询后 `renderAll()`。这是「UI 主动拉」而不是官方指南
   的 UDF（状态向下流、事件向上流，ViewModel 暴露 StateFlow、UI 生命周期感知收集）。
3. **MainActivity 职责过载**：连接管理、四页构建、遥测渲染、模型刷新、休息/更新
   入口、弹窗处理全在一个类，任何新功能都继续往里堆。
4. **面板状态源不统一**：`SshPanel` 自管 session、`UpdatePanel` 自管下载状态，与
   `SessionHolder` 的会话状态没有单一真源（SSOT）关系。
5. **3D 模型状态表达错位**：15 舵机状态用「叠加圆点」表达（`DuckModelView`），
   模型本体只是静态外观。监控设计惯例是**颜色即状态**（见 §2.2），圆点方案与
   模型本体割裂，且用户明确要求去掉圆点、改为部件变色。

## 2. 调研依据（一手出处）

### 2.1 Android 官方架构指南（2026-11-16 检索核验）

来源：developer.android.com/topic/architecture/recommendations、
developer.android.com/jetpack/docs/getting-started（应用架构指南）。

- **分层架构**：UI 层（显示数据 + 交互）+ 数据层（业务逻辑 + 数据源）；
  小应用数据层可放 `data` 包。**Strongly recommended**：数据层暴露应用数据、
  Repository 即使只有一个数据源也要建、UI 层不得直接碰数据源。
- **UDF（单向数据流）**：**Strongly recommended**。状态向下流、事件向上传；
  ViewModel 处理事件后更新状态，UI 观察状态变化。
- **ViewModel + StateFlow**：**Strongly recommended**。ViewModel 不持有
  Activity/Context/Resources；通过名为 `uiState` 的单个属性（StateFlow）暴露
  UI 状态；界面用生命周期感知方式收集。
- **SSOT（单一数据源）**：用户事件进 SSOT 修改数据，以不可变类型暴露，
  保证一致性、可调试。
- **协程与 Flow**：**Strongly recommended**，层间通信用 Flow。
- 域层（use case）仅在「大应用、多 ViewModel 复用」时推荐——本项目规模
  **不引入**，core 的三个 Controller 已承担域逻辑职责。

### 2.2 监控界面 3D 模型设计惯例（2026-11-16 检索核验）

来源：数字孪生工业监控方案（《数字孪生驱动的工业生产过程可视化监控系统》、
UE5 数字孪生参数化材质实践、具身智能 QT 人机界面方案等）。

- **颜色即状态**：温度/健康用**红-黄-绿颜色梯度**映射（如 >350℃ 红、
  250–350℃ 黄、<250℃ 绿）；UE5 做法是母材质暴露 `StatusColor` 向量参数，
  数据传入时实时改部件自发光/颜色（「温度过高时机柜泛红警报」）。
- **模型本体干净**：3D 模型承载状态着色本身，不叠散点标记；状态灯/告警用
  状态色 + 必要时闪烁，不用与模型割裂的标记层。
- **阈值预警**：超阈值部件变色/闪烁报警，其余部件保持常态配色。
- 映射到本项目：**舵机/硬件部件按 `Severity`（OK 绿/WARN 琥珀/CRITICAL 红/
  UNKNOWN 灰）直接给模型部件着色**，无证据一律灰（项目铁律 `UNVERIFIED != PASS`
  的可视化表达），替代当前的圆点叠加。

### 2.3 架构演进资料（MVC→MVP→MVVM→MVI）

核心结论与官方指南一致：控制权从「主动调用」收拢为「被动响应」，数据流单向化。
本项目重构不引入 MVI 的完整事件密封类体系（规模不足以摊薄成本），采用
**MVVM（Views 体系）+ UDF + Repository**。

## 3. 目标架构

```
┌─────────────────────────────────────────────────────────┐
│ UI 层（app 模块，Views + Material 1.12）                  │
│  MainActivity ── 持有页面 ViewModel，只做：                 │
│   · 收集 uiState → 渲染（生命周期感知）                     │
│   · 用户事件 → 调 ViewModel 方法（不碰数据源）              │
│  DriveActivity ── 同上（遥控页）                            │
│  面板组件（SshPanel/UpdatePanel/BleConnectPanel/           │
│   DuckModelView）── 纯展示 + 事件回调，不持有业务状态        │
└─────────────────────────────────────────────────────────┘
          ↑ uiState (StateFlow)        ↓ 事件（方法调用）
┌─────────────────────────────────────────────────────────┐
│ ViewModel 层（app 模块，新增）                              │
│  MainViewModel（状态/健康/设置/终端四页的 uiState 聚合）     │
│  DriveViewModel（遥控页状态）                                │
│  职责：组合数据层 → uiState；处理事件 → 调数据层              │
└─────────────────────────────────────────────────────────┘
          ↑ StateFlow                    ↓ 调用
┌─────────────────────────────────────────────────────────┐
│ 数据层（core 模块，纯 JVM，已有骨架，补 Repository 边界）   │
│  RobotRepository ── 封装 RobotSession：连接/断开/状态/      │
│     健康查询，以不可变快照（StateSnapshot/HealthSnapshot）   │
│     经 Flow 暴露；会话唯一持有者                              │
│  SshRepository ── 封装 SshClient 连接与命令执行              │
│  UpdateRepository ── 封装 OTA 检查/下载/安装状态             │
│  域逻辑：DriveController/HeadController/RestController      │
│  （core 已有，不动）                                        │
└─────────────────────────────────────────────────────────┘
```

### 3.1 关键决策

1. **不换 Compose**：项目已定 Views + Material 1.12（build.gradle.kts 注释），
   重构是**分层**而非换 UI 工具链。官方「Use Jetpack Compose」针对**新应用**，
   存量 Views 应用按指南做 ViewModel + UDF 即可，重写 UI 的收益不抵风险。
2. **SessionHolder 改造为 RobotRepository 的会话持有者**：跨 Activity 共享
   一条链路是真实需求（DriveActivity 与 MainActivity 共用连接），但状态不再
   以散列 `@Volatile var` 暴露，而是 Repository 内部持有会话、对外只暴露
   不可变快照 Flow。`SessionHolder` 的遥测计数等 App 自观测字段保留，但统一
   由 Repository 推进。
3. **渲染从轮询改状态驱动**：`renderAll()` 1s 轮询逐步替换为收集
   `uiState`；3D 模型的 1s 步进旋转保留（性能约束不变），但**状态着色**
   随 uiState 更新，不随 tick 重算。
4. **3D 模型部件归属**：`duck_mesh.bin` 当前只有顶点/三角形/颜色，无部件标签。
   重构需要给网格增加「三角形 → 部件」映射（见 §4），才能按部件着色。

## 4. 分阶段执行计划

每阶段结束必须过全套门禁：core 自检（`bash tools/selftest.sh`，现 492 项）、
`check_all_app_gates.py`、真机门禁 `device_ui_check.py`（59 项）、lint、CI。
**任一阶段门禁不绿不进下一阶段。**

### 阶段 0：基线冻结（0.5 天）

- 记录当前全绿基线（core 自检 492/492、门禁、APK 版本 v0.3.1）。
- 本规划文档入库（`docs/active/`），作为重构期间的决策依据。

### 阶段 1：数据层 Repository 化（1–2 天）

- core 新增 `RobotRepository`：封装 `RobotSession` 的创建/连接/断开/重连，
  对外暴露 `StateFlow<RobotSnapshot>`（不可变，含 kind/连接状态/lastState/
  lastHealth/遥测计数）与 `suspend fun` 动作（connect/disconnect/refreshHealth）。
- `SshRepository`、`UpdateRepository` 同理：把 `SshPanel`/`UpdatePanel` 里
  自管的 session/下载状态收进 Repository，面板只调 Repository、只收状态。
- **迁移原则**：先加 Repository 并让旧路径继续工作（双轨），UI 暂不改，
  门禁保持绿后再切 UI。

### 阶段 2：ViewModel 层与 UDF（1–2 天）

- 新增 `MainViewModel`：聚合四页 uiState（状态页/健康页/设置页/终端页各自
  的展示状态），暴露为 StateFlow；处理事件（切页、切模式、连接、休息、
  更新）后更新状态。
- `DriveViewModel` 同理（遥控页）。
- MainActivity/DriveActivity 改为：`viewModel.uiState.collect { 渲染 }`，
  删除 `renderAll()` 轮询中可被状态覆盖的部分；保留 1s tick 仅用于
  3D 模型旋转步进与遥测采样（这两项是时间驱动，不是状态驱动）。
- 依赖注入不引入 Hilt（规模不足）：ViewModel 用工厂手动构造，
  Repository 由 Application 级单例提供（替代 SessionHolder 的全局性，
  但状态出口统一为 Flow）。

### 阶段 3：面板组件状态解耦（1 天）

- `SshPanel`/`UpdatePanel`/`BleConnectPanel` 改为「纯展示 + 回调」：
  构造时传入状态 + 事件回调，内部不持有 session、不自管下载状态。
- `DuckModelView` 改为「接收部件状态映射 + 网格部件归属」的纯渲染组件
  （见 §5）。

### 阶段 4：3D 模型状态着色重构（1–2 天，用户当前需求）

详见 §5。与阶段 3 的 DuckModelView 改造合并执行。

### 阶段 5：收尾（0.5 天）

- 删除 `SessionHolder` 散列状态（迁移完的字段逐个删，不留双真源）。
- 全量门禁 + 真机截图目视验收（模型着色、四页、遥控页、终端页）。
- 更新本文档与开发规范文档，记录最终结构。

## 5. 3D 模型状态着色重构专项（阶段 4 详细设计）

### 5.1 目标

- **去掉 15 个圆点**，状态直接落在模型部件本体颜色上（监控设计惯例：
  颜色即状态）。
- **舵机可变色**：15 个关节对应的模型部件按 `Severity` 着色。
- **其他硬件部件可变色**：躯干/电池/SoC/IMU/总线/链路等 SYSTEM 部件
  同样可着色（有健康证据时变色，无证据保持官方配色或灰色）。
- 模型本体保持官方 Cream 配色作为「常态」，状态着色是叠加层。

### 5.2 网格部件归属（数据层扩展）

- `tools/build_duck_mesh.py` 扩展：提取时按 MJCF `geom_group==2` 的 mesh
  归属，为每个三角形记录**部件索引**（与 `RobotPart` 或新设的
  `ModelPart` 枚举对应）。
- `duck_mesh.bin` 格式升级（DMSH v2）：header 增加 `n_parts`，triangles 后
  追加 `n_tris × uint8` 部件索引数组。**v1 解析器保留**（自检里加
  版本分支负对照），v2 由新解析器读取。
- 部件映射表：`ModelPart`（纯 JVM，core）列出模型上可着色的部件：
  15 关节对应模型上的舵机/连接骨架部件（`upper_leg_*`/`ankle_*`/`xl330` 等
  生成期已识别的部件名）+ 躯干/头/电池仓等 SYSTEM 对应部件。
  映射必须来自生成期实际提取的部件清单（生成脚本输出清单核对），
  **禁止手写猜映射**（项目铁律：命名真源来自一手数据）。

### 5.3 着色规则（渲染层）

- 每个三角形有「基色」（官方配色，来自 v2 网格）+「状态色」（按部件
  severity 映射，`RobotParts.severityArgb` 单一真源）。
- 着色规则：
  - 部件 severity = UNKNOWN → 用基色（不造状态色，铁律 `UNVERIFIED != PASS`）。
  - OK → 绿色调叠加（低强度，避免整机刷绿失真；具体强度在离线预览里
    目视定，写进自检判据）。
  - WARN → 琥珀色；CRITICAL → 红色（可加闪烁/高亮描边，与监控惯例一致）。
  - Lambert 光照保留：状态色同样过 `shadeColor`，保证立体感。
- 渲染顺序不变：不透明填充 + 深度排序。

### 5.4 验收判据（产物级，不靠目视猜）

- core 自检新增：v2 格式解析、部件索引越界检查、着色规则单测
  （UNKNOWN 用基色、CRITICAL 用红的正/负对照）。
- 离线预览：`tools/MeshPreview.java` 扩展，输出「基色版 + 全 UNKNOWN +
  模拟 WARN/CRITICAL」三张 PNG，**必须真的打开看**（项目教训：
  文本门禁全绿照不出视觉问题）。
- 真机截图目视：健康页模型着色与舵机状态卡一致。

## 6. 风险与不做清单

**不做**：
- 不换 Compose、不重写渲染管线（Canvas 软件投影 + Lambert 保留）。
- 不引入 Hilt/依赖注入框架（手动工厂足够）。
- 不引入域层 use case（core Controller 已够）。
- 不重训、不动训练侧任何代码（本规划只涉及 App）。
- 不在重构中顺带改功能行为（行为变更单独提交、单独说明）。

**风险**：
- 双轨期（Repository 与旧路径并存）可能产生双真源 ⇒ 阶段 1 的 Repository
  必须是旧路径的**唯一数据出口**，旧路径读 Repository，禁止两边各自维护。
- 1s tick 与 StateFlow 并存时，遥测采样去重逻辑（既有 `lastSampleMs`
  窗口去重）必须保留，防止两 Activity 交替踩状态（既有真机 bug）。
- 3D 模型着色若基色与状态色叠加不当会失真 ⇒ 离线预览目视定强度，
  不拍脑袋。

## 7. 现状快照（重构基线）

- core 自检：**492/492**（含 REST 9 项，2026-11-16）。
- 提交基线：`3c47869`（模型悬空分离根治）已 push。
- App 版本：v0.3.1（真机已装）。
- 门禁工具：`check_all_app_gates.py`（动态发现 `--selftest` 工具）、
  `device_ui_check.py`（真机 59 项，当前 UNVERIFIED——装包后待复跑）。
- 2026-11-16 同日修复：终端页按钮超长折行（快捷命令标签缩短 + 全按钮
  `maxLines=1` + ellipsize 兜底；updaterd 按钮文本精简，警示语义移入
  说明文字与确认对话框）。

## 8. 阶段 5 落地记录：全息渲染 + 网格重建（2026-11-17）

### 8.1 网格还原度（「不够还原」的真因）

- 旧 `duck_mesh.bin` 由**顶点聚类**简化而来：大 geom 被压塌（实测某支架 z 跨度
  -22%~96%、整机高宽比 1.26→1.85）——渲染风格救不回几何失真。
- 🔴 后端实测铁证（写进 `build_duck_mesh.py` 头注）：fast_simplification（trimesh
  `simplify_quadric_decimation` 底层）与 pyfqmr 是同一受限 C++ 内核，对 CAD 网格有
  「质量地板」——请求 80 面实际输出 14044 面，`agg=10` 也压不动。判据=请求面数 vs
  实际输出面数是否一致。
- ✅ 换 **pymeshlab QECD**（MeshLab 参考实现）：全部块精确到目标面数且保形
  （7 代表块 req300 全部 out=300、收缩 ≤3%）。产物 796,844 → **11,956 面**，
  最大部件收缩 20%。工具自检 31/31、core 自检 549/549。

### 8.2 数字孪生全息渲染（用户确认效果图后落地）

- 用户对照两张参考图提出「模型能不能做成图片的这种效果」，离线迭代 v9–v14 确认
  路线后落地。**路线 = 图像空间提边**（游戏引擎 outline 后处理标准做法）：
  超采样 z-buffer 光栅化（精确遮挡 + 部件 ID）→ 外轮廓/部件分界提边 →
  覆盖率抗锯齿（16 级能量守恒渐变）→ HDR 三级 bloom → Reinhard → 合成。
  几何提边路线（Markosian/零交叉/EdgesGeometry）在 38 个嵌套零件上必然漏线。
- 落地为 core **`HoloRenderer.kt`**（纯 JVM 像素管线，可被自检真跑）；
  View 只做 `Bitmap.setPixels` + `drawBitmap`。状态色单一真源仍是
  `RobotParts.severityArgb`（HoloRenderer 禁止自造 RGB，自检有负对照）。
- View 性能架构：内部渲染尺寸上限 520px（拖动 400px）+ SS 3/2 分档 +
  **后台单线程渲染、最新优先去重、UI 只贴图**（桌面稳态 42ms/帧，手机 3~5 倍，
  同步渲染必卡帧 + uiautomator idle 死锁老坑）。
- 性能优化（分阶段计时定位，非猜）：bloom 高斯→前缀和盒式（60→5ms）、
  投影内联去对象分配、光栅改增量边函数（28→9ms 段）。98→**42ms/帧**。
- 🔴 教训（负对照的价值）：增量光栅首版把行基值 y 写成循环外常数，整帧碎成
  竖条纹——文本门禁全绿（覆盖率断言 0.075 仍在带内）照不出来，**目视负对照**
  抓出来的。验证问「量动没动/量级对不对」之外，纯视觉改动必须真的看图。

### 8.3 门禁变化

- `check_hardware_monitor.py`：视图断言从「调用 `DuckMesh.project(...sevOf)`」
  升为「`HoloRenderer.render(m, angleDeg, iw, ih, sevOf, …)` 第 5 实参注入」+
  「HoloRenderer 取 severityArgb」+「z 测试代码存在」，三条均配注入式负对照
  （自检 35/35）。CoreSelfTest 新增 `[HOLO]` 组：像素尺寸/不透明/覆盖率（取自
  光栅化计数，亮度统计会把背景算成模型——首版假绿 0.995）/状态色正负对照/
  旋转差异/幂等。

### 8.4 遗留

- 真机项全 UNVERIFIED（手机 CM_PROB_PHANTOM 需重插线）：59/59 门禁复跑、
  全息渲染真机截图目视、拖动流畅度实测（HOLO_LOG 打点）。
- `MeshPreview.java`（Java 参考实现）与 `HoloPreview.kt`（真机同源渲染）并存，
  后者是移植一致性的核验工具。
