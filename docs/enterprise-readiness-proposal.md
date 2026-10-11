# ifinmail Enterprise Readiness Proposal — End to End

**Status:** Proposal · **Baseline rating:** 2.2/5 (Developing) · **Target:** 4/5 (Enterprise-pilotable) in ~120 days
**Companion docs:** `docs/REMEDIATION-MILESTONES.md` (engineering standard), `README.md` (operations baseline)

---

## 1. What "enterprise-ready" means here (definition of done)

An enterprise customer (or their security review) can answer **yes** to all of these:

1. **Identity:** Admin access requires MFA; workforce SSO (OIDC) available; sessions expire on idle + absolute timeouts; least-privilege roles exist.
2. **Data:** Backups are encrypted, off-site, and **restore-tested on a schedule**; stated RPO/RTO are measured, not assumed.
3. **Availability:** Failure modes are known, health is observable, and recovery is a runbook — not an improvisation.
4. **Security:** Dependencies are pinned and scanned, CI gates every merge, CSP enforced, secrets managed with rotation.
5. **Governance:** Every privileged action is audited in a tamper-evident, exportable trail; retention policy is single and consistent.
6. **Operability:** Upgrades are safe/repeatable; on-call knows what pages, what to do, and what "healthy" looks like.

**Out of scope (explicit):** built-in webmail, multi-region active/active HA, FedRAMP/ISO certification audits themselves. Those are Phase 5+ options, not blockers for a pilot.

### Assumptions

- Team of 2–4 engineers, part-time security reviewer available for Weeks 4, 8, 12.
- Baseline is the current single-VPS Docker Compose topology (kept; hardened, not replaced).
- Each work item follows the repo's **Milestone Completion Packet** standard (`REMEDIATION-MILESTONES.md:23-39`): architecture, schema, service/job/config/health/audit contracts, security review, UX evidence, test evidence, operational note. No packet → not done.

---

## 2. Baseline (where we start)

| Pillar | Score | One-line evidence |
|---|---|---|
| Identity & Access | 2/5 | Axes lockout + audit exist; **no MFA/SSO**; 2-role RBAC; 2-week default sessions; no API tokens |
| Data Protection | 2/5 | TLS/DNSSEC/GPG backups; **backups on same disk**, no off-site; keys in DB/env |
| Availability & DR | 2/5 | Health tiers + monitor script; **single-host SPOF**; RPO ~24h (unstated); manual RTO |
| Scalability | 2/5 | Vertical headroom modeled; no horizontal path; downtime deploys |
| Observability | 3/5 | DB telemetry w/ PII scrub + dedup, correlation IDs, health tiers; no metrics/OTEL; webhook-only alerts |
| App Security | 3/5 | Harden headers, CSP report-only, fail-closed env; **unpinned deps, no CI/scans**; HSTS 1h |
| Compliance/Governance | 2/5 | Audit trail exists; mutable log, no SIEM export, retention mismatch (30d vs 7d) |
| Operability/Quality | 3/5 | Idempotent provisioning, broad tests, runbook README; **no CI** |

**Single sentence:** the product is *operationally honest* (it reports its own state well) but *structurally fragile* (one host, one disk, two roles, no second factor).

---

## 3. Phased flow (end to end)

```
Phase 0  Assess & Baseline        (Week 1)      → frozen scope, SLOs, risk register
Phase 1  Pilot-Ready: IAM+DR      (Weeks 2–5)   → MFA, off-site backups, restore drill  →  ~3.0/5
Phase 2  Harden: Supply+Sessions  (Weeks 6–9)   → CI/scans, RBAC/tokens, session mgmt    →  ~3.5/5
Phase 3  Prove it: DR+Evidence    (Weeks 10–12) → measured RTO/RPO, pen-test fixes, packet →  4.0/5
Phase 4  Operate: Continuous      (Week 13+)    → SLOs, rotations, reviews as routine
```

Each phase has **entry criteria** (what must be true to start), **workstreams with acceptance criteria**, and **exit criteria** (what must be true to advance). A phase does not start until the previous phase's exit criteria are signed off.

**RACI convention used below:** R = builds it, A = accepts it (sign-off), C = consulted, I = informed.

---

## Phase 0 — Assess & Baseline (Week 1)

**Goal:** freeze scope, agree SLOs, stand up the CHANGELOG of record.
**Entry:** this proposal approved. **Exit:** risk register + SLO sheet + Phase-1 backlog signed by engineering lead (A).

