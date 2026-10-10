package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.unit.sp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.ui.components.InlineError
import kotlinx.coroutines.launch

enum class UiComposeMode { NEW, REPLY, REPLY_ALL, FORWARD }

data class ComposePayload(
    val replyTo: UiMessage?,
    val mode: UiComposeMode,
    val initialBody: String? = null,
    val draft: UiDraft? = null
)

@Composable
fun ComposeScreen(
    controller: MailController,
    replyTo: UiMessage?,
    mode: UiComposeMode,
    onSent: () -> Unit,
    onCancel: () -> Unit,
    initialBody: String? = null,
    initialDraft: UiDraft? = null
) {
    val scope = rememberCoroutineScope()
    val activeAccount = controller.accounts.value.firstOrNull { it.id == controller.activeAccountId.value }

    val draftSeed = initialDraft
    var to by remember { mutableStateOf(initialDraft?.to?.joinToString(", ") ?: prefilledTo(replyTo, mode)) }
    var cc by remember { mutableStateOf(initialDraft?.cc?.joinToString(", ") ?: prefilledCc(replyTo, mode)) }
    var ccExpanded by remember { mutableStateOf(cc.isNotBlank()) }
    var subject by remember { mutableStateOf(initialDraft?.subject ?: prefilledSubject(replyTo, mode)) }
    var body by remember { mutableStateOf(initialBody ?: initialDraft?.body ?: prefilledBody(replyTo, mode)) }
    var sending by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var scheduleOpen by remember { mutableStateOf(false) }
    var attachOpen by remember { mutableStateOf(false) }
    var feedback by remember { mutableStateOf<String?>(null) }

    val canSend = to.trim().isNotBlank() && (subject.trim().isNotBlank() || body.trim().isNotBlank())
    val canSave = subject.isNotBlank() || body.isNotBlank()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .background(MaterialTheme.colorScheme.surface)
    ) {
        // Gmail top bar — close left, send right
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 2.dp)
        ) {
            IconButton(onClick = onCancel) {
                Icon(Icons.Default.Close, contentDescription = "Close", tint = MaterialTheme.colorScheme.onSurface)
            }
            Spacer(Modifier.width(4.dp))
            Text(
                when (mode) {
                    UiComposeMode.FORWARD -> "Forward"
                    UiComposeMode.REPLY, UiComposeMode.REPLY_ALL -> "Reply"
                    else -> "Compose"
                },
                style = MaterialTheme.typography.titleMedium
            )
            Spacer(Modifier.weight(1f))
            // Save draft — Gmail autosaves; we persist on tap
            IconButton(onClick = {
                val account = activeAccount
                if (account == null) {
                    error = "Select an account first"
                    return@IconButton
                }
                scope.launch {
                    controller.saveDraft(
                        UiDraft(
                            to = splitAddresses(to),
                            cc = splitAddresses(cc),
                            subject = subject.trim(),
                            body = body,
                            id = initialDraft?.id ?: ""
                        )
                    ).fold(
                        onSuccess = { feedback = "Draft saved" },
                        onFailure = { feedback = "Could not save" }
                    )
                }
            }, enabled = canSave) {
                Icon(Icons.Default.Save, contentDescription = "Save draft",
                    tint = if (canSave) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
            }
            IconButton(onClick = { attachOpen = true }) {
                Icon(Icons.Default.AttachFile, contentDescription = "Attach file", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = { attachOpen = true }) {
                Icon(Icons.Default.MoreVert, contentDescription = "More options", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (sending) {
                androidx.compose.material3.CircularProgressIndicator(
                    modifier = Modifier.padding(12.dp).height(22.dp).width(22.dp),
                    strokeWidth = 2.dp
                )
            } else {
                IconButton(onClick = { if (canSend) scheduleOpen = true }, enabled = canSend) {
                    Icon(
                        Icons.Default.Schedule,
                        contentDescription = "Schedule send",
                        tint = if (canSend) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.outline.copy(alpha = 0.4f)
                    )
                }
                IconButton(
                    onClick = {
                        val account = activeAccount
                        if (account == null) {
                            error = "Select an account first"
                            return@IconButton
                        }
                        sending = true
                        scope.launch {
                            controller.send(
                                UiDraft(
                                    to = splitAddresses(to),
                                    cc = splitAddresses(cc),
                                    subject = subject.trim(),
                                    body = body
                                )
                            ).fold(
                                onSuccess = { sending = false; onSent() },
                                onFailure = { failure -> sending = false; error = failure.message ?: "Sending failed" }
                            )
                        }
                    },
                    enabled = canSend
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.Send,
                        contentDescription = "Send",
                        tint = if (canSend) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline.copy(alpha = 0.4f)
                    )
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))

        if (scheduleOpen) {
            ScheduleDialog(
                onDismiss = { scheduleOpen = false },
                onSchedule = { atMs ->
                    scheduleOpen = false
                    val account = activeAccount
                    if (account != null) {
                        scope.launch {
                            controller.sendScheduled(
                                UiDraft(
                                    to = splitAddresses(to),
                                    cc = splitAddresses(cc),
                                    subject = subject.trim(),
                                    body = body
                                ),
                                atMs
                            ).fold(
                                onSuccess = { feedback = "Scheduled — will send later" },
                                onFailure = { error = it.message ?: "Scheduling failed" }
                            )
                        }
                    }
                }
            )
        }

        if (attachOpen) {
            androidx.compose.material3.AlertDialog(
                onDismissRequest = { attachOpen = false },
                title = { Text("Attachments") },
                text = { Text("Attachments are coming soon in this build. You can still send plain text and quoted replies.") },
                confirmButton = { androidx.compose.material3.TextButton(onClick = { attachOpen = false }) { Text("OK") } }
            )
        }

        Column(
            modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(0.dp)
        ) {
            // From — Gmail shows sender avatar + email + dropdown
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
                Text("From", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(48.dp))
                Text(
                    activeAccount?.email ?: "No account selected",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))

            // To — Gmail uses chips; we keep single field with placeholder but styled minimal
            GmailRecipientField(
                label = "To",
                value = to,
                onValueChange = { to = it },
                placeholder = "Recipients",
                testTag = "field-to"
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))

            // Cc/Bcc — collapsed by default like Gmail
            if (!ccExpanded) {
                Text(
                    "Cc/Bcc",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable { ccExpanded = true }.padding(vertical = 8.dp)
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))
            } else {
                GmailRecipientField(
                    label = "Cc",
                    value = cc,
                    onValueChange = { cc = it },
                    placeholder = "Cc",
                    testTag = "field-cc"
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))
            }

            GmailSubjectField(
                value = subject,
                onValueChange = { subject = it },
                placeholder = "Subject",
                testTag = "field-subject"
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))

            GmailBodyField(
                value = body,
                onValueChange = { body = it },
                placeholder = "Compose email",
                testTag = "field-body"
            )

            InlineError(error)
            feedback?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun GmailRecipientField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    testTag: String
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(48.dp)
        )
        TextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = { Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color.Transparent,
                unfocusedContainerColor = Color.Transparent,
                disabledContainerColor = Color.Transparent,
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
                disabledIndicatorColor = Color.Transparent
            ),
            modifier = Modifier.weight(1f).testTag(testTag)
        )
    }
}

