from django.apps import AppConfig


class MailConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.mail'
    label: str = 'mail'

    def ready(self) -> None:
        # Extension points and setting types this app offers to plugins.
        from backend.apps.mail.assistant_handlers import register as register_tools
        from backend.apps.mail.services.plugin_points import register

        register()
        register_tools()
