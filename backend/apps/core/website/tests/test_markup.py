"""The administrator's text is shown as text: nothing in it can become markup."""

from __future__ import annotations

from django.test import SimpleTestCase

from backend.apps.core.website.services import markup


class MarkupTests(SimpleTestCase):
    def test_the_supported_marks(self) -> None:
        html = markup.render(
            '## Heading\n\nA **bold** and *italic* and `code` word.\n\n- one\n- two\n\n'
            '1. first\n2. second\n\n> quoted\n\n---\n\nSee [the docs](https://example.com/a?b=1&c=2).'
        )
        self.assertIn('<h2>Heading</h2>', html)
        self.assertIn('<strong>bold</strong>', html)
        self.assertIn('<em>italic</em>', html)
        self.assertIn('<code>code</code>', html)
        self.assertIn('<ul><li>one</li><li>two</li></ul>', html)
        self.assertIn('<ol><li>first</li><li>second</li></ol>', html)
        self.assertIn('<blockquote>', html)
        self.assertIn('<hr>', html)
        self.assertIn('href="https://example.com/a?b=1&amp;c=2" rel="noopener noreferrer"', html)

    def test_html_and_scripts_are_text(self) -> None:
        html = markup.render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n**<b>x</b>**')
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<b>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_dangerous_links_stay_text(self) -> None:
        for url in (
            'javascript:alert(1)',
            'JaVaScRiPt:alert(1)',
            'data:text/html;base64,AAAA',
            'vbscript:x',
            '//evil.example/x',
            ' javascript:alert(1)',
            'file:///etc/passwd',
        ):
            with self.subTest(url=url):
                html = markup.render(f'[click]({url})')
                self.assertNotIn('<a ', html)
                self.assertNotIn('href=', html)

    def test_attribute_breakouts_are_escaped(self) -> None:
        html = markup.render('[x](https://a.example/"onmouseover="alert(1))')
        self.assertNotIn('onmouseover="alert', html)
        html = markup.render('[x"><script>](https://a.example/)')
        self.assertNotIn('<script', html)

    def test_code_blocks_are_not_interpreted(self) -> None:
        html = markup.render('```\n<b>**x**</b>\n```')
        self.assertIn('&lt;b&gt;**x**&lt;/b&gt;', html)
        self.assertNotIn('<strong>', html)

    def test_safe_link(self) -> None:
        for good in ('https://a.example', 'http://a.example', 'mailto:a@b.example', '/docs/', '#install', 'tel:+123'):
            self.assertTrue(markup.safe_link(good), good)
        for bad in ('', 'javascript:x', '//a.example', 'ftp://a.example', 'a.example', 'https://a\nb'):
            self.assertFalse(markup.safe_link(bad), bad)
