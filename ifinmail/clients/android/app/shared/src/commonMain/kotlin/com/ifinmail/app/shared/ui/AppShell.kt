package com.ifinmail.app.shared.ui

import androidx.compose.runtime.Composable
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

sealed interface Screen {
    data object Inbox : Screen
    data object Accounts : Screen
    data object AddAccount : Screen
    data object Drafts : Screen
    data class Detail(val messageId: String) : Screen
    data class Compose(val payload: ComposePayload) : Screen
}

@Composable
fun App(mailController: MailController? = null) {
    var darkThemeMode by rememberSaveable { mutableStateOf(false) }
    // false = follow system, true = force dark; simple toggle for MVP
    IfinmailTheme(darkTheme = darkThemeMode || isSystemDark()) {
        if (mailController == null) {
            com.ifinmail.app.shared.ui.components.EmptyState(
                iconText = "",
                title = "Mail sync is not available yet",
                subtitle = "Use the Android app for full IMAP/POP3/SMTP support."
            )
        } else {
            MailAppRoot(mailController, darkThemeMode) { darkThemeMode = it }
        }
    }
}

@Composable
private fun isSystemDark(): Boolean = androidx.compose.foundation.isSystemInDarkTheme()

@Composable
private fun MailAppRoot(
    controller: MailController,
    darkThemeMode: Boolean,
    onThemeChange: (Boolean) -> Unit
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
            onOpenDrafts = { push(Screen.Drafts) }
        )

        Screen.Accounts -> AccountsScreen(
            controller = controller,
            onAddAccount = { push(Screen.AddAccount) },
            onBack = { pop() },
            darkTheme = darkThemeMode,
            onToggleTheme = { onThemeChange(it) }
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
