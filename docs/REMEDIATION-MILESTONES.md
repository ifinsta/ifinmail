# Internal Remediation Milestones for an End-to-End Mail Appliance Experience

## Purpose

This plan turns ifinmail from a collection of working pieces into a self-managing mail appliance with real internal organs: durable state, service contracts, background jobs, generated mail-server configuration, observability, safe maintenance boundaries, and end-to-end certification.

Built-in webmail is intentionally excluded. The target experience is excellent admin, provisioning, client autoconfig, IMAP/SMTP, operations, backups, and deliverability.

## Non-Negotiable Internal Standard

Every milestone must define and test:

- **State:** the database models, files, Redis keys, secrets, and generated configs involved.
- **Service boundary:** the service class/function that owns business logic.
- **Worker boundary:** the background job or CLI script that performs slow/system work.
- **Config boundary:** which Postfix, Dovecot, Rspamd, nginx, certbot, DKIM, DNS, or backup files are read or generated.
- **Audit boundary:** who did what, to which entity, with what result.
- **Health boundary:** how the system reports ok/warn/error/degraded.
- **Rollback boundary:** what happens when the action partially fails.
- **UI/API boundary:** the admin surface and API contract must use the same service truth.
- **Tests:** unit, service, view/API, provisioning dry-run, and end-to-end tests.

## Milestone Completion Packet

Each milestone must produce a completion packet before it can be considered done. This avoids "feature done" claims when only the UI or only the script was touched.

Required packet:

- **Architecture note:** what changed internally, where state lives, and which service owns it.
- **Schema note:** models, migrations, indexes, uniqueness constraints, and retention rules.
- **Service contract:** public methods, inputs, outputs, typed errors, idempotency rules, and permissions.
- **Job contract:** task name, queue/runner, lock key, retry policy, timeout, cancellation behavior, and output format.
- **Config contract:** generated files, source templates, validation command, reload command, rollback path.
- **Health contract:** check id, severity mapping, stale threshold, remediation message, dashboard/API representation.
- **Audit contract:** event names, actor, entity, target id, correlation id, severity, and redaction rules.
- **Security review:** secrets handling, permission checks, CSRF/API auth, shell/system boundaries.
- **UX evidence:** screenshots or review notes for empty, loading, success, validation error, permission error, and system failure states.
- **Test evidence:** test names, command output, mocked external dependencies, and remaining manual verification.
- **Operational note:** how an admin recovers when the milestone's main flow fails.

## Experience Bar

The target is not simply parity with Mail-in-a-Box. The target is a guided appliance that explains itself without overwhelming the admin.

Experience rules:

- Every degraded state must say **what is wrong**, **why it matters**, and **what to do next**.
- Every system action must show **pending**, **result**, and **persistence after refresh**.
- Every dangerous action must be mediated by permission, audit, and a safe internal service.
- Every generated artifact must be previewable before apply when practical.
- Every integration must report whether it is **configured**, **verified**, **stale**, **failed**, or **not available**.
- Every dashboard badge must be traceable to a health check or job result.
- Every remediation hint must be specific to the entity, for example the affected domain, DNS record, certificate, mailbox, or backup target.

## Cross-Cutting Architecture Decisions

These decisions should be made early and then applied consistently across milestones.

### State Ownership

- Product/application state belongs in Django models.
- Fast-changing monitor samples may use Redis for ingestion, but durable status summaries must land in the database.
- Generated service configs are artifacts, not primary truth.
- Secrets must not be stored in plaintext model fields. Use environment, encrypted storage, or a secret reference pattern.

### Job Ownership

- Web requests may create jobs and poll jobs; they must not perform slow privileged work directly.
- Jobs must be idempotent where users can retry from the UI.
- Jobs must have correlation ids that link UI action, service call, job run, audit event, logs, and health result.
- Jobs must write structured summaries, not only raw stdout.

### Config Ownership

- Config render must be deterministic from database state and template version.
- Config apply must validate before reload.
- Config reload must know which service is affected.
- Last-known-good config must be restorable.
- Config drift must be detectable.

### Health Ownership

