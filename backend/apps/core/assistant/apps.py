from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.core.assistant'
    label: str = 'ifinmail_assistant'
    verbose_name: str = 'Assistant'

    def ready(self) -> None:
        # The capability the Assistant plugin configures, and the core tools.
        from backend.apps.core.assistant.assistant_handlers import register

        register()
