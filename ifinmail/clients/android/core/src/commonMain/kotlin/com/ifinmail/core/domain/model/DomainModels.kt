package com.ifinmail.core.domain.model

import kotlinx.serialization.Serializable

@Serializable
data class SyncState(
    val imapLastSeenUid: Long = 0L,
    val imapUidValidity: Long = 0L,
    val popUidMap: Map<String, String> = emptyMap()
)

@Serializable
data class Account(
    val id: String,
    val email: String,
    val displayName: String,
    val incoming: IncomingConfig,
    val outgoing: ServerConfig,
    val credentials: Credentials? = null,
    val capabilities: Set<String> = emptySet(),
    val sync: SyncState = SyncState()
) {
    fun primaryIdentity(): Identity = Identity(
        id = "primary",
        displayName = displayName,
        address = email
    )
}

@Serializable
data class StoredMessage(
    val id: String,
    val accountId: String,
    val folder: String,
    val uid: Long,
    val subject: String,
    val fromName: String?,
    val fromAddress: String,
    val toCsv: String,
    val ccCsv: String,
    val dateEpochMs: Long?,
    val snippet: String,
    val sizeBytes: Long,
    val read: Boolean,
    val flagged: Boolean,
    val hasAttachments: Boolean,
    val attachmentNames: List<String> = emptyList(),
    val bodyText: String? = null,
    val bodyHtml: String? = null,
    val threadId: String = "",
    val messageIdHeader: String? = null,
    val triageCategory: String? = null,
    val triagePriority: Int = 0,
    val snoozedUntilMs: Long? = null
)

@Serializable
data class MailThread(
    val id: String,
    val accountId: String,
    val subject: String,
    val normalizedSubject: String,
    val messageIds: List<String>,
    val count: Int,
    val unreadCount: Int,
    val hasStarred: Boolean,
    val snippet: String,
    val latestDateMs: Long?,
    val participants: List<String>
)

@Serializable
data class OutgoingDraft(
    val to: List<EmailAddress>,
    val cc: List<EmailAddress> = emptyList(),
    val bcc: List<EmailAddress> = emptyList(),
    val subject: String,
    val bodyText: String,
    val inReplyToMessageId: String? = null,
    val references: String? = null
)

enum class MutationKind { SEND, MARK_READ, DELETE }

@Serializable
data class PendingMutation(
    val id: String,
    val accountId: String,
    val kind: MutationKind,
    val messageId: String? = null,
    val read: Boolean? = null,
    val draft: OutgoingDraft? = null,
    val createdAtEpochMs: Long = 0L,
    val scheduledAtMs: Long = 0L
)

data class ConnectionProfile(
    val label: String,
    val incoming: IncomingConfig,
    val outgoing: ServerConfig,
    val note: String? = null
)

data class VerifyStep(
    val name: String,
    val ok: Boolean,
    val detail: String
)

data class VerifyReport(
    val success: Boolean,
    val steps: List<VerifyStep>,
    val error: String? = null
) {
    companion object {
        fun failure(steps: List<VerifyStep>, error: String) =
            VerifyReport(success = false, steps = steps, error = error)
    }
}
