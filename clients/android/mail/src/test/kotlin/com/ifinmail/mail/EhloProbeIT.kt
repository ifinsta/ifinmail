package com.ifinmail.mail

import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.smtp.SmtpClient
import com.ifinmail.mail.transport.JvmSocketTransport
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import kotlin.test.Test

private typealias JvmSocketTransportForProbe = JvmSocketTransport

class EhloProbeIT {

    @Test
    fun probeEhlo465() = runBlocking {
        assumeTrue(System.getenv("IFINMAIL_LIVE") == "1")
        val t = JvmSocketTransportForProbe()
        val client = SmtpClient(t) { line -> println("RAW> $line") }
        client.connect(System.getenv("IFINMAIL_HOST") ?: "mail.ifinsta.com", 465, ConnectionSecurity.SSL_TLS)
        println("=== EHLO on 465 done ===")
        client.close()
    }

    @Test
    fun probeEhlo587() = runBlocking {
        assumeTrue(System.getenv("IFINMAIL_LIVE") == "1")
        val t = JvmSocketTransportForProbe()
        val logs = mutableListOf<String>()
        val client = SmtpClient(t) { line -> logs += line; println("RAW> $line") }
        client.connect(System.getenv("IFINMAIL_HOST") ?: "mail.ifinsta.com", 587, ConnectionSecurity.STARTTLS)
        println("=== EHLO after STARTTLS on 587 done ===")
        client.close()
    }
}
