"""Standard page text as Markdown, so an administrator edits the words instead of retyping them.

The page is rendered the way visitors see it and its content is converted: headings, paragraphs,
lists, emphasis, links and code blocks. Buttons, forms, scripts and the site's own menus are left
out. Text in, text out; it never touches the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from backend.apps.core.website.services import markup

_SKIP = {'script', 'style', 'svg', 'button', 'form', 'nav', 'header', 'footer', 'select', 'textarea'}
_VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'path'}
_BLOCKS = {
    'p', 'div', 'section', 'article', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'pre',
    'blockquote', 'table', 'tr', 'dl', 'dt', 'dd', 'figure', 'figcaption', 'details', 'summary',
}  # fmt: skip


@dataclass
class Starter:
    title: str = ''
    description: str = ''
    heading: str = ''
    lede: str = ''
    body: str = ''


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.skip = 0
        self.skip_btn = 0
        self.blocks: list[tuple[str, str]] = []  # (kind, text)
        self.inline: list[str] = []
        self.kind = 'p'
        self.lists: list[str] = []
        self.counter: list[int] = []
        self.in_pre = False
        self.links: list[str | None] = []
        self.lede_depth = 0
        self.in_h1 = False
        self.description = ''
        self.cells: list[str] = []
        self.in_cell = False

    # -- helpers -----------------------------------------------------------

    def flush(self) -> None:
        text = ''.join(self.inline)
        self.inline = []
        if self.in_cell:
            return
        text = text if self.in_pre else re.sub(r'\s+', ' ', text).strip()
        if text.strip():
            self.blocks.append((self.kind, text))
        self.kind = 'p'

    # -- parser ------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or '' for k, v in attrs}
        if tag == 'meta' and a.get('name') == 'description':
            self.description = a.get('content', '')
        if tag == 'main':
            self.in_main = True
            return
        if not self.in_main:
            return
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        classes = a.get('class', '')
        if tag == 'a' and 'ifinmail-btn' in classes:
            self.skip_btn += 1
            return
        if self.skip_btn:
            return
        if tag in _BLOCKS:
            self.flush()
        if tag == 'h1':
            self.kind = 'h1'
        elif tag in ('h2', 'h3', 'h4'):
            self.kind = tag
        elif tag == 'pre':
            self.in_pre = True
            self.kind = 'pre'
        elif tag in ('ul', 'ol'):
            self.lists.append(tag)
            self.counter.append(0)
        elif tag == 'li':
            self.kind = 'li'
            if self.counter:
                self.counter[-1] += 1
        elif tag == 'dt':
            self.kind = 'dt'
        elif tag == 'blockquote':
            self.kind = 'quote'
        elif tag == 'p' and 'ifinmail-site-lede' in classes:
            self.kind = 'lede'
        elif tag in ('td', 'th'):
            self.in_cell = True
            self.inline = []
        elif tag in ('strong', 'b'):
            self.inline.append('**')
        elif tag in ('em', 'i'):
            self.inline.append('*')
        elif tag == 'code' and not self.in_pre:
            self.inline.append('`')
        elif tag == 'a':
            href = a.get('href', '')
            keep = markup.safe_link(href) and not href.startswith('{%')
            self.links.append(href if keep else None)
            self.inline.append('[' if keep else '')
        elif tag == 'br':
            self.inline.append(' ')

    def handle_endtag(self, tag: str) -> None:
        if tag == 'main':
            self.flush()
            self.in_main = False
            return
        if not self.in_main:
            return
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == 'a':
            if self.skip_btn:
                self.skip_btn -= 1
                return
            href = self.links.pop() if self.links else None
            if href:
                self.inline.append(f']({href})')
            return
        if self.skip_btn:
            return
        if tag in ('td', 'th'):
            text = re.sub(r'\s+', ' ', ''.join(self.inline)).strip()
            self.inline = []
            self.in_cell = False
            if text:
                self.cells.append(text)
        elif tag == 'tr':
            if self.cells:
                self.blocks.append(('li', ' — '.join(self.cells)))
            self.cells = []
        elif tag in ('strong', 'b'):
            self.inline.append('**')
        elif tag in ('em', 'i'):
            self.inline.append('*')
        elif tag == 'code' and not self.in_pre:
            self.inline.append('`')
        elif tag in ('ul', 'ol'):
            self.flush()
            if self.lists:
                self.lists.pop()
                self.counter.pop()
            self.blocks.append(('end-list', ''))
        elif tag in _BLOCKS:
            kind_before, number = self.kind, (self.counter[-1] if self.counter else 0)
            ordered = bool(self.lists) and self.lists[-1] == 'ol'
            self.flush()
            if tag == 'pre':
                self.in_pre = False
            if kind_before == 'li' and ordered and self.blocks and self.blocks[-1][0] == 'li':
                self.blocks[-1] = (f'li-ol-{number}', self.blocks[-1][1])

    def handle_data(self, data: str) -> None:
        if self.in_main and not self.skip and not self.skip_btn:
            self.inline.append(data)


def _body(blocks: list[tuple[str, str]], skip_first_h1: bool) -> str:
    out: list[str] = []
    has_h1 = any(kind == 'h1' for kind, _ in blocks)
    seen_h1 = False
    previous = ''
    for kind, text in blocks:
        if kind == 'h1':
            seen_h1 = True
            if skip_first_h1:
                continue
        if kind == 'lede':
            continue
        if kind == 'end-list':
            previous = ''
            continue
        if has_h1 and not seen_h1 and kind != 'h1':
            continue  # the small label above the heading
        if kind.startswith('li-'):
            _, ltype, number = kind.split('-')
            out.append(f'{number}. {text}' if ltype == 'ol' else f'- {text}')
            previous = 'li'
            continue
        if kind == 'li':
            out.append(f'- {text}')
            previous = 'li'
            continue
        if previous == 'li':
            out.append('')
        previous = ''
        if kind in ('h1', 'h2'):
            out.append('\n## ' + text)
        elif kind in ('h3', 'h4'):
            out.append('\n### ' + text)
        elif kind == 'pre':
            out.append('\n```\n' + text.strip('\n') + '\n```')
        elif kind == 'quote':
            out.append('> ' + text)
        elif kind == 'dt':
            out.append('\n**' + text + '**')
        else:
            out.append('\n' + text if out else text)
    text = '\n'.join(out)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # items of one list follow each other without blank lines
    return text.strip()


def convert(html: str) -> Starter:
    parser = _Converter()
    parser.feed(html)
    parser.close()
    heading = next((t for k, t in parser.blocks if k == 'h1'), '')
    lede = next((t for k, t in parser.blocks if k == 'lede'), '')
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    name = re.sub(r'\s+', ' ', title.group(1)).strip() if title else ''
    # The site appends " — Name" to each title; the editor's title is the part before it.
    return Starter(
        title=name.split(' — ')[0].strip(),
        description=parser.description,
        heading=heading,
        lede=lede,
        body=_body(parser.blocks, skip_first_h1=True),
    )
