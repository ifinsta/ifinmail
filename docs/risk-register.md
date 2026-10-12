# Risk register

Owner of every risk is the project maintainer unless stated. Reviewed quarterly and whenever a
finding in `docs/enterprise-readiness-proposal.md` changes status. *L* = likelihood, *I* = impact
(H/M/L). *Residual* is after the controls listed as **in place**.

| # | Risk | L | I | Controls in place | Open mitigation | Residual |
|---|---|---|---|---|---|---|
| R1 | Loss of the single host or its disk | M | **H** | Encrypted nightly backups; weekly restore test; verified off-site copy over SSH when `BACKUP_OFFSITE_TARGET` is set | Run and time the rebuild drill (G.1); keep the key escrowed (B.6) | M until the drill is logged |
| R2 | Backups exist but cannot be opened | M | **H** | `make backup-key` proves the exported key opens the newest backup; System health warns until exported | Quarterly `verify-key` drill from the off-host copy | L once drilled |
| R3 | Administrator credential theft | M | **H** | MFA (enforced on new installs, `MFA_ENFORCEMENT`); password re-confirmation for role/admin/token/delete; Axes lockout; 30 min idle and 12 h absolute sessions | Turn on `required` for existing installs; consider SSO if customers ask | L–M |
| R4 | Stolen mailbox password used to send spam, damaging IP reputation | M | **H** | Per-login and per-recipient-domain send limits (Rspamd); blocklist check in System health | Per-mailbox suspend on anomaly (not built) | M |
| R5 | Evidence lost or altered during an incident | L | **H** | Hash-chained audit trail, 365-day time-based retention, dashboard cannot erase recent events, JSONL export with chain head, daily verification and `ifinmail_audit_chain_ok` metric | Pin the export head off-host after significant events; ship exports to a log host if one exists | L |
| R6 | Vulnerable dependency shipped | M | M | Hash-pinned lockfile enforced at build; `pip-audit` on every change and weekly; CVE targets in `enterprise-slo.md` | Maintainer must act on the weekly run | M |
| R7 | Poisoned or swapped package at build time | L | **H** | `--require-hashes` | Image base is pulled by tag, not digest | L |
| R8 | Secret exposure from the database or a disk image | L | **H** | TOTP secrets encrypted; API tokens hashed; backups encrypted | DKIM private keys are stored in plaintext in the database and on disk (B.7) | M |
| R9 | One maintainer unavailable | M | M | Update, rollback, uninstall and backups are scripted; runbook written | Second person with access to the key escrow and registrar | M |
| R10 | Console served with a broken page under CSP | L | L | CSP enforced with reporting to `/csp-report/`; contract tests forbid inline script | `CSP_REPORT_ONLY=true` is the emergency switch | L |
| R11 | Upgrade breaks the console | L | M | Database snapshot before update, automatic rollback if unhealthy | None | L |
| R12 | Registrar or DNS-provider account compromise | L | **H** | Authoritative DNS on this server; DNSSEC | Registrar MFA is outside this project; list in the drill | M |
