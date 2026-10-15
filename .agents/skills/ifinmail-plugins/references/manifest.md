# Plugin manifest (`plugin.toml`, manifest_version 2)

TOML, UTF-8, at most 32 KiB. Parsed with Python's standard `tomllib`. **Unknown keys are errors** at
every level, so a typo fails validation instead of being ignored. Validation reports every problem at
once, each with its location (`plugin.version`, `settings[1].type`, ...).

```toml
manifest_version = 2               # 1 named mail software directly and is refused with a hint

[plugin]
id = "compliance-journal"          # ^[a-z][a-z0-9-]{2,39}$, no "--", no trailing "-"
name = "Compliance journal"        # 1-60 characters
version = "2.0.0"                  # MAJOR.MINOR.PATCH, each 0-9999, no leading zeros
publisher = "ifinmail"             # 1-60 characters
category = "compliance"            # compliance | security | delivery | operations | integration
summary = "One line, 1-160 characters."
description = """Plain text, at most 4000 characters. Rendered escaped; blank lines are paragraphs."""
requires_core = "0.0.10"           # optional: lowest core release this works with
install_by_default = false         # optional; bundled only: installed once per server, an uninstall is respected

[[settings]]                       # 0-20 entries
key = "archive_address"            # ^[a-z][a-z0-9_]{0,39}$, unique
type = "mailbox"                   # see types below
label = "Archive mailbox"          # 1-60 characters
help = "Shown under the field."    # optional, at most 300 characters
required = true                    # optional, default false
default = "..."                    # optional; must itself be valid for the type
# type-specific: min/max (integer), options (choice), max_length (text, 1-500, default 200)

[[contributes]]                    # 1-10 entries
capability = "mail.journal"        # a capability this server offers (contract below)
values = { archive_address = "{archive_address}" }
```

## Setting types

| Type | Value | Rules |
| --- | --- | --- |
| `text` | string | trimmed; no control characters; length ≤ `max_length` |
| `integer` | int | within `min`/`max` when given; booleans are not integers |
| `boolean` | bool | form checkboxes post "on"/absent |
| `choice` | string | one of `options` (1-50 unique strings) |
| `email` | string | lower-cased; one `@`; no spaces, quotes, commas or control characters |
| `mailbox` | string | an `email` that is an existing mailbox on this server (registered by the mail app); checked again when the plugin is enabled |
| `secret` | string | an API key or token: no spaces; encrypted at rest (`plugin-secret:` + Fernet, key derived from `SECRET_KEY`); never shown again (password field, "•••• set"), an empty field keeps it; no default; may only be the **whole value** of a capability field marked `secret`, and such fields may only be bound to an in-console adapter target, so a secret never reaches a runtime file |

Defaults are validated with the type rules except the live check of `mailbox` (it cannot have a
meaningful default and is rejected if one is given).

**Defaults apply only when a value is not supplied.** Forms show the default and always post every
field, so what the administrator sees is what is saved: a field cleared on purpose stays empty (or
fails `required`), and an unchecked checkbox means false. `configure` with only some keys keeps the
current values of the others.

## Contributions

* `capability` must be offered when the manifest is validated **and** when it is installed.
* Every key in `values` must be a field of that capability. Values are strings; the only expansion is
  `{setting_key}`, which must name a declared setting. `{{` and `}}` are literal braces.
* A setting used in a value should be `required` or have a default; an empty expansion clears the field.
* Two contributions in one manifest may not set the same field. Two enabled plugins may not either
  (the second is refused with a conflict).
* After expansion the value is validated by the capability's grammar, translated for the engine by
  the adapter, validated again by the adapter target, and once more by the container's watcher.
* Booleans expand to `yes`/`no`, which is what every yes/no field of the contract takes.

## Capability contract (what plugins write)

