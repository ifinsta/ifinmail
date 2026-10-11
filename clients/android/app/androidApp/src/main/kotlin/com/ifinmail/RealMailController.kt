package com.ifinmail

import android.content.Context
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiAccount
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.mail.MailController as ControllerContract
import com.ifinmail.mail.engine.MailEngine
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.EmailAddress
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.OutgoingDraft
import com.ifinmail.mail.model.ServerConfig
import com.ifinmail.mail.model.StoredMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.FlowCollector
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okio.Path.Companion.toPath

class RealMailController(
    storeDirPath: String,
    context: Context? = null,
    private val engine: MailEngine = MailEngine(
        storeDirPath.toPath(),
        credentialStore = context?.let { KeystoreCredentialStore.fromContext(it) } ?: FileCredentialStoreCompat(storeDirPath)
    )
) : MailController {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val busy = MutableStateFlow(false)

    override val accounts: StateFlow<List<UiAccount>> =
        mapState(engine.accounts) { list -> list.map { UiAccount(it.id, it.email, it.displayName, it.capabilities) } }

    override val messages: StateFlow<List<UiMessage>> =
        mapState(engine.messagesByAccount) { byAccount -> activeAccountId.value?.let(byAccount::get).orEmpty().map(::toUi) }

    override val activeAccountId = MutableStateFlow<String?>(null)

    override val isBusy: StateFlow<Boolean> = busy

    override val queuedCount: StateFlow<Int> =
        mapState(engine.pendingMutations) { list -> list.count { it.accountId == activeAccountId.value } }

    override val lastQueuedMutationId: StateFlow<String?> = engine.lastQueuedMutationId

    override val drafts: StateFlow<List<UiDraft>> =
        mapState(engine.drafts) { list ->
            list.map { d -> UiDraft(d.to.map { it.address }, d.cc.map { it.address }, d.subject, d.bodyText, d.inReplyToMessageId ?: "") }
        }

    init {
        scope.launch {
            engine.initialize()
            val stored = engine.accounts.value
            if (activeAccountId.value == null && stored.isNotEmpty()) {
                activeAccountId.value = stored.first().id
                runCatching { engine.refresh(stored.first().id) }
            }
        }
    }

    override suspend fun autoConfigure(email: String): List<com.ifinmail.app.shared.mail.UiProviderProfile> =
        engine.autoConfigure(email).map { profile ->
            com.ifinmail.app.shared.mail.UiProviderProfile(
                label = profile.label,
                protocol = when (profile.incoming.protocol) {
                    com.ifinmail.mail.model.IncomingProtocol.IMAP -> com.ifinmail.app.shared.mail.UiProtocol.IMAP
                    com.ifinmail.mail.model.IncomingProtocol.POP3 -> com.ifinmail.app.shared.mail.UiProtocol.POP3
                },
                incomingHost = profile.incoming.server.host,
                incomingPort = profile.incoming.server.port,
                incomingSecurity = toUiSecurity(profile.incoming.server.security),
                outgoingHost = profile.outgoing.host,
                outgoingPort = profile.outgoing.port,
                outgoingSecurity = toUiSecurity(profile.outgoing.security),
                note = profile.note
            )
        }

    override suspend fun addAccount(
        email: String,
        displayName: String,
        profile: com.ifinmail.app.shared.mail.UiProviderProfile,
        password: String?,
        oauthAccessToken: String?,
        trustedCertificateSha256: String?
    ): Result<Unit> = guarded {
        val credentials = if (oauthAccessToken != null) {
            Credentials(authMethod = com.ifinmail.mail.model.AuthMethod.XOAUTH2, oauthAccessToken = oauthAccessToken)
        } else {
            Credentials(password = password ?: "")
        }
        val account = try {
            engine.addAccount(
                email = email,
                displayName = displayName,
                incoming = IncomingConfig(
                    protocol = when (profile.protocol) {
                        com.ifinmail.app.shared.mail.UiProtocol.IMAP -> com.ifinmail.mail.model.IncomingProtocol.IMAP
                        com.ifinmail.app.shared.mail.UiProtocol.POP3 -> com.ifinmail.mail.model.IncomingProtocol.POP3
                    },
                    server = ServerConfig(
                        profile.incomingHost,
                        profile.incomingPort,
                        fromUiSecurity(profile.incomingSecurity),
                        trustedCertificateSha256
                    )
                ),
                outgoing = ServerConfig(
                    profile.outgoingHost,
                    profile.outgoingPort,
                    fromUiSecurity(profile.outgoingSecurity),
                    trustedCertificateSha256
                ),
                credentials = credentials,
                verified = false
            )
        } catch (e: com.ifinmail.mail.model.MailException) {
            // The UI module only knows :core, so hand it the structured certificate error in core's own type.
            val untrusted = e.error as? com.ifinmail.core.domain.error.MailError.CertificateUntrusted ?: throw e
            throw com.ifinmail.core.domain.error.MailException(e.message ?: "Untrusted certificate", e, untrusted)
        }
        activeAccountId.value = account.id
        engine.refresh(account.id)
        Unit
    }

    override suspend fun removeAccount(accountId: String) {
        engine.removeAccount(accountId)
        if (activeAccountId.value == accountId) {
            activeAccountId.value = engine.accounts.value.firstOrNull()?.id
        }
    }

    override suspend fun selectAccount(accountId: String) {
        activeAccountId.value = accountId
        refresh()
    }

    override suspend fun refresh(): Result<Int> = guarded {
        val id = activeAccountId.value ?: return@guarded 0
        engine.refresh(id)
    }

    override suspend fun openMessage(messageId: String): Result<UiMessage> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        toUi(engine.loadBody(id, messageId))
    }

    override suspend fun setMessageRead(messageId: String, read: Boolean): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.markRead(id, messageId, read)
        Unit
    }

    override suspend fun setMessageFlagged(messageId: String, flagged: Boolean): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.markFlagged(id, messageId, flagged)
        Unit
    }

    override suspend fun deleteMessage(messageId: String): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.deleteMessage(id, messageId)
    }

    override suspend fun send(draft: UiDraft): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.send(
            id,
            OutgoingDraft(
                to = draft.to.map(EmailAddress::parse),
                cc = draft.cc.map(EmailAddress::parse),
                subject = draft.subject,
                bodyText = draft.body
            )
        )
    }

    override suspend fun sendScheduled(draft: UiDraft, atEpochMs: Long): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.sendScheduled(
            id,
            OutgoingDraft(
                to = draft.to.map(EmailAddress::parse),
                cc = draft.cc.map(EmailAddress::parse),
                subject = draft.subject,
                bodyText = draft.body
            ),
            atEpochMs
        )
        Unit
    }

    override suspend fun cancelPending(mutationId: String) {
        engine.cancelPending(mutationId)
    }

    override suspend fun snooze(messageId: String, untilEpochMs: Long): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.snooze(id, messageId, untilEpochMs)
        Unit
    }

    override suspend fun smartReplies(messageId: String): List<com.ifinmail.app.shared.mail.UiSmartReply> {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        return engine.smartReplies(id, messageId).map {
            com.ifinmail.app.shared.mail.UiSmartReply(label = it.label, body = it.bodyPrefix)
        }
    }

    override suspend fun exportMbox(): Result<String> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.exportMbox(id)
    }

    override suspend fun saveDraft(draft: UiDraft): Result<Unit> = guarded {
        val id = activeAccountId.value ?: throw IllegalStateException("No active account")
        engine.saveDraft(
            OutgoingDraft(
                to = draft.to.map(EmailAddress::parse),
                cc = draft.cc.map(EmailAddress::parse),
                subject = draft.subject,
                bodyText = draft.body,
                inReplyToMessageId = draft.id.ifBlank { null },
                references = draft.id.ifBlank { null }
            )
        )
        Unit
    }

    override suspend fun deleteDraft(draftId: String) {
        engine.deleteDraft(draftId)
    }

    private fun toUi(message: StoredMessage) = UiMessage(
        id = message.id,
        accountId = message.accountId,
        subject = message.subject,
        fromName = message.fromName,
        fromAddress = message.fromAddress,
        dateEpochMs = message.dateEpochMs,
        snippet = message.snippet,
        read = message.read,
        flagged = message.flagged,
        hasAttachments = message.hasAttachments,
        toCsv = message.toCsv,
        ccCsv = message.ccCsv,
        bodyText = message.bodyText,
        bodyHtml = message.bodyHtml,
        threadId = message.threadId,
        triageCategory = message.triageCategory,
        snoozedUntilMs = message.snoozedUntilMs
    )

    private fun toUiSecurity(security: com.ifinmail.mail.model.ConnectionSecurity): com.ifinmail.app.shared.mail.UiSecurity =
        when (security) {
            com.ifinmail.mail.model.ConnectionSecurity.SSL_TLS -> com.ifinmail.app.shared.mail.UiSecurity.SSL_TLS
            com.ifinmail.mail.model.ConnectionSecurity.STARTTLS -> com.ifinmail.app.shared.mail.UiSecurity.STARTTLS
            com.ifinmail.mail.model.ConnectionSecurity.NONE -> com.ifinmail.app.shared.mail.UiSecurity.NONE
        }

    private fun fromUiSecurity(security: com.ifinmail.app.shared.mail.UiSecurity): com.ifinmail.mail.model.ConnectionSecurity =
        when (security) {
            com.ifinmail.app.shared.mail.UiSecurity.SSL_TLS -> com.ifinmail.mail.model.ConnectionSecurity.SSL_TLS
            com.ifinmail.app.shared.mail.UiSecurity.STARTTLS -> com.ifinmail.mail.model.ConnectionSecurity.STARTTLS
            com.ifinmail.app.shared.mail.UiSecurity.NONE -> com.ifinmail.mail.model.ConnectionSecurity.NONE
        }

    private inline fun <T> guarded(block: () -> T): Result<T> =
        try {
            busy.value = true
            Result.success(block())
        } catch (t: Throwable) {
            Result.failure(t)
        } finally {
            busy.value = false
        }
}

private fun FileCredentialStoreCompat(path: String) =
    com.ifinmail.mail.store.FileCredentialStore(path.toPath())

private fun <T, R> mapState(source: StateFlow<T>, transform: (T) -> R): StateFlow<R> =
    object : StateFlow<R> {
        override val value: R
            get() = transform(source.value)

        override val replayCache: List<R>
            get() = listOf(value)

        override suspend fun collect(collector: FlowCollector<R>): Nothing {
            source.collect { collector.emit(transform(it)) }
        }
    }
