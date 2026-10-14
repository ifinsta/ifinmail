package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Forward
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.automirrored.filled.ReplyAll
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.mail.UiSmartReply
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.InlineError
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.components.StarToggle
import com.ifinmail.app.shared.ui.components.StatusBadge
import com.ifinmail.app.shared.ui.components.avatarColorFor
import kotlinx.coroutines.launch
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.action_back
import com.ifinmail.app.shared.resources.action_cancel
import com.ifinmail.app.shared.resources.action_delete
import com.ifinmail.app.shared.resources.attachment_badge
import com.ifinmail.app.shared.resources.could_not_delete
import com.ifinmail.app.shared.resources.could_not_open
import com.ifinmail.app.shared.resources.could_not_snooze
import com.ifinmail.app.shared.resources.forward
import com.ifinmail.app.shared.resources.in_one_hour
import com.ifinmail.app.shared.resources.mark_as_read
import com.ifinmail.app.shared.resources.mark_as_unread
import com.ifinmail.app.shared.resources.more_options
import com.ifinmail.app.shared.resources.no_content
import com.ifinmail.app.shared.resources.no_subject
import com.ifinmail.app.shared.resources.reply
import com.ifinmail.app.shared.resources.reply_all
import com.ifinmail.app.shared.resources.smart_reply
import com.ifinmail.app.shared.resources.snooze
import com.ifinmail.app.shared.resources.snooze_next_monday
import com.ifinmail.app.shared.resources.snooze_tomorrow_afternoon
import com.ifinmail.app.shared.resources.snooze_tomorrow_morning
import com.ifinmail.app.shared.resources.snooze_until
import com.ifinmail.app.shared.resources.to_me
import com.ifinmail.app.shared.resources.to_recipients
import org.jetbrains.compose.resources.stringResource
import org.jetbrains.compose.resources.getString

