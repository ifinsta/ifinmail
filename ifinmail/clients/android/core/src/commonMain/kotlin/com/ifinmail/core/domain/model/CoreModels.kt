package com.ifinmail.core.domain.model

import kotlinx.serialization.Serializable

@Serializable
data class EmailAddress(
    val name: String? = null,
    val address: String
) {
    override fun toString(): String =
        if (name.isNullOrBlank()) "<$address>" else "\"${name.replace("\"", "'")}\" <$address>"

    companion object {
        fun parse(raw: String): EmailAddress {
            val trimmed = raw.trim().trim(',')
            if (trimmed.isEmpty()) return EmailAddress(address = "")
            if (!trimmed.contains('<')) return EmailAddress(address = trimmed)
            val open = trimmed.indexOf('<')
            val close = trimmed.lastIndexOf('>')
            val addr = if (close > open) trimmed.substring(open + 1, close).trim() else ""
            var display = trimmed.substring(0, open).trim()
            if (display.length >= 2 && display.first() == '"' && display.last() == '"') {
                display = display.substring(1, display.length - 1)
            }
            return EmailAddress(name = display.ifBlank { null }, address = addr)
        }
    }
}

enum class ConnectionSecurity {
    SSL_TLS,
    STARTTLS,
    NONE
}

enum class IncomingProtocol {
    IMAP,
    POP3
}

enum class AuthMethod {
    PASSWORD,
    XOAUTH2
}

@Serializable
data class ServerConfig(
    val host: String,
    val port: Int,
    val security: ConnectionSecurity
)

@Serializable
data class IncomingConfig(
    val protocol: IncomingProtocol,
    val server: ServerConfig
)

@Serializable
data class Credentials(
    val authMethod: AuthMethod = AuthMethod.PASSWORD,
    val password: String? = null,
    val oauthAccessToken: String? = null,
    val oauthRefreshToken: String? = null
)

data class RemoteReference(
    val protocol: IncomingProtocol,
    val accountId: String,
    val resourceType: String,
    val remoteId: String
)

enum class MailboxRole {
    INBOX, SENT, DRAFTS, TRASH, ARCHIVE, SPAM, OTHER
}

data class Mailbox(
    val id: String,
    val name: String,
    val parentId: String? = null,
    val role: MailboxRole = MailboxRole.OTHER
)

data class Identity(
    val id: String,
    val displayName: String,
    val address: String,
    val replyTo: String? = null,
    val signature: String? = null
)

data class Attachment(
    val id: String,
    val filename: String,
    val mediaType: String = "application/octet-stream",
    val sizeBytes: Long = 0,
    val contentReference: String? = null
)
