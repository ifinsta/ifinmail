package com.ifinmail.update

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/** A response whose body is still on the wire. Always [close] it. */
class HttpStream(
    val status: Int,
    /** Bytes still to come in this response, or -1 when the server did not say. */
    val contentLength: Long,
    /** For a 206: the offset this body starts at, taken from `Content-Range`; otherwise 0. */
    val rangeStart: Long,
    val body: InputStream,
    private val onClose: () -> Unit
) : AutoCloseable {
    override fun close() {
        try {
            body.close()
        } finally {
            onClose()
        }
    }
}

/** The one thing the update logic needs from the network, so tests can use a real local server. */
interface UpdateHttp {
    /** GET [url]; [rangeStart] > 0 asks for the bytes from that offset on. */
    @Throws(IOException::class)
    fun open(url: String, rangeStart: Long = 0, userAgent: String = DEFAULT_USER_AGENT): HttpStream

    companion object {
        const val DEFAULT_USER_AGENT = "ifinmail-android-updater"
    }
}

/** [UpdateHttp] on `HttpURLConnection`: no dependency, honours the platform trust store. */
class JavaUpdateHttp(
    private val connectTimeoutMs: Int = 10_000,
    private val readTimeoutMs: Int = 20_000
) : UpdateHttp {
    override fun open(url: String, rangeStart: Long, userAgent: String): HttpStream {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = connectTimeoutMs
        connection.readTimeout = readTimeoutMs
        connection.instanceFollowRedirects = true
        connection.setRequestProperty("User-Agent", userAgent)
        connection.setRequestProperty("Accept-Encoding", "identity") // exact bytes, so ranges line up
        if (rangeStart > 0) connection.setRequestProperty("Range", "bytes=$rangeStart-")
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else (connection.errorStream ?: emptyStream())
        val start = if (status == 206) parseRangeStart(connection.getHeaderField("Content-Range")) else 0L
        return HttpStream(
            status = status,
            contentLength = connection.getHeaderField("Content-Length")?.toLongOrNull() ?: -1L,
            rangeStart = start,
            body = stream,
            onClose = { connection.disconnect() }
        )
    }

    // InputStream.nullInputStream() needs API 33; this app supports API 24.
    private fun emptyStream(): InputStream = ByteArrayInputStream(ByteArray(0))

    private fun parseRangeStart(header: String?): Long {
        // "bytes 1000-1999/2000"
        val match = Regex("""bytes\s+(\d+)-""").find(header.orEmpty()) ?: return 0L
        return match.groupValues[1].toLongOrNull() ?: 0L
    }
}
