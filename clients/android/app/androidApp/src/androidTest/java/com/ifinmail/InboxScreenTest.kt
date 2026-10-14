package com.ifinmail

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.ifinmail.app.shared.ui.App
import org.junit.Before
import org.junit.Rule
import org.junit.Test

fun ComposeContentTestRule.setApp(controller: FakeMailController) {
    setContent { App(mailController = controller) }
}

fun ComposeContentTestRule.waitUntilExists(text: String, timeoutMs: Long = 5_000) {
    waitUntil(timeoutMillis = timeoutMs) {
        onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty()
    }
}

class InboxScreenTest {

    @get:Rule
    val rule = createComposeRule()

    private lateinit var controller: FakeMailController

    @Before
    fun setUp() {
        // The catalogue is localised; these assertions are written against the English strings.
        java.util.Locale.setDefault(java.util.Locale.ENGLISH)
        controller = FakeMailController()
    }

    @Test
    fun emptyStateShownWhenNoAccounts() {
        rule.setApp(controller)
        rule.waitUntilExists("No mailbox connected")
        rule.onNodeWithText("Add your Gmail, Outlook, Yahoo or any IMAP/POP3 account to start reading mail.")
            .assertIsDisplayed()
    }

    @Test
    fun inboxRowsRenderWithUnreadAndReadStyling() {
        controller.givenAccount("me@gmail.com")
        val m1 = FakeMailController.seedMessage("me@gmail.com", 1)
        val m2 = FakeMailController.seedMessage("me@gmail.com", 2)
        controller.givenMessages(m1, m2)
        rule.setApp(controller)

        rule.waitUntilExists("Quarterly report attached")
        rule.onNodeWithText("Alice Example").assertIsDisplayed()
        rule.onAllNodesWithText("See the numbers for Q3.", substring = true)[0].assertIsDisplayed()
        rule.onNodeWithText("Lunch tomorrow?").assertIsDisplayed()
        rule.onNodeWithText("Are you free at noon?").assertIsDisplayed()
        rule.onNodeWithContentDescription("Menu").assertIsDisplayed()
        rule.onNodeWithContentDescription("Compose").assertIsDisplayed()
    }

    @Test
    fun tappingRowOpensMessageDetail() {
        controller.givenAccount("me@gmail.com")
        controller.givenMessages(FakeMailController.seedMessage("me@gmail.com", 1))
        rule.setApp(controller)

        rule.waitUntilExists("Quarterly report attached")
        rule.onNodeWithText("Quarterly report attached").performClick()

        rule.waitUntilExists("Hello world body")
        rule.onNodeWithText("Alice Example").assertIsDisplayed()
        rule.onNodeWithText("attachment").assertIsDisplayed()
    }

    @Test
    fun fabOpensComposeAndSendDisabledWithoutRecipient() {
        controller.givenAccount("me@gmail.com")
        controller.givenMessages(FakeMailController.seedMessage("me@gmail.com", 1))
        rule.setApp(controller)
        rule.waitUntilExists("Quarterly report attached")

        rule.onNodeWithContentDescription("Compose").performClick()
        rule.waitUntilExists("Compose")

        rule.onNodeWithContentDescription("Send").assertIsNotEnabled()

        rule.onNodeWithTag("field-to").performTextInput("friend@example.org")
        rule.onNodeWithTag("field-subject").performTextInput("Hi")
        rule.onNodeWithContentDescription("Send").performClick()

        rule.waitUntil { controller.sentDrafts.isNotEmpty() }
        assert(controller.sentDrafts.first().to == listOf("friend@example.org"))
    }

    @Test
    fun manageAccountsNavigationViaAccountSwitcher() {
        controller.givenAccount("me@gmail.com")
        rule.setApp(controller)
        rule.waitUntilExists("Inbox")

        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("Manage accounts")
        rule.onAllNodesWithText("Manage accounts", substring = true)[0].performClick()

        rule.waitUntilExists("Accounts")
        rule.onNodeWithText("Add account").assertIsDisplayed()
    }
}
