# MicroDuck 硬件核查：资料溯源与结论审计

_2026-11-06。回应「是否找了参考资料」。按项目铁律「遇到问题先去网上找资料，自己推是最后手段且必须明说」，把这几轮每个关键结论的依据类型逐条摊开。_

## 0. 一句话回答

**查了，但不彻底。** 一手资料覆盖了 BOM、装配说明书、作者 README、3MF 内部数据、Releases、SolidWorks 包、Orange Pi 官方引脚/尺寸、kissqy HAT KiCad、上游 Rust 源码。但**两个最关键的格式语义判断当初是自己看数据推的，没查规范**：

- 「3MF 里的 transform 是打印排布、没有整机装配位姿」——推的（本次补查 3MF 官方规范，已获背书，升级为规范+实测双证）。
- 「`.SLDASM` 是专有二进制 ⇒ 无法还原位姿」——推的，**而且说过头了**（本次查到 eDrawings / Onshape / Fusion 360 等免费读取路径，已收敛为「本机缺工具」）。

另外「找作者 MakerWorld 装配版 3MF」这条我上轮**只提了没查**，本次查了：页面上没有整机装配文件，路已堵死。

**规律**：这几轮翻车的结论，无一例外都是「自己推的」或「查了但没查全」；站稳的结论都有一手资料。

---

## 1. 一手资料清单（实际查过的）

| # | 资料 | 来源 | 用途 |
|---|---|---|---|
| 1 | `fanhao375/microduck-replica-cad` README（master，390+ 行） | codeload tarball | 版本、打印工程定义、装配体清单、许可、MakerWorld 链接 |
| 2 | `BOM/README.md` + BOM Excel（机械行者Robo 2026-11-02） | 同上 | **33 项打印件 + 24 项外购件**，逐项数量/材料/采购链接 |
| 3 | `microduck装配安装说明书.pdf`（21 页） | 同上；用 `pypdf` 抽全文 | 15 组件 / 34 步装配顺序、装配硬约束 |
| 4 | 组件图（整机渲染 + 3 爆炸图 + 15 部件图） | 同上 | 结构判读、SBC 位置判读 |
| 5 | `microduck-飞特版-BambuStudio2026-11-02.3mf` | 同上 | 33 网格、43 build item、43 component transform、`assembly_model.json` / `assembly_step.json` |
| 6 | GitHub Releases API（含 `v2.2` tag / assets 端点） | api.github.com | 417.7 MB SolidWorks 包、21.7 MB 改动件 STEP 包 |
| 7 | `SolidWorks-FT2026-10-20.zip`（417,656,282 B，完整下载） | `gh-proxy.com` 镜像 | 18 `.SLDASM` + 59 `.SLDPRT` + 10 单件 `.STEP`；总装 66 MB 文件头 |
| 8 | `STEP-changed-parts-FT-2026-10-20.zip`（21.7 MB） | 同上 | 13 个改动件 STEP，确认全为单件 |
| 9 | **3MF Core Specification v1.3.0**（3MF Consortium，40 页） | 3mf.io 官方 PDF（本次补查） | §3.4.3.1 / §4.2 关于 `<item>` 与 `<component>` 变换的**规范级定义** |
| 10 | Bambu Lab 官方：下载页「STEP 格式」说明 + Assemble Tool wiki | bambulab.com / wiki.bambulab.com（本次补查） | STEP 可保留零件装配关系；Assemble Tool 语义 |
| 11 | Orange Pi Zero 3W 40-pin 引脚表与尺寸页 | playwithcircuit / orangepi 官方 / cnx-software / thequantumdispatch | HAT 可直插、板型与 Pi Zero 兼容 |
| 12 | kissqy `elec_RPI_Robot_HAT.kicad_pcb` | 作者硬件工程（KiCad 9） | HAT 引脚闭环（J4 Pin8/10 → UART，DE 板内自动产生） |
| 13 | **MakerWorld 飞特版页面**（作者本人，2026-09-13） | makerworld.com.cn/models/2963569（本次补查） | 确认只有 6 盘打印配置 + 1 份组装指南 PDF，**无整机装配 3MF/STL** |
| 14 | SLDASM 读取/转换路径多源交叉 | Dassault eDrawings 官方说明、Onshape、Autodesk Fusion 360、FreeCAD/OCC、file-extension.info、file-types.com（本次补查） | `.SLDASM` 存 mates、内嵌细分显示图形；免费导入导出路径 |
| 15 | `pollen-robotics/microduck` 主仓 Rust 源码 | 早前轮次，官方一手 | policy load 校验、robotd 配置键、寄存器硬校验 |