Plugins never name mail software or its settings: a test fails if a bundled manifest mentions
Postfix, Dovecot, Rspamd, Sieve or an engine key. Units are plain (MB, days, yes/no), lists are
comma-separated and normalised (lower-case, sorted, de-duplicated, at most 200 entries). Defined in
`backend/apps/mail/services/plugin_points.py` (`_capabilities()`).

| Capability | Field | Value | Meaning |
| --- | --- | --- | --- |
| `mail.journal` | `archive_address` | one address | A copy of every message, inbound and outbound |
| `mail.limits` | `max_message_mb` | 1-50 | Largest message accepted or sent |
| `delivery.require_tls` | `domains` | domain list | Never send to these domains without TLS |
| | `verify_certificate` | yes/no | Also require a valid certificate |
| `sending.internal_only` | `mailboxes` | address list | May send only to domains hosted here |
| `sending.rate_limit` | `per_minute`, `per_day` | 1-1000, 1-100000 | Messages one mailbox may send (set both) |
| `sending.recipient_limits` | `per_message` | 1-1000 | Most recipients of one message from a logged-in user (submission ports only) |
| `sending.blocked_destinations` | `domains` | address/domain list | Logged-in users cannot send to these (subdomains included) |
| `sending.containment` | `action` | `pause` / `notify` / `off` | What to do when a mailbox crosses a threshold in an hour |
| | `max_messages`, `max_recipients`, `max_domains` | integers | Messages, distinct recipients, distinct recipient domains per mailbox per hour |
| | `notify` | address list | Told besides the administrators |
| `inbound.senders` | `block`, `allow` | address/domain lists | Refused; never spam (only when SPF or DKIM proves the sender) |
| `inbound.attachments` | `block_types` | extension list | Attachment types blocked (name and content) |
| | `action` | `reject` / `quarantine` | Refuse, or deliver to Junk |
| `inbound.authentication` | `dmarc` | `enforce` / `quarantine` / `off` | Act on senders' DMARC policies (`off` removes the engine setting) |
| `inbound.greylisting` | `enabled` | yes/no | Delay suspicious first-time senders |
| `forwarding.arc` | `trusted_forwarders` | domain list | A valid ARC chain from these lifts a DMARC rejection |
| | `seal` | yes/no | Seal mail this server forwards |
| `mailbox.retention` | `trash_days`, `junk_days`, `sent_days` | 1-3650 | Delete messages in that folder after N days |
| `mailbox.forwarding` | `max_redirects` | 0-20 | Addresses one filter rule may forward to (0 = none) |
| `mailbox.quota_warnings` | `enabled` | yes/no | Notice in the Inbox at 80% and 95% of the quota |
| `developer.sandbox` | `enabled`, `retention_days`, `max_messages` | yes/no, 1-90, 10-10000 | Mail from sandbox API keys is checked like real mail, kept for inspection and never delivered (in-console target `console.developer`) |
| `developer.events` | `enabled`, `allow_http`, `allow_private`, `max_attempts` | yes/no, yes/no, yes/no, 1-8 | Delivery outcomes of mail sent through the API, as signed webhook events (in-console target `console.developer`) |
| `developer.agent_inboxes` | `enabled`, `domain`, `max_per_key`, `default_ttl_hours`, `quota_mb` | yes/no, one hosted domain, 1-1000, 0-8760, 1-1024 | API keys with `agents.manage` create mailboxes for agents and read them over IMAP as Dovecot's master user (in-console target `console.developer`) |
| `developer.inbox_webhooks` | `enabled`, `include_body`, `allow_http`, `allow_private` | yes/no x4 | Received mail of watched mailboxes as signed `message.received` webhook events (read over IMAP every 30 s; in-console target `console.developer`) |
| `website.pages` | `modes`, `powered_by`, `project_links`, `tagline`, `footer_note` | `page=standard\|custom\|off` list, yes/no, yes/no, one line, one line | Which public pages are served, whether the footer and links mention the platform and its project, and the footer's own sentence or line (in-console target `console.website`; the text of custom pages is written under Settings → Website, not in plugin settings) |
| `assistant.model` | `base_url`, `model`, `api_key` (secret), `daily_tokens` | http(s) URL, model name, secret, 1000-10000000 | The administrator assistant's OpenAI-compatible model (in-console target `console.assistant`) |

