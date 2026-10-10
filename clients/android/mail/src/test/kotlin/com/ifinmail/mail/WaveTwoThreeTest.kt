package com.ifinmail.mail

import com.ifinmail.core.domain.draft.SmartReplyEngine
import com.ifinmail.core.domain.export.MboxExportService
import com.ifinmail.core.domain.model.Account
import com.ifinmail.core.domain.model.ConnectionSecurity
import com.ifinmail.core.domain.model.Credentials
import com.ifinmail.core.domain.model.IncomingConfig
import com.ifinmail.core.domain.model.IncomingProtocol
import com.ifinmail.core.domain.model.ServerConfig
import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.ocr.LocalOcrEngine
import com.ifinmail.core.domain.vault.InMemoryVaultService
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class WaveTwoThreeTest {

    private fun message(subject: String, snippet: String = "content") = StoredMessage(
        id = "m1", accountId = "a1", folder = "INBOX", uid = 1,
        subject = subject, fromName = "Alice", fromAddress = "alice@x.com",
        toCsv = "", ccCsv = "", dateEpochMs = 100L, snippet = snippet,
        sizeBytes = 0, read = false, flagged = false, hasAttachments = false
    )

    private fun account() = Account(
        id = "a1", email = "me@x.com", displayName = "Me",
        incoming = IncomingConfig(IncomingProtocol.IMAP, ServerConfig("h", 993, ConnectionSecurity.SSL_TLS)),
        outgoing = ServerConfig("s", 465, ConnectionSecurity.SSL_TLS),
        credentials = Credentials(password = "p")
    )

    @Test
    fun `smart reply suggests meeting-aware replies`() = runBlocking {
        val engine = SmartReplyEngine()
        val replies = engine.suggestions(account(), message("Meeting invite for Friday"))
        assertTrue(replies.any { it.label == "Can do" })
        assertTrue(replies.any { it.label == "Can't make it" })
    }

    @Test
    fun `smart reply suggests financial replies`() = runBlocking {
        val engine = SmartReplyEngine()
        val replies = engine.suggestions(account(), message("Overdue invoice"))
        assertTrue(replies.any { it.label == "Paid" })
        assertTrue(replies.any { it.label == "Question" })
    }

    @Test
    fun `smart reply always provides got-it fallback`() = runBlocking {
        val engine = SmartReplyEngine()
        val replies = engine.suggestions(account(), message("Just saying hi"))
        assertTrue(replies.any { it.label == "Got it" })
    }

    @Test
    fun `vault stores bytes and resolves before expiry`() = runBlocking {
        var now = 1000L
        val vault = InMemoryVaultService(clock = { now })
        val ref = vault.store("a1", "report.pdf", "application/pdf", byteArrayOf(1, 2, 3), 10_000)
        assertNotNull(ref)
        assertTrue(vault.resolve(ref)!!.contentEquals(byteArrayOf(1, 2, 3)))
        vault.purgeExpired()
        assertNotNull(vault.resolve(ref))
        Unit
    }

    @Test
    fun `vault expires after ttl`() = runBlocking {
        var now = 1000L
        val vault = InMemoryVaultService(clock = { now })
        val ref = vault.store("a1", "secret.txt", "text/plain", "secret".toByteArray(), 5_000)
        assertNotNull(vault.resolve(ref))
        now = 7_000L
        vault.purgeExpired()
        assertNull(vault.resolve(ref))
    }

    @Test
    fun `ocr extracts embedded text`() = runBlocking {
        val engine = LocalOcrEngine()
        val text = engine.extractText("hello scanned contract 12345".toByteArray(), "application/pdf")
        assertEquals("hello scanned contract 12345", text)
    }

    @Test
    fun `ocr returns empty for non-text`() = runBlocking {
        val engine = LocalOcrEngine()
        val text = engine.extractText(byteArrayOf(0, 255.toByte(), 1, 2, 0), "image/png")
        assertEquals("", text)
    }

    @Test
    fun `mbox export includes headers and dot-stuffs from lines`() = runBlocking {
        val msg = message("Report").copy(fromName = "Alice", fromAddress = "alice@x.com", toCsv = "bob@y.com", bodyText = "Hello\nFrom line should be escaped")
        val mbox = MboxExportService.exportMbox("a1", listOf(msg))
        assertTrue(mbox.contains("From: Alice <alice@x.com>"))
        assertTrue(mbox.contains("To: bob@y.com"))
        assertTrue(mbox.contains("Subject: Report"))
        assertTrue(mbox.contains(">From line should be escaped"))
        assertTrue(mbox.startsWith("From MAILER-DAEMON"))
    }

    @Test
    fun `vcard export is well-formed`() = runBlocking {
        val vcard = MboxExportService.exportVCard("Alice Example", "alice@x.com")
        assertTrue(vcard.contains("BEGIN:VCARD"))
        assertTrue(vcard.contains("FN:Alice Example"))
        assertTrue(vcard.contains("EMAIL;TYPE=INTERNET:alice@x.com"))
        assertTrue(vcard.contains("END:VCARD"))
    }
}
