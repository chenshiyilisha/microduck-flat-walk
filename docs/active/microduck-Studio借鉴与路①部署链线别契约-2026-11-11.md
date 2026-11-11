# Studio / 官网一手借鉴 与 路① 部署链线别契约（B5）

_2026-11-11，Pass107。起因：用户连续追问「陆吾是不是还有一个 studio」「microai-lab/microduck-studio 有什么值得借鉴」「xgorobot.com/duck.html」「开发者指南里的 Arduino App Lab 能借鉴吗」，随后要 fanhao 打印文件准备开工。_
_主线仍按上一轮建议推进 B5：路① 中控链几乎零工具覆盖，是最大线别错配风险。_

## 0. 结论

1. **两条「studio」是四个不同东西**：陆吾组织 25 个公开仓**没有** studio 命名仓；`studio.webp` 只是官网产品主图文件名；真正叫 Studio 的是 `microai-lab/microduck-studio`（MIT，另一作者）和 kissqy 的「训练中控 R1.5.27 / Training-Studio」。陆吾的软件形态是**设备端网页控制台 9527** + **电脑端一键烧录软件**。
2. **microai-lab Studio 值得借的是「边界与验证契约」，不是代码**：它是官方 XL330 / `duck-ipc-proto` 线，与路①（Radxa + HD-1910 + ID200 + kissqy 中控）不是一条线。11 条不变量已逐条落到本仓已有护栏，见 §2。
3. **官网/开发者指南最值钱的一条**：「不能仅凭绿色完成提示认定所有镜像都已下载成功」＋「`started successfully` 之后仍要看 Python 日志三项证据」。这是本项目「回读 PASS ≠ 持久 PASS」「只测内部函数不测 CLI 全绿假象」的同型判据，已升格为 B10。
4. **B5 查出的真冲突**：`deploy_import_checklist.md` B1/B13 仍写「HD-1910 只能用 B 代」「主控 = Orange Pi A733 / 500k / reg6 逐颗写」，与 SSOT 订正⑬（Radxa 1GB / 1M / reg6 免写 / R17→V167 中控）**直接矛盾**；部署链文档的 `uv run publish → robotctl policy load` 是 B 代链，被单独引用就会变成路① 错配。
5. **打印包已交付**：`out/deliverables/fanhao-飞特HD1910-打印包-2026-11-11.zip`，3mf / PDF / BOM 三个文件的 git blob sha 与上游 master API 逐个一致；`00-打印前必读.md` 写明 `-FT1` 面壳、TPU 件与本项目「先别打」清单（§6）。

## 1. 把四个「studio」拆开（一手核验）

| 来源 | 到底是什么 | 端口 / 形态 | 线别 |
|---|---|---|---|
| `LuwuDynamics` 组织 | GitHub API `orgs/LuwuDynamics/repos` = **25 个公开仓**；搜 `LuwuDynamics studio in:name` / `xgoduck studio` / `xgorobot studio` **total_count 全为 0** | — | 无 studio 产品 |
| `xgorobot.com/duck.html` | `images/duck/studio.webp` 是 **og:image / 首屏产品主图文件名** | — | 不是软件 |
| `xgoduck_runtime_arduino` | 设备端**网页控制台**，Arduino App Lab 跑应用后浏览器访问 | `http://设备IP:9527/` | 陆吾线（UNO Q） |
| `xgoduck_community` | 纯 HTML/CSS/JS 社区作品投稿站，Node 22+ 构建、零第三方依赖 | — | 不是控制台 |
| `luwu_os` | CM4/CM5 嵌入式桌面 OS（Qt C++ Launcher + PySide6 Apps） | — | 不是 Studio |
| `microai-lab/microduck-studio` | FastAPI + Compose 开发工作台，接官方 `microduck` / `microduck_rl` | `127.0.0.1:8090` | **L3 官方 XL330 线** |
| kissqy `Microduck-Training-Studio-R1.5.27` | **训练中控**（另一套 ZIP） | 8092 | 路① 的训练侧，不是机器人中控 |
| kissqy `Microduck-Console-R17-V167.zip` | **本项目路① 的机器人中控** | `127.0.0.1:8090` | **L1** |

🔴 **8090 撞车**：kissqy V167 中控与 microai-lab Studio 都用 `127.0.0.1:8090`，同一台开发机不能同时开；契约里登记为 `port_conflicts`，不默认可共存。

### 官网 duck.html 的一手增量