**Adding a capability:** only when a real plugin needs it. Name the outcome, not the mechanism; give
every field one documented meaning and plain units; bind each field to exactly one adapter target key
(registration refuses an unknown or shared binding).

**Replacing an engine:** register new adapter targets and change the `target=` bindings (and
translations) in `_capabilities()`. Manifests, installations and their settings do not change.

# Adapter (engine side: plugins never see this)

Most targets are files applied by a container. A target with `in_process = True` (only
`console.assistant` and `console.containment` today) has no file and is always "applied": the console reads its values with
`InstallationService.capability_values()`. Secret fields may only be bound to such targets.

Each adapter target is a `key = value` file on the runtime volume, applied by a watcher in the
container that owns the software. `registry.to_targets()` turns capability values into target values
(e.g. `inbound.greylisting.enabled = yes` → `rspamd.policy: greylisting = on`). The Marketplace and
System health name the target's container (`service`) when something waits to be applied.

## Adapter target `postfix.main`

Postfix `main.cf` parameters applied by `sync-overrides.sh` from `postfix-plugins.conf`.

| Key | Value grammar | Effect | Notes |
| --- | --- | --- | --- |
| `always_bcc` | one email address | Postfix sends a copy of every message to it | Kept apart from the core's own overrides file and keys, so plugins can never change relaying |
| `recipient_limit` | 1-1000 | `ifinmail_recipient_limit`, which `master.cf` passes to the submission and smtps services as `smtpd_recipient_limit` | Port 25 keeps Postfix's own limit; removing it restores the template's 100 |
| `message_size_limit_mb` | 1-50 | `message_size_limit` in bytes (MB × 1048576), advertised as `SIZE` in EHLO | Capped at 50: Rspamd does not scan (or DKIM-sign) messages over its 50 MiB `max_message`, and `milter_default_action = accept` would pass them on unscanned |

An empty or absent value restores this server's own value from `main.cf.template` (e.g.
`message_size_limit = 52428800`), or removes the parameter (`postconf -X`) when the template has
none. Postfix's built-in default (10 MB for the size) is never what an uninstall leaves behind.

## Adapter target `postfix.sender_policy`

Applied by `sync-overrides.sh` from `postfix-sender-policy.conf`; acknowledged as
`postfix-sender-policy.applied`.

| Key | Value grammar | Effect |
| --- | --- | --- |
| `internal_only_logins` | comma-separated email addresses (normalised: lower-case, sorted, de-duplicated; at most 200) | These SASL logins may send only to domains hosted here; anything else is refused with 554 "This mailbox may only send to addresses within the organisation" |
| `blocked_destinations` | comma-separated addresses and/or domains (at most 200) | `check_recipient_access texthash:` map answering `554 5.7.1`; a domain also covers its subdomains. Evaluated **first**: a class that permits local delivery would end the checks early |
| `paused_logins` | comma-separated addresses | Same map as the internal-only logins, answering `554 5.7.1 Sending from this mailbox is paused`; outranks internal-only. **Not a plugin setting**: written from live containment state through a *dynamic source* (`registry.register_dynamic_source`), so a pause survives uninstalling the plugin |

The logins become a `texthash:` map of `login ifinmail_internal_only`. `main.cf` defines the
restriction class (`permit_auth_destination`, then a static reject) and the parameter
`ifinmail_submission_restrictions`, which both submission services in `master.cf` use as their
`smtpd_recipient_restrictions`. The watcher always writes the complete parameter:
`check_sasl_access texthash:<map>, permit_sasl_authenticated, reject`, or the default
`permit_sasl_authenticated, reject` when the list is empty. Port 25 is unaffected.

## Adapter target `postfix.tls_policy`

