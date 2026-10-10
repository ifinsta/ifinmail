package com.ifinmail.mail.mime

import com.ifinmail.mail.model.EmailAddress
import com.ifinmail.mail.model.OutgoingDraft
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.TimeZone

object MimeComposer {

    private val random = SecureRandom()

    fun compose(from: EmailAddress, draft: OutgoingDraft): ByteArray {
        val sb = StringBuilder(1024)
        sb.append("From: ").append(addressLine(from.name ?: "", from.address)).append(CRLF)
        appendAddressHeader(sb, "To", draft.to)
        appendAddressHeader(sb, "Cc", draft.cc)
        appendAddressHeader(sb, "Bcc", draft.bcc)
        sb.append("Subject: ").append(Encodings.encodeHeaderValueIfNecessary(draft.subject.ifBlank { "(no subject)" })).append(CRLF)
        val rfc1123 = SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss Z", java.util.Locale.US)
        rfc1123.timeZone = TimeZone.getTimeZone("UTC")
        sb.append("Date: ").append(rfc1123.format(Date())).append(CRLF)
        sb.append("Message-ID: <").append(System.currentTimeMillis()).append('.').append(random.nextInt(Int.MAX_VALUE))
            .append("@ifinmail.local>").append(CRLF)
        draft.inReplyToMessageId?.let { sb.append("In-Reply-To: ").append(it).append(CRLF) }
        draft.references?.let { sb.append("References: ").append(it).append(CRLF) }
        sb.append("MIME-Version: 1.0").append(CRLF)
        sb.append("Content-Type: text/plain; charset=UTF-8").append(CRLF)
        sb.append("Content-Transfer-Encoding: quoted-printable").append(CRLF)
        sb.append(CRLF)
        val body = Encodings.quotedPrintableEncode(normalizeNewlines(draft.bodyText))
        sb.append(body)
        return sb.toString().toByteArray(StandardCharsets.UTF_8)
    }

    fun addressLine(name: String, address: String): String {
        if (name.isBlank()) return address
        return "\"${Encodings.encodeHeaderValueIfNecessary(name)}\" <$address>"
    }

    private fun appendAddressHeader(sb: StringBuilder, name: String, addresses: List<EmailAddress>) {
        if (addresses.isEmpty()) return
        val joined = addresses.joinToString(", ") { addr ->
            if (addr.name.isNullOrBlank()) addr.address else addressLine(addr.name!!, addr.address)
        }
        sb.append(name).append(": ").append(joined).append(CRLF)
    }

    private fun normalizeNewlines(text: String): String =
        text.replace("\r\n", "\n").replace("\n", CRLF)

    const val CRLF = "\r\n"
}
