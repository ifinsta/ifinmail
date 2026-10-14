package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import com.ifinmail.app.shared.ui.update.UpdateBanner
import com.ifinmail.app.shared.update.UpdateController
import com.ifinmail.app.shared.update.info
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
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.EmptyState
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.components.SelectableChip
import com.ifinmail.app.shared.ui.components.StarToggle
import com.ifinmail.app.shared.ui.components.avatarColorFor
import com.ifinmail.core.domain.search.matches
import kotlinx.coroutines.launch
import kotlinx.datetime.toLocalDateTime
import org.jetbrains.compose.resources.StringResource
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.account
import com.ifinmail.app.shared.resources.action_undo
import com.ifinmail.app.shared.resources.add_account
import com.ifinmail.app.shared.resources.category_financial
import com.ifinmail.app.shared.resources.category_general
import com.ifinmail.app.shared.resources.category_social
import com.ifinmail.app.shared.resources.category_urgent
import com.ifinmail.app.shared.resources.chip_all
import com.ifinmail.app.shared.resources.chip_threads
import com.ifinmail.app.shared.resources.clear_search
import com.ifinmail.app.shared.resources.compose
import com.ifinmail.app.shared.resources.empty_inbox_subtitle
import com.ifinmail.app.shared.resources.empty_inbox_title
import com.ifinmail.app.shared.resources.empty_snoozed_subtitle
import com.ifinmail.app.shared.resources.empty_snoozed_title
import com.ifinmail.app.shared.resources.empty_starred_subtitle
import com.ifinmail.app.shared.resources.empty_starred_title
import com.ifinmail.app.shared.resources.has_attachment
import com.ifinmail.app.shared.resources.inbox_no_mailbox_subtitle
import com.ifinmail.app.shared.resources.inbox_no_mailbox_title
import com.ifinmail.app.shared.resources.mailbox_drafts
import com.ifinmail.app.shared.resources.mailbox_inbox
import com.ifinmail.app.shared.resources.mailbox_snoozed
import com.ifinmail.app.shared.resources.mailbox_starred
import com.ifinmail.app.shared.resources.manage_accounts
import com.ifinmail.app.shared.resources.menu
import com.ifinmail.app.shared.resources.month_abbreviations
import com.ifinmail.app.shared.resources.no_account_selected
import com.ifinmail.app.shared.resources.no_results_for
import com.ifinmail.app.shared.resources.no_results_hint
import com.ifinmail.app.shared.resources.no_subject
import com.ifinmail.app.shared.resources.nothing_in_category
import com.ifinmail.app.shared.resources.queued_count
import com.ifinmail.app.shared.resources.refresh
import com.ifinmail.app.shared.resources.search_in_mail
import com.ifinmail.app.shared.resources.sending_undo
import com.ifinmail.app.shared.resources.switch_account
import com.ifinmail.app.shared.resources.unread_count
import org.jetbrains.compose.resources.stringResource
import org.jetbrains.compose.resources.getString
import org.jetbrains.compose.resources.stringArrayResource
import com.ifinmail.app.shared.resources.date_month_day
import com.ifinmail.app.shared.resources.date_month_day_year

/** Room under the last row so the floating compose button never covers it. */
private val ListBottomPadding = 96.dp

private enum class Mailbox(val title: StringResource) {
    Inbox(Res.string.mailbox_inbox),
    Starred(Res.string.mailbox_starred),
    Snoozed(Res.string.mailbox_snoozed)
}

