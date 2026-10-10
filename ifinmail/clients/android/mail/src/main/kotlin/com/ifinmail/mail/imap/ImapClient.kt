package com.ifinmail.mail.imap

import com.ifinmail.core.domain.model.MailboxRole
import com.ifinmail.mail.mime.MimeParser
import com.ifinmail.mail.model.ConnectionSecurity
import com.ifinmail.mail.model.Credentials
import com.ifinmail.mail.transport.JvmSocketTransport
import com.ifinmail.mail.transport.MailTransport
import java.nio.charset.StandardCharsets
import java.util.Base64

data class ImapSummary(
    val uid: Long,
    val flags: Set<String>,
    val internalDateEpochMs: Long?,
    val sizeBytes: Long,
    val headerBytes: ByteArray?
)

data class ImapSelectResult(
    val exists: Int,
    val uidValidity: Long,
    val unseen: Int
)

class ImapClient(
    private val transport: MailTransport,
    private val logListener: ((String) -> Unit)? = null
) : AutoCloseable {

    private var tagCounter = 0
    private var capabilities: MutableSet<String> = LinkedHashSet()

    fun capabilitiesSnapshot(): Set<String> = capabilities.toSet()

    suspend fun connect(host: String, port: Int, security: ConnectionSecurity): String {
        transport.connect(host, port, security == ConnectionSecurity.SSL_TLS)
        val greeting = readLogicalLine() ?: throw error("No greeting from $host")
        if (!greeting.startsWith("* ")) throw error("Unexpected greeting: $greeting")
        if (!greeting.contains(" OK", ignoreCase = true)) throw error("Server refused greeting: $greeting")
        capability()
        if (security == ConnectionSecurity.STARTTLS && capabilities.none { it.equals("STARTTLS", true) }) {
            throw error("Server does not support STARTTLS")
        }
        return greeting
    }

    suspend fun startTls(host: String) {
        execute("STARTTLS")
        transport.startTls(host)
        capability()
    }

    suspend fun authenticate(email: String, credentials: Credentials) {
        when (credentials.authMethod) {
            com.ifinmail.mail.model.AuthMethod.XOAUTH2 -> {
                val token = credentials.oauthAccessToken ?: throw error("OAuth2 access token missing")
                authenticateXOauth2(email, token)
            }
            com.ifinmail.mail.model.AuthMethod.PASSWORD -> {
                val password = credentials.password ?: throw error("Password missing")
                login(email, password)
            }
        }
    }

    suspend fun authenticateXOauth2(email: String, accessToken: String) {
        val payload = "user=$email\u0001auth=Bearer $accessToken\u0001\u0001"
        val b64 = Base64.getEncoder().encodeToString(payload.toByteArray(StandardCharsets.UTF_8))
        val result = execute("AUTHENTICATE XOAUTH2 $b64")
        if (result.status == "NO" || result.status == "BAD") {
            throw error("XOAUTH2 rejected: ${result.untaggedLines.joinToString(" ")} ${result.rest}")
        }
    }

    suspend fun login(email: String, password: String) {
        val hasSaslPlain = capabilities.any { it.startsWith("AUTH=PLAIN", true) }
        val result = if (hasSaslPlain) {
            val payload = "\u0000$email\u0000$password"
            execute("AUTHENTICATE PLAIN " + Base64.getEncoder().encodeToString(payload.toByteArray(StandardCharsets.UTF_8)))
        } else {
            execute("LOGIN \"${escapeString(email)}\" \"${escapeString(password)}\"")
        }
        if (result.status != "OK") {
            throw error("Authentication failed for $email: ${result.rest.ifBlank { result.untaggedLines.lastOrNull() ?: "" }}")
        }
    }

    suspend fun listFolders(): List<String> {
        val result = execute("""LIST "" *""")
        return result.untaggedLines.mapNotNull { line ->
            if (!line.startsWith("* LIST ")) return@mapNotNull null
            parseListLine(line.substringAfter("* LIST "))
        }.filter { !it.endsWith("/Trash", true) && !it.equals("Trash", true) }
    }

    data class FolderEntry(
        val name: String,
        val flags: Set<String>
    ) {
        fun specialUseRole(): MailboxRole? = when {
            flags.any { it.equals("\\Sent", true) } -> MailboxRole.SENT
            flags.any { it.equals("\\Drafts", true) } -> MailboxRole.DRAFTS
            flags.any { it.equals("\\Trash", true) } -> MailboxRole.TRASH
            flags.any { it.equals("\\Archive", true) } -> MailboxRole.ARCHIVE
            flags.any { it.equals("\\Junk", true) } -> MailboxRole.SPAM
            flags.any { it.equals("\\Inbox", true) } || name.equals("INBOX", true) -> MailboxRole.INBOX
            else -> null
        }
    }

    suspend fun listFoldersDetailed(): List<FolderEntry> {
        val result = execute("""LIST "" *""")
        return result.untaggedLines.mapNotNull { line ->
            if (!line.startsWith("* LIST ")) return@mapNotNull null
            val rest = line.substringAfter("* LIST ")
            val flags = parseListFlags(rest)
            val name = parseListLine(rest) ?: return@mapNotNull null
            FolderEntry(name, flags)
        }
    }

    private fun parseListFlags(rest: String): Set<String> {
        val open = rest.indexOf('(')
        if (open < 0) return emptySet()
        val close = rest.indexOf(')', open)
        if (close < 0) return emptySet()
        return rest.substring(open + 1, close).split(' ').map { it.trim() }.filter { it.isNotEmpty() }.toSet()
    }

    data class SelectResult(val exists: Int, val uidValidity: Long, val unseen: Int)

    suspend fun select(folder: String, readOnly: Boolean = false): SelectResult {
        val command = (if (readOnly) "EXAMINE" else "SELECT") + " " + quoteMailbox(folder)
        val result = execute(command)
        if (result.status != "OK") throw error("Cannot select folder '$folder': ${result.rest}")
        var exists = 0
        var unseen = 0
        var uidValidity = 0L
        for (line in result.untaggedLines) {
            Regex("^\\* (\\d+) EXISTS$").find(line)?.let { exists = it.groupValues[1].toInt() }
            Regex("^\\* OK \\[UNSEEN (\\d+)\\]").find(line)?.let { unseen = it.groupValues[1].toInt() }
            Regex("\\[UIDVALIDITY (\\d+)]", RegexOption.IGNORE_CASE).find(line)?.let {
                uidValidity = it.groupValues[1].toLong()
            }
        }
        return SelectResult(exists, uidValidity, unseen)
    }

    suspend fun fetchSummaries(fromUidInclusive: Long): List<ImapSummary> {
        val range = "$fromUidInclusive:*"
        val command = "UID FETCH $range (UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER])"
        val result = execute(command)
        return result.untaggedLines.mapNotNull(::parseSummaryLine).sortedBy { it.uid }
    }

    suspend fun fetchBody(uid: Long): ByteArray {
        val command = "UID FETCH $uid (BODY.PEEK[])"
        val result = execute(command)
        val parsed = result.untaggedLines.firstNotNullOfOrNull(::parseFetchResponse)
            ?: throw error("No FETCH response for UID $uid")
        val bytes = parsed.second?.let { it.toByteArray(StandardCharsets.ISO_8859_1) }
            ?: throw error("Empty body for UID $uid")
        return bytes
    }

    suspend fun storeFlags(uid: Long, addFlags: Set<String> = emptySet(), removeFlags: Set<String> = emptySet()) {
        if (addFlags.isEmpty() && removeFlags.isEmpty()) return
        val op = if (addFlags.isNotEmpty()) "+" else "-"
        val flags = (if (addFlags.isNotEmpty()) addFlags else removeFlags).joinToString(" ") { it }
        val result = execute("UID STORE $uid ${op}FLAGS ($flags)")
        if (result.status != "OK") throw error("STORE failed for UID $uid: ${result.rest}")
    }

    suspend fun expunge() {
        execute("EXPUNGE")
    }

    suspend fun append(folder: String, messageBytes: ByteArray, flags: String = "\\Seen"): Long? {
        val tag = nextTag()
        writeLine("$tag APPEND ${quoteMailbox(folder)} ($flags) {${messageBytes.size}}")
        val continuation = readLogicalLine() ?: throw error("No continuation for APPEND")
        if (!continuation.startsWith("+")) {
            throw error("APPEND refused: $continuation")
        }
        writeRaw(messageBytes + byteArrayOf('\r'.code.toByte(), '\n'.code.toByte()))
        val final = awaitTagged(tag)
        return Regex("\\[APPENDUID (\\d+) (\\d+)]", RegexOption.IGNORE_CASE).find(final.line)?.groupValues?.get(2)?.toLongOrNull()
    }

    suspend fun noop(): Int? {
        val result = execute("NOOP")
        var exists: Int? = null
        for (line in result.untaggedLines) {
            Regex("^\\* (\\d+) EXISTS$").find(line)?.let { exists = it.groupValues[1].toInt() }
        }
        return exists
    }

    suspend fun idle(onExists: (Int) -> Unit, timeoutSeconds: Long = 29 * 60) {
        val tag = nextTag()
        writeLine("$tag IDLE")
        val ack = transport.readLine(30_000) ?: throw error("Timeout entering IDLE")
        if (!ack.startsWith("+")) throw error("IDLE refused: $ack")
        logListener?.invoke("> IDLE entered")
        val deadline = System.currentTimeMillis() + timeoutSeconds * 1000
        try {
            while (System.currentTimeMillis() < deadline) {
                val remaining = deadline - System.currentTimeMillis()
                val line = transport.readLine(minOf(remaining, 30_000)) ?: continue
                val m = Regex("^\\* (\\d+) EXISTS$").find(line)
                if (m != null) onExists(m.groupValues[1].toInt())
            }
        } finally {
            runCatching {
                writeLine("DONE")
                while (true) {
                    val line = transport.readLine(15_000) ?: break
                    if (line.startsWith("$tag ")) break
                }
            }
        }
    }

    override fun close() {
        runCatching { kotlinx.coroutines.runBlocking { execute("LOGOUT") } }
        runCatching { transport.close() }
    }

    internal data class TaggedResult(val status: String, val rest: String, val untaggedLines: List<String>, val line: String)

    internal suspend fun execute(commandText: String): TaggedResult {
        val tag = nextTag()
        writeLine("$tag $commandText")
        return awaitTagged(tag)
    }

    private suspend fun awaitTagged(tag: String): TaggedResult {
        val untagged = mutableListOf<String>()
        while (true) {
            val line = readLogicalLine() ?: throw error("Connection closed awaiting response to $tag")
            if (line.startsWith("$tag ")) {
                val status = line.substringAfter("$tag ").substringBefore(' ').uppercase()
                val rest = line.removePrefix("$tag $status ").trim()
                return TaggedResult(status, rest, untagged, line)
            }
            untagged += line
        }
    }

    private suspend fun capability() {
        val result = execute("CAPABILITY")
        caps(result)
    }

    private fun caps(result: TaggedResult) {
        val capLine = result.untaggedLines.firstOrNull { it.startsWith("* CAPABILITY") } ?: return
        capabilities.clear()
        capabilities.addAll(capLine.removePrefix("* CAPABILITY ").trim().split(' ').map { it.trim() }.filter { it.isNotEmpty() })
    }

    private fun nextTag(): String {
        tagCounter += 1
        return "IFM%04d".format(tagCounter)
    }

    internal suspend fun writeLine(line: String) {
        logListener?.invoke("< $line")
        transport.write((line + "\r\n").toByteArray(StandardCharsets.UTF_8))
    }

    internal suspend fun writeRaw(data: ByteArray) {
        transport.write(data)
    }

    internal suspend fun readLogicalLine(): String? {
        var line = transport.readLine(JvmSocketTransport.DEFAULT_TIMEOUT_MS) ?: return null
        var guard = 0
        while (guard++ < 1000) {
            val match = literalRegex.find(line) ?: break
            val length = match.groupValues[1].toInt()
            if (length < 0 || length > MAX_LITERAL_BYTES) throw error("Literal too large: $length")
            val literalBytes = transport.readBytes(length)
            val literalAsLatin1 = String(literalBytes, StandardCharsets.ISO_8859_1)
            val escaped = literalAsLatin1.replace("\\", "\\\\").replace("\"", "\\\"")
            line = line.substring(0, match.range.first) + "\"" + escaped + "\""
            val rest = transport.readLine(JvmSocketTransport.DEFAULT_TIMEOUT_MS)
                ?: throw error("Connection closed inside literal response")
            line += rest
        }
        logListener?.invoke("> " + line.take(LOG_LINE_LIMIT))
        return line
    }

    private fun parseFetchResponse(line: String): Pair<Long, String?>? {
        val match = fetchRegex.find(line) ?: return null
        val items = parseItems(match.groupValues[1])
        val uid = (items["UID"] as? Long) ?: return null
        val body = items["BODY[]"] as? String
        return uid to body
    }

    private fun parseSummaryLine(line: String): ImapSummary? {
        val match = fetchRegex.find(line) ?: return null
        val items = parseItems(match.groupValues[1])
        val uid = (items["UID"] as? Long) ?: return null
        val flags = (items["FLAGS"] as? List<*>)?.filterIsInstance<String>()?.toSet() ?: emptySet()
        val size = items["RFC822.SIZE"] as? Long ?: 0L
        val internalDate = (items["INTERNALDATE"] as? String)?.let { MimeParser.parseRfc5322Date(it) }
        val headerBytes = (items["BODY[HEADER]"] as? String)?.toByteArray(StandardCharsets.ISO_8859_1)
        return ImapSummary(uid, flags, internalDate, size, headerBytes)
    }

    internal fun parseFetchItemsForTest(itemsPart: String): Map<String, Any?> = parseItems(itemsPart)

    private fun parseItems(itemsPart: String): Map<String, Any?> {
        val map = LinkedHashMap<String, Any?>()
        val scanner = FetchScanner(itemsPart)
        var opened = false
        if (scanner.isNext('(')) {
            scanner.expect('(')
            opened = true
        }
        while (true) {
            if (opened && scanner.isNext(')')) {
                scanner.expect(')')
                break
            }
            if (!opened && scanner.atEnd()) break
            val key = scanner.readAtom().uppercase()
            if (key.isEmpty()) break
            when {
                scanner.isNext('(') -> {
                    scanner.expect('(')
                    val values = mutableListOf<String>()
                    while (!scanner.isNext(')')) {
                        val atom = scanner.readAtom()
                        if (atom.isNotEmpty()) values += atom
                    }
                    scanner.expect(')')
                    map[key] = values
                }
                else -> {
                    val quoted = scanner.tryReadQuoted()
                    if (quoted != null) {
                        map[key] = unescapeQuoted(quoted)
                    } else {
                        val atom = scanner.readAtom()
                        map[key] = when {
                            atom.equals("NIL", true) || atom.isBlank() -> null
                            else -> atom.toLongOrNull() ?: atom
                        }
                    }
                }
            }
        }
        return map
    }

    private fun parseListLine(rest: String): String? {
        var i = 0
        var name: String?
        val openParen = rest.indexOf('(')
        if (openParen >= 0) {
            var depth = 1
            i = openParen + 1
            while (i < rest.length && depth > 0) {
                when (rest[i]) {
                    '(' -> depth++
                    ')' -> depth--
                }
                i++
            }
        }
        while (i < rest.length && rest[i] == ' ') i++
        if (i >= rest.length) return null
        if (rest[i] == '"') {
            i++
            while (i < rest.length && rest[i] != '"') i++
            i++
        } else {
            while (i < rest.length && rest[i] != ' ') i++
        }
        while (i < rest.length && rest[i] == ' ') i++
        if (i >= rest.length) return null
        name = if (rest[i] == '"') {
            val sb = StringBuilder()
            i++
            while (i < rest.length) {
                val c = rest[i]
                if (c == '\\' && i + 1 < rest.length) {
                    sb.append(rest[i + 1])
                    i += 2
                    continue
                }
                if (c == '"') break
                sb.append(c)
                i++
            }
            sb.toString()
        } else {
            rest.substring(i).trim()
        }
        return name.ifBlank { null }
    }

    private fun quoteMailbox(name: String): String = "\"${escapeString(name)}\""

    private fun escapeString(value: String): String = value.replace("\\", "\\\\").replace("\"", "\\\"")

    private fun unescapeQuoted(value: String): String {
        val sb = StringBuilder(value.length)
        var i = 0
        while (i < value.length) {
            val c = value[i]
            if (c == '\\' && i + 1 < value.length) {
                sb.append(value[i + 1])
                i += 2
            } else {
                sb.append(c)
                i++
            }
        }
        return sb.toString()
    }

    private class FetchScanner(private val s: String) {
        var i = 0

        fun atEnd(): Boolean {
            skipWs()
            return i >= s.length
        }

        fun skipWs() {
            while (i < s.length && s[i] == ' ') i++
        }

        fun expect(c: Char) {
            skipWs()
            require(i < s.length && s[i] == c) { "Expected '$c' at $i in '${s.take(200)}'" }
            i++
        }

        fun isNext(c: Char): Boolean {
            skipWs()
            return i < s.length && s[i] == c
        }

        fun readAtom(): String {
            skipWs()
            val start = i
            while (i < s.length && s[i] != ' ' && s[i] != '(' && s[i] != ')') i++
            return s.substring(start, i)
        }

        fun tryReadQuoted(): String? {
            skipWs()
            if (i >= s.length || s[i] != '"') return null
            i++
            val sb = StringBuilder()
            while (i < s.length) {
                val c = s[i]
                if (c == '\\' && i + 1 < s.length) {
                    sb.append(c)
                    sb.append(s[i + 1])
                    i += 2
                    continue
                }
                if (c == '"') {
                    i++
                    break
                }
                sb.append(c)
                i++
            }
            return sb.toString()
        }
    }

    companion object {
        private val literalRegex = Regex("\\{(\\d+)\\}$")
        private val fetchRegex = Regex("^\\* \\d+ FETCH \\((.*)\\)$", RegexOption.DOT_MATCHES_ALL)
        private const val MAX_LITERAL_BYTES = 64 * 1024 * 1024
        private const val LOG_LINE_LIMIT = 160
    }
}
