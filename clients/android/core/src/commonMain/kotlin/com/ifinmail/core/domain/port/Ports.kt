package com.ifinmail.core.domain.port

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.model.Account
import com.ifinmail.core.domain.model.ConnectionProfile
import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.model.IncomingConfig
import com.ifinmail.core.domain.model.IncomingProtocol
import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.core.domain.model.OutgoingDraft
import com.ifinmail.core.domain.model.ServerConfig
import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.model.SyncState
import com.ifinmail.core.domain.model.VerifyStep

data class ProbeOutcome(
    val success: Boolean,
    val steps: List<VerifyStep>,
    val capabilities: Set<KnownCapability>,
    val error: MailError? = null,
    val errorDetail: String? = null
)

data class SyncRequest(
    val account: Account,
    val credentials: Credentials,
    val cursor: SyncState,
    val backfillFromUid: Long,
    val knownUidls: Set<String> = emptySet()
)

data class ChangeSet(
    val newMessages: List<StoredMessage>,
    val nextCursor: SyncState
)

data class BodyPayload(
    val text: String?,
    val html: String?
)

interface MailAccessAdapter {
    val protocol: IncomingProtocol

    suspend fun probe(
        email: String,
        incoming: IncomingConfig,
        credentials: Credentials
    ): ProbeOutcome

    suspend fun sync(request: SyncRequest): ChangeSet

    suspend fun loadBody(account: Account, credentials: Credentials, message: StoredMessage): BodyPayload

    suspend fun setSeen(account: Account, credentials: Credentials, message: StoredMessage, read: Boolean)

    suspend fun setFlagged(account: Account, credentials: Credentials, message: StoredMessage, flagged: Boolean) {}

    suspend fun deleteRemote(account: Account, credentials: Credentials, message: StoredMessage)

    suspend fun appendToMailbox(account: Account, credentials: Credentials, role: MailboxRole, mimeBytes: ByteArray): Boolean
}

interface SubmissionAdapter {
    suspend fun probe(email: String, outgoing: ServerConfig, credentials: Credentials): ProbeOutcome

    suspend fun submit(
        email: String,
        outgoing: ServerConfig,
        credentials: Credentials,
        draft: OutgoingDraft,
        mimeBytes: ByteArray
    )
}

interface CredentialStore {
    suspend fun read(accountId: String): Credentials?
    suspend fun write(accountId: String, credentials: Credentials)
    suspend fun erase(accountId: String)
}

interface AutoConfigSource {
    fun profilesFor(email: String): List<ConnectionProfile>
}

class AdapterRegistry(private val adapters: Map<IncomingProtocol, MailAccessAdapter>) {
    fun forAccount(incoming: IncomingConfig): MailAccessAdapter =
        adapters[incoming.protocol]
            ?: error("No adapter registered for protocol ${incoming.protocol}")
}

data class DraftSuggestion(
    val label: String,
    val bodyPrefix: String
)

interface DraftCapability {
    suspend fun suggestions(account: Account, message: StoredMessage): List<DraftSuggestion>
}

interface VaultService {
    suspend fun store(accountId: String, name: String, mediaType: String, bytes: ByteArray, ttlMillis: Long): String
    suspend fun resolve(reference: String): ByteArray?
    suspend fun purgeExpired()
}

interface OcrService {
    suspend fun extractText(bytes: ByteArray, mediaType: String): String
}

interface ExportService {
    suspend fun exportMbox(accountId: String, messages: List<StoredMessage>): String
    suspend fun exportVCard(displayName: String, email: String): String
}

interface CalendarCapability {
    suspend fun probe(): CalendarProbeResult
}

data class CalendarProbeResult(
    val reachable: Boolean,
    val detail: String
)

interface ContactCapability {
    suspend fun probe(): ContactProbeResult
}

data class ContactProbeResult(
    val reachable: Boolean,
    val detail: String
)