@Composable
fun InboxScreen(
    controller: MailController,
    onOpenMessage: (String) -> Unit,
    onCompose: () -> Unit,
    onManageAccounts: () -> Unit,
    onAddAccount: () -> Unit,
    onOpenDrafts: () -> Unit,
    updateController: UpdateController? = null
) {
    val accounts by controller.accounts.collectAsState()
    val messages by controller.messages.collectAsState()
    val activeAccountId by controller.activeAccountId.collectAsState()
    val busy by controller.isBusy.collectAsState()
    val queuedCount by controller.queuedCount.collectAsState()
    val drafts by controller.drafts.collectAsState()
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    var selectedMailbox by rememberSaveable { mutableStateOf(Mailbox.Inbox) }
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var accountMenuOpen by remember { mutableStateOf(false) }
    var refreshError by remember { mutableStateOf<String?>(null) }
    var groupByThread by rememberSaveable { mutableStateOf(true) }
    var selectedCategory by rememberSaveable { mutableStateOf<String?>(null) }

    // Pull-to-refresh tracks its own flag: controller.isBusy is also true for unrelated work
    // such as starring a message, which must not spin the pull indicator.
    var refreshing by remember { mutableStateOf(false) }
    fun refresh() {
        refreshError = null
        refreshing = true
        scope.launch {
            controller.refresh().fold(onSuccess = {}, onFailure = { refreshError = it.displayableMessage() })
            refreshing = false
        }
    }

    // Sync when the inbox opens and whenever it comes back into view (after reading or composing),
    // not only when the list happens to be empty.
    LaunchedEffect(activeAccountId) {
        if (activeAccountId != null) {
            controller.refresh().fold(onSuccess = {}, onFailure = { refreshError = it.displayableMessage() })
        }
    }

    // A message is only handed to the server once the outbox drains (after the undo window), so
    // refresh then to pick up sent mail and anything it triggered.
    var lastQueuedCount by remember { mutableStateOf(queuedCount) }
    LaunchedEffect(queuedCount) {
        if (lastQueuedCount > 0 && queuedCount == 0) refresh()
        lastQueuedCount = queuedCount
    }

    var nowTick by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(60_000)
            nowTick = System.currentTimeMillis()
        }
    }
    val visibleMessages = remember(messages, nowTick, selectedMailbox) {
        val awake = messages.filter { it.snoozedUntilMs == null || it.snoozedUntilMs <= nowTick }
        when (selectedMailbox) {
            Mailbox.Starred -> awake.filter { it.flagged }
            Mailbox.Snoozed -> messages.filter { it.snoozedUntilMs != null && it.snoozedUntilMs > nowTick }
            Mailbox.Inbox -> awake
        }
    }
    val categories = remember(visibleMessages) {
        visibleMessages.mapNotNull { it.triageCategory }.distinct()
    }
    // A category that no longer exists in the list (after a refresh or mailbox change) must not
    // leave the person looking at an empty, filter-less screen.
    val activeCategory = selectedCategory?.takeIf { it in categories }
    val filtered = remember(visibleMessages, searchQuery, activeCategory) {
        visibleMessages
            .filter { matchesQuery(it, searchQuery) }
            .filter { activeCategory == null || it.triageCategory == activeCategory }
    }
    val threads = remember(filtered) {
        filtered.groupBy { it.threadId.ifBlank { it.id } }.values
            .sortedByDescending { ms -> ms.maxOfOrNull { it.dateEpochMs ?: 0L } }
    }
    val activeAccount = accounts.firstOrNull { it.id == activeAccountId }

    val accountDescription = stringResource(Res.string.account)
    val composeDescription = stringResource(Res.string.compose)

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
                        .padding(horizontal = 24.dp, vertical = 20.dp)
                ) {
                    Text(
                        "ifinmail",
                        style = MaterialTheme.typography.headlineMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        activeAccount?.email ?: stringResource(Res.string.no_account_selected),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(8.dp))
                DrawerItem(
                    icon = Icons.Default.Inbox,
                    label = stringResource(Mailbox.Inbox.title),
                    badge = messages.count { !it.read },
                    selected = selectedMailbox == Mailbox.Inbox
                ) {
                    selectedMailbox = Mailbox.Inbox; scope.launch { drawerState.close() }
                }
                DrawerItem(
                    icon = Icons.Default.Star,
                    label = stringResource(Mailbox.Starred.title),
                    badge = messages.count { it.flagged },
                    selected = selectedMailbox == Mailbox.Starred
                ) {
                    selectedMailbox = Mailbox.Starred; scope.launch { drawerState.close() }
                }
                DrawerItem(
                    icon = Icons.Default.DateRange,
                    label = stringResource(Mailbox.Snoozed.title),
                    badge = messages.count { it.snoozedUntilMs != null && it.snoozedUntilMs > nowTick },
                    selected = selectedMailbox == Mailbox.Snoozed
                ) {
                    selectedMailbox = Mailbox.Snoozed; scope.launch { drawerState.close() }
                }
                DrawerItem(
                    icon = Icons.Default.Edit,
                    label = stringResource(Res.string.mailbox_drafts),
                    badge = drafts.size,
                    selected = false
                ) {
                    scope.launch { drawerState.close() }; onOpenDrafts()
                }
                HorizontalDivider(
                    color = MaterialTheme.colorScheme.outlineVariant,
                    modifier = Modifier.padding(vertical = 8.dp, horizontal = 12.dp)
                )
                DrawerItem(
                    icon = Icons.Default.Settings,
                    label = stringResource(Res.string.manage_accounts),
                    badge = 0,
                    selected = false
                ) {
                    scope.launch { drawerState.close() }; onManageAccounts()
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
                SearchBar(
                    query = searchQuery,
                    onQueryChange = { searchQuery = it },
                    busy = busy,
                    onMenu = { scope.launch { drawerState.open() } },
                    onRefresh = ::refresh,
                    avatar = {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(48.dp)
                                .clip(CircleShape)
                                .clickable(role = Role.Button) { accountMenuOpen = true }
                                .semantics { contentDescription = accountDescription }
                        ) {
                            if (activeAccount != null) {
                                AvatarCircle(
                                    activeAccount.email,
                                    size = 32,
                                    tint = Color.White,
                                    container = avatarColorFor(activeAccount.email)
                                )
                            } else {
                                Icon(
                                    Icons.Default.AccountCircle,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(32.dp)
                                )
                            }
                            DropdownMenu(expanded = accountMenuOpen, onDismissRequest = { accountMenuOpen = false }) {
                                if (accounts.size > 1) {
                                    Text(
                                        stringResource(Res.string.switch_account),
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                                    )
                                    accounts.forEach { account ->
                                        DropdownMenuItem(
                                            text = {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                    AvatarCircle(
                                                        account.email,
                                                        size = 28,
                                                        tint = Color.White,
                                                        container = avatarColorFor(account.email)
                                                    )
                                                    Spacer(Modifier.width(12.dp))
                                                    Column {
                                                        Text(account.displayName, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                                                        Text(
                                                            account.email,
                                                            style = MaterialTheme.typography.bodySmall,
                                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                            maxLines = 1
                                                        )
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
                                    text = { Text(stringResource(Res.string.add_account)) },
                                    leadingIcon = { Icon(Icons.Default.PersonAdd, null) },
                                    onClick = { accountMenuOpen = false; onAddAccount() }
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(Res.string.manage_accounts)) },
                                    leadingIcon = { Icon(Icons.Default.Settings, null) },
                                    onClick = { accountMenuOpen = false; onManageAccounts() }
                                )
                            }
                        }
                    }
                )

                if (updateController != null) {
                    val updateState by updateController.state.collectAsState()
                    // "Later" hides the banner for this version only; a newer build brings it back.
                    var dismissedFor by rememberSaveable { mutableStateOf(0) }
                    val offeredCode = updateState.info?.versionCode ?: 0
                    if (offeredCode != dismissedFor) {
                        UpdateBanner(updateController, onLater = { dismissedFor = offeredCode })
                    }
                }

                refreshError?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(MaterialTheme.colorScheme.errorContainer)
                            .padding(horizontal = 16.dp, vertical = 10.dp)
                    )
                }

                when {
                    accounts.isEmpty() -> EmptyState(
                        icon = Icons.Default.Inbox,
                        title = stringResource(Res.string.inbox_no_mailbox_title),
                        subtitle = stringResource(Res.string.inbox_no_mailbox_subtitle),
                        modifier = Modifier.weight(1f),
                        actionLabel = stringResource(Res.string.add_account),
                        onAction = onAddAccount
                    )

                    else -> {
                        MailboxHeader(
                            title = stringResource(selectedMailbox.title),
                            unread = visibleMessages.count { !it.read },
                            showFilters = visibleMessages.isNotEmpty(),
                            groupByThread = groupByThread,
                            onToggleThreads = { groupByThread = !groupByThread },
                            categories = categories,
                            selectedCategory = activeCategory,
                            onSelectCategory = { selectedCategory = it }
                        )
                        PullToRefreshBox(
                            isRefreshing = refreshing,
                            onRefresh = ::refresh,
                            modifier = Modifier.weight(1f).fillMaxWidth()
                        ) {
                            when {
                                visibleMessages.isEmpty() -> {
                                    if (busy) {
                                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                            CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
                                        }
                                    } else {
                                        EmptyListState(selectedMailbox)
                                    }
                                }

                                filtered.isEmpty() -> EmptyState(
                                    icon = Icons.Default.Search,
                                    title = if (searchQuery.isBlank()) {
                                        stringResource(Res.string.nothing_in_category)
                                    } else {
                                        stringResource(Res.string.no_results_for, searchQuery)
                                    },
                                    subtitle = stringResource(Res.string.no_results_hint),
                                    modifier = Modifier.fillMaxSize()
                                )

                                groupByThread && activeCategory == null && searchQuery.isBlank() -> {
                                    LazyColumn(
                                        modifier = Modifier.fillMaxSize(),
                                        contentPadding = PaddingValues(bottom = ListBottomPadding)
                                    ) {
                                        items(threads, key = { group -> group.first().id }) { group ->
                                            ThreadRow(group = group, onClick = { onOpenMessage(group.first().id) })
                                            RowDivider()
                                        }
                                    }
                                }

                                else -> {
                                    LazyColumn(
                                        modifier = Modifier.fillMaxSize(),
                                        contentPadding = PaddingValues(bottom = ListBottomPadding)
                                    ) {
                                        items(filtered, key = { it.id }) { message ->
                                            MessageRow(
                                                message = message,
                                                onClick = { onOpenMessage(message.id) },
                                                onStarToggle = { flagged ->
                                                    scope.launch { controller.setMessageFlagged(message.id, flagged) }
                                                }
                                            )
                                            RowDivider()
                                        }
                                    }
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
                        .windowInsetsPadding(WindowInsets.navigationBars)
                        .padding(start = 16.dp, bottom = 16.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.secondaryContainer)
                        .padding(horizontal = 14.dp, vertical = 10.dp)
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onSecondaryContainer
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        stringResource(Res.string.queued_count, queuedCount),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer
                    )
                }
            }

            val lastQueuedId by controller.lastQueuedMutationId.collectAsState()
            val snackbarHostState = remember { SnackbarHostState() }
            LaunchedEffect(lastQueuedId) {
                val id = lastQueuedId ?: return@LaunchedEffect
                val result = snackbarHostState.showSnackbar(
                    message = getString(Res.string.sending_undo),
                    actionLabel = getString(Res.string.action_undo),
                    duration = SnackbarDuration.Short
                )
                if (result == SnackbarResult.ActionPerformed) {
                    scope.launch { controller.cancelPending(id) }
                }
            }
            SnackbarHost(
                hostState = snackbarHostState,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .windowInsetsPadding(WindowInsets.navigationBars)
                    .padding(bottom = 88.dp)
            )

            if (accounts.isNotEmpty()) ExtendedFloatingActionButton(
                onClick = onCompose,
                icon = { Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(20.dp)) },
                text = { Text(stringResource(Res.string.compose), style = MaterialTheme.typography.labelLarge) },
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .windowInsetsPadding(WindowInsets.navigationBars)
                    .padding(16.dp)
                    .semantics { contentDescription = composeDescription }
            )
        }
    }
}

