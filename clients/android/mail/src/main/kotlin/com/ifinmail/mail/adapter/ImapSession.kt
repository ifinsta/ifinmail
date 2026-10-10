package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.mail.imap.ImapClient
import com.ifinmail.mail.model.Account
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.VerifyStep
import com.ifinmail.mail.transport.MailTransport

internal class ImapSession(
    val transport: MailTransport,
    val client: ImapClient,
    private val roleNames: MutableMap<MailboxRole, String> = mutableMapOf()
) : AutoCloseable {

    suspend fun inbox(): String {
        discoverRolesOnce()
        return roleNames[MailboxRole.INBOX] ?: "INBOX"
    }

    suspend fun mailboxFor(role: MailboxRole): String? {
        discoverRolesOnce()
        return roleNames[role]
    }

    private suspend fun discoverRolesOnce() {
        if (roleNames.isNotEmpty()) return
        val folders = runCatching { client.listFoldersDetailed() }.getOrNull().orEmpty()
        for (entry in folders) {
            val role = entry.specialUseRole() ?: continue
            if (role != MailboxRole.INBOX && roleNames[role] == null) {
                roleNames[role] = entry.name
            }
        }
        folders.firstOrNull { it.name.equals("INBOX", true) }?.let {
            roleNames[MailboxRole.INBOX] = it.name
        }
        roleNames.putIfAbsent(MailboxRole.INBOX, "INBOX")
    }

    override fun close() {
        client.close()
    }

    companion object {
        suspend fun connect(
            transportFactory: () -> MailTransport,
            incoming: IncomingConfig,
            credentials: Credentials,
            email: String,
            steps: MutableList<VerifyStep>? = null
        ): ImapSession {
            val transport = transportFactory()
            try {
                val client = ImapClient(transport)
                client.connect(incoming.server.host, incoming.server.port, incoming.server.security)
                steps?.add(VerifyStep("Incoming connection", true, "${incoming.server.host}:${incoming.server.port}"))
                if (incoming.server.security == ConnectionSecurity.STARTTLS) {
                    client.startTls(incoming.server.host)
                    steps?.add(VerifyStep("STARTTLS", true, "Encrypted channel established"))
                }
                client.authenticate(email, credentials)
                steps?.add(VerifyStep("Incoming authentication", true, "Logged in as $email"))
                val session = ImapSession(transport, client)
                session.inbox()
                return session
            } catch (t: Throwable) {
                runCatching { transport.close() }
                throw t
            }
        }

        fun capabilitiesOf(client: ImapClient): Set<KnownCapability> {
            val caps = client.capabilitiesSnapshot()
            val granted = mutableSetOf(
                KnownCapability.MAIL_READ,
                KnownCapability.MAIL_SEARCH,
                KnownCapability.MAIL_FLAG,
                KnownCapability.MAIL_SENT_APPEND,
                KnownCapability.MAIL_DELETE_REMOTE
            )
            if (caps.any { it.equals("IDLE", true) }) granted += KnownCapability.MAIL_PUSH
            if (caps.any { it.equals("MOVE", true) }) granted += KnownCapability.MAIL_MOVE
            return granted
        }
    }
}
