# MicroDuck 安卓 App：GitHub Releases 自更新功能设计依据（2026-11-13）

> 需求：用户「能不能加一个更新功能，依赖 github 发布」→ 选择 **应用内下载并调起安装**
> + **SOP 与本地发布脚本**；追加「结合多个开源项目，做一个最优的」。
> 纪律：先查一手资料再动手；`UNVERIFIED != PASS`、`COLLECTED != PASS`；不编造引用。

---

## 0. 先说清楚当前真实状态（决定了很多设计）

| 观测 | 结果 | 来源 |
|---|---|---|
| 仓库 | `chenshiyilisha/microduck-flat-walk`，public，default_branch=main | GitHub REST API `GET /repos/chenshiyilisha/microduck-flat-walk` |
| releases | `[]`（0 个） | `GET /repos/.../releases` |
| tags | `[]`（0 个） | `GET /repos/.../tags` |
| latest | **HTTP 404 Not Found** | `GET /repos/.../releases/latest` |
| 未认证限额 | `core.limit = 60` / 小时 | `GET /rate_limit` |
| App 版本 | `versionCode=1`、`versionName="0.1.0-p0-skeleton"`、`minSdk=26`、`targetSdk=35` | `app/build.gradle.kts` |

⇒ 所以 App 第一次点「检查更新」的**正确结果**是「暂无正式发布（GitHub REST API 返回 404）」，
不是「已是最新」，更不是造一个假版本。这条已真机复验（见 §6）。
发布脚本不擅自创建 Release；要让功能真正可用，必须由用户按 §5 发布一次。

> ⚠️ 上表是 2026-11-13 **设计当日**的观测快照，不是当前态。发布准备已完成：
> 版本升到 `versionCode=2` / `versionName="0.2.0"`、固定签名证书已建立（§5），
> 首个 Release 创建后 releases/tags 不再是 0、`releases/latest` 不再是 404。
> 发布与回读结果见 §6；用户 2026-11-13 晚授权「可以发布到 github 了」并开始执行。

---

## 1. 多开源项目一手对照（全部经 GitHub REST API 定位 + raw 源码逐行核验）

| 项目（机构/仓库） | 一手文件 | 可取之处 | 本项目采用 |
|---|---|---|---|
| `KaringX/clashmi`（Dart，Clash Mihomo 客户端） | `lib/app/utils/auto_update_utils.dart`（`AutoupdateItem{platform,channels,abis,version,url,sha256,version_channel}`）；`lib/app/modules/auto_update_manager.dart`（`_duration=3h`、`_checking/_downloading` 防重入、`AutoUpdateCheckVersion{latest_check,new_version,version,url,sha256}`、`CryptoUtils.getFileSha256` 不符删文件、404 清状态）；`lib/app/utils/version_compare_utils.dart` | 清单元数据 + SHA-256 + 按 ABI/渠道选包 + 检查状态持久化 + 节流 | ✅ 清单（`update.json`）、SHA-256、防重入、缓存上次检查时间；❌ 不做自动轮询、不引自有 CDN（用户要求依赖 GitHub 发布） |
| `ImranR98/Obtainium` | `lib/app_sources/github.dart`（读 releases、`prerelease` 过滤、`tag_name` 作版本、`assets[].browser_download_url`、`filterApks` 按 `.apk` 筛、`trackOnly`、无 APK 与无 release 分状态） | 直读 GitHub Releases、按 `.apk` 筛 asset、状态分层、release `html_url` 给用户看 | ✅ 全部采用；❌ 不用它的 Root/Shizuku/多安装器 |
| `Tobi823/ffupdater`（Kotlin） | `installer/impl/CertificateVerifier.kt`（`FingerprintValidator.checkApkFile` 安装前校验证书、安装后复核）；`installer/impl/IntentInstaller.kt`（FileProvider + `ACTION_INSTALL_PACKAGE` + `EXTRA_RETURN_RESULT`）；`network/exceptions/ApiRateLimitExceededException.kt`；`app/VersionCompareHelper.kt`（解析失败兜底，不默认「已是最新」） | 签名证书校验、限流独立状态、版本解析兜底、安装结果可观测 | ✅ 签名证书比对、限流独立状态、解析失败转 Failed；❌ **不用**其 deprecated 安装 intent（见 §3） |
| `javiersantos/AppUpdater`（Java） | `library/.../ParserJSON.java`（`latestVersion` + `latestVersionCode`）；`app/update*.json` 与 `app/src/androidTest/.../files/*-available-*.json` | versionCode/versionName 双字段 + 固定 JSON 夹具做正负对照 | ✅ 双字段（versionCode 为主判据）+ 40 条固定夹具自检 |

