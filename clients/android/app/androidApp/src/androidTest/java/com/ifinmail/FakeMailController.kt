package com.ifinmail

import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiAccount
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.mail.UiProviderProfile
import com.ifinmail.app.shared.mail.UiProtocol
import com.ifinmail.app.shared.mail.UiSecurity
import com.ifinmail.app.shared.mail.UiSmartReply
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

class FakeMailController : MailController {

    val accountsFlow = MutableStateFlow<List<UiAccount>>(emptyList())
    private val messagesFlow = MutableStateFlow<List<UiMessage>>(emptyList())
    val activeId = MutableStateFlow<String?>(null)
    private val busyFlow = MutableStateFlow(false)
    val queued = MutableStateFlow(0)

    override val accounts: StateFlow<List<UiAccount>> = accountsFlow
    override val messages: StateFlow<List<UiMessage>> get() = messagesFlow
    override val activeAccountId: StateFlow<String?> = activeId
    override val isBusy: StateFlow<Boolean> = busyFlow
    override val queuedCount: StateFlow<Int> = queued

    val lastQueuedId = MutableStateFlow<String?>(null)
    override val lastQueuedMutationId: StateFlow<String?> = lastQueuedId

    val draftsFlow = MutableStateFlow<List<UiDraft>>(emptyList())
    override val drafts: StateFlow<List<UiDraft>> = draftsFlow

    var refreshResult: Result<Int> = Result.success(0)
    var addAccountResult: Result<Unit> = Result.success(Unit)
    var sendResult: Result<Unit> = Result.success(Unit)
    var deleteResult: Result<Unit> = Result.success(Unit)
    var autoConfigureProfiles: List<UiProviderProfile>? = null

    val sentDrafts = mutableListOf<UiDraft>()
    var refreshCalls = 0
    var removedAccounts = mutableListOf<String>()
    var deletedIds = mutableListOf<String>()
    var readToggles = mutableListOf<Pair<String, Boolean>>()
    var flagToggles = mutableListOf<Pair<String, Boolean>>()

    fun givenAccount(email: String) {
        val account = UiAccount(id = "acct-$email", email = email, displayName = email.substringBefore('@'))
        accountsFlow.value = accountsFlow.value + account
        if (activeId.value == null) activeId.value = account.id
    }

    fun givenMessages(vararg messages: UiMessage) {
        messagesFlow.value = messages.toList()
    }

    override suspend fun autoConfigure(email: String): List<UiProviderProfile> {
        autoConfigureProfiles?.let { return it }
        return if (email.endsWith("gmail.com")) listOf(
            UiProviderProfile(
                label = "Gmail · IMAP",
                protocol = UiProtocol.IMAP,
                incomingHost = "imap.gmail.com",
                incomingPort = 993,
                incomingSecurity = UiSecurity.SSL_TLS,
                outgoingHost = "smtp.gmail.com",
                outgoingPort = 465,
                outgoingSecurity = UiSecurity.SSL_TLS,
                note = "Requires an app password or OAuth2 token."
            ),
            UiProviderProfile(
                label = "Gmail · POP3",
                protocol = UiProtocol.POP3,
                incomingHost = "pop.gmail.com",
                incomingPort = 995,
                incomingSecurity = UiSecurity.SSL_TLS,
                outgoingHost = "smtp.gmail.com",
                outgoingPort = 465,
                outgoingSecurity = UiSecurity.SSL_TLS,
                note = "Requires an app password or OAuth2 token."
            )
        ) else emptyList()
    }

    override suspend fun addAccount(
        email: String,
        displayName: String,
        profile: UiProviderProfile,
        password: String?,
        oauthAccessToken: String?,
        trustedCertificateSha256: String?
    ): Result<Unit> {
        lastAddTrustedCert = trustedCertificateSha256
        lastAddEmail = email
        lastAddPassword = password
        lastAddToken = oauthAccessToken
        return addAccountResult.map {
            givenAccount(email)
            givenMessages(seedMessage(email, 1), seedMessage(email, 2))
        }
    }