- **一键烧录软件**（电脑端 ZIP）5 个平台：`win32-x64` / `darwin-arm64` / `darwin-x64` / `linux-x64` / `linux-arm64`，并给「查看历史版本与校验文件」入口 ⇒ **版本配对 + 可复现做卡**的第三方互证（对应 B2 / B8），但未下载实算 sha，不进 B2 四元组。
- Arduino App Lab 明确标 **「非官方 · 群友优化版」** Windows EXE 804.1 MB，页面未见 sha256 ⇒ **边界声明可借、无校验分发不可借**。
- 功能边界写得极诚实：「前向避障不等同于自主导航」「坐站、踢球和翻滚尚未接入当前运行端，需自行训练、适配并验证」「叼取是预训练动作，不包含物体识别/目标定位/自主寻找」「影片为实机原型演示，功能以 GitHub 开源项目提供的内容为准」。
- 硬件交叉验证：整机套件 ToF = **8×8 VL53L5X**（与本项目收口的 **VL53L5CX V2** 同族）；电池 **8.4V >3500mAh >3C 18650 组**，与本项目 NP-F550 2200mAh 双电不是同一体系，不可套载流结论；主控 **Arduino UNO Q 2GB** ≠ 本项目 Radxa Zero3W 1GB。

## 2. 11 条可借鉴不变量（都带一手出处，已落到本仓）

| # | 不变量 | 一手出处 | 落地到 |
|---|---|---|---|
| B1 | 不复制兄弟仓职责 / 不是第二份真相 | `microai-lab/.../AGENTS.md:3-12,38-43`；`ROADMAP.md:29-30`；**fanhao `软件来源与我们的改动.md:38` 互证**「中控改动不放进本仓库，自己写引导页调他的接口」 | B5 契约**不复制** `current_line` / `refuse_for_signoff`，运行时从 `line_labels.json` 读并断言 |
| B2 | HTTP 绝不接受任意 shell（allowlist argv + `shell=False`） | `AGENTS.md:44-47`；`jobs.py:10,40-52,63-68` | B8 `reproducible_card.py` 绝不执行 dd/写卡 |
| B3 | 持久单连接 + 通知/请求分离；每请求开新 socket 会静默取消运动 | `AGENTS.md:53-59`；`protocol.py:75-78` | B1 服务状态判据不得只看单次 200 |
| B4 | 拒绝必须到 UI，**字节写出去 ≠ 成功** | `AGENTS.md:58-59`；`protocol.py:21-26` | A2 `UNVERIFIED != PASS`；B1 `--record` 只写 `COLLECTED` |
| B5 | deadman 最后安全层；隐藏/断连/超时必停 | `AGENTS.md:56-57`；`verify_contract.py:103-126,234-248`；官网「页面离开、转入后台或控制数据超时后停止位置控制」 | B1 停止/急停判据覆盖三类 |
| B6 | 启动契约探针：钉 ref/revision/scene + 策略清单 + 传感器帧 + **运动/停止/断连三段** | `verify_contract.py:153-249`；`dev-stack.sh:460-462` | B2 `--verify-sources` 实算；判据用**位移跨度**非「请求已发」 |
| B7 | 策略 pin 不复用 alpha / 离线 seed 成功 ≠ 就绪 / manifest 拒路径穿越 | `test_runtime_policies.py:32-82` | B2 `UPSTREAM_PUBLISHED` / `UNOBTAINABLE` / `UNPINNED` 一律不算 `LOCAL_COMPUTED` |
| B8 | 任务记录 argv/cwd/时间戳/exit_code/日志，默认禁训练，graceful terminate | `AGENTS.md:63-72`；`jobs.py:13-28,54-85,110-115` | A3 报告带 interpreter / known_gaps / 契约 sha256 |
| B9 | 显式 ROADMAP 列已知缺口 + 功能边界写进购前须知 | `ROADMAP.md:23-30`；官网购前须知 | B5 `scope.known_gaps`；仿真任务 ≠ 实机可用 |
| **B10** | **绿色完成提示 ≠ 成功，必须下游实跑 + 三项日志证据** | 开发者指南 `index.html §1.5` 截图日志说明（Docker 镜像拉取超时）；`04-start-app.html §4.5-4.6`「`started successfully` 之后仍需等 Python 日志初始化」 | B1 判据需登记可观测证据；A3 真跑 CLI 非只测内部函数 |
| **B11** | 示例值不是权威值；前置条件逐项完成且失败不得跳过 | `04-start-app.html §4.2-4.4`「Tab 补全目录名，避免照抄错误文件夹」「两个脚本是两项配置，需分别完成」「不要跳过失败的命令继续启动」 | B2 四类证据分级；B8 前置条件与禁用 flag |

