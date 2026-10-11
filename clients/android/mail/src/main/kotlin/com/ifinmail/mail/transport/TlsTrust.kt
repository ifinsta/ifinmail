package com.ifinmail.mail.transport

import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** The server's certificate is not trusted by the system; carries what the person needs to decide. */
class UntrustedCertificateException(
    val host: String,
    val sha256: String,
    val subject: String,
    cause: Throwable? = null
) : CertificateException("$host presented an untrusted certificate ($subject, SHA-256 $sha256)", cause)

internal fun sha256Hex(certificate: X509Certificate): String =
    MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }

/** Accepts "AB:CD..." or "abcd..." and returns lowercase hex without separators. */
internal fun normalizeFingerprint(value: String): String =
    value.lowercase().filter { it in '0'..'9' || it in 'a'..'f' }

/**
 * System trust first. A certificate the system rejects is accepted only if it is exactly the one
 * the person pinned; otherwise [UntrustedCertificateException] reports its fingerprint so the app can ask.
 * Host name checking still happens afterwards (the connection sets endpointIdentificationAlgorithm).
 */
internal class PinningTrustManager(
    private val system: X509TrustManager,
    private val host: String,
    pinnedSha256: String?
) : X509TrustManager {
    private val pin = pinnedSha256?.let(::normalizeFingerprint)?.takeIf { it.isNotEmpty() }

    override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) =
        system.checkClientTrusted(chain, authType)

    override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) {
        try {
            system.checkServerTrusted(chain, authType)
        } catch (e: CertificateException) {
            val leaf = chain.firstOrNull() ?: throw e
            val fingerprint = sha256Hex(leaf)
            if (pin != null && pin == fingerprint) return
            throw UntrustedCertificateException(host, fingerprint, leaf.subjectX500Principal.name, e)
        }
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = system.acceptedIssuers
}

internal object TlsTrust {
    fun socketFactory(host: String, pinnedSha256: String?): SSLSocketFactory {
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        factory.init(null as KeyStore?)
        val system = factory.trustManagers.filterIsInstance<X509TrustManager>().first()
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf<TrustManager>(PinningTrustManager(system, host, pinnedSha256)), null)
        return context.socketFactory
    }
}
