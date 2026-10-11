"""Telemetry admin — read-only (errors are immutable evidence)."""

from django.contrib import admin

from backend.apps.core.telemetry.models import ErrorEvent, ErrorFingerprint


@admin.register(ErrorFingerprint)
class ErrorFingerprintAdmin(admin.ModelAdmin):
    list_display = ('hash', 'exc_type', 'view_name', 'count', 'status', 'severity_max', 'last_seen')
    list_filter = ('status', 'severity_max')
    search_fields = ('hash', 'exc_type', 'view_name')
    readonly_fields = ('hash', 'exc_type', 'view_name', 'count', 'first_seen', 'last_seen')


@admin.register(ErrorEvent)
class ErrorEventAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'severity',
        'source',
        'exc_type',
        'view_name',
        'correlation_id',
        'resolved',
    )
    list_filter = ('severity', 'source', 'resolved')
    search_fields = ('message', 'exc_type', 'request_path', 'correlation_id')
    readonly_fields = tuple(f.name for f in ErrorEvent._meta.fields if f.name not in ('resolved',))

    def has_add_permission(self, request) -> bool:  # type: ignore[override]
        return False