**开发者指南第四步命令链**（仅作机制参照，**不可移植到路①**）：`cd ~/ArduinoApps/<实际目录>` → `python3 tools/prepare-bridge.py`（RouterBridge/RPClite 库补丁）→ `sudo bash tools/router-2m.sh`（Router 串口 2 Mbps 并重启）→ `arduino-app-cli app start "$PWD"`；随后看 `WebUI: ...` / `Network URL: http://设备IP:9527` / `App: App started` 三条日志。库缓存更新后必须重跑 `prepare-bridge.py`。

## 3. 不能照搬的边界

- **microai-lab Studio 是官方 XL330 / `duck-ipc-proto` 线**：依赖官方 v8 策略、官方 robotd、`robotctl monitor/health`、Docker Compose + MuJoCo；不认 HD-1910 / ID200 / FT6 / kissqy 中控。`README.md:329-332` 还明写「Studio has no authentication. Keep it on 127.0.0.1 or a trusted LAN. Robot safety and motor control remain the responsibility of robotd」；`ROADMAP.md` 要到 **v0.4** 才做急停/限速/控制租约/审计与仿真-实机观测差异报告。
- **Arduino App Lab 不能移植**：UNO Q 专用、`sketch/` + `app.yaml` + Bridge 2 Mbps、群友优化版 EXE 无 sha、设备端 9527。
- **`--no-camera` / `--no-tof` 之类的裁剪 flag 不能抄**：本项目订正㉑ 已拍「相机 + ToF 必需不可砍」，B8 契约把它们列为禁用。
- **fanhao 的 `banana_pcb_locker` / `power_support` 不能照打**：订正㉕ 取电改人人 HUB ¥36，几何 `INCONCLUSIVE_DIMENSION` 待到手卡尺。

## 4. B5 查出的线别冲突（一手对照）

| 来源 | 原话 | 判决 |
|---|---|---|
| SSOT `…最优方案…md:22` 订正⑬（2026-11-10 拍板） | 「部署链 **R17→V167 中控**（非 `uv run publish`）」；Radxa 1GB / 1M / reg6 出厂 0 免写 / 官方 ID 20-34 + IMU200 | **唯一现行判决** |
| `deploy_import_checklist.md` **B1** | 「两代 schema 不通用，HD-1910 **只能用 B 代**」 | `SUPERSEDED_BY_SSOT_13`：照抄会让路① 按 500k / ID1-15 / reg6 逐颗写配置，整机起不来 |
| `deploy_import_checklist.md` **B13** | 「主控已定为 Orange Pi Zero 3W（A733），`BAUD_RATE` 保持 500_000，15 颗必须逐颗把 reg6 从 0 改成 1」 | `SUPERSEDED_BY_SSOT_13`：11-06 旧拍板，与 11-10 最终判决直接矛盾 |
| `…策略导出部署链…md §1.3` | 「`sudo robotctl policy load walk <repo>`……这是 B 代 robotd 的 `robotctl`」 | `LINE_SCOPED_NOT_L1`：文档对 B 代**是对的**，但脱离抬头单独引用即错配 |
| 四源对照 §5 / `line_labels.json#shared_not_discriminators` | ~~`policy.gain=200` 是 B 代硬错配~~ | `CORRECTED_NOT_A_DISCRIMINATOR`：`gain=200` 是 XL330 参考值 / `KP_REFERENCE=200`，`gain=8` 才会写 reg50=1 使机器人瘫软 |

🔴 **同名不同物 `robotctl` 三义**：B 代 `robotctl policy load`（L2）/ 官方 `robotctl monitor|health`（L3，Studio 用）/ 路① 中控**根本没有 robotctl 命令**（电脑端 ZIP + 浏览器 8090 + SSH）。契约里按 token 登记全部 sense 与消歧规则。

## 5. B5 落地件

| 文件 | 作用 |
|---|---|
| `microduck-software/tools/hd1910/deploy_chain_contract.json` | 三条链 + 5 个歧义 token + 4 条 SUPERSEDED + 11 条 borrowed + 3 份外部一手来源 + Scope，单一主人 |
| `microduck-software/tools/hd1910/check_deploy_chain.py` | 结构校验、集合相等断言、跨线拒绝、`--check/--json/--ship-gate/--selftest/--list`，stdlib-only 只读 |
| `microduck-software/tests/test_deploy_chain.py` | 8 个回归测试，含 CLI 真跑与契约腐化负对照 |
| `microduck-software/tools/hd1910/line_labels.json` | 纯追加 1 条 `META_GUARD`（22 → 23 条登记） |

设计要点：