@Composable
private fun GmailSubjectField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    testTag: String
) {
    TextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline) },
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyMedium,
        colors = TextFieldDefaults.colors(
            focusedContainerColor = Color.Transparent,
            unfocusedContainerColor = Color.Transparent,
            disabledContainerColor = Color.Transparent,
            focusedIndicatorColor = Color.Transparent,
            unfocusedIndicatorColor = Color.Transparent,
            disabledIndicatorColor = Color.Transparent
        ),
        modifier = Modifier.fillMaxWidth().testTag(testTag)
    )
}

@Composable
private fun GmailBodyField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    testTag: String
) {
    TextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline) },
        textStyle = MaterialTheme.typography.bodyMedium.copy(lineHeight = 20.sp),
        colors = TextFieldDefaults.colors(
            focusedContainerColor = Color.Transparent,
            unfocusedContainerColor = Color.Transparent,
            disabledContainerColor = Color.Transparent,
            focusedIndicatorColor = Color.Transparent,
            unfocusedIndicatorColor = Color.Transparent,
            disabledIndicatorColor = Color.Transparent
        ),
        modifier = Modifier.fillMaxWidth().height(320.dp).testTag(testTag)
    )
}

internal fun prefilledTo(replyTo: UiMessage?, mode: UiComposeMode): String =
    when (mode) {
        UiComposeMode.REPLY, UiComposeMode.REPLY_ALL -> replyTo?.fromAddress ?: ""
        else -> ""
    }

