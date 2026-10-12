# ifinmail Enterprise Readiness Plan — Status and Roadmap

**Status:** Revised plan (revision 2, 2026-10-12) · **Release assessed:** v0.0.1 (`main`)
**Rating:** 2.6/5 today (was stated as 2.2/5 on 2026-10-11) · **Target:** 4/5 "enterprise-pilotable"
**Companion docs:** `docs/enterprise-slo.md` (objectives), `docs/REMEDIATION-MILESTONES.md` (engineering standard), `README.md` (operations baseline)

> **How to read this document.** The first version was a proposal written against a baseline that
> has since moved: MFA, roles, API tokens, session policy and CI all shipped. This revision
> re-checks every claim against the code, marks each work item **Done / Partial / Open**, and
> adds the gaps the first version did not see. Where the code and an earlier claim disagree, the
> code wins and the disagreement is listed in §3.

---

## 1. What "enterprise-ready" means here (definition of done)

An enterprise customer, or their security review, can answer **yes** to all six. Status is
measured against the code, not against intent.

| # | Requirement | Status | Why |
|---|---|---|---|
| 1 | **Identity** — admin MFA enforced; workforce SSO (OIDC); idle and absolute session timeouts; least-privilege roles | **Partial** | TOTP, 12 h absolute / 30 min idle timeouts and three roles ship. MFA is *offered, not enforced*: enrollment can be snoozed a week and a user can switch it off with a code. No SSO. |
| 2 | **Data** — backups encrypted, off-site, restore-tested on a schedule; RPO/RTO measured | **Partial** | Encrypted, broad scope, weekly restore test. No off-site copy, no key escrow, RPO/RTO never measured. |
| 3 | **Availability** — known failure modes, observable health, recovery is a runbook | **Partial** | Health tiers and safe update/rollback exist. Single host; no runbook; no rebuild drill. |
| 4 | **Security** — pinned and scanned dependencies, CI gates merges, CSP enforced, secrets managed | **Partial** | CI with `pip-audit`, secret scan, lint, shellcheck. CSP still report-only; lockfile unhashed; no automated dependency updates. |
| 5 | **Governance** — privileged actions audited in a tamper-evident, exportable trail; one retention policy | **Open** | Audit trail is capped at 10,000 rows, mutable, CSV-only export. Retention is not time-based. |
| 6 | **Operability** — safe, repeatable upgrades; on-call knows what pages and what to do | **Partial** | `make update`/`rollback`/`uninstall` with database snapshots are proven. No runbooks or on-call guidance. |

**Out of scope (explicit):** built-in webmail, multi-region active/active HA, and the compliance
audits themselves (SOC 2 / ISO 27001 / FedRAMP). Those are post-pilot options.

### Assumptions

- A small team (1–4 engineers) and a security reviewer who may be external and part-time.
- The topology stays **single VPS, Docker Compose**: hardened, not replaced.
- Each item follows the **Milestone Completion Packet** standard (`REMEDIATION-MILESTONES.md:23-39`).
  No packet, not done.

---

## 2. Where we are (re-scored)

Scores use a fixed rubric so they can be re-measured rather than argued:

| Score | Meaning |
|---|---|
| 1 | Absent |
| 2 | Exists, but a known gap defeats the control |
| 3 | Works as built on a single host; enforcement or evidence still open |
| 4 | Evidenced: tested, measured, exportable, reviewed |
| 5 | Independently audited |

