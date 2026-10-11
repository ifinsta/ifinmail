import logging

from django.apps import AppConfig


class MyDocConfig(AppConfig):
    """Auto-generated API documentation app inspired by Mintlify."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.apps.core.mydoc"
    label = "mydoc"
    verbose_name = "MyDoc API Documentation"

    def ready(self) -> None:
        """Apply MyDoc configuration that requires the app registry."""
        from .config import get_setting

        log_level = get_setting("LOG_LEVEL", "INFO")
        logging.getLogger("backend.apps.core.mydoc").setLevel(getattr(logging, log_level, logging.INFO))
