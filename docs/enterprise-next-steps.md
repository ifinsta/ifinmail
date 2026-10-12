# Enterprise remediation: what is left

**As of 2026-10-12.** Branch `remediation/enterprise-phase-1` (10 commits on `main` at v0.0.1) is
complete, tested (769 passing, 78 % coverage) and **not yet pushed, released or deployed**.
Current self-assessed score: **3.5/5**. Full detail: `enterprise-readiness-proposal.md`.

Do these in order. Each has a prerequisite and a finish line.

## 1. Review and release the branch

| | |
|---|---|
| **Needs** | You, ~1 hour |
| **Do** | Push the branch, open a PR, read the diff. Decide D1–D3 and D5–D8 in §8 of the proposal (D4 is already approved). Merge, tag, then `sudo make update` on the server. |
| **Watch for** | Migration `0002_audit_hash_chain` runs on update. Older audit rows have no chain position and sit outside it; the chain starts with the first new event. |
| **Done when** | `make version` shows the new release; `docker compose exec api python manage.py verify_audit_chain` prints `Audit chain intact.` |

## 2. Switch the protections on for the existing server

Upgrades deliberately do not change an existing install's posture. In `provisioning/.env`:

```
MFA_ENFORCEMENT=required
BACKUP_OFFSITE_TARGET=user@host:/absolute/path     # any host you control over SSH
```

Then `sudo make up`, `sudo make offsite-check`, `sudo make backup`, `sudo make backup-key`.
Move the two files from `/root/ifinmail-backup-key` to a password manager or an encrypted drive and
delete them from the server.

**Done when** System health shows green for *Two-factor sign-in*, *Off-site backup* and
*Backup key*, and the key files exist somewhere that is not this server.

## 3. Rebuild drill  (moves Data and Availability to 4)

| | |
|---|---|
| **Needs** | A spare VPS for a day; the escrowed key; an off-site backup |
| **Do** | Follow only `dr-runbook.md` on the fresh host. Fill in the drill template in `enterprise-evidence/README.md`. Correct the runbook wherever it was wrong. |
| **Done when** | `enterprise-evidence/drill-YYYY-MM-DD.md` exists with a measured RTO ≤ 4 h, and the SLO table in `enterprise-slo.md` says "measured" |
| **Known open questions** | `pg_restore` ownership on a fresh database; whether the restored `.env` leaves a stale secret (see the runbook's last section) |

## 4. Capacity statement  (moves Scalability to 4)

| | |
|---|---|
| **Needs** | A staging server of production size, and a second machine to run the probe from |
| **Do** | `python3 provisioning/scripts/capacity_probe.py --base https://<staging mail host> --levels 1,5,10,25,50` (add the `--smtp-*` options to test submission, remembering the 100/hour send limit). Paste the result into the capacity template. |
| **Done when** | `enterprise-evidence/capacity-YYYY-MM-DD.md` states the concurrency and mailbox count the server supports and which resource limits it |

After 3 and 4 the self-assessed average is **4.0**. Do not describe it as more.

## 5. Outside review  (the only route to 4.5)

| Review | Moves | Scope to give them |
|---|---|---|
| Penetration test | Application security, Identity → 5 | Console login, MFA and step-up, session handling, invite and setup tokens, API token auth, CSRF/CSP, DNS/DKIM handling, backup crypto and the off-site copy |
| DR / readiness review | Data, Governance → 5 | `dr-runbook.md`, the drill log, `risk-register.md`, `secrets-map.md`, the audit export and chain, the SOC 2 mapping in §9 of the proposal |

Hand them `enterprise-evidence/` and the proposal. Fix criticals and highs, re-test, and file the
reports next to the drill log. Four pillars at 5 with the rest at 4 is an average of 4.5.

## Small checks that can happen any time

- In GitHub, confirm branch protection requires the CI workflow to pass before merge (not visible
  from the repository).
- Read the first weekly scheduled CI run; if the dependency audit fails, `make lock`.
- Confirm the CSP is behaving: Logs should show no steady stream of `CSP violation` entries after the
  release. `CSP_REPORT_ONLY=true` is the emergency switch.
- Tell any bulk sender about the send limits (100/hour per login, 40/hour per login and recipient
  domain) before launch; raise them in `provisioning/docker/rspamd/local.d/ratelimit.conf`.

## Cadence once this is all in place

Weekly (5–15 min): CI audit result and System health. Monthly (30 min): risk register rows marked
M or H, off-site age, key export. Quarterly (half a day): recovery drill on a scratch host and
`verify-key` from the escrowed copy. See §7 of the proposal for what to drop first if time runs out.

## Deliberately not planned

SSO/OIDC, SCIM/LDAP, domain-scoped roles, mail retention and legal hold, mail erasure, automatic
send suspension, DANE, SBOM/signed images, an update bot, and extra monitoring integrations. Each
has a trigger that would reverse the decision in §6 of the proposal.
