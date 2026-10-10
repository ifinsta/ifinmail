package com.ifinmail.mail

import com.ifinmail.mail.engine.MailEngine
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.model.IncomingConfig
import com.ifinmail.mail.model.IncomingProtocol
import com.ifinmail.mail.model.ServerConfig
import kotlinx.coroutines.runBlocking
import okio.Path.Companion.toPath
import okio.fakefilesystem.FakeFileSystem
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class EngineStoreTest {

    @Test
    fun `account persists across engine restarts`() = runBlocking {
        val fs = FakeFileSystem()
        val dir = "/data".toPath()
        fs.createDirectories(dir)

        val engine = MailEngine(dir, fileSystem = fs)
        engine.initialize()
        engine.addAccount(
            email = "me@test.org",
            displayName = "Me",
            incoming = IncomingConfig(IncomingProtocol.IMAP, ServerConfig("imap.test.org", 993, ConnectionSecurity.SSL_TLS)),
            outgoing = ServerConfig("smtp.test.org", 465, ConnectionSecurity.SSL_TLS),
            credentials = Credentials(password = "secret"),
            verified = true
        )
        assertEquals(1, engine.accounts.value.size)

        val restarted = MailEngine(dir, fileSystem = fs)
        restarted.initialize()
        assertEquals(1, restarted.accounts.value.size)
        assertEquals("me@test.org", restarted.accounts.value[0].email)
        assertTrue(restarted.messagesByAccount.value.isEmpty())
    }

    @Test
    fun `duplicate accounts are rejected`() = runBlocking {
        val fs = FakeFileSystem()
        val dir = "/data".toPath()
        fs.createDirectories(dir)
        val engine = MailEngine(dir, fileSystem = fs)
        engine.initialize()
        val incoming = IncomingConfig(IncomingProtocol.POP3, ServerConfig("pop.test.org", 995, ConnectionSecurity.SSL_TLS))
        val outgoing = ServerConfig("smtp.test.org", 465, ConnectionSecurity.SSL_TLS)
        engine.addAccount("dup@test.org", "", incoming, outgoing, Credentials(password = "x"), true)
        var failed = false
        try {
            engine.addAccount("DUP@TEST.ORG", "", incoming, outgoing, Credentials(password = "y"), true)
        } catch (e: Exception) {
            failed = true
        }
        assertTrue(failed)
    }
}
