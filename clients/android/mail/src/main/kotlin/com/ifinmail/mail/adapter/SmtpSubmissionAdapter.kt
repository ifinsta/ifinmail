package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.port.ProbeOutcome
import com.ifinmail.core.domain.port.SubmissionAdapter
import com.ifinmail.core.domain.model.OutgoingDraft
import com.ifinmail.core.domain.model.ServerConfig
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.VerifyStep
import com.ifinmail.mail.model.toMailError
import com.ifinmail.mail.smtp.SmtpClient
import com.ifinmail.mail.transport.JvmSocketTransport

class SmtpSubmissionAdapter : SubmissionAdapter {

    override suspend fun probe(
        email: String,
        outgoing: ServerConfig,
        credentials: Credentials
    ): ProbeOutcome {
        val steps = mutableListOf<VerifyStep>()
        return try {
            JvmSocketTransport(outgoing.pinnedCertSha256).use { transport ->
                val client = SmtpClient(transport)
                client.connect(outgoing.host, outgoing.port, outgoing.security)
                steps += VerifyStep("Outgoing connection", true, "${outgoing.host}:${outgoing.port}")
                if (outgoing.security == ConnectionSecurity.STARTTLS) {
                    steps += VerifyStep("Outgoing STARTTLS", true, "Encrypted channel established")
                }
                client.authenticate(email, credentials.password, credentials.oauthAccessToken)
                steps += VerifyStep("Outgoing authentication", true, "Ready to send as $email")
                ProbeOutcome(true, steps, setOf(KnownCapability.MAIL_SEND), null, null)
            }
        } catch (t: Throwable) {
            ProbeOutcome(false, steps, emptySet(), t.toMailError(), t.message)
        }
    }

    override suspend fun submit(
        email: String,
        outgoing: ServerConfig,
        credentials: Credentials,
        draft: OutgoingDraft,
        mimeBytes: ByteArray
    ) {
        JvmSocketTransport(outgoing.pinnedCertSha256).use { transport ->
            val client = SmtpClient(transport)
            client.connect(outgoing.host, outgoing.port, outgoing.security)
            client.authenticate(email, credentials.password, credentials.oauthAccessToken)
            val recipients = draft.to + draft.cc + draft.bcc
            client.sendMail(email, recipients.map { it.address }, mimeBytes)
            client.close()
        }
    }
}
