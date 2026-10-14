"""Context processor providing safe user display values for templates."""

from django.http import HttpRequest


def _photo_url(user: object) -> str:
    """URL of the signed-in person's small photo, or ``''`` when they have none."""
    from django.urls import reverse

    from backend.apps.accounts.services.photos import PhotoService

    try:
        version = PhotoService.photo_version(user)  # type: ignore[arg-type]
    except Exception:  # a page must still render if the profile table is unavailable
        return ''
    if not version:
        return ''
    return reverse('accounts:photo', args=[user.pk, 'small']) + f'?v={version}'  # type: ignore[attr-defined]


def user_context(request: HttpRequest) -> dict[str, object]:
    """Provide user_initials, user_display_name, and user_role_label."""
    user = request.user
    if user.is_anonymous:
        return {
            'user_initials': '?',
            'user_display_name': 'Guest',
            'user_role_label': 'GUEST',
        }
    email: str = getattr(user, 'email', '') or ''

    # Real values only: the profile name, else the email's local part.
    full_name = getattr(user, 'get_full_name', lambda: '')() or email.split('@')[0] or 'Account'

    # Avatar shows a single first letter when there is no profile image.
    initials = full_name[:1].upper()

    if user.is_superuser:
        role = 'SUPERUSER'
    elif user.is_staff:
        role = 'STAFF'
    else:
        role = 'USER'

    can_use_assistant = assistant_ready = False
    if user.is_staff:
        from backend.apps.accounts.services.roles import RoleService
        from backend.apps.accounts.types.permissions import PermissionCode

        can_use_assistant = RoleService.has_perm(user, PermissionCode.SYSTEM_MANAGE)
    if can_use_assistant:
        from backend.apps.core.assistant.services import config as assistant_config

        assistant_ready = assistant_config.current() is not None
    return {
        'user_photo_url': _photo_url(user),
        'user_initials': initials,
        'user_display_name': full_name,
        'user_role_label': role,
        'can_use_assistant': can_use_assistant,
        'assistant_ready': assistant_ready,  # a model is connected: offer "Ask the assistant"
    }
