package com.ifinmail.app.shared.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import com.ifinmail.app.shared.ui.update.UpdateRequiredScreen
import com.ifinmail.app.shared.update.UpdateController
import com.ifinmail.app.shared.update.isRequired
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.mail.UiMessage
import com.ifinmail.app.shared.ui.platform.PlatformBackHandler
import com.ifinmail.app.shared.ui.screens.AccountsScreen
import com.ifinmail.app.shared.ui.screens.AddAccountScreen
import com.ifinmail.app.shared.ui.screens.ComposeScreen
import com.ifinmail.app.shared.ui.screens.ComposePayload
import com.ifinmail.app.shared.ui.screens.DraftsScreen
import com.ifinmail.app.shared.ui.screens.InboxScreen
import com.ifinmail.app.shared.ui.screens.MessageDetailScreen
import com.ifinmail.app.shared.ui.screens.UiComposeMode
import com.ifinmail.app.shared.ui.theme.IfinmailTheme
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.sync_unavailable_subtitle
import com.ifinmail.app.shared.resources.sync_unavailable_title
import org.jetbrains.compose.resources.stringResource

sealed interface Screen {
    data object Inbox : Screen
    data object Accounts : Screen
    data object AddAccount : Screen
    data object Drafts : Screen
    data class Detail(val messageId: String) : Screen
    data class Compose(val payload: ComposePayload) : Screen
}

@Composable
fun App(
    mailController: MailController? = null,
    /** Reports the effective theme so the host can restyle platform chrome such as system bars. */
    onDarkThemeChanged: (Boolean) -> Unit = {},
    /** Stored theme choice: null follows the system, true/false is an explicit dark/light choice. */
    initialThemeOverride: Boolean? = null,
    /** Called when the person picks a theme in Settings so the host can persist it. */
    onThemeOverrideChanged: (Boolean?) -> Unit = {},
    /** In-house over-the-air updates; null where the platform has none. */
    updateController: UpdateController? = null
) {
    var darkOverride by rememberSaveable { mutableStateOf(initialThemeOverride) }
    val systemDark = androidx.compose.foundation.isSystemInDarkTheme()
    val dark = darkOverride ?: systemDark
    LaunchedEffect(dark) { onDarkThemeChanged(dark) }
    val updateState = updateController?.state?.collectAsState()?.value
    IfinmailTheme(darkTheme = dark) {
        if (updateController != null && updateState?.isRequired == true) {
            // The server has declared this version unusable: nothing else is offered.
            UpdateRequiredScreen(updateController)
        } else if (mailController == null) {
            com.ifinmail.app.shared.ui.components.EmptyState(
                icon = Icons.Default.MailOutline,
                title = stringResource(Res.string.sync_unavailable_title),
                subtitle = stringResource(Res.string.sync_unavailable_subtitle)
            )
        } else {
            MailAppRoot(mailController, updateController, darkOverride) {
                darkOverride = it
                onThemeOverrideChanged(it)
            }
        }
    }
}

@Composable
private fun MailAppRoot(
    controller: MailController,
    updateController: UpdateController?,
    themeOverride: Boolean?,
    onThemeChange: (Boolean?) -> Unit
) {
    val backStack = remember { mutableStateListOf<Screen>(Screen.Inbox) }

    fun push(screen: Screen) {
        backStack.add(screen)
    }

    fun pop(): Boolean {
        if (backStack.size <= 1) return false
        backStack.removeAt(backStack.size - 1)
        return true
    }

    PlatformBackHandler(enabled = backStack.size > 1) { pop() }

    val current = backStack.last()
    when (current) {
        Screen.Inbox -> InboxScreen(
            controller = controller,
            onOpenMessage = { id -> push(Screen.Detail(id)) },
            onCompose = { push(Screen.Compose(ComposePayload(null, UiComposeMode.NEW))) },
            onManageAccounts = { push(Screen.Accounts) },
            onAddAccount = { push(Screen.AddAccount) },
            onOpenDrafts = { push(Screen.Drafts) },
            updateController = updateController
        )

        Screen.Accounts -> AccountsScreen(
            controller = controller,
            onAddAccount = { push(Screen.AddAccount) },
            onBack = { pop() },
            updateController = updateController,
            themeOverride = themeOverride,
            onThemeChange = onThemeChange
        )

        Screen.AddAccount -> AddAccountScreen(
            controller = controller,
            onDone = {
                while (backStack.size > 1) backStack.removeAt(backStack.size - 1)
            },
            onCancel = { pop() }
        )

        Screen.Drafts -> DraftsScreen(
            controller = controller,
            onOpen = { draft -> push(Screen.Compose(ComposePayload(null, UiComposeMode.NEW, draft = draft))) },
            onBack = { pop() }
        )

        is Screen.Detail -> MessageDetailScreen(
            controller = controller,
            messageId = current.messageId,
            onReply = { message, mode ->
                val composeMode = when (mode) {
                    "reply_all" -> UiComposeMode.REPLY_ALL
                    "forward" -> UiComposeMode.FORWARD
                    else -> UiComposeMode.REPLY
                }
                push(Screen.Compose(ComposePayload(message, composeMode)))
            },
            onSmartReply = { message, body ->
                push(Screen.Compose(ComposePayload(message, UiComposeMode.REPLY, initialBody = body)))
            },
            onDeleteDone = { pop() },
            onBack = { pop() }
        )

        is Screen.Compose -> ComposeScreen(
            controller = controller,
            replyTo = current.payload.replyTo,
            mode = current.payload.mode,
            initialBody = current.payload.initialBody ?: current.payload.draft?.body,
            initialDraft = current.payload.draft,
            onSent = { pop() },
            onCancel = { pop() }
        )
    }
}
