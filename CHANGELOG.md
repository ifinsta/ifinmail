# Changelog

## v0.0.7
- New built-in plugin **Mail policy essentials**, one plugin for the controls administrators need
  first, with defaults taken from Google Workspace and Microsoft 365 so it is safe to install
  unchanged:
  - blocked senders (address or domain, envelope or From header) are refused;
  - allowed senders are never treated as spam, but only when SPF or DKIM proves them, and
    attachment and malware rules still apply (Microsoft's guidance on allow entries);
  - sending limits per login: 30 a minute and 2,000 a day, in separate counters;
  - largest message 50 MB (this server's existing limit; 50 MB is also the most Rspamd scans and
    signs, so the setting cannot go higher);
  - internal-only mailboxes may send only to domains hosted here (clear 554 message otherwise);
  - greylisting on or off;
  - a notice in the Inbox at 80% and 95% of the quota, delivered even when the mailbox is full.
- New extension point `postfix.sender_policy`; new keys on `rspamd.policy`, `postfix.main` and
  `dovecot.policy`. Both submission ports now read their recipient restrictions from one parameter
  (`ifinmail_submission_restrictions`), unchanged by default.
- A plugin value that is removed from `postfix.main` restores this server's value from
  `main.cf.template`, not Postfix's built-in default.
- Fix: Rspamd counted but did not enforce sending limits (including the built-in 100 an hour) if
  Redis was not reachable when Rspamd started, for example after a reboot. The Rspamd watcher now
  reloads it once it is serving and again whenever Redis restarts.
- The Rspamd configuration test runs as `_rspamd`, so it leaves no root-owned cache files.

## v0.0.6
- New built-in plugin **ARC trusted forwarding**: seals mail this server passes on (aliases that
  forward outside) with the domain's DKIM key, and lets a valid ARC chain from a forwarder you
  trust lift a DMARC rejection, so DMARC enforcement does not bounce genuine forwarded or list
  mail. Seals verified with an independent implementation; tampering is detected.
- Plugin settings: a default now applies only when a value is not supplied, so a field cleared on
  purpose stays empty and a boolean `default = true` is honoured (it was ignored when absent).
  `configure` with some keys keeps the current values of the others.

## v0.0.5
- Five new built-in plugins: **Attachment guard**, **DMARC enforcement**, **Forwarding control**,
  **Mailbox cleanup** and **Partner TLS**.
- Three new extension points: `rspamd.policy`, `dovecot.policy` and `postfix.tls_policy`. The Rspamd
  and Dovecot containers each run a small watcher that re-validates plugin values, checks the
  configuration (`rspamadm configtest`, `doveconf -n`) before reloading, rolls back a failing one
  and acknowledges only what took effect. Partner TLS uses a `texthash:` map, so no `postmap` step.
- Extension-point values can be normalised (e.g. `EXE, .js` becomes `exe,js`).
- The Rspamd and Dovecot containers mount the runtime volume (read-only) and the status volume.
- 240 handled edge cases documented in `.agents/skills/ifinmail-plugins/`.

## v0.0.4
- **Marketplace** (sidebar, after Settings): browse, install, configure, enable, disable, update and
  uninstall plugins; submit new ones for review. Approval is always a person (`system.manage`);
  sources are internal only (built-in plugins and approved submissions).
- **Plugin layer** (`backend/apps/core/plugins`): declarative `plugin.toml` manifests, strict
  validation that reports every problem at once, extension points and setting types registered by
  the apps that own them, an installation state machine with crash recovery and reconciliation,
  and an acknowledgement so the console shows whether Postfix has applied a change. No new
  packages or services.
- **Compliance journal**, the first built-in plugin: a copy of every message to an archive mailbox.
- The postfix watcher applies a second file (`postfix-plugins.conf`) with its own allow-list.
- System health reports failed or unapplied plugins. A `plugins.reconcile` job runs every 10 minutes
  and writes only when something drifted.
- Guide, state machines and 215 handled edge cases: `.agents/skills/ifinmail-plugins/`.

## v0.0.3
- `make audit-verify` and `make reset-mfa EMAIL=...` replace the `docker compose exec` commands
  documented in v0.0.2, which failed without the environment file.

## v0.0.2
Enterprise hardening. Existing installs keep their current policy until switched on in
`provisioning/.env` (see `docs/enterprise-next-steps.md`).

- **Audit trail:** hash-chained, kept 365 days (`AUDIT_RETENTION_DAYS`, minimum 30) instead of a
  10,000-row cap; the dashboard log purge can only remove expired entries; export reads the whole
  trail from the database (`?format=jsonl` adds hashes); `manage.py verify_audit_chain`.
- **Two-factor:** `MFA_ENFORCEMENT=required` removes postponing and switching off (new installs
  default to it); `manage.py reset_mfa <email>` for a lost authenticator.
- **Backups:** verified off-site copy over SSH (`BACKUP_OFFSITE_TARGET`, `make offsite-check`) and
  `make backup-key` to export the key and prove it opens the newest backup. System health reports both.
- **Sensitive actions** (admin rights, roles, API tokens, mailbox deletion) ask for the password again.
- **API tokens** last at most 90 days.
- **CSP is enforced**; `CSP_REPORT_ONLY=true` is the emergency switch.
- **Dependencies** are hash-pinned and verified at image build; audited weekly.
- **Outbound limits:** per-login send limits through Rspamd (100/hour per login, 40/hour per
  recipient domain).
- `GET /api/metrics` (Prometheus text, token scope `audit.view`).
- `SECURITY.md`, `docs/dr-runbook.md`, `docs/risk-register.md`, `docs/secrets-map.md`.
- Fixed: mailbox profile showed the "Admin rights" row twice.

## v0.0.1
First working release.

- One-command install verified end to end; mail delivery fixes (Postfix chroot, Dovecot volume
  ownership); setup wizard required until finished; forced first password; optional two-factor;
  System health page; one brand name default.
- `make update [TO=vX.Y.Z]` with a database and configuration snapshot, automatic rollback if the
  new version is not healthy, and `make rollback` (code and database) / `make version`.
- The console shows the installed version and announces new releases (six-hourly GitHub check,
  can be switched off).
- `make uninstall` undoes the installation (including anonymous volumes of the stack's
  containers); `--check` lists anything left.
- New mailboxes: the setup link and getting-started instructions (mail app settings) can be
  emailed to an address the owner already reads, when the mailbox is created or later from the
  mailbox list or profile.
- System email (setup links, registration verification) is delivered through an internal-only
  Postfix port (10025, never published) instead of failing on a missing local mail server.