| Pillar | 2026-10-11 | Now | Evidence |
|---|---|---|---|
| Identity & Access | 2 | **3** | TOTP + recovery codes (`services/mfa.py`), `Role` model with Owner / Administrator / Support, scoped hashed API tokens, session list with revoke. Not enforced; no SSO; no step-up re-auth. |
| Data Protection | 2 | **2** | GPG-encrypted backups of Postgres, mail, DKIM, certs, DNSSEC keys, calendars, runtime state, queue spool and Rspamd data. **No off-site copy; decryption key lives only on the host.** |
| Availability & DR | 2 | **2** | Health tiers, backup-age alert, snapshot-before-update and automatic rollback. Single host, no runbook, RTO unmeasured. |
| Scalability | 2 | **2** | Vertical headroom only; no horizontal path. Acceptable for pilot. |
| Observability | 3 | **3** | Telemetry with PII scrub, correlation IDs, health tiers, webhook alerts. No metrics endpoint, no OpenTelemetry. |
| Application security | 3 | **3** | HSTS one year, session cookie policy, `check --deploy` in CI. CSP report-only; lockfile has no hashes. |
| Governance | 2 | **2** | Audit events exist but are count-capped and mutable (see §3, finding F1). |
| Operability & quality | 3 | **4** | CI gates, ~720 tests, idempotent provisioning, proven update / rollback / uninstall. Runbooks missing. |

**Average: 2.6.** The first version stated 2.2, but its own table averaged 2.4; the rubric above
removes that ambiguity.

**One sentence:** the product is *operationally honest and now meaningfully access-controlled*,
but it is still *structurally fragile* (one host, one disk, no off-site copy) and its audit trail
would not survive an incident review.

---

## 3. Findings: what the code says versus what was claimed

Severity is judged against the §1 definition of done.

| ID | Sev. | Finding | Evidence | Fix (item) |
|---|---|---|---|---|
| F1 | **High** | **The audit trail is capped at 10,000 rows**, oldest deleted first, by the application itself. A login flood can evict the evidence you need. It also contradicts the "30 days everywhere" statement in `enterprise-slo.md`. | `core/platform/services/audit.py:39,220`; model docstring | G.3 |
| F2 | **High** | **MFA is not enforced.** Enrollment can be snoozed for a week, and `disable_second_factor` turns it off with a valid code. Fails requirement 1 as written. | `accounts/services/mfa.py:200`; `tests/test_mfa_optional.py` | A.6 |
| F3 | **High** | **No off-site backup.** A disk or host loss still destroys data *and* backups. The original risk register rated this Critical. | no off-site code in `provisioning/`, README or `.env.example` | B.1 |
| F4 | **High** | **Backup decryption key is host-local.** The GPG key and its passphrase are generated on the server and the passphrase is appended to `.env`, which is itself inside the backup. After host loss the backups cannot be opened unless the key was exported separately. | `provision.sh:266-300`; `backup_full.sh:72-73` | B.6 |
| F5 | Med | Audit rows are not append-only, hash-chained or exportable beyond CSV; no SIEM schema. | `AuditEvent` model; `views/logs.py:135` | G.3 |
| F6 | Med | CSP defaults to report-only; no soak data recorded. | `settings/production.py:85` | C.1 |
| F7 | Med | Token expiry allows up to 365 days; policy said 90. | `forms/mailboxes.py:119`, `services/tokens.py:88` | E.2 |
| F8 | Med | **DKIM private keys are stored in plaintext** in the database and on disk (Rspamd needs the file). Compliance map claimed "secrets encrypted at rest". | `domains/models/__init__.py:33` | B.7 |
| F9 | Med | `requirements/prod.lock` is pinned but has **no hashes**; automated dependency updates are no longer configured (`.github/dependabot.yml` is absent). | `prod.lock`; repo tree | D.2 |
| F10 | Med | No step-up re-authentication for high-risk actions (role grant, token create, mailbox delete). | no matches in `backend/` | F.1 |
| F11 | Med | **Referenced deliverables do not exist:** `docs/dr-runbook.md`, `docs/risk-register.md`, `docs/enterprise-evidence/`. RTO ≤ 4 h is therefore an assertion. | repo tree | B.4, B.5, 0.3, G.5 |
| F12 | Low | Four `test_quota_budget` tests fail in the local test container. CI is stated to block red merges, so confirm whether CI is green or the gate is not enforced. | pytest run 2026-10-12: 715 passed, 4 failed, 4 skipped | 0.1 |
| F13 | Low | `enterprise-slo.md` states audit retention is 30 days and cites a runbook that does not exist. | `docs/enterprise-slo.md` | update with F1, F11 |
| F14 | **High** | **Any `system.manage` user can erase the audit trail** down to 500 rows from the dashboard "log purge" action; the purge is recorded only after the evidence is gone. | `views/dashboard.py` `dashboard_log_purge`; `AuditService.purge_keeping` | G.3 |
| F15 | Med | **The audit "export" was not an export:** it read a 200-event in-memory buffer that differs per worker process, so the CSV omitted most of the trail. | `views/logs.py` `logs_export` | G.3 |

