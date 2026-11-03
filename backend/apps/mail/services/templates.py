"""Templates: messages kept on the server to be sent again (Marketing plugin).

A template is a subject and a text and/or html body with ``{{merge}}`` tags. A campaign names one
instead of carrying the message in the request, and what the campaign gives (a different subject,
say) wins over the template. The campaign **copies** the template when it is created, so editing or
deleting a template never changes a campaign that exists.

A key sees and changes the templates it created; a key with ``mail.manage`` sees all of them.

Failures carry a status and a message that are safe to show.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from django.db.models import QuerySet

from backend.apps.mail.models import Template
from backend.apps.mail.services import marketing
from backend.apps.mail.services.messages import SendRefused

MAX_NAME = 120
MAX_PER_KEY = 500  # templates one key may keep


@dataclass(frozen=True)
class TemplateKey:
    """What templates need to know about the key making the call."""

    prefix: str
    manager: bool = False  # mail.manage: sees every template


@dataclass
class Preview:
    subject: str
    text: str
    html: str
    missing: list[str] = field(default_factory=list)  # tags with no value and no fallback


def visible(key: TemplateKey) -> QuerySet[Template]:
    rows = Template.objects.all()
    return rows if key.manager else rows.filter(key_prefix=key.prefix)


def _clean_name(name: str | None) -> str:
    clean = (name or '').strip()
    if not clean or len(clean) > MAX_NAME:
        raise SendRefused(422, f'Give the template a name of 1 to {MAX_NAME} characters.')
    return clean


def create(
    name: str, subject: str, text: str | None, html: str | None, key: TemplateKey
) -> Template:
    _require_enabled()
    clean_name = _clean_name(name)
    clean_subject, clean_text, clean_html = marketing.check_message(subject, text, html)
    if not key.manager and visible(key).count() >= MAX_PER_KEY:
        raise SendRefused(
            422, f'A key may keep {MAX_PER_KEY} templates; delete some you no longer use.'
        )
    return Template.objects.create(
        name=clean_name,
        key_prefix=key.prefix,
        subject=clean_subject,
        text=clean_text,
        html=clean_html,
    )


def update(
    template: Template,
    *,
    name: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    html: str | None = None,
) -> Template:
    """Change what is given; the rest stays. The result must still be a sendable message."""
    _require_enabled()
    if name is not None:
        template.name = _clean_name(name)
    template.subject, template.text, template.html = marketing.check_message(
        subject if subject is not None else template.subject,
        text if text is not None else template.text,
        html if html is not None else template.html,
    )
    template.save()
    return template


def preview(template: Template, merge: Mapping[str, object] | None, email: str = '') -> Preview:
    """The message as one person would get it (without the footer, which is added at sending).

    A tag with no value and no fallback is left as written and listed in ``missing``: in a
    campaign it would skip that person, so a preview shows it rather than failing.
    """
    values = marketing.clean_merge(merge)
    if values is None:
        raise SendRefused(422, 'The merge values are not acceptable (see the documentation).')
    values = {
        **values,
        'email': email or 'person@example.org',
        'unsubscribe_url': '(each person gets their own link)',
    }
    missing: list[str] = []
    one_line = {name: ' '.join(value.split()) for name, value in values.items()}
    shown = Preview(
        subject=' '.join(
            marketing.render(template.subject, one_line, escape=False, missing=missing).split()
        ),
        text=marketing.render(template.text, values, escape=False, missing=missing),
        html=marketing.render(template.html, values, escape=True, missing=missing),
    )
    shown.missing = missing
    return shown


def tags(template: Template) -> list[dict[str, object]]:
    """The merge tags the template uses: ``[{"name", "required"}]``, built-in ones left out.

    ``required`` means some use of the tag has no fallback, so a person without a value is skipped.
    """
    required: dict[str, bool] = {}
    for name, fallback in marketing.tags_in(template.subject, template.text, template.html):
        if name not in marketing.BUILTIN_TAGS:
            required[name] = required.get(name, False) or fallback is None
    return [{'name': name, 'required': required[name]} for name in sorted(required)]


def _require_enabled() -> None:
    if not marketing.settings().enabled:
        raise SendRefused(
            403, 'Marketing is switched off. Install or enable the Marketing plugin to use it.'
        )


__all__ = [
    'MAX_PER_KEY',
    'Preview',
    'TemplateKey',
    'create',
    'preview',
    'tags',
    'update',
    'visible',
]
