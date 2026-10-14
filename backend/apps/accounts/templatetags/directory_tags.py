"""Template helpers for the contact directory panel."""

from __future__ import annotations

from django import template

from backend.apps.accounts.services import directory

register = template.Library()


@register.inclusion_tag('admin/partials/directory_panel.html', takes_context=True)
def directory_panel(context: dict[str, object]) -> dict[str, object]:
    from backend.apps.accounts.models import UserProfile

    on = directory.enabled()
    return {
        'request': context.get('request'),
        'csrf_token': context.get('csrf_token'),
        'directory_enabled': on,
        'directory_people': len(directory.entries()) if on else 0,
        'directory_hidden': UserProfile.objects.filter(directory_hidden=True).count() if on else 0,
    }


@register.inclusion_tag('admin/partials/account_photo.html', takes_context=True)
def account_photo_panel(context: dict[str, object]) -> dict[str, object]:
    """The Profile photo section of the Account page."""
    from django.urls import reverse

    from backend.apps.accounts.models import UserProfile
    from backend.apps.accounts.services.photos import PhotoService

    user = context['user']
    version = PhotoService.photo_version(user)  # type: ignore[arg-type]
    large = ''
    if version:
        large = reverse('accounts:photo', args=[user.pk, 'large']) + f'?v={version}'  # type: ignore[attr-defined]
    hidden = UserProfile.objects.filter(user=user, directory_hidden=True).exists()
    return {
        'csrf_token': context.get('csrf_token'),
        'user': user,
        'photo_large_url': large,
        'user_initials': context.get('user_initials', '?'),
        'directory_hidden': hidden,
        'directory_shared': directory.enabled(),
    }