@Composable
private fun SearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
    busy: Boolean,
    onMenu: () -> Unit,
    onRefresh: () -> Unit,
    avatar: @Composable () -> Unit
) {
    val searchDescription = stringResource(Res.string.search_in_mail)
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp)
            .clip(RoundedCornerShape(28.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 4.dp)
    ) {
        MaterialIconAction(
            imageVector = Icons.Default.Menu,
            contentDescription = stringResource(Res.string.menu),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            onClick = onMenu
        )
        Box(
            contentAlignment = Alignment.CenterStart,
            modifier = Modifier
                .weight(1f)
                .height(48.dp)
                .padding(horizontal = 4.dp)
        ) {
            BasicTextField(
                value = query,
                onValueChange = onQueryChange,
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                keyboardOptions = KeyboardOptions.Default.copy(imeAction = ImeAction.Search),
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (query.isEmpty()) {
                            Text(
                                stringResource(Res.string.search_in_mail),
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        inner()
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = searchDescription }
                    .testTag("search-inbox")
            )
        }
        when {
            query.isNotEmpty() -> MaterialIconAction(
                imageVector = Icons.Default.Close,
                contentDescription = stringResource(Res.string.clear_search),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                onClick = { onQueryChange("") }
            )

            busy -> Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
            }

            else -> MaterialIconAction(
                imageVector = Icons.Default.Refresh,
                contentDescription = stringResource(Res.string.refresh),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                onClick = onRefresh
            )
        }
        avatar()
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun MailboxHeader(
    title: String,
    unread: Int,
    showFilters: Boolean,
    groupByThread: Boolean,
    onToggleThreads: () -> Unit,
    categories: List<String>,
    selectedCategory: String?,
    onSelectCategory: (String?) -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        Row(
            verticalAlignment = Alignment.Bottom,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 4.dp)
        ) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            if (unread > 0) {
                Spacer(Modifier.width(8.dp))
                Text(
                    stringResource(Res.string.unread_count, unread),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 3.dp)
                )
            }
        }
        if (showFilters) androidx.compose.foundation.layout.FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp)
        ) {
            SelectableChip(
                label = stringResource(Res.string.chip_threads),
                selected = groupByThread,
                onClick = onToggleThreads
            )
            if (categories.isNotEmpty()) {
                SelectableChip(
                    label = stringResource(Res.string.chip_all),
                    selected = selectedCategory == null,
                    onClick = { onSelectCategory(null) }
                )
                categories.forEach { category ->
                    SelectableChip(
                        label = categoryLabel(category),
                        selected = selectedCategory == category,
                        onClick = { onSelectCategory(if (selectedCategory == category) null else category) }
                    )
                }
            }
        }
    }
}

