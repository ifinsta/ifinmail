package com.ifinmail.mail.store

import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.port.CredentialStore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okio.FileSystem
import okio.Path
import okio.buffer
import okio.use

@Serializable
private data class CredentialFile(
    val entries: Map<String, Credentials> = emptyMap()
)

class FileCredentialStore(
    baseDir: Path,
    private val fileSystem: FileSystem = FileSystem.SYSTEM
) : CredentialStore {

    private val file: Path = baseDir / FILE_NAME
    private val json = Json { ignoreUnknownKeys = true }
    private val mutex = Mutex()

    override suspend fun read(accountId: String): Credentials? = mutex.withLock {
        load().entries[accountId]
    }

    override suspend fun write(accountId: String, credentials: Credentials) = mutex.withLock {
        val current = load()
        save(CredentialFile(current.entries + (accountId to credentials)))
    }

    override suspend fun erase(accountId: String) = mutex.withLock {
        val current = load()
        save(CredentialFile(current.entries - accountId))
    }

    private fun load(): CredentialFile {
        if (!fileSystem.exists(file)) return CredentialFile()
        return try {
            val text = fileSystem.source(file).buffer().use { it.readUtf8() }
            json.decodeFromString(CredentialFile.serializer(), text)
        } catch (e: Exception) {
            CredentialFile()
        }
    }

    private fun save(data: CredentialFile) {
        fileSystem.createDirectories(file.parent!!)
        fileSystem.sink(file).buffer().use { it.writeUtf8(json.encodeToString(CredentialFile.serializer(), data)) }
    }

    companion object {
        const val FILE_NAME = "ifinmail-credentials.json"
    }
}
