from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.accounts'
    label: str = 'accounts'

    def ready(self) -> None:
        # Tools this app offers to the administrator assistant.
        from backend.apps.accounts.assistant_handlers import register

        register()
