package com.ifinmail.core.domain.event

import com.ifinmail.core.domain.model.StoredMessage
import com.ifinmail.core.domain.error.MailError
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

sealed interface DomainEvent {
    data class AccountAdded(val accountId: String, val email: String) : DomainEvent
    data class MessageReceived(val accountId: String, val count: Int) : DomainEvent
    data class MessageRead(val accountId: String, val messageId: String, val read: Boolean) : DomainEvent
    data class MessageDeleted(val accountId: String, val messageId: String) : DomainEvent
    data class MessageSubmitted(val accountId: String, val subject: String) : DomainEvent
    data class SubmissionQueued(val accountId: String, val mutationId: String) : DomainEvent
    data class MutationsFlushed(val accountId: String, val count: Int) : DomainEvent
    data class SyncCompleted(val accountId: String, val newCount: Int) : DomainEvent
    data class SyncFailed(val accountId: String, val error: MailError) : DomainEvent
    data class SubmissionFailed(val accountId: String, val error: MailError) : DomainEvent
}

class DomainEventBus {
    private val flow = MutableSharedFlow<DomainEvent>(extraBufferCapacity = 256)

    val events: SharedFlow<DomainEvent> = flow

    fun publish(event: DomainEvent) {
        flow.tryEmit(event)
    }
}
