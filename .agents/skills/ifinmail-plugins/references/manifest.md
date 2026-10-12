# Plugin manifest (`plugin.toml`, manifest_version 1)

TOML, UTF-8, at most 32 KiB. Parsed with Python's standard `tomllib`. **Unknown keys are errors** at
every level, so a typo fails validation instead of being ignored. Validation reports every problem at
once, each with its location (`plugin.version`, `settings[1].type`, ...).

```toml
manifest_version = 1

[plugin]
id = "compliance-journal"          # ^[a-z][a-z0-9-]{2,39}$, no "--", no trailing "-"
name = "Compliance journal"        # 1-60 characters
version = "1.0.0"                  # MAJOR.MINOR.PATCH, each 0-9999, no leading zeros
publisher = "ifinmail"             # 1-60 characters
category = "compliance"            # compliance | security | delivery | operations | integration
summary = "One line, 1-160 characters."
description = """Plain text, at most 4000 characters. Rendered escaped; blank lines are paragraphs."""
requires_core = "0.0.4"            # optional: lowest core release this works with

[[settings]]                       # 0-20 entries
key = "archive_address"            # ^[a-z][a-z0-9_]{0,39}$, unique
type = "mailbox"                   # see types below
label = "Archive mailbox"          # 1-60 characters
help = "Shown under the field."    # optional, at most 300 characters
required = true                    # optional, default false
default = "..."                    # optional; must itself be valid for the type
# type-specific: min/max (integer), options (choice), max_length (text, 1-500, default 200)

[[contributes]]                    # 1-10 entries
point = "postfix.main"             # a registered extension point
values = { always_bcc = "{archive_address}" }
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

Defaults are validated with the type rules except the live check of `mailbox` (it cannot have a
meaningful default and is rejected if one is given).

## Contributions

* `point` must be registered when the manifest is validated **and** when it is installed.
* Every key in `values` must be on that point's allow-list. Values are strings; the only expansion is
  `{setting_key}`, which must name a declared setting. `{{` and `}}` are literal braces.
* A setting used in a value should be `required` or have a default; an empty expansion clears the key.
* Two contributions in one manifest may not set the same key.
* After expansion the value is validated by the point's own grammar (for `always_bcc`: one address,
  no whitespace). The Postfix watcher validates it again before calling `postconf`.

## Extension point `postfix.main`

Postfix `main.cf` parameters applied by `sync-overrides.sh` from `postfix-plugins.conf`.

| Key | Value grammar | Effect | Notes |
| --- | --- | --- | --- |
| `always_bcc` | one email address | Postfix sends a copy of every message to it | Kept apart from the core's own overrides file and keys, so plugins can never change relaying |

Empty or absent values remove the parameter (`postconf -X`), restoring Postfix's default.

## Extension point `postfix.tls_policy`

Rendered into a `texthash:` map used as `smtp_tls_policy_maps` by `sync-overrides.sh`.

| Key | Value grammar | Effect |
| --- | --- | --- |
| `domains` | comma-separated domain names (normalised: lower-case, trailing dot dropped, sorted, de-duplicated; at most 200) | Mail to these domains must use TLS |
| `level` | `encrypt` or `secure` | `secure` also requires a valid, matching certificate |

## Extension point `rspamd.policy`

Rendered by `rspamd/sync-plugins.sh` into fragments included from `local.d/multimap.conf` and
`local.d/dmarc.conf`; `rspamadm configtest` must pass before Rspamd reloads (`HUP`).

| Key | Value grammar | Effect |
| --- | --- | --- |
| `blocked_attachment_types` | comma-separated extensions `[a-z0-9]{1,10}` (normalised: dots dropped, lower-case, sorted; at most 200) | Multimap rule on attachment names, matched case-insensitively; Rspamd also detects disguised types by content |
| `blocked_attachment_action` | `reject` or `quarantine` | quarantine = "add header", filed into Junk by the global Sieve rule |
| `dmarc_enforcement` | `enforce` or `quarantine` | DMARC module actions: enforce follows the sender's policy; quarantine sends both to Junk |

## Extension point `dovecot.policy`

Rendered by `dovecot/sync-plugins.sh` into `/etc/dovecot/ifinmail-plugins.conf`, included last
from `dovecot.conf`; `doveconf -n` must pass before `doveadm reload`.

| Key | Value grammar | Effect |
| --- | --- | --- |
| `max_redirects` | 0-20 | `sieve_max_redirects` |
| `autoexpunge_trash_days`, `autoexpunge_junk_days`, `autoexpunge_sent_days` | 1-3650 | `autoexpunge` on that special-use mailbox |

Keys a point allows may carry a **normaliser**: values are normalised, then validated, both in the
console and (by grammar) again in the container.
