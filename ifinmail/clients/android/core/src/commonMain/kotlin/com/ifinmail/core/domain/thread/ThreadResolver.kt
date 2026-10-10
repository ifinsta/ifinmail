package com.ifinmail.core.domain.thread

import com.ifinmail.core.domain.model.MailThread
import com.ifinmail.core.domain.model.StoredMessage

object ThreadResolver {

    fun normalizedSubject(subject: String): String {
        var s = subject.lowercase().trim()
        while (true) {
            val stripped = s.replace(Regex("^(re|fwd?|aw|sv|tr):\\s*"), "").trim()
            if (stripped == s) break
            s = stripped
        }
        s = s.replace(Regex("^\\[[^\\]]*\\]\\s*"), "").trim()
        return s.ifBlank { "(no subject)" }
    }

    fun computeThreadId(subject: String, accountId: String, messageId: String? = null, references: String? = null): String {
        if (!references.isNullOrBlank()) {
            val root = references.trim().split(Regex("\\s+")).firstOrNull { it.contains("@") }
            if (root != null) return "${accountId}:${root.lowercase().trim()}"
        }
        if (!messageId.isNullOrBlank() && messageId.contains("@")) {
            return "${accountId}:${normalizedSubject(subject)}"
        }
        return "${accountId}:${normalizedSubject(subject)}"
    }

    fun groupIntoThreads(messages: List<StoredMessage>): List<MailThread> {
        return messages.groupBy { it.threadId.ifBlank { computeThreadId(it.subject, it.accountId, it.messageIdHeader) } }
            .map { (threadId, grouped) ->
                val sorted = grouped.sortedByDescending { it.dateEpochMs ?: 0L }
                val first = sorted.first()
                MailThread(
                    id = threadId,
                    accountId = first.accountId,
                    subject = first.subject,
                    normalizedSubject = normalizedSubject(first.subject),
                    messageIds = sorted.map { it.id },
                    count = grouped.size,
                    unreadCount = grouped.count { !it.read },
                    hasStarred = grouped.any { it.flagged },
                    snippet = first.snippet,
                    latestDateMs = sorted.firstOrNull()?.dateEpochMs,
                    participants = grouped.mapNotNull { it.fromAddress }.distinct()
                )
            }
            .sortedByDescending { it.latestDateMs ?: 0L }
    }
}