Rendered into a `texthash:` map used as `smtp_tls_policy_maps` by `sync-overrides.sh`.

| Key | Value grammar | Effect |
| --- | --- | --- |
| `domains` | comma-separated domain names (normalised: lower-case, trailing dot dropped, sorted, de-duplicated; at most 200) | Mail to these domains must use TLS |
| `level` | `encrypt` or `secure` | `secure` also requires a valid, matching certificate (from `verify_certificate` yes/no) |

## Adapter target `rspamd.policy`

Rendered by `rspamd/sync-plugins.sh` into fragments included from `local.d/multimap.conf`,
`dmarc.conf`, `arc.conf`, `composites.conf`, `greylist.conf` and `ratelimit.conf`;
`rspamadm configtest` (run as `_rspamd`) must pass before Rspamd reloads (`HUP`).

| Key | Value grammar | Effect |
| --- | --- | --- |
| `blocked_attachment_types` | comma-separated extensions `[a-z0-9]{1,10}` (normalised: dots dropped, lower-case, sorted; at most 200) | Multimap rule on attachment names, matched case-insensitively; Rspamd also detects disguised types by content |
| `blocked_attachment_action` | `reject` or `quarantine` | quarantine = "add header", filed into Junk by the global Sieve rule |
| `dmarc_enforcement` | `enforce` or `quarantine` | DMARC module actions: enforce follows the sender's policy; quarantine sends both to Junk |
| `arc_trusted_sealers` | domain list (normalised like partner TLS domains) | `whitelisted_signers_map` with `adjust_dmarc`: a valid ARC chain from these lifts a DMARC rejection |
| `arc_sealing` | `yes` or `no` | yes: seal mail passing through with the domain's DKIM key (`/etc/dkim/$domain.$selector.key`, selector `default`, `use_domain = recipient`) |
| `sender_block_list` | comma-separated addresses and/or domains (normalised like domain lists; at most 200) | Multimap rules on the envelope sender and the From header, by address and by domain, with `action = "reject"` |
| `sender_allow_list` | same grammar | Multimap rules scoring 0; the composite `IFINMAIL_SENDER_ALLOWED` (score -20) needs one of them **and** `R_DKIM_ALLOW` or `R_SPF_ALLOW`, so a forged sender gains nothing. Forced actions (attachments, malware) still apply. Allowed senders are in greylisting's `whitelist_symbols` |
| `greylisting` | `on` or `off` | off: `enabled = false` for the greylist module (from `inbound.greylisting.enabled` yes/no) |
| `send_limit_per_minute`, `send_limit_per_day` | 1-1000 and 1-100000 (both required) | Replace the built-in per-login rate with two buckets. Selectors `user.lower` and `user.lower.append("/day")`: Rspamd keys a bucket by the hash of the selector value, so the same selector twice would share one counter. The per-recipient-domain rate (40/h) is kept |

The watch loop also reloads Rspamd once it is serving and again whenever Redis's `run_id` changes:
Rspamd 3.8.1 counts but does not enforce rate limits if Redis was unreachable when it started.

## Adapter target `dovecot.policy`

Rendered by `dovecot/sync-plugins.sh` into `/etc/dovecot/ifinmail-plugins.conf`, included last
from `dovecot.conf`; `doveconf -n` must pass before `doveadm reload`.

| Key | Value grammar | Effect |
| --- | --- | --- |
| `max_redirects` | 0-20 | `sieve_max_redirects` |
| `autoexpunge_trash_days`, `autoexpunge_junk_days`, `autoexpunge_sent_days` | 1-3650 | `autoexpunge` on that special-use mailbox |
| `quota_warnings` | `yes` or `no` | yes: `quota_warning` at 95% and `quota_warning2` at 80% run `service quota-warning` (as `vmail`), which puts a notice in the user's Inbox with `dovecot-lda` and quota enforcement off for that message |

Capability fields and target keys may carry a **normaliser**: values are normalised, then validated, both in the
console and (by grammar) again in the container.