@Composable
fun MessageDetailScreen(
    controller: MailController,
    messageId: String,
    onReply: (UiMessage, String) -> Unit,
    onSmartReply: (UiMessage, String) -> Unit,
    onDeleteDone: () -> Unit,
    onBack: () -> Unit
) {
    val messages by controller.messages.collectAsState()
    val scope = rememberCoroutineScope()
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var actionError by remember { mutableStateOf<String?>(null) }
    var loaded by remember { mutableStateOf<UiMessage?>(null) }
    var menuOpen by remember { mutableStateOf(false) }
    var snoozeOpen by remember { mutableStateOf(false) }

    LaunchedEffect(messageId) {
        controller.openMessage(messageId).fold(
            onSuccess = { opened ->
                loaded = opened
                loading = false
            },
            onFailure = { failure ->
                loadError = failure.message ?: getString(Res.string.could_not_open)
                loading = false
            }
        )
    }

    // The body comes from the one-off load, but read/starred state must follow the live list or
    // the star would never change after it is tapped.
    val live = messages.firstOrNull { it.id == messageId }
    val message = loaded?.let { snapshot ->
        if (live == null) snapshot else snapshot.copy(flagged = live.flagged, read = live.read)
    } ?: live

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surface)
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp)
        ) {
            MaterialIconAction(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(Res.string.action_back),
                tint = MaterialTheme.colorScheme.onSurface,
                onClick = onBack
            )
            Spacer(Modifier.weight(1f))
            if (message != null) {
                StarToggle(starred = message.flagged, onToggle = {
                    scope.launch { controller.setMessageFlagged(message.id, !message.flagged) }
                })
            }
            Box {
                MaterialIconAction(
                    imageVector = Icons.Default.MoreVert,
                    contentDescription = stringResource(Res.string.more_options),
                    onClick = { menuOpen = true }
                )
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    DropdownMenuItem(
                        text = {
                            Text(
                                stringResource(
                                    if (message?.read == true) Res.string.mark_as_unread else Res.string.mark_as_read
                                )
                            )
                        },
                        onClick = {
                            menuOpen = false
                            val target = message ?: return@DropdownMenuItem
                            scope.launch { controller.setMessageRead(target.id, !target.read) }
                        }
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(Res.string.snooze)) },
                        onClick = {
                            menuOpen = false
                            snoozeOpen = true
                        }
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(Res.string.action_delete), color = MaterialTheme.colorScheme.error) },
                        onClick = {
                            menuOpen = false
                            val target = message ?: return@DropdownMenuItem
                            scope.launch {
                                controller.deleteMessage(target.id).fold(
                                    onSuccess = { onDeleteDone() },
                                    onFailure = { actionError = it.message ?: getString(Res.string.could_not_delete) }
                                )
                            }
                        }
                    )
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

        if (snoozeOpen && message != null) {
            SnoozeDialog(
                onDismiss = { snoozeOpen = false },
                onSnooze = { ms ->
                    snoozeOpen = false
                    scope.launch {
                        controller.snooze(message.id, ms).fold(
                            onSuccess = { onDeleteDone() },
                            onFailure = { actionError = it.message ?: getString(Res.string.could_not_snooze) }
                        )
                    }
                }
            )
        }

        Column(modifier = Modifier.padding(horizontal = 16.dp).padding(top = 8.dp)) {
            InlineError(actionError)
        }

        when {
            message != null -> MessageBody(message, controller, onReply, onSmartReply)

            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
            }

            loadError != null -> Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                Text(
                    loadError.orEmpty(),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MessageBody(
    message: UiMessage,
    controller: MailController,
    onReply: (UiMessage, String) -> Unit,
    onSmartReply: (UiMessage, String) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 16.dp)
    ) {
        Text(
            message.subject.ifBlank { stringResource(Res.string.no_subject) },
            style = MaterialTheme.typography.headlineMedium
        )
        Spacer(Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            AvatarCircle(
                message.fromName ?: message.fromAddress,
                size = 40,
                tint = Color.White,
                container = avatarColorFor(message.fromAddress)
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    message.fromName ?: message.fromAddress,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    if (message.toCsv.isBlank()) {
                        stringResource(Res.string.to_me)
                    } else {
                        stringResource(Res.string.to_recipients, message.toCsv)
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (message.hasAttachments) {
                Spacer(Modifier.width(8.dp))
                StatusBadge(
                    stringResource(Res.string.attachment_badge),
                    tint = MaterialTheme.colorScheme.onTertiaryContainer,
                    background = MaterialTheme.colorScheme.tertiaryContainer
                )
            }
        }
        Text(
            formatDateTime(message.dateEpochMs, rememberDateLabels()),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp, start = 52.dp)
        )
        HorizontalDivider(
            color = MaterialTheme.colorScheme.outlineVariant,
            modifier = Modifier.padding(vertical = 16.dp)
        )

        val bodyText = message.bodyText
        val bodyHtml = message.bodyHtml
        when {
            !bodyText.isNullOrBlank() -> SelectionContainer {
                Text(bodyText, style = MaterialTheme.typography.bodyLarge)
            }

            bodyHtml != null -> HtmlContentView(bodyHtml)

            else -> Text(
                stringResource(Res.string.no_content),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        Spacer(Modifier.height(24.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(16.dp))

        var smartReplies by remember(message.id) { mutableStateOf<List<UiSmartReply>?>(null) }
        LaunchedEffect(message.id) {
            smartReplies = runCatching { controller.smartReplies(message.id) }.getOrNull()
        }
        smartReplies?.takeIf { it.isNotEmpty() }?.let { replies ->
            Text(
                stringResource(Res.string.smart_reply),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(8.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                replies.forEach { reply ->
                    OutlinedButton(
                        onClick = { onSmartReply(message, reply.body) },
                        shape = MaterialTheme.shapes.large
                    ) { Text(reply.label) }
                }
            }
            Spacer(Modifier.height(16.dp))
        }

        // Three equal actions on a ~360dp screen leave about 100dp each, so the padding is trimmed
        // and the labels are single-line to keep "Reply all" from wrapping.
        val actionPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
        val replyDescription = stringResource(Res.string.reply)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = { onReply(message, "reply") },
                shape = MaterialTheme.shapes.medium,
                contentPadding = actionPadding,
                modifier = Modifier.weight(1f).semantics { contentDescription = replyDescription }
            ) {
                Icon(Icons.AutoMirrored.Filled.Reply, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(Res.string.reply), maxLines = 1)
            }
            OutlinedButton(
                onClick = { onReply(message, "reply_all") },
                shape = MaterialTheme.shapes.medium,
                contentPadding = actionPadding,
                modifier = Modifier.weight(1f)
            ) {
                Icon(Icons.AutoMirrored.Filled.ReplyAll, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(Res.string.reply_all), maxLines = 1)
            }
            OutlinedButton(
                onClick = { onReply(message, "forward") },
                shape = MaterialTheme.shapes.medium,
                contentPadding = actionPadding,
                modifier = Modifier.weight(1f)
            ) {
                Icon(Icons.AutoMirrored.Filled.Forward, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(Res.string.forward), maxLines = 1)
            }
        }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
internal expect fun HtmlContentView(html: String)

@Composable
private fun SnoozeDialog(
    onDismiss: () -> Unit,
    onSnooze: (Long) -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(Res.string.snooze_until)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SnoozeOption(stringResource(Res.string.in_one_hour)) { onSnooze(System.currentTimeMillis() + 3_600_000L) }
                SnoozeOption(stringResource(Res.string.snooze_tomorrow_morning)) { onSnooze(tomorrowAt(9)) }
                SnoozeOption(stringResource(Res.string.snooze_tomorrow_afternoon)) { onSnooze(tomorrowAt(15)) }
                SnoozeOption(stringResource(Res.string.snooze_next_monday)) { onSnooze(nextWeekdayAt(java.util.Calendar.MONDAY, 9)) }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(Res.string.action_cancel)) }
        }
    )
}

@Composable
private fun SnoozeOption(label: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) { Text(label) }
}

private fun tomorrowAt(hour: Int): Long {
    val cal = java.util.Calendar.getInstance()
    cal.add(java.util.Calendar.DAY_OF_YEAR, 1)
    cal.set(java.util.Calendar.HOUR_OF_DAY, hour)
    cal.set(java.util.Calendar.MINUTE, 0)
    cal.set(java.util.Calendar.SECOND, 0)
    cal.set(java.util.Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}

private fun nextWeekdayAt(weekday: Int, hour: Int): Long {
    val cal = java.util.Calendar.getInstance()
    val current = cal.get(java.util.Calendar.DAY_OF_WEEK)
    var diff = (weekday - current + 7) % 7
    if (diff == 0) diff = 7
    cal.add(java.util.Calendar.DAY_OF_YEAR, diff)
    cal.set(java.util.Calendar.HOUR_OF_DAY, hour)
    cal.set(java.util.Calendar.MINUTE, 0)
    cal.set(java.util.Calendar.SECOND, 0)
    cal.set(java.util.Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}
