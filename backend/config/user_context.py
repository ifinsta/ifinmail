"""Context processor providing safe user display values for templates."""

from django.http import HttpRequest


def user_context(request: HttpRequest) -> dict[str, str]:
    """Provide user_initials, user_display_name, and user_role_label."""
    user = request.user
    if user.is_anonymous:
        return {
            'user_initials': '?',
            'user_display_name': 'Guest',
            'user_role_label': 'GUEST',
        }
    email: str = getattr(user, 'email', '') or ''
    initials = email[:2].upper() if email else 'AD'

    # Real values only: the profile name, else the email's local part.
    full_name = getattr(user, 'get_full_name', lambda: '')() or email.split('@')[0] or 'Account'

    if user.is_superuser:
        role = 'SUPERUSER'
    elif user.is_staff:
        role = 'STAFF'
    else:
        role = 'USER'

    return {
        'user_initials': initials,
        'user_display_name': full_name,
        'user_role_label': role,
    }