@Composable
private fun RowDivider() {
    HorizontalDivider(
        color = MaterialTheme.colorScheme.outlineVariant,
        thickness = 0.5.dp,
        modifier = Modifier.padding(start = 70.dp)
    )
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
private fun EmptyListState(mailbox: Mailbox) {
    val (icon, title, subtitle) = when (mailbox) {
        Mailbox.Inbox -> Triple(
            Icons.Default.Inbox,
            stringResource(Res.string.empty_inbox_title),
            stringResource(Res.string.empty_inbox_subtitle)
        )
        Mailbox.Starred -> Triple(
            Icons.Default.Star,
            stringResource(Res.string.empty_starred_title),
            stringResource(Res.string.empty_starred_subtitle)
        )
        Mailbox.Snoozed -> Triple(
            Icons.Default.DateRange,
            stringResource(Res.string.empty_snoozed_title),
            stringResource(Res.string.empty_snoozed_subtitle)
        )
    }
    EmptyState(icon = icon, title = title, subtitle = subtitle, modifier = Modifier.fillMaxSize())
}

@Composable
private fun DrawerItem(
    icon: ImageVector,
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
            .clip(RoundedCornerShape(28.dp))
            .background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
            .clickable(role = Role.Button, onClick = onClick)
            .height(52.dp)
            .padding(horizontal = 16.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(22.dp)
        )
        Spacer(Modifier.width(16.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium.copy(
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
            ),
            color = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f)
        )
        if (badge > 0) {
            Text(
                "$badge",
                style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold),
                color = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.primary
            )
        }
    }
}

