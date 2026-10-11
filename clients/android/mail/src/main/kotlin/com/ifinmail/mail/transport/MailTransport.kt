package com.ifinmail.mail.transport

import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.EOFException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import javax.net.SocketFactory
import javax.net.ssl.SSLParameters
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface MailTransport : AutoCloseable {
    val isConnected: Boolean

    suspend fun connect(host: String, port: Int, ssl: Boolean, connectTimeoutMs: Long = 15_000)

    suspend fun startTls(host: String)

    suspend fun readLine(timeoutMs: Long): String?

    suspend fun readBytes(count: Int): ByteArray

    suspend fun write(data: ByteArray)

    fun setTimeout(timeoutMs: Long)
}

class JvmSocketTransport(private val pinnedSha256: String? = null) : MailTransport {

    private var socket: Socket? = null
    private var input: InputStream? = null
    private var output: OutputStream? = null

    override val isConnected: Boolean
        get() = socket?.let { it.isConnected && !it.isClosed } == true

    override suspend fun connect(host: String, port: Int, ssl: Boolean, connectTimeoutMs: Long) =
        withContext(Dispatchers.IO) {
            closeQuietly()
            val raw: Socket = if (ssl) {
                TlsTrust.socketFactory(host, pinnedSha256).createSocket()
            } else {
                SocketFactory.getDefault().createSocket()
            }
            try {
                raw.tcpNoDelay = true
                raw.connect(InetSocketAddress(host, port), connectTimeoutMs.toInt())
                configure(raw)
                if (ssl) {
                    enableHostnameVerification(raw as SSLSocket)
                    // Handshake now so an untrusted certificate is reported here, not as a read error.
                    raw.startHandshake()
                }
                socket = raw
                input = BufferedInputStream(raw.getInputStream(), BUFFER)
                output = BufferedOutputStream(raw.getOutputStream(), BUFFER)
            } catch (t: Throwable) {
                runCatching { raw.close() }
                throw t
            }
        }

    override suspend fun startTls(host: String) = withContext(Dispatchers.IO) {
        val current = socket ?: error("Not connected")
        val wrapped = TlsTrust.socketFactory(host, pinnedSha256).createSocket(current, host, current.port, false) as SSLSocket
        enableHostnameVerification(wrapped)
        wrapped.startHandshake()
        configure(wrapped)
        socket = wrapped
        input = BufferedInputStream(wrapped.getInputStream(), BUFFER)
        output = BufferedOutputStream(wrapped.getOutputStream(), BUFFER)
    }

    override suspend fun readLine(timeoutMs: Long): String? = withContext(Dispatchers.IO) {
        val stream = input ?: error("Not connected")
        setTimeout(timeoutMs)
        val sb = StringBuilder(128)
        while (true) {
            val b = try {
                stream.read()
            } catch (e: SocketTimeoutException) {
                return@withContext null
            } catch (e: IOException) {
                throw EOFException("Connection closed while reading line").initCause(e)
            }
            if (b < 0) throw EOFException("Connection closed while reading line")
            if (b == LF) break
            if (b != '\r'.code) sb.append(b.toChar())
        }
        sb.toString()
    }

    override suspend fun readBytes(count: Int): ByteArray = withContext(Dispatchers.IO) {
        val stream = input ?: error("Not connected")
        val out = ByteArray(count)
        var read = 0
        while (read < count) {
            val n = stream.read(out, read, count - read)
            if (n < 0) throw EOFException("Connection closed expecting $count bytes, got $read")
            read += n
        }
        out
    }

    override suspend fun write(data: ByteArray) = withContext(Dispatchers.IO) {
        val stream = output ?: error("Not connected")
        stream.write(data)
        stream.flush()
    }

    override fun setTimeout(timeoutMs: Long) {
        runCatching { socket?.soTimeout = timeoutMs.toInt().coerceAtLeast(1) }
    }

    override fun close() {
        closeQuietly()
    }

    private fun configure(s: Socket) {
        s.tcpNoDelay = true
        s.soTimeout = DEFAULT_TIMEOUT_MS.toInt()
    }

    private fun enableHostnameVerification(ssl: SSLSocket) {
        val params: SSLParameters = ssl.sslParameters
        params.endpointIdentificationAlgorithm = "HTTPS"
        ssl.sslParameters = params
    }

    private fun closeQuietly() {
        runCatching { input?.close() }
        runCatching { output?.close() }
        runCatching { socket?.close() }
        input = null
        output = null
        socket = null
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS: Long = 30_000L
        private const val BUFFER = 32 * 1024
        private const val LF = '\n'.code

        internal fun tlsFactory(): SSLSocketFactory = SSLSocketFactory.getDefault() as SSLSocketFactory
    }
}
