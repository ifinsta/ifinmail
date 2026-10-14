package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.ui.components.InlineError
import com.ifinmail.app.shared.ui.platform.PlatformBackHandler
import kotlinx.coroutines.launch
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.action_cancel
import com.ifinmail.app.shared.resources.action_close
import com.ifinmail.app.shared.resources.action_discard
import com.ifinmail.app.shared.resources.cc_bcc
import com.ifinmail.app.shared.resources.compose
import com.ifinmail.app.shared.resources.discard_message
import com.ifinmail.app.shared.resources.discard_title
import com.ifinmail.app.shared.resources.draft_save_failed
import com.ifinmail.app.shared.resources.draft_saved
import com.ifinmail.app.shared.resources.field_cc
import com.ifinmail.app.shared.resources.field_from
import com.ifinmail.app.shared.resources.field_to
import com.ifinmail.app.shared.resources.forward
import com.ifinmail.app.shared.resources.in_one_hour
import com.ifinmail.app.shared.resources.keep_editing
import com.ifinmail.app.shared.resources.more_options
import com.ifinmail.app.shared.resources.no_account_selected
import com.ifinmail.app.shared.resources.placeholder_body
import com.ifinmail.app.shared.resources.placeholder_recipients
import com.ifinmail.app.shared.resources.placeholder_subject
import com.ifinmail.app.shared.resources.quote_forwarded_header
import com.ifinmail.app.shared.resources.quote_reply_header
import com.ifinmail.app.shared.resources.reply
import com.ifinmail.app.shared.resources.save_draft
import com.ifinmail.app.shared.resources.schedule_failed
import com.ifinmail.app.shared.resources.schedule_next_monday_9
import com.ifinmail.app.shared.resources.schedule_send
import com.ifinmail.app.shared.resources.schedule_tomorrow_13
import com.ifinmail.app.shared.resources.schedule_tomorrow_8
import com.ifinmail.app.shared.resources.select_account_first
import com.ifinmail.app.shared.resources.send
import com.ifinmail.app.shared.resources.send_failed
import org.jetbrains.compose.resources.stringResource
import org.jetbrains.compose.resources.getString

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

    val dateLabels = rememberDateLabels()
    val quoteHeader = when {
        replyTo == null -> ""
        mode == UiComposeMode.FORWARD -> stringResource(Res.string.quote_forwarded_header, replyTo.fromAddress)
        else -> stringResource(
            Res.string.quote_reply_header,
            formatDateTime(replyTo.dateEpochMs, dateLabels),
            replyTo.fromName ?: replyTo.fromAddress
        )
    }

    val seedTo = initialDraft?.to?.joinToString(", ") ?: prefilledTo(replyTo, mode)
    val seedCc = initialDraft?.cc?.joinToString(", ") ?: prefilledCc(replyTo, mode)
    val seedSubject = initialDraft?.subject ?: prefilledSubject(replyTo, mode)
    val seedBody = initialBody ?: initialDraft?.body ?: prefilledBody(replyTo, quoteHeader)

    var to by remember { mutableStateOf(seedTo) }
    var cc by remember { mutableStateOf(seedCc) }
    var ccExpanded by remember { mutableStateOf(cc.isNotBlank()) }
    var subject by remember { mutableStateOf(seedSubject) }
    var body by remember { mutableStateOf(seedBody) }
    var sending by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var scheduleOpen by remember { mutableStateOf(false) }
    var moreOpen by remember { mutableStateOf(false) }
    var discardOpen by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    val snackbarHost = remember { SnackbarHostState() }
    val selectAccountFirst = stringResource(Res.string.select_account_first)

    val canSend = to.trim().isNotBlank() && (subject.trim().isNotBlank() || body.trim().isNotBlank())
    val canSave = subject.isNotBlank() || body.isNotBlank()
    val edited = to != seedTo || cc != seedCc || subject != seedSubject || body != seedBody
    val hasUnsavedEdits = edited && canSave && !saved && !sending

    fun requestClose() {
        if (hasUnsavedEdits) discardOpen = true else onCancel()
    }

    fun currentDraft(withId: Boolean) = UiDraft(
        to = splitAddresses(to),
        cc = splitAddresses(cc),
        subject = subject.trim(),
        body = body,
        id = if (withId) initialDraft?.id ?: "" else ""
    )

    fun saveDraft(thenClose: Boolean = false) {
        if (activeAccount == null) {
            error = selectAccountFirst
            return
        }
        scope.launch {
            controller.saveDraft(currentDraft(withId = true)).fold(
                onSuccess = {
                    saved = true
                    if (thenClose) onCancel() else snackbarHost.showSnackbar(getString(Res.string.draft_saved))
                },
                onFailure = { snackbarHost.showSnackbar(getString(Res.string.draft_save_failed)) }
            )
        }
    }

    // Edits made after a save make the draft dirty again.
    LaunchedEffect(to, cc, subject, body) { saved = false }

    PlatformBackHandler(enabled = hasUnsavedEdits) { discardOpen = true }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surface)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.statusBars)
                .windowInsetsPadding(WindowInsets.navigationBars)
                .imePadding()
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp)
            ) {
                IconButton(onClick = ::requestClose) {
                    Icon(Icons.Default.Close, contentDescription = stringResource(Res.string.action_close), tint = MaterialTheme.colorScheme.onSurface)
                }
                Text(
                    when (mode) {
                        UiComposeMode.FORWARD -> stringResource(Res.string.forward)
                        UiComposeMode.REPLY, UiComposeMode.REPLY_ALL -> stringResource(Res.string.reply)
                        else -> stringResource(Res.string.compose)
                    },
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.padding(start = 4.dp)
                )
                Spacer(Modifier.weight(1f))
                if (sending) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(13.dp).size(22.dp),
                        strokeWidth = 2.dp
                    )
                } else {
                    IconButton(
                        onClick = { scheduleOpen = true },
                        enabled = canSend
                    ) {
                        Icon(
                            Icons.Default.Schedule,
                            contentDescription = stringResource(Res.string.schedule_send),
                            tint = if (canSend) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.outlineVariant
                        )
                    }
                    IconButton(
                        onClick = {
                            if (activeAccount == null) {
                                error = selectAccountFirst
                                return@IconButton
                            }
                            error = null
                            sending = true
                            scope.launch {
                                controller.send(currentDraft(withId = false)).fold(
                                    onSuccess = { sending = false; onSent() },
                                    onFailure = { failure -> sending = false; error = failure.message ?: getString(Res.string.send_failed) }
                                )
                            }
                        },
                        enabled = canSend
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.Send,
                            contentDescription = stringResource(Res.string.send),
                            tint = if (canSend) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant
                        )
                    }
                }
                Box {
                    IconButton(onClick = { moreOpen = true }) {
                        Icon(
                            Icons.Default.MoreVert,
                            contentDescription = stringResource(Res.string.more_options),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    DropdownMenu(expanded = moreOpen, onDismissRequest = { moreOpen = false }) {
                        DropdownMenuItem(
                            text = { Text(stringResource(Res.string.save_draft)) },
                            leadingIcon = { Icon(Icons.Default.Save, contentDescription = null) },
                            enabled = canSave,
                            onClick = {
                                moreOpen = false
                                saveDraft()
                            }
                        )
                    }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp)
            ) {
                FieldRow(label = stringResource(Res.string.field_from)) {
                    Text(
                        activeAccount?.email ?: stringResource(Res.string.no_account_selected),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(start = 16.dp, top = 14.dp, bottom = 14.dp)
                    )
                }
                FieldDivider()

                FieldRow(label = stringResource(Res.string.field_to)) {
                    ComposeTextField(
                        value = to,
                        onValueChange = { to = it },
                        placeholder = stringResource(Res.string.placeholder_recipients),
                        testTag = "field-to",
                        keyboardType = KeyboardType.Email,
                        modifier = Modifier.weight(1f)
                    )
                }
                FieldDivider()

                if (!ccExpanded) {
                    Box(
                        contentAlignment = Alignment.CenterStart,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .clickable(role = Role.Button) { ccExpanded = true }
                    ) {
                        Text(
                            stringResource(Res.string.cc_bcc),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                } else {
                    FieldRow(label = stringResource(Res.string.field_cc)) {
                        ComposeTextField(
                            value = cc,
                            onValueChange = { cc = it },
                            placeholder = stringResource(Res.string.field_cc),
                            testTag = "field-cc",
                            keyboardType = KeyboardType.Email,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
                FieldDivider()

                ComposeTextField(
                    value = subject,
                    onValueChange = { subject = it },
                    placeholder = stringResource(Res.string.placeholder_subject),
                    testTag = "field-subject",
                    capitalization = KeyboardCapitalization.Sentences,
                    modifier = Modifier.fillMaxWidth()
                )
                FieldDivider()

                ComposeTextField(
                    value = body,
                    onValueChange = { body = it },
                    placeholder = stringResource(Res.string.placeholder_body),
                    testTag = "field-body",
                    singleLine = false,
                    capitalization = KeyboardCapitalization.Sentences,
                    imeAction = ImeAction.Default,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 240.dp)
                )

                InlineError(error)
                Spacer(Modifier.height(24.dp))
            }
        }

        SnackbarHost(
            hostState = snackbarHost,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .windowInsetsPadding(WindowInsets.navigationBars)
                .imePadding()
                .padding(16.dp)
        )
    }

    if (scheduleOpen) {
        ScheduleDialog(
            onDismiss = { scheduleOpen = false },
            onSchedule = { atMs ->
                scheduleOpen = false
                if (activeAccount == null) {
                    error = selectAccountFirst
                } else {
                    scope.launch {
                        controller.sendScheduled(currentDraft(withId = false), atMs).fold(
                            onSuccess = { onSent() },
                            onFailure = { error = it.message ?: getString(Res.string.schedule_failed) }
                        )
                    }
                }
            }
        )
    }

    if (discardOpen) {
        AlertDialog(
            onDismissRequest = { discardOpen = false },
            title = { Text(stringResource(Res.string.discard_title)) },
            text = { Text(stringResource(Res.string.discard_message)) },
            confirmButton = {
                TextButton(onClick = { discardOpen = false; saveDraft(thenClose = true) }) { Text(stringResource(Res.string.save_draft)) }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { discardOpen = false }) { Text(stringResource(Res.string.keep_editing)) }
                    TextButton(
                        onClick = { discardOpen = false; onCancel() }
                    ) { Text(stringResource(Res.string.action_discard), color = MaterialTheme.colorScheme.error) }
                }
            }
        )
    }
}

