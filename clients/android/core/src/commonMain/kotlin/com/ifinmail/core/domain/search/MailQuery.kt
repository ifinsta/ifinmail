package com.ifinmail.core.domain.search

import com.ifinmail.core.domain.model.StoredMessage

data class MailQuery(
    val text: String = "",
    val from: String? = null,
    val to: String? = null,
    val subject: String? = null,
    val hasAttachment: Boolean? = null,
    val isUnread: Boolean? = null,
    val isStarred: Boolean? = null,
    val isUrgent: Boolean? = null,
    val category: String? = null,
    val beforeMs: Long? = null,
    val afterMs: Long? = null,
    val inFolder: String? = null
) {
    val isEmpty: Boolean get() = text.isBlank() && from == null && to == null && subject == null &&
        hasAttachment == null && isUnread == null && isStarred == null && isUrgent == null &&
        category == null && beforeMs == null && afterMs == null && inFolder == null
}

object MailQueryParser {
    fun parse(raw: String): MailQuery {
        if (raw.isBlank()) return MailQuery()
        val tokens = raw.trim().split(Regex("\\s+"))
        var textParts = mutableListOf<String>()
        var from: String? = null
        var to: String? = null
        var subject: String? = null
        var hasAttachment: Boolean? = null
        var isUnread: Boolean? = null
        var isStarred: Boolean? = null
        var isUrgent: Boolean? = null
        var category: String? = null
        var beforeMs: Long? = null
        var afterMs: Long? = null
        var inFolder: String? = null

        for (token in tokens) {
            when {
                token.startsWith("from:", true) -> from = token.substringAfter(":").trim().ifBlank { null }
                token.startsWith("to:", true) -> to = token.substringAfter(":").trim().ifBlank { null }
                token.startsWith("subject:", true) -> subject = token.substringAfter(":").trim().ifBlank { null }
                token.equals("has:attachment", true) || token.equals("has:attachments", true) -> hasAttachment = true
                token.equals("is:unread", true) -> isUnread = true
                token.equals("is:read", true) -> isUnread = false
                token.equals("is:starred", true) || token.equals("is:flagged", true) -> isStarred = true
                token.equals("is:unstarred", true) -> isStarred = false
                token.equals("is:urgent", true) || token.equals("priority:high", true) -> isUrgent = true
                token.startsWith("category:", true) -> category = token.substringAfter(":").trim().lowercase().ifBlank { null }
                token.startsWith("in:", true) -> inFolder = token.substringAfter(":").trim().ifBlank { null }
                token.startsWith("before:", true) -> beforeMs = parseDate(token.substringAfter(":"))
                token.startsWith("after:", true) -> afterMs = parseDate(token.substringAfter(":"))
                else -> textParts.add(token)
            }
        }
        return MailQuery(
            text = textParts.joinToString(" ").trim(),
            from = from,
            to = to,
            subject = subject,
            hasAttachment = hasAttachment,
            isUnread = isUnread,
            isStarred = isStarred,
            isUrgent = isUrgent,
            category = category,
            beforeMs = beforeMs,
            afterMs = afterMs,
            inFolder = inFolder
        )
    }

    private fun parseDate(raw: String): Long? {
        return try {
            val parts = raw.split("/", "-", ".")
            if (parts.size == 3) {
                val y = parts[0].toIntOrNull() ?: parts[2].toIntOrNull() ?: return null
                val m = parts[1].toIntOrNull() ?: return null
                val d = if (parts[0].length == 4) parts[2].toIntOrNull() else parts[0].toIntOrNull() ?: return null
                // Approximate epoch: use Instant parsing if available, else simple
                null
            } else null
        } catch (e: Exception) { null }
    }
}

fun MailQuery.matches(message: StoredMessage): Boolean {
    if (text.isNotBlank()) {
        val q = text.lowercase()
        val haystack = "${message.subject} ${message.snippet} ${message.fromAddress} ${message.fromName}".lowercase()
        if (!haystack.contains(q)) return false
    }
    if (from != null && !message.fromAddress.lowercase().contains(from.lowercase()) &&
        !(message.fromName?.lowercase()?.contains(from.lowercase()) == true)) return false
    if (to != null && !message.toCsv.lowercase().contains(to.lowercase())) return false
    if (subject != null && !message.subject.lowercase().contains(subject.lowercase())) return false
    if (hasAttachment != null && message.hasAttachments != hasAttachment) return false
    if (isUnread != null && message.read == isUnread) return false
    if (isStarred != null && message.flagged != isStarred) return false
    if (isUrgent != null) {
        val urgent = message.triageCategory == "Urgent"
        if (urgent != isUrgent) return false
    }
    if (category != null && message.triageCategory?.lowercase() != category.lowercase()) return false
    if (inFolder != null && !message.folder.equals(inFolder, ignoreCase = true)) return false
    if (beforeMs != null && (message.dateEpochMs ?: Long.MAX_VALUE) >= beforeMs) return false
    if (afterMs != null && (message.dateEpochMs ?: 0L) <= afterMs) return false
    return true
}
