package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.port.BodyPayload
import com.ifinmail.core.domain.port.ChangeSet
import com.ifinmail.core.domain.port.MailAccessAdapter
import com.ifinmail.core.domain.port.ProbeOutcome
import com.ifinmail.core.domain.port.SyncRequest
import com.ifinmail.core.domain.model.SyncState
import com.ifinmail.core.domain.thread.ThreadResolver
import com.ifinmail.core.domain.triage.LocalClassifier
import com.ifinmail.mail.mime.MimeParser
import com.ifinmail.mail.model.Account
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.ServerConfig
import com.ifinmail.mail.model.MailboxRole
import com.ifinmail.mail.model.StoredMessage
import com.ifinmail.mail.model.VerifyStep
import com.ifinmail.mail.model.toMailError
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.MailTransport

class ImapAccessAdapter(
    private val transportFactory: (ServerConfig) -> MailTransport = { JvmSocketTransport(it.pinnedCertSha256) }
) : MailAccessAdapter {

    override val protocol: IncomingProtocol = IncomingProtocol.IMAP

    override suspend fun probe(
        email: String,
        incoming: IncomingConfig,
        credentials: Credentials
    ): ProbeOutcome {
        val steps = mutableListOf<VerifyStep>()
        return try {
            ImapSession.connect(transportFactory, incoming, credentials, email, steps).use { session ->
                session.client.select(session.inbox())
                steps += VerifyStep("INBOX opened", true, "Mailbox accessible")
                // The pre-login list omits extensions such as MOVE; ask again now that we are in.
                session.client.refreshCapabilities()
                ProbeOutcome(
                    success = true,
                    steps = steps,
                    capabilities = ImapSession.capabilitiesOf(session.client),
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
        ImapSession.connect(transportFactory, account.incoming, request.credentials, account.email).use { session ->
            val client = session.client
            val selectResult = client.select(session.inbox())
            val cursor = request.cursor
            var lastSeenUid = cursor.imapLastSeenUid
            var uidValidity = cursor.imapUidValidity
            if (uidValidity != 0L && selectResult.uidValidity != 0L && uidValidity != selectResult.uidValidity) {
                lastSeenUid = 0L
            }
            val backfillFrom = if (lastSeenUid > 0L) lastSeenUid else request.backfillFromUid
            val summaries = client.fetchSummaries(backfillFrom).filter { it.uid > lastSeenUid }
            val inboxName = session.inbox()
            val classifier = LocalClassifier()
            val parsedNew = summaries.mapNotNull { summary ->
                val headerBytes = summary.headerBytes ?: return@mapNotNull null
                val parsed = MimeParser.parseMessage(headerBytes)
                val threadId = ThreadResolver.computeThreadId(parsed.subject, account.id, parsed.messageId)
                val base = StoredMessage(
                    id = "${account.id}-${summary.uid}",
                    accountId = account.id,
                    folder = inboxName,
                    uid = summary.uid,
                    subject = parsed.subject,
                    fromName = parsed.from?.name,
                    fromAddress = parsed.from?.address ?: "",
                    toCsv = parsed.to.joinToString(",") { it.address },
                    ccCsv = parsed.cc.joinToString(",") { it.address },
                    dateEpochMs = parsed.dateEpochMs ?: summary.internalDateEpochMs,
                    snippet = parsed.snippet,
                    sizeBytes = summary.sizeBytes,
                    read = summary.flags.any { it.equals("\\Seen", ignoreCase = true) },
                    flagged = summary.flags.any { it.equals("\\Flagged", ignoreCase = true) },
                    hasAttachments = parsed.attachmentNames.isNotEmpty(),
                    attachmentNames = parsed.attachmentNames,
                    threadId = threadId,
                    messageIdHeader = parsed.messageId
                )
                val triage = classifier.classify(base)
                base.copy(triageCategory = triage.category.name, triagePriority = triage.category.priority)
            }
            val nextCursor = SyncState(
                imapLastSeenUid = maxOf(lastSeenUid, summaries.maxOfOrNull { it.uid } ?: lastSeenUid),
                imapUidValidity = selectResult.uidValidity,
                popUidMap = cursor.popUidMap
            )
            return ChangeSet(parsedNew, nextCursor)
        }
    }

    override suspend fun loadBody(
        account: Account,
        credentials: Credentials,
        message: StoredMessage
    ): BodyPayload {
        ImapSession.connect(transportFactory, account.incoming, credentials, account.email).use { session ->
            val client = session.client
            client.select(message.folder.ifBlank { session.inbox() })
            val bytes = client.fetchBody(message.uid)
            client.storeFlags(message.uid, addFlags = setOf("\\Seen"))
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
        ImapSession.connect(transportFactory, account.incoming, credentials, account.email).use { session ->
            val client = session.client
            client.select(message.folder.ifBlank { session.inbox() })
            client.storeFlags(
                message.uid,
                addFlags = if (read) setOf("\\Seen") else emptySet(),
                removeFlags = if (read) emptySet() else setOf("\\Seen")
            )
        }
    }

    override suspend fun setFlagged(
        account: Account,
        credentials: Credentials,
        message: StoredMessage,
        flagged: Boolean
    ) {
        ImapSession.connect(transportFactory, account.incoming, credentials, account.email).use { session ->
            val client = session.client
            client.select(message.folder.ifBlank { session.inbox() })
            client.storeFlags(
                message.uid,
                addFlags = if (flagged) setOf("\\Flagged") else emptySet(),
                removeFlags = if (flagged) emptySet() else setOf("\\Flagged")
            )
        }
    }

    override suspend fun deleteRemote(
        account: Account,
        credentials: Credentials,
        message: StoredMessage
    ) {
        ImapSession.connect(transportFactory, account.incoming, credentials, account.email).use { session ->
            val client = session.client
            client.select(message.folder.ifBlank { session.inbox() })
            client.storeFlags(message.uid, addFlags = setOf("\\Deleted"))
            client.expunge()
        }
    }

    override suspend fun appendToMailbox(
        account: Account,
        credentials: Credentials,
        role: MailboxRole,
        mimeBytes: ByteArray
    ): Boolean {
        ImapSession.connect(transportFactory, account.incoming, credentials, account.email).use { session ->
            val target = session.mailboxFor(role) ?: return false
            session.client.append(target, mimeBytes)
            return true
        }
    }
}
