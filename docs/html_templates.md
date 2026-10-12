# HTML template registry

Single source: `frontend/templates/`. No app-embedded templates.
Canonical board map: `.agents/skills/ifinmail-design-system/references/template-map.md`
(50 boards). This file is the runtime registry CI and `test_frontend_contract.py`
verify — every row must exist on disk.

## Shell / chrome

| Template | Board | Rendered by |
|---|---|---|
| `base.html` | ShellParts | `backend/config/urls.py` base for all console pages |
| `includes/header.html` | ShellParts | `base.html` include |
| `includes/sidebar.html` | ShellParts | `base.html` include |
| `includes/admin_table.html` | TablesRows | admin list pages |
| `includes/setup_table.html` | TablesRows | setup wizard tables |
| `includes/settings_nav.html` | Settings | `admin/settings_base.html` (`SettingsCatalogue`) |
| `includes/brand_mark.html` | ShellParts, Landing | nav/footer mark on `landing.html`, `terms.html`, `privacy.html` (uploaded logo only; without one the brand name text carries identity) |
| `includes/card_brand.html` | Login, Registration, Setup, ErrorPages | auth/registration/setup/error cards — uploaded logo, else the system name |
| `error_base.html` | ErrorPages | `400/403/404/500/502/503/504.html` |

## Console

| Template | Board | Rendered by |
|---|---|---|
| `admin/dashboard.html` | Dashboard | `accounts/views/dashboard.py` |
| `admin/user_management.html` | Users | `accounts/views/users.py` |
| `admin/spam_filtering.html` | Spam | rspamd settings view |
| `admin/dns_config.html` | DomainConfig | `dns/views/web.py` |
| `admin/branding_identity.html` | Branding | branding view |
| `admin/logs.html` | Logs | telemetry/audit view |
| `admin/login.html` | Login | `accounts/views/` login |
| `admin/mfa_setup.html`, `admin/mfa_verify.html` | (MFA extension) | `accounts/views/mfa.py` |
| `admin/mailbox_setup.html`, `admin/mailbox_profile.html` | (Mailbox extension) | `accounts/views/mailboxes.py` |
| `admin/partials/admin_row.html` | TablesRows | user rows |
| `admin/partials/dns_row.html` | TablesRows | DNS rows |
| `admin/partials/log_row.html` | TablesRows | log rows |
| `admin/partials/provider_row.html` | TablesRows | provider rows |
| `admin/partials/queue_row.html` | TablesRows | queue rows |
| `admin/partials/mailbox_row.html` | (Mailbox extension) | mailbox rows |
| `includes/flash_messages.html` | ShellParts | flash messages on admin pages outside the Settings layout |
| `admin/marketplace.html` | (Marketplace extension) | `accounts/views/marketplace.py` — Discover / Installed / Submissions tabs |
| `admin/marketplace_plugin.html` | (Marketplace extension) | one plugin: about, what it changes, settings, update, manage |
| `admin/marketplace_submit.html` | (Marketplace extension) | submit a `plugin.toml` for review |
| `admin/marketplace_submission.html` | (Marketplace extension) | review a submission (approve, reject, withdraw, retire) |
| `admin/partials/plugin_fields.html` | (Marketplace extension) | setting fields rendered from a plugin manifest |

## Settings hub (`SettingsCatalogue` in `accounts/services/settings_catalogue.py`)

| Template | Board |
|---|---|
| `admin/settings_hub.html` | Settings |
| `admin/settings_base.html` | Settings |
| `admin/settings_config.html`, `settings_about.html`, `settings_maintenance.html` | SettingsMail |
| `admin/settings_appearance.html` | SettingsAppearance (+Dark/+Contrast) |
| `admin/settings_certificates.html` | (TLS extension) |
| `admin/settings_network.html` | (Network extension) |
| `admin/settings_account.html` | (Account extension) |
| `admin/settings_dns_server.html`, `settings_dns_zone.html` | (DNS extension) |
| `admin/settings_mailboxes.html`, `settings_aliases.html` | (Mailbox extension) |

## Auth / registration / setup

| Template | Board |
|---|---|
| `admin/password_reset_form.html`, `_done.html`, `_confirm.html`, `_complete.html` | PasswordReset |
| `admin/password_reset_email.html`, `registration/email_verify.html` | Emails |
| `admin/password_reset_email.txt` | Emails (plain-text body) |
| `admin/password_reset_subject.txt` | Emails (subject) |
| `registration/_stepper.html`, `step_profile.html`, `step_username.html`, `step_password.html`, `step_verify.html`, `step_complete.html` | Registration |
| `setup/base.html`, `welcome.html`, `dns_provider.html`, `dns_auto.html`, `dns_manual.html`, `dns_server.html`, `create_account.html`, `done.html` | Setup |

## Public / errors

| Template | Board |
|---|---|
| `landing.html` | Landing |
| `privacy.html`, `terms.html` | Privacy, Terms |
| `400.html`, `403.html`, `404.html`, `500.html`, `502.html`, `503.html`, `504.html` | ErrorPages |
| `static/error-pages/40x.html`, `50x.html` | ErrorPages (nginx fallback, self-contained) |

## Clients

| Template | Board |
|---|---|
| `clients/android/app/webApp/src/webMain/resources/index.html` | AndroidShell |

## Inventory (69 html on disk, 2026-10-11)

Root (8): `base.html`, `error_base.html`, `landing.html`, `privacy.html`,
`terms.html`, `400/403/404/500/502/503/504.html` (7). `admin/` (22 + 6 partials),
`includes/` (7), `registration/` (7), `setup/` (8). Extras beyond the original
50-board map are intentional extensions tagged above; do not delete without
updating `SettingsCatalogue` and `test_frontend_contract.py`.
