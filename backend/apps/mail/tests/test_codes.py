"""Finding one-time codes and sign-in links in verification mail, without a model."""

from __future__ import annotations

from django.test import SimpleTestCase

from backend.apps.mail.services import codes

CASES = (
    ('Your GitHub launch code', 'Here is your GitHub launch code: 48291037\nContinue signing in.\nOrder #77812 shipped 2025', '', '48291037'),
    ('G-482913 is your Google verification code', 'Your verification code is G-482913.', '', 'G-482913'),
    ('Confirm your email', 'Thanks for signing up!\n\n  739 204  \n\nEnter this code. Call 555-0199. Invoice 2026-10-15 total $1499', '', '739204'),
    ('Your login code', '', '<p>Hello,</p><p>Your one-time passcode is</p><h1>K7M-29Q</h1><p>It expires in 10 minutes.</p>', 'K7M-29Q'),
    ('Tu código de verificación', 'Tu código es: 551203', '', '551203'),
    ('123456 is your Instagram code', 'Use 123456 to confirm your account.', '', '123456'),
    ('Sign-in attempt', 'Your security code: 0042', '', '0042'),
    ('Welcome', 'Your PIN is\n8813\nDo not share it.', '', '8813'),
)  # fmt: skip
DISTRACTIONS = (
    ('Receipt', 'Thanks for your order 123456. Total: $49.99. Call 800 555 1234.', ''),
    ('Meeting', 'See you at 10:30 on 2026-10-20 in room 4012.', ''),
    ('Newsletter', 'In 2025 we grew 300%. Read more at https://news.example.com/2025', ''),
)  # fmt: skip


class CodeTests(SimpleTestCase):
    def test_codes_are_found(self) -> None:
        for subject, text, html, expected in CASES:
            with self.subTest(subject=subject):
                self.assertEqual(codes.extract(subject, text, html)['code'], expected)

    def test_numbers_that_are_not_codes_are_left_alone(self) -> None:
        for subject, text, html in DISTRACTIONS:
            with self.subTest(subject=subject):
                self.assertIsNone(codes.extract(subject, text, html)['code'])

    def test_invisible_characters_do_not_hide_or_fake_a_code(self) -> None:
        sneaky = 'Your verification code is 48​29​13.'
        self.assertEqual(codes.extract('Code', sneaky)['code'], '482913')

    def test_alternatives_are_ranked(self) -> None:
        result = codes.extract('Verify', 'Your verification code: 112233\nReference 998877')
        self.assertEqual(result['code'], '112233')
        self.assertLessEqual(len(result['codes']), 5)


class LinkTests(SimpleTestCase):
    def test_verification_and_magic_links(self) -> None:
        text = (
            'Confirm your address: https://acme.example.com/verify?token=abc123&u=9\n'
            'Unsubscribe: https://acme.example.com/unsubscribe?id=9'
        )
        self.assertEqual(codes.extract('Welcome', text)['link'], 'https://acme.example.com/verify?token=abc123&u=9')
        html = (
            '<a href="https://slack.example.com/z/magic-login/xyz?x=1">Sign in to Slack</a>'
            '<a href="https://slack.example.com/privacy">Privacy</a><img src="https://x/pixel.gif">'
        )
        self.assertEqual(codes.extract('Sign in', '', html)['link'], 'https://slack.example.com/z/magic-login/xyz?x=1')

    def test_link_text_counts_when_the_address_is_opaque(self) -> None:
        html = '<a href="https://e.example.com/c/ZXhhbXBsZQ">Confirm my email</a>'
        self.assertEqual(codes.extract('Hi', '', html)['link'], 'https://e.example.com/c/ZXhhbXBsZQ')

    def test_ordinary_links_are_not_sign_in_links(self) -> None:
        text = 'Read our blog https://acme.example.com/blog and our docs https://docs.example.com/'
        self.assertIsNone(codes.extract('News', text)['link'])

    def test_only_web_links(self) -> None:
        html = '<a href="javascript:alert(1)">Verify</a><a href="mailto:x@example.com">Confirm</a>'
        self.assertIsNone(codes.extract('Verify', '', html)['link'])
