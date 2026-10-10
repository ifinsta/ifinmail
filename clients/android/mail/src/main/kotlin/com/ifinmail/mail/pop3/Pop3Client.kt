package com.ifinmail.mail.pop3

import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.MailTransport
import java.nio.charset.StandardCharsets
import java.util.Base64

data class Pop3MessageRef(
    val number: Int,
    val uidl: String,
    val sizeBytes: Long
)

class Pop3Client(
    private val transport: MailTransport,
    private val logListener: ((String) -> Unit)? = null
) : AutoCloseable {

    suspend fun connect(host: String, port: Int, security: ConnectionSecurity): String {
        transport.connect(host, port, security == ConnectionSecurity.SSL_TLS)
        val greeting = expectStatus(readLine())
        if (security == ConnectionSecurity.STARTTLS) {
            writeLine("STLS")
            expectStatus(readLine())
            transport.startTls(host)
        }
        return greeting
    }

    suspend fun authenticate(email: String, password: String) {
        writeLine("USER $email")
        expectStatus(readLine())
        writeLine("PASS $password")
        val response = readLine()
        if (!isOk(response)) {
            throw error("POP3 authentication failed for $email: ${response ?: "no response"}")
        }
    }

    suspend fun stat(): Pair<Int, Long> {
        writeLine("STAT")
        val line = expectStatus(readLine())
        val parts = line.substringAfter("+OK").trim().split(' ')
        return parts[0].toInt() to (parts.getOrNull(1)?.toLongOrNull() ?: 0L)
    }

    suspend fun uidlMap(): Map<Int, String> {
        writeLine("UIDL")
        expectStatus(readLine())
        val map = mutableMapOf<Int, String>()
        while (true) {
            val line = readLine() ?: break
            if (line.trim() == TERMINATOR) break
            val parts = line.trim().split(' ', limit = 2)
            if (parts.size == 2) {
                val num = parts[0].toIntOrNull() ?: continue
                map[num] = parts[1]
            }
        }
        return map
    }

    suspend fun retr(number: Int): ByteArray {
        writeLine("RETR $number")
        expectStatus(readLine())
        return readMultiline()
    }

    suspend fun top(number: Int, lineCount: Int): ByteArray {
        writeLine("TOP $number $lineCount")
        expectStatus(readLine())
        return readMultiline()
    }

    suspend fun dele(number: Int) {
        writeLine("DELE $number")
        expectStatus(readLine())
    }

    suspend fun rset() {
        writeLine("RSET")
        expectStatus(readLine())
    }

    suspend fun noop() {
        writeLine("NOOP")
        expectStatus(readLine())
    }

    override fun close() {
        runCatching { kotlinx.coroutines.runBlocking { writeLine("QUIT"); readLine() } }
        runCatching { transport.close() }
    }

    private suspend fun readMultiline(): ByteArray {
        val out = StringBuilder(4096)
        while (true) {
            val line = readLine() ?: throw error("Connection closed during multi-line response")
            if (line == TERMINATOR) break
            out.append(if (line.startsWith("..")) line.substring(1) else line).append("\r\n")
        }
        return out.toString().toByteArray(StandardCharsets.ISO_8859_1)
    }

    private fun isOk(line: String?): Boolean = line != null && line.startsWith("+OK")

    private fun expectStatus(line: String?): String =
        if (isOk(line)) line!!
        else throw error("POP3 command failed: ${line ?: "no response"}")

    private suspend fun readLine(): String? = transport.readLine(JvmSocketTransport.DEFAULT_TIMEOUT_MS)

    private suspend fun writeLine(line: String) {
        logListener?.invoke("< $line")
        transport.write((line + "\r\n").toByteArray(StandardCharsets.ISO_8859_1))
    }

    companion object {
        const val TERMINATOR = "."
    }
}
