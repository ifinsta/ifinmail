# HTML Templates

Total: 50 files found via `**/*.html`.

## Redesign

All 50 templates are redesigned in one canvas: https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE (private; ask the owner for access). It borrows the compact ifinsta system (https://claude.ai/artifact/SLYdVZjTPp1W1S69kfsrbf).

- Board for each template: `.agents/skills/ifinmail-design-system/references/template-map.md`
- Short guide: `DESIGN.md`. Rules, tokens and patterns: `.agents/skills/ifinmail-design-system/`
- Phone-width (390 px) boards: `PhoneDashboard`, `PhoneNav`, `PhoneUsers`, `PhoneSpam`, `PhoneDomainConfig`, `PhoneBranding`, `PhoneLogs`, `PhoneLogin`, `PhoneLanding`, `PhoneLegal`, `PhoneAccess`
- Implementation: `frontend/static/css/ifinmail-redesign.css`
- Workflow for building or changing a template: `.agents/skills/ifinmail-template-builder/`
- Checks before you finish: `.agents/skills/ifinmail-design-audit/` (`scripts/audit.sh`)

| Group | Board |
| --- | --- |
| Shell: `base.html`, `includes/header.html`, `includes/sidebar.html` | `ShellParts` |
| Tables: `includes/admin_table.html`, `includes/setup_table.html`, `admin/partials/*` | `TablesRows` |
| Admin: `dashboard`, `user_management`, `spam_filtering`, `dns_config`, `branding_identity`, `logs` | `Dashboard`, `Users`, `Spam`, `DomainConfig`, `Branding`, `Logs` |
| Settings: `settings_base`, `settings_hub`, `settings_config`, `settings_appearance`, `settings_maintenance`, `settings_about`, `includes/settings_nav` | `Settings`, `SettingsAppearance`, `PhoneSettings` |
| Access: `admin/login`, `admin/password_reset_*`, `registration/*`, `setup/*` | `Login`, `PasswordReset`, `Registration`, `Setup`, `Emails` |
| Public: `landing`, `privacy`, `terms` | `Landing`, `Privacy`, `Terms` |
| System: `error_base`, `400`-`504`, `static/error-pages/*`, Android `index.html` | `ErrorPages`, `AndroidShell` |

When you add, remove or rename a template, update the list below and the template map.

## frontend/templates/ (root)

- `frontend/templates/base.html`
- `frontend/templates/error_base.html`
- `frontend/templates/400.html`
- `frontend/templates/403.html`
- `frontend/templates/404.html`
- `frontend/templates/500.html`
- `frontend/templates/502.html`
- `frontend/templates/503.html`
- `frontend/templates/504.html`
- `frontend/templates/landing.html`
- `frontend/templates/privacy.html`
- `frontend/templates/terms.html`

## frontend/templates/includes/

- `frontend/templates/includes/header.html`
- `frontend/templates/includes/settings_nav.html`
- `frontend/templates/includes/sidebar.html`
- `frontend/templates/includes/admin_table.html`
- `frontend/templates/includes/setup_table.html`

## frontend/templates/setup/

- `frontend/templates/setup/base.html`
- `frontend/templates/setup/welcome.html`
- `frontend/templates/setup/create_account.html`
- `frontend/templates/setup/dns_provider.html`
- `frontend/templates/setup/dns_auto.html`
- `frontend/templates/setup/dns_manual.html`
- `frontend/templates/setup/done.html`

## frontend/templates/admin/

- `frontend/templates/admin/dashboard.html`
- `frontend/templates/admin/login.html`
- `frontend/templates/admin/user_management.html`
- `frontend/templates/admin/spam_filtering.html`
- `frontend/templates/admin/dns_config.html`
- `frontend/templates/admin/branding_identity.html`
- `frontend/templates/admin/logs.html`
- `frontend/templates/admin/settings_base.html` (layout shared by every settings page)
- `frontend/templates/admin/settings_hub.html`
- `frontend/templates/admin/settings_config.html` (read-only effective config: mail, deliverability, security, monitoring, storage, language)
- `frontend/templates/admin/settings_appearance.html`
- `frontend/templates/admin/settings_maintenance.html`
- `frontend/templates/admin/settings_about.html`
- `frontend/templates/admin/password_reset_form.html`
- `frontend/templates/admin/password_reset_email.html`
- `frontend/templates/admin/password_reset_done.html`
- `frontend/templates/admin/password_reset_confirm.html`
- `frontend/templates/admin/password_reset_complete.html`

## frontend/templates/admin/partials/

- `frontend/templates/admin/partials/admin_row.html`
- `frontend/templates/admin/partials/dns_row.html`
- `frontend/templates/admin/partials/log_row.html`
- `frontend/templates/admin/partials/provider_row.html`
- `frontend/templates/admin/partials/queue_row.html`

## frontend/templates/registration/

- `frontend/templates/registration/_stepper.html`
- `frontend/templates/registration/step_username.html`
- `frontend/templates/registration/step_password.html`
- `frontend/templates/registration/step_profile.html`
- `frontend/templates/registration/step_verify.html`
- `frontend/templates/registration/step_complete.html`
- `frontend/templates/registration/email_verify.html`

## Other

- `frontend/static/error-pages/40x.html`
- `frontend/static/error-pages/50x.html`
- `clients/android/app/webApp/src/webMain/resources/index.html`
