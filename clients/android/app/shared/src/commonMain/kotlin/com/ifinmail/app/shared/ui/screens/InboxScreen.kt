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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.core.domain.search.matches
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.components.StarToggle
import com.ifinmail.app.shared.ui.components.avatarColorFor
import kotlinx.coroutines.launch

@Composable
fun InboxScreen(
    controller: MailController,
    onOpenMessage: (String) -> Unit,
    onCompose: () -> Unit,
    onManageAccounts: () -> Unit,
    onAddAccount: () -> Unit,
    onOpenDrafts: () -> Unit
) {
    val accounts by controller.accounts.collectAsState()
    val messages by controller.messages.collectAsState()
    val activeAccountId by controller.activeAccountId.collectAsState()
    val busy by controller.isBusy.collectAsState()
    val queuedCount by controller.queuedCount.collectAsState()
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(androidx.compose.material3.DrawerValue.Closed)
    var selectedMailbox by remember { mutableStateOf("Inbox") }
    var searchQuery by remember { mutableStateOf("") }
    var accountMenuOpen by remember { mutableStateOf(false) }
    var refreshError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(activeAccountId) {
        if (activeAccountId != null && messages.isEmpty()) {
            controller.refresh().fold(onSuccess = {}, onFailure = { refreshError = it.message })
        }
    }

    var nowTick by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(60_000)
            nowTick = System.currentTimeMillis()
        }
    }
    val visibleMessages = remember(messages, nowTick, selectedMailbox) {
        val base = messages.filter { it.snoozedUntilMs == null || it.snoozedUntilMs <= nowTick }
        when (selectedMailbox) {
            "Starred" -> base.filter { it.flagged }
            "Snoozed" -> messages.filter { it.snoozedUntilMs != null && it.snoozedUntilMs > nowTick }
            else -> base
        }
    }

    val draftsCount by controller.drafts.collectAsState()
    var capabilityNote by remember { mutableStateOf<String?>(null) }
    var groupByThread by rememberSaveable { mutableStateOf(true) }
    val threads = remember(visibleMessages) {
        visibleMessages.groupBy { it.threadId.ifBlank { it.id } }.values
            .sortedByDescending { ms -> ms.maxOfOrNull { it.dateEpochMs ?: 0L } }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = MaterialTheme.colorScheme.surface,
                drawerContentColor = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(300.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))
                        .padding(horizontal = 20.dp, vertical = 24.dp)
                ) {
                    Text(
                        "ifinmail",
                        style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.height(4.dp))
                    accounts.firstOrNull { it.id == activeAccountId }?.let {
                        Text(it.email, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } ?: Text("No account selected", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                Spacer(Modifier.height(4.dp))
                DrawerItem(icon = Icons.Default.Inbox, label = "Inbox", badge = messages.count { !it.read }, selected = selectedMailbox == "Inbox") {
                    selectedMailbox = "Inbox"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.Star, label = "Starred", badge = messages.count { it.flagged }, selected = selectedMailbox == "Starred") {
                    selectedMailbox = "Starred"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.DateRange, label = "Snoozed", badge = messages.count { it.snoozedUntilMs != null && it.snoozedUntilMs > System.currentTimeMillis() }, selected = selectedMailbox == "Snoozed") {
                    selectedMailbox = "Snoozed"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.Send, label = "Sent", badge = 0, selected = selectedMailbox == "Sent") {
                    selectedMailbox = "Sent"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.Edit, label = "Drafts", badge = draftsCount.size, selected = selectedMailbox == "Drafts") {
                    scope.launch { drawerState.close() }; onOpenDrafts()
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f), modifier = Modifier.padding(vertical = 4.dp))
                DrawerItem(icon = Icons.Default.MailOutline, label = "All Mail", badge = 0, selected = selectedMailbox == "All Mail") {
                    selectedMailbox = "All Mail"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.Warning, label = "Spam", badge = 0, selected = selectedMailbox == "Spam") {
                    selectedMailbox = "Spam"; scope.launch { drawerState.close() }
                }
                DrawerItem(icon = Icons.Default.Delete, label = "Trash", badge = 0, selected = selectedMailbox == "Trash") {
                    selectedMailbox = "Trash"; scope.launch { drawerState.close() }
                }
                val activeAccount = accounts.firstOrNull { it.id == activeAccountId }
                if (activeAccount?.hasCapability("CALENDAR_READ") == true || activeAccount?.hasCapability("CONTACTS_READ") == true) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f), modifier = Modifier.padding(vertical = 4.dp))
                    if (activeAccount.hasCapability("CALENDAR_READ")) {
                        DrawerItem(icon = Icons.Default.DateRange, label = "Calendar", badge = 0, selected = false) {
                            capabilityNote = "Calendar sync enabled. Calendar surface arrives in next release."
                        }
                    }
                    if (activeAccount.hasCapability("CONTACTS_READ")) {
                        DrawerItem(icon = Icons.Default.People, label = "Contacts", badge = 0, selected = false) {
                            capabilityNote = "Contacts sync enabled. Contacts surface arrives in next release."
                        }
                    }
                }
            }
        }
    ) {
        Box(modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .windowInsetsPadding(WindowInsets.navigationBars)
            ) {
                // Gmail-style top search bar
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 10.dp)
                        .clip(RoundedCornerShape(28.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(horizontal = 4.dp, vertical = 4.dp)
                ) {
                    MaterialIconAction(
                        imageVector = Icons.Default.Menu,
                        contentDescription = "Menu",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        onClick = { scope.launch { drawerState.open() } }
                    )
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp)
                            .semantics { contentDescription = "Search in mail" }
                            .testTag("search-inbox")
                    ) {
                        Icon(
                            imageVector = Icons.Default.Search,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(Modifier.width(12.dp))
                        androidx.compose.foundation.text.BasicTextField(
                            value = searchQuery,
                            onValueChange = { searchQuery = it },
                            singleLine = true,
                            textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
                            cursorBrush = androidx.compose.ui.graphics.SolidColor(MaterialTheme.colorScheme.primary),
                            decorationBox = { inner ->
                                Box(contentAlignment = Alignment.CenterStart) {
                                    if (searchQuery.isEmpty()) {
                                        Text(
                                            "Search in mail",
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                    inner()
                                }
                            },
                            modifier = Modifier.weight(1f)
                        )
                    }
                    if (busy) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp).padding(10.dp), strokeWidth = 2.dp)
                    } else {
                        MaterialIconAction(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "Refresh",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            onClick = {
                                refreshError = null
                                scope.launch {
                                    controller.refresh().fold(onSuccess = {}, onFailure = { refreshError = it.message })
                                }
                            }
                        )
                    }
                    val active = accounts.firstOrNull { it.id == activeAccountId }
                    Box(
                        modifier = Modifier.padding(start = 4.dp).clickable { accountMenuOpen = true },
                        contentAlignment = Alignment.Center
                    ) {
                        AvatarCircle(
                            active?.email ?: "?",
                            size = 32,
                            tint = Color.White,
                            container = active?.email?.let(::avatarColorFor) ?: MaterialTheme.colorScheme.outline
                        )
                        DropdownMenu(expanded = accountMenuOpen, onDismissRequest = { accountMenuOpen = false }) {
                            if (accounts.size > 1) {
                                Text("Switch account", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                                accounts.forEach { account ->
                                    DropdownMenuItem(
                                        text = {
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                AvatarCircle(account.email, size = 24, tint = Color.White, container = avatarColorFor(account.email))
                                                Spacer(Modifier.width(10.dp))
                                                Column {
                                                    Text(account.displayName, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                                                    Text(account.email, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                                                }
                                            }
                                        },
                                        onClick = {
                                            accountMenuOpen = false
                                            scope.launch { controller.selectAccount(account.id) }
                                        }
                                    )
                                }
                                HorizontalDivider()
                            }
                            DropdownMenuItem(
                                text = { Text("Add account") },
                                leadingIcon = { Icon(Icons.Default.PersonAdd, null) },
                                onClick = { accountMenuOpen = false; onAddAccount() }
                            )
                            DropdownMenuItem(
                                text = { Text("Manage accounts") },
                                leadingIcon = { Icon(Icons.Default.Settings, null) },
                                onClick = { accountMenuOpen = false; onManageAccounts() }
                            )
                        }
                    }
                }

                refreshError?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f))
                            .padding(horizontal = 16.dp, vertical = 8.dp)
                    )
                }

                when {
                    accounts.isEmpty() -> EmptyInboxState()
                    visibleMessages.isEmpty() && !busy -> EmptyInboxListState()
                    else -> {
                        var selectedCategory by remember { mutableStateOf<String?>(null) }
                        val categories = remember(visibleMessages) {
                            visibleMessages.mapNotNull { it.triageCategory }.distinct()
                        }
                        if (categories.isNotEmpty()) {
                            androidx.compose.foundation.layout.FlowRow(
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                androidx.compose.material3.FilterChip(
                                    selected = selectedCategory == null,
                                    onClick = { selectedCategory = null },
                                    label = { Text("All") }
                                )
                                androidx.compose.material3.FilterChip(
                                    selected = groupByThread,
                                    onClick = { groupByThread = !groupByThread },
                                    label = { Text("Threads") }
                                )
                                categories.forEach { cat ->
                                    androidx.compose.material3.FilterChip(
                                        selected = selectedCategory == cat,
                                        onClick = { selectedCategory = if (selectedCategory == cat) null else cat },
                                        label = { Text(cat.lowercase().replaceFirstChar { it.uppercase() }) }
                                    )
                                }
                            }
                        } else {
                            androidx.compose.material3.FilterChip(
                                selected = groupByThread,
                                onClick = { groupByThread = !groupByThread },
                                label = { Text("Threads") },
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                            )
                        }
                        val filtered = visibleMessages.filter { matchesQuery(it, searchQuery) }
                            .filter { selectedCategory == null || it.triageCategory == selectedCategory }
                        if (filtered.isEmpty()) {
                            Column(
                                modifier = Modifier.fillMaxSize().padding(32.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.Center
                            ) {
                                Icon(Icons.Default.Search, null, modifier = Modifier.size(48.dp), tint = MaterialTheme.colorScheme.outline)
                                Spacer(Modifier.height(12.dp))
                                Text("No results for \"$searchQuery\"", style = MaterialTheme.typography.titleMedium)
                                Text("Try different keywords or filters", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        } else if (groupByThread && selectedCategory == null && searchQuery.isBlank()) {
                            LazyColumn(modifier = Modifier.fillMaxSize()) {
                                items(threads, key = { ms -> ms.first().id }) { group ->
                                    GmailThreadRow(
                                        group = group,
                                        onClick = { onOpenMessage(group.first().id) }
                                    )
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.25f),
                                        thickness = 0.5.dp
                                    )
                                }
                            }
                        } else {
                            LazyColumn(modifier = Modifier.fillMaxSize()) {
                                items(filtered, key = { it.id }) { message ->
                                    GmailMessageRow(
                                        message = message,
                                        onClick = { onOpenMessage(message.id) },
                                        onStarToggle = { flagged ->
                                            scope.launch { controller.setMessageFlagged(message.id, flagged) }
                                        }
                                    )
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.25f),
                                        thickness = 0.5.dp
                                    )
                                }
                            }
                        }
                    }
                }
            }

            if (queuedCount > 0) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(start = 16.dp, bottom = 88.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.secondaryContainer)
                        .padding(horizontal = 14.dp, vertical = 8.dp)
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onSecondaryContainer)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "$queuedCount queued",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer
                    )
                }
            }

            capabilityNote?.let { note ->
                androidx.compose.material3.AlertDialog(
                    onDismissRequest = { capabilityNote = null },
                    title = { Text("Coming soon") },
                    text = { Text(note) },
                    confirmButton = {
                        androidx.compose.material3.TextButton(onClick = { capabilityNote = null }) { Text("OK") }
                    }
                )
            }

            val lastQueuedId by controller.lastQueuedMutationId.collectAsState()
            val snackbarHostState = remember { androidx.compose.material3.SnackbarHostState() }
            LaunchedEffect(lastQueuedId) {
                val id = lastQueuedId ?: return@LaunchedEffect
                val result = snackbarHostState.showSnackbar(
                    message = "Sending — tap Undo to cancel",
                    actionLabel = "Undo",
                    duration = androidx.compose.material3.SnackbarDuration.Short
                )
                if (result == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                    scope.launch { controller.cancelPending(id) }
                }
            }
            androidx.compose.material3.SnackbarHost(
                hostState = snackbarHostState,
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 88.dp)
            )

            FloatingActionButton(
                onClick = onCompose,
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .windowInsetsPadding(WindowInsets.navigationBars)
                    .padding(16.dp)
                    .semantics { contentDescription = "Compose" }
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp)
                ) {
                    Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Compose", style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

private fun matchesQuery(message: UiMessage, query: String): Boolean {
    if (query.isBlank()) return true
    return try {
        val parsed = com.ifinmail.core.domain.search.MailQueryParser.parse(query)
        parsed.matches(
            com.ifinmail.core.domain.model.StoredMessage(
                id = message.id,
                accountId = message.accountId,
                folder = "INBOX",
                uid = 0,
                subject = message.subject,
                fromName = message.fromName,
                fromAddress = message.fromAddress,
                toCsv = "",
                ccCsv = message.ccCsv,
                dateEpochMs = message.dateEpochMs,
                snippet = message.snippet,
                sizeBytes = 0,
                read = message.read,
                flagged = message.flagged,
                hasAttachments = message.hasAttachments,
                triageCategory = message.triageCategory
            )
        )
    } catch (e: Exception) {
        val q = query.trim().lowercase()
        message.subject.lowercase().contains(q) ||
            message.snippet.lowercase().contains(q) ||
            message.fromAddress.lowercase().contains(q) ||
            (message.fromName?.lowercase()?.contains(q) == true)
    }
}

@Composable
private fun EmptyInboxState() {
    com.ifinmail.app.shared.ui.components.EmptyState(
        iconText = "",
        title = "No mailbox connected",
        subtitle = "Add your Gmail, Outlook, Yahoo or any IMAP/POP3 account to start reading mail."
    )
}

@Composable
private fun EmptyInboxListState() {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(Icons.Default.Inbox, null, modifier = Modifier.size(56.dp), tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
        Spacer(Modifier.height(16.dp))
        Text("Inbox is empty", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        Text("New messages appear here automatically.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DrawerItem(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    badge: Int,
    selected: Boolean,
    onClick: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 2.dp)
            .clip(RoundedCornerShape(24.dp))
            .background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp)
        )
        Spacer(Modifier.width(16.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium.copy(
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
            ),
            modifier = Modifier.weight(1f)
        )
        if (badge > 0) {
            Text(
                "$badge",
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

@Composable
private fun MailboxNavItem(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    unreadBadge: Int,
    selected: Boolean,
    onClick: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 2.dp)
            .clip(RoundedCornerShape(24.dp))
            .background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp)
        )
        Spacer(Modifier.width(16.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal),
            color = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f)
        )
        if (unreadBadge > 0) {
            Text(
                "$unreadBadge",
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.7f))
                    .padding(horizontal = 8.dp, vertical = 2.dp)
            )
        }
    }
}

