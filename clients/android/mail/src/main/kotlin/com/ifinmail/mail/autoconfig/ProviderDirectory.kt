package com.ifinmail.mail.autoconfig

import com.ifinmail.mail.model.ConnectionProfile
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.ServerConfig

private data class ProviderEntry(
    val name: String,
    val domains: Set<String>,
    val imapHost: String?,
    val imapPort: Int = 993,
    val imapSecurity: ConnectionSecurity = ConnectionSecurity.SSL_TLS,
    val popHost: String? = null,
    val popPort: Int = 995,
    val smtpHost: String?,
    val smtpPort: Int,
    val smtpSecurity: ConnectionSecurity,
    val requiresAppPassword: Boolean = false,
    val unsupportedReason: String? = null
)

object ProviderDirectory : com.ifinmail.core.domain.port.AutoConfigSource {

    private val providers = listOf(
        ProviderEntry(
            name = "ifinsta Mail",
            domains = setOf("ifinsta.com"),
            imapHost = "mail.ifinsta.com",
            popHost = "mail.ifinsta.com",
            smtpHost = "mail.ifinsta.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS
        ),
        ProviderEntry(
            name = "ifinsta Mail",
            domains = setOf("ifinsta.online"),
            imapHost = "mail.ifinsta.online",
            popHost = "mail.ifinsta.online",
            smtpHost = "mail.ifinsta.online",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS
        ),
        ProviderEntry(
            name = "Gmail",
            domains = setOf("gmail.com", "googlemail.com"),
            imapHost = "imap.gmail.com",
            popHost = "pop.gmail.com",
            smtpHost = "smtp.gmail.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            requiresAppPassword = true
        ),
        ProviderEntry(
            name = "Outlook / Microsoft 365",
            domains = setOf("outlook.com", "hotmail.com", "live.com", "live.co.uk", "msn.com", "passport.com"),
            imapHost = "outlook.office365.com",
            popHost = "outlook.office365.com",
            smtpHost = "smtp-mail.outlook.com",
            smtpPort = 587,
            smtpSecurity = ConnectionSecurity.STARTTLS
        ),
        ProviderEntry(
            name = "Yahoo Mail",
            domains = setOf("yahoo.com", "yahoo.co.uk", "ymail.com", "rocketmail.com"),
            imapHost = "imap.mail.yahoo.com",
            popHost = "pop.mail.yahoo.com",
            smtpHost = "smtp.mail.yahoo.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            requiresAppPassword = true
        ),
        ProviderEntry(
            name = "iCloud Mail",
            domains = setOf("icloud.com", "me.com", "mac.com"),
            imapHost = "imap.mail.me.com",
            smtpHost = "smtp.mail.me.com",
            smtpPort = 587,
            smtpSecurity = ConnectionSecurity.STARTTLS
        ),
        ProviderEntry(
            name = "Zoho Mail",
            domains = setOf("zoho.com", "zohomail.com"),
            imapHost = "imap.zoho.com",
            popHost = "pop.zoho.com",
            smtpHost = "smtp.zoho.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            requiresAppPassword = true
        ),
        ProviderEntry(
            name = "Fastmail",
            domains = setOf("fastmail.com", "fastmail.fm"),
            imapHost = "imap.fastmail.com",
            popHost = "pop.fastmail.com",
            smtpHost = "smtp.fastmail.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            requiresAppPassword = true
        ),
        ProviderEntry(
            name = "GMX",
            domains = setOf("gmx.com", "gmx.de", "gmx.net"),
            imapHost = "imap.gmx.com",
            popHost = "pop.gmx.com",
            smtpHost = "mail.gmx.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS
        ),
        ProviderEntry(
            name = "Yandex Mail",
            domains = setOf("yandex.com", "yandex.ru"),
            imapHost = "imap.yandex.com",
            popHost = "pop.yandex.com",
            smtpHost = "smtp.yandex.com",
            smtpPort = 465,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            requiresAppPassword = true
        ),
        ProviderEntry(
            name = "Proton Mail",
            domains = setOf("proton.me", "protonmail.com", "pm.me"),
            imapHost = null,
            popHost = null,
            smtpHost = null,
            smtpPort = 0,
            smtpSecurity = ConnectionSecurity.SSL_TLS,
            unsupportedReason = "Proton Mail requires the Proton Mail Bridge desktop app; direct IMAP/SMTP is not available."
        )
    )

