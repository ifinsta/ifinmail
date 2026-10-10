package com.ifinmail.core.domain.draft

import com.ifinmail.core.domain.model.Account
import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.port.DraftCapability
import com.ifinmail.core.domain.port.DraftSuggestion

class SmartReplyEngine : DraftCapability {

    override suspend fun suggestions(account: Account, message: StoredMessage): List<DraftSuggestion> {
        val sender = message.fromName ?: message.fromAddress.substringBefore('@')
        val text = "${message.subject} ${message.snippet}".lowercase()
        val bodyQuote = message.bodyText ?: message.snippet

        val replies = mutableListOf<DraftSuggestion>()
        if (text.contains("meeting") || text.contains("calendar") || text.contains("invite")) {
            replies += DraftSuggestion("Can do", "Yes, that works for me. Thanks!")
            replies += DraftSuggestion("Can't make it", "Sorry, I can't make that time. Could we reschedule?")
        }
        if (text.contains("invoice") || text.contains("payment") || text.contains("bill")) {
            replies += DraftSuggestion("Paid", "I've taken care of this. Thanks for the reminder.")
            replies += DraftSuggestion("Question", "Could you clarify a couple of line items on this?")
        }
        if (text.contains("urgent") || text.contains("asap") || text.contains("action required")) {
            replies += DraftSuggestion("On it", "Thanks for the heads-up — I'm on it and will follow up shortly.")
        }
        replies += DraftSuggestion("Got it", "Thanks for letting me know.")
        replies += DraftSuggestion("Thanks", "Thanks, appreciate it!")

        return replies.distinctBy { it.label }.map {
            it.copy(bodyPrefix = "${it.bodyPrefix}\n\nOn ${message.snippet}, $sender wrote:\n$bodyQuote".let { quoted ->
                "${it.bodyPrefix}\n\n> ${quoted.split('\n').joinToString("\n> ")}"
            })
        }.take(4)
    }
}