**Fixed in this release (2026-10-12):** the console's own email (mailbox setup links, registration
verification) was silently failing because the app tried to send from a mail server inside its own
container. System email now goes through an internal-only Postfix port (10025) that is never
published and accepts only the Docker network. A contract test guards this.

---

## 4. Work-item status

### Phase 0 — Assess and baseline

| # | Item | Status | Notes |
|---|---|---|---|
| 0.1 | Freeze baseline metrics | **Open** | Record test pass rate and duration, `pip-audit` count, backup size and duration, full-rebuild time. Resolve F12 first. |
| 0.2 | Adopt SLO sheet | **Done** | `docs/enterprise-slo.md`; correct F13. |
| 0.3 | Risk register | **Open** | `docs/risk-register.md` missing (F11). |
| 0.4 | Retention unification | **Partial** | Telemetry and backups are 30 d in `.env.example`. Audit is count-capped, not time-based (F1). |
| 0.5 | Landing-page honesty | **Done** | MFA now exists; the landing template makes no unsupported MFA claim. |

### Workstream A — Multi-factor authentication

| # | Item | Status | Notes |
|---|---|---|---|
| A.1 | TOTP device model | **Done** | Fernet-encrypted secrets, recovery codes. |
| A.2 | Enrollment UX | **Done** | QR code, verification, recovery codes shown once. |
| A.3 | Login enforcement and rate limit | **Partial** | Enrolled users must present a code; attempts are rate-limited and audited. Enrollment itself is optional (F2). |
| A.4 | Session binding | **Done** | `mfa_verified_at` held in session. |
| A.5 | Tests | **Done** | `test_mfa.py`, `test_mfa_optional.py`, `test_mfa_qr.py`. |
| A.6 | **Enforcement policy (new)** | **Open** | Setting "require MFA for staff": removes snooze and self-disable when on, with a documented two-person break-glass path. |

### Workstream B — Backups and recovery

| # | Item | Status | Notes |
|---|---|---|---|
| B.1 | Off-site copy | **Open** | Nightly push of the encrypted archive to an S3-compatible or SSH target; credentials in env; failure alerts through `BACKUP_NOTIFY_URL`. **Do first.** |
| B.2 | Backup scope | **Done** | Postgres, mail, DKIM, certs, DNSSEC, DAV, runtime, queue spool, Rspamd data. |
| B.3 | Scheduled restore test | **Partial** | Weekly cron installed (`provision.sh:460`); backup age shown in System health. Extend assertions to DKIM count, DS presence, cert archive. |
| B.4 | Full rebuild drill | **Open** | Fresh VPS to working mail; measure RTO; repeat until ≤ 4 h. |
| B.5 | DR runbook | **Open** | `docs/dr-runbook.md` (F11). |
| B.6 | **Backup key escrow (new)** | **Open** | Export the key pair and passphrase to an off-host secret store at provision time; add a restore test that decrypts using only the escrowed copy (F4). |
| B.7 | **Secrets-at-rest map (new)** | **Open** | Inventory every secret (DKIM, DNS provider tokens, TOTP, API tokens, backup key), state its protection, and encrypt the DB-held ones or record a waiver (F8). |

### Workstream C — Quick security wins

| # | Item | Status | Notes |
|---|---|---|---|
| C.1 | HSTS one year; CSP enforce | **Partial** | HSTS done. CSP still report-only by default; run a one-week soak on `/csp-report/` data, then flip (F6). |
| C.2 | Session baseline | **Done** | 12 h absolute, 30 min idle, `SameSite=Lax`, expire at browser close. |