| # | Work item | Acceptance criteria |
|---|---|---|
| 0.1 | Freeze baseline metrics | Record: test suite pass rate + duration, `pip-audit` findings count, backup size/duration, full-rebuild time measured once (stopwatch, documented) |
| 0.2 | Adopt SLO sheet | RPO ≤ 24h (interim), RTO ≤ 4h (interim, manual), console availability ≥ 99.5% monthly (single host, stated honestly), backup age alert > 25h = CRITICAL (already in `monitor.py`) |
| 0.3 | Risk register | Top-10 risks with owner + mitigation phase (single-host loss, credential compromise without MFA, unpinned dep CVE, same-disk backup loss, session hijack window) |
| 0.4 | Retention unification | One decision recorded: single retention value (recommend 30d) applied to telemetry, audit, backups; fix `.env.example` 7-vs-30 mismatch |
| 0.5 | Landing-page honesty | Remove or gate the "MFA support" marketing claim until Phase 1 ships (`frontend/templates/landing.html:253`) |

**Deliverables:** `docs/enterprise-slo.md`, `docs/risk-register.md`, frozen Phase-1 backlog.

---

## Phase 1 — Pilot-Ready: Identity + Data Survival (Weeks 2–5)

**Goal:** survive the two questions that kill enterprise deals: *"Do you support MFA/SSO?"* and *"Prove you can restore my mail."*
**Entry:** Phase 0 exit signed. **Exit:** admin enrollment in TOTP enforced on new setups; off-site backup copy verified; one full rebuild drill completed with measured RTO; rating ~3.0/5.

### Workstream A — Multi-factor authentication (R: backend eng, A: eng lead, C: security reviewer)

| # | Work item | Acceptance criteria |
|---|---|---|
| A.1 | TOTP device model | `TOTPDevice(user, secret_encrypted, verified_at, last_used)`; secrets encrypted at rest (Fernet via Django SECRET_KEY, same pattern as DNS credentials); recovery codes hashed, single-use; migrations + indexes |
| A.2 | Enrollment + verification UX | Setup-wizard and settings flows: QR code, 2-code verification, 10 recovery codes shown once; states covered (empty/loading/success/error) per repo Experience Bar |
| A.3 | Enforcement | Staff login requires verified device; `login_blocked`/new `mfa_*` audit events; rate-limit code attempts (reuse Axes/IP limiter pattern); backup-code use audited |
| A.4 | Session binding | Successful MFA binds `mfa_verified_at` into session; `mailbox_setup` invite-accept flow already captures viewer pre-change (keep that pattern) |
| A.5 | Tests + packet | Unit (token drift ±1 step, replay rejected), view (unenrolled staff blocked post-password), e2e enroll→logout→login; completion packet per repo standard |

**Explicitly deferred to Phase 2:** WebAuthn/passkeys, SSO/OIDC (shipped as "SSO ready" only after A is stable).

### Workstream B — Backups that can actually save you (R: platform eng, A: eng lead)

| # | Work item | Acceptance criteria |
|---|---|---|
| B.1 | Off-site copy | Nightly `backup_full.sh` output (already GPG-encrypted) synced to S3-compatible/rSync target; target credentials in env, never in repo; alert on copy failure via existing `BACKUP_NOTIFY_URL` |
| B.2 | Backup scope fix | Add `runtime_data` (zones/Knot/postfix/firewall state), `postfix_spool` (queued mail), `rspamd_data` (Bayes) to the manifest — or record signed waivers for each exclusion |
| B.3 | Automate restore test | Cron-install `restore_test.sh` weekly; extend to assert DKIM count, DNSSEC DS presence, cert archive presence; results mailed + visible in console (reuse `last-backup-at` pattern) |
| B.4 | Full rebuild drill (the money item) | Fresh VPS → `make provision` → `pg_restore` → copy `mail_data/dkim/certs/dns_data` → verify mail flow + DNSSEC + console; **measure wall-clock RTO**, record gaps, re-run until RTO ≤ 4h |
| B.5 | Runbook | `docs/dr-runbook.md`: prerequisites, step-by-step rebuild, verification checklist (send/receive, DNSSEC, certs, console login), rollback notes, on-call contacts |

### Workstream C — Quick security wins (fold into Phase 1 sprints)

| # | Work item | Acceptance criteria |
|---|---|---|
| C.1 | HSTS 1 year + CSP enforce (staged) | `SECURE_HSTS_SECONDS=31536000`; CSP `REPORT_ONLY=false` behind env flag, 1-week report-only soak first using existing `/csp-report/` telemetry |
| C.2 | Session baseline | `SESSION_COOKIE_AGE` (e.g. 12h), `SESSION_EXPIRE_AT_BROWSER_CLOSE=True` for non-staff, `SESSION_COOKIE_SAMESITE=Lax` explicit; document the 2-week → 12h change in release notes |

