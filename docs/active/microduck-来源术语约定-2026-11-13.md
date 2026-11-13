# MicroDuck 项目来源术语约定 —— 唯一「官方」= Pollen Robotics 原厂

_2026-11-13。用户明确：「**真正的官方只有一个：Pollen Robotics 原厂**」。_
_本文件是引用归属的唯一准绳。此前各文档把「官方」泛指到 fork、另一产品、第三方平台，一律按此收敛。_
_本文件只定规矩，不改任何功能代码。_

---

## 1. 定义（唯一允许的用法）

| 称呼 | 唯一允许指代 |
|---|---|
| **官方 / 原厂 / Pollen 原厂** | `pollen-robotics`（**Pollen Robotics**）发布的 **MicroDuck** 内容，即 `pollen-robotics/microduck` 仓 |
| 其余一切 | **必须带仓库全名 / 机构名 / 版本号**，不得称「官方」 |

**一手证据（2026-11-13 GitHub REST API `api.github.com/repos/...` 实测）**：

| 仓 | 状态 | 说明 |
|---|---|---|
| `pollen-robotics/microduck` | public，`default_branch=main`，`pushed_at=2026-11-13T07:32:35Z` | **唯一官方**。一手文件：`docs/design/mobile-app.md`、`docs/design/app-path-design.md`、`duck-ipc-proto/src/lib.rs`、`duck-ble/`、`btd/src/route.rs`、`duckctl.md` |
| `pollen-robotics/microduck-app` | **HTTP 404（私有）** | 原厂手机 App 源码**读不到**。可以引用其设计文档，但不得声称读过 App 源码 |
| `pollen-robotics/reachy_mini_mobile_app` | public，`Cross-platform Tauri mobile client for Reachy Mini robots` | **Pollen 另一产品（Reachy Mini）**的公开 App，只算参考实现，**不是 MicroDuck 官方** |

---

## 2. 一律不叫「官方」的来源（具名表）

| 来源 | 正确称呼 | 与本 App 的关系 |
|---|---|---|
| `fanhao375/Microduck-kissqy` @ `hd1910-v167-trunk-imu-i2c` | **fanhao fork（API40）** | 本 App **实际对接目标**。⚠️ 该仓 GitHub API 现返回 404（转私有/改名），本地 `/tmp/fanhao/...` 保有整份源码，本轮一手核对基于它 |
| B 代 / `.upstream/ft1910` / `imu-displace` / kissqy / `AiBoBoMaker/MicroDuck-BoBoRedesign` | **本地 API16 快照 / 社区同源分支** | C2 / C2+ / P1「活体」联调证据的全部来源 |
| `pollen-robotics/reachy_mini_mobile_app` | **Pollen 另一产品（Reachy Mini）的公开参考 App** | 借配网 FSM / 错误恢复 / 地址徽章，结构不同（它 BLE 是一次性配网向导，我们 BLE 是常驻通道） |
| `developer.android.com` / Material Design / Google Play | **Android 平台文档（Google）** | 平台规范，与机器人项目无关 |
| Kotlin / Gradle / Oracle JDK / Rust 标准库 | **JetBrains / Gradle Inc. / Oracle / Rust 项目文档**（逐一具名） | 工具链规范 |
| QGroundControl / GitHub / Wandelbots / NIST / arXiv / FPV OSD | **各项目/机构名 + 文档名** | 第三方规范或研究，逐一具名 |
| `Ley-WL/ducklink`、`OpenBot`、`ble-rc-controller` 等 | **社区 App（具名）** | 开源借鉴 |

---

## 3. API 版本三套并存，别混

| 来源 | `API_VERSION` | 地位 |
|---|---|---|
| Pollen 原厂 `pollen-robotics/microduck@main` | **61**（2026-11-13 GitHub API 实测） | 上游最新，**不是**本 App 对接目标 |
| fanhao fork | **40** | ✅ **本 App 实际对接目标** |
| B 代 / 本地 `.upstream` 快照 | **16** | 目前所有「真固件活体」证据的版本 |

> 此前 A5 文档写「主仓 16」是**本地旧快照**，不代表原厂现状，已在本约定中澄清。

---

## 4. 文档归属硬规则（本轮最容易犯的错）

`docs/design/mobile-app.md`、`app-path-design.md` 的**作者是 Pollen 原厂**；
fanhao / BoBo / `.upstream` 里的同名文件只是**副本**。