- Health checks must be entity-scoped when possible: domain, mailbox, service, certificate, backup target.
- Stale health is a separate state from healthy.
- Health checks must separate measured fact from recommendation.
- UI rollups must not hide the underlying failing check.

### Audit Ownership

- Audit is for user/admin/business/security actions.
- System logs are for service/runtime telemetry.
- Metric samples are for numeric trends.
- Do not merge all three into one table or one UI concept.

### Provisioning Ownership

- Provisioning must be resumable.
- Provisioning must never overwrite existing secrets, DKIM keys, TLS keys, or mail data without explicit recovery flow.
- Provisioning must write a phase report that the admin UI can later display.

## Milestone 0: Internal Systems Map

Objective: Produce an architectural map of the organs before changing behavior.

Internal work:

- Map current models in `accounts`, `domains`, `mail`, `dns`, `devices`, `core/storage`, and `backend/services`.
- Map unmanaged mail tables used by Postfix/Dovecot lookups.
- Map generated files under `provisioning/docker/postfix`, `dovecot`, `rspamd`, `nginx`, `certbot`, and `dkim`.
- Map scripts under `provisioning/scripts`: bootstrap, setup wizard, provision, obtain-ssl, backup, restore test, monitor, firewall, deploy.
- Map env files and secrets: `.env`, `provisioning/.env`, DKIM keys, GPG backup key, TLS private keys, database credentials.
- Map runtime data: PostgreSQL rows, Redis monitor keys, mail queue, Maildir volume, audit events, logs.

Deliverables:

- `docs/INTERNAL-SYSTEMS-MAP.md`.
- Entity/action matrix: Domain, Mailbox, Alias, User, DNSProviderConfig, DNSRecord, Certificate, BackupJob, MonitorSample, AuditEvent.
- Current-state classification: implemented, placeholder, script-only, UI-only, missing.

Acceptance criteria:

- No milestone can claim completion without naming its internal state and owner service.
- Every UI page has a traced backend source of truth.

## Milestone 1: Appliance State Model

Objective: Create durable state for setup, appliance health, jobs, and system configuration.

Internal work:

- Add or complete models for:
  - `ApplianceState`: install id, setup status, setup step, domain, mail hostname, version, mode.
  - `SystemSetting`: typed key/value settings with validation and secrecy flags.
  - `JobRun`: background job status, kind, input summary, output summary, logs pointer, started/finished timestamps.
  - `HealthCheckResult`: check id, target, status, observed value, expected value, message, remediation, last run.
  - `NotificationEvent`: alert/recovery state, channel, dedupe key.
- Keep secrets out of plain model fields unless encrypted or stored through the approved secret mechanism.
- Define service APIs for reading and mutating state.

Deliverables:

- Models, migrations, services, admin registration, tests.
- Typed status enums in the relevant `types/` modules.
- Cleanup of any setup/session-only state that should persist.

Acceptance criteria:

- Setup progress survives process restart.
- Health state survives long enough for UI and alerts.
- Background jobs are queryable and auditable.

## Milestone 2: Configuration Rendering Engine

Objective: Stop hand-editing scattered config as the source of truth; render configs from validated appliance state.

Internal work:

- Add a config rendering service that produces:
  - Postfix virtual domain/mailbox/alias lookup config.
  - Dovecot SQL/auth/passdb/userdb config references.
  - Rspamd DKIM signing config and policy snippets.
  - nginx autoconfig/static/TLS snippets.
  - certbot renewal/deploy hook config.
- Separate templates from generated files.
- Implement dry-run render, diff, apply, validate, reload.
- Define file ownership and permission checks.
- Add rollback: keep last known good generated config.

Deliverables:

- `ConfigRenderService`.
- Template directory for generated configs.
- Checksums and last-applied metadata.
- CLI command: render configs dry-run/apply.

Acceptance criteria:

- Creating a domain/mailbox/alias can regenerate the exact config needed by mail services.
- Bad config render fails before reload.
- Previous working config can be restored.

## Milestone 3: Job Runner and Safe System Adapter

Objective: Move shell/system work behind a safe internal adapter instead of direct view subprocess calls.

Internal work:

