package io.microduck.app.core

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.util.Base64

internal object NoiseBleFrameCodec {
    private const val FIELD = "_microduck_noise"
    private const val VERSION = 1
    private const val MAX_CIPHERTEXT = 64 * 1024 + 16
    private const val MAX_BASE64 = 90 * 1024

    enum class Type(val wireName: String) {
        INIT("init"),
        REPLY("reply"),
        DATA("data"),
    }

    data class Frame(val type: Type, val payload: ByteArray)

    fun encode(type: Type, payload: ByteArray): String {
        require(payload.size <= MAX_CIPHERTEXT) { "BLE_NOISE_FRAME_TOO_LARGE" }
        return JsonObject().apply {
            addProperty(FIELD, VERSION)
            addProperty("type", type.wireName)
            addProperty("data", Base64.getEncoder().encodeToString(payload))
        }.toString()
    }

    fun decode(line: String): Frame {
        require(line.length <= MAX_BASE64) { "BLE_NOISE_LINE_TOO_LARGE" }
        val json = JsonParser.parseString(line).asJsonObject
        require(json.size() == 3 && json.has(FIELD) && json.has("type") && json.has("data")) {
            "BLE_NOISE_INVALID_ENVELOPE"
        }
        require(json.get(FIELD).asInt == VERSION) { "BLE_NOISE_UNSUPPORTED_VERSION" }
        val type = Type.entries.firstOrNull { it.wireName == json.get("type").asString }
            ?: throw IllegalArgumentException("BLE_NOISE_INVALID_TYPE")
        val encoded = json.get("data").asString
        require(encoded.length <= MAX_BASE64) { "BLE_NOISE_DATA_TOO_LARGE" }
        val payload = Base64.getDecoder().decode(encoded)
        require(payload.size <= MAX_CIPHERTEXT) { "BLE_NOISE_FRAME_TOO_LARGE" }
        return Frame(type, payload)
    }
}