**「最优」的具体含义**：把四家各自最硬的一条串成一条链，而不是照抄任何一家；
并在 FFUpdater 之上再进一步 —— 按 Android 平台文档改用未被废弃的 `PackageInstaller`。

---

## 2. 平台与 GitHub 一手依据

| 结论 | 一手来源（原文要点） |
|---|---|
| `GET /repos/{owner}/{repo}/releases/latest` 返回「the most recent **non-prerelease, non-draft** release」，按 `created_at` 排序；响应含 `tag_name/html_url/published_at/prerelease/draft/assets[].name/browser_download_url/size` | GitHub Docs《REST API endpoints for releases》 |
| 未认证 60 次/小时；403/429 且 `x-ratelimit-remaining=0` 才按 `x-ratelimit-reset` 退避；`GET /rate_limit` 不占主限额 | GitHub Docs《Rate limits for the REST API》 |
| 「Avoid polling」；反复 404 的资源不要每次轮询；条件请求 ETag/`If-None-Match`；跟随重定向 | GitHub Docs《Best practices for using the REST API》 |
| 「Requests without a valid `User-Agent` header will be rejected」；`X-GitHub-Api-Version` 写错会 400 | GitHub Docs《Troubleshooting the REST API》 |
| 上传 asset 用创建 release 响应里的 `upload_url`（`uploads.github.com`），必带 `Content-Length`/`Content-Type`，body 为原始二进制 | GitHub Docs《REST API endpoints for release assets》 |
| `versionCode`「数字越大表示版本越新」「Android 系统使用 versionCode 值来防止降级」，后续版本必须更大；`versionName` 才是给用户看的值 | Google Android《对应用进行版本控制》 |
| 「当安装应用的更新时，系统会比较新版本和现有版本中的证书…如果使用不同的证书为新版本签名，您必须为应用分配另一个软件包名称」 | Google Android《为应用签名 / 签名注意事项》 |
| API 26+ 用户须在「Install unknown apps」按来源授权；「a source that installs unknown apps should always call `canRequestPackageInstalls()`」 | Google Android《Publish your app / User opt-in for unknown apps and sources》 |
| `ACTION_INSTALL_PACKAGE`「Deprecated in API level 29. use **PackageInstaller** instead」；targeting API>25 需 `REQUEST_INSTALL_PACKAGES` | Android `Intent` reference + AOSP `Intent.java`（`@deprecated`） |
| `Session.commit(IntentSender)`「Throws IllegalArgumentException if the statusReceiver from an immutable PendingIntent when caller has a target SDK of API version **35 or above**」 | Android `PackageInstaller.Session` reference（本项目 targetSdk=35 命中，真机实测复现） |
| Android 9+ 默认 `cleartextTrafficPermitted="false"`；`domain-config` 可按域放行；`android:networkSecurityConfig` 挂载 | Google Android《网络安全配置》 |

⛔ 本项目**不写死 `X-GitHub-Api-Version`**：官方说写不存在的值会 400，而当前可用版本字面值未逐字核验；
不写则用服务端默认版本（实测 GET 正常）。这是「查不到就别编」的落实。

---

## 3. 架构与关键决策

