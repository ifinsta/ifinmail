package com.ifinmail.mail.mime

import com.ifinmail.mail.model.EmailAddress
import java.nio.charset.StandardCharsets

data class ParsedMessage(
    val messageId: String?,
    val subject: String,
    val from: EmailAddress?,
    val to: List<EmailAddress>,
    val cc: List<EmailAddress>,
    val dateEpochMs: Long?,
    val plainText: String?,
    val htmlText: String?,
    val snippet: String,
    val attachmentNames: List<String>,
    val replyToMessageId: String?
)

data class MimePart(
    val headers: Map<String, String>,
    val bodyBytes: ByteArray,
    val children: List<MimePart>
) {
    fun header(name: String): String? = headers[name.lowercase()]

    val contentTypeFull: String get() = (header("content-type") ?: "text/plain; charset=us-ascii")

    val mimeType: String
        get() = contentTypeFull.substringBefore(';').trim().lowercase().ifBlank { "text/plain" }

    val parameters: Map<String, String> by lazy {
        MimeParser.parseHeaderParameters(contentTypeFull)
    }

    val dispositionParameters: Map<String, String> by lazy {
        MimeParser.parseHeaderParameters(header("content-disposition") ?: "")
    }
}

object MimeParser {

    fun parseMessage(raw: ByteArray): ParsedMessage {
        val root = parsePart(raw)
        return buildMessage(root)
    }

    fun parsePart(raw: ByteArray): MimePart {
        val (headerBlock, body) = splitHeaderAndBody(raw)
        val headers = parseHeaders(headerBlock)
        val part = MimePart(headers, body, emptyList())
        val contentType = part.mimeType
        return if (contentType.startsWith("multipart/")) {
            val boundary = part.parameters["boundary"]
            if (boundary.isNullOrBlank()) {
                part
            } else {
                part.copy(children = splitMultipart(body, boundary).map { parsePart(it) })
            }
        } else {
            part
        }
    }

    private fun splitHeaderAndBody(raw: ByteArray): Pair<ByteArray, ByteArray> {
        var separatorIndex = -1
        var sepLength = 0
        for (i in 0 until raw.size - 1) {
            if (raw[i] == '\r'.code.toByte() && i + 3 < raw.size &&
                raw[i + 1] == '\n'.code.toByte() && raw[i + 2] == '\r'.code.toByte() && raw[i + 3] == '\n'.code.toByte()
            ) {
                separatorIndex = i
                sepLength = 4
                break
            }
            if (raw[i] == '\n'.code.toByte() && raw[i + 1] == '\n'.code.toByte()) {
                separatorIndex = i
                sepLength = 2
                break
            }
        }
        return if (separatorIndex < 0) {
            raw to ByteArray(0)
        } else {
            raw.copyOfRange(0, separatorIndex) to raw.copyOfRange(separatorIndex + sepLength, raw.size)
        }
    }

    fun parseHeaders(headerBlock: ByteArray): Map<String, String> {
        val text = String(headerBlock, StandardCharsets.ISO_8859_1)
        val lines = text.split("\r\n", "\n")
        val unfolded = mutableListOf<String>()
        for (line in lines) {
            if (line.isEmpty()) continue
            if ((line[0] == ' ' || line[0] == '\t') && unfolded.isNotEmpty()) {
                unfolded[unfolded.size - 1] += line
            } else {
                unfolded += line
            }
        }
        val headers = mutableMapOf<String, String>()
        for (line in unfolded) {
            val colon = line.indexOf(':')
            if (colon <= 0) continue
            val name = line.substring(0, colon).trim().lowercase()
            val value = Encodings.decodeEncodedWords(line.substring(colon + 1).trim())
            headers[name] = if (headers.containsKey(name)) headers[name] + ", " + value else value
        }
        return headers
    }

    private fun splitMultipart(body: ByteArray, boundary: String): List<ByteArray> {
        val delimiter = "--$boundary"
        val parts = mutableListOf<ByteArray>()
        val current = java.io.ByteArrayOutputStream()
        var inPart = false
        val lines = splitLines(body)
        for (line in lines) {
            val trimmed = line.trimEnd { it == '\r' || it == '\n' }
            when {
                trimmed == delimiter -> {
                    if (inPart) parts += current.toByteArray()
                    current.reset()
                    inPart = true
                }
                trimmed.startsWith(delimiter) && trimmed.drop(delimiter.length).trimStart('-').isBlank() -> {
                    if (inPart) parts += current.toByteArray()
                    return parts
                }
                inPart -> {
                    current.write(line.toByteArray(StandardCharsets.ISO_8859_1))
                    current.write(CRLF)
                }
            }
        }
        if (inPart && current.size() > 0) parts += current.toByteArray()
        return parts
    }

