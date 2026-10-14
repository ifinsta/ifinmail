from django.apps import AppConfig


class ReleasesConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.core.releases'
    label: str = 'releases'
    verbose_name: str = 'App releases'
