"""devices admin — Device registry."""

from django.contrib import admin

from backend.apps.devices.models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_type', 'is_active', 'last_seen', 'updated_at')
    list_filter = ('is_active', 'device_type')
    search_fields = ('name', 'identifier')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-last_seen', 'name')
