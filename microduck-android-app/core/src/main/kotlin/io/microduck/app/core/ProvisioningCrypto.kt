package io.microduck.app.core

import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.PublicKey
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Wi-Fi 配网应用层加密**能力预埋 / 参考实现**（A2'）—— 默认不接入真实配网路径。
 *
 * 🔴🔴 交付边界（先读这段，别急着接入）—— 一手核验，2026-11-17：
 * 1. 目标固件 fanhao fork `btd/src/route.rs:139-155`：`net.connect` 的 Wi-Fi passphrase
 *    **明文跨 BLE**，`--require-pairing` 默认 off，bond 是 just-works 无认证，「passphrase
 *    crosses in clear … §8.1 is the blocker that has to close before a robot goes to anyone」。
 * 2. 原厂 `app-path-design.md` §8.1 的三种修复（修链路层 / 应用层封密 / 会话封密）**都需要
 *    固件端改动**；本仓库内的 fanhao/BoBo/hd1910m 固件源码全树**零**应用层加解密实现、
 *    Cargo.toml **零** crypto 依赖（x25519/hkdf/aes-gcm 全无）。App 单侧加密无法互操作。
 * 3. 本 App `minSdk=26`；Android 平台 X25519 到 API 34 才有限支持、HPKE 到 API 37
 *    （Conscrypt 官方发布说明，2026-11-17 查）——本类用 JDK `javax.crypto` 仅在 JVM 自检可跑，
 *    不能假定在低版本真机可用。
 * ⇒ 本类是**跨端对拍夹具 + 接口预埋**：`KAT` 证明「算法实现正确」，为固件端实现提供权威
 *    对拍向量；`INTEROP_UNVERIFIED=true` 恒定，表示**从未与真固件互通验证**。
 *    `NetProvisioning.connectParams` 仍走明文（原厂现状），本类**不**被任何配网 UI 调用。
 *    谁要接入，必须先让固件端实现同一套 wire（见 docs/active 固件对接规格文档）并真机对拍。
 *
 * ── 算法与一手测试向量（全部 RFC 原文，非自推）──
 * · X25519：RFC 7748 §6.1 —— a/b 私钥、公钥、共享密钥 K；KAT-1 复现 K，KAT-2 复现 K 且双方对称。
 * · HKDF-SHA256：RFC 5869 §A.1 Test Case 1 —— IKM(22×0b)/salt/info/L=42 → 42-byte OKM。
 * · AES-256-GCM：JDK 标准 AEAD，roundtrip + 篡改密文必须失败（GCM 的完整性保证）。
 * · 低阶点防护：RFC 7748 §7 —— 全零共享密钥必须拒绝（小阶点攻击）。
 *
 * wire 约定（供固件端实现，详见 docs/active 固件对接规格）：
 *   salt = 32B 随机（每会话），info = ASCII "microduck/wifi-provision/v1" 。
 *   密钥 = HKDF-SHA256(ikm = X25519 shared || client_pub || robot_pub, salt, info, 32)。
 *   nonce = 12B 随机，AAD = ASCII 方法名 "net.connect"，密文 = AES-256-GCM(key, nonce, AAD, plaintext JSON)。
 */
object ProvisioningCrypto {
    /** 恒为 true：从未与真固件互通验证，不可写成 PASS。 */
    const val INTEROP_UNVERIFIED = true
    const val HKDF_INFO = "microduck/wifi-provision/v1"
    const val AAD_METHOD = "net.connect"

    /** RFC 7748 §6.1 的权威向量（hex），供 KAT 与固件对拍共用。 */
    object Rfc7748 {
        const val ALICE_PRIV = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
        const val ALICE_PUB = "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
        const val BOB_PRIV = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"
        const val BOB_PUB = "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
        const val SHARED = "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    }

    /** RFC 5869 §A.1 Test Case 1 的权威向量（hex）。 */
    object Rfc5869Tc1 {
        const val IKM = "0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b" // 22 octets
        const val SALT = "000102030405060708090a0b0c"
        const val INFO = "f0f1f2f3f4f5f6f7f8f9"
        const val OKM = "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    }

    // ---- hex 工具（纯 JVM，无 Gson 依赖）----
    fun hexDecode(s: String): ByteArray {
        require(s.length % 2 == 0) { "HEX_ODD_LENGTH" }
        return ByteArray(s.length / 2) { i -> ((Character.digit(s[i * 2], 16) shl 4) or Character.digit(s[i * 2 + 1], 16)).toByte() }
    }
    fun hexEncode(b: ByteArray): String = buildString { for (x in b) append("%02x".format(x.toInt() and 0xff)) }

    private fun concat(vararg xs: ByteArray): ByteArray {
        val n = xs.sumOf { it.size }
        val out = ByteArray(n)
        var p = 0
        for (x in xs) { System.arraycopy(x, 0, out, p, x.size); p += x.size }
        return out
    }

