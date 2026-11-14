#!/usr/bin/env python3
"""MicroDuck 安卓 App 的 GitHub Releases 发布脚本（本地运行，带 --dry-run）。

把「构建 APK → 生成机器可读 update.json → 创建 Release → 上传 assets」串起来，
让 App 内的更新检查真的有东西可查。默认 **dry-run**，不写任何远端状态。

一手依据（2026-11-13 核验）：
  · GitHub Docs「REST API endpoints for releases」：
      GET  /repos/{owner}/{repo}/releases/tags/{tag}   查询同 tag 是否已发布
      POST /repos/{owner}/{repo}/releases              创建 release
      GET  /repos/{owner}/{repo}/releases/latest       App 侧读取；只返回
           「most recent non-prerelease, non-draft release」
  · GitHub Docs「REST API endpoints for release assets」：
      上传用创建 release 响应里的 upload_url（host 为 uploads.github.com），
      必带 Content-Length / Content-Type，原始二进制作 body，查询参数 name。
  · GitHub Docs「Troubleshooting / User agent required」：所有请求必须带有效 User-Agent。
  · Google Android《对应用进行版本控制》：versionCode 必须单调递增；
    《为应用签名》：覆盖安装要求同一签名证书 ⇒ 本脚本用 apksigner 实读 APK 证书指纹，
    与 EXPECTED_SIGNER_SHA256 不符一律拒发（含 --dry-run，不静默放行）。
  · core/UpdatePolicy.kt：App 侧对 update.json / tag / sha256 的校验规则，
    本脚本生成的清单必须与之一致（单一真源：字段与 schema 常量对齐）；
    core/Hex.kt 是摘要十六进制编码的单一真源，两条消费链共用。

用法：
  python tools/publish_release.py --tag v0.2.0 --dry-run
  GITHUB_TOKEN=xxx python tools/publish_release.py --tag v0.2.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
BUILD_GRADLE = BASE / "app" / "build.gradle.kts"
DEFAULT_APK = BASE / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
MANIFEST_ASSET = "update.json"
MANIFEST_SCHEMA = 1
USER_AGENT = "io.microduck.app-publish-release"
# 项目专用固定签名证书的 SHA-256 指纹（C:/Users/hejih/.microduck/microduck-release.jks，
# alias=microduck；keystore 与密码都放在本机 local.properties，绝不入库）。
# 换证书必须同步改这里，否则所有已装用户无法覆盖安装（Google《为应用签名》）。
EXPECTED_SIGNER_SHA256 = "bd1e5c2907189c0bc0525ac9f4e9aba4502cf56eefa259501928fe6da95268d6"


def android_sdk_dir() -> Path | None:
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(key)
        if v and Path(v).is_dir():
            return Path(v)
    lp = BASE / "local.properties"
    if lp.is_file():
        for line in lp.read_text(encoding="utf-8").splitlines():
            if line.startswith("sdk.dir="):
                raw = line.split("=", 1)[1].replace("\\:", ":").replace("\\\\", "\\")
                p = Path(raw)
                if p.is_dir():
                    return p
    return None


def find_apksigner() -> Path | None:
    sdk = android_sdk_dir()
    if sdk is None:
        return None
    bt = sdk / "build-tools"
    if not bt.is_dir():
        return None
    for d in sorted(bt.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        for name in ("apksigner.bat", "apksigner"):
            exe = d / name
            if exe.is_file():
                return exe
    return None


def verify_signer(apk: Path) -> tuple[bool, str]:
    """实读 APK 签名证书指纹；拿不到工具/解析不出指纹一律判失败，不静默放行。"""
    exe = find_apksigner()
    if exe is None:
        return False, "找不到 apksigner（ANDROID_HOME / local.properties 的 sdk.dir），拒绝发布"
    try:
        r = subprocess.run([str(exe), "verify", "--print-certs", str(apk)],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"apksigner 执行失败：{e}"
    text = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        return False, f"apksigner verify 返回 {r.returncode}：{text.strip()[:200]}"
    fps = [m.group(1).replace(":", "").lower()
           for m in re.finditer(r"SHA-256 digest:\s*([0-9a-fA-F:]+)", text)]
    if not fps:
        return False, "apksigner 输出里没有证书 SHA-256 指纹，拒绝发布"
    if any(fp != EXPECTED_SIGNER_SHA256 for fp in fps):
        return False, ("签名证书指纹与 EXPECTED_SIGNER_SHA256 不符：实得 "
                       + ", ".join(fps) + "（可能误用了默认 debug 证书或换了 keystore）")
    return True, ", ".join(fps)


def read_gradle_versions() -> tuple[str, int, int]:
    text = BUILD_GRADLE.read_text(encoding="utf-8")
    def grab(pattern: str) -> str:
        m = re.search(pattern, text)
        if not m:
            raise SystemExit("无法从 build.gradle.kts 解析：" + pattern)
        return m.group(1)
    name = grab(r'versionName\s*=\s*"([^"]+)"')
    code = int(grab(r"versionCode\s*=\s*(\d+)"))
    min_sdk = int(grab(r"minSdk\s*=\s*(\d+)"))
    return name, code, min_sdk


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def github_request(url: str, token: str | None, method: str = "GET",
                   body: bytes | None = None, content_type: str | None = None) -> tuple[int, bytes, dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def build_manifest(version_name: str, version_code: int, min_sdk: int,
                   apk_name: str, digest: str, abi: str) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "versionName": version_name,
        "versionCode": version_code,
        "apkAsset": apk_name,
        "sha256": digest,
        "minSdk": min_sdk,
        "abi": abi,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="发布 MicroDuck 安卓 APK 到 GitHub Releases")
    ap.add_argument("--tag", required=True, help="形如 v<versionName>，必须与 build.gradle.kts 一致")
    ap.add_argument("--apk", type=Path, default=DEFAULT_APK, help="要发布的 APK 路径")
    ap.add_argument("--repo", default="chenshiyilisha/microduck-flat-walk")
    ap.add_argument("--abi", default="universal", help="APK 的目标 ABI（写入清单，供 App 选包）")
    ap.add_argument("--notes", default="", help="Release 说明文本")
    ap.add_argument("--prerelease", action="store_true",
                    help="标为预发布；latest 端点会跳过它，App 不会提示更新")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划与清单，不发任何写请求")
    ap.add_argument("--token-env", default="GITHUB_TOKEN", help="存放 token 的环境变量名")
    args = ap.parse_args()

    version_name, version_code, min_sdk = read_gradle_versions()
    problems: list[str] = []
    tag_version = args.tag.lstrip("v")
    if tag_version != version_name:
        problems.append(f"tag({args.tag}) 与 versionName({version_name}) 不一致（App 侧 validate 会拒绝）")
    if not args.apk.is_file():
        problems.append(f"APK 不存在：{args.apk}")
    if not re.fullmatch(r"v[0-9A-Za-z.\-+]+", args.tag):
        problems.append(f"tag 格式不合法：{args.tag}")
    if args.apk.is_file():
        signer_ok, signer_detail = verify_signer(args.apk)
        if not signer_ok:
            problems.append(signer_detail)
    if problems:
        for p in problems:
            print("  FAIL  " + p)
        return 2

    digest = sha256_file(args.apk)
    apk_name = args.apk.name
    if not apk_name.endswith(".apk"):
        print("  FAIL  asset 名必须以 .apk 结尾：" + apk_name)
        return 2
    manifest = build_manifest(version_name, version_code, min_sdk, apk_name, digest, args.abi)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    print("=== 发布计划（" + ("DRY-RUN，不会写远端" if args.dry_run else "真实执行") + "）===")
    print(f"  仓库        : {args.repo}")
    print(f"  tag         : {args.tag}")
    print(f"  versionName : {version_name}")
    print(f"  versionCode : {version_code}  (必须比上一版大)")
    print(f"  minSdk      : {min_sdk}")
    print(f"  APK         : {args.apk}  ({args.apk.stat().st_size} B)")
    print(f"  sha256      : {digest}")
    print(f"  signer      : {EXPECTED_SIGNER_SHA256}  (apksigner 实读已核对)")
    print(f"  prerelease  : {args.prerelease}")
    print("  ✓ 签名门禁：本 APK 证书指纹已与 EXPECTED_SIGNER_SHA256 实读比对通过；")
    print("     不一致会在 dry-run 阶段就拒发（Google《为应用签名》：不同证书无法覆盖安装）。")
    print("  --- update.json ---")
    print(manifest_bytes.decode("utf-8").rstrip())

    if args.dry_run:
        print("  RESULT: DRY-RUN OK（未创建 Release、未上传任何 asset）")
        return 0

    token = os.environ.get(args.token_env)
    if not token:
        print(f"  FAIL  环境变量 {args.token_env} 未设置；需要 Contents: write 权限的 token")
        return 2
    api = "https://api.github.com/repos/" + args.repo

    code, _, _ = github_request(api + "/releases/tags/" + urllib.parse.quote(args.tag), token)
    if code != 404:
        print(f"  FAIL  tag {args.tag} 已存在或查询失败（HTTP {code}）；拒绝重复发布")
        return 2

    payload = json.dumps({
        "tag_name": args.tag,
        "name": args.tag,
        "body": args.notes or f"MicroDuck Android {version_name} ({version_code})",
        "draft": False,
        "prerelease": args.prerelease,
        "make_latest": "false" if args.prerelease else "true",
    }, ensure_ascii=False).encode("utf-8")
    code, resp, _ = github_request(api + "/releases", token, "POST", payload, "application/json")
    if code not in (200, 201):
        print(f"  FAIL  创建 Release 失败 HTTP {code}: {resp.decode('utf-8', 'replace')[:300]}")
        return 2
    release = json.loads(resp)
    print(f"  OK    创建 Release: {release.get('html_url')}")

    upload_template = release.get("upload_url", "")
    upload_base = upload_template.split("{", 1)[0]
    if not upload_base:
        print("  FAIL  release 响应缺 upload_url")
        return 2

    for name, data, ctype in (
        (apk_name, args.apk.read_bytes(), "application/vnd.android.package-archive"),
        (MANIFEST_ASSET, manifest_bytes, "application/json"),
    ):
        url = upload_base + "?" + urllib.parse.urlencode({"name": name})
        code, resp, _ = github_request(url, token, "POST", data, ctype)
        if code not in (200, 201):
            print(f"  FAIL  上传 {name} 失败 HTTP {code}: {resp.decode('utf-8', 'replace')[:300]}")
            return 2
        print(f"  OK    上传 asset {name} ({len(data)} B)")

    code, resp, _ = github_request(api + "/releases/tags/" + urllib.parse.quote(args.tag), token)
    if code == 200:
        names = [a.get("name") for a in json.loads(resp).get("assets", [])]
        print("  OK    回读 assets: " + ", ".join(str(n) for n in names))
        if MANIFEST_ASSET not in names or apk_name not in names:
            print("  FAIL  回读缺 asset，App 侧会判「清单缺失」")
            return 2
    else:
        print(f"  WARN  回读失败 HTTP {code}（不影响已上传结果，但需人工核对）")
    print("  RESULT: PUBLISHED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
