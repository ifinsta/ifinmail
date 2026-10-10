package com.ifinmail.mail.smtp

import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.MailTransport
import java.nio.charset.StandardCharsets
import java.util.Base64

data class SmtpReply(val code: Int, val lines: List<String>) {
    val text: String get() = lines.joinToString("\n")
    val isSuccess: Boolean get() = code in 200..399
}

class SmtpClient(
    private val transport: MailTransport,
    private val logListener: ((String) -> Unit)? = null
) : AutoCloseable {

    private var extensions: Set<String> = emptySet()

    suspend fun connect(host: String, port: Int, security: ConnectionSecurity): SmtpReply {
        transport.connect(host, port, security == ConnectionSecurity.SSL_TLS)
        val greeting = readReply()
        if (greeting.code != 220) throw error("SMTP greeting refused: ${greeting.text}")
        ehlo()
        if (security == ConnectionSecurity.STARTTLS) {
            if ("STARTTLS" !in extensions) throw error("Server does not offer STARTTLS")
            writeLine("STARTTLS")
            val reply = readReply()
            if (reply.code != 220) throw error("STARTTLS refused: ${reply.text}")
            transport.startTls(host)
            ehlo()
        }
        return greeting
    }

    suspend fun authenticate(email: String, password: String?, oauthAccessToken: String?) {
        if (oauthAccessToken != null) {
            authXOauth2(email, oauthAccessToken)
        } else if (password != null) {
            val mechanisms = advertisedAuthMechanisms()
            when {
                mechanisms.any { it.equals("PLAIN", true) } -> authPlain(email, password)
                mechanisms.any { it.equals("LOGIN", true) } -> authLogin(email, password)
                else -> throw error("Server supports none of the supported AUTH mechanisms (PLAIN/LOGIN); advertised: $mechanisms")
            }
        } else {
            throw error("No credentials provided")
        }
    }

    private fun advertisedAuthMechanisms(): List<String> =
        extensions.firstOrNull { it.startsWith("AUTH", true) }
            ?.substringAfter("AUTH", "")
            ?.trim()
            ?.split(' ')
            ?.filter { it.isNotBlank() }
            .orEmpty()

    suspend fun authPlain(email: String, password: String) {
        val payload = "\u0000$email\u0000$password"
        sendExpecting("AUTH PLAIN " + Base64.getEncoder().encodeToString(payload.toByteArray(StandardCharsets.UTF_8)), 235)
    }

    suspend fun authLogin(email: String, password: String) {
        sendExpecting("AUTH LOGIN", 334)
        writeLine(Base64.getEncoder().encodeToString(email.toByteArray(StandardCharsets.UTF_8)))
        expectCode(readReply(), 334)
        writeLine(Base64.getEncoder().encodeToString(password.toByteArray(StandardCharsets.UTF_8)))
        expectCode(readReply(), 235)
    }

    suspend fun authXOauth2(email: String, accessToken: String) {
        require(advertisedAuthMechanisms().any { it.equals("XOAUTH2", true) }) {
            "Server does not advertise XOAUTH2"
        }
        val payload = "user=$email\u0001auth=Bearer $accessToken\u0001\u0001"
        writeLine("AUTH XOAUTH2 " + Base64.getEncoder().encodeToString(payload.toByteArray(StandardCharsets.UTF_8)))
        val reply = readReply()
        if (reply.code == 334) {
            writeLine("")
            val final = readReply()
            if (final.code != 235) throw error("OAuth2 rejected: ${final.text}")
        } else {
            expectCode(reply, 235)
        }
    }

    suspend fun sendMail(fromAddress: String, recipientAddresses: List<String>, messageData: ByteArray) {
        sendExpecting("MAIL FROM:<$fromAddress>", 250)
        for (recipient in recipientAddresses) {
            val reply = command("RCPT TO:<$recipient>")
            if (reply.code != 250 && reply.code != 251) {
                throw error("Recipient rejected '$recipient': ${reply.text}")
            }
        }
        sendExpecting("DATA", 354)
        val stuffed = dotStuff(messageData)
        logListener?.invoke("< [${stuffed.size} bytes of message data]")
        transport.write(stuffed)
        transport.write(".\r\n".toByteArray(StandardCharsets.ISO_8859_1))
        val reply = readReply()
        if (reply.code != 250) throw error("Message rejected by server: ${reply.text}")
    }

    override fun close() {
        runCatching { kotlinx.coroutines.runBlocking { writeLine("QUIT"); readReply() } }
        runCatching { transport.close() }
    }

    private suspend fun ehlo() {
        writeLine("EHLO ifinmail.local")
        val reply = readReply()
        if (reply.code != 250) {
            writeLine("HELO ifinmail.local")
            val helo = readReply()
            if (helo.code != 250) throw error("EHLO/HELO failed: ${helo.text}")
            extensions = emptySet()
        } else {
            extensions = reply.lines.drop(1).mapNotNull { line ->
                val keyword = line.trim().substringBefore(' ').uppercase()
                when (keyword) {
                    "AUTH" -> "AUTH " + line.substringAfter(' ', "").trim().uppercase()
                    else -> keyword
                }
            }.toSet()
        }
    }

    private suspend fun command(text: String): SmtpReply {
        writeLine(text)
        return readReply()
    }

    private suspend fun sendExpecting(text: String, code: Int): SmtpReply =
        expectCode(command(text), code)

    private fun expectCode(reply: SmtpReply, code: Int): SmtpReply {
        if (reply.code != code) throw error("Expected SMTP $code but got ${reply.code}: ${reply.text}")
        return reply
    }

    internal suspend fun writeLine(line: String) {
        logListener?.invoke("< $line")
        transport.write((line + "\r\n").toByteArray(StandardCharsets.ISO_8859_1))
    }

    private suspend fun readReply(): SmtpReply {
        val lines = mutableListOf<String>()
        var code = 0
        while (true) {
            val line = transport.readLine(JvmSocketTransport.DEFAULT_TIMEOUT_MS)
                ?: throw error("Connection closed awaiting SMTP reply")
            logListener?.invoke("> $line")
            if (line.length < 4 || line[3] !in listOf('-', ' ')) {
                code = line.take(3).toIntOrNull() ?: 0
                lines += line.drop(4)
                break
            }
            code = line.substring(0, 3).toIntOrNull() ?: 0
            lines += line.substring(4)
            if (line[3] == ' ') break
        }
        return SmtpReply(code, lines)
    }

    companion object {
        internal fun dotStuff(data: ByteArray): ByteArray {
            val text = String(data, StandardCharsets.ISO_8859_1)
            val normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
            val sb = StringBuilder(normalized.length + 16)
            var atLineStart = true
            for (c in normalized) {
                if (atLineStart && c == '.') sb.append('.')
                sb.append(c)
                atLineStart = c == '\n'
            }
            if (!normalized.endsWith("\r\n")) sb.append("\r\n")
            return sb.toString().toByteArray(StandardCharsets.ISO_8859_1)
        }
    }
}