- Build `SystemCommandService` with allowlisted commands only.
- Build `JobService` for queued jobs: DNS sync, health scan, backup, restore test, cert issue, config apply, service reload.
- Move slow or privileged operations out of web requests.
- Record stdout/stderr summaries safely with sensitive-value redaction.
- Add idempotency keys for repeated UI clicks.
- Add timeout, lock, retry, cancellation, and concurrency rules.

Deliverables:

- No web view directly shells out except through approved service or documented CLI exception.
- Job status endpoint and UI pattern.
- Audit event for start, success, failure, cancellation.

Acceptance criteria:

- Rescan, backup, certificate issue, DNS sync, and config apply are all background jobs.
- A failed job leaves state unchanged or explicitly degraded with remediation.
- Web shell remains impossible.

## Milestone 4: First-Run Setup State Machine

Objective: Make setup a real state machine, not a set of loosely connected pages/session values.

Internal work:

- Define setup states: `fresh`, `domain_pending`, `dns_pending`, `admin_pending`, `tls_pending`, `backup_pending`, `verification_pending`, `complete`.
- Store transitions in `ApplianceState`.
- Add transition guards and rollback points.
- Generate initial domain, DKIM, DNS expected records, admin user, mailbox, and backup preference through services.
- Ensure setup can resume after browser/server restart.
- Seal setup after completion.

Deliverables:

- `SetupService`.
- Setup transition tests.
- Setup audit trail.
- Setup verification checklist persisted as health checks.

Acceptance criteria:

- Re-running setup does not duplicate domains, users, DKIM keys, or mailboxes.
- Setup cannot skip required internal state unless explicitly marked deferred.
- Dashboard reflects true setup state.

## Milestone 5: Domain, Mailbox, Alias, and User Core

Objective: Make the primary mail entities internally consistent and connected to Postfix/Dovecot.

Internal work:

- Normalize data model relationships:
  - Domain owns DKIM keys, DNS records, mailboxes, aliases, TLS target state.
  - Mailbox maps to Dovecot username, storage path, quota, active state.
  - Alias maps source to one or more destinations with loop prevention.
  - User maps login/admin identity separately from mailbox identity when needed.
- Add service-level transactions for create/update/delete.
- Add validation for domain names, local parts, duplicate addresses, alias loops, reserved names.
- Add generated lookup checks for Postfix and Dovecot.
- Add password-hash rotation path.

Deliverables:

- `DomainLifecycleService`, `MailboxService`, `AliasService`, `UserLifecycleService`.
- Import/export service contracts.
- Config render trigger after lifecycle changes.

Acceptance criteria:

- Create domain -> mailbox -> user -> alias from service and UI.
- Postfix lookup and Dovecot auth resolve the created mailbox.
- Deletes are protected when dependent mailboxes/aliases exist unless explicitly cascaded.

## Milestone 6: DNS Source of Truth and Verification Engine

Objective: Treat DNS as a first-class state machine with expected, provider, and observed values.

Internal work:

- Create/complete models:
  - `DNSRecord`: expected type/name/value/ttl/priority/source/purpose/status.
  - `DNSProviderConfig`: provider, credential reference, capabilities, last sync.
  - `DNSCheckResult`: observed value, resolver used, status, remediation.
- Generate records from domain state: A, MX, SPF, DKIM, DMARC, MTA-STS, TLS-RPT, autoconfig.
- Implement provider adapters with capability detection, dry-run, apply, verify.
- Implement manual DNS mode with copy/export and resolver verification.
- Add DNSSEC status checks and registrar-oriented guidance.
- Add custom DNS records with conflict detection.

Deliverables:

- `DNSRecordService`, `DNSVerificationService`, provider sync jobs.
- Zone export.
- Resolver tests with mocked DNS answers.

Acceptance criteria:

- Each DNS row has expected, observed, status, last checked, and next action.
- Provider sync never reports success without subsequent verification or explicit pending state.
- DKIM TXT values are split/exported correctly and never truncated.

## Milestone 7: Deliverability Engine

Objective: Turn deliverability into computed health, not prose.

Internal work:

