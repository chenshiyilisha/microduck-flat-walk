#!/usr/bin/env python3
"""§4 配网加密 golden vector：独立生成 + 与 App WireGolden 常量一致性自检。

用途（路线 B 落地前的可验证工程资产）：
  1) 用 Python `cryptography`（独立实现，非 App 的 Kotlin/JCA）按 §4 wire 全链生成
     确定性 golden vector —— X25519 → HKDF-SHA256 → AES-256-GCM。
  2) --check：把生成值与 App `ProvisioningCrypto.WireGolden` 里的常量逐字节比对，
     漂移即红（防止谁手改 hex 而 KAT 还绿）。带负对照证明判据有效。

🔴 边界：本工具证明「两条独立代码路径算法一致」，不等于真机互通；
   INTEROP_UNVERIFIED 恒真，ship_verdict=NOT_SHIPPABLE 不变。

一手向量来源：X25519/hkdf/aesgcm 参数全部来自
  docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md §4。
依赖：Project .venv-mjlab（cryptography 50.0.2 已核可用）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as e:
    print("DEPENDENCY_MISSING: 用 microduck-software/.venv-mjlab/Scripts/python.exe 运行；" + str(e))
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = REPO_ROOT / "core/src/main/kotlin/io/microduck/app/core/ProvisioningCrypto.kt"

H2B = lambda s: bytes.fromhex(s)
B2H = lambda b: b.hex()

# ---- 固定输入（RFC7748 §6.1 权威向量 + 确定性 salt/nonce；plaintext 为测试凭据，非真实密码）----
CLIENT_PRIV = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
ROBOT_PRIV = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"
CLIENT_PUB = "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
ROBOT_PUB = "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
SALT = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
NONCE = "000102030405060708090a0b"
INFO = b"microduck/wifi-provision/v1"
AAD = b"net.connect"
PLAINTEXT = b'{"ssid":"DS1002","psk":"TestPass123"}'

# RFC7748 §6.1 权威 shared，作为独立交叉校验锚点（不取自被测实现）
RFC7748_SHARED = "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"


def generate() -> dict:
    a = X25519PrivateKey.from_private_bytes(H2B(CLIENT_PRIV))
    b_pub = X25519PublicKey.from_public_bytes(H2B(ROBOT_PUB))
    shared = a.exchange(b_pub)
    assert B2H(shared) == RFC7748_SHARED, "X25519 shared 与 RFC7748 权威向量不符"

    # 公钥必须由私钥派生一致（绑定 transcript 的输入不能是手抄错值）
    def pub_of(priv_hex: str) -> str:
        k = X25519PrivateKey.from_private_bytes(H2B(priv_hex))
        return B2H(k.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    assert pub_of(CLIENT_PRIV) == CLIENT_PUB, "client_pub 与 client_priv 不匹配"
    assert pub_of(ROBOT_PRIV) == ROBOT_PUB, "robot_pub 与 robot_priv 不匹配"

    ikm = shared + H2B(CLIENT_PUB) + H2B(ROBOT_PUB)
    key = HKDF(algorithm=hashes.SHA256(), length=32,
               salt=H2B(SALT), info=INFO).derive(ikm)
    ct = AESGCM(key).encrypt(H2B(NONCE), PLAINTEXT, AAD)
    blob = H2B(NONCE) + ct
    # 自环：解封得回明文
    assert AESGCM(key).decrypt(H2B(NONCE), ct, AAD) == PLAINTEXT
    return {
        "CLIENT_PRIV": CLIENT_PRIV, "ROBOT_PRIV": ROBOT_PRIV,
        "CLIENT_PUB": CLIENT_PUB, "ROBOT_PUB": ROBOT_PUB,
        "SALT": SALT, "NONCE": NONCE,
        "SHARED": B2H(shared), "KEY": B2H(key),
        "PLAINTEXT": PLAINTEXT.decode(), "BLOB": B2H(blob),
    }


def read_app_wire_golden() -> dict:
    src = APP_SRC.read_text(encoding="utf-8")
    m = re.search(r"object WireGolden \{(.*?)\n    \}", src, re.S)
    if not m:
        raise SystemExit("APP_WIRE_GOLDEN_NOT_FOUND: " + str(APP_SRC))
    block = m.group(1)
    out = {}
    for name in ("CLIENT_PRIV", "ROBOT_PRIV", "CLIENT_PUB", "ROBOT_PUB",
                 "SALT", "NONCE", "SHARED", "KEY", "PLAINTEXT", "BLOB"):
        mm = re.search(r'const val ' + name + r' = "((?:[^"\\]|\\.)*)"', block)
        if not mm:
            raise SystemExit("APP_CONST_MISSING: " + name)
        raw = mm.group(1)
        # App 的 PLAINTEXT 用 Kotlin 转义 \" ——还原为真实 JSON 文本再比对
        out[name] = raw.replace('\\"', '"')
    return out


def check() -> int:
    gen = generate()
    app = read_app_wire_golden()
    fails = []
    for k, v in gen.items():
        if app.get(k) != v:
            fails.append("%s:\n    generated = %s\n    app       = %s" % (k, v, app.get(k)))
    # 负对照：确认比对器会因单字节改动变红（否则"相等"无意义）
    neg = dict(gen); neg["BLOB"] = gen["BLOB"][:-2] + ("00" if gen["BLOB"][-2:] != "00" else "01")
    if all(neg.get(k) == app.get(k) for k in gen):
        fails.append("NEGATIVE_CONTROL_BROKEN: 改坏 BLOB 末字节比对器竟未变红")

    if fails:
        print("CHECK FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("CHECK PASS: App WireGolden 全部 %d 个常量与 Python 独立实现逐字节一致" % len(gen))
    print("  负对照：篡改 BLOB 末字节 → 比对变红（判据有效）")
    print("  边界：INTEROP_UNVERIFIED 恒真 —— 算法一致 ≠ 真机互通，ship_verdict=NOT_SHIPPABLE 不变")
    return 0


def selftest() -> int:
    """注入式负对照：证明 generate()/比对/跨语言不变量不是碰巧绿。"""
    import copy
    results = []

    def ck(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    v = generate()
    # 正对照：两条独立实现一致（App 常量 == Python 生成）
    app = read_app_wire_golden()
    ck("正对照: App WireGolden 10 常量全等", all(app.get(k) == val for k, val in v.items()))

    # 负对照 1：X25519 shared 必须是 RFC7748 权威值（不是任取）
    ck("负对照: shared 等于 RFC7748 权威 K", v["SHARED"] == RFC7748_SHARED and
       v["SHARED"] != "00" * 32)

    # 负对照 2：私钥标量改动 → 派生 shared 必变（证明标量乘法真做了，不是常量返回）。
    # 🔴 关键坑（负对照曾失败后一手查证）：RFC7748 §5 clamp 会清 byte0 低 3 位，
    #    改 1<<0 被吞掉、shared 不变 ⇒ 必须改不被 clamp 的位（byte0 的 1<<3）。
    bad_priv = bytearray(H2B(CLIENT_PRIV))
    bad_priv[0] ^= (1 << 3)
    bad_shared = X25519PrivateKey.from_private_bytes(bytes(bad_priv)).exchange(
        X25519PublicKey.from_public_bytes(H2B(ROBOT_PUB)))
    ck("负对照: 改 client_priv 非 clamp 位 → shared 变", B2H(bad_shared) != v["SHARED"])

    # 负对照 3：AES-GCM 密文单字节篡改 → 解封失败（完整性）
    ct = H2B(v["BLOB"])[12:]
    bad_ct = bytearray(ct); bad_ct[0] ^= 1
    rejected = False
    try:
        AESGCM(H2B(v["KEY"])).decrypt(H2B(NONCE), bytes(bad_ct), AAD)
    except Exception:
        rejected = True
    ck("负对照: 篡改密文 → GCM 解封失败", rejected)

    # 负对照 4：AAD 不符 → 解封失败（绑定 wire 方法名）
    aad_rejected = False
    try:
        AESGCM(H2B(v["KEY"])).decrypt(H2B(NONCE), ct, b"net.forget")
    except Exception:
        aad_rejected = True
    ck("负对照: AAD 改 net.forget → 解封失败", aad_rejected)

    # 负对照 5：比对器对单字节改动敏感
    neg = copy.deepcopy(v); neg["KEY"] = v["KEY"][:-1] + ("0" if v["KEY"][-1] != "0" else "1")
    ck("负对照: KEY 末字节改动 → 比对不等", neg["KEY"] != app["KEY"])

    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print("  %s  %s" % ("PASS" if ok else "FAIL", name))
    print("SELFTEST: %d/%d passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="比对 App WireGolden 与独立实现")
    ap.add_argument("--selftest", action="store_true", help="注入式负对照自检")
    ap.add_argument("--json", action="store_true", help="打印 golden vector JSON")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.check:
        return check()
    v = generate()
    if args.json:
        print(json.dumps(v, ensure_ascii=False, indent=2))
    else:
        for k, val in v.items():
            print("%-12s = %s" % (k, val))
    return 0


if __name__ == "__main__":
    sys.exit(main())
