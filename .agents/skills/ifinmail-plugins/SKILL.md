---
name: ifinmail-plugins
description: How ifinmail's configuration-based plugin layer works and how to build on it - the manifest format, extension points, setting types, the installation and submission state machines, the Marketplace, and the edge cases every change must keep handling. Use before writing or reviewing a plugin manifest, adding an extension point or setting type, changing plugin lifecycle code, or touching the Marketplace pages.
---

# ifinmail plugins

A plugin is a **declarative manifest**, not code. It describes settings an administrator fills in and
the values those settings produce for named **capabilities** (`mail.journal`, `sending.rate_limit`):
an engine-neutral contract that never names Postfix, Dovecot or Rspamd. An **adapter** owned by the
mail app binds each capability field to an engine-side **target** and translates the value. The core validates
everything, renders the result, and applies it through machinery that already exists. A plugin can
therefore never do more than its extension points allow, cannot run code, and cannot crash a worker.

```
plugin.toml ──validate──> PluginManifest ──install──> PluginInstallation (DB, desired state)
                                                          │ render (pure)
                                                          v
             capability (contract) ──adapter: to_targets──> adapter target ──publish──> runtime file
                                                          │ applied by the owning container
                                                          v
                                               acknowledgement ──> "Applied" / "Waiting"
```

## Where things live

| Piece | Location | Owner |
| --- | --- | --- |
| Engine: manifest, catalog, registries, lifecycle, submissions | `backend/apps/core/plugins/` | core (no imports from domain apps) |
| Capabilities (the contract, 13), adapter targets `postfix.main`, `postfix.tls_policy`, `postfix.sender_policy`, `rspamd.policy`, `dovecot.policy`; setting type `mailbox` | `backend/apps/mail/services/plugin_points.py`, registered in `MailConfig.ready()` | mail app |
| Bundled (first-party) plugins | `backend/apps/core/plugins/bundled/<id>/plugin.toml` | reviewed through code review |
| Marketplace pages | `backend/apps/accounts/views/marketplace.py`, `frontend/templates/admin/marketplace*.html` | console |
| Container side (re-validate, check config, reload, acknowledge) | `postfix/sync-overrides.sh`, `rspamd/sync-plugins.sh`, `dovecot/sync-plugins.sh` under `provisioning/docker/` | postfix, rspamd, dovecot containers |

Full references: `references/manifest.md` (format and rules), `references/state-machines.md`
(transitions, recovery, reconciliation), `references/edge-cases.md` (the 310 cases and where each is
handled).

## Principles (do not trade these away)

1. **Neutral core.** `core/plugins` defines registries; domain apps register capabilities, adapter
   targets and setting types in `AppConfig.ready()`. Core never imports `mail`, `dns` or `accounts`.
2. **Plugins never know the engine.** Manifests name capabilities and plain values only. Engine
   names and settings live in adapter targets; swapping an engine changes bindings, not manifests.
3. **Declarative only.** Manifests contain data. Values reach the system only as validated strings at
   allow-listed keys, re-validated where they are applied (defence in depth).
4. **Desired state in the database, effects derived from it.** Rendering is a pure function of all
   enabled installations. Any file can be rebuilt from the database at any time (`reconcile`).
5. **Every transition is explicit.** One table defines which operation is allowed from which state;
   anything else is refused with a message, never silently ignored.
6. **Crash-safe by construction.** Transient states are committed before effects run; a request that
   dies mid-way leaves a row the next read or the reconcile job finishes or marks failed.
7. **Cheap.** No new process, no polling loop, no third-party package. Bundled manifests are parsed
   once per process; files are rewritten only when their content changes; the Postfix watcher already
   wakes every 10 s and compares one hash.
8. **Humans approve.** Submissions are never approved automatically. Approval is one explicit action by
   someone with `system.manage`, recorded in the audit trail. No other gates in v1.
9. **Internal sources only.** Plugins come from the bundled directory or from approved submissions.
   There is no URL, registry or upload of code.

## Adding a capability (checklist)

Only when a real plugin needs it. Name the outcome, not the mechanism.

1. Add it to `_capabilities()` in `plugin_points.py`: key (`area.outcome`), title, description,
   fields in plain units, each bound with `target=(adapter target, key)` and, if the engine word
   differs, a `translate`. Registration refuses unknown or shared bindings.
2. If no target key carries it yet, add the key to an adapter target (below) first.
3. Document it in the contract table of `references/manifest.md`; add edge cases and tests (grammar,
   translation, empty value, no engine words).

## Adding an adapter target (checklist)

1. Implement `AdapterTarget` (key, `service`, `keys` with a validator per key, `runtime_file`,
   `ack_file`) in the owning app's services and add it to `TARGETS`.
2. Make the consumer re-validate every value (allow-list + value grammar) before applying it.
3. Publish an acknowledgement (hash of what was applied) so the console can show Applied / Waiting.
4. Add the target's keys to the adapter part of `references/manifest.md`, its cases to
   `references/edge-cases.md`, and tests: allowed/forbidden keys, injection attempts, empty values
   removing the setting, reconcile after a lost file.

## Writing a plugin (checklist)

Group by what an administrator decides together, not one plugin per capability: a plugin may write
several capabilities, and each part should still have an "off" value (an empty list, an unticked
box, a choice such as `off`). The built-in set is Inbound protection, Sending and delivery policy,
Mailbox care and Compliance journal, which between them offer every capability field exactly once.

1. Copy `bundled/compliance-journal/plugin.toml`. Pick an id that says what it does (`kebab-case`).
2. Declare only the settings an administrator must decide; give safe defaults to the rest.
3. Map settings to capability fields with `{setting_key}` placeholders. Nothing else is expanded.
   Never mention the mail software in names, help or description.
4. Run `python manage.py validate_plugin path/to/plugin.toml` (prints every problem at once).
5. Bundled: open a pull request. Otherwise: Marketplace → Submit, then a reviewer approves or rejects.

## When you are done

Run the plugin tests (`backend/apps/core/plugins/tests/`), the Marketplace view tests, the Postfix sync
tests, the design audit (`.agents/skills/ifinmail-design-audit/scripts/audit.sh`), and update the
edge-case table if you changed behaviour.
