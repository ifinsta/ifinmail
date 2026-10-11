from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.core.platform'
    label: str = 'ifinmail_services'
