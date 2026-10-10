package com.ifinmail.mail.store

import com.ifinmail.core.domain.model.PendingMutation
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okio.FileSystem
import okio.Path
import okio.buffer
import okio.use

class MutationQueue(
    baseDir: Path,
    private val fileSystem: FileSystem = FileSystem.SYSTEM
) {

    @Serializable
    private data class QueueFile(
        val entries: List<PendingMutation> = emptyList()
    )

    private val file: Path = baseDir / FILE_NAME
    private val json = Json { ignoreUnknownKeys = true }
    private val mutex = Mutex()
    private val pendingFlow = MutableStateFlow<List<PendingMutation>>(emptyList())

    val pending: StateFlow<List<PendingMutation>> = pendingFlow.asStateFlow()

    suspend fun load() {
        mutex.withLock { pendingFlow.value = readUnsafe() }
    }

    suspend fun enqueue(mutation: PendingMutation) {
        mutex.withLock {
            val updated = readUnsafe() + mutation
            writeUnsafe(QueueFile(updated))
            pendingFlow.value = updated
        }
    }

    suspend fun remove(mutationId: String) {
        mutex.withLock {
            val updated = readUnsafe().filterNot { it.id == mutationId }
            writeUnsafe(QueueFile(updated))
            pendingFlow.value = updated
        }
    }

    suspend fun all(): List<PendingMutation> = mutex.withLock { readUnsafe() }

    private fun readUnsafe(): List<PendingMutation> {
        if (!fileSystem.exists(file)) return emptyList()
        return try {
            val text = fileSystem.source(file).buffer().use { it.readUtf8() }
            json.decodeFromString(QueueFile.serializer(), text).entries
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun writeUnsafe(data: QueueFile) {
        fileSystem.createDirectories(file.parent!!)
        fileSystem.sink(file).buffer().use { it.writeUtf8(json.encodeToString(QueueFile.serializer(), data)) }
    }

    companion object {
        const val FILE_NAME = "ifinmail-outbox.json"
    }
}
