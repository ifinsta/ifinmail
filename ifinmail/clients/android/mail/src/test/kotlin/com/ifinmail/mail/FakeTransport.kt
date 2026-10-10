package com.ifinmail.mail

import com.ifinmail.mail.transport.MailTransport
import java.io.EOFException
import java.nio.charset.StandardCharsets

class FakeTransport : MailTransport {

    private val pending = StringBuilder()
    private val written = StringBuilder()
    var connected = false
        private set
    var tlsUpgraded = false
        private set

    fun feedLine(line: String) {
        pending.append(line).append("\r\n")
    }

    fun feedRaw(raw: String) {
        pending.append(raw)
    }

    fun exhaust() {
        pending.setLength(0)
    }

    override val isConnected: Boolean get() = connected

    override suspend fun connect(host: String, port: Int, ssl: Boolean, connectTimeoutMs: Long) {
        connected = true
    }

    override suspend fun startTls(host: String) {
        tlsUpgraded = true
    }

    override suspend fun readLine(timeoutMs: Long): String? {
        while (pending.indexOf('\n') < 0) {
            throw EOFException("Script exhausted waiting for a line")
        }
        val index = pending.indexOf('\n')
        val line = pending.substring(0, index).trimEnd('\r')
        pending.delete(0, index + 1)
        return line
    }

    override suspend fun readBytes(count: Int): ByteArray {
        if (pending.length < count) throw EOFException("Script exhausted expecting $count bytes, have ${pending.length}")
        val chunk = pending.substring(0, count)
        pending.delete(0, count)
        return chunk.toByteArray(StandardCharsets.ISO_8859_1)
    }

    override suspend fun write(data: ByteArray) {
        written.append(String(data, StandardCharsets.ISO_8859_1))
    }

    override fun setTimeout(timeoutMs: Long) {}

    override fun close() {
        connected = false
    }

    fun writtenText(): String = written.toString()

    fun writtenLines(): List<String> = written.toString().split("\r\n").filter { it.isNotEmpty() }
}
