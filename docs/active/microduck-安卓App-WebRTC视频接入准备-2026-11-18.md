# WebRTC 真视频：接入前准备（一手调研，不引依赖）

日期：2026-11-18
用户授权：「都做，照最优的来，记得查资料」；本方向按选项边界 = **只做准备工作**，
不引重型依赖、不改 build 文件（引入 `stream-webrtc-android` 需用户另行拍板）。
本文性质：**调研 + 接入契约准备**，未写任何功能代码、未改任何 gradle、未接视频。

## 0. 一句话结论

**技术路线已经清楚了，但"能不能接"卡在一个非技术决定上：机器人侧 WebRTC 信令端口零鉴权。**
依赖替换方案已查实（`google-webrtc` 停维 → `stream-webrtc-android`，包名兼容），
信令协议/流结构已有一手契约；**真正该先做的是"是否暴露视频面"的安全拍板，而不是写代码。**

## 1. 依赖现状：一手核实（WebSearch + 官方仓库 README，2026-11-18）

| 项 | 一手事实 | 出处 |
|---|---|---|
| 老依赖已死 | `org.webrtc:google-webrtc:1.0.32006` 最后可用构建停更多年，JCenter 关闭后 2026 新工程 Gradle **无法解析**；缓存镜像只是技术债，镜像消失就带崩发布 | Google 停维护 + 多来源一致（WebSearch） |
| 现成替代 | `io.getstream:stream-webrtc-android`，Maven Central，**保留 `org.webrtc.*` 包名** ⇒ `PeerConnection` / `VideoTrack` / `EglBase` 导入路径不变；核心是预编译 WebRTC，跟随上游提交 | `github.com/getstream/webrtc-android` 官方 README |
| 版本 | 仓库 README 写 `1.3.9`；第三方索引（last synced 2026-11-16）列最新 release **1.3.10（2025-09-11）**、snapshot `1.3.11-SNAPSHOT`。⇒ 以**官方 Maven Central 实际可解析版本**为准，pin 显式版本不用范围 | 同上 + hysenlabs 索引（非一手，仅提示去核） |
| 许可 | Apache-2.0（宽松，可商用，保留声明即可）——与本项目 App 主线无许可冲突 | 官方仓库 |
| 多模块 | core / ktx / compose / ui / utils + **BOM**（`stream-webrtc-android-bom`）——BOM 用于把 core/扩展版本锁在同一 ABI，避免链接失败 | 官方仓库 |
| 备选 | `io.github.webrtc-sdk:android`（webrtc-sdk 构建） | 官方 README |

⚠️ **未做**：未实际解析依赖、未下 AAR、未量 APK 增量——这些要等"拍板引入"后真跑才算数，现在写"可用"是假绿。

## 2. 机器人侧信令契约（一手：`Animan-AI/DuckBuddy/docs/design/remote-webrtc.md`，社区非官方）

DuckBuddy 是社区项目（非 pollen 官方，来源按约定具名）。它这份文档的价值是**第一手实测契约**，

| 项 | 一手内容 | 来源性质 |
|---|---|---|
| 状态 | **2026-08-25 真机端到端跑通**：Radxa Zero 3W 上 `videotestsrc`→硬编 H.264→LAN 浏览器，同时拿到 `control` datachannel | 社区实测（非我方） |
| 信令 | `mediad` **进程内自带信令服务器**（webrtcsink 的 `run-signalling-server`），默认 `ws://127.0.0.1:8443`；LAN 客户端直连同一服务器；**绑定所有网卡**（loopback-only 会让 LAN 客户端完全不可达） | 一手设计 |
| 视频 | `mpph264enc` 硬编，协商 `profile-level-id=42e01f`（constrained baseline）；W stored head cam 实测 29.3 fps | 一手实测 |
| 流结构 | 一会话四流：video / audio / datachannel `control`（reliable,ordered → 机器人 API）/ datachannel `teleop`（`maxRetransmits:0`，最新值胜出）。**第一版只开 `control`** | 一手设计 |
| 帧快照 | pipeline 在编码器前 tee 出 raw NV12 → leaky queue(1) → appsink，供"每秒一两帧 + 状态 blob"的服务端程序用；stall 只丢帧不卡编码器 | 一手设计 |
| 坑 | ① 从 GStreamer signal 线程 `tokio::spawn` 会 abort 进程（非 unwind panic）；② `file://` 页面被 Chrome PNA 挡，需 `http://localhost`；③ H.264 协商失败是 warn 不是 error，会静默退 VP8 后会话死；④ 需 gst-plugins-rs ≥ v3 | 一手踩坑 |

