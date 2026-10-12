# ifinmail Enterprise Readiness Plan — Status and Roadmap

**Status:** Revision 3, 2026-10-12 · **Assessed:** branch `remediation/enterprise-phase-1` (not yet released; v0.0.1 is the last release)
**Rating:** **3.5/5** on the branch (2.6/5 on v0.0.1, stated as 2.2/5 on 2026-10-11) · **Target:** 4.5/5 (4.0 self-assessed; the last half point needs outside parties, see §3)
**Companion docs:** `docs/enterprise-slo.md` (objectives) · `docs/risk-register.md` · `docs/secrets-map.md` · `docs/dr-runbook.md` · `docs/REMEDIATION-MILESTONES.md`

> **Read this first: what 4.5 means.** The rubric in §2 defines 5 as *independently audited*. Nothing
> the maintainer can do alone reaches 5, so an average of 4.5 needs outside parties on at least four
> of the eight pillars. What the project *can* do alone is make every pillar a 4 (enforced, tested,
> observable, documented) and leave behind the evidence that makes an outside audit cheap. This
> revision does the first part on most pillars and says precisely what remains (§3). It does not
> raise a score without a test, a measurement or a document behind it.

---

## 1. Operating principles (why the plan is shaped this way)

The constraints are a single maintainer and a deliberately small dependency surface.

1. **Configure what already runs before adding anything.** The off-site copy uses OpenSSH, the
   rate limits use Rspamd, the metrics are text, the audit chain is SHA-256. No new daemon, SaaS,
   SDK or bot was introduced.
2. **A feature is done only with four things:** a test, a signal (health check or metric), a line in
   the docs, and an off switch or safe default. Otherwise it is a liability.
3. **Say "not doing" out loud** (§6). Each deferral has a trigger that would reverse it.
4. **Recurring work is budgeted** (§7). A control that needs more maintainer time than exists will
   rot; the plan counts that time.
5. **Upgrades never change an existing install's security posture silently.** New installs get the
   strict default; existing installs get a health warning and a one-line switch.

---

## 2. Definition of done and scoring

### Requirements (an enterprise security review can answer yes to all six)

| # | Requirement | Status | Evidence on the branch |
|---|---|---|---|
| 1 | **Identity** — MFA enforced; idle/absolute timeouts; least-privilege roles; workforce SSO on customer demand | **Met** (self-assessed) | `MFA_ENFORCEMENT=required` (default for new installs); password re-confirmation for role/admin/token/delete; 12 h/30 min sessions; three roles; break-glass `reset_mfa`. SSO deferred by decision D4 (approved 2026-10-12, §6). |
| 2 | **Data** — encrypted, off-site, restore-tested; RPO/RTO measured | **Partial** | Verified off-site copy and proven key export built and tested end to end. Off-site target must be configured by the operator; **RTO never measured**. |
| 3 | **Availability** — failure modes known, health observable, recovery is a runbook | **Partial** | Health checks, metrics, update/rollback, `dr-runbook.md`. The runbook has **not been executed end to end**. |
| 4 | **Security** — pinned and scanned dependencies, CI gates, CSP enforced, secrets managed | **Met** (self-assessed) | Hashes enforced at build, weekly audit, secret scan, CSP enforced, `secrets-map.md`. No external penetration test. |
| 5 | **Governance** — tamper-evident, exportable audit trail; one retention policy | **Met** (self-assessed) | Hash-chained trail, time-based retention, JSONL export, daily verification, metric. |
| 6 | **Operability** — safe upgrades; on-call knows what pages and what to do | **Met** (self-assessed) | `make update`/`rollback`, SLOs mapped to health checks and metrics, runbook, risk register. |

### Rubric

| Score | Meaning |
|---|---|
| 1 | Absent |
| 2 | Exists, but a known gap defeats the control |
| 3 | Works as built on a single host; enforcement or evidence still open |
| 4 | Enforced by default or by documented policy, covered by automated tests, observable through health checks or metrics, and documented (maintainer review plus CI) |
| 5 | Independently audited |

### Scores

