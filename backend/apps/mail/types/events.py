"""Events the server can send to webhooks, and what each one means."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    # Delivery Events plugin: mail sent through the API.
    QUEUED = 'message.queued'  # the API accepted it for delivery
    DELIVERED = 'message.delivered'  # a receiving server accepted it (not "in the inbox")
    DEFERRED = 'message.deferred'  # an attempt failed and will be retried
    BOUNCED = 'message.bounced'  # it failed for good for one recipient
    # Inbox Webhooks plugin: mail received by a mailbox.
    RECEIVED = 'message.received'
    # Sent by "Send a test event"; never sent otherwise.
    PING = 'webhook.ping'


DELIVERY_EVENTS = (EventType.QUEUED, EventType.DELIVERED, EventType.DEFERRED, EventType.BOUNCED)
SUBSCRIBABLE = (*DELIVERY_EVENTS, EventType.RECEIVED)

DESCRIPTIONS = {
    EventType.QUEUED: 'The API accepted a message for delivery.',
    EventType.DELIVERED: 'A receiving server accepted the message (it may still file it as spam).',
    EventType.DEFERRED: 'A delivery attempt failed and will be retried.',
    EventType.BOUNCED: 'Delivery to a recipient failed for good.',
    EventType.RECEIVED: 'A mailbox received a message.',
}
