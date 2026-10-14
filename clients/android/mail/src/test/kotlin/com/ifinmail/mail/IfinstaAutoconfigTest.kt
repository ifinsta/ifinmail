package com.ifinmail.mail

import com.ifinmail.mail.autoconfig.ProviderDirectory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class IfinstaAutoconfigTest {

    @Test
    fun `ifinsta accounts autoconfigure to mail host`() {
        val profiles = ProviderDirectory.profilesFor("test1@ifinsta.com")
        assertEquals(2, profiles.size)
        val imap = profiles.first { it.label.endsWith("IMAP") }
        assertEquals("mail.ifinsta.com", imap.incoming.server.host)
        assertEquals(993, imap.incoming.server.port)
        assertEquals("mail.ifinsta.com", imap.outgoing.host)
        assertEquals(465, imap.outgoing.port)
    }

    @Test
    fun `ifinsta online accounts autoconfigure to the online mail host`() {
        val profiles = ProviderDirectory.profilesFor("douglas@ifinsta.online")
        assertEquals(2, profiles.size)
        val imap = profiles.first { it.label.endsWith("IMAP") }
        assertEquals("mail.ifinsta.online", imap.incoming.server.host)
        assertEquals(993, imap.incoming.server.port)
        assertEquals("mail.ifinsta.online", imap.outgoing.host)
        assertEquals(465, imap.outgoing.port)
        // Must not fall through to the unverified heuristic guesses (imap.<domain>, smtp.<domain>).
        assertTrue(profiles.none { it.note?.startsWith("Unverified guess") == true })
    }
}