internal fun prefilledCc(replyTo: UiMessage?, mode: UiComposeMode): String =
    if (mode == UiComposeMode.REPLY_ALL) replyTo?.ccCsv.orEmpty() else ""

internal fun prefilledSubject(replyTo: UiMessage?, mode: UiComposeMode): String {
    replyTo ?: return ""
    return when (mode) {
        UiComposeMode.FORWARD ->
            if (replyTo.subject.startsWith("Fwd:", true)) replyTo.subject else "Fwd: ${replyTo.subject}"
        else ->
            if (replyTo.subject.startsWith("Re:", true)) replyTo.subject else "Re: ${replyTo.subject}"
    }
}

internal fun prefilledBody(replyTo: UiMessage?, mode: UiComposeMode): String {
    replyTo ?: return ""
    val header = when (mode) {
        UiComposeMode.FORWARD -> "---------- Forwarded message ----------\nFrom: ${replyTo.fromAddress}\n"
        else -> "\n\nOn ${formatTimestamp(replyTo.dateEpochMs)}, ${replyTo.fromName ?: replyTo.fromAddress} wrote:\n"
    }
    val quoted = (replyTo.bodyText ?: replyTo.snippet)
        .split('\n')
        .joinToString("\n") { "> $it" }
    return "$header$quoted"
}

internal fun splitAddresses(raw: String): List<String> =
    raw.split(',', ';', ' ')
        .map { it.trim() }
        .filter { it.contains('@') }

@Composable
private fun ScheduleDialog(
    onDismiss: () -> Unit,
    onSchedule: (Long) -> Unit
) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Schedule send") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                ScheduleOption("In 1 hour") { onSchedule(System.currentTimeMillis() + 3_600_000L) }
                ScheduleOption("Tomorrow 8:00") { onSchedule(tomorrowAtHour(8)) }
                ScheduleOption("Tomorrow 13:00") { onSchedule(tomorrowAtHour(13)) }
                ScheduleOption("Next Monday 9:00") { onSchedule(nextMondayAtHour(9)) }
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun ScheduleOption(label: String, onClick: () -> Unit) {
    androidx.compose.material3.OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) { Text(label) }
}

private fun tomorrowAtHour(hour: Int): Long {
    val cal = java.util.Calendar.getInstance()
    cal.add(java.util.Calendar.DAY_OF_YEAR, 1)
    cal.set(java.util.Calendar.HOUR_OF_DAY, hour)
    cal.set(java.util.Calendar.MINUTE, 0)
    cal.set(java.util.Calendar.SECOND, 0)
    cal.set(java.util.Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}

private fun nextMondayAtHour(hour: Int): Long {
    val cal = java.util.Calendar.getInstance()
    var diff = (java.util.Calendar.MONDAY - cal.get(java.util.Calendar.DAY_OF_WEEK) + 7) % 7
    if (diff == 0) diff = 7
    cal.add(java.util.Calendar.DAY_OF_YEAR, diff)
    cal.set(java.util.Calendar.HOUR_OF_DAY, hour)
    cal.set(java.util.Calendar.MINUTE, 0)
    cal.set(java.util.Calendar.SECOND, 0)
    cal.set(java.util.Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}
