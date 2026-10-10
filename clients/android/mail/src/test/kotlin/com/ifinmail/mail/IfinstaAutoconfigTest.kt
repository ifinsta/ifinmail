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
}
