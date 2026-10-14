# Template -> redesign board

Canvas: https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE (board = artboard file in the canvas). All 50 entries of `docs/html_templates.md` are covered.

| Template(s) | Board | What it shows |
| --- | --- | --- |
| `base.html`, `includes/header.html`, `includes/sidebar.html` | `ShellParts` | Expanded and rail sidebar, header with open profile menu, system information dialog, shell anatomy |
| `includes/admin_table.html`, `includes/setup_table.html`, `admin/partials/admin_row.html`, `dns_row.html`, `log_row.html`, `provider_row.html`, `queue_row.html` | `TablesRows` | Every row partial in the new table style, empty state, table rules |
| `admin/dashboard.html` | `Dashboard` | Status banner, stat strip, domain health table, quick actions, activity, disk and TLS |
| `admin/user_management.html` | `Users` | Stat cards, admin directory, RBAC, live sessions, governance |
| `admin/spam_filtering.html` | `Spam` | Stats, sensitivity slider, engines, DNSBL table, add-provider dialog |
| `admin/dns_config.html` | `DomainConfig` | Zone health strip, registry, empty cluster, toolbox, routing toggles, register-domain dialog |
| `admin/branding_identity.html` | `Branding` | Logo upload, typography, palette with live preview, brand application toggles |
| `admin/settings_hub.html`, `includes/settings_nav.html` | `Settings` | Grouped category list (Workspace, Access, Personalization, System) plus overview; the nav is generated from `SettingsCatalogue` |
| `admin/settings_config.html`, `settings_about.html`, `settings_maintenance.html` | `SettingsMail` | Read-only effective config rows with the env variable beside each value; secrets show only "Configured" |
| `admin/settings_appearance.html` | `SettingsAppearance`, `SettingsAppearanceDark`, `SettingsAppearanceContrast` | Theme picker cards and the Current panel, shown in each theme |
| `admin/logs.html` | `Logs` | Level filter chips, live log table, empty audit trail |
| `admin/login.html` | `Login` | Auth card with `state` tweak: default, error, inactive |
| `admin/password_reset_form.html`, `_done.html`, `_confirm.html` (valid and invalid), `_complete.html` | `PasswordReset` | Five reset states |
| `admin/password_reset_email.html`, `registration/email_verify.html` | `Emails` | System email layout |
| `registration/_stepper.html`, `step_profile.html`, `step_username.html`, `step_password.html`, `step_verify.html`, `step_complete.html` | `Registration` | Five steps plus the verify-send-failed variant |
| `setup/base.html`, `welcome.html`, `dns_provider.html`, `dns_auto.html`, `dns_manual.html`, `create_account.html`, `done.html` | `Setup` | Six wizard screens with the stepper |
| `site/landing.html` (+ `site/features.html`, `pricing.html`, `security.html`, `docs.html`, `changelog.html`, `download.html`, `about.html`, `contact.html`, shell `site/base.html`, `_nav.html`, `_footer.html`) | `Landing` | Nav, hero with product window, capabilities, steps, security and cost, CTA, footer; inner pages use the page head, split sections and prose pattern |
| `site/privacy.html`, `site/terms.html` | `Privacy`, `Terms` | Reading column with section rules |
| `error_base.html`, `400.html`, `403.html`, `404.html`, `500.html`, `502.html`, `503.html`, `504.html`, `static/error-pages/40x.html`, `50x.html` | `ErrorPages` | Eight error cards and the static fallback note |
| `clients/android/.../webMain/resources/index.html` | `AndroidShell` | Loading splash |

Phone-width boards (390 px, "Phone widths" row): `PhoneDashboard`, `PhoneNav` (drawer open), `PhoneUsers`, `PhoneSpam`, `PhoneDomainConfig`, `PhoneBranding`, `PhoneLogs`, `PhoneSettings` (hub, category page, dark appearance), `PhoneLogin`, `PhoneLanding`, `PhoneLegal`, and `PhoneAccess` (registration, setup, error, email). They render the same boards with the `phone` prop, so a change to a desktop board shows up there too.

Shared components in the canvas (components row): `Icon`, `Pill`, `Btn`, `Field`, `Stepper`, `TopBar`, `PageHead`, `Sidebar`. Foundations sheet: `Main`.

## Mapping notes

- Board filenames are not template names. Use this table to find the board, and the board's title strip shows the template path.
- Boards use example data (example.com, 192.0.2.x, `[Admin name]`). Real templates keep their Django variables and `{% trans %}` tags.
- Where a template has several states (login error, reset invalid link, verify failed) the board shows each; implement all of them.
