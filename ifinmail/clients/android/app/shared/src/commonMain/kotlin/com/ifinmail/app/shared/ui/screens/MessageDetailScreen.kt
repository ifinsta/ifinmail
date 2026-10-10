package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiMessage
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Forward
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.filled.MoreVert
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.components.StatusBadge
import com.ifinmail.app.shared.ui.components.StarToggle
import kotlinx.coroutines.launch

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
    var current by remember { mutableStateOf<UiMessage?>(null) }
    var menuOpen by remember { mutableStateOf(false) }
    var snoozeOpen by remember { mutableStateOf(false) }

    LaunchedEffect(messageId) {
        controller.openMessage(messageId).fold(
            onSuccess = { loaded ->
                current = loaded
                loading = false
            },
            onFailure = { failure ->
                loadError = failure.message
                loading = false
            }
        )
    }

    val message = current ?: messages.firstOrNull { it.id == messageId }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .background(MaterialTheme.colorScheme.background)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp)
        ) {
            MaterialIconAction(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "Back",
                tint = MaterialTheme.colorScheme.onSurface,
                onClick = onBack
            )
            Spacer(Modifier.weight(1f))
            if (message != null) {
                val nextFlagged = !message.flagged
                StarToggle(starred = message.flagged, onToggle = {
                    scope.launch { controller.setMessageFlagged(message.id, nextFlagged) }
                })
            }
            Box {
                MaterialIconAction(
                    imageVector = Icons.Default.MoreVert,
                    contentDescription = "More options",
                    onClick = { menuOpen = true }
                )
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    DropdownMenuItem(
                        text = { Text(if (message?.read == true) "Mark as unread" else "Mark as read") },
                        onClick = {
                            menuOpen = false
                            val target = message ?: return@DropdownMenuItem
                            scope.launch { controller.setMessageRead(target.id, !(target.read)) }
                        }
                    )
                    DropdownMenuItem(
                        text = { Text("Snooze") },
                        onClick = {
                            menuOpen = false
                            val target = message ?: return@DropdownMenuItem
                            snoozeOpen = true
                        }
                    )
                    DropdownMenuItem(
                        text = { Text("Delete", color = MaterialTheme.colorScheme.error) },
                        onClick = {
                            menuOpen = false
                            val target = message ?: return@DropdownMenuItem
                            scope.launch {
                                controller.deleteMessage(target.id).fold(
                                    onSuccess = { onDeleteDone() },
                                    onFailure = { loadError = it.message }
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
                    scope.launch { controller.snooze(message.id, ms).fold(onSuccess = { onDeleteDone() }, onFailure = { loadError = it.message }) }
                }
            )
        }

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

        when {
            loading && message == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
            }
            loadError != null && message == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(loadError!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            message != null -> MessageBody(message!!, controller, onReply, onSmartReply)
        }
    }
}

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
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                message.subject,
                style = MaterialTheme.typography.headlineMedium,
                modifier = Modifier.weight(1f)
            )
        }
        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            AvatarCircle(
                message.fromName ?: message.fromAddress,
                size = 40,
                tint = androidx.compose.ui.graphics.Color.White,
                container = com.ifinmail.app.shared.ui.components.avatarColorFor(message.fromAddress)
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    message.fromName ?: message.fromAddress,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    message.toCsv.ifBlank { "to me" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (message.hasAttachments) {
                StatusBadge(
                    "attachment",
                    tint = MaterialTheme.colorScheme.tertiary,
                    background = MaterialTheme.colorScheme.tertiaryContainer
                )
                Spacer(Modifier.width(8.dp))
            }
            Text(
                formatTimestamp(message.dateEpochMs),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.outline
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(vertical = 14.dp))

        val bodyText = message.bodyText
        if (!bodyText.isNullOrBlank()) {
            Text(bodyText, style = MaterialTheme.typography.bodyLarge)
        } else if (message.bodyHtml != null) {
            HtmlContentView(message.bodyHtml!!)
        }

        Spacer(Modifier.height(24.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(12.dp))
        var smartReplies by remember(message.id) { mutableStateOf<List<com.ifinmail.app.shared.mail.UiSmartReply>?>(null) }
        LaunchedEffect(message.id) {
            smartReplies = runCatching { controller.smartReplies(message.id) }.getOrNull()
        }
        smartReplies?.takeIf { it.isNotEmpty() }?.let { replies ->
            Text("Smart reply", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(8.dp))
            androidx.compose.foundation.layout.FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                replies.forEach { reply ->
                    androidx.compose.material3.OutlinedButton(
                        onClick = { onSmartReply(message, reply.body) },
                        shape = MaterialTheme.shapes.large
                    ) { Text(reply.label) }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = { onReply(message, "reply") },
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.weight(1f).semantics { contentDescription = "Reply" }
            ) {
                androidx.compose.material3.Icon(Icons.AutoMirrored.Filled.Reply, null, modifier = androidx.compose.ui.Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Reply")
            }
            OutlinedButton(
                onClick = { onReply(message, "reply_all") },
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.weight(1f)
            ) {
                androidx.compose.material3.Icon(Icons.AutoMirrored.Filled.Reply, null, modifier = androidx.compose.ui.Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Reply all")
            }
            OutlinedButton(
                onClick = { onReply(message, "forward") },
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.weight(1f)
            ) {
                androidx.compose.material3.Icon(Icons.AutoMirrored.Filled.Forward, null, modifier = androidx.compose.ui.Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Forward")
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
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Snooze until") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                SnoozeOption("In 1 hour") { onSnooze(System.currentTimeMillis() + 3_600_000L) }
                SnoozeOption("Tomorrow morning") { onSnooze(tomorrowAt(9)) }
                SnoozeOption("Tomorrow afternoon") { onSnooze(tomorrowAt(15)) }
                SnoozeOption("Next Monday") { onSnooze(nextWeekdayAt(2, 9)) }
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun SnoozeOption(label: String, onClick: () -> Unit) {
    androidx.compose.material3.OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) { Text(label) }
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
