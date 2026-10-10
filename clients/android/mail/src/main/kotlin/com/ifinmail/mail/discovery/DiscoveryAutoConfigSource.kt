package com.ifinmail.mail.discovery

import com.ifinmail.core.domain.port.AutoConfigSource
import com.ifinmail.mail.model.ConnectionProfile
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.ServerConfig
import java.net.HttpURLConnection
import java.net.URL

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

    internal fun parseConfigXml(xml: String, domain: String): List<ConnectionProfile> {
        val profiles = mutableListOf<ConnectionProfile>()
        val incomingBlocks = Regex("<(incomingType|emailIncomingType)>([\\s\\S]*?)</\\1>").findAll(xml)
        val outgoingBlock = Regex("<outgoingType>([\\s\\S]*?)</outgoingType>").findAll(xml).firstOrNull()
        for (match in incomingBlocks) {
            val block = match.groupValues[2]
            val type = tagValue(block, "type")?.lowercase() ?: continue
            val protocol = when (type) {
                "imap" -> IncomingProtocol.IMAP
                "pop3" -> IncomingProtocol.POP3
                else -> continue
            }
            val host = tagValue(block, "hostname") ?: continue
            if (host == "%EMAILDOMAIN%" || host.isBlank()) continue
            val port = tagValue(block, "port")?.toIntOrNull() ?: defaultPort(protocol)
            val security = when (tagValue(block, "socketType")?.lowercase()) {
                "ssl", "ssl/tls" -> ConnectionSecurity.SSL_TLS
                "starttls" -> ConnectionSecurity.STARTTLS
                else -> ConnectionSecurity.SSL_TLS
            }
            val smtp = outgoingBlock?.let {
                val outHost = tagValue(it.groupValues[1], "hostname")
                val outPort = tagValue(it.groupValues[1], "port")?.toIntOrNull() ?: 465
                val outSocket = tagValue(it.groupValues[1], "socketType")?.lowercase()
                if (outHost != null && !outHost.contains('%')) {
                    ServerConfig(
                        outHost,
                        outPort,
                        when (outSocket) {
                            "starttls" -> ConnectionSecurity.STARTTLS
                            "none" -> ConnectionSecurity.NONE
                            else -> ConnectionSecurity.SSL_TLS
                        }
                    )
                } else null
            } ?: ServerConfig("mail.$domain", 465, ConnectionSecurity.SSL_TLS)
            profiles += ConnectionProfile(
                label = "Discovered · ${protocol.name}",
                incoming = IncomingConfig(protocol, ServerConfig(host, port, security)),
                outgoing = smtp,
                note = "Discovered via $domain autoconfiguration"
            )
        }
        return profiles
    }

    private fun tagValue(block: String, tag: String): String? =
        Regex("<$tag>([^<]*)</$tag>").find(block)?.groupValues?.get(1)?.trim()

    private fun defaultPort(protocol: IncomingProtocol): Int =
        if (protocol == IncomingProtocol.IMAP) 993 else 995

    companion object {
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
