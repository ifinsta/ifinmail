package com.ifinmail.mail

import com.ifinmail.mail.mime.MimeComposer
import com.ifinmail.mail.mime.MimeParser
import com.ifinmail.mail.model.EmailAddress
import com.ifinmail.mail.model.OutgoingDraft
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class MimeTest {

    @Test
    fun `parses simple plain text message`() {
        val raw = ("From: Alice Example <alice@example.com>\r\n" +
            "To: bob@example.org\r\n" +
            "Subject: Greetings =?UTF-8?B?SMOpbGxv?=\r\n" +
            "Date: Tue, 08 Jul 2026 09:15:00 +0200\r\n" +
            "Message-ID: <m1@example.com>\r\n" +
            "Content-Type: text/plain; charset=utf-8\r\n" +
            "Content-Transfer-Encoding: quoted-printable\r\n" +
            "\r\n" +
            "H=C3=A9llo Bob,\r\nhow are you?\r\n").toByteArray(Charsets.ISO_8859_1)

        val parsed = MimeParser.parseMessage(raw)
        assertEquals("Greetings Héllo", parsed.subject)
        assertEquals("alice@example.com", parsed.from?.address)
        assertEquals("Alice Example", parsed.from?.name)
        assertNotNull(parsed.dateEpochMs)
        assertTrue(parsed.plainText!!.startsWith("Héllo Bob"))
        assertEquals("<m1@example.com>", parsed.messageId)
    }

    @Test
    fun `parses multipart with html and attachment`() {
        val boundary = "----=_Part_42"
        val body = buildString {
            append("From: x@example.com\r\n")
            append("Subject: Report\r\n")
            append("MIME-Version: 1.0\r\n")
            append("Content-Type: multipart/mixed; boundary=\"$boundary\"\r\n")
            append("\r\n")
            append("preamble to ignore\r\n")
            append("--$boundary\r\n")
            append("Content-Type: text/plain; charset=us-ascii\r\n\r\n")
            append("See attached.\r\n")
            append("--$boundary\r\n")
            append("Content-Type: text/html; charset=us-ascii\r\n\r\n")
            append("<p>See <b>attached</b>.</p>\r\n")
            append("--$boundary\r\n")
            append("Content-Type: application/pdf; name=\"report.pdf\"\r\n")
            append("Content-Disposition: attachment; filename=\"report.pdf\"\r\n")
            append("Content-Transfer-Encoding: base64\r\n\r\n")
            append("JVBERi0xLjQK\r\n")
            append("--$boundary--\r\n")
            append("epilogue\r\n")
        }
        val parsed = MimeParser.parseMessage(body.toByteArray(Charsets.ISO_8859_1))
        assertEquals("See attached.", parsed.plainText)
        assertTrue(parsed.htmlText!!.contains("attached"))
        assertEquals(listOf("report.pdf"), parsed.attachmentNames)
        assertTrue(parsed.attachmentNames.isNotEmpty())
    }

    @Test
    fun `nested multipart alternative picks both texts`() {
        val b1 = "outer"
        val b2 = "inner"
        val raw = buildString {
            append("Subject: alt\r\nContent-Type: multipart/mixed; boundary=$b1\r\n\r\n")
            append("--$b1\r\n")
            append("Content-Type: multipart/alternative; boundary=$b2\r\n\r\n")
            append("--$b2\r\nContent-Type: text/plain\r\n\r\nplain body\r\n")
            append("--$b2\r\nContent-Type: text/html\r\n\r\n<b>html body</b>\r\n")
            append("--$b2--\r\n")
            append("--$b1--\r\n")
        }
        val parsed = MimeParser.parseMessage(raw.toByteArray())
        assertEquals("plain body", parsed.plainText)
        assertEquals("<b>html body</b>", parsed.htmlText)
    }

    @Test
    fun `rfc 5322 date parsing handles common formats`() {
        val ms = MimeParser.parseRfc5322Date("Tue, 08 Jul 2026 09:15:00 +0200")
        assertNotNull(ms)
        val expectedUtc = MimeParser.parseRfc5322Date("Tue, 08 Jul 2026 07:15:00 +0000")
        assertEquals(expectedUtc, ms)
    }

    @Test
    fun `header parameter parser reads quoted values`() {
        val params = MimeParser.parseHeaderParameters("""multipart/mixed; boundary="a b\""; charset=UTF-8""")
        assertEquals("a b\"", params["boundary"])
        assertEquals("UTF-8", params["charset"])
    }

    @Test
    fun `compose then parse roundtrip`() {
        val draft = OutgoingDraft(
            to = listOf(EmailAddress(name = "Bob", address = "bob@example.org")),
            cc = listOf(EmailAddress(address = "carol@example.net")),
            subject = "Réponse : héllo",
            bodyText = "Line one ünïcode\r\nLine two = fine"
        )
        val bytes = MimeComposer.compose(EmailAddress(name = "Sender", address = "me@ifinmail.local"), draft)
        val parsed = MimeParser.parseMessage(bytes)
        assertEquals(draft.subject, parsed.subject)
        assertEquals("bob@example.org", parsed.to.first().address)
        assertEquals("carol@example.net", parsed.cc.first().address)
        assertEquals("me@ifinmail.local", parsed.from?.address)
        assertEquals("Line one ünïcode\nLine two = fine", parsed.plainText)
    }
}
