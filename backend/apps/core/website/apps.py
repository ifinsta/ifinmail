from django.apps import AppConfig


class WebsiteConfig(AppConfig):
    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'backend.apps.core.website'
    label: str = 'ifinmail_website'
    verbose_name: str = 'Website'

    def ready(self) -> None:
        # The capability the "Website pages" plugin configures and its in-console target.
        from backend.apps.core.website.website_handlers import register

        register()