- Build checks for:
  - Port 25 inbound/outbound reachability.
  - PTR/rDNS match.
  - HELO/EHLO hostname consistency.
  - SPF, DKIM, DMARC alignment.
  - TLS availability on SMTP/IMAP/submission.
  - Rspamd signing status.
  - Postfix queue deferred/bounced/sent counts.
  - Blacklist checks via pluggable providers.
  - MTA-STS and TLS-RPT record presence.
- Store results in `HealthCheckResult`.
- Add severity rules and dashboard rollups.

Deliverables:

- `DeliverabilityService`.
- Periodic deliverability job.
- UI/API response contract.

Acceptance criteria:

- Admin can answer whether mail is send-ready and receive-ready.
- Every failed deliverability check has measured evidence and remediation.
- Checks run without blocking web requests.

## Milestone 8: TLS and Certificate Lifecycle Internals

Objective: Own certificate state across nginx, Postfix, Dovecot, and autoconfig.

Internal work:

- Add `CertificateState`: domain, paths, issuer, SANs, expiry, status, source, last renewal attempt.
- Add certificate scanner for filesystem and live socket probes.
- Add certbot job wrapper with lock, timeout, rollback to previous cert.
- Add imported certificate validation: key match, chain validity, SAN coverage.
- Add service reload plan after cert changes.
- Add deploy-hook audit and health update.

Deliverables:

- `CertificateService`.
- Certificate status page/API.
- Renewal alert rules.

Acceptance criteria:

- Certificate issue/renew/import has a job record, audit event, health result, and rollback.
- Mail ports and HTTPS are verified after certificate changes.

## Milestone 9: Backup and Restore Internals

Objective: Make backup status and restore confidence queryable, not just script output.

Internal work:

- Add `BackupTarget`, `BackupRun`, `RestoreTestRun` models or equivalents.
- Wrap `backup_full.sh` and `restore_test.sh` with `BackupService`.
- Parse backup manifests, checksums, archive metadata, encryption status, DKIM key presence, mail volume presence.
- Support local, rsync, and S3-compatible targets through typed target config.
- Redact secrets in logs.
- Add retention policy state and enforcement.
- Add restore-test job that records granular result per component.

Deliverables:

- Backup status UI/API.
- Backup and restore-test jobs.
- Backup target validation.

Acceptance criteria:

- Admin can see latest backup, target, age, size, encryption, checksum, and restore-test result.
- Missing DKIM keys or failed DB dump marks backup unhealthy.
- Failed backup triggers notification event.

## Milestone 10: Monitoring, Logs, Metrics, and Audit Pipeline

Objective: Build one observability pipeline instead of separate ad hoc outputs.

Internal work:

- Normalize monitor output into `HealthCheckResult` and time-series history.
- Separate:
  - `AuditEvent`: admin/security/business actions.
  - `SystemLogEvent`: service logs and telemetry.
  - `HealthCheckResult`: current computed state.
  - `MetricSample`: numeric trend data.
- Ingest monitor.py output from Redis or direct service.
- Add parsers for Postfix delivery outcomes and queue states.
- Add retention and purge policies.
- Add correlation ids from UI action -> job -> audit -> logs.

Deliverables:

- `MonitoringIngestService`.
- `LogService`.
- Real logs page data source.
- Dashboard cards backed by live health results.

Acceptance criteria:

- Logs page never uses placeholder telemetry.
- Audit trail can trace admin actions.
- System logs can trace service failures.
- Dashboard degrades gracefully when monitor data is stale.

## Milestone 11: Admin Security, 2FA, and Session Control

Objective: Secure the admin plane as a production control plane.

Internal work:

- Add TOTP device model or integrate a vetted Django TOTP package.
- Add recovery code storage with hashing.
- Add staff 2FA enforcement setting.
- Add session inventory, revoke-all, revoke-specific.
- Add login risk events: failed attempts, new device/IP, locked account.
- Ensure high-risk actions require staff, CSRF, and optional re-auth.

Deliverables:

- `AdminSecurityService`.
- 2FA enrollment/recovery flow.
- Session management service.
- Audit events for login, logout, 2FA, recovery, session revocation.

Acceptance criteria:

