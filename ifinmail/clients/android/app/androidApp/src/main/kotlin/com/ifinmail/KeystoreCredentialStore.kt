package com.ifinmail

import android.content.Context
import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.port.CredentialStore
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import com.ifinmail.core.domain.model.AuthMethod
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject

class KeystoreCredentialStore private constructor(
    private val fileContents: () -> String?,
    private val writeFile: (String) -> Unit,
    private val keyProvider: () -> SecretKey
) : CredentialStore {

    private val mutex = Mutex()

    override suspend fun read(accountId: String): Credentials? = mutex.withLock {
        val map = loadMap()
        val blob = map[accountId]
        if (blob.isNullOrEmpty()) return@withLock null
        runCatching { decrypt(blob) }.getOrNull()
    }

    override suspend fun write(accountId: String, credentials: Credentials) = mutex.withLock {
        val map = loadMap()
        map.put(accountId, encrypt(credentials))
        writeFile(JSONObject(map).toString())
    }

    override suspend fun erase(accountId: String) = mutex.withLock {
        val map = loadMap()
        map.remove(accountId)
        writeFile(JSONObject(map).toString())
    }

    private fun loadMap(): MutableMap<String, String> {
        val raw = fileContents() ?: return mutableMapOf()
        val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return mutableMapOf()
        val result = mutableMapOf<String, String>()
        for (key in obj.keys()) result[key] = obj.getString(key)
        return result
    }

    private fun encrypt(credentials: Credentials): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, keyProvider())
        val iv = cipher.iv
        val payload = JSONObject()
            .put("auth", credentials.authMethod.name)
            .put("password", credentials.password ?: "")
            .put("oauth", credentials.oauthAccessToken ?: "")
            .toString().toByteArray(Charsets.UTF_8)
        val cipherText = cipher.doFinal(payload)
        val out = ByteArray(iv.size + cipherText.size)
        iv.copyInto(out)
        cipherText.copyInto(out, iv.size)
        return android.util.Base64.encodeToString(out, android.util.Base64.NO_WRAP)
    }

    private fun decrypt(blob: String): Credentials {
        val data = android.util.Base64.decode(blob, android.util.Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, keyProvider(), GCMParameterSpec(128, data, 0, IV_LENGTH))
        val plain = cipher.doFinal(data, IV_LENGTH, data.size - IV_LENGTH)
        val obj = JSONObject(String(plain, Charsets.UTF_8))
        return Credentials(
            authMethod = runCatching { AuthMethod.valueOf(obj.optString("auth", "PASSWORD")) }.getOrDefault(AuthMethod.PASSWORD),
            password = obj.optString("password").takeIf { it.isNotEmpty() },
            oauthAccessToken = obj.optString("oauth").takeIf { it.isNotEmpty() }
        )
    }

    companion object {
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_LENGTH = 12
        private const val KEY_ALIAS = "ifinmail-credentials-key"
        private const val FILE_NAME = "ifinmail-secrets.bin"

        fun fromContext(context: Context): KeystoreCredentialStore {
            val file = java.io.File(context.filesDir, FILE_NAME)
            return KeystoreCredentialStore(
                fileContents = { if (file.exists()) file.readText() else null },
                writeFile = { text -> file.writeText(text) },
                keyProvider = { masterKey() }
            )
        }

        private fun masterKey(): SecretKey {
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
            if (existing != null) return existing
            val generator = KeyGenerator.getInstance("AES", "AndroidKeyStore")
            generator.init(
                android.security.keystore.KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or
                        android.security.keystore.KeyProperties.PURPOSE_DECRYPT
                )
                    .setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
            return generator.generateKey()
        }
    }
}
