package com.ifinmail.mail

import com.ifinmail.mail.discovery.DiscoveryAutoConfigSource
import com.ifinmail.mail.imap.ImapClient
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.IncomingProtocol
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The XML below is exactly what the ifinmail backend serves (backend/apps/mail/views). */
class DiscoveryAutoConfigSourceTest {

    private val ifinmailXml = """<?xml version="1.0" encoding="UTF-8"?>
<clientConfig version="1.1">
    <emailProvider id="example.test">
        <domain>example.test</domain>
        <displayName>example.test Mail</displayName>
        <incomingServer type="imap">
            <hostname>mail.example.test</hostname>
            <port>993</port>
            <socketType>SSL</socketType>
            <authentication>password-cleartext</authentication>
            <username>%EMAILADDRESS%</username>
        </incomingServer>
        <outgoingServer type="smtp">
            <hostname>mail.example.test</hostname>
            <port>587</port>
            <socketType>STARTTLS</socketType>
            <authentication>password-cleartext</authentication>
            <username>%EMAILADDRESS%</username>
        </outgoingServer>
    </emailProvider>
</clientConfig>"""

    private val source = DiscoveryAutoConfigSource(fetcher = { null })

    @Test
    fun `the ifinmail backend's autoconfig is understood`() {
        val profiles = source.parseConfigXml(ifinmailXml, "example.test")
        assertEquals(1, profiles.size)
        val profile = profiles.single()
        assertEquals(IncomingProtocol.IMAP, profile.incoming.protocol)
        assertEquals("mail.example.test", profile.incoming.server.host)
        assertEquals(993, profile.incoming.server.port)
        assertEquals(ConnectionSecurity.SSL_TLS, profile.incoming.server.security)
        assertEquals("mail.example.test", profile.outgoing.host)
        assertEquals(587, profile.outgoing.port)
        assertEquals(ConnectionSecurity.STARTTLS, profile.outgoing.security)
    }

    @Test
    fun `imap and pop3 are both offered, imap first, with the first usable smtp server`() {
        val xml = """<clientConfig><emailProvider id="x.test">
            <incomingServer type="pop3"><hostname>pop.%EMAILDOMAIN%</hostname><port>995</port><socketType>SSL</socketType></incomingServer>
            <incomingServer type="imap"><hostname>imap.%EMAILDOMAIN%</hostname><socketType>STARTTLS</socketType></incomingServer>
            <outgoingServer type="smtp"><hostname>relay</hostname><socketType>plain</socketType></outgoingServer>
            <outgoingServer type="smtp"><hostname>smtp.%EMAILDOMAIN%</hostname><socketType>SSL</socketType></outgoingServer>
            </emailProvider></clientConfig>"""
        val profiles = source.parseConfigXml(xml, "x.test")
        assertEquals(listOf(IncomingProtocol.IMAP, IncomingProtocol.POP3), profiles.map { it.incoming.protocol })
        assertEquals("imap.x.test", profiles[0].incoming.server.host)
        assertEquals(143, profiles[0].incoming.server.port) // default for STARTTLS
        assertEquals("smtp.x.test", profiles[0].outgoing.host)
        assertEquals(465, profiles[0].outgoing.port) // default for implicit TLS
    }

    @Test
    fun `servers that would send the password unprotected or need another scheme are skipped`() {
        val plainIncoming = """<clientConfig><emailProvider id="x"><incomingServer type="imap"><hostname>h</hostname><socketType>plain</socketType></incomingServer>
            <outgoingServer type="smtp"><hostname>h</hostname><socketType>SSL</socketType></outgoingServer></emailProvider></clientConfig>"""
        assertTrue(source.parseConfigXml(plainIncoming, "x").isEmpty())
        val oauthOnly = """<clientConfig><emailProvider id="x"><incomingServer type="imap"><hostname>h</hostname><socketType>SSL</socketType><authentication>OAuth2</authentication></incomingServer>
            <outgoingServer type="smtp"><hostname>h</hostname><socketType>SSL</socketType></outgoingServer></emailProvider></clientConfig>"""
        assertTrue(source.parseConfigXml(oauthOnly, "x").isEmpty())
    }

    @Test
    fun `a server that signs in with the local part is flagged in the note`() {
        val xml = ifinmailXml.replaceFirst("<username>%EMAILADDRESS%</username>", "<username>%EMAILLOCALPART%</username>")
        val note = source.parseConfigXml(xml, "example.test").single().note
        assertTrue(note!!.contains("%EMAILLOCALPART%"))
    }

    @Test
    fun `hostile or broken xml yields nothing`() {
        assertTrue(source.parseConfigXml("not xml at all", "x").isEmpty())
        assertTrue(source.parseConfigXml("", "x").isEmpty())
        val xxe = """<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/passwd">]>
            <clientConfig><emailProvider id="x"><incomingServer type="imap"><hostname>&e;</hostname><socketType>SSL</socketType></incomingServer>
            <outgoingServer type="smtp"><hostname>h</hostname><socketType>SSL</socketType></outgoingServer></emailProvider></clientConfig>"""
        assertTrue(source.parseConfigXml(xxe, "x").isEmpty())
    }

    @Test
    fun `discovery asks the domain first and stops at the first usable answer`() {
        val asked = mutableListOf<String>()
        val discovery = DiscoveryAutoConfigSource(fetcher = { url ->
            asked += url
            if (url.startsWith("https://autoconfig.example.test/")) ifinmailXml else null
        })
        val profiles = discovery.profilesFor("Sam@Example.Test")
        assertEquals(1, profiles.size)
        assertEquals(
            listOf(
                "https://example.test/.well-known/autoconfig/mail/config-v1.1.xml",
                "https://autoconfig.example.test/mail/config-v1.1.xml"
            ),
            asked
        )
    }

    @Test
    fun `no answers means no profiles so the caller can fall back`() {
        assertTrue(DiscoveryAutoConfigSource(fetcher = { null }).profilesFor("a@example.test").isEmpty())
        assertTrue(DiscoveryAutoConfigSource(fetcher = { null }).profilesFor("not-an-address").isEmpty())
    }

    @Test
    fun `capabilities announced in the login response replace the pre-login list`() = runBlocking {
        val transport = FakeTransport()
        transport.feedLine("* OK ready")
        transport.feedLine("* CAPABILITY IMAP4rev1 SASL-IR AUTH=PLAIN IDLE")
        transport.feedLine("IFM0001 OK done")
        transport.feedLine("IFM0002 OK [CAPABILITY IMAP4rev1 SASL-IR IDLE MOVE UIDPLUS SPECIAL-USE] Logged in")
        val client = ImapClient(transport)
        client.connect("h", 993, ConnectionSecurity.SSL_TLS)
        assertNull(client.capabilitiesSnapshot().firstOrNull { it == "MOVE" })
        client.login("u@x", "p")
        assertTrue("MOVE" in client.capabilitiesSnapshot())
        assertTrue("AUTH=PLAIN" !in client.capabilitiesSnapshot())
    }
}