- Staff can be forced through TOTP.
- Recovery codes are single-use and not stored plaintext.
- Security events appear in audit and notifications.

## Milestone 12: Notification Engine

Objective: Notify admins when the appliance needs attention without spamming them.

Internal work:

- Define notification triggers: backup failed, restore test failed, certificate expiring, DNS broken, deliverability critical, service down, suspicious login.
- Add `NotificationPreference` and `NotificationEvent`.
- Add dedupe keys, cooldowns, recovery events, escalation severity.
- Support email channel first; keep webhook adapters pluggable.
- Add template rendering and delivery audit.

Deliverables:

- `NotificationService`.
- Email templates.
- Notification history page.

Acceptance criteria:

- A health transition from ok -> critical sends one alert.
- A transition from critical -> ok sends one recovery notice.
- Repeated failures are deduped according to policy.

## Milestone 13: Safe Maintenance and Update Intelligence

Objective: Expose maintenance truth without dangerous browser power.

Internal work:

- Add `VersionService`: app version, image tags, OS version, migration state, config schema version.
- Add update availability check as read-only.
- Add reboot-required check as read-only.
- Add maintenance command generation for CLI execution.
- Add migration/check status and config drift detection.
- Keep web reboot and shell disabled.

Deliverables:

- Maintenance status page/API.
- CLI command recommendations.
- Audit when maintenance checks are run.

Acceptance criteria:

- Admin can see update/reboot/config drift state.
- Browser cannot execute arbitrary system commands.
- Suggested commands are copyable and explicit.

## Milestone 14: API Contract and Automation Surface

Objective: Make automation stable and documented.

Internal work:

- Define API resources for domains, mailboxes, aliases, users, DNS, jobs, health, backups, certs, logs, audit, settings.
- Add auth model: staff session, API tokens, scoped permissions.
- Add typed serializers and stable error envelope.
- Add idempotency for unsafe actions.
- Add OpenAPI docs.
- Ensure UI and API share services.

Deliverables:

- API implementation and docs.
- Contract tests.
- API token lifecycle UI.

Acceptance criteria:

- Common admin tasks can be automated without HTML scraping.
- Unsafe API calls are authenticated, authorized, audited, and idempotent where needed.

## Milestone 15: Provisioning and Deployment Hardening

Objective: Make fresh installs deterministic and repeatable.

Internal work:

- Split provisioning into phases: preflight, env generation, secret generation, image build/pull, DB migrate, config render, service start, verification.
- Add preflight checks: OS, RAM, disk, ports, DNS, Docker, IPv4, port 25, hostname, root permissions.
- Make scripts idempotent and resumable.
- Make generated secrets and keys explicit artifacts.
- Remove committed runtime secrets/keys from repo if present and add guardrails.
- Add dry-run and non-interactive CI mode.

Deliverables:

- Provisioning phase state file.
- Preflight report.
- Idempotency tests for scripts where practical.
- Hardened `.gitignore` and secret checks.

Acceptance criteria:

- Re-running provision does not destroy working mail data.
- Failed phase can resume or clearly instruct rollback.
- Runtime secrets are not committed.

## Milestone 16: UI Remediation Against Real Internal State

Objective: Make every UI screen a truthful view of the internal organs.

Internal work:

- Replace inline styles with component classes.
- Bind every dashboard/log/DNS/users/spam/branding/setup value to service data or explicit unavailable state.
- Add action-state components: idle, pending, success, validation error, permission error, system failure.
- Add job progress UI for long operations.
- Add stale-data indicators for monitoring.
- Add compact no-shadow visual standard.

Deliverables:

- Updated templates and CSS.
- Per-page data-source annotations.
- Completion of `docs/FRONTEND-UI-UX-TEST-PLAN.md`.

Acceptance criteria:

- No UI lies about system state.
- No action disappears into silence.
- Every screen works at target viewports.

## Milestone 17: Migration, Import, and Disaster Recovery

Objective: Let users arrive, recover, and leave safely.

Internal work:

- Add import parsers for domains, mailboxes, aliases, users.
- Add dry-run validation with row-level errors.
- Add migration transaction strategy and rollback.
- Add export artifacts aligned with import.
- Document restore from backup and partial restore boundaries.
- Add disaster recovery checklist generated from actual appliance state.

