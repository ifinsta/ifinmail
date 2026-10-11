package com.ifinmail.mail.discovery

import com.ifinmail.core.domain.port.AutoConfigSource
import com.ifinmail.mail.model.ConnectionProfile
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.ServerConfig
import java.io.StringReader
import java.net.HttpURLConnection
import java.net.URL
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Element
import org.xml.sax.InputSource

class DiscoveryAutoConfigSource(
    private val timeoutMs: Int = 4000,
    private val fetcher: (String) -> String? = ::httpGet
) : AutoConfigSource {

    override fun profilesFor(email: String): List<ConnectionProfile> {
        val domain = email.trim().substringAfterLast('@', "").lowercase()
        if (domain.isBlank() || !domain.contains('.')) return emptyList()
        val urls = listOf(
            "https://$domain/.well-known/autoconfig/mail/config-v1.1.xml",
            "https://autoconfig.$domain/mail/config-v1.1.xml",
            "https://autoconfig.thunderbird.net/v1.1/$domain"
        )
        for (url in urls) {
            val body = runCatching { fetcher(url) }.getOrNull() ?: continue
            val profiles = parseConfigXml(body, domain)
            if (profiles.isNotEmpty()) return profiles
        }
        return emptyList()
    }

    /**
     * Parses Mozilla autoconfig (config-v1.1.xml): `<incomingServer type="imap|pop3">` and
     * `<outgoingServer type="smtp">` with `hostname`, `port`, `socketType` (SSL | STARTTLS | plain)
     * and `authentication`. Servers that would send the password unencrypted or need another
     * authentication scheme are skipped; the first usable outgoing server is paired with each
     * incoming one. Malformed XML (or any DOCTYPE) yields no profiles.
     */
    internal fun parseConfigXml(xml: String, domain: String): List<ConnectionProfile> {
        val provider = parseProvider(xml) ?: return emptyList()
        val outgoing = elements(provider, "outgoingServer")
            .filter { it.getAttribute("type").equals("smtp", true) }
            .mapNotNull { serverOf(it, domain, IncomingProtocol.IMAP, outgoing = true) }
            .firstOrNull() ?: return emptyList()
        val profiles = mutableListOf<ConnectionProfile>()
        for (protocol in listOf(IncomingProtocol.IMAP, IncomingProtocol.POP3)) {
            for (element in elements(provider, "incomingServer")) {
                if (!element.getAttribute("type").equals(protocol.name, true)) continue
                val server = serverOf(element, domain, protocol, outgoing = false) ?: continue
                val username = childText(element, "username")
                val note = if (username != null && !username.equals("%EMAILADDRESS%", true)) {
                    "The server asks for the user name '$username'; the app signs in with the full address."
                } else {
                    null
                }
                profiles += ConnectionProfile(
                    label = "Discovered \u00b7 ${protocol.name}",
                    incoming = IncomingConfig(protocol, server),
                    outgoing = outgoing,
                    note = listOfNotNull("Discovered via $domain autoconfiguration", note).joinToString(" ")
                )
            }
        }
        return profiles
    }

    private fun parseProvider(xml: String): Element? = try {
        val factory = DocumentBuilderFactory.newInstance()
        // Untrusted input: no DTDs, no external entities.
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
        factory.setFeature("http://xml.org/sax/features/external-general-entities", false)
        factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false)
        factory.isXIncludeAware = false
        factory.isExpandEntityReferences = false
        val document = factory.newDocumentBuilder().parse(InputSource(StringReader(xml)))
        document.getElementsByTagName("emailProvider").item(0) as? Element
    } catch (e: Exception) {
        null
    }

    private fun elements(parent: Element, tag: String): List<Element> {
        val nodes = parent.getElementsByTagName(tag)
        return (0 until nodes.length).mapNotNull { nodes.item(it) as? Element }
    }

    private fun childText(parent: Element, tag: String): String? =
        elements(parent, tag).firstOrNull()?.textContent?.trim()?.takeIf { it.isNotEmpty() }

    private fun serverOf(element: Element, domain: String, protocol: IncomingProtocol, outgoing: Boolean): ServerConfig? {
        val host = childText(element, "hostname")
            ?.replace("%EMAILDOMAIN%", domain, ignoreCase = true)
            ?.takeIf { it.isNotBlank() && !it.contains('%') }
            ?: return null
        val security = when (childText(element, "socketType")?.lowercase()) {
            "ssl", "ssl/tls", "tls" -> ConnectionSecurity.SSL_TLS
            "starttls" -> ConnectionSecurity.STARTTLS
            else -> return null // "plain" or missing: never send a password in the clear
        }
        val authentication = childText(element, "authentication")?.lowercase()
        if (authentication != null && authentication !in PASSWORD_AUTH) return null
        val port = childText(element, "port")?.toIntOrNull()?.takeIf { it in 1..65535 }
            ?: defaultPort(protocol, security, outgoing)
        return ServerConfig(host, port, security)
    }

    private fun defaultPort(protocol: IncomingProtocol, security: ConnectionSecurity, outgoing: Boolean): Int {
        val implicitTls = security == ConnectionSecurity.SSL_TLS
        return when {
            outgoing -> if (implicitTls) 465 else 587
            protocol == IncomingProtocol.IMAP -> if (implicitTls) 993 else 143
            else -> if (implicitTls) 995 else 110
        }
    }

    companion object {
        private val PASSWORD_AUTH = setOf("password-cleartext", "password-encrypted", "plain", "secure")

        internal fun httpGet(url: String): String? {
            val connection = URL(url).openConnection() as HttpURLConnection
            return try {
                connection.connectTimeout = 4000
                connection.readTimeout = 4000
                connection.setRequestProperty("User-Agent", "ifinmail/0.1 autoconfig")
                if (connection.responseCode != 200) return null
                connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            } catch (e: Exception) {
                null
            } finally {
                connection.disconnect()
            }
        }
    }
}

class CompositeAutoConfigSource(
    private vararg val sources: AutoConfigSource
) : AutoConfigSource {

    override fun profilesFor(email: String): List<ConnectionProfile> {
        for (source in sources) {
            val profiles = runCatching { source.profilesFor(email) }.getOrNull().orEmpty()
            if (profiles.isNotEmpty()) return profiles
        }
        return emptyList()
    }
}
