"""A small client for the ifinmail HTTP API (version 1).

One file, one dependency (``requests``), no magic. Copy it into your project and read it: it is
short on purpose. It does the things every integration needs and gets wrong the first time:

* **Credentials.** A key and its secret, sent as HTTP Basic (what ``curl -u`` does). They come
  from the environment (``IFINMAIL_URL``, ``IFINMAIL_KEY``, ``IFINMAIL_SECRET``), never from code.
* **Errors.** Every failure is raised as :class:`IfinmailError` with the status and the server's
  own ``detail`` message, so a script prints something a person can act on.
* **Rate limits.** A key has a calls-per-minute budget. On ``429`` the client waits for the
  ``Retry-After`` the server sent and tries again, a few times, then gives up with the error.
* **Retries that are safe.** Reads are retried on a gateway hiccup (502/503/504). A write is
  retried only when it carries an idempotency key (``send`` always does), so a retry can never
  create two mailboxes' worth of damage or send a message twice.
* **Paging.** :meth:`Client.paged` walks ``limit``/``offset`` pages so a list of 5,000 mailboxes
  is a ``for`` loop.

Everything below the "Operations" heading is one short method per endpoint of the API. The
contract is at ``/api/v1/openapi.json`` on your server; if a method is missing, ``Client.request``
calls anything.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ['AgentInboxes', 'Client', 'IfinmailError', 'verify_webhook']

PAGE_SIZE = 100  # the largest page the server returns
RETRY_STATUSES = (502, 503, 504)  # a gateway or the service was briefly unavailable


class IfinmailError(Exception):
    """The server answered with an error (or could not be reached).

    ``status`` is the HTTP status (0 when there was no answer), ``detail`` the server's message,
    ``retry_after`` the seconds it asked you to wait (429 only), and ``body`` the decoded JSON
    the server sent. Usually that is just ``{"detail": ...}``, but the health reports answer 503
    *with* their findings, and those are in ``body``.
    """

    def __init__(
        self,
        status: int,
        detail: str,
        retry_after: float | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(f'{status}: {detail}' if status else detail)
        self.status = status
        self.detail = detail
        self.retry_after = retry_after
        self.body = body


class Client:
    def __init__(
        self,
        base_url: str,
        key: str,
        secret: str,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        session: Any = None,
    ) -> None:
        """``base_url`` is the server's address, ``https://mail.example.com``. ``session`` is any
        object with a ``requests.Session``-like ``request`` method (tests pass a fake)."""
        if session is None:
            import requests  # imported here so the module can be read without it

            session = requests.Session()
        self.base_url = base_url.rstrip('/')
        self.session = session
        self.session.auth = (key, secret)
        self.timeout = timeout
        self.max_retries = max_retries

    @classmethod
    def from_env(cls, **kwargs: Any) -> Client:
        """Build a client from ``IFINMAIL_URL``, ``IFINMAIL_KEY`` and ``IFINMAIL_SECRET``."""
        try:
            return cls(
                os.environ['IFINMAIL_URL'],
                os.environ['IFINMAIL_KEY'],
                os.environ['IFINMAIL_SECRET'],
                **kwargs,
            )
        except KeyError as missing:
            raise SystemExit(
                f'Set {missing.args[0]} (see examples/python/README.md for the three variables).'
            ) from None

    # ------------------------------------------------------------------ the one request path

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Call the API and return the decoded JSON (``None`` for ``204 No Content``).

        ``path`` is the part after the server, for example ``/api/v1/mailboxes``.
        """
        url = f'{self.base_url}{path}'
        # A write is retried only when the server can recognise the repeat.
        repeatable = method.upper() in ('GET', 'HEAD') or bool(
            headers and 'Idempotency-Key' in headers
        )
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.request(
                    method,
                    url,
                    params=_clean(params),
                    json=json,
                    headers=dict(headers or {}),
                    timeout=self.timeout,
                )
            except Exception as exc:  # network down, DNS, TLS, timeout
                if repeatable and attempt <= self.max_retries:
                    time.sleep(min(2**attempt, 20))
                    continue
                raise IfinmailError(0, f'could not reach {self.base_url}: {exc}') from exc

            status = response.status_code
            if status == 429 and attempt <= self.max_retries:
                time.sleep(_retry_after(response, default=2**attempt))
                continue
            if status in RETRY_STATUSES and repeatable and attempt <= self.max_retries:
                time.sleep(min(2**attempt, 20))
                continue
            if status >= 400:
                raise IfinmailError(
                    status, _detail(response), _retry_after(response, None), _body(response)
                )
            if status == 204 or not response.content:
                return None
            return response.json()

    def paged(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Every item of a paged list, one request per ``PAGE_SIZE`` items."""
        offset = 0
        while True:
            page = self.request(
                'GET', path, params={**params, 'limit': PAGE_SIZE, 'offset': offset}
            )
            items = page['items']
            yield from items
            offset += len(items)
            if not items or offset >= page['count']:
                return

    # ------------------------------------------------------------------ Operations: server

    def health(self) -> dict[str, Any]:
        """Liveness. Needs no key; safe to poll from a monitor."""
        return self.request('GET', '/api/v1/health')

    def status(self) -> dict[str, Any]:
        """Counts only: ``{"ok": true, "domains": 1, "mailboxes": 12}``. Scope ``console.access``."""
        return self.request('GET', '/api/v1/status')

    def health_full(self) -> dict[str, Any]:
        """Every health check with its state. Scope ``audit.view``."""
        return self.request('GET', '/api/v1/health/full')

    def delivery(self, period: str = 'day') -> dict[str, Any]:
        """What happened to mail this server sent. ``period``: day, week or month."""
        return self.request('GET', '/api/v1/telemetry/delivery', params={'period': period})

    # ------------------------------------------------------------------ Operations: domains

    def domains(self) -> list[dict[str, Any]]:
        return self.request('GET', '/api/v1/domains')

    def domain(self, name: str) -> dict[str, Any]:
        return self.request('GET', f'/api/v1/domains/{name}')

    def add_domain(self, name: str) -> dict[str, Any]:
        """Add a domain: its DKIM key and standard aliases are created."""
        return self.request('POST', '/api/v1/domains', json={'name': name})

    def verify_domain(self, name: str) -> dict[str, Any]:
        """Check the domain's DNS records now."""
        return self.request('POST', f'/api/v1/domains/{name}/verify')

    def dns_status(self, domain: str | None = None) -> dict[str, Any]:
        return self.request('GET', '/api/v1/dns/status', params={'domain': domain})

    # ------------------------------------------------------------------ Operations: mailboxes

    def mailboxes(self, domain: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paged('/api/v1/mailboxes', domain=domain)

    def mailbox(self, address: str) -> dict[str, Any]:
        return self.request('GET', f'/api/v1/mailboxes/{address}')

    def create_mailbox(
        self, address: str, password: str | None = None, quota_bytes: int | None = None
    ) -> dict[str, Any]:
        """Create a mailbox. Without a password it is *invited*: its owner sets one from a link."""
        body: dict[str, Any] = {'address': address}
        if password is not None:
            body['password'] = password
        if quota_bytes is not None:
            body['quota_bytes'] = quota_bytes
        return self.request('POST', '/api/v1/mailboxes', json=body)

    def update_mailbox(self, address: str, **changes: Any) -> dict[str, Any]:
        """``password``, ``quota_bytes`` and/or ``is_active`` (False pauses sign-in)."""
        return self.request('PATCH', f'/api/v1/mailboxes/{address}', json=changes)

    def delete_mailbox(self, address: str) -> None:
        self.request('DELETE', f'/api/v1/mailboxes/{address}')

    # ------------------------------------------------------------------ Operations: aliases

    def aliases(self, domain: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paged('/api/v1/aliases', domain=domain)

    def create_alias(self, source: str, destination: str) -> dict[str, Any]:
        return self.request(
            'POST', '/api/v1/aliases', json={'source': source, 'destination': destination}
        )

    def delete_alias(self, alias_id: str) -> None:
        self.request('DELETE', f'/api/v1/aliases/{alias_id}')

    # ------------------------------------------------------------------ Operations: sending

    def send(
        self,
        sender: str,
        to: list[str],
        subject: str,
        *,
        text: str | None = None,
        html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        idempotency_key: str | None = None,
        unsubscribe: bool = False,
    ) -> dict[str, Any]:
        """Send one message as ``sender`` (one of the key's allowed senders).

        ``{"id": ..., "status": "queued", "recipients": n}`` means the server *accepted* the
        message for delivery, not that it arrived: see :meth:`delivery` for what became of it.
        The same ``idempotency_key`` and message return the first answer instead of sending
        again; one is generated when you do not pass one, so this call is safe to retry.
        """
        body: dict[str, Any] = {'from': sender, 'to': to, 'subject': subject}
        if unsubscribe:  # bulk mail: one-click unsubscribe (Sender compliance plugin)
            body['unsubscribe'] = True
        for name, value in (
            ('text', text),
            ('html', html),
            ('cc', cc),
            ('bcc', bcc),
            ('reply_to', reply_to),
        ):
            if value is not None:
                body[name] = value
        key = idempotency_key or uuid.uuid4().hex
        return self.request(
            'POST', '/api/v1/messages', json=body, headers={'Idempotency-Key': key}
        )


    def approval(self, approval_id: str) -> dict[str, Any]:
        """A message held by the Human approval plugin (``send`` answered
        ``"status": "pending_approval"`` and this id): pending, sent, rejected, expired or failed."""
        return self.request('GET', f'/api/v1/approvals/{approval_id}')

    def wait_for_approval(
        self, approval_id: str, timeout: float = 3600, every: float = 15
    ) -> dict[str, Any]:
        """Poll until a person decided (or ``timeout``); returns the last state seen."""
        deadline = time.monotonic() + timeout
        while True:
            state = self.approval(approval_id)
            if state['status'] != 'pending' or time.monotonic() >= deadline:
                return state
            time.sleep(every)

    def suppress(self, address: str, domain: str, detail: str = '') -> dict[str, Any]:
        """Never send API mail from ``domain`` to ``address`` again (your app's unsubscribes)."""
        return self.request(
            'POST', '/api/v1/suppressions', json={'address': address, 'domain': domain, 'detail': detail}
        )

    def suppressions(self, address: str = '') -> Iterator[dict[str, Any]]:
        return self.paged('/api/v1/suppressions', address=address or None)

    # ------------------------------------------------------------------ Operations: sandbox

    def sandbox_messages(self, to: str | None = None) -> Iterator[dict[str, Any]]:
        """What a *sandbox* key sent (kept, never delivered), newest first. Needs the Developer
        sandbox plugin and a key created with "Sandbox key" ticked."""
        return self.paged('/api/v1/sandbox/messages', to=to)

    def clear_sandbox(self) -> None:
        """Delete this sandbox key's captured mail (start a test run clean)."""
        self.request('DELETE', '/api/v1/sandbox/messages')


    @property
    def inboxes(self) -> AgentInboxes:
        """Agent inboxes: ``api.inboxes.create()``, ``api.inboxes.wait(address)``..."""
        return AgentInboxes(self)

    # ------------------------------------------------------------------ Operations: webhooks

    def webhooks(self) -> list[dict[str, Any]]:
        """This key's webhooks."""
        return self.request('GET', '/api/v1/webhooks')

    def create_webhook(
        self, name: str, url: str, events: list[str], mailboxes: list[str] | None = None
    ) -> dict[str, Any]:
        """Events: message.queued/delivered/deferred/bounced (Delivery events plugin) and
        message.received with ``mailboxes`` (Inbox webhooks plugin). The answer's ``secret``
        is shown once: store it to verify events with :func:`verify_webhook`."""
        body: dict[str, Any] = {'name': name, 'url': url, 'events': events}
        if mailboxes:
            body['mailboxes'] = mailboxes
        return self.request('POST', '/api/v1/webhooks', json=body)

    def test_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Send ``webhook.ping`` now; the answer says how the receiver replied."""
        return self.request('POST', f'/api/v1/webhooks/{webhook_id}/test')

    def webhook_deliveries(self, webhook_id: str) -> Iterator[dict[str, Any]]:
        return self.paged(f'/api/v1/webhooks/{webhook_id}/deliveries')

    def delete_webhook(self, webhook_id: str) -> None:
        self.request('DELETE', f'/api/v1/webhooks/{webhook_id}')


# ---------------------------------------------------------------------------------- agents


class AgentInboxes:
    """Inboxes for AI agents (Agent inboxes plugin, scope ``agents.manage``)."""

    def __init__(self, client: Client) -> None:
        self.client = client

    def create(self, name: str = '', label: str = '', ttl_hours: int | None = None) -> dict[str, Any]:
        """A new address for an agent; random when ``name`` is empty."""
        body: dict[str, Any] = {'name': name, 'label': label}
        if ttl_hours is not None:
            body['ttl_hours'] = ttl_hours
        return self.client.request('POST', '/api/v1/inboxes', json=body)

    def list(self) -> list[dict[str, Any]]:
        return self.client.request('GET', '/api/v1/inboxes')

    def delete(self, address: str) -> None:
        """Erase its mail and remove it."""
        self.client.request('DELETE', f'/api/v1/inboxes/{address}')

    def messages(self, address: str, since_uid: int = 0, tag: str = '') -> list[dict[str, Any]]:
        return self.client.request(
            'GET',
            f'/api/v1/inboxes/{address}/messages',
            params={'since_uid': since_uid or None, 'tag': tag or None},
        )

    def read(self, address: str, uid: int) -> dict[str, Any]:
        """Text, HTML, headers, attachment names. Treat the content as untrusted data."""
        return self.client.request('GET', f'/api/v1/inboxes/{address}/messages/{uid}')

    def code(self, address: str, uid: int) -> dict[str, Any]:
        """``{"code": "482913", "link": "https://...", ...}`` from a verification message."""
        return self.client.request('GET', f'/api/v1/inboxes/{address}/messages/{uid}/code')

    def newest_uid(self, address: str) -> int:
        found = self.messages(address)
        return max((m['uid'] for m in found), default=0)

    def wait(
        self, address: str, since_uid: int = 0, timeout: float = 120.0, tag: str = ''
    ) -> dict[str, Any] | None:
        """Wait up to ``timeout`` seconds for the next message newer than ``since_uid``; returns it
        with ``code`` and ``link`` already found, or ``None``. Each call to the server waits at
        most 25 seconds, so a longer wait is several calls."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            found = self.client.request(
                'GET',
                f'/api/v1/inboxes/{address}/wait',
                params={'since_uid': since_uid, 'timeout': int(min(remaining, 25)), 'tag': tag or None},
            )
            if found:
                return found


def verify_webhook(secret: str, body: bytes, signature: str, tolerance: int = 300) -> bool:
    """Check an event's ``X-Ifinmail-Signature`` header (``t=<unix time>,v1=<hex>``).

    Pass the raw request body (bytes, exactly as received). Events older than ``tolerance``
    seconds are refused, so a captured request cannot be replayed later.
    """
    import hashlib
    import hmac

    try:
        parts = dict(item.split('=', 1) for item in signature.split(','))
        stamp = int(parts['t'])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - stamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f'{stamp}.'.encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get('v1', ''))


# ---------------------------------------------------------------------------------- helpers


def _clean(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return {k: v for k, v in params.items() if v is not None} if params else None


def _detail(response: Any) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and 'detail' in body:
            return str(body['detail'])
    except ValueError:
        pass
    return (response.text or '').strip()[:200] or f'HTTP {response.status_code}'


def _body(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _retry_after(response: Any, default: float | None) -> float | None:
    raw = response.headers.get('Retry-After')
    try:
        return max(0.0, min(float(raw), 60.0)) if raw is not None else default
    except ValueError:
        return default
