package com.ifinmail

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.ifinmail.app.shared.ui.App
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class AddAccountWizardTest {

    @get:Rule
    val rule = createComposeRule()

    private lateinit var controller: FakeMailController

    @Before
    fun setUp() {
        // The catalogue is localised; these assertions are written against the English strings.
        java.util.Locale.setDefault(java.util.Locale.ENGLISH)
        controller = FakeMailController()
        rule.setContent { App(mailController = controller) }
        navigateToWizard()
    }

    private fun navigateToWizard() {
        rule.waitUntilExists("No mailbox connected")
        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("Manage accounts")
        rule.onAllNodesWithText("Manage accounts", substring = true)[0].performClick()
        rule.waitUntilExists("Add account")
        rule.onNodeWithText("Add account").performClick()
        rule.waitUntilExists("Email address *")
    }

    @Test
    fun invalidEmailShowsValidationError() {
        rule.onNodeWithTag("field-email-address").performTextInput("not-an-email")
        rule.onNodeWithText("Continue").performClick()

        rule.onNodeWithText("Enter a valid email address").assertIsDisplayed()
        assertNull(controller.lastAddEmail)
    }

    @Test
    fun unknownDomainExplainsNoAutoconfig() {
        rule.onNodeWithTag("field-email-address").performTextInput("user@some-unknown-domain.tld")
        rule.onNodeWithText("Continue").performClick()

        rule.waitUntilExists("No automatic configuration found")
    }

    @Test
    fun fullGmailWizardAddsAccountAndReturnsToInbox() {
        rule.onNodeWithTag("field-email-address").performTextInput("demo@gmail.com")
        rule.onNodeWithText("Continue").performClick()

        rule.waitUntilExists("Detected configuration")
        rule.onAllNodesWithText("imap.gmail.com:993", substring = true)[0].assertIsDisplayed()
        rule.onAllNodesWithText("smtp.gmail.com:465", substring = true)[0].assertIsDisplayed()
        rule.onNodeWithText("Gmail · POP3").performClick()
        rule.onAllNodesWithText("pop.gmail.com:995", substring = true)[0].assertIsDisplayed()
        rule.onNodeWithText("Gmail · IMAP").performClick()
        rule.onNodeWithText("Continue").performClick()

        rule.waitUntilExists("Sign in")
        rule.onNodeWithTag("field-password-app-password").performTextInput("app-secret-123")
        rule.onNodeWithText("Verify & add account").performClick()

        rule.waitUntilExists("Inbox", timeoutMs = 8_000)
        rule.onNodeWithContentDescription("Menu").performClick()
        rule.waitUntilExists("demo@gmail.com")
        rule.onNodeWithText("demo@gmail.com").assertIsDisplayed()
        assertEquals("demo@gmail.com", controller.lastAddEmail)
        assertEquals("app-secret-123", controller.lastAddPassword)
        assertNull(controller.lastAddToken)
    }

    @Test
    fun oauthModeCollectsTokenInsteadOfPassword() {
        rule.onNodeWithTag("field-email-address").performTextInput("oauth@gmail.com")
        rule.onNodeWithText("Continue").performClick()
        rule.waitUntilExists("Detected configuration")
        rule.onNodeWithText("Continue").performClick()

        rule.waitUntilExists("Sign in")
        rule.onNodeWithText("OAuth2 token (XOAUTH2)").performClick()
        rule.onNodeWithTag("field-access-token").performTextInput("ya29.token-value")
        rule.onNodeWithText("Verify & add account").performClick()

        rule.waitUntilExists("Inbox", timeoutMs = 8_000)
        assertNull(controller.lastAddPassword)
        assertEquals("ya29.token-value", controller.lastAddToken)
        assertTrue(controller.lastAddEmail == "oauth@gmail.com")
    }
}