> 本地留存：`out/builds/microduck_replica/` 下 `3MF_Core_Spec_v1.3.0.pdf`、`3MF_spec_text.txt`、`pdf_text.txt`、`SolidWorks-FT2026-10-20.zip`、`step_changed.zip` 等（该目录按 `.gitignore` 不入库）。

---

## 2. 结论逐条溯源

| 结论 | 依据类型 | 具体出处 | 当前状态 |
|---|---|---|---|
| 33 项打印件 + 24 项外购件 = 57 项，两版齐全 | **一手** | BOM/README.md + Excel + 说明书 | ✅ 站稳 |
| 15 组件 / 34 步装配顺序 01→15 | **一手** | 21 页说明书 PDF 全文 | ✅ 站稳 |
| 两版仅差主控板 1 项 + 软件配置 | **一手 + 推导** | BOM + Orange Pi 引脚/尺寸 | ✅ 站稳 |
| Orange Pi 40-pin 与 RPi 同脚位，HAT 可直插 | **一手** | Orange Pi 官方/评测引脚表 + kissqy HAT KiCad | ✅ 站稳（推翻早前「电气死穴」） |
| Orange Pi = Pi Zero 兼容板型，机械零改动 | **一手为主，仍有一处冲突** | 官方产品页多源「same footprint as Pi Zero」；官方中文参数页仍写 65×32 | 🟡 高置信但有矛盾，见 §4 |
| Radxa Pin8/10 = `UART2_M0` / `ttyS2` 跑 1 Mbps | **一手** | 官方主仓 Rust / 板级资料 | ✅ 站稳 |
| 33 个网格中心全 `(0,0,0)`，之前「合体鸭子」是一坨 | **实测** | 3MF 33 个 `object_*.model` 顶点统计 | ✅ 站稳（已作废旧 STL 与文档） |
| 43 个 `<component>` transform 全为单位阵 | **实测** | `3D/3dmodel.model` 逐个比对 12 元矩阵 | ✅ 站稳 |
| `<build>` 的 43 个 transform 是打印排布、不是整机位姿 | **推的 → 已获规范背书** | 原：bbox `X[17,816]`、16 实例 Z<0 自己判读；**补**：3MF Core Spec §3.4.3.1 逐字原文 | ✅ 升级为规范+实测 |
| `assembly_model.json` 不含整机位姿 | **实测 + 规范旁证** | `offset_to_assembly` 全 0、keyframes 全空 | ✅ 站稳 |
| 417 MB 包里没有整机 STEP/STL | **实测** | zip 全目录（10 个 STEP 全是单件）+ 作者 README「77 个 SolidWorks 文件」 | ✅ 站稳 |
| `.SLDASM` magic `58 8f 9a 95…`，非 OLE2 / 非 ZIP | **实测** | 总装文件头 + `olefile.isOleFile()=False` | ✅ 站稳 |
| 「`.SLDASM` 无法还原位姿」 | **推的，且说过头** | 当时只扫了文件头/字符串就下结论 | ❌ **已更正**：格式专有 ≠ 不可解析；有 eDrawings / Onshape / Fusion 360 免费路径，本机是缺工具 |
| MakerWorld 有装配版 3MF 可找 | **未查的猜测** | 上轮只在「下一步」里提了一句 | ❌ **已排除**：页面只有 1 个 6 盘打印配置 + 1 份组装指南 PDF |
| 外购件占位体尺寸 | **部分是推的** | 电池 / 轴承有据；板卡 / 舵机 / 摄像头 / ToF 等为推定 | ⚠️ 已在 manifest 逐项标注，**不可用于干涉检查** |

---

## 3. 翻烧饼史：错的全是「推的」或「没查全」