| Pillar | v0.0.1 | Branch | Why |
|---|---|---|---|
| Identity & Access | 3 | **4** | Controls enforced, tested and observable. SSO deferred by decision D4. |
| Data Protection | 2 | **3** | Off-site + key escrow exist and are proven in isolation; off by default, RTO unmeasured. |
| Availability & DR | 2 | **3** | Runbook, health, rollback exist; the rebuild drill has not run. |
| Scalability | 2 | **2** | Vertical headroom only; probe and template exist, but no measurement has been run. |
| Observability | 3 | **4** | Every SLO signal is a health check and a metric (`/api/metrics`); alert thresholds documented. |
| Application security | 3 | **4** | CSP enforced, hashed lock enforced, step-up, rate limits, secrets mapped. Pen test outstanding (needed for 5). |
| Governance | 2 | **4** | Chain, retention, export, purge fixed, risk register, SOC 2 mapping. |
| Operability & quality | 4 | **4** | 769 tests, 78 % coverage, shellcheck clean, scheduled audit, proven update/rollback. |

**Average: 3.5** (28 / 8).

---

## 3. The honest path to 4.0 and 4.5

| Step | Moves | Needs | Maintainer effort |
|---|---|---|---|
| ~~Accept the SSO deferral (D4)~~ | Identity 3→4 | **Done 2026-10-12** | — |
| Run and log one rebuild drill from the off-site copy and escrowed key, using only the runbook (template and clock in `docs/enterprise-evidence/`) | Data 3→4, Availability 3→4 | A spare VPS for a day | ~1 day |
| Run `provisioning/scripts/capacity_probe.py` from another machine against a staging server of production size; record the capacity statement | Scalability 2→4 | Staging host, one afternoon | ~half a day |
| **Average after the two remaining steps** | | | **4.0** |
| Independent penetration test of auth, session, invite tokens, DNS/DKIM, headers, backup crypto | Application security 4→5, Identity 4→5 | External tester (budget) | days of fixes |
| Independent DR/backup review, or a SOC 2 Type I readiness assessment | Data 4→5, Governance 4→5 | External assessor | evidence pack ready |
| **Average with those four at 5** | | | **4.5** |

Until the last two rows are done by someone else, the project is at most **4.0 self-assessed**, and
the maintainer should not describe it as more.

---

## 4. Findings and their status

| ID | Sev. | Finding (as found on v0.0.1) | Status | Where |
|---|---|---|---|---|
| F1 | High | Audit trail capped at 10,000 rows, oldest deleted first | **Fixed** | time-based retention; `AuditService.purge_expired` |
| F2 | High | MFA could be postponed or switched off | **Fixed** (policy) | `MFA_ENFORCEMENT`; existing installs stay `optional` until switched, with a health warning |
| F3 | High | No off-site backup | **Built; operator must configure** | `backup_offsite.sh send`; health warns until set |
| F4 | High | Backup key only on the server | **Fixed** | `make backup-key` + proof; health warns until exported |
| F5 | Med | Audit rows mutable, not exportable | **Fixed** | hash chain, JSONL export, verify command |
| F6 | Med | CSP report-only | **Fixed** | enforced by default; `CSP_REPORT_ONLY` emergency switch |
| F7 | Med | Tokens up to 365 days | **Fixed** | `MAX_TOKEN_DAYS = 90` |
| F8 | Med | DKIM keys plaintext at rest | **Accepted, documented** | `secrets-map.md` waiver and reversal conditions |
| F9 | Med | Lockfile unhashed, no update automation | **Fixed** (by design: no bot) | `--require-hashes`; weekly CI audit |
| F10 | Med | No step-up re-authentication | **Fixed** | `StepUpService` |
| F11 | Med | Referenced documents missing | **Partly fixed** | runbook, risk register, secrets map written; evidence pack and drill log open |
| F12 | Low | Four quota tests failing | **Fixed** | tests wrote GBs into RAM; sparse files |
| F13 | Low | SLO doc wrong about audit retention | **Fixed** | `enterprise-slo.md` corrected |
| F14 | High | Dashboard could erase the audit trail | **Fixed** | purge limited to expired rows |
| F15 | Med | "Export" read a 200-event per-process buffer | **Fixed** | exports read the database |
| F16 | Low | DKIM key files mode 0644 | **Accepted, documented** | needed for Rspamd; see waiver |

