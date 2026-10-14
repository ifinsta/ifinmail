package com.ifinmail

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.junit4.accessibility.enableAccessibilityChecks
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.tryPerformAccessibilityChecks
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Runs the Accessibility Test Framework (touch-target size, missing labels, text contrast,
 * duplicate descriptions) over every primary screen as it is actually rendered.
 */
@OptIn(ExperimentalTestApi::class)
class AccessibilityAuditTest {

    @get:Rule
    val rule = createComposeRule()

    private lateinit var controller: FakeMailController

    @Before
    fun setUp() {
        // The catalogue is localised; these assertions are written against the English strings.
        java.util.Locale.setDefault(java.util.Locale.ENGLISH)
        controller = FakeMailController()
        controller.givenAccount("me@gmail.com")
        controller.givenMessages(
            FakeMailController.seedMessage("me@gmail.com", 1),
            FakeMailController.seedMessage("me@gmail.com", 2)
        )
        rule.enableAccessibilityChecks()
        rule.setApp(controller)
        rule.waitUntilExists("Quarterly report attached")
    }

    private fun audit() {
        rule.waitForIdle()
        rule.onRoot().tryPerformAccessibilityChecks()
    }

    @Test
    fun inbox() = audit()

    @Test
    fun drawer() {
        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("Manage accounts")
        audit()
    }

    @Test
    fun messageDetail() {
        rule.onNodeWithText("Quarterly report attached").performClick()
        rule.waitUntilExists("Hello world body")
        audit()
    }

    @Test
    fun compose() {
        rule.onNodeWithContentDescription("Compose").performClick()
        rule.waitUntilExists("Recipients")
        rule.onNodeWithTag("field-to").performTextInput("friend@example.org")
        audit()
    }

    @Test
    fun accounts() {
        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("Manage accounts")
        rule.onNodeWithText("Manage accounts").performClick()
        rule.waitUntilExists("PREFERENCES")
        audit()
    }

    @Test
    fun addAccountWizard() {
        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("Manage accounts")
        rule.onNodeWithText("Manage accounts").performClick()
        rule.waitUntilExists("Add account")
        rule.onNodeWithText("Add account").performClick()
        rule.waitUntilExists("Email address")
        audit()
    }
}
