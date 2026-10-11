# Enterprise SLOs

Source of truth for service objectives referenced by CI (`ci.yml:45`) and the
enterprise-readiness proposal Phase 0.2. Interim values — tighten after 4 weeks
of measured restore drills (proposal §G.1).

## Objectives

| Signal | Objective | Alert |
|---|---|---|
| Console availability (single host, stated honestly) | ≥ 99.5% monthly | nginx/API healthcheck failing > 5 min |
| RPO (daily encrypted backup) | ≤ 24h | backup age > 25h = CRITICAL (`monitor.py`) |
| RTO (manual rebuild via `docs/dr-runbook.md`) | ≤ 4h | rebuild drill exceeding 4h opens P1 |
| Certificate expiry | renew > 30d before expiry | < 30d WARN, < 7d CRITICAL |
| Queue depth (`monitor.py`) | drain < 15 min | > 50 WARN, > 200 CRITICAL |

## Retention (single value)

30 days everywhere: telemetry (`TELEMETRY_RETENTION_DAYS`), audit trail, backups
(`BACKUP_RETENTION_DAYS`). Fixes the 7-vs-30 mismatch noted in the proposal §0.4.

## Quality gates (lint baseline)

CI `backend` job runs `ruff check backend/` and `ruff format --check backend/`
as blocking gates (no `continue-on-error`).
Baseline as of 2026-10-11: **zero** — `ruff check` passes and all files are
formatted. Policy: every PR must keep both gates green.

## Measurement

* Restore tests: weekly `restore_test.sh`, results mailed + visible in console.
* Rebuild drill: fresh VPS → `make provision` → `pg_restore` → verify mail flow
  + DNSSEC + console; record wall-clock RTO in `docs/enterprise-evidence/`.
