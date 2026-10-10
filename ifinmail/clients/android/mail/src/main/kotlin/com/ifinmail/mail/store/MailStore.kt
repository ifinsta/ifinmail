package com.ifinmail.mail.store

import com.ifinmail.core.domain.model.OutgoingDraft
import com.ifinmail.mail.model.Account
import com.ifinmail.mail.model.StoredMessage
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okio.FileSystem
import okio.Path
import okio.buffer
import okio.use

@Serializable
data class MailStoreData(
    val accounts: List<Account> = emptyList(),
    val messages: Map<String, List<StoredMessage>> = emptyMap(),
    val outbox: Map<String, List<String>> = emptyMap(),
    val drafts: List<OutgoingDraft> = emptyList()
)

class MailStore(
    baseDir: Path,
    private val fileSystem: FileSystem = FileSystem.SYSTEM
) {

    private val file: Path = baseDir / FILE_NAME
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = false }
    private val mutex = Mutex()

    suspend fun read(): MailStoreData = mutex.withLock { readUnsafe() }

    suspend fun write(transform: (MailStoreData) -> MailStoreData): MailStoreData = mutex.withLock {
        val updated = transform(readUnsafe())
        writeUnsafe(updated)
        updated
    }

    private fun readUnsafe(): MailStoreData {
        if (!fileSystem.exists(file)) return MailStoreData()
        return try {
            val text = fileSystem.source(file).buffer().use { it.readUtf8() }
            json.decodeFromString(MailStoreData.serializer(), text)
        } catch (e: Exception) {
            MailStoreData()
        }
    }

    private fun writeUnsafe(data: MailStoreData) {
        fileSystem.createDirectories(file.parent!!)
        val text = json.encodeToString(MailStoreData.serializer(), data)
        fileSystem.sink(file).buffer().use { it.writeUtf8(text) }
    }

    companion object {
        const val FILE_NAME = "ifinmail-store.json"
        const val MAX_MESSAGES_PER_ACCOUNT = 500
        const val BACKFILL_WINDOW = 100L
    }
}