---

## 5. Work-item status

### Done on the branch

| Item | What was built | Proof |
|---|---|---|
| G.3 Audit trail | Seq + SHA-256 chain, 365-day retention (min 30), daily maintenance and alarm, JSONL/CSV export from DB with chain head, purge limited to expired, `verify_audit_chain` | 13 tests incl. edit/removal detection, race retry |
| A.6 MFA policy | Enforcement setting, no snooze/disable when required, re-prompt for previously opted-out, health check, break-glass | 11 tests |
| B.1 Off-site | Copy, SHA-256 compare on the far side, atomic publish, prune, plaintext refused, strict target grammar | End-to-end run against a real SSH server: 9 behaviours incl. injection and failure |
| B.6 Key escrow | Export + proof against the newest backup using only the exported files | Same run: verified with a keyring that never held the key; wrong passphrase caught |
| F.1 Step-up | Password re-confirmation, rate limited, audited | 5 tests |
| E.2 Token cap | 90 days across form, service and UI | test |
| C.1 CSP | Enforced; contract tests keep inline script out | contract tests |
| D.2 Supply chain | Hashed lock enforced at build, tamper rejected, weekly audit | install dry-run; tampered lock exits 1 |
| G.4 Observability | `/api/metrics` Prometheus text, audit.view scope | 4 tests; no addresses or secrets |
| M5 Send limits | Rspamd per-login and per-login+domain buckets | `rspamadm configtest` in the real image; contract test |
| M7 (part) | `SECURITY.md` | n/a |
| Evidence tooling | `capacity_probe.py` (stdlib only), drill and capacity templates | Probe verified for success and unreachable-target paths |
| B.7 Secrets map | `docs/secrets-map.md` | verified table names against models |
| 0.3 / B.5 | `risk-register.md`, `dr-runbook.md` | runbook flagged unexecuted |

### Open

| Item | Needed | Why not done here |
|---|---|---|
| B.4 / G.1 Rebuild drill, measured RTO/RPO | A second host and a day; template ready in `docs/enterprise-evidence/` | Cannot be done from this host; the single biggest evidence gap |
| G.2 Penetration test | External party | Independence is the point |
| Capacity statement (Scalability) | Run `capacity_probe.py` against staging (tool built, tested against a stand-in server only) | Not run: a production-size staging host is not available here, and load-testing the live server is not safe |
| G.5 Evidence pack (`docs/enterprise-evidence/`) | Drill log, test report, config exports | Assembled after the drill |
| Verify branch protection requires CI | GitHub settings access | Not visible from the repo |
| Release and deploy the branch | Owner approval | Nothing on this branch is live |

---

## 6. Not doing, and what would change that

Deliberate deferrals, so the backlog does not grow by default.

| Item | Why not now | Reverse when |
|---|---|---|
| **Workforce SSO (OIDC)** — *decided 2026-10-12 (D4)* | Security-sensitive code (token validation, key rotation, JIT) or a new dependency for a feature no customer has asked for. Local roles already exist for a future claim mapping. | A signed customer requires it. Then OIDC authorization-code flow only; SAML only on explicit demand. |
| SCIM / LDAP directory sync | Same, plus a long tail of IdP quirks | Customer with more than ~50 mailboxes and an IdP |
| Domain-scoped roles | Schema and permission changes across every view | A multi-domain customer with delegated administration |
| Mail retention, legal hold, erasure (M1, M2) | Needs a component that can write the mail volume; the console mounts it read-only on purpose | A regulated customer; design as a separate audited job |
| Automatic suspension on send anomaly | Rate limits already cap the damage; anomaly rules produce false positives for one maintainer to triage | Repeated abuse despite limits |
| DANE/TLSA | Little receiver support; MTA-STS and TLS-RPT already ship | Receiver adoption changes |
| SBOM and signed images | Meaningful only with a registry and consumers | A customer asks, or releases are published to a registry |
| Dependabot / Renovate | A bot the maintainer must triage; the weekly audit covers the risk | Dependency churn exceeds weekly manual review |
| Prometheus client library, OpenTelemetry, SIEM connectors | `/api/metrics` and JSONL export already interoperate | A customer's tooling cannot consume text/JSONL |
| High availability / multi-region | Out of scope for a single-VPS product | Revisit annually |

