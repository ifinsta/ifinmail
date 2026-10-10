package com.ifinmail

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import com.ifinmail.app.shared.ui.App
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class MessageDetailTest {

    @get:Rule
    val rule = createComposeRule()

    private lateinit var controller: FakeMailController

    @Before
    fun setUp() {
        controller = FakeMailController()
        controller.givenAccount("me@gmail.com")
        controller.givenMessages(
            FakeMailController.seedMessage("me@gmail.com", 1),
            FakeMailController.seedMessage("me@gmail.com", 2)
        )
        rule.setContent { App(mailController = controller) }
        rule.waitUntilExists("Quarterly report attached")
        rule.onNodeWithText("Quarterly report attached").performClick()
        rule.waitUntilExists("Hello world body")
    }

    @Test
    fun detailShowsSenderBodyAndBackNavigation() {
        rule.onNodeWithText("Quarterly report attached").assertIsDisplayed()
        rule.onNodeWithText("Alice Example").assertIsDisplayed()
        rule.onNodeWithText("Hello world body").assertIsDisplayed()
        rule.onNodeWithText("attachment").assertIsDisplayed()

        rule.onNodeWithContentDescription("Back").performClick()
        rule.waitUntilExists("Lunch tomorrow?")
    }

    @Test
    fun replyOpensComposer() {
        rule.onNodeWithContentDescription("Reply").performClick()
        rule.waitUntilExists("To")
        assertEquals(0, controller.sentDrafts.size)
    }

    @Test
    fun deleteRemovesMessageAndReturnsToInbox() {
        rule.onNodeWithContentDescription("More options").performClick()
        rule.waitUntilExists("Delete")
        rule.onNodeWithText("Delete").performClick()

        rule.waitUntilExists("Inbox", timeoutMs = 8_000)
        assertEquals(listOf("me@gmail.com-msg1"), controller.deletedIds)
        rule.onAllNodesWithText("Quarterly report attached").fetchSemanticsNodes().let {
            assertTrue("Deleted message row should be gone", it.isEmpty())
        }
    }
}