```
GitHub Releases ──GET latest──> GithubReleaseClient (app, HttpURLConnection)
                                   │  GET update.json (asset)
                                   ▼
                       UpdatePolicy (core, 纯 JVM / gson，可脱机自检 327 条)
                                   │  Decision: Available / UpToDate / NoRelease /
                                   │           RateLimited / Failed
                                   ▼
                       UpdateController (编排、防重入、状态文案)
                                   │  下载 → SHA-256 → 签名证书比对
                                   ▼
                       UpdateInstaller (canRequestPackageInstalls → PackageInstaller.Session)
                                   │
                                   ▼
                       UpdatePanel (设置页最末尾的纯代码 UI)
```

1. **不做后台轮询**：仓库当前就是 404，GitHub 官方明确「反复 404 不要每次轮询」。
   全部请求只由用户点击触发；`last_check` 只用于展示，不用于自动触发。
2. **主判据是 `versionCode`**（Android 平台语义），`versionName` 只用于显示与
   「versionName 变了但 versionCode 没涨」的发布漏改早失败。
3. **双层完整性**：`update.json` 的 `sha256` 验证下载字节（ClashMi），
   `PackageManager.getPackageArchiveInfo(GET_SIGNING_CERTIFICATES)` 比对签名证书指纹集合
   验证「能不能覆盖安装」（FFUpdater + Google《为应用签名》）。二者缺一不可。
4. **安装走 `PackageInstaller.Session`**，不是 FFUpdater 用的 deprecated
   `ACTION_INSTALL_PACKAGE`；因此**不需要 FileProvider**、不暴露 content Uri，攻击面更小。
   `setAppPackageName(本包名)` + `MODE_FULL_INSTALL` + `commit(IntentSender)`，
   结果由 `EXTRA_STATUS` 广播回传，`STATUS_PENDING_USER_ACTION` 视为正常状态而非失败。
5. **只从 GitHub 域取 APK**：core 白名单只允许 `github.com`；
   debug 端到端验证可显式追加 `127.0.0.1`，生产恒为空集（自检有负对照）。
6. **明文只对 debug 包开**：`src/main/res/xml/network_security_config.xml` 全禁明文，
   `src/debug/res/xml/` 同名覆盖只放行 `127.0.0.1`。生产包不含该覆盖。

### 状态机（每一类都是真实可观测量，不合并、不伪造）
`NoRelease(404)` / `RateLimited(403|429)` / `Failed(HTTP/解析/清单缺失/域不允许/签名不符)`
/ `UpToDate` / `Available`；下载阶段另有「失败 / SHA-256 校验不符 / 权限未开 / 等待用户确认 / 安装完成」。

---

## 4. 逐元素界面依据（用户要求每个元素都挂资料）

| 元素 | 依据 |
|---|---|
| 设置页最末尾的细描边 20dp 卡片 | 项目《现代化科技感视觉设计依据》统一 token；**放最末尾**因 `uiautomator` 只 dump 视口内节点，往上插会把「方向摇杆死区」推出首屏（门禁 59 条实测踩过） |
| 标题「版本与更新 · GitHub Releases」 | 数据源具名，避免把 GitHub 发布与本地 Mock 混淆 |
| 「手动检查 · 不做后台轮询（60 次/小时）」 | GitHub Docs《Avoid polling》《Rate limits》 |
| 「当前版本 x (y)」+ `tnum` | Android《对应用进行版本控制》双字段；AndroidX `FontSetting.tabularNum()` 源码「all numeral characters will have the same width」 |
| 「检查更新」按钮 | 同上，手动触发 |
| 「打开发布页」按钮 | Obtainium `github.dart` 用 `html_url` 让用户看到原始资产 |
| 「下载并安装」按钮 | 用户选择；Google《Publish your app》侧载路径 |
| 「开启安装权限」按钮 | Google《Publish your app》按来源授权 + `ACTION_MANAGE_UNKNOWN_APP_SOURCES` |
| 状态行（含下载百分比） | 真实 HTTP/校验结果；Obtainium 状态分层 + 项目铁律不造数据 |

