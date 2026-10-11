package com.ifinmail.mail

import com.ifinmail.mail.adapter.CalDavProbeAdapter
import com.ifinmail.mail.adapter.CardDavProbeAdapter
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlinx.coroutines.runBlocking
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A tiny local DAV server that behaves like ifinmail's: well-known redirects to /dav/, which answers PROPFIND. */
class DavProbeTest {
    private val servers = mutableListOf<HttpServer>()
    private val seen = mutableListOf<String>() // "METHOD path auth?"

    private fun server(handler: (HttpExchange) -> Unit): HttpServer {
        val s = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        s.createContext("/") { ex ->
            seen += "${ex.requestMethod} ${ex.requestURI.path} ${ex.requestHeaders.getFirst("Authorization") != null}"
            handler(ex)
            ex.close()
        }
        s.start()
        servers += s
        return s
    }

    private fun HttpServer.base() = "http://127.0.0.1:${address.port}"

    private fun HttpExchange.reply(code: Int, body: String = "") {
        val bytes = body.toByteArray()
        sendResponseHeaders(code, if (bytes.isEmpty()) -1 else bytes.size.toLong())
        if (bytes.isNotEmpty()) responseBody.use { it.write(bytes) }
    }

    private val multistatus = """<multistatus xmlns="DAV:"><response><href>/dav/</href><propstat><prop>
        <current-user-principal><href>/dav/sam%40example.test/</href></current-user-principal></prop></propstat></response></multistatus>"""

    @AfterTest
    fun stop() = servers.forEach { it.stop(0) }

    private fun ifinmailLike() = server { ex ->
        when (ex.requestURI.path) {
            "/.well-known/caldav", "/.well-known/carddav" -> {
                ex.responseHeaders.add("Location", "/dav/")
                ex.reply(301)
            }
            "/dav/" -> if (ex.requestHeaders.getFirst("Authorization") == null) ex.reply(401) else ex.reply(207, multistatus)
            else -> ex.reply(404)
        }
    }

    @Test
    fun `follows the well-known redirect with the same method and finds the principal`() = runBlocking {
        val s = ifinmailLike()
        val calendar = CalDavProbeAdapter(s.base(), "sam@example.test", "pw").probe()
        assertTrue(calendar.reachable, calendar.detail)
        assertTrue(calendar.detail.contains("/dav/sam%40example.test/"), calendar.detail)
        assertEquals(listOf("PROPFIND /.well-known/caldav true", "PROPFIND /dav/ true"), seen)
        assertTrue(CardDavProbeAdapter(s.base(), "sam@example.test", "pw").probe().reachable)
    }

    @Test
    fun `falls back to the dav root when there is no well-known path`() = runBlocking {
        val s = server { ex -> if (ex.requestURI.path == "/dav/") ex.reply(207, multistatus) else ex.reply(404) }
        assertTrue(CalDavProbeAdapter(s.base(), "a@b.test", "pw").probe().reachable)
        assertEquals("PROPFIND /.well-known/caldav true", seen.first())
    }

    @Test
    fun `a server that rejects the credentials is still reported as present`() = runBlocking {
        val s = server { it.reply(401) }
        val result = CalDavProbeAdapter(s.base(), "a@b.test", "bad").probe()
        assertTrue(result.reachable)
        assertTrue(result.detail.contains("rejected"))
    }

    @Test
    fun `no dav server means not reachable with the reason`() = runBlocking {
        val s = server { it.reply(404) }
        val result = CardDavProbeAdapter(s.base(), "a@b.test", "pw").probe()
        assertFalse(result.reachable)
        assertTrue(result.detail.contains("404"))
        val down = CardDavProbeAdapter("http://127.0.0.1:1", "a@b.test", "pw", timeoutMs = 500).probe()
        assertFalse(down.reachable)
    }

    @Test
    fun `credentials are not sent to a host we were redirected to`() = runBlocking {
        val other = server { ex -> ex.reply(207, multistatus) }
        val first = server { ex ->
            ex.responseHeaders.add("Location", "http://localhost:${other.address.port}/dav/")
            ex.reply(302)
        }
        CalDavProbeAdapter(first.base(), "a@b.test", "secret").probe()
        assertTrue(seen.any { it.startsWith("PROPFIND /.well-known/caldav true") })
        assertTrue(seen.contains("PROPFIND /dav/ false"), "second host must not get the Authorization header: $seen")
    }

    @Test
    fun `credentials are never sent over plain http to a remote host`() = runBlocking {
        val result = CalDavProbeAdapter("http://mail.example.invalid", "a@b.test", "secret").probe()
        assertFalse(result.reachable)
        assertTrue(result.detail.contains("without TLS"), result.detail)
        assertNull(seen.firstOrNull())
    }
}