- **不是第二份真相**：契约里**不写** `current_line` / `refuse_for_signoff`，校验器运行时读 `line_labels.json#policy`；把 labels 的 `current_line` 改坏，结构校验必红（负对照已验）。
- **集合相等断言**：`required.chain_ids / ambiguous_tokens / superseded_ids / borrowed_ids` 与实体逐项相等，删条目必红（借 `open-microduck check_book.py`）。
- **SUPERSEDED 不是删除史料**：每条必须带 `source / claim / verdict / superseded_by / why_it_matters / evidence`，少一个就红。
- **borrowed 不许只抄不落**：每条必须带 `source / quote / adopted_as`，少一个就红。
- **跨线拒绝**：`assert_for_line()` 在 `enforce=False` 时返回 `WOULD_ALLOW:`，证明门禁不是空操作。
- **`ship_verdict` 恒 `NOT_SHIPPABLE`**：L1 的 `still_owed` 五项（15 关节 `identify` / `p8head_2999` 在 V167 能否加载 / control.43 / 手柄 mapping / 5GHz Wi-Fi）全部未做，结构全绿也不升格。

## 6. 顺带交付：fanhao 打印包

`out/deliverables/fanhao-飞特HD1910-打印包-2026-11-11.zip`（34.0 MB / 14 条目，`out/` 已被 gitignore，不入库）。内含：

- `01-打印工程/microduck-飞特版-BambuStudio2026-11-02.3mf` — git blob `7ba46be4…` **与上游 master API 逐字节同源**；本地 `.upstream/` 那份 10-20 版是旧的，未收。
- `01-打印工程/…-标注版.3mf` — 本项目派生，**只改 15 个对象的显示名**，几何 / 盘面 / 切片参数一字未改；`【不打-金属替换】` 7 件 + `【轮滑变体件】` 8 件两组前缀。
- `02-装配说明书/microduck装配安装说明书.pdf`（21 页）、`03-BOM/装配BOM-机械行者Robo-2026-11-02-带采购链接.xlsx`（33 打印件 + 24 外购件）— 两者 git blob 也与上游一致。
- `04-FT1面壳与改动件STEP/STEP-changed-parts-FT-2026-10-20.zip` — **含 `face_part_面部零件-FT1适配瑞莎原版摄像头 改了孔距.STEP`** 与 `合体轮胎.STEP`。
- `00-打印前必读.md`、`06-校验信息.txt`、`07-不打清单-7件金属替换件.md`、`08-轮滑件在哪与走路版取舍.md`、`05-盘面预览/盘1..5.png`。

🔴 **打印前四条硬提醒**：① 3mf 工程里**没有 -FT1 面壳**（逐件解析 `Metadata/model_settings.config` 确认），本项目用 IMX219 + Radxa 必须把 FT1 STEP 导出 STL 替换默认面壳；② `jaw_soft_软下巴` / `soft_mouth_top_软嘴顶部` 必须 TPU，合体轮胎仅轮滑版用且同为 TPU；③ `banana_pcb_locker` / `power_support` / IMU 座 / 主控腔 HAT 固定位按人人实物重定；④ **7 件受力件改金属 ¥45 不打、轮滑专属 8 件走路版不打** ⇒ 走路版实打 **43−7−2−8 = 26 件**。盘数三处读数不一致（README 5 盘 52 对象 / 元数据 6 组 plate 预览 / model 1 build 43 object），已在必读里如实标注，打开 Bambu Studio 以实际盘面为准，不武断判谁对。

## 7. 实跑验收

| 项 | 结果 |
|---|---|
| `check_deploy_chain.py --selftest` | **31/31 passed**，rc=0（含 13 组结构腐化负对照 + 3 个 CLI 真跑） |
| `--check` / `--check --json` | `structure_verdict=PASS`、`ship_verdict=NOT_SHIPPABLE`、`problems=0`，rc=0 |
| `--check --ship-gate` | **rc=1**，`SHIP GATE REFUSED`（如实红） |
| `pytest tests/` | **141 passed in 149.22s，rc=0**（`.venv-mjlab` + `--basetemp` 全新临时根） |
| `run_all_gates.py --check` | **PASS 42/42、NOT_PASS 0、rc=0**；`--list` 显示 `--selftest tools = 40`，其中第 12 行是 `hd1910/check_deploy_chain.py` ⇒ B5 由 `discover()` 自动纳入，A3 代码未改。`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` |
| `line_contract.py --check` / `check_closure.py --check` | 均 rc=0；A1 `verdict=PASS`，A2 `docs markers=6 / contract ids=6`、`UNVERIFIED 5 / CLOSED 1`、`structure_verdict=PASS`、`ship_verdict=NOT_SHIPPABLE` |
| 打印包同源核验 | 3mf / PDF / BOM 三个 git blob sha 与 GitHub API `contents` 返回值逐个一致；11-11 追加轮滑件订正（见下） |

