# State machines

## Installation (`PluginInstallation.state`)

A row exists from the moment an install starts until an uninstall completes; "not installed" is the
absence of a row.

```
                 install                       ┌──────── configure / update ───────┐
   (none) ──────────────> installing ──ok──> enabled <──ok── applying ──ok──> disabled
                               │               │  ^            ^   │             │  ^
                               │ error  disable│  │ enable     │   │ error       │  │
                               v               v  │            │   v             │  │
                             failed <──────── applying ────────┘ failed          │  │
                               │  retry ─> applying ─> (target)                  │  │
                               └──── uninstall ──> uninstalling ──ok──> (row removed)
```

| Operation | Allowed from | Transient | Target | Effects |
| --- | --- | --- | --- | --- |
| install | *(no row)* | installing | enabled | validate settings, conflicts, compatibility; publish |
| enable | disabled | applying | enabled | conflict check; publish |
| disable | enabled | applying | disabled | publish (keys removed) |
| configure | enabled, disabled | applying | unchanged | validate settings; publish |
| update | enabled, disabled | applying | unchanged | new manifest snapshot; settings revalidated against it; publish |
| retry | failed | applying | the target recorded when it failed | publish |
| uninstall | enabled, disabled, failed | uninstalling | *(row removed)* | publish (keys removed) |

Rules:

1. **Validate first, then change state.** Bad settings, conflicts, incompatible core version or an
   unknown extension point are refused before any state is written: the row (if any) is untouched.
2. **Two phases.** Phase 1 (transaction, row locked): check the transition and the revision, write the
   transient state, the target and the new desired values, bump `revision`. Phase 2: publish every
   affected extension point from the database. Phase 3 (transaction): write the target (or delete the row).
3. **Rendering counts the target.** While a row is transient, the renderer treats it as its target, so
   phase 2 produces exactly the end state.
4. **Effect failure ⇒ `failed`.** If publishing raises, the row becomes `failed` with `last_error` and
   the target it was heading for; the files are reconciled from the database; `retry` or `uninstall`
   recover it.
5. **Busy.** Another operation on a row in a transient state is refused, unless that state is older
   than 120 s (`STALE_SECONDS`): then the stale operation is finished first (phase 2 + 3), because
   rendering is idempotent.
6. **Optimistic concurrency.** Forms carry `revision`; a mismatch means someone else changed the
   installation and the operation is refused with "reload".
7. **Manifest snapshot.** Each installation stores the manifest it was installed or updated with, so
   it keeps rendering if the catalog entry is retired or a bundled plugin is removed from the code.
8. **Audit.** Every operation records `plugin_<operation>` (and `plugin_failed`) with actor, plugin,
   version and `from -> to`.

## Applied state (observed, not stored)

The console writes `<runtime>/postfix-plugins.conf`; the Postfix watcher applies it and writes the
SHA-256 of what it applied to `<status>/postfix-plugins.applied`. The Marketplace compares the two:

| Observation | Shown |
| --- | --- |
| hashes equal | Applied |
| different, file younger than 60 s | Applying (within ~10 s) |
| different, older | Not applied: check the postfix container |
| no acknowledgement readable | Unknown |

Nothing polls: the comparison happens when a page is rendered.

## Reconcile

`InstallationService.reconcile()` finishes stale transient rows and republishes every extension
point from the database, writing a file only when its content changed. It runs from the
`plugins.reconcile` beat job every 10 minutes and after any failed operation.

## Submission (`PluginSubmission.state`)

```
submit ──> submitted ──approve──> approved ──retire──> retired
              │  │
              │  └──reject──> rejected
              └──withdraw──> withdrawn
```

| Operation | From | To | Who |
| --- | --- | --- | --- |
| submit | — | submitted | anyone with console access |
| approve | submitted | approved | `system.manage`, explicit action, never automatic |
| reject | submitted | rejected | `system.manage`; a note is required |
| withdraw | submitted | withdrawn | the submitter or `system.manage` |
| retire | approved | retired | `system.manage`; installed copies keep working |

Rules: a plugin id used by a bundled plugin cannot be submitted; a version must be higher than the
latest approved one for the same id; the same id and version cannot be live twice (submitted,
approved or retired), but may be resubmitted after a rejection or withdrawal; the manifest is
validated again at approval time.
