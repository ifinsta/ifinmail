package com.ifinmail.mail

import com.ifinmail.mail.autoconfig.ProviderDirectory
import com.ifinmail.mail.model.IncomingProtocol
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ProviderDirectoryTest {

    @Test
    fun `gmail resolves to imap pop3 and smtp profiles`() {
        val profiles = ProviderDirectory.profilesFor("user@gmail.com")
        assertEquals(2, profiles.size)
        val imap = profiles.first { it.incoming.protocol == IncomingProtocol.IMAP }
        assertEquals("imap.gmail.com", imap.incoming.server.host)
        assertEquals(993, imap.incoming.server.port)
        assertEquals("smtp.gmail.com", imap.outgoing.host)
        assertTrue(imap.note!!.contains("app password"))
    }

    @Test
    fun `outlook uses starttls for smtp`() {
        val profile = ProviderDirectory.profilesFor("someone@hotmail.com")
            .first { it.incoming.protocol == IncomingProtocol.IMAP }
        assertEquals("outlook.office365.com", profile.incoming.server.host)
        assertEquals(587, profile.outgoing.port)
    }

    @Test
    fun `proton is flagged unsupported`() {
        assertTrue(ProviderDirectory.profilesFor("user@proton.me").isEmpty())
    }

    @Test
    fun `unknown domain produces heuristic guesses`() {
        val profiles = ProviderDirectory.profilesFor("me@mycompany.example")
        assertTrue(profiles.isNotEmpty())
        assertTrue(profiles.first().incoming.server.host.contains("mycompany.example"))
    }

    @Test
    fun `domain extraction is case insensitive`() {
        assertEquals("GMAIL.COM".lowercase(), ProviderDirectory.domainOf("x@GMAIL.COM"))
    }
}