---

## 5. 发布 SOP（让「依赖 GitHub 发布」这条链真正闭合）

### 前置（一次性，2026-11-13 已落实）
1. ✅ **固定签名密钥已建立**（用户拍板选「先建项目专用正式 keystore」）：
   - keystore：`C:/Users/hejih/.microduck/microduck-release.jks`（项目外，alias `microduck`，
     RSA 2048，PKCS12）；**keystore 与密码都不入库**，密码只放在本机
     `microduck-android-app/local.properties` 的 `microduck.*` 键（`git check-ignore` 已确认被忽略）。
   - 证书 SHA-256 指纹：`bd1e5c2907189c0bc0525ac9f4e9aba4502cf56eefa259501928fe6da95268d6`；
     该值同时登记为 `tools/publish_release.py` 的 `EXPECTED_SIGNER_SHA256`。
   - `app/build.gradle.kts`：debug / release 两条构建类型共用 `signingConfigs.fixed`；
     缺配置时回退 AGP 默认 debug 证书并打印 WARN，由发布门禁兜底拦截。
   - 换机器/换证书时**必须**带着同一个 keystore，并同步更新指纹常量，否则已装用户无法覆盖安装。
2. ✅ **发布脚本真做签名门禁**：`publish_release.py` 用 `apksigner verify --print-certs`
   实读 APK 证书指纹，与 `EXPECTED_SIGNER_SHA256` 不符（或找不到 apksigner / 解析不出指纹）
   一律 `rc=2` 拒发，**dry-run 也查**，不静默放行。负对照：拿旧默认 debug 证书签的 APK 跑
   dry-run，实得旧默认 debug 证书指纹
   `cb001753706c74cf48e0e6d65bfd38daf356e77b6c128319a1d58478f983553d`，被拒（见 §6）。
3. ✅ `versionCode` 本次 `1 → 2`（严格递增），`versionName` 从预发布后缀
   `0.1.0-p0-skeleton` 改为正式 semver `0.2.0`；测试机先装同证书的 `0.1.0 (1)` 基线包，
   发布后才会真正提示「发现新版本」。
4. ✅ tag 约定 `v<versionName>` ⇒ 本次 `v0.2.0`；`UpdatePolicy.validate` 会逐字核对。
   ⚠️ 因证书更换，测试机上原来的默认 debug 签名包**必须先卸载**再装基线包（已完成）。

### 操作
```bash
# 1) 只打印计划与 update.json，不写任何远端状态（默认安全）
python tools/publish_release.py --tag v0.2.0 --dry-run

# 2) 确认计划无误后，用有 Contents: write 权限的 token 真发布
GITHUB_TOKEN=xxx python tools/publish_release.py --tag v0.2.0 --apk <signed.apk> --abi arm64-v8a
```
脚本会：解析 build.gradle 版本 → 校验 tag 一致 → **apksigner 实读证书指纹并比对** →
算 APK sha256 → 生成 `update.json` → 查同 tag 已存在则拒发 → 创建 release →
用 `upload_url` 上传 APK 与 `update.json` → 回读 assets 校验。
token 只从环境变量读，不落日志、不写文件；本机真实执行用 `gh auth token`（GitHub CLI 登录态，
scopes `repo`）临时注入，不写进仓库。

⚠️ `--prerelease` 的发布会被 `releases/latest` 跳过，App 不会提示更新（GitHub Docs 原文）。
⚠️ `draft` 同样不会被 App 读到。

### `update.json` 字段（与 `core/UpdatePolicy.kt` 单一真源，自检会跨文件核对）
`schema` / `versionName` / `versionCode` / `apkAsset` / `sha256` / `minSdk` / `abi`。
App 侧校验：schema=1、versionCode>0、sha256 为 64 位 hex、apkAsset 以 `.apk` 结尾、
tag 与 versionName 一致、下载地址域在白名单内。

---

## 6. 验证记录（全部真跑，非推断）

