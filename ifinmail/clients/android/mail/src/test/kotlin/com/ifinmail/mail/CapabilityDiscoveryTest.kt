package com.ifinmail.mail

import com.ifinmail.core.domain.capability.KnownCapability
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.model.ConnectionSecurity
import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.model.IncomingConfig
import com.ifinmail.core.domain.model.IncomingProtocol
import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.core.domain.model.ServerConfig
import com.ifinmail.mail.adapter.ImapAccessAdapter
import com.ifinmail.mail.imap.ImapClient
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CapabilityDiscoveryTest {

    private fun incoming() = IncomingConfig(
        IncomingProtocol.IMAP,
        ServerConfig("imap.test", 993, ConnectionSecurity.SSL_TLS)
    )

    private fun feedHappyPath(transport: FakeTransport, capabilityLine: String) {
        transport.feedLine("* OK IMAP4rev1 ready")
        transport.feedLine("* CAPABILITY $capabilityLine")
        transport.feedLine("IFM0001 OK cap")
        transport.feedLine("IFM0002 OK auth")
        transport.feedLine("""* LIST (\HasNoChildren) "." INBOX""")
        transport.feedLine("IFM0003 OK list")
        transport.feedLine("* 0 EXISTS")
        transport.feedLine("* OK [UIDVALIDITY 42]")
        transport.feedLine("IFM0004 OK selected")
    }

    @Test
    fun `idle and move capabilities are discovered from server capability line`() = runBlocking {
        val transport = FakeTransport()
        feedHappyPath(transport, "IMAP4rev1 IDLE MOVE AUTH=PLAIN")

        val adapter = ImapAccessAdapter { transport }
        val outcome = adapter.probe("u@test", incoming(), Credentials(password = "p"))

        assertTrue(outcome.success, outcome.errorDetail ?: "probe failed")
        assertTrue(KnownCapability.MAIL_PUSH in outcome.capabilities)
        assertTrue(KnownCapability.MAIL_MOVE in outcome.capabilities)
        assertTrue(KnownCapability.MAIL_READ in outcome.capabilities)
        assertTrue(KnownCapability.MAIL_SEARCH in outcome.capabilities)
    }

    @Test
    fun `server without idle has no push capability`() = runBlocking {
        val transport = FakeTransport()
        feedHappyPath(transport, "IMAP4rev1 AUTH=PLAIN")

        val adapter = ImapAccessAdapter { transport }
        val outcome = adapter.probe("u@test", incoming(), Credentials(password = "p"))

        assertTrue(outcome.success, outcome.errorDetail ?: "probe failed")
        assertEquals(false, KnownCapability.MAIL_PUSH in outcome.capabilities)
    }

    @Test
    fun `failed authentication reports authentication required`() = runBlocking {
        val transport = FakeTransport()
        transport.feedLine("* OK ready")
        transport.feedLine("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
        transport.feedLine("IFM0001 OK cap")
        transport.feedLine("IFM0002 NO [AUTHENTICATIONFAILED] bad password")

        val adapter = ImapAccessAdapter { transport }
        val outcome = adapter.probe("u@test", incoming(), Credentials(password = "wrong"))

        assertEquals(false, outcome.success)
        assertTrue(outcome.capabilities.isEmpty())
        assertEquals(MailError.AuthenticationRequired, outcome.error)
    }

    @Test
    fun `special use flags resolve mailbox roles`() {
        val sent = ImapClient.FolderEntry("Gesendet", setOf("\\Sent", "\\HasNoChildren"))
        val drafts = ImapClient.FolderEntry("Entwuerfe", setOf("\\Drafts"))
        val junk = ImapClient.FolderEntry("Spamverdacht", setOf("\\Junk"))
        assertEquals(MailboxRole.SENT, sent.specialUseRole())
        assertEquals(MailboxRole.DRAFTS, drafts.specialUseRole())
        assertEquals(MailboxRole.SPAM, junk.specialUseRole())
        assertNull(ImapClient.FolderEntry("Random", emptySet()).specialUseRole())
    }
}