## 3. 🔴 的安全结论（这是"要不要接"的真正闸门）

`remote-webrtc.md` §4 明写：**机器人侧信令端口零鉴权——"a decision, not an oversight"**。
任何能连到信令端口的 peer 都能开会话、驱动机器人、看摄像头。作者论证的"安全"来自两层：

1. **LAN 场景**：`000000` 共享 PIN  authenticate 不了任何人，作者直接承认"fine on a bench and
   in an office, **not fine in a home**"；
2. **远程场景**：靠 bridge 前面的 OAuth——客户端对 rendezvous 服务 OAuth、机器人持账号 token 外连，
   两侧都已认证后由服务撮合，所以机器人侧不再加 `system.authenticate`（加了反而更弱，因为
   `000000` 比账号 token 证明力低）；
3. **唯一未覆盖**：端口转发把信令端口直接暴露公网——bridge 不在路径上，§4 的 LAN 论证不成立。

**对本项目的判定**：
- 我方 App 走的是 BLE JSON-RPC 控制，**WebRTC 视频是"看"的功能**，可达性受限于 drugs 的部署
  （局域网 or bridge）；在没有 bridge OAuth 的本地场景下，**开视频 = 开一个无鉴权的驱动+观看面**。
- 这与 §A2' 配网加密是同一类"对外交付前必须关掉"的洞，但**互相独立**：加密 BLE 不解决
  信令端口无鉴权，反之亦然。
- ⇒ **接入前置**：① 明确只在受控 LAN/本机回环使用、② 或实现 §4 §"the hook"提到的
  `system.authenticate` 门（作者说 cheap，路由表已有"哪些方法在认证前可达"的概念）、
  ③ 或确认通过带 OAuth 的 bridge。**三者未定之前，接视频代码 = 制造假安全。**

## 4. 接入前还需一手确认的（不在本轮做）

- 我方 fanhao/复刻固件里 mediad 的实际版本与配置键 `[media]`、`signalling-server-port`、
  是否真绑定所有网卡；DuckBuddy 文档 ≠ 我方固件（API16/40 差异、来源不同）。
- `stream-webrtc-android` 在**本项目 Gradle 环境**（腾讯/阿里镜像、compileSdk35、AGP8.9.1）能否解析。
- 真人真机上的 `PeerConnection` ↔ `mediad` 信令互通（SDP/ICE/BUNDLE `application1` datachannel）。
- 视频帧延迟 / 码率 / CPU 占用对 50Hz 控制环的影响（DuckBuddy 文档有拥塞控制是 CPU 设置的提醒）。

## 5. 本轮边界

- 未改任何代码/gradle、未引依赖、未宣称可接；`ship_verdict=NOT_SHIPPABLE` 不变。
- 所有固件侧契约来自社区一手文档，**非我方实测 ⇒ UNVERIFIED**；真机前一律只读观察。
- 唯一官方仍 `pollen-robotics/microduck`；DuckBuddy/Stream 均具名。

## 6. 下一步（需用户拍板）

引入重型依赖 + 暴露无鉴权视频面属**方向性决定**，本轮不替用户做。若拍板：先按 §3 定安全边界，
再按 §1 pin 版本实际解析、量 APK 增量，最后才写 `WebRtcTransport`（与现有四后端同 NDJSON JSON-RPC 接口）。
