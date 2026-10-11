package com.ifinmail.mail

import com.ifinmail.core.domain.error.MailError
import com.ifinmail.mail.model.toMailError
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.PinningTrustManager
import com.ifinmail.mail.transport.UntrustedCertificateException
import com.ifinmail.mail.transport.sha256Hex
import java.security.KeyStore
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.X509TrustManager
import kotlinx.coroutines.runBlocking
import kotlin.concurrent.thread
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

/**
 * First boot: a new ifinmail server presents a temporary self-signed certificate until Let's Encrypt
 * replaces it. The client must refuse it by default, report what it saw, and accept exactly that
 * certificate once the person has confirmed its fingerprint.
 */
class TlsPinningTest {
    private val keyStore = KeyStore.getInstance("PKCS12").also { store ->
        javaClass.getResourceAsStream("/selfsigned-localhost.p12")!!.use { store.load(it, "changeit".toCharArray()) }
    }
    private val certificate = keyStore.getCertificate("t") as X509Certificate
    private val fingerprint = sha256Hex(certificate)
    private val servers = mutableListOf<SSLServerSocket>()

    @AfterTest
    fun stop() = servers.forEach { runCatching { it.close() } }

    /** A TLS server that greets with a POP3-style banner, like Dovecot does. */
    private fun greetingServer(): Int {
        val keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
        keys.init(keyStore, "changeit".toCharArray())
        val context = SSLContext.getInstance("TLS").apply { init(keys.keyManagers, null, null) }
        val server = context.serverSocketFactory.createServerSocket(0) as SSLServerSocket
        servers += server
        thread(isDaemon = true) {
            while (!server.isClosed) {
                runCatching {
                    server.accept().use { s ->
                        s.getOutputStream().apply { write("+OK hello\r\n".toByteArray()); flush() }
                        Thread.sleep(100)
                    }
                }
            }
        }
        return server.localPort
    }

    private fun untrusted(block: () -> Unit): UntrustedCertificateException {
        val failure = assertFailsWith<Throwable> { block() }
        return generateSequence(failure) { it.cause }.filterIsInstance<UntrustedCertificateException>().first()
    }

    @Test
    fun selfSignedCertificateIsRefusedAndDescribed() {
        val port = greetingServer()
        val error = untrusted { runBlocking { JvmSocketTransport().connect("localhost", port, true, 5000) } }
        assertEquals(fingerprint, error.sha256)
        assertEquals("localhost", error.host)
        assertTrue(error.subject.contains("CN=localhost"))
    }

    @Test
    fun refusalMapsToAStructuredMailError() {
        val port = greetingServer()
        val failure = assertFailsWith<Throwable> {
            runBlocking { JvmSocketTransport().connect("localhost", port, true, 5000) }
        }
        val mapped = failure.toMailError()
        assertIs<MailError.CertificateUntrusted>(mapped)
        assertEquals(fingerprint, mapped.sha256)
    }

    @Test
    fun pinnedCertificateIsAccepted_inAnyFingerprintNotation() {
        val port = greetingServer()
        val colonSeparated = fingerprint.uppercase().chunked(2).joinToString(":")
        for (pin in listOf(fingerprint, colonSeparated)) {
            val transport = JvmSocketTransport(pin)
            runBlocking {
                transport.connect("localhost", port, true, 5000)
                assertEquals("+OK hello", transport.readLine(5000))
            }
            transport.close()
        }
    }

    @Test
    fun aDifferentPinDoesNotHelp() {
        val port = greetingServer()
        val error = untrusted {
            runBlocking { JvmSocketTransport("00".repeat(32)).connect("localhost", port, true, 5000) }
        }
        assertEquals(fingerprint, error.sha256)
    }

    @Test
    fun aPinNeverOverridesHostnameChecking() {
        val port = greetingServer()
        // 127.0.0.2 is not in the certificate's names even though the certificate itself is pinned.
        val failure = assertFailsWith<Throwable> {
            runBlocking { JvmSocketTransport(fingerprint).connect("127.0.0.2", port, true, 5000) }
        }
        assertTrue(generateSequence(failure) { it.cause }.none { it is UntrustedCertificateException })
    }

    @Test
    fun trustedCertificatesAreAcceptedWhateverThePin() {
        val systemAccepts = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) = Unit
            override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) = Unit
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        // The certificate has been replaced by a real one: a stale pin must not get in the way.
        PinningTrustManager(systemAccepts, "mail.example.test", "00".repeat(32))
            .checkServerTrusted(arrayOf(certificate), "ECDSA")
    }

    @Test
    fun untrustedChainWithoutPinReportsFingerprint() {
        val systemRejects = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) = Unit
            override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) =
                throw CertificateException("no trusted authority")
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val error = assertFailsWith<UntrustedCertificateException> {
            PinningTrustManager(systemRejects, "mail.example.test", null).checkServerTrusted(arrayOf(certificate), "ECDSA")
        }
        assertEquals(fingerprint, error.sha256)
    }
}
