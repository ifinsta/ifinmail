package com.ifinmail.core.domain.vault

import com.ifinmail.core.domain.port.VaultService
import kotlin.random.Random
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class VaultEntry(
    val reference: String,
    val name: String,
    val mediaType: String,
    val bytes: ByteArray,
    val expiresAtMs: Long
) {
    override fun equals(other: Any?): Boolean =
        other is VaultEntry && reference == other.reference && name == other.name &&
            mediaType == other.mediaType && expiresAtMs == other.expiresAtMs &&
            bytes.contentEquals(other.bytes)

    override fun hashCode(): Int = reference.hashCode()
}

class InMemoryVaultService(
    private val clock: () -> Long = { System.currentTimeMillis() }
) : VaultService {

    private val mutex = Mutex()
    private val entries = mutableMapOf<String, VaultEntry>()

    override suspend fun store(accountId: String, name: String, mediaType: String, bytes: ByteArray, ttlMillis: Long): String =
        mutex.withLock {
            val nonce = Random.nextBytes(8).joinToString("") { "%02x".format(it.toInt() and 0xFF) }
            val reference = "vault:$accountId:$nonce"
            entries[reference] = VaultEntry(reference, name, mediaType, bytes, clock() + ttlMillis)
            reference
        }

    override suspend fun resolve(reference: String): ByteArray? = mutex.withLock {
        val entry = entries[reference] ?: return null
        if (entry.expiresAtMs < clock()) {
            entries.remove(reference)
            return null
        }
        entry.bytes
    }

    override suspend fun purgeExpired() = mutex.withLock {
        val now = clock()
        entries.entries.removeAll { it.value.expiresAtMs < now }
        Unit
    }

    internal fun size(): Int = mutex.let { entries.size }
}