/** A labelled row in the header block (From / To / Cc), at least 48dp tall. */
@Composable
private fun FieldRow(label: String, content: @Composable RowScope.() -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(48.dp)
        )
        content()
    }
}

@Composable
private fun FieldDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

@Composable
private fun ComposeTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    testTag: String,
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Text,
    capitalization: KeyboardCapitalization = KeyboardCapitalization.None,
    imeAction: ImeAction = ImeAction.Next
) {
    TextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = {
            Text(
                placeholder,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        },
        singleLine = singleLine,
        textStyle = MaterialTheme.typography.bodyMedium.copy(lineHeight = 22.sp),
        keyboardOptions = KeyboardOptions.Default.copy(
            keyboardType = keyboardType,
            capitalization = capitalization,
            imeAction = imeAction
        ),
        colors = TextFieldDefaults.colors(
            focusedContainerColor = Color.Transparent,
            unfocusedContainerColor = Color.Transparent,
            disabledContainerColor = Color.Transparent,
            focusedIndicatorColor = Color.Transparent,
            unfocusedIndicatorColor = Color.Transparent,
            disabledIndicatorColor = Color.Transparent
        ),
        modifier = modifier.testTag(testTag)
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

internal fun prefilledBody(replyTo: UiMessage?, quoteHeader: String): String {
    replyTo ?: return ""
    val quoted = (replyTo.bodyText ?: replyTo.snippet)
        .split('\n')
        .joinToString("\n") { "> $it" }
    return "$quoteHeader$quoted"
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
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(Res.string.schedule_send)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ScheduleOption(stringResource(Res.string.in_one_hour)) { onSchedule(System.currentTimeMillis() + 3_600_000L) }
                ScheduleOption(stringResource(Res.string.schedule_tomorrow_8)) { onSchedule(tomorrowAtHour(8)) }
                ScheduleOption(stringResource(Res.string.schedule_tomorrow_13)) { onSchedule(tomorrowAtHour(13)) }
                ScheduleOption(stringResource(Res.string.schedule_next_monday_9)) { onSchedule(nextMondayAtHour(9)) }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(Res.string.action_cancel)) }
        }
    )
}

@Composable
private fun ScheduleOption(label: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) { Text(label) }
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
