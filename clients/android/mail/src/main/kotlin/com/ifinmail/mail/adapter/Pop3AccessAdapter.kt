package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.core.domain.port.BodyPayload
import com.ifinmail.core.domain.port.ChangeSet
import com.ifinmail.core.domain.port.MailAccessAdapter
import com.ifinmail.core.domain.port.ProbeOutcome
import com.ifinmail.core.domain.port.SyncRequest
import com.ifinmail.mail.mime.MimeParser
import com.ifinmail.mail.model.Account
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.MailException
import com.ifinmail.core.domain.thread.ThreadResolver
import com.ifinmail.core.domain.triage.LocalClassifier
import com.ifinmail.mail.model.StoredMessage
import com.ifinmail.mail.model.SyncState
import com.ifinmail.mail.model.VerifyStep
import com.ifinmail.mail.model.toMailError
import com.ifinmail.mail.pop3.Pop3Client
import com.ifinmail.mail.transport.JvmSocketTransport

class Pop3AccessAdapter : MailAccessAdapter {

    override val protocol: IncomingProtocol = IncomingProtocol.POP3

    private fun requirePassword(credentials: Credentials): String =
        credentials.password ?: throw MailException("POP3 requires a password credential", error = MailError.AuthenticationRequired)

    override suspend fun probe(
        email: String,
        incoming: IncomingConfig,
        credentials: Credentials
    ): ProbeOutcome {
        val steps = mutableListOf<VerifyStep>()
        return try {
            JvmSocketTransport(incoming.server.pinnedCertSha256).use { transport ->
                val client = Pop3Client(transport)
                client.connect(incoming.server.host, incoming.server.port, incoming.server.security)
                steps += VerifyStep("Incoming connection", true, "${incoming.server.host}:${incoming.server.port}")
                client.authenticate(email, requirePassword(credentials))
                steps += VerifyStep("Incoming authentication", true, "Logged in as $email")
                val stat = client.stat()
                steps += VerifyStep("Mailbox check", true, "${stat.first} message(s) on server")
                ProbeOutcome(
                    success = true,
                    steps = steps,
                    capabilities = setOf(KnownCapability.MAIL_READ),
                    error = null,
                    errorDetail = null
                )
            }
        } catch (t: Throwable) {
            ProbeOutcome(false, steps, emptySet(), t.toMailError(), t.message)
        }
    }

    override suspend fun sync(request: SyncRequest): ChangeSet {
        val account = request.account
        val password = requirePassword(request.credentials)
        JvmSocketTransport(account.incoming.server.pinnedCertSha256).use { transport ->
            val client = Pop3Client(transport)
            client.connect(account.incoming.server.host, account.incoming.server.port, account.incoming.server.security)
            client.authenticate(account.email, password)
            val uidl = client.uidlMap()
            val knownUidls = request.knownUidls
            val fresh = uidl.entries.filter { (_, uidlValue) -> uidlValue !in knownUidls }
                .sortedByDescending { (num, _) -> num }
                .take(INITIAL_POP_BACKFILL)
            val classifier = LocalClassifier()
            val parsedNew = mutableListOf<StoredMessage>()
            for ((number, uidlValue) in fresh) {
                runCatching {
                    val raw = client.retr(number)
                    val parsed = MimeParser.parseMessage(raw)
                    val threadId = ThreadResolver.computeThreadId(parsed.subject, account.id, parsed.messageId)
                    val base = StoredMessage(
                        id = "${account.id}|$uidlValue",
                        accountId = account.id,
                        folder = "INBOX",
                        uid = stableHash(uidlValue),
                        subject = parsed.subject,
                        fromName = parsed.from?.name,
                        fromAddress = parsed.from?.address ?: "",
                        toCsv = parsed.to.joinToString(",") { it.address },
                        ccCsv = parsed.cc.joinToString(",") { it.address },
                        dateEpochMs = parsed.dateEpochMs,
                        snippet = parsed.snippet,
                        sizeBytes = raw.size.toLong(),
                        read = false,
                        flagged = false,
                        hasAttachments = parsed.attachmentNames.isNotEmpty(),
                        attachmentNames = parsed.attachmentNames,
                        bodyText = parsed.plainText,
                        bodyHtml = parsed.htmlText,
                        threadId = threadId,
                        messageIdHeader = parsed.messageId
                    )
                    val triage = classifier.classify(base)
                    parsedNew += base.copy(triageCategory = triage.category.name, triagePriority = triage.category.priority)
                }
            }
            val nextCursor = SyncState(
                imapLastSeenUid = 0L,
                imapUidValidity = 0L,
                popUidMap = uidl.entries.associate { it.key.toString() to it.value }
            )
            return ChangeSet(parsedNew, nextCursor)
        }
    }

    override suspend fun loadBody(
        account: Account,
        credentials: Credentials,
        message: StoredMessage
    ): BodyPayload {
        val password = requirePassword(credentials)
        JvmSocketTransport(account.incoming.server.pinnedCertSha256).use { transport ->
            val client = Pop3Client(transport)
            client.connect(account.incoming.server.host, account.incoming.server.port, account.incoming.server.security)
            client.authenticate(account.email, password)
            val uidlValue = message.id.substringAfterLast('|')
            val number = client.uidlMap().entries.firstOrNull { it.value == uidlValue }?.key
                ?: throw MailException("Message no longer on server", error = MailError.Conflict)
            val bytes = client.retr(number)
            val parsed = MimeParser.parseMessage(bytes)
            return BodyPayload(text = parsed.plainText, html = parsed.htmlText)
        }
    }

    override suspend fun setSeen(
        account: Account,
        credentials: Credentials,
        message: StoredMessage,
        read: Boolean
    ) {
    }

    override suspend fun deleteRemote(
        account: Account,
        credentials: Credentials,
        message: StoredMessage
    ) {
    }

    override suspend fun appendToMailbox(
        account: Account,
        credentials: Credentials,
        role: MailboxRole,
        mimeBytes: ByteArray
    ): Boolean = false

    internal fun stableHash(value: String): Long =
        java.security.MessageDigest.getInstance("SHA-1").digest(value.toByteArray()).take(8)
            .foldIndexed(0L) { i, acc, b -> acc or ((b.toLong() and 0xFF) shl (i * 8)) }

    companion object {
        const val INITIAL_POP_BACKFILL = 50
    }
}