@Composable
private fun rowBackground(unread: Boolean): Color =
    if (unread) MaterialTheme.colorScheme.surface else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)

@Composable
private fun TriageBadge(category: String) {
    val (tint, container) = when (category) {
        "URGENT" -> MaterialTheme.colorScheme.onErrorContainer to MaterialTheme.colorScheme.errorContainer
        "FINANCIAL" -> MaterialTheme.colorScheme.onTertiaryContainer to MaterialTheme.colorScheme.tertiaryContainer
        "GENERAL" -> MaterialTheme.colorScheme.onSurfaceVariant to MaterialTheme.colorScheme.surfaceVariant
        else -> MaterialTheme.colorScheme.onSecondaryContainer to MaterialTheme.colorScheme.secondaryContainer
    }
    Text(
        categoryLabel(category),
        style = MaterialTheme.typography.labelMedium,
        color = tint,
        maxLines = 1,
        modifier = Modifier
            .background(container, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp)
    )
}

@Composable
private fun MessageRow(
    message: UiMessage,
    onClick: () -> Unit,
    onStarToggle: (Boolean) -> Unit
) {
    var starred by remember(message.id, message.flagged) { mutableStateOf(message.flagged) }
    val senderDisplay = message.fromName ?: message.fromAddress.substringBefore('@')
    val isUnread = !message.read
    val dateLabels = rememberDateLabels()
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBackground(isUnread))
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
                    modifier = Modifier.weight(1f)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    formatTimestamp(message.dateEpochMs, dateLabels),
                    style = MaterialTheme.typography.labelMedium,
                    color = if (isUnread) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                )
            }
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    message.subject.ifBlank { stringResource(Res.string.no_subject) },
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                if (message.triageCategory != null) {
                    Spacer(Modifier.width(8.dp))
                    TriageBadge(message.triageCategory)
                }
            }
            if (message.snippet.isNotBlank() || message.hasAttachments) {
                Spacer(Modifier.height(2.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (message.snippet.isNotBlank()) Text(
                    message.snippet,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                if (message.hasAttachments) {
                    Spacer(Modifier.width(6.dp))
                    Icon(
                        Icons.Default.AttachFile,
                        contentDescription = stringResource(Res.string.has_attachment),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(14.dp)
                    )
                }
            }
        }
        StarToggle(
            starred = starred,
            onToggle = {
                starred = !starred
                onStarToggle(starred)
            }
        )
    }
}

