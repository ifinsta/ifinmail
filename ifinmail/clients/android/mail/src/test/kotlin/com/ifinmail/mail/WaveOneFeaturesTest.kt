package com.ifinmail.mail

import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.search.MailQuery
import com.ifinmail.core.domain.search.MailQueryParser
import com.ifinmail.core.domain.search.matches
import com.ifinmail.core.domain.thread.ThreadResolver
import com.ifinmail.core.domain.triage.LocalClassifier
import com.ifinmail.core.domain.triage.TriageCategory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ThreadResolverTest {

    private fun msg(id: String, subject: String, accountId: String = "a1", read: Boolean = false, dateMs: Long = 100L) =
        StoredMessage(
            id = id, accountId = accountId, folder = "INBOX", uid = 0,
            subject = subject, fromName = null, fromAddress = "s@t.com",
            toCsv = "", ccCsv = "", dateEpochMs = dateMs, snippet = "s", sizeBytes = 1,
            read = read, flagged = false, hasAttachments = false
        )

    @Test
    fun `normalizedSubject strips re fwd brackets`() {
        assertEquals("quarterly report", ThreadResolver.normalizedSubject("Re: Quarterly Report"))
        assertEquals("hello world", ThreadResolver.normalizedSubject("Fwd: Re: FWD: hello WORLD"))
        assertEquals("announce", ThreadResolver.normalizedSubject("[List] Announce"))
        assertEquals("(no subject)", ThreadResolver.normalizedSubject(""))
    }

    @Test
    fun `same normalized subject groups into one thread per account`() {
        val m1 = msg("1", "Re: Invoice #42")
        val m2 = msg("2", "Invoice #42")
        val threads = ThreadResolver.groupIntoThreads(listOf(m1, m2))
        assertEquals(1, threads.size)
        assertEquals(2, threads[0].count)
    }

    @Test
    fun `different accounts never merge`() {
        val m1 = msg("1", "Hello", accountId = "acctA")
        val m2 = msg("2", "Hello", accountId = "acctB")
        val threads = ThreadResolver.groupIntoThreads(listOf(m1, m2))
        assertEquals(2, threads.size)
    }

    @Test
    fun `thread aggregates unread count and latest date`() {
        val older = msg("old", "Meeting notes", read = true, dateMs = 100L)
        val newer = msg("new", "Re: Meeting notes", read = false, dateMs = 200L)
        val threads = ThreadResolver.groupIntoThreads(listOf(older, newer))
        assertEquals(1, threads.size)
        assertEquals(1, threads[0].unreadCount)
        assertEquals(200L, threads[0].latestDateMs)
        assertEquals("new", threads[0].messageIds.first())
    }
}

class LocalClassifierTest {

    private val classifier = LocalClassifier()

    private fun msg(subject: String, snippet: String = "", from: String = "x@y.z") = StoredMessage(
        id = "m", accountId = "a", folder = "INBOX", uid = 0,
        subject = subject, fromName = null, fromAddress = from,
        toCsv = "", ccCsv = "", dateEpochMs = null, snippet = snippet,
        sizeBytes = 0, read = false, flagged = false, hasAttachments = false
    )

    @Test
    fun `urgent keywords classify as urgent`() {
        assertEquals(TriageCategory.URGENT, classifier.classify(msg("Action required ASAP")).category)
    }

    @Test
    fun `invoice classifies as financial`() {
        assertEquals(TriageCategory.FINANCIAL, classifier.classify(msg("Your invoice for July")).category)
    }

    @Test
    fun `meeting invite classifies as meeting`() {
        assertEquals(TriageCategory.MEETING, classifier.classify(msg("Calendar invite: sync")).category)
    }

    @Test
    fun `newsletter classifies as updates`() {
        assertEquals(TriageCategory.UPDATES, classifier.classify(msg("Weekly digest")).category)
    }

    @Test
    fun `promo classifies as promotions`() {
        assertEquals(TriageCategory.PROMOTIONS, classifier.classify(msg("50% discount today!", "unsubscribe here")).category)
    }

    @Test
    fun `plain message is general`() {
        assertEquals(TriageCategory.GENERAL, classifier.classify(msg("Hi there")).category)
    }
}

class MailQueryParserTest {

    private fun msg(
        id: String = "m", subject: String = "Hello", from: String = "alice@example.com",
        to: String = "", read: Boolean = true, flagged: Boolean = false,
        hasAtt: Boolean = false, category: String? = null, folder: String = "INBOX"
    ) = StoredMessage(
        id = id, accountId = "a", folder = folder, uid = 0,
        subject = subject, fromName = null, fromAddress = from,
        toCsv = to, ccCsv = "", dateEpochMs = 100L, snippet = "body text here",
        sizeBytes = 1, read = read, flagged = flagged, hasAttachments = hasAtt,
        triageCategory = category
    )

    @Test
    fun `blank query matches everything`() {
        val q = MailQueryParser.parse("")
        assertTrue(q.isEmpty)
        assertTrue(q.matches(msg()))
    }

    @Test
    fun `from filter`() {
        val q = MailQueryParser.parse("from:alice")
        assertTrue(q.matches(msg(from = "alice@example.com")))
        assertEquals(false, q.matches(msg(from = "bob@example.com")))
    }

    @Test
    fun `is unread filter`() {
        val q = MailQueryParser.parse("is:unread")
        assertTrue(q.matches(msg(read = false)))
        assertEquals(false, q.matches(msg(read = true)))
    }

    @Test
    fun `has attachment filter`() {
        val q = MailQueryParser.parse("has:attachment report")
        assertTrue(q.hasAttachment == true)
        assertTrue(q.matches(msg(hasAtt = true, subject = "report ready")))
        assertEquals(false, q.matches(msg(hasAtt = false, subject = "report ready")))
    }

    @Test
    fun `is starred filter`() {
        val q = MailQueryParser.parse("is:starred")
        assertTrue(q.matches(msg(flagged = true)))
        assertEquals(false, q.matches(msg(flagged = false)))
    }

    @Test
    fun `category filter matches triage`() {
        val q = MailQueryParser.parse("category:urgent")
        assertTrue(q.matches(msg(category = "URGENT")))
        assertEquals(false, q.matches(msg(category = "GENERAL")))
    }

    @Test
    fun `free text searches subject and body`() {
        val q = MailQueryParser.parse("invoices")
        assertTrue(q.matches(msg(subject = "Overdue invoices list")))
        assertEquals(false, q.matches(msg(subject = "Weekly standup")))
    }

    @Test
    fun `combined query applies all constraints`() {
        val q = MailQueryParser.parse("from:bob is:unread has:attachment")
        assertTrue(q.matches(msg(from = "bob@c.d", read = false, hasAtt = true)))
        assertEquals(false, q.matches(msg(from = "bob@c.d", read = true, hasAtt = true)))
        assertEquals(false, q.matches(msg(from = "alice@e.f", read = false, hasAtt = true)))
    }

    @Test
    fun `in folder filter`() {
        val q = MailQueryParser.parse("in:Archive")
        assertTrue(q.matches(msg(folder = "Archive")))
        assertEquals(false, q.matches(msg(folder = "INBOX")))
    }
}
