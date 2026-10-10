package com.ifinmail.core.domain.capability

enum class KnownCapability {
    MAIL_READ,
    MAIL_SEND,
    MAIL_SEARCH,
    MAIL_PUSH,
    MAIL_MOVE,
    MAIL_FLAG,
    MAIL_SENT_APPEND,
    MAIL_DELETE_REMOTE,
    MAIL_SCHEDULE,
    MAIL_SNOOZE,
    MAIL_SMART_REPLY,
    MAIL_CONFIDENTIAL,
    MAIL_EXPORT,
    CALENDAR_READ,
    CALENDAR_WRITE,
    CONTACTS_READ,
    CONTACTS_WRITE
}

data class AccountCapabilities(
    val granted: Set<KnownCapability>,
    val extensions: Set<String> = emptySet()
) {
    fun has(capability: KnownCapability): Boolean = capability in granted

    fun names(): Set<String> = granted.map { it.name }.toSet()

    companion object {
        val NONE = AccountCapabilities(emptySet())

        fun ofNames(names: Collection<String>): AccountCapabilities =
            AccountCapabilities(names.mapNotNull { runCatching { KnownCapability.valueOf(it) }.getOrNull() }.toSet())
    }
}