### Workstream D — CI and supply chain

| # | Item | Status | Notes |
|---|---|---|---|
| D.1 | CI pipeline | **Done** | `ci.yml`: `check --deploy`, pytest with 70 % coverage gate, `pip-audit`, ruff, gitleaks, shellcheck, compose validation. Verify branch protection requires it. |
| D.2 | Pin, hash, update | **Partial** | Pinned via `pip-compile`; add `--generate-hashes`; restore automated updates (Renovate, a scheduled CI job, or a documented weekly manual review) and publish the CVE SLA (F9). |
| D.3 | Image hygiene | **Partial** | `make reload` and unattended OS updates exist; base-image refresh cadence not documented. |

### Workstream E — Authorization

| # | Item | Status | Notes |
|---|---|---|---|
| E.1 | Roles | **Done** | Owner, Administrator, Support; nine permission codes; legacy staff mapped. **Open:** domain-scoped roles (§5). |
| E.2 | API tokens | **Partial** | Hashed, scoped (role and setup administration excluded), expiring, rotate and revoke. Cap expiry at 90 days (F7); confirm input schemas. |
| E.3 | Credential-lifecycle audit | **Partial** | Role assignment, invite issued/accepted/sent, session revoke, MFA events are audited. Needs a checked list covering every row in the original acceptance criteria. |

### Workstream F — Session control

| # | Item | Status | Notes |
|---|---|---|---|
| F.1 | Idle, absolute, step-up | **Partial** | Timeouts done. Step-up re-auth for role grant, token create, mailbox delete missing (F10). |
| F.2 | Session inventory | **Done** | Per-profile session list, per-session and revoke-all, audited. |
| F.3 | SSO / OIDC | **Open** | Only a design note exists in `types/permissions.py`: IdP claims will map onto local roles and enforcement never reads the IdP. |

### Workstream G — Prove it

| # | Item | Status | Notes |
|---|---|---|---|
| G.1 | RTO/RPO measurement | **Open** | Four weekly restore tests plus one unannounced runbook-only drill. |
| G.2 | Lightweight pen test | **Open** | Auth, session, invite-token, DNS/DKIM, headers, backup crypto. Budget externally. |
| G.3 | Audit export and retention | **Open — priority** | Time-based purge (replacing the row cap); JSONL export with documented schema read from the database; append-only control (hash chain); the dashboard purge limited to expired rows (F1, F5, F14, F15). |
| G.4 | Observability uplift | **Open** | JSON log formatter, Prometheus `/metrics` (backup age, queue depth, cert days, probe status), alert thresholds mapped to SLOs. |
| G.5 | Evidence pack | **Open** | Architecture and data-flow, secrets map (B.7), RTO/RPO data, pen-test report, CI history, role matrix. |

---

## 5. Gaps the first version did not cover (mail-specific)

For a *mail server* these are the questions a procurement review asks after MFA and backups.

| # | Requirement | Current state | Proposed |
|---|---|---|---|
| M1 | **Mail retention, legal hold, archiving** | Retention policy covers telemetry, audit and backups, never the mail itself. | Per-domain retention setting; legal-hold flag that blocks deletion; documented archive export. |
| M2 | **Erasure on request** | Deleting a mailbox leaves its mail on disk (the console mounts the mail volume read-only). | Admin-initiated, audited purge job with a grace period, run by a component that can write the volume. |
| M3 | **Domain-scoped administration** | Roles are global. | Role assignments carry a domain scope; Support and Administrator roles honour it. |
| M4 | **Directory sync (SCIM / LDAP)** | JIT provisioning only (planned); no leaver handling. | SCIM v2 users endpoint behind a scoped token; deprovision disables the mailbox and revokes sessions and tokens. |
| M5 | **Outbound abuse containment** | No per-mailbox send-rate limits or compromised-account detection. | Per-mailbox hourly/daily caps, auto-suspend on anomaly, alert to the owner role. One stolen password otherwise burns the server's IP reputation. |
| M6 | **Transport security policy** | DNSSEC is already in place. | Publish MTA-STS and TLS-RPT; DANE (TLSA) records; ingest DMARC aggregate reports into System health. |
| M7 | **Disclosure and supply chain** | None. | `SECURITY.md` with contact and response times; SBOM per release; sign release images. |
| M8 | **Break-glass recovery** | Mentioned as a risk, no procedure. | Documented offline Owner recovery with a two-person rule and mandatory audit entry. |