Deliverables:

- `MigrationService`.
- Import/export UI/API.
- DR runbook.

Acceptance criteria:

- Import dry-run catches duplicates, invalid domains, alias loops, and missing dependencies.
- Failed import does not partially corrupt state.
- Backup artifacts map to documented restore steps.

## Milestone 18: End-to-End Certification Harness

Objective: Prove the internal organs work together.

Internal work:

- Build a certification suite that runs against a fresh environment.
- Test phases:
  - Bootstrap/provision.
  - Setup wizard.
  - Domain creation.
  - DNS expected/export/verify.
  - DKIM key generation and Rspamd config render.
  - Mailbox/user/alias lifecycle.
  - Postfix lookup.
  - Dovecot auth lookup.
  - SMTP submission.
  - Inbound delivery.
  - IMAP login.
  - Autoconfig XML.
  - TLS issuance or self-signed fallback.
  - Backup and restore test.
  - Monitoring ingest.
  - Audit/log correlation.
  - Notification trigger and recovery.
- Produce a release certification report.

Deliverables:

- E2E scripts or test suite.
- Certification report template.
- CI/nightly mode for non-destructive checks.

Acceptance criteria:

- A fresh install reaches working mail without developer intervention.
- Failures identify the broken internal subsystem.
- Release decision is based on evidence, not screenshots.

## Execution Matrix

This matrix turns each milestone into implementation workstreams. The names are intentionally concrete so engineers can open the repo and know where to begin.

| Milestone | Core modules | Services | Jobs/commands | Evidence |
| --- | --- | --- | --- | --- |
| 0 Internal map | `backend/apps/*`, `backend/services`, `provisioning/*` | n/a | inventory script | `INTERNAL-SYSTEMS-MAP.md`, current-state matrix |
| 1 Appliance state | `backend/apps/core` or dedicated core app | `ApplianceStateService`, `SystemSettingService`, `HealthStateService` | state consistency check | migrations, service tests, dashboard source map |
| 2 Config rendering | `backend/apps/core/config` or `backend/services/config` | `ConfigRenderService`, `ConfigApplyService` | `render_configs --dry-run`, `render_configs --apply` | rendered diff, validation output, rollback test |
| 3 Job runner | `backend/apps/core/jobs` | `JobService`, `SystemCommandService` | job worker, job cleanup | job lifecycle tests, redaction tests |
| 4 Setup state machine | `backend/apps/accounts/views/setup.py`, setup services | `SetupService` | setup verification job | restart/resume test, transition tests |
| 5 Mail identity core | `backend/apps/domains`, `backend/apps/mail`, `backend/apps/accounts` | `DomainLifecycleService`, `MailboxService`, `AliasService`, `UserLifecycleService` | config render trigger | Postfix/Dovecot lookup tests |
| 6 DNS source of truth | `backend/apps/dns` | `DNSRecordService`, `DNSVerificationService`, provider adapters | DNS verify/sync jobs | expected/provider/observed record tests |
| 7 Deliverability | `backend/services/deliverability.py` | `DeliverabilityService` | deliverability scan job | send-ready/receive-ready report |
| 8 TLS lifecycle | certificate service module, provisioning certbot hooks | `CertificateService` | cert scan, issue, renew, import jobs | socket/cert filesystem verification |
| 9 Backups | backup service module, scripts | `BackupService`, `RestoreTestService` | backup, restore-test, retention jobs | manifest/checksum/restore evidence |
| 10 Observability | `backend/services/monitoring.py`, logs/audit services | `MonitoringIngestService`, `LogService`, `AuditQueryService` | monitor ingest job | correlation trace from UI action to audit/log |
| 11 Security | accounts/security module | `AdminSecurityService`, `SessionService` | recovery code cleanup | TOTP enrollment/recovery/session tests |
| 12 Notifications | notification module | `NotificationService` | alert dispatch/recovery job | dedupe and recovery notification tests |
| 13 Maintenance | maintenance module | `VersionService`, `MaintenanceStatusService` | update check, drift check | read-only maintenance status report |
| 14 API | app `api.py`, serializers, viewsets | existing services reused | token rotation job if needed | OpenAPI/contract tests |
| 15 Provisioning | `provisioning/scripts/*` | provisioning adapter if surfaced in UI | preflight, phase runner | idempotency and resume evidence |
| 16 UI remediation | `frontend/templates`, `frontend/static` | service-backed contexts | job polling where needed | frontend QA packet |
| 17 Migration/DR | migration service module | `MigrationService`, `DisasterRecoveryService` | import dry-run/apply | dry-run row errors, rollback test |
| 18 Certification | `tests/e2e` or `provisioning/tests` | all services | certification runner | release certification report |