**Phase 1 exit demo (must be demonstrable live):** enroll TOTP → logout → login blocked without code → login with code; trigger backup → show off-site copy receipt; tabletop the rebuild drill timeline with measured numbers.

---

## Phase 2 — Harden: Supply Chain, Access Control, Sessions (Weeks 6–9)

**Goal:** make every change traceable and every privilege minimal. Target ~3.5/5.
**Entry:** Phase 1 exit signed. **Exit:** CI green on every PR; MFA + roles + tokens live; session policy enforced; rating ~3.5/5.

### Workstream D — CI + dependency supply chain (R: platform eng, A: eng lead)

| # | Work item | Acceptance criteria |
|---|---|---|
| D.1 | CI pipeline (new `.github/workflows/ci.yml`) | Jobs: `manage.py check --deploy`, `pytest`, `ruff check`, `pip-audit`, secret scan (gitleaks), shellcheck for `provisioning/scripts`; PR cannot merge red (branch protection) |
| D.2 | Pin + hash dependencies | `pip-compile` lockfile with hashes for prod image; Dependabot/Renovate weekly; documented CVE-SLA (critical ≤ 7d, high ≤ 30d) |
| D.3 | Image hygiene | `make reload` path documented; base-image refresh cadence monthly; `unattended-upgrades` verified covering host (already enabled in `provision.sh`) |

### Workstream E — Authorization worth auditing (R: backend eng, A: eng lead, C: security reviewer)

| # | Work item | Acceptance criteria |
|---|---|---|
| E.1 | Roles | `Role` model (e.g. Owner, Admin, Support-read-only, Billing) mapped to explicit permission sets; replace bare `is_staff` gates on at least console settings; migration path for existing staff; `unassigned_roles`/`rbac_status` UI becomes real |
| E.2 | First-party API tokens | Scoped service-account tokens (read/write scopes, expiry ≤ 90d, rotation endpoint, revocation list); Ninja schemas validate every input (close the empty-`serializers.py` gap); token use audited |
| E.3 | Credential-lifecycle audit | Password set/reset, invite issued/accepted, token created/rotated/revoked, role granted/revoked all emit structured audit events (actor, target, IP, correlation ID) |

### Workstream F — Session control (R: backend eng, A: eng lead)

| # | Work item | Acceptance criteria |
|---|---|---|
| F.1 | Idle vs absolute timeout | Idle 30 min + absolute 12h (env-tunable); high-risk actions (role grant, token create, mailbox delete) require fresh password/MFA re-auth |
| F.2 | Session inventory | Per-user device/session list with per-session revoke (finish the `live_sessions: []` stub); revocation audited; admin kill-switch retained |
| F.3 | SSO/OIDC (start) | `mozilla-django-oidc` (or equivalent) behind feature flag for one IdP; staff-only initially; JIT provisioning mapped to lowest role; full rollout in Phase 3 if stable |

---

## Phase 3 — Prove It: Measured DR, Adversarial Review, Evidence Pack (Weeks 10–12)

**Goal:** replace claims with measurements and produce the artifact a CISO actually reads. Target 4.0/5.
**Entry:** Phase 2 exit signed. **Exit:** signed evidence pack; pen-test criticals fixed; SLOs measured ≥ 4 weeks; pilot approved.

| # | Work item | Acceptance criteria |
|---|---|---|
| G.1 | RTO/RPO measurement | 4 consecutive weekly restore tests green; 1 unannounced rebuild drill (different engineer follows only the runbook); RTO/RPO published in `docs/enterprise-slo.md` with data |
| G.2 | Lightweight pen test | Scoped test (auth, session, invite-token entropy/expiry, DNS/DKIM, headers, backup crypto); all criticals/highs fixed + retested; report filed in evidence pack |
| G.3 | Audit export + retention | SIEM export (JSONL download + documented schema); retention single-value enforced by scheduled purge; audit table append-only by policy (documented control, technical WORM if cheap) |
| G.4 | Observability uplift (cheap, high-value) | JSON log formatter (keep human console format in dev), Prometheus `/metrics` (backup age, queue depth, cert days, probe status — all already computed), alert thresholds mapped to SLOs; PagerDuty/Opsgenie webhook documented |
| G.5 | Evidence pack | `docs/enterprise-evidence/` : architecture diagram, data-flow + secrets map, RTO/RPO measurements, pen-test report + fixes, CI/scan history, retention config, DR runbook, role matrix, incident contacts |

**Phase 3 exit demo:** from a laptop with only the runbook + secrets: rebuild, restore, verify mail + DNSSEC + MFA login, inside published RTO. If it fails, Phase 3 repeats.

---

## Phase 4 — Operate (Week 13+, continuous)