---

## 6. Roadmap (re-planned from current state)

```
Phase 1  Close what is built     (2–3 wks)  → audit trail, MFA enforced, off-site + key escrow, CSP, token cap
Phase 2  Prove it                (3–4 wks)  → runbook, measured RTO/RPO, risk register, metrics, pen test, evidence pack
Phase 3  Mail-grade enterprise   (4–6 wks)  → OIDC, domain-scoped roles, MTA-STS/DANE, retention and erasure, send limits
Phase 4  Operate                 (continuous)
```

Each phase keeps the original rule: it does not start until the previous phase's exit criteria
are signed off by the accountable owner.

### Phase 1 — Close what is built

**Entry:** this revision accepted. **Exit:** F1–F4, F6, F7, F9, F10, F14, F15 closed; rating ≥ 3.0.

| Order | Item | Reason for the order |
|---|---|---|
| 1 | G.3 audit retention + export + append-only | Every other control is only as credible as the log. |
| 2 | B.1 + B.6 off-site backup and key escrow | Removes the critical single-host loss risk; one without the other is useless. |
| 3 | A.6 MFA enforcement policy | Makes requirement 1 literally true. |
| 4 | C.1 CSP enforce, D.2 hashes + update automation, E.2 token cap, F.1 step-up | Small, independent changes. |
| 5 | 0.1 baseline + F12 | Settles whether CI really gates merges. |

**Exit demo:** trigger a login flood and show the earlier privileged events still present;
destroy a scratch host and restore from the off-site copy using only the escrowed key; show a
staff login refusing to proceed without enrolled MFA.

### Phase 2 — Prove it

**Entry:** Phase 1 exit. **Exit:** F11 closed; four consecutive weekly restore tests green; one
runbook-only drill inside the published RTO; criticals and highs from the pen test fixed and
retested; rating ≥ 3.5.

Items: B.3, B.4, B.5, 0.3, G.1, G.2, G.4, G.5, B.7.

### Phase 3 — Mail-grade enterprise

**Entry:** Phase 2 exit. **Exit:** one pilot customer integrated through OIDC with domain-scoped
roles; MTA-STS/TLS-RPT live; retention and erasure demonstrable; rating ≥ 4.0.

Items: F.3 (OIDC first, SAML only on signed customer demand), E.1 domain scope (M3), M1, M2, M4,
M5, M6, M7, M8.

### Phase 4 — Operate

A cadence, not a project. Each line needs a named owner and a calendar entry or it will rot.

| Cadence | Item |
|---|---|
| Weekly | Dependency scan review; restore-test result review |
| Monthly | Base-image refresh; access review (roles, tokens, staff); off-site copy integrity spot-check |
| Quarterly | DR drill by a rotating engineer using only the runbook; secrets rotation (backup key, DNS provider tokens, OIDC); SLO review |
| Per release | Completion packet; auth/session regression test; retention verification |
| Annual | Access recertification; architecture revisit (managed Postgres, object-store mail); compliance mapping refresh |

---

## 7. Risks and mitigations

| Risk | Likelihood / Impact | Mitigation |
|---|---|---|
| Host or disk loss before B.1 and B.6 land | Med / **Critical** | Do B.1 and B.6 together first; until then, a documented manual copy of backups *and* the key to an off-host location. |
| Evidence evicted from the audit trail during an incident | **High** / High | G.3 first; interim: raise the row cap and export daily. |
| MFA enforcement locks out the only Owner | Med / High | Recovery codes, break-glass (M8), and enforcement staged: warn, then require for new staff, then all staff. |
| Backups exist but cannot be decrypted | Med / **Critical** | B.6 plus a restore test that uses only the escrowed key. |
| Dependency CVE lands unnoticed (updates now manual) | Med / High | D.2: restore automation or a calendared weekly review with a recorded owner. |
| Scope creep into HA / multi-region | Med / Med | Explicit out-of-scope list (§1). |
| Tests fail locally but CI reports green | Low / High | F12 resolved in Phase 1; branch protection verified. |

