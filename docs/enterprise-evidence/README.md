# Enterprise evidence

What a security reviewer asks for, in one place. Each file here is **a record of something that
was run**, with a date, a person, and numbers. Do not write aspirations here; those live in
`docs/enterprise-readiness-proposal.md`.

| Evidence | File | Status |
|---|---|---|
| Rebuild drill from off-site copy and escrowed key (measured RTO) | `drill-YYYY-MM-DD.md` | **Not yet run** |
| Capacity statement (load test) | `capacity-YYYY-MM-DD.md` | **Not yet run** |
| Penetration test report and fixes | `pentest-YYYY-MM-DD.md` | Not commissioned |
| Test and coverage report for a release | `release-<version>.md` | Per release |

Standing documents: `../enterprise-slo.md`, `../risk-register.md`, `../secrets-map.md`,
`../dr-runbook.md`, `../../SECURITY.md`.

---

## Template: rebuild drill

Copy to `drill-YYYY-MM-DD.md`. Run on a **fresh** host, following only `docs/dr-runbook.md`, by
someone who did not write it if possible. Stop the clock only when System health is green.

```
Date:                         Operator:
Source backup (name, age):    Taken from: off-site copy / local
Key used: escrowed copy (yes/no — must be yes)
New host (provider, size):
Release restored:

Timeline (UTC)                      Clock   Minutes since start
1  Host ready, install started
2  Install finished
3  Backup fetched and decrypted
4  Secrets and keys restored
5  Database restored
6  File volumes restored, stack up
7  Verification table all pass
8  Registrar/PTR changes made          (outside our control; report separately)
9  System health green

Measured RTO (1 -> 7):                  minutes   Target: <= 240
Measured RPO (backup age at loss):      hours     Target: <= 24
Mail present and readable: yes/no      DKIM matches: yes/no     DNSSEC matches: yes/no
Audit chain intact (verify_audit_chain): yes/no

Steps that were wrong or missing in the runbook (and the fix committed):
-
Anything that needed knowledge not in the runbook:
-
Outcome: PASS / FAIL (re-run until PASS, then update the SLO table with the measured numbers)
```

## Template: capacity statement

Copy to `capacity-YYYY-MM-DD.md`. Run `provisioning/scripts/capacity_probe.py` from a *different*
machine against a staging server of the same size as production, then paste its output.

```
Date:                    Operator:
Server (provider, vCPU, RAM, disk):
Release:                 Mailboxes / domains / stored mail at test time:
Probe command:

<paste the probe's Markdown table here>

Reading:
- Comfortable up to N concurrent console users (p95 under 500 ms, no errors).
- Degrades at N; fails at N.
- Submission: N messages/s accepted; the send limit deferred after N.
- Limiting resource (CPU / RAM / disk / Postgres / Postfix): evidence:
Statement: this server size supports about N mailboxes of typical use. (State the assumption.)
```
