from django.apps import AppConfig


class TelemetryConfig(AppConfig):
    name: str = 'backend.apps.core.telemetry'
    label: str = 'ifinmail_telemetry'
    verbose_name: str = 'ifinmail Telemetry'

    def ready(self) -> None:
        import backend.apps.core.telemetry.signals  # noqa: F401 — register exception/task hooks