| # | 当初的结论 | 怎么错的 | 怎么翻过来 |
|---|---|---|---|
| 1 | `trunk_base` 是 SBC 卡位，Orange Pi 仅 2 mm 余量待核 | 看 BOM 备注**推**的，没看结构图/README | 读 README + 躯干主体图：`trunk_base` 是**髋 yaw 舵机位**，SBC 在躯干主壳型腔 |
| 2 | Orange Pi 40-pin ≠ RPi，HAT 不能直插、IMU I2C 失效、「电气死穴」 | **推**的 | 查 Orange Pi 官方引脚表 + kissqy HAT KiCad：UART 8/10、I2C 3/5、电源地全同脚位 |
| 3 | 418 MB STEP 包**不在** Releases | 查了，但**漏了分页/旧 tag** | `v2.2` release 里就有；已完整下载 |
| 4 | 33 件直接合并 = 完整鸭子，bbox 三轴铺开即整机 | 自己看 bbox **推**的，把「包围盒并集」当装配占位 | 实测 33 网格中心全 `(0,0,0)`；旧 STL 作废 |
| 5 | Orange Pi 65×32 ⇒ 腔体深度要放宽 2–3 mm，需改 1 个件 | 拿官方中文参数页 32 mm **推**的 | 多源「same footprint as Raspberry Pi Zero」+ 40-pin 同脚位 ⇒ 净尺寸应为 65×30，改腔体任务取消 |
| 6 | `.SLDASM` 专有二进制 ⇒ 整机位姿无法还原 | 只扫文件头就**推**论，没查有没有现成读取方案 | 查到 eDrawings（官方免费）/ Onshape / Fusion 360；准确说法是「本机缺工具」 |
| 7 | 找 MakerWorld 装配版 3MF | **没查，只是写在「下一步」里** | 已查：页面无整机装配文件 |

> 这一列有个很干净的模式：**资料提供「应该是什么」，实测提供「实际是什么」；只推不查时，两者都没了**。项目记忆里那条「找资料防不住自己那一行的语义差」在这轮再次成立——第 4 条（bbox 并集误判）正是我自己代码语义上的错，规范也救不了，只能靠负对照/第二算法。

---

## 4. 仍然是「推的 / 未找到现成方案」的（按铁律明说）

- **Orange Pi 板宽 30 vs 32 mm 冲突未钉死**：官方中文参数页写 65×32，官方产品页与多篇评测写 65×30 且「same footprint as Raspberry Pi Zero」。目前按「大概率 30（Pi Zero 板型 + 58×23 孔距），保守按 32 出占位体」处理。**这是推的**，要实物卡尺或官方机械图才能定死。
- **Pin27/28（HAT EEPROM 自动识别用 I2C0）** Orange Pi 是否同脚位：orangepi.org 官方引脚图本次没抓到，**未核实**。缺失只影响 HAT 自动配置，不影响手动使用。
- **43 个 build 实例 vs BOM 42 个实体差 1**：口径含 V1 备选踝、独立轮辋+轮胎、辅助对象；三套 UUID 互不相交 + 11 个装配组名丢失 ⇒ **无法自动映射网格 ↔ BOM 项名**，需按 5 张打印盘图人工对号。
- **SBC 在躯干主壳腔里的实际朝向**：网格是壳+腔结构，纯顶点包络测不准净腔深；需实物或参数化 CAD。
- **外购件占位体**：板卡 / 舵机 / 摄像头 / ToF / 扬声器 / 线材外形尺寸均为**推定**，仅表示「该件存在」。
- **A733 5V 轨带载、UART 500k 实测**：尚未上电验证，来自源码/资料而非实测。

---

## 5. 本次补查带来的三处实质变化

1. **规范级背书**：3MF Core Spec §3.4.3.1 原文明确区分 `<item>`（打印排布，consumers MAY rearrange）与 `<component>`（对象内部装配关系，设备 MUST NOT 相对变换）。配合实测「43 个 component 全单位阵」→「这份 3MF 不是整机装配文件」从**推断**升级为**规范+实测双证**。
2. **结论收敛**：`.SLDASM` 从「无法还原」改为「本机缺工具」；给出可执行免费路径（eDrawings 查看 / Onshape 或 Fusion 360 导入后导出整机 STEP/STL）。
3. **排除一条死路**：MakerWorld 已核查无装配版 3MF/整机 STL，不必再找。

文档落地：`microduck-两版整机装配完整性核对-2026-11-06.md` 新增 §5.1（规范原文）、§5.2（免费读取路径）、§5.3（MakerWorld 核查）、§5.4（收敛后的三条路）。

---

## 6. 元教训（值得记进项目准则）

- **「下一步」里写的资料线索，不等于查过**。本轮 MakerWorld 就是这么漏的：写在建议里，没真去点开。
- **格式的「读不懂」和「读不了」是两件事**。看到专有 magic 就断言「无法还原」，跳过了「有没有现成工具」这一问——这正是铁律要求先查的那一问。
- **查询要查全比查到更重要**：Releases 那次不是没查，是没翻分页；引脚那次不是没查，是拿旧记忆当结论。
