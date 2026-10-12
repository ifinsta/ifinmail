"""``{{ text|markdown }}``: model output as safe HTML (see services/safe_markdown.py)."""

from __future__ import annotations

from django import template
from django.utils.safestring import mark_safe

from backend.apps.core.assistant.services.safe_markdown import render

register = template.Library()


@register.filter(name='markdown')
def markdown_filter(value: object) -> str:
    # Safe by construction: render() escapes all input and writes only whitelisted tags.
    return mark_safe(render('' if value is None else str(value)))  # noqa: S308