    // ---- RFC 8410 编码包装：raw 32B ↔ PKCS8/X509 ----
    // X25519 的 PKCS8 = 302e020100300506032b656e04220420 || raw(32)
    // X25519 的 SPKI  = 302a300506032b656e032100 || raw(32)
    private val PKCS8_PREFIX = hexDecode("302e020100300506032b656e04220420")
    private val SPKI_PREFIX = hexDecode("302a300506032b656e032100")

    fun privateKeyFromRaw(raw: ByteArray): PrivateKey {
        require(raw.size == 32) { "X25519_PRIV_LEN" }
        return KeyFactory.getInstance("X25519").generatePrivate(PKCS8EncodedKeySpec(concat(PKCS8_PREFIX, raw)))
    }

    fun publicKeyFromRaw(raw: ByteArray): PublicKey {
        require(raw.size == 32) { "X25519_PUB_LEN" }
        return KeyFactory.getInstance("X25519").generatePublic(X509EncodedKeySpec(concat(SPKI_PREFIX, raw)))
    }

    /** 生成临时 X25519 密钥对（每会话新鲜，前向保密）。raw 私钥 32B。 */
    fun generateEphemeral(): Pair<ByteArray, ByteArray> {
        val kp: KeyPair = KeyPairGenerator.getInstance("X25519").generateKeyPair()
        // 从 PKCS8 / X509 尾部取 raw：私钥末 32B、公钥末 32B（RFC 8410 固定结构）
        val priv = kp.private.encoded
        val pub = kp.public.encoded
        return Pair(priv.copyOfRange(priv.size - 32, priv.size), pub.copyOfRange(pub.size - 32, pub.size))
    }

    /**
     * X25519 密钥协商；全零共享密钥（低阶点）必须拒绝返回 null（RFC 7748 §7）。
     */
    fun x25519(privateRaw: ByteArray, peerPublicRaw: ByteArray): ByteArray? = try {
        val ka = KeyAgreement.getInstance("X25519")
        ka.init(privateKeyFromRaw(privateRaw))
        ka.doPhase(publicKeyFromRaw(peerPublicRaw), true)
        val secret = ka.generateSecret()
        // JDK 的 XDHKeyAgreement 在 doPhase 已对小阶点抛 InvalidKeyException（RFC 7748 §7 防护），
        // 这里再兜一层全零检查（规范建议的 OR 归零判定），两条路径都统一返回 null=拒绝。
        if (secret.all { it == 0.toByte() }) null else secret
    } catch (e: java.security.InvalidKeyException) {
        null // 低阶点 / 非法公钥 → 拒绝协商，不泄漏、不崩溃
    }

    /** HKDF-SHA256（RFC 5869 的 extract+expand），纯 JCA Mac 实现。 */
    fun hkdfSha256(ikm: ByteArray, salt: ByteArray, info: ByteArray, length: Int): ByteArray {
        require(length in 1..255 * 32) { "HKDF_LENGTH" }
        val hmac = Mac.getInstance("HmacSHA256")
        val realSalt = if (salt.isEmpty()) ByteArray(32) else salt
        hmac.init(SecretKeySpec(realSalt, "HmacSHA256"))
        val prk = hmac.doFinal(ikm)
        val okm = ByteArray(length)
        var pos = 0
        var t = ByteArray(0)
        var i = 1
        while (pos < length) {
            hmac.init(SecretKeySpec(prk, "HmacSHA256"))
            t = hmac.doFinal(concat(t, info, byteArrayOf(i.toByte())))
            val copy = minOf(t.size, length - pos)
            System.arraycopy(t, 0, okm, pos, copy)
            pos += copy
            i++
        }
        return okm
    }

    /**
     * 会话密钥派生：ikm = shared || client_pub || robot_pub（把双方公钥绑进 transcript，
     * 符合 RFC 7748「KDF 应包含 K_A/K_B」的建议 + RFC 搜索结果「include both public keys」）。
     */
    fun deriveSessionKey(shared: ByteArray, clientPub: ByteArray, robotPub: ByteArray, salt: ByteArray): ByteArray =
        hkdfSha256(concat(shared, clientPub, robotPub), salt, HKDF_INFO.toByteArray(Charsets.US_ASCII), 32)

    /** AES-256-GCM 封密；返回 nonce(12) || ciphertext||tag。 */
    fun seal(key: ByteArray, plaintext: ByteArray, aad: String = AAD_METHOD): ByteArray {
        val nonce = ByteArray(12).also { java.security.SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(aad.toByteArray(Charsets.US_ASCII))
        return concat(nonce, cipher.doFinal(plaintext))
    }

    /** AES-256-GCM 解封；tag 不符/篡改抛 AEADBadTagException。 */
    fun open(key: ByteArray, blob: ByteArray, aad: String = AAD_METHOD): ByteArray {
        require(blob.size > 12) { "GCM_BLOB_TOO_SHORT" }
        val nonce = blob.copyOfRange(0, 12)
        val ct = blob.copyOfRange(12, blob.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(aad.toByteArray(Charsets.US_ASCII))
        return cipher.doFinal(ct)
    }
}
