package com.ifinmail.mail.mime

import java.io.ByteArrayOutputStream
import java.nio.charset.Charset
import java.nio.charset.StandardCharsets
import java.util.Base64

object Encodings {

    private val encodedWordRegex = Regex("=\\?([^?]+)\\?([BbQq])\\?([^?]*)\\?=")

    fun base64DecodeLenient(text: String): ByteArray {
        val cleaned = text.replace(Regex("[^A-Za-z0-9+/=]"), "")
        return try {
            Base64.getMimeDecoder().decode(cleaned)
        } catch (e: IllegalArgumentException) {
            ByteArray(0)
        }
    }

    fun base64Encode(data: ByteArray): String = Base64.getEncoder().encodeToString(data)

    fun quotedPrintableDecode(input: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(input.size)
        var i = 0
        while (i < input.size) {
            val b = input[i].toInt() and 0xFF
            if (b == '='.code) {
                if (i + 2 < input.size && input[i + 1] == '\r'.code.toByte() && input[i + 2] == '\n'.code.toByte()) {
                    i += 3
                    continue
                }
                if (i + 1 < input.size && (input[i + 1] == '\n'.code.toByte())) {
                    i += 2
                    continue
                }
                if (i + 2 < input.size) {
                    val hi = hexValue(input[i + 1])
                    val lo = hexValue(input[i + 2])
                    if (hi >= 0 && lo >= 0) {
                        out.write((hi shl 4) or lo)
                        i += 3
                        continue
                    }
                }
            }
            out.write(b)
            i++
        }
        return out.toByteArray()
    }

    fun quotedPrintableEncode(text: String): String {
        val bytes = text.toByteArray(StandardCharsets.UTF_8)
        val sb = StringBuilder(bytes.size)
        var lineLength = 0
        var i = 0
        while (i < bytes.size) {
            val b = bytes[i].toInt() and 0xFF
            if (b == '\r'.code && i + 1 < bytes.size && bytes[i + 1] == '\n'.code.toByte()) {
                trimTrailingSpaceOrTab(sb)
                sb.append("\r\n")
                lineLength = 0
                i += 2
                continue
            }
            if (b == '\n'.code) {
                trimTrailingSpaceOrTab(sb)
                sb.append("\r\n")
                lineLength = 0
                i++
                continue
            }
            val encoded = encodeByteQp(b)
            val isTrailingWhitespaceCandidate = b == ' '.code || b == '\t'.code
            if (lineLength + encoded.length > 75) {
                sb.append("=\r\n")
                lineLength = 0
            }
            sb.append(encoded)
            lineLength += encoded.length
            i++
            if (!isTrailingWhitespaceCandidate) continue
            val nextIsBreak = i >= bytes.size || bytes[i] == '\n'.code.toByte() ||
                (bytes[i] == '\r'.code.toByte() && i + 1 < bytes.size && bytes[i + 1] == '\n'.code.toByte())
            if (nextIsBreak) {
                val last = sb.length - 1
                val tail = sb[last]
                sb.setLength(last)
                sb.append(if (tail == ' ') "=20" else "=09")
            }
        }
        return sb.toString()
    }

    fun decodeEncodedWords(headerValue: String): String {
        if (!headerValue.contains("=?")) return headerValue
        val collapsed = headerValue.replace(Regex("(=\\?[^?]*\\?[BbQq]\\?[^?]*\\?=)\\s+(=\\?)", RegexOption.IGNORE_CASE), "$1$2")
        return encodedWordRegex.replace(collapsed) { match ->
            val charsetName = match.groupValues[1]
            val encoding = match.groupValues[2].lowercase()
            val payload = match.groupValues[3]
            val bytes = if (encoding == "b") {
                base64DecodeLenient(payload)
            } else {
                val q = payload.replace('_', ' ')
                val out = ByteArrayOutputStream(q.length)
                var i = 0
                while (i < q.length) {
                    val c = q[i]
                    if (c == '=' && i + 2 < q.length + 1 && i + 2 <= q.lastIndex) {
                        val hi = q[i + 1].digitToIntOrNull(16)
                        val lo = q[i + 2].digitToIntOrNull(16)
                        if (hi != null && lo != null) {
                            out.write((hi shl 4) or lo)
                            i += 3
                            continue
                        }
                    }
                    out.write(c.code)
                    i++
                }
                out.toByteArray()
            }
            runCatching { String(bytes, Charset.forName(charsetName)) }.getOrDefault(match.value)
        }
    }

    fun encodeHeaderValueIfNecessary(value: String): String {
        val needsEncoding = value.any { it.code > 126 || (it.code < 32 && it != '\t') }
        if (!needsEncoding) return value
        val bytes = value.toByteArray(StandardCharsets.UTF_8)
        val chunkSize = 30
        if (bytes.size <= chunkSize) {
            return "=?UTF-8?B?${base64Encode(bytes)}?="
        }
        val words = mutableListOf<String>()
        var start = 0
        while (start < bytes.size) {
            var end = minOf(start + chunkSize, bytes.size)
            while (end < bytes.size && (bytes[end].toInt() and 0xC0) == 0x80) end++
            words += "=?UTF-8?B?${base64Encode(bytes.copyOfRange(start, end))}?="
            start = end
        }
        return words.joinToString(" ")
    }

    fun charsetDecode(bytes: ByteArray, charsetName: String?): String {
        if (charsetName.isNullOrBlank()) return String(bytes, StandardCharsets.UTF_8)
        return try {
            String(bytes, Charset.forName(charsetName))
        } catch (e: Exception) {
            String(bytes, StandardCharsets.UTF_8)
        }
    }

    private fun encodeByteQp(b: Int): String =
        if (b == '='.code || b < ' '.code || b > '~'.code) {
            "=%02X".format(b)
        } else {
            b.toChar().toString()
        }

    private fun trimTrailingSpaceOrTab(sb: StringBuilder) {
        while (sb.isNotEmpty() && (sb.last() == ' ' || sb.last() == '\t')) {
            sb.setLength(sb.length - 1)
        }
    }

    private fun hexValue(b: Byte): Int {
        val c = b.toInt() and 0xFF
        return when (c) {
            in '0'.code..'9'.code -> c - '0'.code
            in 'A'.code..'F'.code -> c - 'A'.code + 10
            in 'a'.code..'f'.code -> c - 'a'.code + 10
            else -> -1
        }
    }
}
