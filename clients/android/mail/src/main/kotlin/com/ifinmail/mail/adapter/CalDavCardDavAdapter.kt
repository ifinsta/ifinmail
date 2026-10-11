package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.port.CalendarCapability
import com.ifinmail.core.domain.port.CalendarProbeResult
import com.ifinmail.core.domain.port.ContactCapability
import com.ifinmail.core.domain.port.ContactProbeResult
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.MailTransport
import java.net.URI
import java.net.URL
import java.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val PRINCIPAL_REQUEST =
    "<?xml version=\"1.0\"?><d:propfind xmlns:d=\"DAV:\"><d:prop><d:current-user-principal/></d:prop></d:propfind>"
private const val MAX_REDIRECTS = 5

/**
 * Looks for a DAV server the standard way (RFC 6764): the well-known path first, then the `/dav/` root
 * that ifinmail serves, following redirects by hand (a redirected PROPFIND must stay a PROPFIND).
 * 207/200 means a principal answered; 401 means a server is there but wants other credentials.
 * Credentials are only sent over TLS (or to this machine) and never to a host we were redirected to.
 *
 * PROPFIND is not a method HttpURLConnection (JDK or Android) will send, so this speaks the small
 * amount of HTTP/1.1 it needs over the same TLS transport the mail protocols use.
 */
internal suspend fun davProbe(
    baseHost: String,
    wellKnown: String,
    email: String,
    password: String,
    timeoutMs: Int
): Pair<Boolean, String> {
    val origin = if (baseHost.startsWith("http")) baseHost.trimEnd('/') else "https://${baseHost.trimEnd('/')}"
    var detail = "DAV endpoint not found at $origin"
    for (path in listOf("/.well-known/$wellKnown", "/dav/")) {
        val outcome = probeOnce(origin + path, email, password, timeoutMs)
        if (outcome.first) return outcome
        if (outcome.second.isNotEmpty()) detail = outcome.second
    }
    return false to detail
}

private class DavReply(val status: Int, val headers: Map<String, String>, val body: String)

private suspend fun propfind(url: URL, authorization: String?, timeoutMs: Int): DavReply {
    val tls = url.protocol == "https"
    val port = if (url.port > 0) url.port else if (tls) 443 else 80
    val body = PRINCIPAL_REQUEST.toByteArray()
    val hostHeader = if (url.port > 0) "${url.host}:${url.port}" else url.host
    val path = (url.path.ifEmpty { "/" }) + (url.query?.let { "?$it" } ?: "")
    val head = buildString {
        append("PROPFIND $path HTTP/1.1\r\nHost: $hostHeader\r\nDepth: 0\r\n")
        append("Content-Type: application/xml; charset=utf-8\r\nContent-Length: ${body.size}\r\n")
        append("Connection: close\r\nUser-Agent: ifinmail/0.1 dav-probe\r\n")
        if (authorization != null) append("Authorization: $authorization\r\n")
        append("\r\n")
    }
    JvmSocketTransport().use { transport ->
        transport.connect(url.host, port, tls, timeoutMs.toLong())
        transport.write(head.toByteArray(Charsets.ISO_8859_1) + body)
        val statusLine = transport.readLine(timeoutMs.toLong()) ?: throw java.io.IOException("No response")
        val status = statusLine.split(' ').getOrNull(1)?.toIntOrNull()
            ?: throw java.io.IOException("Not an HTTP response: ${statusLine.take(60)}")
        val headers = LinkedHashMap<String, String>()
        while (true) {
            val line = transport.readLine(timeoutMs.toLong()) ?: break
            if (line.isEmpty()) break
            val colon = line.indexOf(':')
            if (colon > 0) headers[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
        }
        val text = when {
            status in 301..308 || status == 401 -> ""
            headers["transfer-encoding"]?.contains("chunked", true) == true -> readChunked(transport, timeoutMs)
            headers["content-length"]?.toIntOrNull() != null ->
                String(transport.readBytes(headers.getValue("content-length").toInt().coerceAtMost(MAX_BODY)), Charsets.UTF_8)
            else -> ""
        }
        return DavReply(status, headers, text)
    }
}

private const val MAX_BODY = 256 * 1024

private suspend fun readChunked(transport: MailTransport, timeoutMs: Int): String {
    val out = StringBuilder()
    while (out.length < MAX_BODY) {
        val size = transport.readLine(timeoutMs.toLong())?.substringBefore(';')?.trim()?.toIntOrNull(16) ?: break
        if (size == 0) break
        out.append(String(transport.readBytes(size), Charsets.UTF_8))
        transport.readLine(timeoutMs.toLong()) // CRLF after the chunk
    }
    return out.toString()
}

private suspend fun probeOnce(startUrl: String, email: String, password: String, timeoutMs: Int): Pair<Boolean, String> {
    var url = URI(startUrl).toURL()
    val originHost = url.host
    var detail = ""
    repeat(MAX_REDIRECTS + 1) {
        val secure = url.protocol == "https" || url.host == "localhost" || url.host == "127.0.0.1"
        if (!secure) return false to "Refusing to send credentials to ${url.host} without TLS"
        val authorization = if (url.host == originHost) {
            "Basic " + Base64.getEncoder().encodeToString("$email:$password".toByteArray())
        } else {
            null
        }
        val reply = try {
            propfind(url, authorization, timeoutMs)
        } catch (e: Exception) {
            return false to "DAV endpoint unreachable: ${e.message}"
        }
        when (reply.status) {
            200, 207 -> {
                val principal = Regex("current-user-principal[^>]*>\\s*<[^>]*href[^>]*>([^<]+)<").find(reply.body)
                    ?.groupValues?.get(1)?.trim()
                return true to (if (principal != null) "DAV server answered; principal $principal" else "DAV server answered")
            }
            301, 302, 307, 308 -> {
                val location = reply.headers["location"] ?: return false to "Redirect without a location"
                url = url.toURI().resolve(location).toURL()
                detail = "Redirected to $url"
            }
            401 -> return true to "DAV server reachable; it rejected these credentials"
            else -> return false to "DAV endpoint responded ${reply.status}"
        }
    }
    return false to "Too many redirects ($detail)"
}

class CalDavProbeAdapter(
    private val baseHost: String,
    private val email: String,
    private val password: String,
    private val timeoutMs: Int = 5000
) : CalendarCapability {

    override suspend fun probe(): CalendarProbeResult = withContext(Dispatchers.IO) {
        val (reachable, detail) = davProbe(baseHost, "caldav", email, password, timeoutMs)
        CalendarProbeResult(reachable, detail)
    }
}

class CardDavProbeAdapter(
    private val baseHost: String,
    private val email: String,
    private val password: String,
    private val timeoutMs: Int = 5000
) : ContactCapability {

    override suspend fun probe(): ContactProbeResult = withContext(Dispatchers.IO) {
        val (reachable, detail) = davProbe(baseHost, "carddav", email, password, timeoutMs)
        ContactProbeResult(reachable, detail)
    }
}
