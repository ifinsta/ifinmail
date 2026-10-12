"""Keys of the persisted system settings (see SystemSettings)."""

from __future__ import annotations

from enum import StrEnum


class SettingKey(StrEnum):
    SETUP_COMPLETED = 'setup.completed'
    REGISTRATION_OPEN = 'registration.open'
    SMART_HOST_ENABLED = 'mail.smart_host_enabled'
    SMTP_PROXY_ENABLED = 'mail.smtp_proxy_enabled'
    MAX_HOPS = 'mail.max_hops'
    MTA_STS_MODE = 'mail.mta_sts_mode'
    LAST_BACKUP_AT = 'ops.last_backup_at'
    LAST_VERIFY_AT = 'ops.last_verify_at'
    UPDATE_LATEST = 'updates.latest'
    UPDATE_CHECK_ENABLED = 'updates.check_enabled'
    DNS_SECONDARIES = 'dns.secondaries'
    DNS_CAA_ENABLED = 'dns.caa_enabled'
    ENTRYPOINTS = 'network.entrypoints'
    NETWORK_BLOCKLIST = 'network.blocklist'
    NETWORK_RATE_LIMITS = 'network.rate_limits'
    # Bundled plugins with install_by_default already offered once (installed, or later removed).
    PLUGIN_DEFAULTS_OFFERED = 'plugins.defaults_offered'
