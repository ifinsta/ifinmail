package com.ifinmail.core.domain.export

import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.port.ExportService
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime

object MboxExportService : ExportService {

    private val monthNames = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    override suspend fun exportMbox(accountId: String, messages: List<StoredMessage>): String {
        val sb = StringBuilder(4096)
        for (message in messages.sortedByDescending { it.dateEpochMs ?: 0L }) {
            sb.append("From MAILER-DAEMON ").append(epochToMboxDate(message.dateEpochMs)).append('\n')
            sb.append("From: ").append(message.fromName ?: "").append(" <").append(message.fromAddress).append(">\n")
            sb.append("To: ").append(message.toCsv).append('\n')
            if (message.ccCsv.isNotBlank()) sb.append("Cc: ").append(message.ccCsv).append('\n')
            sb.append("Subject: ").append(message.subject).append('\n')
            message.dateEpochMs?.let { sb.append("Date: ").append(epochToRfc5322(it)).append('\n') }
            sb.append("X-Ifinmail-Account: ").append(message.accountId).append('\n')
            sb.append('\n')
            val body = message.bodyText ?: " "
            for (line in body.split('\n')) {
                if (line.startsWith("From ")) sb.append('>')
                sb.append(line).append('\n')
            }
            sb.append('\n')
        }
        return sb.toString()
    }

    override suspend fun exportVCard(displayName: String, email: String): String {
        val parts = displayName.split(' ').filter { it.isNotBlank() }
        val given = parts.firstOrNull() ?: ""
        val family = parts.drop(1).joinToString(" ")
        return buildString {
            appendLine("BEGIN:VCARD")
            appendLine("VERSION:3.0")
            appendLine("FN:$displayName")
            appendLine("N:$family;;;$given;")
            appendLine("EMAIL;TYPE=INTERNET:$email")
            appendLine("PRODID:-//ifinmail//EN")
            appendLine("END:VCARD")
        }
    }

    private fun epochToRfc5322(epochMs: Long): String {
        val dt = Instant.fromEpochMilliseconds(epochMs).toLocalDateTime(TimeZone.UTC)
        val dayName = dt.dayOfWeek.name.take(3)
        val time = "%02d:%02d:%02d".format(dt.hour, dt.minute, dt.second)
        return "$dayName, %02d %s %04d $time +0000".format(
            dt.dayOfMonth, monthNames[dt.monthNumber - 1], dt.year
        )
    }

    private fun epochToMboxDate(epochMs: Long?): String {
        if (epochMs == null) return "Thu Jan  1 00:00:00 1970"
        val dt = Instant.fromEpochMilliseconds(epochMs).toLocalDateTime(TimeZone.UTC)
        val dayName = dt.dayOfWeek.name.take(3)
        val time = "%02d:%02d:%02d".format(dt.hour, dt.minute, dt.second)
        return "$dayName ${monthNames[dt.monthNumber - 1]} %2d $time %04d".format(dt.dayOfMonth, dt.year)
    }
}
