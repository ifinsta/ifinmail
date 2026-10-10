package com.ifinmail.core.domain.triage

import com.ifinmail.core.domain.model.StoredMessage

enum class TriageCategory(val label: String, val priority: Int) {
    URGENT("Urgent", 3),
    FINANCIAL("Financial", 2),
    MEETING("Meetings", 2),
    ACTION("Action", 2),
    SOCIAL("Social", 1),
    UPDATES("Updates", 1),
    PROMOTIONS("Promotions", 0),
    GENERAL("General", 0)
}

data class TriageResult(
    val category: TriageCategory,
    val confidence: Float,
    val reason: String
)

interface MessageClassificationService {
    fun classify(message: StoredMessage): TriageResult
}

class LocalClassifier : MessageClassificationService {
    override fun classify(message: StoredMessage): TriageResult {
        val text = "${message.subject} ${message.snippet} ${message.fromAddress}".lowercase()
        return when {
            containsAny(text, listOf("urgent", "asap", "immediate", "critical", "emergency", "action required")) ->
                TriageResult(TriageCategory.URGENT, 0.9f, "Urgent keywords")
            containsAny(text, listOf("invoice", "payment", "receipt", "paid", "billing", "subscription")) ->
                TriageResult(TriageCategory.FINANCIAL, 0.85f, "Financial keywords")
            containsAny(text, listOf("meeting", "calendar", "invite", "schedule", "appointment", "zoom", "teams")) ->
                TriageResult(TriageCategory.MEETING, 0.8f, "Meeting keywords")
            containsAny(text, listOf("please review", "approval", "sign", "confirm", "feedback needed")) ->
                TriageResult(TriageCategory.ACTION, 0.75f, "Action keywords")
            containsAny(text, listOf("linkedin", "twitter", "facebook", "instagram", "social", "friend request")) ->
                TriageResult(TriageCategory.SOCIAL, 0.7f, "Social keywords")
            containsAny(text, listOf(
                "update", "newsletter", "digest", "weekly", "changelog",
                "webinar", "schedule", "roadmap", "what's next", "universe",
                "design mode", "is now", "live in", "q2", "q3", "q4"
            )) -> TriageResult(TriageCategory.UPDATES, 0.65f, "Update keywords")
            containsAny(text, listOf(
                "sale", "discount", "offer", "deal", "promo", "unsubscribe",
                "save", "early bird", "ending soon", "last chance",
                "invited", "pricing", "register"
            )) -> TriageResult(TriageCategory.PROMOTIONS, 0.6f, "Promotional keywords")
            else -> TriageResult(TriageCategory.GENERAL, 0.5f, "General")
        }
    }

    private fun containsAny(text: String, keywords: List<String>): Boolean =
        keywords.any { text.contains(it) }
}
