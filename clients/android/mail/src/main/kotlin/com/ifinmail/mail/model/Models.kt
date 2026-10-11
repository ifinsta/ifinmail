package com.ifinmail.mail.model

import com.ifinmail.core.domain.error.MailError
import com.ifinmail.mail.transport.UntrustedCertificateException

typealias ConnectionSecurity = com.ifinmail.core.domain.model.ConnectionSecurity
typealias IncomingProtocol = com.ifinmail.core.domain.model.IncomingProtocol
typealias AuthMethod = com.ifinmail.core.domain.model.AuthMethod
typealias ServerConfig = com.ifinmail.core.domain.model.ServerConfig
typealias IncomingConfig = com.ifinmail.core.domain.model.IncomingConfig
typealias Credentials = com.ifinmail.core.domain.model.Credentials
typealias Account = com.ifinmail.core.domain.model.Account
typealias SyncState = com.ifinmail.core.domain.model.SyncState
typealias StoredMessage = com.ifinmail.core.domain.model.StoredMessage
typealias OutgoingDraft = com.ifinmail.core.domain.model.OutgoingDraft
typealias ConnectionProfile = com.ifinmail.core.domain.model.ConnectionProfile
typealias VerifyStep = com.ifinmail.core.domain.model.VerifyStep
typealias VerifyReport = com.ifinmail.core.domain.model.VerifyReport
typealias MailboxRole = com.ifinmail.core.domain.model.MailboxRole
typealias RemoteReference = com.ifinmail.core.domain.model.RemoteReference
typealias Mailbox = com.ifinmail.core.domain.model.Mailbox
typealias Identity = com.ifinmail.core.domain.model.Identity
typealias Attachment = com.ifinmail.core.domain.model.Attachment

typealias EmailAddress = com.ifinmail.core.domain.model.EmailAddress

class MailException(
    message: String,
    cause: Throwable? = null,
    val error: MailError = cause?.toMailError() ?: MailError.Unknown(message)
) : Exception(message, cause)

fun Throwable.toMailError(): MailError {
    val message = message ?: ""
    generateSequence(this) { it.cause }.take(8).filterIsInstance<UntrustedCertificateException>().firstOrNull()?.let {
        return MailError.CertificateUntrusted(it.host, it.sha256, it.subject)
    }
    return when {
        this is java.net.SocketTimeoutException -> MailError.Timeout
        this is java.io.IOException && message.contains("timed out", true) -> MailError.Timeout
        this is java.io.EOFException -> MailError.NetworkUnavailable
        this is java.io.IOException -> MailError.NetworkUnavailable
        listOf(
            "authentication failed", "authenticationfailed", "[auth]", "invalid credentials",
            "login failed", "wrong password", "authenticate", "access token", "oauth"
        ).any { message.contains(it, true) } -> MailError.AuthenticationRequired
        listOf("rate limit", "too many", "try again later").any { message.contains(it, true) } -> MailError.RateLimited
        listOf("quota", "over quota", "insufficient system storage").any { message.contains(it, true) } -> MailError.QuotaExceeded
        listOf("recipient", "relay access denied", "no such user", "user unknown").any { message.contains(it, true) } -> MailError.InvalidRecipient
        listOf("rejected", "blocked", "spam").any { message.contains(it, true) } -> MailError.SubmissionRejected
        listOf("permission denied", "not permitted").any { message.contains(it, true) } -> MailError.PermissionDenied
        listOf("does not support", "not advertised", "unsupported").any { message.contains(it, true) } -> MailError.UnsupportedCapability
        else -> MailError.Unknown(message)
    }
}
