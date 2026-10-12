---
name: ifinmail-plugins
description: How ifinmail's configuration-based plugin layer works and how to build on it - the manifest format, extension points, setting types, the installation and submission state machines, the Marketplace, and the edge cases every change must keep handling. Use before writing or reviewing a plugin manifest, adding an extension point or setting type, changing plugin lifecycle code, or touching the Marketplace pages.
---

# ifinmail plugins

A plugin is a **declarative manifest**, not code. It describes settings an administrator fills in and
the values those settings produce at named **extension points** owned by the core. The core validates
everything, renders the result, and applies it through machinery that already exists. A plugin can
therefore never do more than its extension points allow, cannot run code, and cannot crash a worker.

```
plugin.toml ──validate──> PluginManifest ──install──> PluginInstallation (DB, desired state)
                                                          │ render (pure)
                                                          v
                         extension point (registered by a domain app) ──publish──> runtime file
                                                          │ applied by the owning container
                                                          v
                                               acknowledgement ──> "Applied" / "Waiting"
```

## Where things live

| Piece | Location | Owner |
| --- | --- | --- |
| Engine: manifest, catalog, registries, lifecycle, submissions | `backend/apps/core/plugins/` | core (no imports from domain apps) |
| Extension points `postfix.main`, `postfix.tls_policy`, `rspamd.policy`, `dovecot.policy`; setting type `mailbox` | `backend/apps/mail/services/plugin_points.py`, registered in `MailConfig.ready()` | mail app |
| Bundled (first-party) plugins | `backend/apps/core/plugins/bundled/<id>/plugin.toml` | reviewed through code review |
| Marketplace pages | `backend/apps/accounts/views/marketplace.py`, `frontend/templates/admin/marketplace*.html` | console |
| Container side (re-validate, check config, reload, acknowledge) | `postfix/sync-overrides.sh`, `rspamd/sync-plugins.sh`, `dovecot/sync-plugins.sh` under `provisioning/docker/` | postfix, rspamd, dovecot containers |

Full references: `references/manifest.md` (format and rules), `references/state-machines.md`
(transitions, recovery, reconciliation), `references/edge-cases.md` (the 200 cases and where each is
handled).

## Principles (do not trade these away)

1. **Neutral core.** `core/plugins` defines registries; domain apps register extension points and
   setting types in `AppConfig.ready()`. Core never imports `mail`, `dns` or `accounts`.
2. **Declarative only.** Manifests contain data. Values reach the system only as validated strings at
   allow-listed keys, re-validated where they are applied (defence in depth).
3. **Desired state in the database, effects derived from it.** Rendering is a pure function of all
   enabled installations. Any file can be rebuilt from the database at any time (`reconcile`).
4. **Every transition is explicit.** One table defines which operation is allowed from which state;
   anything else is refused with a message, never silently ignored.
5. **Crash-safe by construction.** Transient states are committed before effects run; a request that
   dies mid-way leaves a row the next read or the reconcile job finishes or marks failed.
6. **Cheap.** No new process, no polling loop, no third-party package. Bundled manifests are parsed
   once per process; files are rewritten only when their content changes; the Postfix watcher already
   wakes every 10 s and compares one hash.
7. **Humans approve.** Submissions are never approved automatically. Approval is one explicit action by
   someone with `system.manage`, recorded in the audit trail. No other gates in v1.
8. **Internal sources only.** Plugins come from the bundled directory or from approved submissions.
   There is no URL, registry or upload of code.

## Adding an extension point (checklist)

1. Implement `ExtensionPoint` (key, title, `allowed_keys` with a validator per key, `render`, `publish`,
   `applied_status`) in the owning app's services.
2. Register it in that app's `AppConfig.ready()` with `registry.register_point(...)`.
3. Make the consumer re-validate every value (allow-list + value grammar) before applying it.
4. Publish an acknowledgement (hash of what was applied) so the console can show Applied / Waiting.
5. Add the point's keys to `references/manifest.md`, its cases to `references/edge-cases.md`, and tests:
   allowed/forbidden keys, injection attempts, empty values removing the setting, conflict between two
   plugins, reconcile after a lost file.

## Writing a plugin (checklist)

1. Copy `bundled/compliance-journal/plugin.toml`. Pick an id that says what it does (`kebab-case`).
2. Declare only the settings an administrator must decide; give safe defaults to the rest.
3. Map settings to extension-point values with `{setting_key}` placeholders. Nothing else is expanded.
4. Run `python manage.py validate_plugin path/to/plugin.toml` (prints every problem at once).
5. Bundled: open a pull request. Otherwise: Marketplace → Submit, then a reviewer approves or rejects.

## When you are done

Run the plugin tests (`backend/apps/core/plugins/tests/`), the Marketplace view tests, the Postfix sync
tests, the design audit (`.agents/skills/ifinmail-design-audit/scripts/audit.sh`), and update the
edge-case table if you changed behaviour.
