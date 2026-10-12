from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.core.plugins'
    label: str = 'ifinmail_plugins'
    verbose_name: str = 'Plugins'