---

## 7. Maintainer load (the cost of keeping these controls true)

| Cadence | Task | Time |
|---|---|---|
| Weekly (automatic, 1 min to read) | CI dependency audit result; System health badge | 5–15 min |
| Monthly | Review `risk-register.md` rows marked M or H; check off-site age and key export status | 30 min |
| Quarterly | Run the recovery drill from `dr-runbook.md` on a scratch host; run `verify-key` from the escrowed copy; rotate the backup key if staff changed | half a day |
| Per release | Run the suite, design audit and shellcheck; read the CHANGELOG diff for security-relevant lines | 30 min |
| On demand | `make lock` when the audit fails | 30–60 min |

If these hours are not available, drop the quarterly drill last and the monthly review first; the
weekly signal and the off-site copy are the controls that fail silently without attention.

---

## 8. Decisions requiring the owner

Everything below is implemented on the branch or proposed; none is released. Approve, change or
reject each before release.

| # | Decision | Recommendation | Impact |
|---|---|---|---|
| D1 | New installs enforce MFA (`MFA_ENFORCEMENT=required`); existing installs unchanged | Approve | An administrator without an authenticator must set one up at first sign-in |
| D2 | CSP enforced by default | Approve | A page that breaks is fixed by switching `CSP_REPORT_ONLY=true` |
| D3 | Audit retention 365 days (telemetry and backups stay 30) | Approve | Database growth is small; adjust with `AUDIT_RETENTION_DAYS` |
| D4 | Defer SSO until a customer requires it (§6) | **Approved by owner 2026-10-12** | Identity scores 4 |
| D5 | No automated update bot; weekly audit instead | Approve | Maintainer reads one CI result a week |
| D6 | Send limits 100/hour per login, 40/hour per login and recipient domain | Review | A bulk sender needs a higher limit before launch |
| D7 | Password re-confirmation for role grants, admin rights, token creation, mailbox deletion | Approve | One extra field on four forms |
| D8 | Existing install `/root/ifinmail`: apply `MFA_ENFORCEMENT=required`, configure off-site target, export key | Do after release | Needs a target host and a safe place for the key |

---

## 9. Compliance mapping (SOC 2-oriented, readiness tracking — not a claim)

| Criterion | Covered by | Status |
|---|---|---|
| CC6.1 logical access | MFA policy, roles, step-up, sessions | Met (self-assessed); SSO deferred |
| CC6.2 credentials | Invite flow, hashed secrets, 90-day tokens, secrets map | Met (self-assessed) |
| CC6.3 encryption | TLS/HSTS, encrypted backups, key escrow, TOTP and DNS credentials encrypted | Partial — DKIM at rest accepted (F8) |
| CC7.2 monitoring | Health checks, metrics, alerts mapped to SLOs | Met (self-assessed) |
| CC7.3 incidents | Hash-chained audit, export, runbook | Partial — runbook unexecuted |
| CC8.1 change management | CI gates, scheduled audit, update/rollback, branch protection | Partial — protection unverified |
| A1 availability | SLOs, backups, off-site, restore tests | Partial — RTO unmeasured |
| C1 confidentiality | Encrypted backups and off-site; secrets map | Partial — mail retention and erasure deferred |

A SOC 2 report needs an independent auditor and an observation period (typically 3–12 months for
Type II). Nothing here substitutes for one.

---

## Appendix — Revision notes

**Revision 3 (2026-10-12)** follows the remediation work on `remediation/enterprise-phase-1`:

- Fifteen of sixteen findings are fixed, built or accepted with a written waiver; the rest are open
  only because they need a second host or an outside party.
- Scores re-derived against an explicit rubric: 3.5/5, up from 2.6. The path to 4.0 and the
  requirement for outside parties at 4.5 are stated in §3 rather than assumed.
- Added operating principles, a "not doing" register with reversal triggers, and the maintainer's
  recurring time budget.
- Corrected earlier claims: TLS-RPT and MTA-STS already shipped, and the SLO document no longer
  says the audit trail is kept 30 days.
