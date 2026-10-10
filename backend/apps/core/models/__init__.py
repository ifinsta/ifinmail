"""Core models."""

from django.db import models

from backend.apps.core.base.models.base import CoreModel


class SystemSetting(CoreModel):
    """Key/value store for settings an administrator changes at runtime.

    Environment variables remain the deployment-time defaults; a row here
    overrides them. Values are JSON so booleans and numbers keep their type.
    """

    key = models.CharField(max_length=128, unique=True)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['key']

    def __str__(self) -> str:
        return self.key


__all__ = ['CoreModel', 'SystemSetting']