- ✅ 正确写法：「**Pollen 原厂** `pollen-robotics/microduck@main` 的 `docs/design/mobile-app.md` §4（经 fanhao 副本核对）」
- ❌ 错误写法：「**fanhao** `docs/design/mobile-app.md` §4」「官方 App 文档（fanhao 原样保留）」——把作者让渡给 fork

**副本核对（2026-11-13 实做）**：原厂版 18796 B / md5 `a4652408f430`，
fanhao 副本 md5 `5cb5394f864e`，逐行 diff **仅 §7 一行**（`robot.sound` 是否已路由 / `duckctl quack`）；
§1 屏幕×调用表、§4 会话层、§6 版本下限、§7 其余条目两版一致 ⇒ 引用原厂结论成立。

---

## 5. 历史文档的处置原则

历史注释 / 文档里的「官方」二字按下面三条读，**不再逐处重写**（避免纯文本噪声）：

1. 指 `pollen-robotics/microduck` ⇒ 读作「Pollen 原厂」；**新写内容一律用「原厂」**。
2. 指 Android / Kotlin / Gradle / Oracle / QGC / GitHub 等 ⇒ 读作**该平台自身**的文档，与本项目「官方」无关；新写内容一律具名机构。
3. 指 **fanhao / Reachy Mini / B 代** ⇒ **属误称**，见 §6 已修正。

「GitHub 官方 API」这类易生歧义的组合，统一改称 **GitHub REST API（`api.github.com`）**。
4. **硬件 / 采购线历史文档**（如 `microduck-选型与打印位决策-官方HAT一手-2026-11-10.md`、
   `docs/active/.MicroDuck-照着买采购清单-2026-11-10.ref/`）里的「**kissqy 官方**清单 / 取电 / 打印包」
   是更早的口语用法，指 **kissqy 仓自带的清单与卖家商品页**，同样**不是本项目官方**；
   本次不改动这些历史文件（涉及采购 SSOT 关联文档，避免无谓扩散），一律按本条读作
   「kissqy 仓自带 / 卖家页面」。新写硬件文档一律写 `kissqy/Microduck-kissqy` 仓名。

---

## 6. 本轮修正清单（把非原厂误称「官方」的地方）

| 文件 | 原文 | 改为 |
|---|---|---|
| `app/.../MainActivity.kt` linkBanner KDoc | 「一手依据：**fanhao** `docs/design/mobile-app.md` §4」 | 「**Pollen 原厂** `pollen-robotics/microduck@main` …（fanhao fork 副本同源）」 |
| `core/.../GattLink.kt` §5 | 「**fanhao 官方** `duckctl/src/main.rs:2075`」 | 「**fanhao fork** `duckctl/src/main.rs:2075`」 |
| `core/.../RobotSession.kt` 类注释 | 「**官方** `mobile-app.md` §4」 | 「**Pollen 原厂** `mobile-app.md` §4」 |
| `core/.../RobotSession.kt` 重连风暴注释 | 「**Reachy Mini 官方 App** 的坑」 | 「**Reachy Mini App（Pollen 另一产品）** 的坑」 |
| `core/.../RobotTransport.kt` | 「这是**官方**设计意图」 | 「这是 **Pollen 原厂**的设计意图」 |
| `README.md` | 「**官方**设计意图」/「QGC **官方** Fly View」/「GitHub **官方** API」 | 「**Pollen 原厂**的设计意图」/「QGC Fly View User Guide」/「GitHub REST API」 |
| `docs/active/microduck-安卓App功能调研-2026-11-12.md` | 「**官方**参考实现（指 Reachy Mini）」等 | 「Pollen **另一产品**（Reachy Mini）的公开参考 App」；开头补术语声明 |
| 三份界面/对照文档 | 「GitHub **官方** API」 | 「GitHub REST API（`api.github.com`）」 |

---

## 7. 为什么这条规矩重要（本项目踩过的坑）

- 把 **fanhao fork 的 API40** 与 **原厂 main 的 API61**、**B 代本地快照的 API16** 混称「官方」，
  会让人误以为「联调已验 = 原厂已验」，直接违反 `未验证 != 通过`。
- 把 **Reachy Mini**（另一产品）的 App 叫「官方参考实现」，会让人误以为 MicroDuck 原厂
  已给出可照抄的移动端实现 —— 实际上原厂手机 App 仓是**私有**的，只有设计文档可读。
- 「查不到」先怀疑搜索范围：此前把原厂 §4 的原文判成「无法证实」，错因是只 Grep 了
  git worktree，漏查 `/tmp/fanhao` 里的一手副本。**来源归属查证必须跨副本、跨仓**。
