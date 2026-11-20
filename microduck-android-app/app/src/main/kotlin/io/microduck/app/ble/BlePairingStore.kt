package io.microduck.app.ble

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import io.microduck.app.core.ProvisioningCrypto

object BlePairingStore {
    data class Pairing(val serial: String, val name: String, val psk: ByteArray)

    private const val FILE = "microduck_ble_pairings"
    private val serialPattern = Regex("[A-Za-z0-9._-]{1,64}")

    private fun prefs(context: Context): SharedPreferences {
        val masterKey = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            FILE,
            masterKey,
            context.applicationContext,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun parsePairingUri(uri: Uri): Pairing {
        require(uri.scheme == "microduck" && uri.host == "pair" && uri.path == "/v1") {
            "BLE_PAIRING_URI_INVALID"
        }
        val parameters = uri.queryParameterNames
        require(parameters == setOf("serial", "name", "psk") &&
            parameters.all { uri.getQueryParameters(it).size == 1 }) {
            "BLE_PAIRING_FIELDS_INVALID"
        }
        val serial = requireNotNull(uri.getQueryParameter("serial")).trim()
        val name = requireNotNull(uri.getQueryParameter("name")).trim()
        val pskText = requireNotNull(uri.getQueryParameter("psk"))
        require(serialPattern.matches(serial)) { "BLE_PAIRING_SERIAL_INVALID" }
        require(name.isNotEmpty() && name.length <= 64 && name.none { it.isISOControl() }) {
            "BLE_PAIRING_NAME_INVALID"
        }
        require(pskText.matches(Regex("[0-9a-fA-F]{64}"))) { "BLE_PAIRING_PSK_INVALID" }
        return Pairing(serial, name, ProvisioningCrypto.hexDecode(pskText))
    }

    fun save(context: Context, pairing: Pairing) {
        require(serialPattern.matches(pairing.serial) && pairing.psk.size == 32) {
            "BLE_PAIRING_INVALID"
        }
        val value = JsonObject().apply {
            addProperty("name", pairing.name)
            addProperty("psk", ProvisioningCrypto.hexEncode(pairing.psk))
        }
        check(prefs(context).edit().putString(pairing.serial, value.toString()).commit()) {
            "BLE_PAIRING_SAVE_FAILED"
        }
    }

    fun contains(context: Context, serial: String): Boolean =
        prefs(context).contains(serial)

    fun findByAdvertisementName(context: Context, name: String): Pairing? {
        val matches = prefs(context).all.keys.mapNotNull { serial ->
            read(context, serial)?.takeIf { it.name == name }
        }
        require(matches.size <= 1) { "BLE_PAIRING_NAME_AMBIGUOUS" }
        return matches.singleOrNull()
    }

    private fun read(context: Context, serial: String): Pairing? {
        val encoded = prefs(context).getString(serial, null) ?: return null
        val json = JsonParser.parseString(encoded).asJsonObject
        val name = json.get("name")?.asString ?: error("BLE_PAIRING_STORE_CORRUPTED")
        val psk = json.get("psk")?.asString?.let(ProvisioningCrypto::hexDecode)
            ?: error("BLE_PAIRING_STORE_CORRUPTED")
        check(psk.size == 32) { "BLE_PAIRING_STORE_CORRUPTED" }
        return Pairing(serial, name, psk)
    }
}
