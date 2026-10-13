"""Mail trace: follow one message through Postfix, Rspamd and Dovecot.

The three logs share two keys: the queue id Postfix gives a message (Rspamd logs it too) and the
Message-ID header (Dovecot logs it when it saves the message). A search finds the lines that match,
collects those keys, then gathers every line carrying them and turns each into one plain sentence.
Subjects and bodies are not in the logs; addresses are, so this is for administrators only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.apps.core.telemetry.threats import mail_log
from backend.apps.core.telemetry.threats.access_log import _tail

MIN_QUERY = 3
MAX_MESSAGES = 5
MAX_LINES_PER_MESSAGE = 40
_QID = re.compile(r'(?:postfix/[\w/]+\[\d+\]: |qid: <)(?P<qid>[0-9A-Za-z]{8,})[:>,]')
_MSGID = re.compile(r'(?:message-id|msgid|id: )=?<(?P<id>[^>]+)>')
_SIZE = re.compile(r'size=(?P<size>\d+), nrcpt=(?P<n>\d+)')
_CLIENT = re.compile(
    r'client=(?P<client>[^,\s]+)(?:, sasl_method=(?P<m>\w+), sasl_username=(?P<u>[^,\s]+))?'
)
_TO = re.compile(r'to=<(?P<to>[^>]*)>, (?:orig_to=<[^>]*>, )?relay=(?P<relay>[^,]*)')
_STATUS = re.compile(r'status=(?P<status>\w+) \((?P<why>[^)]{0,160})')
_RSPAMD = re.compile(
    r'\(default: [TF] \((?P<action>[^)]+)\): \[(?P<score>-?[0-9.]+)/(?P<limit>[0-9.]+)\]'
)
_FROM = re.compile(r'from=<(?P<from>[^>]*)>')


@dataclass
class Step:
    at: datetime
    source: str
    text: str
    tone: str = 'neutral'  # ok | warning | error | neutral


@dataclass
class Trace:
    qid: str
    steps: list[Step] = field(default_factory=list)
    sender: str = ''
    recipients: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        tones = [s.tone for s in self.steps]
        if 'error' in tones:
            return 'failed'
        if any(s.text.startswith('Delivered') or s.text.startswith('Sent') for s in self.steps):
            return 'delivered'
        if 'warning' in tones:
            return 'delayed'
        return 'in progress'


def _sentence(source: str, rest: str) -> tuple[str, str] | None:
    """One plain sentence (and a tone) for a log line, or ``None`` for lines that add nothing."""
    if source == 'rspamd':
        m = _RSPAMD.search(rest)
        if m:
            action = m['action']
            tone = 'error' if action == 'reject' else 'warning' if action != 'no action' else 'ok'
            return f'Spam filter: {action} (score {m["score"]} of {m["limit"]})', tone
        return None
    if source == 'dovecot':
        if 'saved mail to' in rest:
            box = rest.split('saved mail to', 1)[1].strip().split()[0] if rest else 'INBOX'
            return f'Delivered to the mailbox ({box})', 'ok'
        return None
    m = _CLIENT.search(rest)
    if m and 'client=' in rest:
        who = f', signed in as {m["u"]}' if m['u'] else ''
        return f'Received from {m["client"]}{who}', 'neutral'
    m = _SIZE.search(rest)
    if m and 'queue active' in rest:
        return f'Queued ({int(m["size"]):,} bytes, {m["n"]} recipient(s))', 'neutral'
    m = _TO.search(rest)
    s = _STATUS.search(rest)
    if m and s:
        word = {'sent': 'Sent', 'deferred': 'Deferred', 'bounced': 'Bounced'}.get(
            s['status'], s['status']
        )
        local = 'lmtp' in rest.split(':', 1)[0] or 'dovecot' in m['relay']
        where = 'to the mailbox' if local else f'to {m["relay"].split("[")[0] or m["to"]}'
        if s['status'] == 'sent':
            return (f'Delivered {where}' if local else f'Sent {where}'), 'ok'
        tone = 'error' if s['status'] == 'bounced' else 'warning'
        return f'{word} {where}: {s["why"].strip()}', tone
    if 'removed' in rest and 'qmgr' in rest:
        return 'Removed from the queue (finished)', 'neutral'
    if 'milter-reject' in rest:
        return 'Rejected by the spam filter at the door', 'error'
    return None


def search(
    query: str, now: datetime | None = None, *, directory: Path | None = None
) -> list[Trace]:
    """Up to ``MAX_MESSAGES`` traces for messages whose log lines mention ``query``."""
    needle = query.strip().lower()
    if len(needle) < MIN_QUERY:
        return []
    now = now or datetime.now(UTC)
    base = directory or mail_log.log_dir()
    lines: list[tuple[datetime, str, str]] = []  # (time, source, raw)
    for name in mail_log.FILES:
        source = mail_log.SERVICE_OF[name]
        main = base / name
        for path in (main.with_name(name + '.1'), main):
            data, _ = _tail(path, mail_log.MAX_BYTES)
            for raw in data.decode('utf-8', 'replace').splitlines():
                split = mail_log._split(raw, now)  # noqa: SLF001
                if split is not None:
                    lines.append((split[0], source, split[1]))
    qids: list[str] = []
    for _, _, rest in sorted(lines, key=lambda x: x[0], reverse=True):
        if needle not in rest.lower():
            continue
        q = _QID.search(rest)
        if q and q['qid'] not in qids:
            qids.append(q['qid'])
            if len(qids) >= MAX_MESSAGES:
                break
    if not qids:
        return []
    # Dovecot logs the Message-ID, not the queue id; Postfix and Rspamd log both.
    by_message_id: dict[str, str] = {}
    for _, _, rest in lines:
        q, m = _QID.search(rest), _MSGID.search(rest)
        if q and m and q['qid'] in qids:
            by_message_id[m['id']] = q['qid']
    traces = {qid: Trace(qid) for qid in qids}
    for at, source, rest in sorted(lines, key=lambda x: x[0]):
        q = _QID.search(rest)
        qid = q['qid'] if q else ''
        if qid not in traces:
            m = _MSGID.search(rest)
            qid = by_message_id.get(m['id'], '') if m and source == 'dovecot' else ''
        target = traces.get(qid)
        if target is None or len(target.steps) >= MAX_LINES_PER_MESSAGE:
            continue
        sentence = _sentence(source, rest)
        if sentence is None:
            continue
        sender = _FROM.search(rest)
        if sender and not target.sender:
            target.sender = sender['from']
        to = _TO.search(rest)
        if to and to['to'] not in target.recipients:
            target.recipients.append(to['to'])
        target.steps.append(Step(at, source, sentence[0], sentence[1]))
    return [traces[q] for q in qids if traces[q].steps]
