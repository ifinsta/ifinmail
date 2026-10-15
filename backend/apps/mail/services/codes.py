"""Finding the one-time code or the sign-in link in a verification email.

Agents sign up for services and must read back "Your code is 482 913" or "Click to confirm your
address". This does that without a model: candidates are found by pattern and ranked by how close
they are to words that announce a code ("code", "OTP", "verification", "PIN", in several
languages), how they are written (a code alone on its line, in the subject, six digits), and
what they are not (a year, a phone number, a price, an order number, a date).

Links are those whose address or text says what they are for (verify, confirm, activate, magic,
sign in, reset, token); unsubscribe, privacy and image links are dropped.

The result is a ranked list so a caller can take the first and still see the alternatives.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

_INVISIBLE = re.compile('[​-‏ -‮⁠-⁤﻿­]')
_KEYWORDS = re.compile(
    r'(?i)\b(code|otp|one[- ]?time|passcode|pass code|pin|verification|verify|security code|'
    r'login code|sign[- ]?in code|confirmation|confirm|token|2fa|two[- ]factor|auth(?:entication)?|'
    r'código|codigo|verificación|code de vérification|vérification|bestätigungscode|'
    r'bestätigung|sicherheitscode|kod|codice|verifica)\b'
)
# Numbers (optionally grouped "482 913" / "482-913"), and mixed letters+digits like "K7M-29Q".
_NUMERIC = re.compile(
    r'(?<![\w.,/:$€£#-])(\d{3,4}[ -]\d{3,4}|\d{4,8})(?![\w/%:-]|[.,]\d)'
)
_ALNUM = re.compile(
    r'(?<![\w-])([A-Z]{1,3}-\d{4,8}|'
    r'(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{3,5}-[A-Z0-9]{3,5}|'
    r'(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,10})(?![\w-])'
)
_NOT_A_CODE = re.compile(
    r'(?i)(order|invoice|ticket|case|account|customer|reference|ref\.?|phone|tel|call|fax|'
    r'zip|postal|street|suite|apt|price|total|amount|usd|eur|gbp|\$|€|£|#)\s*:?\s*$'
)
_URL = re.compile(r'https?://[^\s<>"\')\]]+', re.I)
_HREF = re.compile(r'''(?is)<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>''')
_LINK_WORDS = re.compile(
    r'(?i)(verif|confirm|activat|magic|sign[-_]?in|signin|log[-_]?in|login|auth|token|reset|'
    r'validate|callback|one[-_]?time|otp|invite|accept|approve)'
)
_LINK_NOISE = re.compile(
    r'(?i)(unsubscribe|optout|opt-out|preferences|privacy|terms|policy|help|support|facebook|'
    r'twitter|linkedin|instagram|youtube|\.png|\.jpg|\.gif|\.svg|/images?/|tracking/open|pixel)'
)


@dataclass(frozen=True)
class Code:
    value: str  # normalised: spaces and dashes inside a numeric code removed
    shown: str  # as written in the message
    score: int
    where: str  # "subject" | "body"


@dataclass(frozen=True)
class Link:
    url: str
    text: str
    score: int


def _clean(text: str) -> str:
    return _INVISIBLE.sub('', html_lib.unescape(text or ''))


def _strip_html(html: str) -> str:
    text = re.sub(r'(?is)<(script|style|head)[^>]*>.*?</\1>', ' ', html or '')
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</td>|</li>|</h\d>', '\n', text)
    return _clean(re.sub(r'<[^>]+>', ' ', text))


def _is_year_or_date(value: str, before: str, after: str) -> bool:
    if re.fullmatch(r'(19|20)\d\d', value):
        return True
    return bool(re.search(r'[/.]\s*$', before) or re.match(r'^\s*[/.]\d', after))


def _score_code(value: str, text: str, start: int, end: int, *, subject: bool) -> int | None:
    before, after = text[max(0, start - 80) : start], text[end : end + 40]
    digits = re.sub(r'\D', '', value)
    if _NOT_A_CODE.search(before[-30:]):
        return None
    if digits and _is_year_or_date(value, before, after):
        return None
    if re.match(r'^\s*(%|px|ms|kb|mb|gb|usd|eur|€|\$)', after, re.I):
        return None
    score = 0
    near = _KEYWORDS.search(before[-60:]) or _KEYWORDS.search(after[:30])
    if near:
        score += 50
    elif _KEYWORDS.search(before):
        score += 25
    line_start = text.rfind('\n', 0, start) + 1
    line_end = text.find('\n', end)
    line = text[line_start : line_end if line_end != -1 else len(text)].strip()
    if line == value.strip():
        score += 20  # a code alone on its line
    if len(digits) == 6:
        score += 10
    elif len(digits) in (4, 5, 7, 8):
        score += 4
    if subject:
        score += 15
    if re.search(r'[:：]\s*$', before):
        score += 5
    return score if score >= 20 else None


def find_codes(subject: str, text: str, html: str = '') -> list[Code]:
    body = _clean(text) or _strip_html(html)
    found: dict[str, Code] = {}
    for where, source in (('subject', _clean(subject)), ('body', body)):
        for pattern in (_NUMERIC, _ALNUM):
            for match in pattern.finditer(source):
                shown = match.group(1)
                value = re.sub(r'[ -]', '', shown) if re.fullmatch(r'[\d -]+', shown) else shown
                score = _score_code(shown, source, match.start(1), match.end(1), subject=where == 'subject')
                if score is None:
                    continue
                best = found.get(value)
                if best is None or score > best.score:
                    found[value] = Code(value=value, shown=shown, score=score, where=where)
    return sorted(found.values(), key=lambda c: (-c.score, c.where != 'subject'))


def find_links(text: str, html: str = '') -> list[Link]:
    candidates: list[tuple[str, str]] = [
        (html_lib.unescape(url), _clean(re.sub(r'<[^>]+>', ' ', label)).strip())
        for url, label in _HREF.findall(html or '')
    ]
    candidates += [(url.rstrip('.,;'), '') for url in _URL.findall(_clean(text))]
    links: dict[str, Link] = {}
    for url, label in candidates:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            continue
        haystack = unquote(f'{parts.path}?{parts.query}')
        if _LINK_NOISE.search(haystack) or _LINK_NOISE.search(label):
            continue
        score = 0
        if _LINK_WORDS.search(haystack):
            score += 40
        if _LINK_WORDS.search(label):
            score += 30
        if re.search(r'(?i)[?&](token|code|key|t|otp|signature|sig)=', parts.query):
            score += 15
        if score < 30:
            continue
        current = links.get(url)
        if current is None or score > current.score:
            links[url] = Link(url=url, text=label[:120], score=score)
    return sorted(links.values(), key=lambda link: -link.score)


def extract(subject: str, text: str, html: str = '') -> dict:
    codes = find_codes(subject, text, html)
    links = find_links(text, html)
    return {
        'code': codes[0].value if codes else None,
        'link': links[0].url if links else None,
        'codes': [{'value': c.value, 'shown': c.shown, 'score': c.score, 'where': c.where} for c in codes[:5]],
        'links': [{'url': link.url, 'text': link.text, 'score': link.score} for link in links[:5]],
    }