@Composable
private fun GmailMessageRow(
    message: UiMessage,
    onClick: () -> Unit,
    onStarToggle: (Boolean) -> Unit
) {
    var starredOverride by remember(message.id) { mutableStateOf(message.flagged) }
    val senderDisplay = message.fromName ?: message.fromAddress.substringBefore('@')
    val isUnread = !message.read
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(if (isUnread) MaterialTheme.colorScheme.surface else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(start = 16.dp, end = 4.dp, top = 12.dp, bottom = 12.dp)
    ) {
        AvatarCircle(
            senderDisplay,
            size = 40,
            tint = Color.White,
            container = avatarColorFor(message.fromAddress)
        )
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    senderDisplay,
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (isUnread) FontWeight.Bold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    formatTimestamp(message.dateEpochMs),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isUnread) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                    fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                )
            }
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    message.subject,
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                if (message.triageCategory != null) {
                    Spacer(Modifier.width(6.dp))
                    Text(
                        message.triageCategory.lowercase().replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                        color = when (message.triageCategory) {
                            "URGENT" -> MaterialTheme.colorScheme.error
                            "FINANCIAL" -> MaterialTheme.colorScheme.tertiary
                            "SOCIAL" -> MaterialTheme.colorScheme.secondary
                            "GENERAL" -> MaterialTheme.colorScheme.onSurfaceVariant
                            else -> MaterialTheme.colorScheme.primary
                        },
                        modifier = Modifier
                            .background(
                                when (message.triageCategory) {
                                    "URGENT" -> MaterialTheme.colorScheme.errorContainer
                                    "FINANCIAL" -> MaterialTheme.colorScheme.tertiaryContainer
                                    "GENERAL" -> MaterialTheme.colorScheme.surfaceVariant
                                    else -> MaterialTheme.colorScheme.secondaryContainer
                                },
                                RoundedCornerShape(4.dp)
                            )
                            .padding(horizontal = 6.dp, vertical = 2.dp)
                    )
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    message.snippet,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                if (message.hasAttachments) {
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "📎",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
            }
        }
        StarToggle(
            starred = starredOverride,
            onToggle = {
                starredOverride = !starredOverride
                onStarToggle(starredOverride)
            }
        )
    }
}