Not a project — a cadence. Each item has an owner and a calendar entry, or it will rot.

| Cadence | Item | Owner |
|---|---|---|
| Weekly | Dependency scan review; restore-test result review | Eng lead |
| Monthly | Base-image refresh; access review (roles, tokens, staff list); backup-copy integrity spot-check | Eng lead + Owner admin |
| Quarterly | DR drill (rotating engineer, runbook-only); secrets rotation (GPG, DNS provider keys, OIDC); SLO review | Eng lead |
| Per-release | Completion packet; pen-test regression on auth/session surface; retention verification | Feature owner |
| Annual | Full access recertification; DR architecture revisit (managed PG / object-store mail?); compliance mapping refresh (SOC 2 CC6/CC7) | Leadership |

---

## 4. End-to-end expectations map (who expects what, when)

| Stakeholder | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|---|
| Executive sponsor | Approves scope/SLOs | Sees MFA + backup receipts demo | Sees CI enforcement | Signs evidence pack, approves pilot | Quarterly SLO review |
| Engineering lead (A) | Signs backlog | Signs A.5/B.5 packets | Signs D/E/F packets | Signs evidence + pen-test fixes | Owns cadence |
| Security reviewer (C) | Threat-model lite (top-10) | Reviews A.1/A.3, B.1 crypto | Reviews E.1/E.2, F.3 | Runs/witnesses pen test | Annual recert |
| Customer (pilot) | Nothing promised | "MFA live, backups off-site" | "Roles + tokens, SSO beta" | Receives evidence pack + SLOs | SLA-backed support |
| On-call | — | DR runbook draft | Alert tuning | Runbook-only drill | Paged per SLOs |

---

## 5. Risks & mitigations

| Risk | Likelihood / Impact | Mitigation |
|---|---|---|
| Single-host loss before B.1 lands | Med / **Critical** | Do B.1 first (Week 2); interim manual off-site copy documented Day 1 |
| MFA enrollment lockout (lost device, no codes) | Med / High | Recovery codes + documented break-glass owner procedure; never allow self-service bypass without two-person rule |
| Scope creep into HA/multi-region | Med / Med | Explicit out-of-scope list (§1); revisit only in Phase 5 |
| SSO IdP diversity (SAML vs OIDC) | Med / Med | OIDC first behind flag; SAML only on signed customer demand |
| Audit-log growth / DB bloat | Low / Med | Existing purge jobs kept; verify retention job covers audit + telemetry + backups in one place |
| Upgrade downtime during hardening | High / Low | Announced windows; `make reload` rehearsed on staging VPS first |

---

## 6. Effort sketch (planning aid, not a quote)

Assumes 2–4 engineers, familiar with codebase. In engineer-weeks:

- Phase 0: 0.5 · Phase 1: 4–6 (MFA ~2.5, backups/DR ~2, quick wins ~0.5) · Phase 2: 5–7 (CI/deps ~1, RBAC/tokens ~2.5, sessions ~1, SSO start ~1.5) · Phase 3: 3–4 (drills + pen-test fixes + evidence) · External pen test: budget separately.
- Contingency: +20% (single-host surprises are the norm, not the exception).

---

## 7. Compliance mapping (lightweight, SOC 2-oriented)

| Trust criterion | Covered by |
|---|---|
| CC6.1 (logical access) | MFA (A), roles (E.1), session control (C.2/F) |
| CC6.2 (credentials) | Password validators + invite flow (shipped), rotation policy (Phase 4), token expiry (E.2) |
| CC6.3 (encryption) | TLS/HSTS, GPG backups, secret encryption at rest (A.1 pattern + E) |
| CC7.2 (monitoring) | Health tiers, telemetry, monitor webhooks, metrics (G.4) |
| CC7.3 (incidents) | Audit trail + export (G.3), DR runbook (B.5), incident contacts (G.5) |
| CC8.1 (change mgmt) | CI gates (D.1), completion packets, branch protection |

---

## 8. Decision log (fill as we go)

| Date | Decision | By | Rationale |
|---|---|---|---|
| — | Retention = 30d everywhere | TBD | Unify telemetry/audit/backup; fix `.env.example` mismatch |
| — | OIDC before SAML | TBD | Broader IdP coverage per integration; SAML on demand |
| — | Single-host retained through pilot | TBD | Cost/simplicity; revisit managed-PG/object-store in Phase 5 |
| — | RPO ≤ 24h / RTO ≤ 4h interim | TBD | Matches daily backups + manual rebuild; tighten after measurement |

---

*End of proposal. Next step: approve §1–§3 scope, then open Phase 0 items (0.1–0.5) as tracked work.*