| 项 | 结果 |
|---|---|
| `assembleDebug` | rc=0 |
| `:app:lintDebug` | **0 errors / 38 warnings**，本轮新代码 0 条（修前 43 → 修后 38，负对照成立） |
| `tools/selftest.sh` | **327 passed / 0 failed**（283 → +44；含 24 条负对照输入、Manifest 权限正则核对、发布脚本常量单一真源核对） |
| 真机 59 条门禁 | **59/59**；首轮装包后冷启动 57/59 是已知的系统通知面板污染（脚本内有记录），重跑即 59/59，非回归 |
| 发布脚本 CLI | `--dry-run` rc=0；`--tag v9.9.9` 与 versionName 不一致 **rc=2 红**（真负对照） |
| 端到端（PC 本地模拟 Release + `adb reverse`） | `GET /releases/latest` → `GET /update.json` → UI「发现新版本 0.9.9 (99) · APK 6.1 MB」→ `GET /app.apk` → SHA-256 → 签名一致 → 提交安装会话 → 系统安装；`dumpsys package` 的 `lastUpdateTime=2026-11-13 22:00:05` 证明**真落盘**，进程存活 |
| 生产路径（不带 override，直连 `api.github.com`） | 「暂无正式发布（GitHub REST API 返回 404）· 仓库尚无 release/tag」——真实状态，未伪造 |
| SHA-256 负对照 | 故意把清单 sha256 改坏 →「SHA-256 校验不符，已删除下载文件（不安装）」，**没有**触发任何安装弹窗 |
| 权限负对照 | 未授权时点「下载并安装」→ 先提示「需要开启安装权限」并给入口，不白下载 |

### 发布前加固复验（2026-11-13 晚，用户授权发布后执行）

| 项 | 结果 |
|---|---|
| hex 编码收敛 | `core/Hex.kt` 成为单一真源，下载哈希与签名指纹两条消费链共用；实现**不写字符表字面量**（按 ASCII 码推算），杜绝抄错表 |
| 自检新增 | `Hex.encode` 与 JDK17 `java.util.HexFormat`（独立算法）逐位互算；固定真值 `ab cd ef` → `abcdef`；故意错表负对照被 `verifySha256` 拒绝；跨文件静态核对两链都 import 同一函数（含负对照） |
| `tools/selftest.sh` | **340 passed / 0 failed**（327 → +13） |
| `:app:assembleDebug` / `:app:lintDebug` | rc=0；**0 errors / 38 warnings**，本轮 0 新增 |
| 真机 59 条门禁 | **59/59**（卸载旧默认 debug 签名包 → 装固定签名 `0.1.0 (1)` 基线包后跑） |
| 两包实读 | 基线 `versionCode=1 / 0.1.0`、发布候选 `versionCode=2 / 0.2.0`；`apksigner --print-certs` 两者指纹同为 `bd1e5c29…68d6` |
| 签名门禁正对照 | `--tag v0.2.0 --dry-run` → `DRY-RUN OK`，打印 sha256 与 signer |
| 签名门禁负对照 | 旧默认 debug 签名 APK → `FAIL 签名证书指纹与 EXPECTED_SIGNER_SHA256 不符`，**rc=2**，未创建任何 release |

> 🔴 本轮一次**误判留档**：曾把正确的 `"0123456789abcdef"` 读成错表，并用同一串当判据，
> 得到 `OK=True` 假绿。实际两处原实现都是对的（`ord` 逐字核验 + 与 JDK `HexFormat` 互算）。
> 教训：**判据必须独立于被测值**；因此新增自检用 JDK17 标准库作独立实现，而不是手抄期望串。
> 这轮改动是「消除重复实现 + 补真值/负对照自检」的防复发加固，**不是修 bug**。

