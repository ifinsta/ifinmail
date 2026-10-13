# Changelog

## v0.0.22
- **Every API is versioned.** The health reports and the error log that lived outside `/api/` are
  now `/api/v1` operations (`GET /health`, `/health/full`, `/health/dns`, `/health/deliverability`,
  `/telemetry/errors`, `/telemetry/stats`, `/telemetry/fingerprints`, and acknowledging a
  fingerprint), plus `GET /dns/status`. The old `/health/full/`, `/health/dns/`,
  `/health/deliverability/` and `/telemetry/*` paths answer `308` to the versioned ones. `/health/`
  stays as the infrastructure probe (Docker, nginx and the updater use it).
- **Security fix on the way:** the detailed health reports were open to anyone who could reach the
  server. They ran live DNS, blocklist and port checks on every call and returned internal error
  text and your domain names. They now need a key with `audit.view`; only liveness is anonymous.
- **A rule that cannot rot.** Every JSON endpoint is a v1 operation or is listed in
  `backend/config/api_versions.py` with the reason it is not (browser or mail-client formats, probes,
  and the console's own page calls). A test scans the URL configuration and fails on a new one.
- **Type safe.** Every request and response of the API is a typed schema (the contract has no
  untyped field), every handler and the authentication layer are annotated, all errors are one
  documented `{"detail"}` shape, each operation states `x-required-scope` in the OpenAPI document
  (read from the code that enforces it), and strict **mypy** covers the API layer (`make
  typecheck`, and a CI step). It found and fixed three real problems while being introduced.
- **The assistant knows your API integrations.** Two new read tools: *API overview* (versions,
  authentication, every operation with its scope, rules; read from the live contract so it cannot
  describe an endpoint that does not exist) and *API keys* (which keys exist, owner, scopes, expiry,
  last use, and what looks wrong: expired, unused, too broad, owner no longer holds a scope; plus
  failed authentications and changes made with keys). Secrets never reach it, and `ifs_` / `ifm.`
  values are masked if they appear anywhere. Two suggestions on the start page: *How can a program
  manage mailboxes through the API?* and *Are my API keys set up safely?*
- Found while moving them: the old error-log endpoint returned blank fields for every event (it
  serialised dictionaries with `getattr`). The v1 version is typed and tested.

## v0.0.21
- **The Assistant is now a chat workspace.** Conversations are listed on the left, grouped
  (Today, Yesterday, Previous 7 days, Older), each with its own delete; **New chat** is one
  click. The reading column is centred: your question as a quiet bubble on the right, the answer
  as plain text (full Markdown, tables, code with Copy), and a single "Checked N things · sent to
  host" line that opens to show exactly what was checked and sent. A drafted change is a card with
  the Apply button. The composer is pinned at the bottom (Enter sends, Shift+Enter adds a line,
  an arrow button sends), and a new chat starts with a greeting, the composer and suggested
  questions together in the middle.
- **No page reloads.** A question appears the moment you send it, progress and the answer replace
  the thread in place, the address updates, and the thread stays scrolled to the newest message.
  Without JavaScript every form still works as a normal post.
- Below 1024 px the conversation list is a drawer (scrim, Escape closes); touch targets are 44 px
  on phones and the composer sits edge to edge.
- Connection settings and Test connection moved into the list's footer; the page title area that
  repeated the introduction is gone.

## v0.0.20
- Fixed: the **Changelog page showed "No changelog on this server"** on installed servers. The
  image build ignores `*.md`, so `CHANGELOG.md` was never in the image (the tests read the source
  tree and could not see it). The build now keeps that one file, and a test checks the ignore
  rules.

## v0.0.19
- **An API for integrations, versioned.** `/api/v1/` now lets a program manage **mailboxes**
  (list, create, read, change quota / disable / set password, delete), **aliases** and **domains**
  (list, read, add, verify), next to the existing `status` and `metrics`. The contract is
  `/api/v1/openapi.json`; `/api/` lists the versions the server speaks. Within `v1` only additions
  are made; a breaking change will be `/api/v2/` beside it. The old unversioned `/api/<path>`
  answers `308` to the same path under `/api/v1/` (with `Deprecation` and `Link` headers), so
  existing scrapers and scripts keep working.
- **API keys: a key and a secret.** Settings → **API keys** creates a key (`ifm_…`, public) and a
  secret (`ifs_…`, shown once, stored only as a hash and compared in constant time). Present them
  as HTTP Basic (`curl -u key:secret`) or as one Bearer value. A key has scopes that can never
  exceed its creator's permissions, an expiry (at most 90 days), an optional network allow-list and
  a calls-per-minute limit (default 120; `429` with `Retry-After`, `X-RateLimit-*` on every reply).
  **Rotation can overlap**: keep the old secret working for up to 7 days while the integration
  switches. The key list shows owner, last use and address.
- **Hard to turn into a takeover.** The API cannot create a login with console access and cannot
  change or delete one (a leaked key must not be able to reset an administrator's password), and
  it does not offer domain removal. Every call that changes something is audited under the key and
  its owner; failed attempts are audited once per address and reason; all failures answer the same
  401.
- **Network allow-lists use the address nginx saw** (the last `X-Forwarded-For` entry), not the
  first, which a caller can forge.
- Fixed: on a 360 px screen the Settings pages' header was 32 px wider than the screen; the
  settings icon is now only in the account menu there.
- Tests: 41 for the API (credential format, rotation overlap, networks incl. a forged forwarding
  header, rate limit, versioning and the legacy redirect, scopes, mailboxes, aliases, domains, the
  console page, and "no operation is reachable anonymously" over the whole contract).

## v0.0.18
- **A real public site.** The landing page, Terms and Privacy are rebuilt, and seven pages that
  were only links are added: **Features**, **Pricing**, **Security**, **Docs**, **Changelog**,
  **About** and **Contact**. Compact, flat (no gradients, no shadows), responsive from 360 px, in
  the light, dark and high-contrast themes, with one heading level one and a skip link on every
  page. The phone menu needs no script.
- **Honest copy.** The old pages claimed things the project cannot back: a SOC 2 and GDPR badge,
  paid tiers ($29, "Enterprise"), a 99.9% figure, PGP, a service level. All removed. Pricing now
  says what is true (free to run, you pay for the server and domain; community support), and
  Security lists specific, checkable protections next to a plain "what we do not claim". The
  product preview is labelled "Example data". Terms and Privacy are rewritten for a self-hosted
  server (the operator is the service provider; what is stored, kept and sent where).
- **Nothing is fetched from a third party** on these pages: Inter and JetBrains Mono are served
  from this server. (Console pages still use Google Fonts unless `USE_GOOGLE_FONTS=0`.)
- **The Changelog page is this file**, rendered by the existing Markdown renderer: the newest
  eight releases, with a link to the rest.
- 800 lines of landing-page and legal CSS that nothing uses any more were deleted.
- Tests: every page renders without signing in, has one `h1` and a `main`, loads nothing
  external; the stylesheet has no gradients or literal colours; a list of claims the project
  cannot make is checked against every page.

## v0.0.17
- **Containment of a suspected stolen password.** Sending limits only slow a flood down; now the
  server notices it. Rspamd counts, per logged-in mailbox, the messages, the different recipients
  and the different recipient domains of the last hour (recipients are kept only as short hashes).
  Every minute the worker compares them with thresholds (defaults 300 messages, 500 recipients,
  100 domains, in line with Microsoft 365's outbound spam policy). A mailbox over one is **paused**
  (Postfix refuses its sending with a clear message; it can still receive and be read), the
  administrators are emailed, and **Paused senders** (linked from System health) has a Resume
  button. Choose `notify` to be told without pausing, or `off`. A pause survives uninstalling the
  plugin until someone resumes it.
- **Recipients per message** (default 100, submission ports only) and **blocked destinations**
  (addresses or domains, subdomains included, refused with a clear message).
- The plugin **Sending and delivery policy** is now **Outbound policy**, the counterpart of
  Inbound protection (its id is `outbound-policy`; no server had it installed).
- Plugin layer: *dynamic sources* let live system state (the paused mailboxes) reach an adapter
  target without being a plugin setting.
- Found while testing against real Rspamd and Redis: separate `INCR` and `EXPIRE` commands raced and
  could leave a counter that never expired; the counters are now written by one atomic script.
- Limits you should know: containment reacts within about a minute, so what a mailbox can send in
  that minute is bounded by the per-minute limit times the recipients-per-message limit; bounce
  rate is not a signal yet (that needs the delivery log). 331 handled edge cases are documented.

## v0.0.16
- **PostgreSQL now uses its tuning file.** Since the first release the database ran on the image's
  defaults: `postgres/custom.conf` was mounted but never read (an include was appended to a file
  PostgreSQL does not load). It is now the server's main configuration (`postgres -c
  config_file=...`), verified on a fresh initialisation and on a restart over existing data.
  Effects: shared buffers 64 MB instead of 128 MB (less memory), at most 50 connections (the
  console, worker and mail services use about a dozen), and quieter logs: no line for every
  connection, warnings and above only, autovacuum only when slower than a second.
- A contract test keeps the file in use and keeps what the image's own configuration provided
  (`listen_addresses`) in it.
- Updating restarts the database container once; the console and worker reconnect by themselves.

## v0.0.15
- **System logs** reworked. Activity (the audit trail) and Application errors are tabs with a
  summary (events, errors, warnings, and whether the tamper-evident chain is intact), a search box
  over event, person and details, level and period filters that apply immediately, real
  pagination (25 per page, filters kept in links) and an export that follows the filters. **Live
  view now works**: it adds new events at the top every five seconds and pauses when the tab is
  hidden (before, it only wrote to the browser console). The search box in the header works
  too, and the duplicate "audit trail" side panel is gone.
- **System health** reworked: a one-sentence verdict with the first thing to fix and a link to it;
  checks grouped by area (Mail delivery, Server identity, each domain, Server, Security) with a
  count of what needs attention per group; cards with a "How to fix" block, values you can copy,
  the console page that fixes it and "Ask the assistant"; passing checks are compact. The legacy
  left-border card styles were removed.
- **Assistant** reworked and **full Markdown** for answers: CommonMark plus tables, task lists,
  strikethrough and bare-URL links, rendered by a small renderer in this repository (no new
  package). Raw HTML is shown as text and images as plain links (an image URL could send data
  out); links are limited to http, https, mailto and same-site paths. Conversation list beside the
  thread, suggested questions, "working on it" progress that shows which check ran, Copy on
  answers and code blocks, Enter to send, a token meter, and **Delete conversation**.
- A property test parses every rendering of adversarial and random input and fails if anything
  outside the whitelisted tags, attributes and link targets appears.
- Fixed while checking in a real browser: the Copy buttons raised an unhandled error when the
  browser refused clipboard access; they now fall back to the older route.
- The documented plugin and assistant edge cases are now 318.

## v0.0.14
- Fix: an assistant draft that **cleared** a setting with a default (for example "keep Trash
  forever" on Mailbox care) was applied with the default instead (30 days), so Apply could do
  something other than what the draft table showed. Drafts now clear explicitly, and Apply
  re-validates and refuses unless the result is exactly what was shown. Found during the live
  end-to-end check of the assistant on 2026-10-12: the 30-day Trash/Junk expiry was active on that
  server for about 90 seconds and was removed at once; nobody accessed a mailbox in that window
  and no message was old enough to be removed.
- The draft table says "Default" instead of "Now" for a plugin that is not installed yet.

## v0.0.13
- Fix: the assistant runs its checks in the `worker`, which could not see the mail queue report or
  the plugin acknowledgements, so it told administrators the queue was "not reported" and plugin
  status "unknown" while System health showed them correctly. The worker now mounts the status
  folder (read-only) and has the install directory used in System health hints. Found while
  verifying v0.0.12 end to end against a real model; a contract test keeps the two in step.

## v0.0.12
- **Assistant**: ask the server why something is wrong and get a plain answer, or have it draft
  plugin settings for you to apply. Header button and "Ask the assistant" on failing System
  health checks. Works with any OpenAI-compatible API (chat completions with tool calling);
  other API styles can be added behind the same provider interface later.
  - Built-in plugin, installed by default and inert until a model URL is set; Test connection
    checks that the model can call tools. Uninstalling it is respected by later updates.
  - Tools: System health, mailboxes and aliases, plugins and their settings, recent audit
    events (read), and drafting plugin settings (validated, applied only by your click).
  - Safety: message contents are never available to it; tool results are redacted (keys,
    tokens, passwords, private keys) and shown under each answer with the host they went to;
    the key is encrypted at rest and sent only to the API host; redirects and cloud metadata
    addresses are refused; daily token budget, 8 steps per question, one question at a time;
    30-day retention; `system.manage` only; everything recorded in the audit trail.
- Plugin layer: a `secret` setting type (encrypted, never shown again, only usable by fields
  that stay inside the console), `install_by_default` for bundled plugins, and in-console adapter
  targets. 310 handled edge cases are documented.

## v0.0.11
- **Eight built-in plugins become four**, grouped by what an administrator decides together. One
  plugin can now write several capabilities:
  - **Inbound protection**: dangerous attachments, DMARC, ARC trusted forwarding, blocked and
    allowed senders, greylisting (was Attachment guard, DMARC enforcement, ARC trusted forwarding
    and half of Mail policy essentials).
  - **Sending and delivery policy**: sending limits, largest message, internal-only mailboxes,
    encrypted delivery to partner domains, forwarding-rule cap (was Partner TLS, Forwarding control
    and the rest of Mail policy essentials).
  - **Mailbox care**: Trash/Junk/Sent expiry and quota warnings (was Mailbox cleanup plus quota
    warnings).
  - **Compliance journal**: unchanged, kept on its own because it exposes all mail and needs a
    dedicated mailbox.
- Each part of a plugin can be switched off on its own (empty list, unticked box). DMARC gains an
  `off` value in the capability contract for this. Partner domains are optional (empty = none).
- Together the four plugins offer every capability field exactly once, so they never conflict;
  a test fails if one is left out or offered twice. No server had the old plugins installed, so
  nothing is migrated. 295 handled edge cases are documented.

## v0.0.10
- **Plugins no longer know which mail software runs underneath.** Manifests (now
  `manifest_version = 2`) name engine-neutral **capabilities** such as `mail.journal`,
  `sending.rate_limit`, `inbound.senders` or `mailbox.retention`, with plain values (MB, days,
  yes/no, address lists). An adapter in the mail app is the only code that knows Postfix, Dovecot
  and Rspamd: it binds each capability field to an engine setting and translates the value
  (`inbound.greylisting.enabled = yes` becomes Rspamd's `greylisting = on`). Replacing an engine
  now means re-binding the adapter; plugins, installations and their settings stay as they are.
- 13 capabilities cover everything the 8 built-in plugins do; all 8 are rewritten as version 2.0.0
  (no installed plugins existed on any server, so nothing is migrated). Version 1 manifests are
  refused with a hint. Partner TLS asks "Also require a valid certificate" (yes/no) instead of
  "encrypt / secure"; Mail policy's greylisting is a checkbox.
- The Marketplace shows each plugin's effect as capability and field ("Sending limits ·
  per_day"), never engine settings. When changes wait to be applied, the plugin page and System
  health name the containers they wait for.
- Guard rails: a test fails if a bundled manifest or a capability mentions the mail software or an
  engine setting; registration refuses a capability field bound to an unknown or already bound
  engine setting. 289 handled edge cases are documented.

## v0.0.9
- **Leaner stack: 14 containers down to 12, or 10 without the optional services.**
  - `beat` is gone: the `worker` runs Celery's scheduler in the same process (`--beat`), as one
    server needs only one scheduler. About 85 MB less memory.
  - `telemetry` is gone: it copied container logs into a file nothing read, and could see Docker.
    `make logs` shows the same logs (Docker's own rotated log files). About 40 MB less memory.
  - The DNS server (`dns`) and calendars/contacts (`dav`) are optional: `DNS_SERVER_ENABLED=0` or
    `DAV_ENABLED=0` in `provisioning/.env`, then `make provision`, removes the container. Both
    stay on by default and on existing installs. With DAV off its DNS records are not published.
- **No container can control Docker any more.** Certbot no longer has the Docker socket (which is
  root on the host) and no longer restarts services after a renewal: nginx, Postfix and Dovecot
  notice the new certificate within a minute and reload themselves, without dropping connections.
- `make update` and `make provision` remove containers of services a release dropped
  (`--remove-orphans`); `make down` and `make reload` include the optional services.
- PostgreSQL: removed a start-up script that was meant to enable TLS but wrote to a file PostgreSQL
  never reads (TLS was never on). Only containers on the internal network reach the database.

## v0.0.8
- **Users can send only as themselves.** On the submission ports (587, 465) a logged-in user may
  use as sender only their own address or an alias that forwards to them; anything else is refused
  with "Sender address rejected: not owned by user". The From header of their mail must match that
  sender (checked by Rspamd), so a user can no longer put a colleague's or the CEO's address in From
  and have it DKIM-signed and pass DMARC. Port 25, the console's own mail and Sieve are unaffected,
  and bounces (empty sender) still go out.
- Ownership is read from domains and aliases only (`postfix/pgsql/sender_logins.cf`): the Postfix
  database role still cannot read the users table. The Aliases page says that the mailboxes an
  alias forwards to may send as it.

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
