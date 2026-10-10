package com.ifinmail.app.shared.mail

import kotlinx.coroutines.flow.StateFlow

enum class UiProtocol { IMAP, POP3 }

enum class UiSecurity(val label: String) {
    SSL_TLS("SSL/TLS"),
    STARTTLS("STARTTLS"),
    NONE("None")
}

data class UiAccount(
    val id: String,
    val email: String,
    val displayName: String,
    val capabilities: Set<String> = emptySet()
) {
    fun hasCapability(name: String): Boolean = name in capabilities
}

data class UiMessage(
    val id: String,
    val accountId: String,
    val subject: String,
    val fromName: String?,
    val fromAddress: String,
    val dateEpochMs: Long?,
    val snippet: String,
    val read: Boolean,
    val flagged: Boolean,
    val hasAttachments: Boolean,
    val toCsv: String = "",
    val ccCsv: String = "",
    val bodyText: String? = null,
    val bodyHtml: String? = null,
    val threadId: String = "",
    val triageCategory: String? = null,
    val snoozedUntilMs: Long? = null
)

data class UiDraft(
    val to: List<String>,
    val cc: List<String> = emptyList(),
    val subject: String,
    val body: String,
    val id: String = ""
)

data class UiProviderProfile(
    val label: String,
    val protocol: UiProtocol,
    val incomingHost: String,
    val incomingPort: Int,
    val incomingSecurity: UiSecurity,
    val outgoingHost: String,
    val outgoingPort: Int,
    val outgoingSecurity: UiSecurity,
    val note: String?
) {
    val summaryLine: String
        get() = "$incomingHost:$incomingPort (${incomingSecurity.label}) Â· $outgoingHost:$outgoingPort (${outgoingSecurity.label})"
}

interface MailController {
    val accounts: StateFlow<List<UiAccount>>
    val messages: StateFlow<List<UiMessage>>
    val activeAccountId: StateFlow<String?>
    val isBusy: StateFlow<Boolean>
    val queuedCount: StateFlow<Int>
    val lastQueuedMutationId: StateFlow<String?>
    val drafts: StateFlow<List<UiDraft>>

    suspend fun autoConfigure(email: String): List<UiProviderProfile>

    suspend fun addAccount(
        email: String,
        displayName: String,
        profile: UiProviderProfile,
        password: String?,
        oauthAccessToken: String?
    ): Result<Unit>

    suspend fun removeAccount(accountId: String)
    suspend fun selectAccount(accountId: String)
    suspend fun refresh(): Result<Int>
    suspend fun openMessage(messageId: String): Result<UiMessage>
    suspend fun setMessageRead(messageId: String, read: Boolean): Result<Unit>
    suspend fun setMessageFlagged(messageId: String, flagged: Boolean): Result<Unit>
    suspend fun deleteMessage(messageId: String): Result<Unit>
    suspend fun send(draft: UiDraft): Result<Unit>
    suspend fun sendScheduled(draft: UiDraft, atEpochMs: Long): Result<Unit>
    suspend fun cancelPending(mutationId: String)
    suspend fun snooze(messageId: String, untilEpochMs: Long): Result<Unit>
    suspend fun smartReplies(messageId: String): List<UiSmartReply>
    suspend fun exportMbox(): Result<String>
    suspend fun saveDraft(draft: UiDraft): Result<Unit>
    suspend fun deleteDraft(draftId: String)
}

data class UiSmartReply(
    val label: String,
    val body: String
)