@Composable
private fun ThreadRow(
    group: List<UiMessage>,
    onClick: () -> Unit
) {
    val latest = group.maxByOrNull { it.dateEpochMs ?: 0L } ?: group.first()
    val senderDisplay = latest.fromName ?: latest.fromAddress.substringBefore('@')
    val unreadCount = group.count { !it.read }
    val isUnread = unreadCount > 0
    val dateLabels = rememberDateLabels()
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBackground(isUnread))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp)
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
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (isUnread) FontWeight.Bold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    formatTimestamp(latest.dateEpochMs, dateLabels),
                    style = MaterialTheme.typography.labelMedium,
                    color = if (isUnread) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                )
            }
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    latest.subject.ifBlank { stringResource(Res.string.no_subject) },
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                if (group.size > 1) {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "${group.size}",
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold),
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primaryContainer)
                            .padding(horizontal = 7.dp, vertical = 1.dp)
                    )
                }
            }
            if (latest.snippet.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
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
}

private fun twoDigits(value: Int): String = if (value < 10) "0$value" else "$value"

/** Month names and date patterns from the string catalogue, so translations control order and wording. */
internal class DateLabels(
    val months: List<String>,
    val monthDay: String,
    val monthDayYear: String
)

@Composable
internal fun rememberDateLabels(): DateLabels = DateLabels(
    months = stringArrayResource(Res.array.month_abbreviations),
    monthDay = stringResource(Res.string.date_month_day),
    monthDayYear = stringResource(Res.string.date_month_day_year)
)

private fun String.fillDate(month: String, day: Int, year: Int): String =
    replace("%1\$s", month).replace("%2\$d", day.toString()).replace("%3\$d", year.toString())

/** Localised display name of a triage category; unknown categories are title-cased. */
@Composable
internal fun categoryLabel(category: String): String = when (category) {
    "URGENT" -> stringResource(Res.string.category_urgent)
    "FINANCIAL" -> stringResource(Res.string.category_financial)
    "SOCIAL" -> stringResource(Res.string.category_social)
    "GENERAL" -> stringResource(Res.string.category_general)
    else -> category.lowercase().replaceFirstChar { it.uppercase() }
}

/**
 * List-row timestamp in the person's local time zone, the way mail clients show it: today as
 * `14:05`, earlier this year as `Oct 13`, older as `Oct 13, 2024`.
 */
internal fun formatTimestamp(epochMs: Long?, labels: DateLabels, nowMs: Long = System.currentTimeMillis()): String {
    if (epochMs == null || epochMs <= 0L) return ""
    return try {
        val zone = kotlinx.datetime.TimeZone.currentSystemDefault()
        val then = kotlin.time.Instant.fromEpochMilliseconds(epochMs).toLocalDateTime(zone)
        val now = kotlin.time.Instant.fromEpochMilliseconds(nowMs).toLocalDateTime(zone)
        val month = labels.months.getOrElse(then.month.ordinal) { "" }
        when {
            then.date == now.date -> "${twoDigits(then.hour)}:${twoDigits(then.minute)}"
            then.year == now.year -> labels.monthDay.fillDate(month, then.day, then.year)
            else -> labels.monthDayYear.fillDate(month, then.day, then.year)
        }
    } catch (e: Exception) {
        ""
    }
}

/** Full date and time for headers and reply quotes: `Oct 13, 2026, 14:05`. */
internal fun formatDateTime(epochMs: Long?, labels: DateLabels): String {
    if (epochMs == null || epochMs <= 0L) return ""
    return try {
        val zone = kotlinx.datetime.TimeZone.currentSystemDefault()
        val then = kotlin.time.Instant.fromEpochMilliseconds(epochMs).toLocalDateTime(zone)
        val month = labels.months.getOrElse(then.month.ordinal) { "" }
        "${labels.monthDayYear.fillDate(month, then.day, then.year)}, ${twoDigits(then.hour)}:${twoDigits(then.minute)}"
    } catch (e: Exception) {
        ""
    }
}

/** The text to show for a failure, or null when it is only a coroutine cancellation. */
private fun Throwable.displayableMessage(): String? =
    if (this is kotlinx.coroutines.CancellationException) null else message