    private fun splitLines(body: ByteArray): List<String> {
        val text = String(body, StandardCharsets.ISO_8859_1)
        return text.split("\r\n", "\n")
    }

    private fun transferDecode(part: MimePart): ByteArray {
        val encoding = (part.header("content-transfer-encoding") ?: "7bit").trim().lowercase()
        return when {
            encoding.contains("base64") -> Encodings.base64DecodeLenient(String(part.bodyBytes, StandardCharsets.ISO_8859_1))
            encoding.contains("quoted-printable") -> Encodings.quotedPrintableDecode(part.bodyBytes)
            else -> part.bodyBytes
        }
    }

    private fun decodedText(part: MimePart): String =
        Encodings.charsetDecode(transferDecode(part), part.parameters["charset"])

    private fun isAttachment(part: MimePart): Boolean {
        val disposition = (part.header("content-disposition") ?: "").substringBefore(';').trim().lowercase()
        if (disposition == "attachment") return true
        if (part.dispositionParameters.containsKey("filename")) return true
        val name = part.parameters["name"]
        if (!name.isNullOrBlank()) return true
        val mime = part.mimeType
        if (mime == "message/rfc822") return true
        return false
    }

    fun flattenLeafParts(root: MimePart): List<MimePart> {
        if (root.children.isEmpty()) return listOf(root)
        return root.children.flatMap { flattenLeafParts(it) }
    }

    private fun buildMessage(root: MimePart): ParsedMessage {
        val subject = root.header("subject") ?: "(no subject)"
        val from = root.header("from")?.let(::parseFirstAddress)
        val to = root.header("to")?.let(::parseAddressList).orEmpty()
        val cc = root.header("cc")?.let(::parseAddressList).orEmpty()
        val dateEpochMs = root.header("date")?.let(::parseRfc5322Date)
        val leaves = flattenLeafParts(root)
        var plain: String? = null
        var html: String? = null
        val attachments = mutableListOf<String>()
        for (leaf in leaves) {
            if (isAttachment(leaf)) {
                val name = leaf.dispositionParameters["filename"]
                    ?: leaf.parameters["name"]
                    ?: "attachment"
                attachments += name
                continue
            }
            when (leaf.mimeType) {
                "text/plain" -> if (plain == null) plain = decodedText(leaf)
                "text/html" -> if (html == null) html = decodedText(leaf)
            }
        }
        val textForSnippet = normalizeWhitespace(plain ?: htmlToText(html))
        return ParsedMessage(
            messageId = root.header("message-id"),
            subject = subject.ifBlank { "(no subject)" },
            from = from,
            to = to,
            cc = cc,
            dateEpochMs = dateEpochMs,
            plainText = plain?.normalizeNewlines(),
            htmlText = html?.normalizeNewlines(),
            snippet = textForSnippet.take(SNIPPET_LENGTH),
            attachmentNames = attachments,
            replyToMessageId = null
        )
    }

    fun parseAddressList(value: String): List<EmailAddress> =
        value.split(',').mapNotNull { token ->
            val parsed = EmailAddress.parse(token)
            if (parsed.address.isBlank()) null else parsed
        }

    fun parseFirstAddress(value: String): EmailAddress? =
        parseAddressList(value).firstOrNull()

    fun parseHeaderParameters(headerValue: String): Map<String, String> {
        val params = mutableMapOf<String, String>()
        var index = headerValue.indexOf(';')
        if (index < 0) return params
        val rest = headerValue.substring(index + 1)
        var i = 0
        while (i < rest.length) {
            while (i < rest.length && (rest[i] == ' ' || rest[i] == '\t' || rest[i] == ';')) i++
            if (i >= rest.length) break
            val eq = rest.indexOf('=', i)
            if (eq < 0) break
            val key = rest.substring(i, eq).trim().lowercase()
            var j = eq + 1
            while (j < rest.length && rest[j] == ' ') j++
            val value: String
            if (j < rest.length && rest[j] == '"') {
                val sb = StringBuilder()
                j++
                while (j < rest.length && rest[j] != '"') {
                    if (rest[j] == '\\' && j + 1 < rest.length) j++
                    sb.append(rest[j])
                    j++
                }
                value = sb.toString()
                j++
            } else {
                val start = j
                while (j < rest.length && rest[j] != ';' && rest[j] != ' ') j++
                value = rest.substring(start, j)
            }
            if (key.isNotEmpty()) params[key] = value
            i = j
        }
        return params
    }

