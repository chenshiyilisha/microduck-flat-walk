package io.microduck.app.core

import com.southernstorm.noise.protocol.CipherState
import com.southernstorm.noise.protocol.DHState
import com.southernstorm.noise.protocol.Noise
import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets
import javax.crypto.BadPaddingException
import javax.crypto.Mac
import javax.crypto.ShortBufferException
import javax.crypto.spec.SecretKeySpec

/**
 * Minimal Noise_NNpsk0_25519_ChaChaPoly_SHA256 session state.
 *
 * Noise-Java's handshake engine predates the current psk modifiers, so this implements only the
 * NNpsk0 token sequence and uses its audited primitive implementations for X25519 and ChaChaPoly.
 */
class NoiseNnPsk0Session internal constructor(
    psk: ByteArray,
    private val role: Role,
    prologue: ByteArray = PROLOGUE,
    testEphemeralPrivateKey: ByteArray?,
) : AutoCloseable {
    constructor(
        psk: ByteArray,
        role: Role,
        prologue: ByteArray = PROLOGUE,
    ) : this(psk, role, prologue, null)

    enum class Role { INITIATOR, RESPONDER }

    private enum class Phase { INITIAL, FIRST_SENT, COMPLETE, FAILED, CLOSED }

    private var phase = Phase.INITIAL
    private var chainingKey: ByteArray
    private var handshakeHash: ByteArray
    private var handshakeCipher: CipherState? = null
    private var localEphemeral: DHState? = null
    private var sendCipher: CipherState? = null
    private var receiveCipher: CipherState? = null
    private var testEphemeralPrivateKey: ByteArray? = testEphemeralPrivateKey?.copyOf()

    init {
        require(psk.size == KEY_SIZE) { "BLE_PSK_LENGTH" }
        require(testEphemeralPrivateKey == null || testEphemeralPrivateKey.size == KEY_SIZE) {
            "NOISE_EPHEMERAL_KEY_LENGTH"
        }
        val name = PROTOCOL.toByteArray(StandardCharsets.US_ASCII)
        handshakeHash = if (name.size <= HASH_SIZE) name.copyOf(HASH_SIZE) else sha256(name)
        chainingKey = handshakeHash.copyOf()
        mixHash(prologue)
        mixKeyAndHash(psk)
    }

    /** Initiator's first message: ephemeral public key and an authenticated empty payload. */
    fun start(): ByteArray {
        check(role == Role.INITIATOR && phase == Phase.INITIAL) { "NOISE_UNEXPECTED_START" }
        val ephemeral = generateEphemeral()
        localEphemeral = ephemeral
        val publicKey = ByteArray(KEY_SIZE)
        ephemeral.getPublicKey(publicKey, 0)
        mixHash(publicKey)
        mixKey(publicKey)
        val payload = encryptAndHash(ByteArray(0))
        phase = Phase.FIRST_SENT
        return publicKey + payload
    }

    /** Initiator consumes the responder's second handshake message. */
    fun finish(response: ByteArray) {
        check(role == Role.INITIATOR && phase == Phase.FIRST_SENT) { "NOISE_UNEXPECTED_RESPONSE" }
        try {
            require(response.size >= KEY_SIZE + TAG_SIZE) { "NOISE_HANDSHAKE_FRAME_LENGTH" }
            val remote = readEphemeral(response, 0)
            mixKey(response.copyOfRange(0, KEY_SIZE))
            mixDh(localEphemeral ?: error("NOISE_EPHEMERAL_MISSING"), remote)
            val payload = decryptAndHash(response.copyOfRange(KEY_SIZE, response.size))
            require(payload.isEmpty()) { "NOISE_HANDSHAKE_PAYLOAD_NOT_EMPTY" }
            split(initiator = true)
            remote.destroy()
            localEphemeral?.destroy()
            localEphemeral = null
            phase = Phase.COMPLETE
        } catch (e: Exception) {
            phase = Phase.FAILED
            throw e
        }
    }

    /** Responder consumes the initiator's first message and returns its authenticated response. */
    fun respond(first: ByteArray): ByteArray {
        check(role == Role.RESPONDER && phase == Phase.INITIAL) { "NOISE_UNEXPECTED_INITIATOR_MESSAGE" }
        try {
            require(first.size >= KEY_SIZE + TAG_SIZE) { "NOISE_HANDSHAKE_FRAME_LENGTH" }
            val remote = readEphemeral(first, 0)
            mixKey(first.copyOfRange(0, KEY_SIZE))
            val payload = decryptAndHash(first.copyOfRange(KEY_SIZE, first.size))
            require(payload.isEmpty()) { "NOISE_HANDSHAKE_PAYLOAD_NOT_EMPTY" }

            val ephemeral = generateEphemeral()
            localEphemeral = ephemeral
            val publicKey = ByteArray(KEY_SIZE)
            ephemeral.getPublicKey(publicKey, 0)
            mixHash(publicKey)
            mixKey(publicKey)
            mixDh(ephemeral, remote)
            val response = publicKey + encryptAndHash(ByteArray(0))
            split(initiator = false)
            remote.destroy()
            ephemeral.destroy()
            localEphemeral = null
            phase = Phase.COMPLETE
            return response
        } catch (e: Exception) {
            phase = Phase.FAILED
            throw e
        }
    }

    fun encrypt(plaintext: ByteArray): ByteArray {
        check(phase == Phase.COMPLETE) { "NOISE_TRANSPORT_NOT_READY" }
        require(plaintext.size <= MAX_PLAINTEXT) { "NOISE_FRAME_TOO_LARGE" }
        val cipher = checkNotNull(sendCipher)
        val ciphertext = ByteArray(plaintext.size + TAG_SIZE)
        val length = cipher.encryptWithAd(null, plaintext, 0, ciphertext, 0, plaintext.size)
        return ciphertext.copyOf(length)
    }

    @Throws(BadPaddingException::class, ShortBufferException::class)
    fun decrypt(ciphertext: ByteArray): ByteArray {
        check(phase == Phase.COMPLETE) { "NOISE_TRANSPORT_NOT_READY" }
        require(ciphertext.size in TAG_SIZE..MAX_PLAINTEXT + TAG_SIZE) { "NOISE_FRAME_LENGTH" }
        val plaintext = ByteArray(ciphertext.size - TAG_SIZE)
        val length = checkNotNull(receiveCipher)
            .decryptWithAd(null, ciphertext, 0, plaintext, 0, ciphertext.size)
        return plaintext.copyOf(length)
    }

    override fun close() {
        if (phase == Phase.CLOSED) return
        phase = Phase.CLOSED
        handshakeCipher?.destroy()
        sendCipher?.destroy()
        receiveCipher?.destroy()
        localEphemeral?.destroy()
        handshakeCipher = null
        sendCipher = null
        receiveCipher = null
        localEphemeral = null
        testEphemeralPrivateKey?.fill(0)
        testEphemeralPrivateKey = null
        chainingKey.fill(0)
        handshakeHash.fill(0)
    }

    private fun generateEphemeral(): DHState =
        Noise.createDH("25519").also { ephemeral ->
            val fixedKey = testEphemeralPrivateKey
            if (fixedKey == null) {
                ephemeral.generateKeyPair()
            } else {
                ephemeral.setPrivateKey(fixedKey, 0)
            }
        }

    private fun readEphemeral(message: ByteArray, offset: Int): DHState {
        val publicKey = message.copyOfRange(offset, offset + KEY_SIZE)
        require(publicKey.any { it != 0.toByte() }) { "NOISE_NULL_EPHEMERAL" }
        return Noise.createDH("25519").also {
            it.setPublicKey(publicKey, 0)
            require(!it.isNullPublicKey) { "NOISE_NULL_EPHEMERAL" }
            mixHash(publicKey)
        }
    }

    private fun mixDh(local: DHState, remote: DHState) {
        val shared = ByteArray(KEY_SIZE)
        try {
            local.calculate(shared, 0, remote)
            require(shared.any { it != 0.toByte() }) { "NOISE_NULL_SHARED_SECRET" }
            mixKey(shared)
        } finally {
            shared.fill(0)
        }
    }

    private fun mixHash(data: ByteArray) {
        val digest = Noise.createHash("SHA256")
        digest.update(handshakeHash)
        handshakeHash = digest.digest(data)
    }

    private fun mixKey(input: ByteArray) {
        val outputs = hkdf(chainingKey, input, 2)
        chainingKey.fill(0)
        chainingKey = outputs[0]
        replaceHandshakeCipher(outputs[1])
    }

    private fun mixKeyAndHash(input: ByteArray) {
        val outputs = hkdf(chainingKey, input, 3)
        chainingKey.fill(0)
        chainingKey = outputs[0]
        mixHash(outputs[1])
        replaceHandshakeCipher(outputs[2])
    }

    private fun replaceHandshakeCipher(key: ByteArray) {
        handshakeCipher?.destroy()
        handshakeCipher = Noise.createCipher("ChaChaPoly").also { it.initializeKey(key, 0) }
        key.fill(0)
    }

    private fun encryptAndHash(plaintext: ByteArray): ByteArray {
        val cipher = checkNotNull(handshakeCipher)
        val ciphertext = ByteArray(plaintext.size + TAG_SIZE)
        val length = cipher.encryptWithAd(
            handshakeHash,
            plaintext,
            0,
            ciphertext,
            0,
            plaintext.size,
        )
        val result = ciphertext.copyOf(length)
        mixHash(result)
        return result
    }

    private fun decryptAndHash(ciphertext: ByteArray): ByteArray {
        val plaintext = ByteArray(ciphertext.size - TAG_SIZE)
        val length = checkNotNull(handshakeCipher).decryptWithAd(
            handshakeHash,
            ciphertext,
            0,
            plaintext,
            0,
            ciphertext.size,
        )
        val result = plaintext.copyOf(length)
        mixHash(ciphertext)
        return result
    }

    private fun split(initiator: Boolean) {
        val keys = hkdf(chainingKey, ByteArray(0), 2)
        val first = Noise.createCipher("ChaChaPoly").also { it.initializeKey(keys[0], 0) }
        val second = Noise.createCipher("ChaChaPoly").also { it.initializeKey(keys[1], 0) }
        keys.forEach { it.fill(0) }
        handshakeCipher?.destroy()
        handshakeCipher = null
        chainingKey.fill(0)
        if (initiator) {
            sendCipher = first
            receiveCipher = second
        } else {
            sendCipher = second
            receiveCipher = first
        }
    }

    private fun hkdf(chainingKey: ByteArray, input: ByteArray, count: Int): Array<ByteArray> {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(chainingKey, "HmacSHA256"))
        val tempKey = mac.doFinal(input)
        val outputs = Array(count) { ByteArray(HASH_SIZE) }
        var previous = ByteArray(0)
        for (i in 0 until count) {
            mac.init(SecretKeySpec(tempKey, "HmacSHA256"))
            val block = ByteArrayOutputStream().apply {
                write(previous)
                write(i + 1)
            }.toByteArray()
            previous = mac.doFinal(block)
            System.arraycopy(previous, 0, outputs[i], 0, HASH_SIZE)
        }
        tempKey.fill(0)
        previous.fill(0)
        return outputs
    }

    private fun sha256(data: ByteArray): ByteArray =
        Noise.createHash("SHA256").digest(data)

    companion object {
        const val PROTOCOL = "Noise_NNpsk0_25519_ChaChaPoly_SHA256"
        val PROLOGUE: ByteArray = "microduck-ble-v1".toByteArray(StandardCharsets.US_ASCII)
        private const val KEY_SIZE = 32
        private const val HASH_SIZE = 32
        private const val TAG_SIZE = 16
        private const val MAX_PLAINTEXT = 64 * 1024
    }
}
