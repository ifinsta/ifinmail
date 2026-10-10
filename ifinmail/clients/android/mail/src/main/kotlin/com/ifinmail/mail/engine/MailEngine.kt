package com.ifinmail.mail.engine

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.event.DomainEvent
import com.ifinmail.core.domain.event.DomainEventBus
import com.ifinmail.core.domain.model.ConnectionProfile
import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.model.EmailAddress
import com.ifinmail.core.domain.model.IncomingConfig
import com.ifinmail.core.domain.model.IncomingProtocol
import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.core.domain.model.OutgoingDraft
import com.ifinmail.core.domain.model.PendingMutation
import com.ifinmail.core.domain.model.ServerConfig
import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.model.VerifyReport
import com.ifinmail.core.domain.model.VerifyStep
import com.ifinmail.core.domain.port.AdapterRegistry
import com.ifinmail.core.domain.port.AutoConfigSource
import com.ifinmail.core.domain.port.CredentialStore
import com.ifinmail.core.domain.port.ProbeOutcome
import com.ifinmail.core.domain.port.SubmissionAdapter
import com.ifinmail.core.domain.port.SyncRequest
import com.ifinmail.mail.adapter.ImapAccessAdapter
import com.ifinmail.mail.adapter.Pop3AccessAdapter
import com.ifinmail.mail.adapter.SmtpSubmissionAdapter
import com.ifinmail.mail.autoconfig.ProviderDirectory
import com.ifinmail.mail.mime.MimeComposer
import com.ifinmail.mail.model.Account
import com.ifinmail.mail.model.MailException
import com.ifinmail.mail.model.toMailError
import com.ifinmail.core.domain.model.MutationKind
import com.ifinmail.mail.store.FileCredentialStore
import com.ifinmail.mail.store.MailStore
import com.ifinmail.mail.store.MutationQueue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okio.FileSystem
import okio.Path

