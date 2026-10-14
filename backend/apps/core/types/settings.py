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
    NETWORK_AUTOBLOCK = 'network.autoblock'  # opt-in automatic blocking: enabled, hours, allow-list
    PROVISION_SIGNATURES = 'domains.provision_signatures'  # last outcome per domain (audit noise)
    EXPOSURE_LAST = 'security.exposure_last'  # the last exposure self-check (accounts.exposure)
    NETWORK_FLOOD = 'network.flood'  # flood mode while it lasts: {'until': iso, 'reason': text}
    # Bundled plugins with install_by_default already offered once (installed, or later removed).
    PLUGIN_DEFAULTS_OFFERED = 'plugins.defaults_offered'
    # Publish every mailbox (name, address, photo) as a read-only CardDAV address book that each
    # mailbox's contacts app picks up (accounts.services.directory).
    DIRECTORY_ENABLED = 'contacts.directory_enabled'
    # Mailboxes whose sending containment paused: {address: {reason, at, usage}}.
    SENDING_PAUSED = 'mail.sending_paused'
    # When each mailbox was last reported to administrators (alerts are rate-limited).
    SENDING_ALERTED = 'mail.sending_alerted'
    # Spam filtering (mail.services.spam_policy): how strict, from 1 to 10, and the extra DNS
    # lists as [{host, type, enabled, tested: {state, ms, at}}].
    SPAM_SENSITIVITY = 'spam.sensitivity'
    SPAM_PROVIDERS = 'spam.providers'
    # Text an administrator wrote for public pages (core.website): {page: {title, body, ...}}.
    WEBSITE_CONTENT = 'website.content'
    # The look people get until they choose one in Settings > Appearance (smooth by default).
    DEFAULT_THEME = 'appearance.default_theme'