### 本轮真机抓到并修掉的真 bug
1. **`FLAG_IMMUTABLE` 导致 `commit()` 抛 `IllegalArgumentException`**：
   Android `PackageInstaller.Session` 文档明确 targetSdk≥35 时 statusReceiver 必须来自
   mutable PendingIntent（系统要填 `EXTRA_STATUS`）。改 `FLAG_MUTABLE`，
   PendingIntent 显式 `setPackage(本包名)` + receiver `RECEIVER_NOT_EXPORTED` 控制风险。
2. **明文 HTTP 被 Android 9+ 默认策略拒绝**：`Cleartext HTTP traffic to 127.0.0.1 not permitted`。
   用 main/debug 双份 `network_security_config.xml`，只对 debug 放行回环地址。
3. lint 新增 5 条（ObsoleteSdkInt / UseKtx ×3 / toUri）→ 逐条真修，43 → 38。

---

## 7. 仍未验证 / 已知限制（不得写成 PASS）

- 🟡 **真实 GitHub Release 端到端**：发布前仍 UNVERIFIED（此前端到端用 PC 本地模拟 Release）；
  本次创建首个正式版本后按 §6 补真机复验结果，未复验完成前不写 PASS。
- ✅ **固定签名密钥已建立**（§5）：项目专用 keystore（项目外、不入库）+ debug/release 共用
  `signingConfigs.fixed` + 发布脚本 `apksigner` 指纹门禁与负对照。
  剩余约束：换机器/重装系统必须携带同一 keystore，否则新包无法覆盖安装。
- ⚠️ **vivo「超级守护」备案拦截**：真机安装时出现「此应用存在未核准（备案）问题…
  若信任该应用，您可点击授权本次安装」系统弹窗；本次在已授权 appops 的情况下仍完成安装，
  但普通用户可能需要手动点「授权本次安装」。属设备侧策略，App 无法绕过也不应绕过。
- ⚠️ 未做 ETag 条件请求（手动触发、频率极低，60 次/小时足够；若将来加自动检查需补）。
- ⚠️ 未做 APK 断点续传、多 ABI 分包选择（当前单 APK；`abi` 字段已预留）。
- ⚠️ 安装结果广播只在 App 进程存活时可见；进程被杀后无持久化安装结果。
- 与整机相关的既有悬案（真机 GATT 上板、后台保活、真视频、策略启停、手感标定）不受本功能影响，
  `ship_verdict` 仍为 `NOT_SHIPPABLE`。

---

## 8. 本轮改动文件

**core**：`UpdatePolicy.kt`（新增，纯 JVM 决策层）、`CoreSelfTest.kt`（+44 条）
**app**：`update/GithubReleaseClient.kt`、`update/UpdateInstaller.kt`、
`update/UpdateController.kt`、`update/UpdatePanel.kt`（新增）；
`MainActivity.kt`（集成 + debug override + onResume/onDestroy）；
`AndroidManifest.xml`（`REQUEST_INSTALL_PACKAGES` + `networkSecurityConfig`）；
`res/xml/network_security_config.xml` 与 `src/debug/res/xml/` 同名覆盖（新增）
**工具**：`tools/publish_release.py`（新增，dry-run 发布脚本）
**文档**：本文件

### 发布前加固（2026-11-13 晚，用户授权发布后）
**core**：`Hex.kt`（新增，十六进制编码单一真源）、`CoreSelfTest.kt`（+13 条）
**app**：`GithubReleaseClient.kt` / `UpdateInstaller.kt`（删各自私有 `toHex`，改调 `Hex.encode`）；
`app/build.gradle.kts`（固定签名 `signingConfigs.fixed` + `versionCode=2` / `versionName=0.2.0`）
**工具**：`tools/publish_release.py`（`apksigner` 证书指纹门禁，dry-run 也查）
**文档**：本文件（§0 快照注记 / §5 前置 / §6 复验 / §7 状态 / §8）
**刻意不入库**：`local.properties`（密码）、`C:/Users/hejih/.microduck/microduck-release.jks`（密钥）、
`build/baseline-fixed-signed-v1.apk` 与 `build/negctrl-old-debug-signed.apk`（本机临时产物）。