    fun parseRfc5322Date(value: String): Long? {
        try {
            var v = value.trim()
            v = v.replace(Regex("\\([^)]*\\)"), "").trim()
            v = v.replaceFirst(Regex("^[A-Za-z]{2,9},\\s*"), "")
            v = v.replace(Regex("\\s+"), " ")
            v = v.replace(Regex("\\b(GMT|UT|UTC|Z)\\b"), "+0000")
            for ((name, offset) in zoneAliases) {
                if (name in v) v = v.replace(name, offset)
            }
            val regex = Regex("(\\d{1,2})[-\\s]+([A-Za-z]{3})[A-Za-z]*[-\\s]+(\\d{2,4})\\s+(\\d{1,2}):(\\d{2})(?::(\\d{2}))?(?:\\s+([+-]\\d{4}))?")
            val match = regex.find(v) ?: return null
            val day = match.groupValues[1].toInt()
            val monthStr = match.groupValues[2].lowercase()
            val month = months.indexOfFirst { it == monthStr } + 1
            if (month <= 0) return null
            var year = match.groupValues[3].toInt()
            if (year < 100) year += if (year < 50) 2000 else 1900
            val hour = match.groupValues[4].toInt()
            val minute = match.groupValues[5].toInt()
            val second = match.groupValues[6].ifBlank { "0" }.toInt()
            val zoneRaw = match.groupValues[7]
            val offsetMinutes = if (zoneRaw.isBlank()) 0 else {
                val sign = if (zoneRaw[0] == '-') -1 else 1
                val hh = zoneRaw.substring(1, 3).toInt()
                val mm = zoneRaw.substring(3, 5).toInt()
                sign * (hh * 60 + mm)
            }
            val epochDay = daysFromCivil(year, month, day)
            val utcMillis = epochDay * 86_400_000L + hour * 3_600_000L + minute * 60_000L + second * 1_000L
            return utcMillis - offsetMinutes * 60_000L
        } catch (e: Exception) {
            return null
        }
    }

    private val months = listOf("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

    private val zoneAliases = mapOf(
        "EST" to "-0500", "EDT" to "-0400",
        "CST" to "-0600", "CDT" to "-0500",
        "MST" to "-0700", "MDT" to "-0600",
        "PST" to "-0800", "PDT" to "-0700"
    )

    private fun daysFromCivil(year: Int, month: Int, day: Int): Long {
        var y = year.toLong()
        val m = month.toLong()
        if (m <= 2) y -= 1
        val era = (if (y >= 0) y else y - 399) / 400
        val yoe = y - era * 400
        val mp = (m + 9) % 12
        val doy = (153 * mp + 2) / 5 + day - 1
        val doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
        return era * 146097 + doe - 719468
    }

    fun htmlToText(html: String?): String? {
        if (html.isNullOrBlank()) return null
        return html
            .replace(Regex("<(script|style)[^>]*>[\\s\\S]*?</(script|style)>", RegexOption.IGNORE_CASE), "")
            .replace(Regex("<br\\s*/?>|</p>|</div>|</tr>", RegexOption.IGNORE_CASE), "\n")
            .replace(Regex("<[^>]+>"), "")
            .replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .let(::normalizeWhitespace)
    }

    private fun normalizeWhitespace(text: String?): String =
        text?.replace(Regex("[ \\t\\x0B\\f\\r]+"), " ")?.replace(Regex("\\s*\\n\\s*"), "\n")?.trim() ?: ""

    private fun String.normalizeNewlines(): String =
        replace("\r\n", "\n").replace(Regex("\n+$"), "")

    const val SNIPPET_LENGTH = 180

    private val CRLF = byteArrayOf('\r'.code.toByte(), '\n'.code.toByte())
}