class MailEngine(
    storeDir: Path,
    private val fileSystem: FileSystem = FileSystem.SYSTEM,
    private val credentialStore: CredentialStore = FileCredentialStore(storeDir, fileSystem),
    private val submissionAdapter: SubmissionAdapter = SmtpSubmissionAdapter(),
    private val registry: AdapterRegistry = AdapterRegistry(
        mapOf(
            IncomingProtocol.IMAP to ImapAccessAdapter(),
            IncomingProtocol.POP3 to Pop3AccessAdapter()
        )
    ),
    private val autoConfigSource: AutoConfigSource =
        com.ifinmail.mail.discovery.CompositeAutoConfigSource(
            com.ifinmail.mail.discovery.DiscoveryAutoConfigSource(),
            ProviderDirectory
        ),
    private val events: DomainEventBus = DomainEventBus(),
    private val mutationQueue: MutationQueue = MutationQueue(storeDir)
) {

    private val store = MailStore(storeDir, fileSystem)

    private val accountsFlow = MutableStateFlow<List<Account>>(emptyList())
    val accounts: StateFlow<List<Account>> = accountsFlow.asStateFlow()

    private val messagesFlow = MutableStateFlow<Map<String, List<StoredMessage>>>(emptyMap())
    val messagesByAccount: StateFlow<Map<String, List<StoredMessage>>> = messagesFlow.asStateFlow()

    val pendingMutations: StateFlow<List<PendingMutation>> = mutationQueue.pending

    private val lastQueuedIdFlow = MutableStateFlow<String?>(null)
    val lastQueuedMutationId: StateFlow<String?> = lastQueuedIdFlow.asStateFlow()

    private val draftsFlow = MutableStateFlow<List<OutgoingDraft>>(emptyList())
    val drafts: StateFlow<List<OutgoingDraft>> = draftsFlow.asStateFlow()

    suspend fun initialize() {
        val data = store.read()
        val migrated = data.accounts.map { account ->
            account.credentials?.let { credentialStore.write(account.id, it) }
            account.copy(credentials = account.credentials ?: credentialStore.read(account.id))
        }
        if (migrated != data.accounts) {
            store.write { current -> current.copy(accounts = migrated) }
        }
        accountsFlow.value = migrated
        messagesFlow.value = data.messages
        draftsFlow.value = data.drafts
        enrichBackfill()
        runCatching { mutationQueue.load() }
        flushMutations()
    }

    private suspend fun enrichBackfill() {
        val classifier = com.ifinmail.core.domain.triage.LocalClassifier()
        var changed = false
        val enriched = messagesFlow.value.mapValues { (accountId, list) ->
            list.map { message ->
                if (message.triageCategory != null && message.threadId.isNotBlank()) return@map message
                var updated = message
                if (message.triageCategory == null) {
                    val triage = classifier.classify(message)
                    updated = updated.copy(triageCategory = triage.category.name, triagePriority = triage.category.priority)
                }
                if (updated.threadId.isBlank()) {
                    updated = updated.copy(threadId = com.ifinmail.core.domain.thread.ThreadResolver.computeThreadId(updated.subject, updated.accountId, updated.messageIdHeader))
                }
                changed = true
                updated
            }
        }
        if (changed) {
            val data = store.write { s -> s.copy(messages = enriched) }
            messagesFlow.value = data.messages
        }
    }

    suspend fun saveDraft(draft: OutgoingDraft): OutgoingDraft {
        val persisted = if (draft.inReplyToMessageId.isNullOrBlank()) {
            draft.copy(inReplyToMessageId = java.util.UUID.randomUUID().toString())
        } else draft
        val data = store.write { current ->
            val others = current.drafts.filterNot { it.inReplyToMessageId == persisted.inReplyToMessageId }
            current.copy(drafts = others + persisted)
        }
        draftsFlow.value = data.drafts
        return persisted
    }

    suspend fun deleteDraft(draftId: String) {
        val data = store.write { current ->
            current.copy(drafts = current.drafts.filterNot { it.inReplyToMessageId == draftId })
        }
        draftsFlow.value = data.drafts
    }

    fun autoConfigure(email: String): List<ConnectionProfile> =
        autoConfigSource.profilesFor(email)

    suspend fun markFlagged(accountId: String, messageId: String, flagged: Boolean): StoredMessage {
        val (account, credentials, current) = resolveForMessage(accountId, messageId)
        val updated = current.copy(flagged = flagged)
        persistMessageUpdate(accountId, updated)
        events.publish(DomainEvent.MessageRead(accountId, messageId, current.read))
        runCatching {
            registry.forAccount(account.incoming).setFlagged(account, credentials, current, flagged)
        }.onFailure { t ->
            if (isTransient(t)) {
                mutationQueue.enqueue(
                    PendingMutation(
                        id = java.util.UUID.randomUUID().toString(),
                        accountId = accountId,
                        kind = MutationKind.MARK_READ,
                        messageId = messageId,
                        read = current.read,
                        createdAtEpochMs = System.currentTimeMillis()
                    )
                )
            }
        }
        return updated
    }

    private fun isTransient(t: Throwable): Boolean {
        val error = t.toMailError()
        return error == MailError.NetworkUnavailable || error == MailError.Timeout ||
            error == MailError.Unavailable || error == MailError.RateLimited
    }

    suspend fun flushMutations(): Int {
        val now = System.currentTimeMillis()
        var flushed = 0
        for (mutation in mutationQueue.all()) {
            if (mutation.scheduledAtMs > 0 && mutation.scheduledAtMs > now) continue
            val account = accountsFlow.value.firstOrNull { it.id == mutation.accountId } ?: continue
            val credentials = runCatching { resolveCredentials(account) }.getOrNull() ?: continue
            val adapter = runCatching { registry.forAccount(account.incoming) }.getOrNull() ?: continue
            val result = runCatching {
                when (mutation.kind) {
                    MutationKind.SEND -> {
                        val draft = mutation.draft ?: return@runCatching
                        val mime = MimeComposer.compose(EmailAddress(name = account.displayName, address = account.email), draft)
                        submissionAdapter.submit(account.email, account.outgoing, credentials, draft, mime)
                        events.publish(DomainEvent.MessageSubmitted(account.id, draft.subject))
                    }
                    MutationKind.MARK_READ -> {
                        val stored = messagesFlow.value[account.id].orEmpty().firstOrNull { it.id == mutation.messageId }
                        val readFlag = mutation.read
                        if (stored != null && readFlag != null) {
                            adapter.setSeen(account, credentials, stored, readFlag)
                        }
                    }
                    MutationKind.DELETE -> {
                        val stored = messagesFlow.value[account.id].orEmpty().firstOrNull { it.id == mutation.messageId }
                        if (stored != null) adapter.deleteRemote(account, credentials, stored)
                    }
                }
            }
            if (result.isSuccess) {
                mutationQueue.remove(mutation.id)
                flushed += 1
            }
        }
        if (flushed > 0) {
            accountsFlow.value.forEach {
                events.publish(DomainEvent.MutationsFlushed(it.id, flushed))
            }
        }
        return flushed
    }

    suspend fun verify(
        email: String,
        incoming: IncomingConfig,
        outgoing: ServerConfig,
        credentials: Credentials
    ): VerifyReport {
        val outcome = verifyWithCapabilities(email, incoming, outgoing, credentials)
        return if (outcome.success) {
            VerifyReport(true, outcome.steps, null)
        } else {
            VerifyReport.failure(outcome.steps, outcome.errorDetail ?: "Verification failed")
        }
    }

    private data class Verification(
        val success: Boolean,
        val steps: List<VerifyStep>,
        val errorDetail: String?,
        val capabilities: Set<KnownCapability>
    )

    private suspend fun verifyWithCapabilities(
        email: String,
        incoming: IncomingConfig,
        outgoing: ServerConfig,
        credentials: Credentials
    ): Verification {
        val incomingOutcome = runCatching {
            registry.forAccount(incoming).probe(email, incoming, credentials)
        }.getOrElse { t -> ProbeOutcome(false, emptyList(), emptySet(), t.toMailError(), t.message) }
        val outgoingOutcome = runCatching {
            submissionAdapter.probe(email, outgoing, credentials)
        }.getOrElse { t -> ProbeOutcome(false, emptyList(), emptySet(), t.toMailError(), t.message) }

        val steps = incomingOutcome.steps + outgoingOutcome.steps
        val success = incomingOutcome.success && outgoingOutcome.success
        val detail = listOfNotNull(incomingOutcome.errorDetail, outgoingOutcome.errorDetail).firstOrNull()
        return Verification(success, steps, detail, incomingOutcome.capabilities + outgoingOutcome.capabilities)
    }

    suspend fun addAccount(
        email: String,
        displayName: String,
        incoming: IncomingConfig,
        outgoing: ServerConfig,
        credentials: Credentials,
        verified: Boolean
    ): Account {
        var capabilities = emptySet<KnownCapability>()
        if (!verified) {
            val verification = verifyWithCapabilities(email, incoming, outgoing, credentials)
            if (!verification.success) {
                throw MailException(
                    verification.errorDetail ?: "Verification failed",
                    error = MailError.Unknown(verification.errorDetail ?: "Verification failed")
                )
            }
            capabilities = verification.capabilities
        }
        var created: Account? = null
        val data = store.write { current ->
            if (current.accounts.any { it.email.equals(email, true) }) {
                throw MailException("Account $email is already set up", error = MailError.Conflict)
            }
            val account = Account(
                id = java.util.UUID.randomUUID().toString(),
                email = email,
                displayName = displayName.ifBlank { email.substringBefore('@') },
                incoming = incoming,
                outgoing = outgoing,
                credentials = credentials,
                capabilities = capabilities.map { it.name }.toSet()
            )
            created = account
            current.copy(accounts = current.accounts + account)
        }
        credentialStore.write(created!!.id, credentials)
        accountsFlow.value = data.accounts
        events.publish(DomainEvent.AccountAdded(created!!.id, email))
        return created!!
    }

    suspend fun removeAccount(accountId: String) {
        val data = store.write { current ->
            current.copy(
                accounts = current.accounts.filterNot { it.id == accountId },
                messages = current.messages - accountId
            )
        }
        credentialStore.erase(accountId)
        accountsFlow.value = data.accounts
        messagesFlow.value = data.messages
    }

    suspend fun refresh(accountId: String): Int {
        val account = accountsFlow.value.firstOrNull { it.id == accountId }
            ?: throw MailException("Unknown account", error = MailError.Unknown("Unknown account"))
        val adapter = registry.forAccount(account.incoming)
        val credentials = resolveCredentials(account)
        val existing = messagesFlow.value[accountId].orEmpty()
        val backfillFrom = if (account.sync.imapLastSeenUid > 0L) {
            account.sync.imapLastSeenUid
        } else {
            maxOf(1L, (existing.maxOfOrNull { it.uid } ?: 0L) - BACKFILL_WINDOW)
        }
        return try {
            val changeSet = adapter.sync(
                SyncRequest(
                    account = account,
                    credentials = credentials,
                    cursor = account.sync,
                    backfillFromUid = backfillFrom,
                    knownUidls = account.sync.popUidMap.values.toSet() +
                        existing.map { it.id.substringAfterLast('|') }
                )
            )
            if (changeSet.newMessages.isNotEmpty()) {
                val merged = (existing + changeSet.newMessages).distinctBy { it.uid }
                    .sortedByDescending { it.dateEpochMs ?: Long.MIN_VALUE }
                    .take(MailStore.MAX_MESSAGES_PER_ACCOUNT)
                val written = store.write { s -> s.copy(messages = s.messages + (accountId to merged)) }
                messagesFlow.value = written.messages
            }
            updateAccount(account.copy(sync = changeSet.nextCursor))
            events.publish(DomainEvent.SyncCompleted(accountId, changeSet.newMessages.size))
            if (changeSet.newMessages.isNotEmpty()) {
                events.publish(DomainEvent.MessageReceived(accountId, changeSet.newMessages.size))
            }
            changeSet.newMessages.size
        } catch (t: Throwable) {
            events.publish(DomainEvent.SyncFailed(accountId, t.toMailError()))
            throw t
        } finally {
            runCatching { flushMutations() }
        }
    }

    suspend fun loadBody(accountId: String, messageId: String): StoredMessage {
        val (account, credentials, current) = resolveForMessage(accountId, messageId)
        if (current.bodyText != null || current.bodyHtml != null) {
            if (!current.read) markRead(accountId, messageId, true)
            return current.copy(read = true)
        }
        val payload = registry.forAccount(account.incoming).loadBody(account, credentials, current)
        val loaded = current.copy(bodyText = payload.text, bodyHtml = payload.html, read = true)
        persistMessageUpdate(accountId, loaded)
        return loaded
    }

    suspend fun markRead(accountId: String, messageId: String, read: Boolean): StoredMessage {
        val (account, credentials, current) = resolveForMessage(accountId, messageId)
        val updated = current.copy(read = read)
        persistMessageUpdate(accountId, updated)
        events.publish(DomainEvent.MessageRead(accountId, messageId, read))
        runCatching {
            registry.forAccount(account.incoming).setSeen(account, credentials, current, read)
        }.onFailure { t ->
            if (isTransient(t)) {
                mutationQueue.enqueue(
                    PendingMutation(
                        id = java.util.UUID.randomUUID().toString(),
                        accountId = accountId,
                        kind = MutationKind.MARK_READ,
                        messageId = messageId,
                        read = read,
                        createdAtEpochMs = System.currentTimeMillis()
                    )
                )
            }
        }
        return updated
    }

    suspend fun deleteMessage(accountId: String, messageId: String) {
        val (account, credentials, current) = resolveForMessage(accountId, messageId)
        val data = store.write { s ->
            s.copy(messages = s.messages + (accountId to s.messages[accountId].orEmpty().filterNot { it.id == messageId }))
        }
        messagesFlow.value = data.messages
        events.publish(DomainEvent.MessageDeleted(accountId, messageId))
        runCatching {
            registry.forAccount(account.incoming).deleteRemote(account, credentials, current)
        }.onFailure { t ->
            if (isTransient(t)) {
                mutationQueue.enqueue(
                    PendingMutation(
                        id = java.util.UUID.randomUUID().toString(),
                        accountId = accountId,
                        kind = MutationKind.DELETE,
                        messageId = messageId,
                        createdAtEpochMs = System.currentTimeMillis()
                    )
                )
            }
        }
    }

    suspend fun send(accountId: String, draft: OutgoingDraft) {
        val account = accountsFlow.value.firstOrNull { it.id == accountId }
            ?: throw MailException("Unknown account", error = MailError.Unknown("Unknown account"))
        val credentials = resolveCredentials(account)
        val mimeBytes = MimeComposer.compose(EmailAddress(name = account.displayName, address = account.email), draft)
        try {
            submissionAdapter.submit(account.email, account.outgoing, credentials, draft, mimeBytes)
        } catch (t: Throwable) {
            if (isTransient(t)) {
                val mutation = PendingMutation(
                    id = java.util.UUID.randomUUID().toString(),
                    accountId = accountId,
                    kind = MutationKind.SEND,
                    draft = draft,
                    createdAtEpochMs = System.currentTimeMillis()
                )
                mutationQueue.enqueue(mutation)
                lastQueuedIdFlow.value = mutation.id
                events.publish(DomainEvent.SubmissionQueued(accountId, mutation.id))
                return
            }
            events.publish(DomainEvent.SubmissionFailed(accountId, t.toMailError()))
            throw t
        }
        events.publish(DomainEvent.MessageSubmitted(accountId, draft.subject))
        val granted = account.capabilities.mapNotNull { runCatching { KnownCapability.valueOf(it) }.getOrNull() }
        val shouldAppendSent = KnownCapability.MAIL_SENT_APPEND in granted || granted.isEmpty()
        if (shouldAppendSent) {
            runCatching {
                registry.forAccount(account.incoming).appendToMailbox(account, credentials, MailboxRole.SENT, mimeBytes)
            }
        }
    }

    suspend fun sendScheduled(accountId: String, draft: OutgoingDraft, atEpochMs: Long): String {
        if (accountsFlow.value.none { it.id == accountId }) {
            throw MailException("Unknown account", error = MailError.Unknown("Unknown account"))
        }
        val mutation = PendingMutation(
            id = java.util.UUID.randomUUID().toString(),
            accountId = accountId,
            kind = MutationKind.SEND,
            draft = draft,
            createdAtEpochMs = System.currentTimeMillis(),
            scheduledAtMs = atEpochMs
        )
        mutationQueue.enqueue(mutation)
        lastQueuedIdFlow.value = mutation.id
        events.publish(DomainEvent.SubmissionQueued(accountId, mutation.id))
        return mutation.id
    }

    suspend fun cancelPending(mutationId: String) {
        mutationQueue.remove(mutationId)
        lastQueuedIdFlow.value = null
    }

    suspend fun snooze(accountId: String, messageId: String, untilEpochMs: Long): StoredMessage {
        val (account, _, current) = resolveForMessage(accountId, messageId)
        val updated = current.copy(snoozedUntilMs = untilEpochMs)
        persistMessageUpdate(accountId, updated)
        return updated
    }

    suspend fun smartReplies(accountId: String, messageId: String): List<com.ifinmail.core.domain.port.DraftSuggestion> {
        val account = accountsFlow.value.firstOrNull { it.id == accountId }
            ?: throw MailException("Unknown account", error = MailError.Unknown("Unknown account"))
        val current = messagesFlow.value[accountId].orEmpty().firstOrNull { it.id == messageId }
            ?: throw MailException("Unknown message", error = MailError.Unknown("Unknown message"))
        return com.ifinmail.core.domain.draft.SmartReplyEngine().suggestions(account, current)
    }

    suspend fun exportMbox(accountId: String): String {
        val messages = messagesFlow.value[accountId].orEmpty()
        return com.ifinmail.core.domain.export.MboxExportService.exportMbox(accountId, messages)
    }

    private suspend fun resolveCredentials(account: Account): Credentials =
        credentialStore.read(account.id)
            ?: account.credentials
            ?: throw MailException(
                "No stored credentials for ${account.email}",
                error = MailError.AuthenticationRequired
            )

    private suspend fun resolveForMessage(
        accountId: String,
        messageId: String
    ): Triple<Account, Credentials, StoredMessage> {
        val account = accountsFlow.value.firstOrNull { it.id == accountId }
            ?: throw MailException("Unknown account", error = MailError.Unknown("Unknown account"))
        val current = messagesFlow.value[accountId].orEmpty().firstOrNull { it.id == messageId }
            ?: throw MailException("Unknown message", error = MailError.Unknown("Unknown message"))
        return Triple(account, resolveCredentials(account), current)
    }

    private suspend fun updateAccount(updated: Account) {
        val written = store.write { current ->
            current.copy(accounts = current.accounts.map { if (it.id == updated.id) updated else it })
        }
        accountsFlow.value = written.accounts
    }

    private suspend fun persistMessageUpdate(accountId: String, updated: StoredMessage) {
        val data = store.write { s ->
            val list = s.messages[accountId].orEmpty().map { if (it.id == updated.id) updated else it }
            s.copy(messages = s.messages + (accountId to list))
        }
        messagesFlow.value = data.messages
    }

    companion object {
        const val BACKFILL_WINDOW = 100L
    }
}
