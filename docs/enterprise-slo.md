# Enterprise SLOs

Source of truth for service objectives referenced by CI (`ci.yml:45`) and the
enterprise-readiness proposal Phase 0.2. Interim values — tighten after 4 weeks
of measured restore drills (proposal §G.1).

## Objectives

| Signal | Objective | Alert |
|---|---|---|
| Console availability (single host, stated honestly) | ≥ 99.5% monthly | nginx/API healthcheck failing > 5 min |
| RPO (daily encrypted backup) | ≤ 24h | backup age > 25h = CRITICAL (`monitor.py`); System health warns at 30h, errors at 72h |
| Off-site copy | verified copy ≤ 30h old | System health "Off-site backup"; `failed` is an error |
| Backup key | exported and proven | System health "Backup key" warns until `make backup-key` is run |
| RTO (manual rebuild via `docs/dr-runbook.md`) | ≤ 4h | **target, not yet measured**: rebuild drill G.1 has not run |
| Certificate expiry | renew > 30d before expiry | < 30d WARN, < 7d CRITICAL |
| Queue depth (`monitor.py`) | drain < 15 min | > 50 WARN, > 200 CRITICAL |

## Retention

| Data | Kept | Setting | Why |
|---|---|---|---|
| Audit trail | 365 days (minimum 30) | `AUDIT_RETENTION_DAYS` | Low volume, and reviewers expect a year of privileged-action history |
| Telemetry (errors) | 30 days | `TELEMETRY_RETENTION_DAYS` | High volume, diagnostic value fades quickly |
| Backups (local and off-site) | 30 days | `BACKUP_RETENTION_DAYS` | Matches the restore-test cadence and disk budget |

The audit trail is hash-chained and removed only by age, never by row count. The dashboard "log
purge" can only remove entries past retention. `manage.py verify_audit_chain` checks the chain; a
daily job does the same and raises `audit_chain_broken`. The metric `ifinmail_audit_chain_ok`
exposes it.

## Quality gates

* **Lint** — CI `backend` job runs `ruff check backend/` and
  `ruff format --check backend/` as blocking gates (no `continue-on-error`).
  Baseline as of 2026-10-11: **zero**. Every PR must keep both green.
* **Coverage** — CI test step runs `pytest --cov=backend` with
  `fail_under = 70` in `pyproject.toml` (measured 73.6% on 2026-10-11;
  migrations, tests and empty `__init__` omitted). Raise the gate as
  coverage improves.
* **Compose** — CI validates `docker-compose.yml` with `docker compose config`.

## Dependencies

* Production dependencies are pinned with SHA-256 hashes (`requirements/prod.lock`) and installed
  with `--require-hashes`, so a swapped release fails the image build.
* `pip-audit` runs on every change and **weekly** (CI schedule); a failing weekly run is the
  reminder. There is deliberately no automated update bot: one maintainer reviews `make lock` output.
* Fix targets: critical vulnerability ≤ 7 days, high ≤ 30 days, medium at the next release.

## Monitoring

`GET /api/metrics` (Bearer token with the `audit.view` scope) returns Prometheus text: every System
health check as `ifinmail_health_check_status{check,group}` (alert on 2 or more), the audit chain,
and domain and mailbox counts. No client library, no addresses, no secrets.

## Measurement

* Restore tests: weekly `restore_test.sh`; backup age and off-site age are visible in System health
  and as metrics. `backup_offsite.sh verify-key` proves the escrowed key independently.
* Rebuild drill: fresh VPS → `make provision` → `pg_restore` → verify mail flow
  + DNSSEC + console; record wall-clock RTO in `docs/enterprise-evidence/`.
