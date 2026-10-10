package com.ifinmail.mail

import com.ifinmail.mail.imap.ImapClient
import com.ifinmail.mail.mime.MimeComposer
import com.ifinmail.mail.mime.MimeParser
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.EmailAddress
import com.ifinmail.mail.model.OutgoingDraft
import com.ifinmail.mail.pop3.Pop3Client
import com.ifinmail.mail.smtp.SmtpClient
import com.ifinmail.mail.transport.JvmSocketTransport
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class LiveServerIT {

    private val host = System.getenv("IFINMAIL_HOST") ?: "mail.ifinsta.com"
    private val user1 = System.getenv("IFINMAIL_USER1") ?: "test1@ifinsta.com"
    private val user2 = System.getenv("IFINMAIL_USER2") ?: "test2@ifinsta.com"
    private val password = System.getenv("IFINMAIL_PASS") ?: "Kenya@12"

    private fun enabled() = System.getenv("IFINMAIL_LIVE") == "1"

    private fun transport() = JvmSocketTransport()

    @Test
    fun imapLoginFoldersFetchBothAccounts() = runBlocking {
        assumeTrue(enabled())
        for (user in listOf(user1, user2)) {
            transport().use { t ->
                val client = ImapClient(t)
                client.connect(host, 993, ConnectionSecurity.SSL_TLS)
                client.login(user, password)
                val folders = client.listFolders()
                assertTrue(
                    folders.any { it.contains("INBOX", ignoreCase = true) },
                    "INBOX listed for $user: $folders"
                )
                client.select("INBOX")
                val summaries = client.fetchSummaries(1)
                println("IMAP[$user]: folders=$folders summaries=${summaries.size}")
                client.close()
            }
        }
    }

    @Test
    fun pop3LoginAndList() = runBlocking {
        assumeTrue(enabled())
        for (user in listOf(user1, user2)) {
            transport().use { t ->
                val client = Pop3Client(t)
                client.connect(host, 995, ConnectionSecurity.SSL_TLS)
                client.authenticate(user, password)
                val stat = client.stat()
                val uidl = client.uidlMap()
                println("POP3[$user]: ${stat.first} messages, ${uidl.size} uidls")
                assertEquals(stat.first, uidl.size)
                client.close()
            }
        }
    }

    @Test
    fun smtpAuthAcceptedForBothAccounts() = runBlocking {
        assumeTrue(enabled())
        for (user in listOf(user1, user2)) {
            transport().use { t ->
                val client = SmtpClient(t)
                client.connect(host, 465, ConnectionSecurity.SSL_TLS)
                client.authenticate(user, password, oauthAccessToken = null)
                println("SMTP[$user]: authenticated OK")
                client.close()
            }
        }
    }

    @Test
    fun endToEndSendFromUser1ToUser2ThenFetchAndCleanup() = runBlocking {
        assumeTrue(enabled())
        val token = "ifinmail-e2e-" + System.currentTimeMillis()

        transport().use { sendTransport ->
            val smtp = SmtpClient(sendTransport)
            smtp.connect(host, 465, ConnectionSecurity.SSL_TLS)
            smtp.authenticate(user1, password, oauthAccessToken = null)
            val mime = MimeComposer.compose(
                from = EmailAddress(name = "ifinmail E2E", address = user1),
                draft = OutgoingDraft(
                    to = listOf(EmailAddress(address = user2)),
                    subject = token,
                    bodyText = "Live end-to-end validation body for $token."
                )
            )
            smtp.sendMail(user1, listOf(user2), mime)
            smtp.close()
        }
        println("E2E: sent $token")

        var parsedSubject: String? = null
        var attempts = 0
        transport().use { recvTransport ->
            val imap = ImapClient(recvTransport)
            imap.connect(host, 993, ConnectionSecurity.SSL_TLS)
            imap.login(user2, password)
            while (parsedSubject == null && attempts < 15) {
                delay(2000)
                attempts += 1
                imap.select("INBOX")
                val summaries = imap.fetchSummaries(1)
                val match = summaries.firstOrNull { s ->
                    s.headerBytes?.let { h ->
                        MimeParser.parseMessage(h).subject.contains(token)
                    } == true
                }
                if (match != null) {
                    val fullBytes = imap.fetchBody(match.uid)
                    val parsed = MimeParser.parseMessage(fullBytes)
                    parsedSubject = parsed.subject
                    assertEquals(token, parsed.subject)
                    assertTrue(parsed.plainText!!.contains(token))
                    imap.storeFlags(match.uid, addFlags = setOf("\\Deleted"))
                    imap.expunge()
                    println("E2E: received and cleaned up after $attempts poll(s)")
                }
            }
            imap.close()
        }
        assertEquals(token, parsedSubject, "Message should arrive at $user2 INBOX within timeout")
    }
}