---

## 8. Effort sketch (planning aid, not a quote)

In engineer-weeks, assuming two engineers who know the codebase:

- Phase 1: 2–3 (audit ~1, backups + escrow ~1, MFA policy ~0.5, small items ~0.5)
- Phase 2: 3–4 (drills and runbook ~1.5, metrics ~1, pen-test fixes ~1–1.5); external pen test budgeted separately
- Phase 3: 4–6 (OIDC ~1.5, domain scope ~1, retention/erasure ~1.5, transport policy ~0.5, send limits ~1)
- Contingency: +20 %. Single-host surprises are the norm.

---

## 9. Compliance mapping (SOC 2-oriented, lightweight)

| Criterion | Covered by | Status |
|---|---|---|
| CC6.1 logical access | MFA (A), roles (E.1), sessions (C.2, F) | Partial — enforcement (A.6), step-up (F.1) |
| CC6.2 credentials | Invite flow, password validators, token expiry (E.2) | Partial — token cap, rotation policy |
| CC6.3 encryption | TLS/HSTS, GPG backups, TOTP secrets | Partial — DKIM keys plaintext (F8), key escrow (F4) |
| CC7.2 monitoring | Health tiers, telemetry, webhooks, metrics (G.4) | Partial — no metrics endpoint |
| CC7.3 incidents | Audit trail and export (G.3), runbook (B.5) | Open — F1, F11 |
| CC8.1 change management | CI gates (D.1), completion packets, update/rollback | Partial — verify branch protection |
| A1 availability | SLOs, backups, restore tests, DR drill | Partial — RTO/RPO unmeasured |
| C1 confidentiality | Encryption, retention (M1), erasure (M2) | Open |

SOC 2 requires an independent auditor and an observation period. Until one is engaged, treat
this table as readiness tracking, not a claim.

---

## 10. Decision log

| Date | Decision | Status | By | Rationale |
|---|---|---|---|---|
| 2026-10-11 | Retention 30 days for telemetry, audit and backups | Adopted in SLO doc; **not implemented for audit** (F1) | TBD | Single policy; fix 7-vs-30 mismatch |
| 2026-10-11 | RPO ≤ 24 h, RTO ≤ 4 h interim | Adopted; **unmeasured** | TBD | Daily backups plus manual rebuild |
| — | Require MFA for staff (A.6) | **Open — recommended** | TBD | Required by §1 requirement 1 |
| — | Automated dependency updates: Renovate / scheduled job / manual cadence | **Open** | TBD | Config removed from repo (F9) |
| — | OIDC before SAML | Proposed | TBD | Broader IdP coverage; SAML on signed demand |
| — | Single host retained through pilot | Proposed | TBD | Cost and simplicity; revisit in Phase 4 annual review |

---

## Appendix — Revision notes

**Revision 2 (2026-10-12)** changes against the 2026-10-11 proposal:

- Re-scored every pillar against the code using a fixed rubric (§2); corrected the stated
  baseline average (2.2 → 2.4 under the original scores).
- Marked all work items Done / Partial / Open with evidence (§4).
- Added findings F1–F15, notably the 10,000-row audit cap, the dashboard purge that can erase the
  trail, optional MFA, the host-local backup key and missing deliverables (§3).
- Added items A.6, B.6, B.7 and the mail-specific requirements M1–M8 (§5).
- Replaced the calendar-week phases with a roadmap from the current state (§6).
- Recorded the system-email fix shipped on 2026-10-12.

**Follow-ups outside this file:** correct `docs/enterprise-slo.md` (F13) and remove the
"30 days everywhere" audit claim until G.3 ships.
