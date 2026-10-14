"""A small, safe Markdown: what an administrator may write on their own pages.

Everything is HTML-escaped before any markup is added, links are limited to a few schemes, and
no raw HTML, image or script can get through. Supported: ``##``/``###`` headings, paragraphs,
``-`` and ``1.`` lists, ``>`` quotes, ``---`` rules, fenced code, and inside text ``**bold**``,
``*italic*``, `` `code` `` and ``[text](link)``.
"""

from __future__ import annotations

import re
from html import unescape

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

_SCHEMES = ('https://', 'http://', 'mailto:', 'tel:')
_LINK = re.compile(r'\[([^\]\n]{1,200})\]\(([^)\s]{1,300})\)')
_BOLD = re.compile(r'\*\*(.+?)\*\*')
_ITALIC = re.compile(r'(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])')
_CODE = re.compile(r'`([^`\n]+)`')
_ORDERED = re.compile(r'^\d{1,3}[.)]\s+(.*)$')


def safe_link(url: str) -> bool:
    """Whether a link may be written into a page: a web or mail address, a path on this site, or
    an anchor. Anything else (``javascript:``, ``data:``, ``//host``) is refused."""
    url = url.strip()
    if not url or len(url) > 300 or any(ord(c) < 32 for c in url):
        return False
    if url.startswith(_SCHEMES):
        return True
    if url.startswith('//') or url.startswith('/\\'):
        return False
    return url.startswith(('/', '#'))


def _inline(text: str) -> str:
    out = escape(text)
    codes: list[str] = []

    def stash(match: re.Match) -> str:
        codes.append(f'<code>{match.group(1)}</code>')
        return f'\x00{len(codes) - 1}\x00'

    out = _CODE.sub(stash, out)

    def link(match: re.Match) -> str:
        label, url = match.group(1), unescape(match.group(2))
        if not safe_link(url):
            return match.group(0)
        external = url.startswith(('http://', 'https://'))
        rel = ' rel="noopener noreferrer"' if external else ''
        return f'<a href="{escape(url)}"{rel}>{label}</a>'

    out = _LINK.sub(link, out)
    out = _BOLD.sub(r'<strong>\1</strong>', out)
    out = _ITALIC.sub(r'<em>\1</em>', out)
    return re.sub(r'\x00(\d+)\x00', lambda m: codes[int(m.group(1))], out)


def render(source: str) -> SafeString:
    lines = source.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    html: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_kind = ''
    quote: list[str] = []

    def flush() -> None:
        nonlocal list_kind
        if paragraph:
            html.append(f'<p>{_inline(" ".join(paragraph))}</p>')
            paragraph.clear()
        if items:
            html.append(f'<{list_kind}>' + ''.join(f'<li>{_inline(i)}</li>' for i in items) + f'</{list_kind}>')
            items.clear()
            list_kind = ''
        if quote:
            html.append(f'<blockquote><p>{_inline(" ".join(quote))}</p></blockquote>')
            quote.clear()

    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        index += 1
        if line.startswith('```'):
            flush()
            code: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith('```'):
                code.append(lines[index])
                index += 1
            index += 1
            html.append(f'<pre><code>{escape(chr(10).join(code))}</code></pre>')
            continue
        if not line:
            flush()
            continue
        heading = re.match(r'^(#{1,3})\s+(.+?)\s*#*$', line)
        if heading:
            flush()
            level = 2 if len(heading.group(1)) < 3 else 3
            html.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
            continue
        if re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', line):
            flush()
            html.append('<hr>')
            continue
        if line.startswith('>'):
            if paragraph or items:
                flush()
            quote.append(line.lstrip('>').strip())
            continue
        bullet = re.match(r'^[-*+]\s+(.*)$', line)
        ordered = _ORDERED.match(line)
        if bullet or ordered:
            kind = 'ul' if bullet else 'ol'
            if paragraph or quote or (items and list_kind != kind):
                flush()
            list_kind = kind
            items.append((bullet or ordered).group(1))
            continue
        if items or quote:
            flush()
        paragraph.append(line)
    flush()
    return mark_safe(''.join(html))  # noqa: S308 - every text node was escaped above
