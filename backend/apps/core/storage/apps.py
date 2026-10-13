from django.apps import AppConfig


class StorageConfig(AppConfig):
    name: str = 'backend.apps.core.storage'
    label: str = 'ifinmail_storage'
    verbose_name: str = 'ifinmail Storage'

    def ready(self) -> None:
        import backend.apps.core.storage.signals  # noqa: F401 — register signal handlers (EC-77)
        from backend.apps.core.storage.plugin_contract import register

        register()  # the storage.objects capability plugins configure
