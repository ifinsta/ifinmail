package com.ifinmail.core.domain.error

sealed class MailError {
    data object AuthenticationRequired : MailError()
    data object PermissionDenied : MailError()
    data object RateLimited : MailError()
    data object Unavailable : MailError()
    data object Conflict : MailError()
    data object QuotaExceeded : MailError()
    data object InvalidRecipient : MailError()
    data object SubmissionRejected : MailError()
    data object UnsupportedCapability : MailError()
    data object NetworkUnavailable : MailError()
    data object Timeout : MailError()
    /** The server's certificate is not issued by a trusted authority; [sha256] identifies it. */
    data class CertificateUntrusted(val host: String, val sha256: String, val subject: String) : MailError()
    data class Protocol(val detail: String) : MailError()
    data class Unknown(val detail: String) : MailError()

    fun userMessage(): String = when (this) {
        AuthenticationRequired -> "Sign-in was rejected. Check the password or token for this account."
        PermissionDenied -> "The server refused this action for this account."
        RateLimited -> "The server asked us to slow down. Try again shortly."
        Unavailable -> "The mail service is temporarily unavailable."
        Conflict -> "This change conflicts with the server state. Refresh and retry."
        QuotaExceeded -> "The mailbox or message exceeds the server quota."
        InvalidRecipient -> "One of the recipients does not exist on this server."
        SubmissionRejected -> "The server rejected this message."
        UnsupportedCapability -> "This account's server does not support that feature."
        NetworkUnavailable -> "No connection to the mail server."
        Timeout -> "The server took too long to respond."
        is CertificateUntrusted -> "$host presented a certificate that is not from a trusted authority."
        is Protocol -> detail.ifBlank { "Protocol error." }
        is Unknown -> detail.ifBlank { "Unexpected error." }
    }
}

class MailException(
    message: String,
    cause: Throwable? = null,
    val error: MailError
) : Exception(message, cause)
