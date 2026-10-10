package com.ifinmail.mail

import com.ifinmail.core.domain.error.MailError
import com.ifinmail.mail.model.toMailError
import java.io.EOFException
import java.net.SocketTimeoutException
import kotlin.test.Test
import kotlin.test.assertEquals

class ErrorMappingTest {

    @Test
    fun `timeouts map to Timeout`() {
        assertEquals(MailError.Timeout, SocketTimeoutException("read timed out").toMailError())
    }

    @Test
    fun `io failures map to NetworkUnavailable`() {
        assertEquals(MailError.NetworkUnavailable, EOFException("Connection closed").toMailError())
    }

    @Test
    fun `auth failures map to AuthenticationRequired`() {
        assertEquals(
            MailError.AuthenticationRequired,
            IllegalStateException("Authentication failed for user").toMailError()
        )
        assertEquals(
            MailError.AuthenticationRequired,
            IllegalStateException("NO [AUTHENTICATIONFAILED] bad password").toMailError()
        )
    }

    @Test
    fun `quota recipient and rejection map correctly`() {
        assertEquals(MailError.QuotaExceeded, IllegalStateException("Mailbox is over quota").toMailError())
        assertEquals(MailError.InvalidRecipient, IllegalStateException("550 5.1.1 no such user here").toMailError())
        assertEquals(MailError.SubmissionRejected, IllegalStateException("554 Message rejected: spam").toMailError())
    }

    @Test
    fun `unknown errors carry detail`() {
        val error = IllegalStateException("weird server behaviour").toMailError() as MailError.Unknown
        assertEquals("weird server behaviour", error.detail)
    }
}
