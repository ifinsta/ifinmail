package com.ifinmail.mail

import com.ifinmail.mail.imap.ImapClient
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.pop3.Pop3Client
import com.ifinmail.mail.smtp.SmtpClient
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private fun <T> blocking(block: suspend () -> T): T = runBlocking { block() }

class ImapClientTest {

    @Test
    fun `connect capability login select fetch with literals`() = blocking {
        val transport = FakeTransport()
        val headerLiteral = "From: alice@example.com\r\nSubject: Hi\r\n\r\n"
        val bodyLiteral =
            "Content-Type: text/plain; charset=us-ascii\r\n\r\nHello literal \"quoted\" \\ backslash"
        transport.feedLine("* OK IMAP4rev1 ready")
        transport.feedLine("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
        transport.feedLine("IFM0001 OK CAPABILITY completed")
        transport.feedLine("IFM0002 OK [CAPABILITY IMAP4rev1] Logged in")
        transport.feedLine("* FLAGS (\\Answered \\Flagged \\Seen)")
        transport.feedLine("* 2 EXISTS")
        transport.feedLine("* OK [UIDVALIDITY 1234567890] UIDs valid")
        transport.feedLine("IFM0003 OK [READ-WRITE] SELECT completed")
        transport.feedLine(
            "* 2 FETCH (UID 44 FLAGS (\\Seen) INTERNALDATE \"08-Jul-2026 09:15:00 +0000\" RFC822.SIZE ${bodyLiteral.length} BODY[HEADER] {${headerLiteral.length}}"
        )
        transport.feedRaw(headerLiteral)
        transport.feedLine(")")
        transport.feedLine("IFM0004 OK fetched")
        transport.feedLine(
            "* 2 FETCH (UID 44 BODY[] {${bodyLiteral.length}}"
        )
        transport.feedRaw(bodyLiteral)
        transport.feedLine(")")
        transport.feedLine("IFM0005 OK fetched")

        val client = ImapClient(transport)
        client.connect("imap.test", 993, ConnectionSecurity.SSL_TLS)
        client.login("user@test", "secret")
        val select = client.select("INBOX")
        assertEquals(2, select.exists)
        assertEquals(1234567890L, select.uidValidity)

        val summaries = client.fetchSummaries(1)
        assertEquals(1, summaries.size)
        assertEquals(44L, summaries[0].uid)
        assertTrue(summaries[0].flags.contains("\\Seen"))
        assertEquals(bodyLiteral.length.toLong(), summaries[0].sizeBytes)
        val headerText = String(summaries[0].headerBytes!!, Charsets.ISO_8859_1)
        assertTrue(headerText.startsWith("From: alice@example.com"))

        val body = String(client.fetchBody(44), Charsets.ISO_8859_1)
        assertTrue(body.contains("Hello literal \"quoted\" \\ backslash"))
    }

    @Test
    fun `literal spanning multiple script lines is reassembled`() = blocking {
        val transport = FakeTransport()
        val longBody = ("x".repeat(30) + "\r\n") .repeat(10)
        transport.feedLine("* OK ready")
        transport.feedLine("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
        transport.feedLine("IFM0001 OK cap done")
        transport.feedLine("IFM0002 OK logged in")
        transport.feedLine("* 1 EXISTS")
        transport.feedLine("* OK [UIDVALIDITY 7]")
        transport.feedLine("IFM0003 OK selected")
        transport.feedLine("* 1 FETCH (UID 9 BODY[] {${longBody.length}}")
        transport.feedRaw(longBody.take(120))
        transport.feedRaw(longBody.drop(120))
        transport.feedLine(")")
        transport.feedLine("IFM0004 OK fetched")

        val client = ImapClient(transport)
        client.connect("imap.test", 993, ConnectionSecurity.SSL_TLS)
        client.login("u", "p")
        client.select("INBOX")
        val body = String(client.fetchBody(9), Charsets.ISO_8859_1)
        assertEquals(longBody, body)
    }
}

class Pop3ClientTest {

    @Test
    fun `uidl and retr parse correctly`() = blocking {
        val transport = FakeTransport()
        transport.feedLine("+OK POP3 ready")
        transport.feedLine("+OK user accepted")
        transport.feedLine("+OK password accepted")
        transport.feedLine("+OK unique-id listing follows")
        transport.feedLine("1 abc123")
        transport.feedLine("2 def456")
        transport.feedLine(".")
        transport.feedLine("+OK 100 octets")
        transport.feedLine("Subject: stuffed")
        transport.feedLine("")
        transport.feedLine("..leading dot line")
        transport.feedLine(".")
        transport.feedLine("+OK")

        val client = Pop3Client(transport)
        client.connect("pop.test", 995, ConnectionSecurity.SSL_TLS)
        client.authenticate("user", "pass")
        val uidl = client.uidlMap()
        assertEquals(mapOf(1 to "abc123", 2 to "def456"), uidl)

        val message = String(client.retr(2), Charsets.ISO_8859_1)
        assertTrue(message.contains("Subject: stuffed"))
        assertTrue(message.contains("\r\n.leading dot line\r\n"))

        client.noop()
        assertTrue(transport.writtenLines().contains("NOOP"))
    }
}

class SmtpClientTest {

    @Test
    fun `ehlo auth send flow`() = blocking {
        val transport = FakeTransport()
        transport.feedLine("220 mail.test ESMTP ready")
        transport.feedLine("250-mail.test greets you")
        transport.feedLine("250-PIPELINING")
        transport.feedLine("250-AUTH PLAIN LOGIN XOAUTH2")
        transport.feedLine("250 SIZE 35882577")
        transport.feedLine("235 Authentication successful")
        transport.feedLine("250 OK")
        transport.feedLine("250 OK")
        transport.feedLine("354 End data with <CR><LF>.<CR><LF>")
        transport.feedLine("250 2.0.0 Queued")

        val client = SmtpClient(transport)
        client.connect("smtp.test", 587, ConnectionSecurity.NONE)
        client.authPlain("user@test", "pass")

        val data = "Subject: hi\r\n\r\nbody\r\n".toByteArray()
        client.sendMail("user@test", listOf("dest@test"), data)

        val lines = transport.writtenLines()
        assertTrue(lines.contains("EHLO ifinmail.local"))
        assertTrue(lines.first { it.startsWith("AUTH PLAIN") }.length > "AUTH PLAIN ".length)
        assertTrue(lines.contains("MAIL FROM:<user@test>"))
        assertTrue(lines.contains("RCPT TO:<dest@test>"))
        assertTrue(lines.contains("DATA"))
        assertTrue(lines.none { it == ".leading" })
    }

    @Test
    fun `dot stuffing escapes leading dots`() {
        val stuffed = SmtpClient.dotStuff(".leading\r\ndotless\r\n..double".toByteArray()).decodeToString()
        assertTrue(stuffed.contains("..leading"))
        assertTrue(stuffed.contains("\r\ndotless\r\n"))
        assertTrue(stuffed.contains("...double"))
        assertTrue(stuffed.endsWith("\r\n"))
    }
}
