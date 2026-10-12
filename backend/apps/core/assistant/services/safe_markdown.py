"""A small, safe Markdown renderer for model answers (no third-party package).

Supported: CommonMark blocks and inlines (ATX and setext headings, paragraphs, hard and soft line
breaks, emphasis with the full delimiter-run rules, code spans, fenced and indented code, block
quotes, nested ordered and bullet lists with tight/loose handling, thematic breaks, inline,
reference and auto links, backslash escapes, character references) plus the GitHub extensions
tables with alignment, task lists, strikethrough and bare-URL autolinks.

Not supported on purpose: raw HTML (shown as text), images (a model could use an image URL to
send data out; they are shown as a plain link), footnotes and math.

Safety rules, all covered by tests:

* every character of input is HTML-escaped before it can reach the output;
* only tags this module writes itself are ever emitted;
* link targets are limited to http, https, mailto and same-site paths; anything else (including
  ``javascript:`` in any spelling) is shown as text;
* output is bounded: input length, nesting depth and delimiter work are capped.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.entities import html5 as named_entities
from urllib.parse import urlsplit

MAX_CHARS = 60_000
MAX_DEPTH = 6
_ALLOWED_SCHEMES = frozenset({'http', 'https', 'mailto'})
_ASCII_PUNCT = frozenset('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')

_FENCE = re.compile(r'^( {0,3})(`{3,}|~{3,})\s*([^\s`]*)[^`]*$')
_ATX = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$')
_HR = re.compile(r'^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$')
_SETEXT = re.compile(r'^ {0,3}(=+|-+)[ \t]*$')
_BULLET = re.compile(r'^( {0,3})([-+*])( +|$)')
_ORDERED = re.compile(r'^( {0,3})(\d{1,9})([.)])( +|$)')
_QUOTE = re.compile(r'^ {0,3}>')
_REF_DEF = re.compile(
    r'^ {0,3}\[([^\]\\]{1,200})\]:[ \t]*<?([^\s<>]+)>?(?:[ \t]+(?:"([^"]*)"|\'([^\']*)\'))?[ \t]*$'
)
_TABLE_DELIM = re.compile(r'^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$')
_TASK = re.compile(r'^\[([ xX])\][ \t]+')
_ENTITY = re.compile(r'&(#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});')
_AUTOLINK = re.compile(r'<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>]*)>')
_EMAIL_AUTOLINK = re.compile(
    r"<([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>'
)
_BARE_URL = re.compile(r'(?:https?://|www\.)[^\s<]+', re.I)
_LANG = re.compile(r'[A-Za-z0-9_+#.-]{1,24}')


def render(text: str) -> str:
    """HTML for ``text``, wrapped in ``<div class="ifinmail-md">``. Always safe to mark_safe."""
    text = (text or '')[:MAX_CHARS].replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '�')
    lines = [line.expandtabs(4) for line in text.split('\n')]
    refs = _collect_references(lines)
    body = ''.join(_blocks(lines, refs, 0, tight=False))
    return f'<div class="ifinmail-md">{body}</div>'


# ------------------------------------------------------------------------------------ helpers


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def _normalise_label(label: str) -> str:
    return ' '.join(label.split()).casefold()


def _collect_references(lines: list[str]) -> dict[str, tuple[str, str]]:
    refs: dict[str, tuple[str, str]] = {}
    fence = ''
    for line in lines:
        match = _FENCE.match(line)
        if match:
            marker = match.group(2)
            if not fence:
                fence = marker[0]
            elif marker[0] == fence and not match.group(3):
                fence = ''
            continue
        if fence:
            continue
        found = _REF_DEF.match(line)
        if found:
            label = _normalise_label(found.group(1))
            refs.setdefault(label, (found.group(2), found.group(3) or found.group(4) or ''))
    return refs


def _unbackslash(text: str) -> str:
    return re.sub(r'\\([!-/:-@\[-`{-~])', r'\1', text)


def _safe_url(url: str) -> str | None:
    """The URL when it may be linked, else None."""
    url = html.unescape(_unbackslash(url.strip()))
    if not url or any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        return None
    if url.startswith('#'):
        return url
    if url.startswith('/') and not url.startswith('//'):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme in ('http', 'https'):
        return url if parts.netloc else None
    if scheme == 'mailto':
        return url if parts.path else None
    return None


def _anchor(url: str, inner: str, title: str = '') -> str:
    external = not url.startswith(('/', '#'))
    attrs = f' href="{_esc(url)}"'
    if title:
        attrs += f' title="{_esc(html.unescape(_unbackslash(title)))}"'
    if external:
        attrs += ' rel="noopener noreferrer nofollow" target="_blank"'
    return f'<a{attrs}>{inner}</a>'


def _starts_block(line: str) -> bool:
    """True when ``line`` may interrupt a paragraph."""
    if _FENCE.match(line) or _ATX.match(line) or _HR.match(line) or _QUOTE.match(line):
        return True
    bullet = _BULLET.match(line)
    if bullet and line[bullet.end() :].strip():
        return True
    ordered = _ORDERED.match(line)
    return bool(ordered and ordered.group(2) == '1' and line[ordered.end() :].strip())


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith('|'):
        text = text[1:]
    if text.endswith('|') and not text.endswith('\\|'):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = ''  # the backtick run that opened a code span: pipes inside it do not split
    i = 0
    while i < len(text):
        char = text[i]
        if char == '\\' and text[i + 1 : i + 2] == '|':
            current.append('|')
            i += 2
        elif char == '`':
            token = text[i : len(text)]
            token = '`' * (len(token) - len(token.lstrip('`')))
            in_code = '' if in_code == token else (in_code or token)
            current.append(token)
            i += len(token)
        elif char == '|' and not in_code:
            cells.append(''.join(current).strip())
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    cells.append(''.join(current).strip())
    return cells


def _is_table_start(lines: list[str], i: int) -> bool:
    if i + 1 >= len(lines) or '|' not in lines[i] or not _TABLE_DELIM.match(lines[i + 1]):
        return False
    if '-' not in lines[i + 1]:
        return False
    return len(_split_row(lines[i])) == len(_split_row(lines[i + 1]))


# -------------------------------------------------------------------------------------- blocks


def _blocks(lines: list[str], refs: dict, depth: int, *, tight: bool) -> list[str]:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if depth >= MAX_DEPTH:  # too deeply nested: show the rest as text
            out.append(_paragraph('\n'.join(lines[i:]), refs, tight))
            break

        fence = _FENCE.match(line)
        if fence:
            i = _fenced(lines, i, fence, out)
            continue
        if _indent(line) >= 4:
            i = _indented_code(lines, i, out)
            continue
        atx = _ATX.match(line)
        if atx:
            out.append(_heading(len(atx.group(1)), atx.group(2) or '', refs))
            i += 1
            continue
        if _HR.match(line):
            out.append('<hr>')
            i += 1
            continue
        if _QUOTE.match(line):
            i = _blockquote(lines, i, refs, depth, out)
            continue
        if _BULLET.match(line) or _ORDERED.match(line):
            i = _list(lines, i, refs, depth, out)
            continue
        if _REF_DEF.match(line):
            i += 1
            continue
        if _is_table_start(lines, i):
            i = _table(lines, i, refs, out)
            continue
        i = _paragraph_block(lines, i, refs, tight, out)
    return out


def _heading(level: int, text: str, refs: dict) -> str:
    tag = f'h{min(level + 2, 6)}'  # the page owns h1 and h2
    return f'<{tag} class="ifinmail-md-h">{_inline(text.strip(), refs)}</{tag}>'


def _paragraph(text: str, refs: dict, tight: bool) -> str:
    body = _inline(text.strip(), refs)
    return body if tight else f'<p>{body}</p>'


def _paragraph_block(lines: list[str], i: int, refs: dict, tight: bool, out: list[str]) -> int:
    n = len(lines)
    collected = [lines[i].lstrip()]  # trailing spaces matter: two of them are a hard break
    i += 1
    while i < n and lines[i].strip():
        setext = _SETEXT.match(lines[i])
        if setext:
            level = 1 if setext.group(1)[0] == '=' else 2
            out.append(_heading(level, ' '.join(part.strip() for part in collected), refs))
            return i + 1
        if _starts_block(lines[i]) or _is_table_start(lines, i):
            break
        collected.append(lines[i].lstrip())
        i += 1
    out.append(_paragraph('\n'.join(collected), refs, tight))
    return i


def _fenced(lines: list[str], i: int, match: re.Match, out: list[str]) -> int:
    indent, marker, info = len(match.group(1)), match.group(2), match.group(3)
    body: list[str] = []
    n = len(lines)
    i += 1
    while i < n:
        closing = re.match(
            r'^ {0,3}(' + re.escape(marker[0]) + r'{' + str(len(marker)) + r',})\s*$', lines[i]
        )
        if closing:
            i += 1
            break
        line = lines[i]
        body.append(line[min(indent, _indent(line)) :])
        i += 1
    lang = info if _LANG.fullmatch(info or '') else ''
    out.append(_code_block('\n'.join(body), lang))
    return i


def _indented_code(lines: list[str], i: int, out: list[str]) -> int:
    body: list[str] = []
    n = len(lines)
    while i < n and (not lines[i].strip() or _indent(lines[i]) >= 4):
        body.append(lines[i][4:] if lines[i].strip() else '')
        i += 1
    while body and not body[-1]:
        body.pop()
    out.append(_code_block('\n'.join(body), ''))
    return i


def _code_block(code: str, lang: str) -> str:
    label = f' data-lang="{_esc(lang)}"' if lang else ''
    cls = f' class="language-{_esc(lang)}"' if lang else ''
    return f'<pre class="ifinmail-md-code"{label}><code{cls}>{_esc(code)}\n</code></pre>'


def _blockquote(lines: list[str], i: int, refs: dict, depth: int, out: list[str]) -> int:
    inner: list[str] = []
    n = len(lines)
    previous_blank = False
    while i < n:
        line = lines[i]
        if _QUOTE.match(line):
            stripped = re.sub(r'^ {0,3}> ?', '', line, count=1)
            inner.append(stripped)
            previous_blank = not stripped.strip()
        elif line.strip() and not previous_blank and inner and not _starts_block(line):
            inner.append(line)  # lazy continuation of a paragraph
        else:
            break
        i += 1
    body = ''.join(_blocks(inner, refs, depth + 1, tight=False))
    out.append(f'<blockquote>{body}</blockquote>')
    return i


def _marker(line: str, ordered: bool) -> re.Match | None:
    return _ORDERED.match(line) if ordered else _BULLET.match(line)


def _delimiter(match: re.Match, ordered: bool) -> str:
    return match.group(3) if ordered else match.group(2)


def _list(lines: list[str], i: int, refs: dict, depth: int, out: list[str]) -> int:
    first = _BULLET.match(lines[i]) or _ORDERED.match(lines[i])
    ordered = first.re is _ORDERED
    delimiter = _delimiter(first, ordered)
    start = int(first.group(2)) if ordered else 1
    n = len(lines)
    items: list[list[str]] = []
    loose = False
    while i < n:
        match = _marker(lines[i], ordered)
        if match is None or _delimiter(match, ordered) != delimiter:
            break
        marker_end = match.start(match.lastindex)  # indent + marker, before the spaces
        spaces = len(match.group(match.lastindex))
        rest = lines[i][match.end() :]
        if not rest.strip():
            content_indent, first_line = marker_end + 1, ''
        elif spaces > 4:  # "-     code": the content is an indented code block
            content_indent, first_line = marker_end + 1, ' ' * (spaces - 1) + rest
        else:
            content_indent, first_line = marker_end + spaces, rest
        item = [first_line]
        i += 1
        while i < n:
            line = lines[i]
            if not line.strip():
                k = i
                while k < n and not lines[k].strip():
                    k += 1
                has_content = bool(first_line.strip()) or len(item) > 1
                if k < n and _indent(lines[k]) >= content_indent and has_content:
                    item.extend([''] * (k - i))
                    i = k
                    continue
                break
            if _indent(line) >= content_indent:
                item.append(line[content_indent:])
                i += 1
            elif (
                item[-1].strip()
                and not _starts_block(line)
                and not _BULLET.match(line)
                and not _ORDERED.match(line)
            ):
                item.append(line.strip())  # lazy continuation of the item's paragraph
                i += 1
            else:
                break
        while item and not item[-1].strip():
            item.pop()
        if any(
            not item[x].strip() and item[x - 1].strip() and any(y.strip() for y in item[x + 1 :])
            for x in range(1, len(item))
        ):
            loose = True
        items.append(item)
        k = i
        while k < n and not lines[k].strip():
            k += 1
        following = _marker(lines[k], ordered) if k < n else None
        if following is None or _delimiter(following, ordered) != delimiter or _HR.match(lines[k]):
            i = k if k >= n else i
            break
        if k > i:  # a blank line between two items
            loose = True
        i = k
    rendered = ''.join(_list_item(item, refs, depth, tight=not loose) for item in items)
    tag = 'ol' if ordered else 'ul'
    attr = f' start="{start}"' if ordered and start != 1 else ''
    out.append(f'<{tag}{attr}>{rendered}</{tag}>')
    return i


def _list_item(item: list[str], refs: dict, depth: int, *, tight: bool) -> str:
    task = ''
    cls = ''
    if item and item[0].strip():
        match = _TASK.match(item[0])
        if match:
            checked = ' checked' if match.group(1) in 'xX' else ''
            task = f'<input type="checkbox" disabled{checked}> '
            item = [item[0][match.end() :], *item[1:]]
            cls = ' class="ifinmail-md-task"'
    body = ''.join(_blocks(item, refs, depth + 1, tight=tight))
    return f'<li{cls}>{task}{body}</li>'


def _table(lines: list[str], i: int, refs: dict, out: list[str]) -> int:
    header = _split_row(lines[i])
    aligns = []
    for cell in _split_row(lines[i + 1]):
        left, right = cell.startswith(':'), cell.endswith(':')
        aligns.append('center' if left and right else 'right' if right else 'left' if left else '')
    columns = len(header)
    i += 2
    rows: list[list[str]] = []
    n = len(lines)
    while i < n and lines[i].strip() and not _starts_block(lines[i]):
        cells = _split_row(lines[i])
        rows.append((cells + [''] * columns)[:columns])
        i += 1

    def cell(tag: str, text: str, column: int) -> str:
        cls = f' class="ifinmail-md-{aligns[column]}"' if aligns[column] else ''
        return f'<{tag}{cls}>{_inline(text, refs)}</{tag}>'

    head = ''.join(cell('th', text, c) for c, text in enumerate(header))
    body = ''.join(
        '<tr>' + ''.join(cell('td', text, c) for c, text in enumerate(row)) + '</tr>'
        for row in rows
    )
    out.append(
        '<div class="ifinmail-md-table"><table>'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )
    return i


# ------------------------------------------------------------------------------------- inlines


@dataclass
class _Delim:
    char: str
    count: int
    can_open: bool
    can_close: bool
    original: int = 0

    def __post_init__(self) -> None:
        self.original = self.count


@dataclass
class _Wrap:
    tag: str
    children: list = field(default_factory=list)


def _is_space(char: str) -> bool:
    return char == '' or char.isspace()


def _is_punct(char: str) -> bool:
    return bool(char) and unicodedata.category(char)[0] in ('P', 'S')


def _flanking(char: str, before: str, after: str) -> tuple[bool, bool]:
    left = not _is_space(after) and (not _is_punct(after) or _is_space(before) or _is_punct(before))
    right = not _is_space(before) and (
        not _is_punct(before) or _is_space(after) or _is_punct(after)
    )
    if char == '_':
        return left and (not right or _is_punct(before)), right and (not left or _is_punct(after))
    return left, right


def _inline(text: str, refs: dict, *, in_link: bool = False) -> str:
    nodes = _scan(text, refs, in_link)
    _emphasis(nodes)
    return ''.join(_stringify(node) for node in nodes)


def _stringify(node: object) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, _Delim):
        return _esc(node.char * node.count)
    inner = ''.join(_stringify(child) for child in node.children)
    return f'<{node.tag}>{inner}</{node.tag}>'


def _scan(text: str, refs: dict, in_link: bool) -> list:
    nodes: list = []
    buf: list[str] = []
    i, n = 0, len(text)

    def flush() -> None:
        if buf:
            nodes.append(_esc(''.join(buf)))
            buf.clear()

    while i < n:
        char = text[i]
        if char == '\\':
            if i + 1 < n and text[i + 1] == '\n':
                flush()
                nodes.append('<br>\n')
                i += 2
                while i < n and text[i] == ' ':
                    i += 1
                continue
            if i + 1 < n and text[i + 1] in _ASCII_PUNCT:
                buf.append(text[i + 1])
                i += 2
                continue
            buf.append('\\')
            i += 1
            continue
        if char == '`':
            run = len(text[i:]) - len(text[i:].lstrip('`'))
            close = _find_backtick_run(text, i + run, run)
            if close is None:
                buf.append('`' * run)
                i += run
                continue
            code = text[i + run : close].replace('\n', ' ')
            if len(code) > 2 and code[0] == ' ' and code[-1] == ' ' and code.strip():
                code = code[1:-1]
            flush()
            nodes.append(f'<code>{_esc(code)}</code>')
            i = close + run
            continue
        if char == '\n':
            joined = ''.join(buf)
            if joined.endswith('  '):
                buf.clear()
                buf.append(joined.rstrip(' '))
                flush()
                nodes.append('<br>\n')
            else:
                buf.clear()
                buf.append(joined.rstrip(' '))
                buf.append('\n')
            i += 1
            while i < n and text[i] == ' ':
                i += 1
            continue
        if char in '*_~':
            run = len(text[i:]) - len(text[i:].lstrip(char))
            before = text[i - 1] if i else ''
            after = text[i + run] if i + run < n else ''
            can_open, can_close = _flanking(char, before, after)
            flush()
            nodes.append(_Delim(char, run, can_open, can_close))
            i += run
            continue
        if char == '!' and i + 1 < n and text[i + 1] == '[' and not in_link:
            done = _link(text, i, refs, image=True)
            if done:
                flush()
                nodes.append(done[0])
                i = done[1]
                continue
        if char == '[' and not in_link:
            done = _link(text, i, refs, image=False)
            if done:
                flush()
                nodes.append(done[0])
                i = done[1]
                continue
        if char == '<':
            match = _AUTOLINK.match(text, i) or _EMAIL_AUTOLINK.match(text, i)
            if match and not in_link:
                target = match.group(1)
                if match.re is _EMAIL_AUTOLINK:
                    target = 'mailto:' + target
                safe = _safe_url(target)
                flush()
                shown = _esc(match.group(1))
                nodes.append(_anchor(safe, shown) if safe else shown)
                i = match.end()
                continue
            buf.append('<')
            i += 1
            continue
        if char == '&':
            match = _ENTITY.match(text, i)
            if match and (match.group(1).startswith('#') or match.group(1) + ';' in named_entities):
                buf.append(html.unescape(match.group(0)))
                i = match.end()
                continue
        if char in 'hHwW' and not in_link and (i == 0 or not text[i - 1].isalnum()):
            match = _BARE_URL.match(text, i)
            if match:
                url = _trim_url(match.group(0))
                if len(url) > 8:
                    href = url if url.lower().startswith('http') else 'https://' + url
                    safe = _safe_url(href)
                    if safe:
                        flush()
                        nodes.append(_anchor(safe, _esc(url)))
                        i += len(url)
                        continue
        buf.append(char)
        i += 1
    flush()
    return nodes


def _find_backtick_run(text: str, start: int, length: int) -> int | None:
    i, n = start, len(text)
    while i < n:
        if text[i] == '`':
            run = len(text[i:]) - len(text[i:].lstrip('`'))
            if run == length:
                return i
            i += run
        else:
            i += 1
    return None


def _trim_url(url: str) -> str:
    while url and url[-1] in '?!.,:;*_~\'"':
        url = url[:-1]
    while url.endswith(')') and url.count(')') > url.count('('):
        url = url[:-1]
    return url


def _find_bracket_end(text: str, start: int) -> int | None:
    depth, i, n = 0, start, len(text)
    while i < n:
        char = text[i]
        if char == '\\':
            i += 2
            continue
        if char == '`':
            run = len(text[i:]) - len(text[i:].lstrip('`'))
            close = _find_backtick_run(text, i + run, run)
            i = close + run if close is not None else i + run
            continue
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _parse_destination(text: str, i: int) -> tuple[str, str, int] | None:
    """After ``](``: destination, title and the index after ``)``."""
    n = len(text)
    while i < n and text[i] in ' \n':
        i += 1
    if i >= n:
        return None
    if text[i] == '<':
        j = i + 1
        while j < n and text[j] not in '>\n':
            j += 1
        if j >= n or text[j] != '>':
            return None
        dest, i = text[i + 1 : j], j + 1
    else:
        depth, j = 0, i
        while j < n:
            char = text[j]
            if char == '\\' and j + 1 < n:
                j += 2
                continue
            if char.isspace() or ord(char) < 32:
                break
            if char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
            j += 1
        dest, i = text[i:j], j
    while i < n and text[i] in ' \n':
        i += 1
    title = ''
    if i < n and text[i] in '"\'(':
        closer = ')' if text[i] == '(' else text[i]
        j = i + 1
        while j < n and text[j] != closer:
            j += 2 if text[j] == '\\' else 1
        if j >= n:
            return None
        title, i = text[i + 1 : j], j + 1
        while i < n and text[i] in ' \n':
            i += 1
    if i >= n or text[i] != ')':
        return None
    return dest, title, i + 1


def _link(text: str, i: int, refs: dict, *, image: bool) -> tuple[str, int] | None:
    start = i + 1 if image else i
    close = _find_bracket_end(text, start)
    if close is None:
        return None
    label = text[start + 1 : close]
    dest = title = None
    end = close + 1
    if text[end : end + 1] == '(':
        parsed = _parse_destination(text, end + 1)
        if parsed:
            dest, title, end = parsed
    if dest is None and text[end : end + 1] == '[':
        ref_close = text.find(']', end + 1)
        if ref_close != -1:
            key = _normalise_label(text[end + 1 : ref_close] or label)
            if key in refs:
                dest, title = refs[key]
                end = ref_close + 1
    if dest is None and _normalise_label(label) in refs and label.strip():
        dest, title = refs[_normalise_label(label)]
    if dest is None:
        return None
    if image:
        plain = re.sub(r'\s+', ' ', re.sub(r'[*_`~\\]', '', label)).strip() or 'image'
        safe = _safe_url(dest)
        shown = _esc(f'Image: {plain}')
        return (_anchor(safe, shown, title) if safe else shown), end
    inner = _inline(label, refs, in_link=True)
    safe = _safe_url(dest)
    return (_anchor(safe, inner, title) if safe else inner), end


def _emphasis(nodes: list) -> None:
    """CommonMark's process-emphasis over the delimiter runs in ``nodes`` (in place)."""
    i = 0
    while i < len(nodes):
        closer = nodes[i]
        if not (isinstance(closer, _Delim) and closer.can_close and closer.count > 0):
            i += 1
            continue
        found = None
        j = i - 1
        while j >= 0:
            opener = nodes[j]
            if (
                isinstance(opener, _Delim)
                and opener.char == closer.char
                and opener.can_open
                and opener.count > 0
            ):
                multiple_of_three = (opener.original + closer.original) % 3 == 0
                both_multiples = opener.original % 3 == 0 and closer.original % 3 == 0
                if (
                    (opener.can_close or closer.can_open)
                    and multiple_of_three
                    and not both_multiples
                ):
                    j -= 1
                    continue
                if closer.char == '~' and not (opener.count >= 2 and closer.count >= 2):
                    j -= 1
                    continue
                found = j
                break
            j -= 1
        if found is None:
            i += 1
            continue
        opener = nodes[found]
        use = 2 if opener.count >= 2 and closer.count >= 2 else 1
        tag = 'del' if closer.char == '~' else ('strong' if use == 2 else 'em')
        inner = nodes[found + 1 : i]
        opener.count -= use
        closer.count -= use
        nodes[found + 1 : i] = [_Wrap(tag, inner)]
        i = found + 2
        if opener.count == 0:
            del nodes[found]
            i -= 1
        if closer.count == 0:
            del nodes[i]