    var lastAddTrustedCert: String? = null
        private set
    var lastAddEmail: String? = null
        private set
    var lastAddPassword: String? = null
        private set
    var lastAddToken: String? = null
        private set

    override suspend fun removeAccount(accountId: String) {
        removedAccounts += accountId
        accountsFlow.value = accountsFlow.value.filterNot { it.id == accountId }
        if (activeId.value == accountId) activeId.value = accountsFlow.value.firstOrNull()?.id
    }

    override suspend fun selectAccount(accountId: String) {
        activeId.value = accountId
    }

    override suspend fun refresh(): Result<Int> {
        refreshCalls += 1
        return refreshResult
    }

    override suspend fun openMessage(messageId: String): Result<UiMessage> =
        messagesFlow.value.firstOrNull { it.id == messageId }?.let {
            Result.success(it.copy(read = true, bodyText = it.bodyText ?: DEFAULT_BODY))
        } ?: Result.failure(IllegalStateException("Unknown message $messageId"))

    override suspend fun setMessageRead(messageId: String, read: Boolean): Result<Unit> {
        readToggles += messageId to read
        messagesFlow.value = messagesFlow.value.map { if (it.id == messageId) it.copy(read = read) else it }
        return Result.success(Unit)
    }

    override suspend fun setMessageFlagged(messageId: String, flagged: Boolean): Result<Unit> {
        flagToggles += messageId to flagged
        messagesFlow.value = messagesFlow.value.map { if (it.id == messageId) it.copy(flagged = flagged) else it }
        return Result.success(Unit)
    }

    override suspend fun deleteMessage(messageId: String): Result<Unit> {
        deletedIds += messageId
        return deleteResult.map { messagesFlow.value = messagesFlow.value.filterNot { m -> m.id == messageId } }
    }

    override suspend fun send(draft: UiDraft): Result<Unit> {
        sentDrafts += draft
        return sendResult
    }

    override suspend fun sendScheduled(draft: UiDraft, atEpochMs: Long): Result<Unit> {
        scheduledDrafts += atEpochMs to draft
        return Result.success(Unit)
    }

    override suspend fun cancelPending(mutationId: String) {
        cancelledMutations += mutationId
    }

    override suspend fun snooze(messageId: String, untilEpochMs: Long): Result<Unit> {
        snoozedIds += messageId to untilEpochMs
        messagesFlow.value = messagesFlow.value.map { if (it.id == messageId) it.copy(snoozedUntilMs = untilEpochMs) else it }
        return Result.success(Unit)
    }

    override suspend fun smartReplies(messageId: String): List<UiSmartReply> =
        listOf(UiSmartReply("Got it", "Thanks for letting me know."), UiSmartReply("Thanks", "Appreciate it!"))

    override suspend fun exportMbox(): Result<String> = Result.success("From MAILER-DAEMON\nTest export")

    override suspend fun saveDraft(draft: UiDraft): Result<Unit> {
        draftsFlow.value = draftsFlow.value.filterNot { it.id == draft.id } + draft
        return Result.success(Unit)
    }

    override suspend fun deleteDraft(draftId: String) {
        draftsFlow.value = draftsFlow.value.filterNot { it.id == draftId }
    }

    var scheduledDrafts = mutableListOf<Pair<Long, UiDraft>>()
    var cancelledMutations = mutableListOf<String>()
    var snoozedIds = mutableListOf<Pair<String, Long>>()

    companion object {
        const val DEFAULT_BODY = "Hello world body"
        fun seedMessage(accountEmail: String, index: Int) = UiMessage(
            id = "$accountEmail-msg$index",
            accountId = "acct-$accountEmail",
            subject = if (index == 1) "Quarterly report attached" else "Lunch tomorrow?",
            fromName = if (index == 1) "Alice Example" else null,
            fromAddress = "sender$index@example.com",
            dateEpochMs = 1755900000000L + index,
            snippet = if (index == 1) "See the numbers for Q3." else "Are you free at noon?",
            read = index != 1,
            flagged = false,
            hasAttachments = index == 1,
            triageCategory = if (index == 1) "FINANCIAL" else "GENERAL",
            threadId = "acct-$accountEmail:thread-$index"
        )
    }
}