## Entity Model Targets

These are the entity targets the remediation should converge toward. Exact app placement can change, but each concept needs an owner.

### Appliance and Settings

- `ApplianceState`: singleton-ish install state, setup phase, version, mail hostname, public hostname, install id.
- `SystemSetting`: typed setting with scope, default, secrecy flag, validation rule, last changed by.
- `ConfigArtifact`: rendered file path, template version, checksum, target service, applied status.
- `ConfigApplyRun`: diff summary, validation result, reload result, rollback pointer.

### Jobs and Health

- `JobRun`: kind, status, lock key, idempotency key, actor, input hash, redacted output, error code.
- `HealthCheckResult`: check id, entity type/id, status, severity, expected, observed, remediation, stale after.
- `MetricSample`: metric name, entity, value, unit, sampled at, retention class.

### Mail Core

- `Domain`: name, active state, DNS mode, mail enabled, DKIM state, TLS state.
- `Mailbox`: address, domain, local part, storage path, quota, active state, password hash version.
- `Alias`: source address, destination list, active state, loop-check metadata.
- `DKIMKey`: selector, domain, key path/reference, public record, status, rotation state.

### DNS

- `DNSProviderConfig`: provider, credential reference, capabilities, status, last sync.
- `DNSRecord`: type, name, value, ttl, priority, purpose, source, expected/generated/custom flag.
- `DNSCheckResult`: resolver, observed values, matched, reason, last checked.
- `DNSChangePlan`: proposed changes, dry-run output, provider response, verification state.

### TLS

- `CertificateState`: domain, source, paths, issuer, serial, SANs, not before, not after, status.
- `CertificateRun`: issue/renew/import action, challenge type, result, rollback pointer.

### Backup and Recovery

- `BackupTarget`: local/rsync/S3-compatible target, encrypted flag, retention, validation state.
- `BackupRun`: target, archive, size, manifest, checksum status, encryption status, component statuses.
- `RestoreTestRun`: backup reference, DB result, mail result, config result, DKIM result, TLS result.

### Security and Notification

- `TOTPDevice` or equivalent: user, confirmed state, last used counter/time.
- `RecoveryCode`: user, hashed code, used state.
- `NotificationPreference`: event class, channel, enabled, severity threshold.
- `NotificationEvent`: trigger, dedupe key, send status, recovery status.

## Service Contract Pattern

Each service should expose a predictable shape:

```python
class ExampleService:
    def plan(self, actor, input) -> PlanResult:
        ...

    def apply(self, actor, plan_id, idempotency_key=None) -> ApplyResult:
        ...

    def verify(self, actor, entity_id) -> VerificationResult:
        ...

    def rollback(self, actor, run_id) -> RollbackResult:
        ...
```

Required service behavior:

- Validate all inputs before mutation.
- Return typed results, not mixed dictionaries unless wrapped in typed structures.
- Raise typed domain errors for validation, permission, conflict, dependency, external provider, and system execution failures.
- Audit all mutations.
- Update health state when the mutation affects operational readiness.
- Avoid direct model access from views except through the service layer.

## Failure Mode Catalog

The remediation must explicitly handle these failure modes.

### Setup

- Domain typo.
- Private or wrong public IP.
- Port 25 blocked.
- Admin account already exists.
- Setup interrupted after domain creation but before mailbox creation.
- DKIM key generated but DNS records not created.

### DNS