    override fun profilesFor(email: String): List<ConnectionProfile> {
        val domain = domainOf(email)
        val entry = domain?.let { d -> providers.firstOrNull { d in it.domains } }
        if (entry != null) {
            if (entry.unsupportedReason != null || entry.imapHost == null || entry.smtpHost == null) {
                return emptyList()
            }
            val profiles = mutableListOf<ConnectionProfile>()
            profiles += profile(entry.name, IncomingProtocol.IMAP, entry.imapHost, entry.imapPort, entry.imapSecurity, entry.smtpHost, entry.smtpPort, entry.smtpSecurity, noteFor(entry))
            if (entry.popHost != null) {
                profiles += profile(entry.name, IncomingProtocol.POP3, entry.popHost, entry.popPort, ConnectionSecurity.SSL_TLS, entry.smtpHost, entry.smtpPort, entry.smtpSecurity, noteFor(entry))
            }
            return profiles
        }
        return heuristicProfiles(email)
    }

    private fun heuristicProfiles(email: String): List<ConnectionProfile> {
        val domain = domainOf(email) ?: return emptyList()
        val incomingCandidates = listOf(
            Triple("imap.$domain", 993, ConnectionSecurity.SSL_TLS),
            Triple("mail.$domain", 993, ConnectionSecurity.SSL_TLS),
            Triple(domain, 143, ConnectionSecurity.STARTTLS)
        )
        val outgoingCandidates = listOf(
            Triple("smtp.$domain", 465, ConnectionSecurity.SSL_TLS),
            Triple("smtp.$domain", 587, ConnectionSecurity.STARTTLS),
            Triple("mail.$domain", 587, ConnectionSecurity.STARTTLS)
        )
        val out = outgoingCandidates.first()
        val profiles = mutableListOf<ConnectionProfile>()
        for ((index, candidate) in incomingCandidates.withIndex()) {
            val (host, port, security) = candidate
            val label = if (index == 0) "Custom server" else "Custom server (alt $index)"
            profiles += profile(label, IncomingProtocol.IMAP, host, port, security, out.first, out.second, out.third, note = "Unverified guess for $domain - edit if connection fails")
            profiles += profile(label, IncomingProtocol.POP3, host.replaceFirst("imap", "pop"), port.takeIf { security == ConnectionSecurity.SSL_TLS } ?: 110, security, out.first, out.second, out.third, note = "Unverified guess for $domain - edit if connection fails")
        }
        return profiles
    }

    private fun noteFor(entry: ProviderEntry): String? =
        if (entry.requiresAppPassword) {
            "${entry.name} requires an app password (enable 2-step verification, then generate one in account security settings) or an OAuth2 token."
        } else {
            null
        }

    private fun profile(
        label: String,
        protocol: IncomingProtocol,
        inHost: String,
        inPort: Int,
        inSecurity: ConnectionSecurity,
        smtpHost: String,
        smtpPort: Int,
        smtpSecurity: ConnectionSecurity,
        note: String?
    ) = ConnectionProfile(
        label = "$label · ${protocol.name}",
        incoming = IncomingConfig(protocol, ServerConfig(inHost, inPort, inSecurity)),
        outgoing = ServerConfig(smtpHost, smtpPort, smtpSecurity),
        note = note
    )

    internal fun domainOf(email: String): String? {
        val at = email.trim().lastIndexOf('@')
        if (at <= 0 || at == email.length - 1) return null
        return email.substring(at + 1).trim().lowercase()
    }
}