### 全量 pytest 首跑 rc=1 的归因（不是测试失败）

首次 `pytest tests/ -q` 在 `[100%]` 后返回 rc=1，输出末尾只有
`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":86,"threshold":50,...}`——
是本机 safe-delete 钩子拦下 pytest 清理**历史**临时目录（86 个 > 阈值 50），**141 个点全绿但没吐汇总行**。
换 `--basetemp=<全新目录>` 重跑得 `141 passed in 149.22s (0:02:29)、rc=0`。
⇒ 判据仍是「结论行 + 返回码」，不把「看起来跑完了」当 PASS；也不把环境钩子失败伪报成测试通过。

### 同轮附带：fanhao 打印包的两处订正（交付物在 `out/`，gitignored，不入库）

用户问「好像没有轮滑的打印文件」，逐件解析 11-02 版 3mf 的 `Metadata/model_settings.config` 后发现：

- 轮滑件**就在同一份 3mf 里**（上游没有按变体分文件）：`合体轮胎.STEP` ×4（id 58–61）、`roller_blade_滚轮叶片.stl` ×2（id 34/43）、V1 备选踝 ×2（id 2/4）、`bearing_roll` ×2 属两版通用且已计入金属 7 件；多数显示名是 `1`，共 13 个对象重名 ⇒ 这才是「找不到」的原因。
- 订正本包早先「3mf 内仍是独立轮辋 4 + 轮胎 4」错述：v2.1 已合并为 4 个合体轮胎实例。
- 订正 `docs/hardware/microduck-轮滑件核图对照清单-2026-11-06.md` 靠几何猜的 3 处编号映射：`object_301` 实为 `bearing_roll`（非叶片）、`object_31` 才是真叶片（非躯体）、V1 踝是 `object_1/3`（非 `object_281`）。命名映射这步可离线闭合，但 P-A 的形态判据仍需开盘核。
- 走路版实际打印对象数由 `43−7−2=34` 改为 **`43−7−2−8=26`**；交付 `…-标注版.3mf` 用 `【不打-金属替换】`7 + `【轮滑变体件】`8 两组前缀标注，只改显示名、几何 sha256 全不变、两组负对照通过。

### 自检抓到的一个真缺陷

补 B10/B11 时用 `Edit` 替换整块，**误删了 B9 条目**；`--check` 立刻报 `required.borrowed_ids != actual: missing=['B9']`，selftest 也从 31/31 掉到 28/31。⇒ 集合相等断言当场生效，补回 B9 后恢复 **31/31、rc=0**。这正是「删条目不报警」类假绿的防护价值。

## 8. Scope / 已知缺口

- `live_hardware_accessed=false`；本轮**不证明** R17 V167 中控在本项目整机跑通、不证明 `p8head_2999` 能被 V167 加载、不证明人人 ¥80 IMU 上机认板、**不消 `INCONCLUSIVE_RATE_MISMATCH`（R3）**、`INCONCLUSIVE_LIVE_IDENTIFY` 与 `INCONCLUSIVE_DIMENSION` 仍 `UNVERIFIED`。
- kissqy R1 镜像 sha / V167 中控 ZIP sha / control.43 `BUILD.json` **未本地实算**（B2 已如实标 `UPSTREAM_PUBLISHED` / `UNOBTAINABLE` / `UNPINNED`）。
- 官网一键烧录软件的 ZIP sha 与历史版本校验文件**未下载实算**，只作机制借鉴，不进 B2 四元组。
- `line_labels.json` 仍有 **20 个 `--selftest` 工具为 `REPORT_ONLY`**（B4 待办，未逐一定线）。
- A1/A2/A3 + B2/B8/B1 + B5 **尚未接入** `.github/workflows/deploy-gate.yml`（B3 待办）；该 workflow 自述 **POST-PUSH ADVISORY、非 merge gate**，不能把绿勾当 merge 门禁。
- 金属结构件「共 7 个」按 BOM 备注推断（颈部×2 + 躯干底座×1 + 上腿加固板×2 + 轴承滚轮×2），**非卖家确认**，到货逐件核对。
- 训练线 #76 多 seed sweep、#77 VelStand / 手柄遥操作仍 pending。

## 9. 边界声明

本轮**未碰** SSOT、`build.py`、两份手改 xlsx、`.ref/` 生成源、任何既有工具的数字或代码；阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579` 不变。`line_labels.json` 为纯追加 1 条，其余全部纯新增。打印包放在 gitignore 的 `out/deliverables/`，不入库。