- Provider credentials invalid.
- Provider supports records but not the needed operation.
- Provider applies record but public resolver has not propagated.
- DKIM TXT exceeds record constraints.
- Existing custom DNS record conflicts with generated mail record.
- DNSSEC enabled at registrar but broken in zone.

### Mail Core

- Mailbox local part invalid.
- Alias loop or circular forwarding.
- Domain delete while mailboxes exist.
- Dovecot hash scheme mismatch.
- Postfix lookup sees stale data.
- Maildir path missing or wrong ownership.

### TLS

- ACME challenge fails.
- Certificate issued for wrong SANs.
- Imported key does not match certificate.
- Renewal succeeds but service reload fails.
- Mail services still serve old certificate.

### Backup

- DKIM keys missing.
- Database dump fails.
- Mail volume unavailable.
- Archive encryption fails.
- S3/rsync target unreachable.
- Restore test cannot decrypt.

### Monitoring

- Monitor data stale.
- Redis unavailable.
- Log parser cannot parse expected format.
- Service status check times out.
- Queue count command fails.

### Security

- Lost 2FA device.
- Recovery codes exhausted.
- Staff enforcement locks out last admin.
- Session revocation fails.
- API token leaked or over-scoped.

## Test Ladder

Use this ladder for every milestone.

1. **Unit tests:** pure validators, parsers, renderers, record builders.
2. **Service tests:** database state transitions and transaction behavior.
3. **Adapter tests:** mocked provider/system command behavior.
4. **View/API tests:** permissions, CSRF, form/API errors, response contracts.
5. **Job tests:** lock, idempotency, retry, timeout, success/failure output.
6. **Config tests:** render, validate, diff, apply simulation, rollback.
7. **Provisioning tests:** preflight, idempotency, resume, secret guardrails.
8. **End-to-end tests:** fresh setup through SMTP/IMAP/autoconfig/backup/monitoring.

## Unmatched Experience Layer

The "unmatched" experience is the layer that turns internal complexity into confidence.

For every major object, the UI should show:

- **Readiness:** ready, needs attention, blocked, pending, unknown, stale.
- **Evidence:** the measured fact behind the status.
- **Impact:** what breaks if ignored.
- **Action:** the next safe action.
- **Automation:** whether ifinmail can fix it, guide it, or only verify it.
- **History:** when it changed and who/what changed it.

Examples:

- DNS row: "DKIM record missing. Outbound mail may fail authentication. Copy this record or sync with Cloudflare. Last checked 3 minutes ago."
- Backup card: "Latest encrypted backup is 31 hours old. Restore test has never passed. Run restore test."
- TLS card: "Certificate expires in 12 days. Renewal failed because HTTP challenge could not reach `mail.example.com`."
- Mailbox row: "Mailbox active. Dovecot auth verified 5 minutes ago. Last successful IMAP login yesterday."

## Release Readiness Scorecard

Before calling the project production ready, produce a scorecard with these sections:

- Setup completion: pass/fail/evidence.
- DNS readiness: pass/fail/evidence.
- Mail send/receive: pass/fail/evidence.
- IMAP/SMTP auth: pass/fail/evidence.
- TLS readiness: pass/fail/evidence.
- Deliverability readiness: pass/fail/evidence.
- Backup and restore confidence: pass/fail/evidence.
- Monitoring freshness: pass/fail/evidence.
- Audit coverage: pass/fail/evidence.
- Security controls: pass/fail/evidence.
- UI compactness/accessibility: pass/fail/evidence.
- API automation: pass/fail/evidence.
- Known risks and release decision.

## Suggested Build Order

1. Internal systems map.
2. Appliance state model.
3. Job runner and safe system adapter.
4. Configuration rendering engine.
5. First-run setup state machine.
6. Domain/mailbox/alias/user core.
7. DNS source of truth.
8. Deliverability engine.
9. TLS lifecycle.
10. Backup/restore internals.
11. Monitoring/logs/audit pipeline.
12. Admin security and 2FA.
13. Notification engine.
14. Safe maintenance.
15. API contract.
16. Provisioning hardening.
17. UI remediation against real state.
18. Migration/import/recovery.
19. End-to-end certification harness.