@Composable
private fun GmailThreadRow(
    group: List<UiMessage>,
    onClick: () -> Unit
) {
    val latest = group.maxByOrNull { it.dateEpochMs ?: 0L } ?: group.first()
    val senderDisplay = latest.fromName ?: latest.fromAddress.substringBefore('@')
    val unreadCount = group.count { !it.read }
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(if (unreadCount > 0) MaterialTheme.colorScheme.surface else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 12.dp)
    ) {
        AvatarCircle(
            senderDisplay,
            size = 40,
            tint = Color.White,
            container = avatarColorFor(latest.fromAddress)
        )
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    senderDisplay,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = if (unreadCount > 0) FontWeight.Bold else FontWeight.Normal),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    formatTimestamp(latest.dateEpochMs),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (unreadCount > 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                    fontWeight = if (unreadCount > 0) FontWeight.SemiBold else FontWeight.Normal
                )
            }
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    latest.subject,
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (unreadCount > 0) FontWeight.SemiBold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "${group.size}",
                    style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primaryContainer)
                        .padding(horizontal = 7.dp, vertical = 1.dp)
                )
            }
            Text(
                latest.snippet,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

internal fun formatTimestamp(epochMs: Long?): String {
    if (epochMs == null || epochMs <= 0L) return ""
    return try {
        val iso = kotlinx.datetime.Instant.fromEpochMilliseconds(epochMs).toString()
        val date = iso.substring(0, 10)
        val time = iso.substring(11, 16)
        val monthDay = date.substring(5, 10).replace("-", " ")
        "$monthDay $time"
    } catch (e: Exception) {
        ""
    }
}

private fun Float.toSp() = androidx.compose.ui.unit.TextUnit(this, androidx.compose.ui.unit.TextUnitType.Sp)

