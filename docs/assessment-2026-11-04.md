# Assessment — findings on `main` at `82cd235`

Date: 2026-11-04. Scope: the whole repository — 1,294 tracked files, of which 770 are Python (749 under
`backend/`, 731 of those under `backend/apps/` including the 17 vendored `mydoc` modules), 117 templates
under `frontend/templates` (114 `.html` plus the three `.txt` email halves in §9.16), 56 files under
`frontend/static` (35 of them CSS/JS), 171 under `clients/android` (120 `.kt`/`.kts`), 99 under
`provisioning` (78 in `docker/`, 21 outside it, 35 `.sh` repo-wide), 24 under `.agents`, 15 in `docs/`,
15 in `examples/`, 5 in `requirements/`, the two CI workflows, the two `frontend/locale` catalog files, 18
`.toml`, 4 `.yml`/`.yaml`, 46 `.md`, and the thirteen top-level entries other directories do not already
account for (`.env.example`, `.gitignore`,
`.dockerignore`, `Makefile`, `manage.py`, `pyproject.toml`, `AGENTS.md`, `DESIGN.md`, `README.md`,
`CHANGELOG.md`, `SECURITY.md`, `branding_overrides.json`, `logs/.gitkeep`). Method: read-only inspection
plus the project venv (`venv/Scripts/python.exe`) on a Windows host, fourteen read-only delegate sweeps —
one per §9 zone as first drawn, several re-chunked into as many as four passes when a zone came back with a
coverage statement admitting a gap, and §9.15–§9.16 swept by this author directly — and independent
re-verification by this author of every claim graded High or Med, and of every claim a delegate contradicted
or could not support. §9 records how it covers each zone — as an explicit statement in §9.9–§9.16 and in
the section headings of §9.1–§9.8, per the note at the top of §9; those records are the evidence that no
zone was sampled.

Nothing here was executed against a production install; no provisioning script was run. Continues
the ID sequence of `docs/enterprise-readiness-proposal.md` §4 (F1–F16 are that document's findings).

**Provenance is marked on every finding.** `CONFIRMED` = this author read the cited code or ran the
cited command. `REPORTED` = produced by a delegated scan and not re-checked here. `REFUTED` =
claimed, tested, and wrong — recorded so it is not re-surfaced.

---

## 1. Summary

| ID | Sev | Area | One line | Status |
|---|---|---|---|---|
| F17 | High | CI | Two blocking CI gates fail on the current tip: lint and dependency audit | CONFIRMED |
| F18 | High | History | A commit with unresolved conflict markers is published in `main`'s ancestry | CONFIRMED |
| F19 | Med | History | 36 of 74 local tags disagree with the remote; a backup tag hijacks `git describe` | CONFIRMED |
| F20 | High | Dev env | Every `mail` migration from `0003` and `accounts` from `0007` is unapplied locally | CONFIRMED |
| F21 | High | Access | `RoleService.effective_permissions` fails open: roleless staff hold every permission | CONFIRMED |
| F22 | High | Access | `mail.manage` can mint an API key carrying the *mailbox owner's* scopes | CONFIRMED (mechanism) |
| F23 | Med | Access | MFA attempt counter increments inside a swallow-everything `except` | CONFIRMED |
| F24 | Med | Delivery | `ping()` sends without claiming, so a sweep can send the same event twice | CONFIRMED |
| F25 | — | Delivery | Sweep can never recover a PENDING row with NULL `next_attempt_at` | REFUTED — unreachable |
| F26 | **High** | Access | `users.manage` rotates *any* owner's API key and receives the new secret | CONFIRMED |
| F27 | Med | Access | The anonymous setup page prints the superuser's email and the install path | CONFIRMED |
| F28 | High | Supply chain | 41 known CVEs in the pinned production lock (certifi, pillow) | CONFIRMED |
| F29 | Med | Access | TOTP codes are not single-use: ±1 step drift, no accepted-counter recorded (~90 s) | CONFIRMED |
| F30 | Med | SSRF | Webhook URL is IP-validated at add time but re-resolved at connect (DNS rebind) | CONFIRMED |
| F31 | Med | Governance | A plugin manifest can hardcode `allow_private=yes` with no operator prompt | CONFIRMED |
| F32 | **High** | Frontend | Stored XSS sink: branding font fields are unvalidated and injected into `base.html` (browser impact gated by an independent nginx CSP — §8) | CONFIRMED |
| F33 | Med | CLI | `manage.py storage upload --purpose backups <file>` cannot accept its filename | CONFIRMED locally |
| F34 | Med | Tests | 82 failures + 1 collection error on this host, in 6 cause groups (5 host, 1 real) | totals from the sweep; bash group + F33 re-verified here |
| F35 | Med | i18n | 2,267 trans tags, but the only catalog is `en` with 299/299 empty translations | CONFIRMED |
| F36 | Med | Tests | The URL contract gate passes 18/18 only because test settings disable the redirect | CONFIRMED |
| F37 | Low | Docs | Template registry, SLO citation and `AGENTS.md` version are stale | CONFIRMED |
| F38 | **High** | Access | Deleting a role mass-escalates every member: `SET_NULL` feeds the F21 fail-open | CONFIRMED |
| F39 | Med | Access | Changing or resetting a password revokes no other session, and the code comment says it does | CONFIRMED |
| F40 | Med | Storage | Branding logo upload stores the client's own `Content-Type` and serves it back verbatim | CONFIRMED |
| F41 | Med | nginx | `location /static/` declares its own `add_header`, so it silently drops CSP, HSTS, nosniff and X-Frame-Options | CONFIRMED (static read) |
| F42 | Low | Access | A system-settings write (update-check toggle) sits behind read-grade `console.access` | CONFIRMED |
| F43 | Low | Access | Self-service MFA disable leaves `mfa_required=False` permanently | CONFIRMED |
| F44 | **High** | Telemetry | `auth_events()` keeps the **oldest** 5,000 rows, so a login spray hides the current hour from detection and from autoblock's known-good set | CONFIRMED |
| F45 | Med | Telemetry | The errors API's memory fallback returns dicts its own schema rejects → 500 exactly when the DB is down | CONFIRMED |
| F46 | Med | Telemetry | A network-bound LLM call runs inside `transaction.atomic()` in the digest pass | CONFIRMED |
| F47 | Med | Telemetry | The mail-trace page tails ~72 MB of logs into a Python list on one GET | CONFIRMED |
| F48 | Med | Telemetry | A threat alert is marked notified *before* it is sent, so a mail outage spends the alert | CONFIRMED |
| F49 | Med | Domains | Deleting a domain leaves its 0644 DKIM private key on disk, and Rspamd keeps signing with it | CONFIRMED |
| F50 | Med | DNS/Domains | Two divergent domain-delete paths; the provisioning one never withdraws the published DNS zone | CONFIRMED |
| F51 | Low | DNS | Provider credentials survive `SECRET_KEY` rotation only as undecryptable blobs; a legacy plaintext path still decrypts | CONFIRMED |
| F52 | Low | Mixed | Assertion-free test, CAA quoting gap, write-behind-GET, dead `verify_records`, `next()` without default, synchronous provider calls | CONFIRMED |
| — | — | Access | `X-Forwarded-For` can be spoofed to beat token network allow-lists | REFUTED as stated |
| — | — | Dev env | Production `users` table drifts from the model | REFUTED — DDL is wired |
| — | — | Secrets | No tracked credential, no `shell=True`, no reachable raw-SQL interpolation | CONFIRMED clean |

### 1.1 What the full sweep added

The table above is the first pass (F17–F52), written before the codebase had been read end to end. The
sweep required by §9 then covered every zone with no sampling and added **F53–F228**. Totals for the
document as a whole: **212 numbered findings, F17–F228 with no missing number — 45 High, 123 Med, 43 Low**,
and one ungraded row, F25, which is a claim the sweep disproved rather than a defect. F34, F51 and F52 are
graded in the first-pass table above rather than only under their own headings, and are counted there: F34
as Med (the suite-status line, which *is* severity-graded), F51 and F52 as Low. Provenance markers stand
throughout: **18 distinct claims are marked REFUTED** — asserted by a delegate or an earlier pass and
disproved by direct reading — and **13 claims are marked SUSPECTED in §9** (F176 is a fourteenth, labelled
only in §11), meaning the missing proof is named rather than papered over. Every one of these figures was
re-measured after §9.16 was written — by machine count over the `**Fnnn — Severity — …**` headings and over
the marker occurrences — and the REFUTED total is de-duplicated by claim: two claims (the
`X-Forwarded-For` row and the production-`users`-table row) appear once in the first-pass table above and
once again in §7's correction table, which is why the document contains 20 REFUTED mentions of 18 distinct
claims.

| Sweep section | Zone | Files | Findings | Highs |
|---|---|---|---|---|
| §9.1 | `core/telemetry` | 58 | F44–F48 (first pass, re-verified) | F44 |
| §9.2 | `dns` + `domains` | 92 | F49–F52 | — |
| §9.3 | `mail` | 214 | F53–F61 | F54 |
| §9.4 | `core/assistant` + `core/releases` | 75 | F62–F67 | F62 |
| §9.5 | `core/plugins` | 58 | F68–F77 | F68 F69 F70 |
| §9.6 | `devices` + `mydoc` + `backend/config` + build files | 75 | F78–F84 | — |
| §9.7 | `core/storage` + `core/base` | 88 | F85–F94 | F85 |
| §9.8 | `provisioning/docker` | 78 | F95–F113 | F95 F96 |
| §9.9 | `core/platform` + `core/website` + `core/tests` | 76 | F114–F126 | — |
| §9.10 | `frontend/templates` | 114 `.html` (+3 `.txt` → §9.16) | F127–F138 | F127 |
| §9.11 | `clients/android` | 171 | F139–F153 | F139–F144 |
| §9.12 | `frontend/static` | 56 (35 CSS/JS) | F154–F165 | F154 |
| §9.13 | requirements, CI, agent skills, repo state | 74 | F166–F180 | F166 F167 F168 F169 |
| §9.14 | `examples/python`, `docs/`, skill `references/` | 24 | F181–F191 | F181 F182 |
| §9.15 | `provisioning/` outside `docker/`, vendored `mydoc`, doc/skill residue | 70 | F192–F225 | F192–F204 |
| §9.16 | the three `.txt` email templates + `logs/.gitkeep` | 4 | F226–F228 | — |

The 35 sweep Highs, in one line each, because they change what ships first:

| ID | One line | Detail |
|---|---|---|
| F54 | The console's own IMAP client disables certificate checking for every mailbox read | §9.3 |
| F62 | A plugin manifest may point the assistant at any http(s) host, and that host receives the API key | §9.4 |
| F68 | `publish_all()` renders and writes the shared runtime files outside every lock | §9.5 |
| F69 | A plugin row that fails to render is skipped, and skipping means "delete this setting" | §9.5 |
| F70 | One validator raises `ValueError` instead of returning a message, so a bad manifest aborts the whole render | §9.5 |
| F85 | Storage authorisation only exists on the path nginx does not take | §9.7 |
| F95 | The internal mail relay accepts mail from every container on the network | §9.8 |
| F96 | Dovecot's LMTP and auth sockets are world-writable in a volume shared with three other containers | §9.8 |
| F127 | Secondary DNS servers are joined with a separator the template then HTML-escapes, so the field silently loses entries | §9.10 |
| F139 | The Android composer transmits `Bcc` recipients to the server | §9.11 |
| F140 | Credentials stay in a plaintext store after the keystore path exists | §9.11 |
| F141 | A corrupt mail store is read as empty and then rewritten over the original | §9.11 |
| F142 | Authentication can be sent in cleartext over a connection the user believes is TLS | §9.11 |
| F143 | The POP3 cursor advances past messages that failed to download, so mail is lost silently | §9.11 |
| F144 | A failed mutation is recorded as applied, and a queued send is reported as "sent" | §9.11 |
| F154 | Reflected XSS in the setup wizard: the DNS-provider field round-trips from `POST` to a script's `data-*` attribute | §9.12 |
| F166 | `base.txt` and `prod.lock` pin incompatible majors of `redis`, so what is declared is not what runs | §9.13 |
| F167 | The same drift for `gunicorn`, the process manager that serves the console | §9.13 |
| F168 | CI installs `testing.txt` (dev range) rather than the hash-pinned lock the image uses | §9.13 |
| F169 | `find-polluter.sh` runs `npm test … \|\| true` in a repo with no `package.json`: a permanently green no-op | §9.13 |
| F181 | Install and disaster recovery are both `curl … \| sudo bash` with no checksum, signature or pinned ref | §9.14 |
| F182 | `docs/ifinmail_proposal.md` describes a repository that does not exist and a licence the README contradicts | §9.14 |
| F192 | The daily backup contains no mail: it looks for a volume name this stack never creates, and the guard has no `else` | §9.15 |
| F193 | `make backup` — the command the DR runbook tells the operator to run — fails at step 1 because the script never passes `--env-file` | §9.15 |
| F194 | "Backups are encrypted with GPG" is false unless the operator overrides a default of `BACKUP_ENCRYPT=false` | §9.15 |
| F195 | A backup it cannot verify still prints "Backup complete", and it records `last-backup-at` before verifying | §9.15 |
| F196 | The weekly restore drill can never pass: it hands `pg_restore` inside the container a host path that is not mounted | §9.15 |
| F197 | The drill counts every SKIP and WARN as a pass, so "Restore test passed" is reachable with nothing tested | §9.15 |
| F198 | The drill decrypts the whole backup into `/backups` as plaintext, never removes it, and next week drills that instead of the encrypted archive | §9.15 |
| F199 | `uninstall.sh --keep-backups` deletes the GPG key that opens the backups it just kept | §9.15 |
| F200 | `uninstall.sh --remove-docker` deletes `/var/lib/docker` — every unrelated project's volumes — while its header promises Docker stays | §9.15 |
| F201 | `obtain-ssl.sh` deletes the live key, archive and renewal state of any certificate not issued by Let's Encrypt, on a backup it never verifies | §9.15 |
| F202 | fail2ban is never installed, its jails watch logs this stack never writes, and its filters cannot match the lines it does write | §9.15 |
| F203 | `make firewall` resets the host firewall before it asks permission, and prints its Docker guard as applied whether or not a rule landed | §9.15 |
| F204 | `monitor.py` is a phantom: nothing runs it, nothing reads what it writes, and `enterprise-slo.md` already cites its thresholds as the standard | §9.15 |

Five of these are the sweep's structural discoveries rather than any single file: the dependency drift
class (F166/F167/F168 — the lock, the range files and CI describe three different systems), the
client-side data-loss class (F141/F143/F144 — the Android app loses work in three independent ways, all
silent), the documentation-is-not-proof class (F181/F182/F186/F187/F191 — hand-maintained counts,
paths and citation columns that no job recomputes), the backup-and-drill class (F192–F198 — every step of
the chain that is supposed to prove the data is recoverable is broken in a different way, and each break
announces itself as a success), and the phantom-control class (F202/F204 — a brute-force guard and a
monitoring agent that exist as files, are cited by the documentation as the control in place, and are
never run).

---

## 2. Publication and history integrity

**F18 — High — broken code is now permanent in published history.**
`cf34786` ("v0.0.2") is a merge commit committed with 10 files still holding literal
`<<<<<<<` / `=======` / `>>>>>>>` lines; three of them (`backend/apps/mail/tasks.py`,
`backend/apps/mail/services/webhooks.py`, `backend/apps/mail/services/compliance.py`) were invalid
Python, so `mail` could not import there. It is a parent of the pushed `82cd235`, therefore an
ancestor of `origin/main` and reachable by checkout. Only a rewrite of `main` removes it. The
current tip itself is clean — a repo-wide marker scan returns zero hits.

**F19 — Med — tag divergence and a `describe` hijack.**
Local `v0.0.1`–`v0.0.4` and `v0.0.43`–`v0.0.74` point at commits the remote's same-named tags do not
(`v0.0.74`: local `ef80f1c` vs remote `3d59198` — identical trees, different commits, because the
history was rewritten and force-pushed). `git push --tags` is rejected on each of the 36. The
remediation safety tag `backup/broken-v0.0.2` sits in `refs/tags/`, so `git describe --tags` now
returns `backup/broken-v0.0.2-6-g82cd235` — any build stamping its version from `describe` is
mislabelled. *Pointer:* recovery refs belong in `refs/backup/`, not `refs/tags/`.

**Version strings are ambiguous in the repo.** `CHANGELOG.md:3` opens with `## v0.0.75` and no such
tag exists; 108 commits on `origin/main` are titled `v0.0.1`; each `v0.0.43`–`v0.0.74` message
appears twice after the rewrite; and the commit that fixed all this is itself titled `v0.0.2`,
which is also an old tag. `REPORTED` by the history sweep.

---

## 3. CI: what actually happens on a push

`.github/workflows/ci.yml` `backend` job runs, in order: `check --deploy` (`:38`), the test suite
with a coverage gate (`:41`), `pip_audit` (`:45`), `mypy` (`:48`), then Lint (`:50-53`). Reproduced
locally on `82cd235`:

| Step | Command | Local result | Pre-dates the merge? |
|---|---|---|---|
| Django checks | `manage.py check --deploy` | **exit 0**, 5 non-fatal warnings (W004/008/009/012/016) | passes |
| Test suite | `pytest -q --cov=backend` | **82 failed / 2187 passed here**, but 74 of those are host artifacts (§8). On the Linux runner the bash, encoding, symlink and timezone groups should clear, leaving F33 as the one likely genuine failure — and the `fail_under = 70` coverage gate (`pyproject.toml:105`) is unmeasured. **Not observed.** | unknown |
| Dependency audit | `python -m pip_audit -r requirements/prod.lock --disable-pip` | **exit 1** | yes |
| Type check | `mypy` | could not run — mypy is absent from this venv | unknown |
| Lint | `ruff check backend/` | **exit 1** | yes |
| Format | `ruff format --check backend/` | never reached (see below) | yes |
| compose / secrets / shell | `docker compose config`, gitleaks, shellcheck | tools absent on this host | unknown |

**F17 — High — the "blocking" lint gate is failing, and the format half of it is invisible.**
`ci.yml:50-53` puts `ruff check backend/` and `ruff format --check backend/` in one multi-line
`run:` block, which Actions executes under `bash -e`; the first command exits 1, so the format
check never runs and its 78-file backlog is masked. Ruff reports **283 errors** here: 256 `E501`,
16 `I001`, 5 `SIM105`, 4 `E741`, 1 `F541`, 1 `SIM102`. `[tool.ruff]` in `pyproject.toml` sets
`line-length = 100` and selects `E, F, I, N, W, UP, B, SIM` with no `ignore` and no
`per-file-ignores`, so the findings are real against the project's own standard, not a stricter
tool default. `git diff --name-only 862ccc0 82cd235` is six files, **none under `backend/`**, and
`ci.yml` is unchanged — so `backend` was already red on the previous remote tip. The claim at
`docs/enterprise-slo.md:34-35` that this gate is enforced is not true in practice.

**F28 — High — 41 known vulnerabilities in the pinned production set.**
`pip_audit` exits 1 with "Found 41 known vulnerabilities in 2 packages": `certifi 2026.7.22`
(fix `2026.10.18`) and `pillow 12.3.0` (fix `13.0.0`, a major bump). This is the CI step whose own
comment says it "fails the build on any known CVE in the locked production set", and it also
pre-dates the merge. `certifi` is the trust store every outbound HTTPS call uses — including
webhook delivery — and `pillow` is reached through image handling in storage. Because the build
installs from a hash-pinned lock (`--require-hashes`, risk register R6/R7), this needs a re-lock,
not a `pip install -U`.

**`mypy` is an unmeasurable risk from this host.** It is declared at
`requirements/development.txt:11` but not present in this venv, and CI installs it at `:34` before
running it at `:48` — so the type gate will execute in CI and nobody can predict its verdict from
here. Same for `docker compose config`, gitleaks and shellcheck (31 shell files in the shell job's
glob). The overall CI verdict in this document is therefore **computed from the workflow's own
commands, not observed from Actions runs**: `gh` is not installed on this host.

---

## 4. Development environment

**F20 — High — the local database is roughly two releases behind, and nothing reports it.**
`manage.py showmigrations mail`: `[X] 0001`, `[X] 0002`, then `[ ] 0003_sandbox` … `[ ]
0012_campaign_tracking`; `accounts 0007`–`0016` likewise unapplied. `db.sqlite3` has 30 tables and
none of `mail_webhook_delivery`, `mail_webhook_endpoint`, `mail_campaign`,
`mail_campaign_recipient`, `mail_suppression`, `mail_pending_message`, `mail_sandbox_message`,
`mail_agent_inbox`. Running webhooks or campaigns locally raises `OperationalError: no such table`.
`makemigrations --check --dry-run` answers "No changes detected" and so **conceals** this — model
state matches the migration files; the files were simply never applied. Consequence for this
assessment: no runtime behaviour of webhooks, campaigns, audiences, templates, scheduled sends or
tracking was exercised anywhere in §6. All of it is static analysis.

**Corrected: production does *not* drift.** The `users` table is unmanaged
(`backend/apps/accounts/models/__init__.py:44,47`, `managed = False`), and the local sqlite copy is
missing `password_change_required` and `mfa_remind_after` (12 columns vs 14) because `accounts`
migrations `0007`/`0008` are state-only. That part is real. But the earlier suspicion that
production drifts the same way is **refuted**: both columns are added by
`provisioning/docker/init-db.sh:52,54` and by `provisioning/docker/db-upgrade.sql:22-32,35`, and
`db-upgrade.sql` *is* invoked — `provision.sh:474` inside `ensure_db_grants`, run before the api
starts for existing installs (`provision.sh:641-650`), reachable through `make provision`
(`Makefile:97`) and `deploy.sh:6`. No model column is absent from the DDL, and the other unmanaged
models (`domains`, `dkim_keys`, `mailboxes`, `aliases`, `dns_provider_config`) are covered too.
One fragility worth keeping: `db-upgrade.sql:28` uses `ADD COLUMN` without `IF NOT EXISTS`, and the
schema contract test (`test_schema_contract.py:31-34`) only ever exercises the `init-db.sh` path.

---

## 5. Access control

**F21 — High — the role model fails open, twice.**
`backend/apps/accounts/services/roles.py:66-83`: inactive → nothing; superuser → `ALL_PERMISSIONS`;
non-staff → nothing; then
* `:73-74` staff with no `role_id` → `set(ALL_PERMISSIONS)` ("legacy staff: unchanged behavior");
* `:81` a `role_id` that no longer resolves → `set(ALL_PERMISSIONS)` ("dangling reference: fail
  open to legacy").

`ALL_PERMISSIONS` includes `roles.manage` and `setup.manage`, so a roleless staff login can grant
roles — precisely the boundary the seeded `administrator` role is documented to enforce
(`backend/apps/accounts/types/permissions.py:66-68`, "Cannot grant roles"). Reachable, not
theoretical: mailbox creation sets `is_staff` and assigns no role
(`backend/apps/mail/services/mailboxes.py:154`, `:158`). A deleted custom role also leaves every
former member at `ALL_PERMISSIONS` via the dangling path.

**F26 — High — `users.manage` takes over any API key in the deployment.** *(new; confirmed line by
line)*
`backend/apps/accounts/views/api_keys.py:106-131` is gated by `@login_required` +
`_MANAGE = require_perm(PermissionCode.USERS_MANAGE)` (`:31`). It loads the token with
`TokenService.get(...)`, which filters **by primary key only**
(`backend/apps/accounts/services/tokens.py:191-198`, `filter(pk=token_id).first()`) — no owner, no
domain scoping. The rotate call then passes `row.user` (`api_keys.py:125`), i.e. the **victim** as
the token's owner, so the ownership filter inside `rotate` (`tokens.py:323`,
`filter(user=user, …)`) can never fail, and the freshly minted plaintext is written into the
**actor's** session (`api_keys.py:126-131`) and rendered back to the actor as `revealed`
(`api_keys.py:44`, "Copy the new secret below"). `revoke` is the same shape (`:143`). Step-up
(`:120`) re-authenticates the actor's own password, so it does not gate cross-owner use
(`stepup.py:22-36`). Net effect: one `users.manage` login — or any roleless staff login, by F21 —
can rotate every integration key in the installation and read the replacement secret, silently
breaking the victim's integrations in the process. This defeats the per-owner token model that
F7/F10 and `TOKEN_SCOPES` were built to protect.
*Pointer:* scope the lookup to the caller unless the caller holds a documented
"manage-all-keys" right, and never place another owner's secret in this session.

**F22 — High on mechanism, chain not proven — a mailbox key can outgrow its requester.**
`backend/apps/accounts/views/profile.py:212-230`, gated by `require_perm(MAIL_MANAGE)` (`:40`) plus
step-up (`:217`). `_token_owner` (`:201-206`) resolves the login **from the mailbox address**
(`MailUser.objects.filter(email=full).first()`) and `TokenService.create` is called with *that* user
(`:225`), not `request.user`. `tokens.py:229` enforces
`wanted & RoleService.effective_permissions(user)` under the comment "A token can never exceed its
owner's current permissions" — correct arithmetic, wrong actor. `_get_mailbox` (`profile.py:44-48`)
filters only by `id`, so any `mail.manage` login can address any mailbox in the deployment, and by
F21 a mailbox whose address is a roleless-staff login is unrestricted. Mitigating, verified here:
`TOKEN_SCOPES` excludes `roles.manage` and `setup.manage` (`types/permissions.py:43-47`), so a
stolen key cannot grant roles or drive the setup wizard — but `system.manage` and `users.manage`
are carryable, which is enough to reach F26. Not proven: whether `StepUpService.confirm` can be
satisfied for a target the attacker does not control.
*Pointer:* pass the actor, or intersect with `actor ∩ target`.

**F27 — Med — the anonymous setup page publishes the superuser identity and install path.**
`views/auth.py:266-275` renders the pending superuser's email (from
`services/initial_admin.py:47-58`) and `IFINMAIL_INSTALL_DIR` to an unauthenticated visitor
(`login_view`, `auth.py:77`; route `urls.py:255`). `frontend/templates/admin/login.html:52` goes
further and prints the command to recover the bootstrap password from
`<install_dir>/provisioning/.env`. The window is "until the password is rotated", and risk register
R8 already notes that the bootstrap password persists in `provisioning/.env` after install.
Login enumeration is real but secondary: `auth.py:233-250` distinguishes inactive accounts, and
`auth.py:112-127` resends a verification mail on an existence check alone, bounded to 10 per 5
minutes per IP (`auth.py:100-105`). **Refuted sub-claim:** the `MAIL_HOSTNAME` output at
`auth.py:190` is inside the authenticated non-staff branch (`:171,175`) and the hostname is public
by design.

**F29 — Med — TOTP codes are not single-use.**
Step is 30 s with drift ±1 (`services/mfa.py:33-35`) and `verify_code` accepts step−1, step, step+1
(`:87-93`), so a code is valid for ~90 s. `verify_login` records only `last_used_at`
(`:267-269`) and `TOTPDevice` has no counter column (`models/__init__.py:85-95`), so nothing
prevents replay inside that window. Reachable on login (`views/mfa.py:230`), second-factor disable
(`mfa.py:238`) and enrolment confirm (`mfa.py:212`). Recovery codes *are* single-use (`:280-288`),
which shows the intended pattern exists. **Correction to the reported version:** step-up does not
use TOTP at all — it is password-based — so this is a two-factor replay, not a step-up bypass.
Precondition is still "password + one observed live code".

**F23 — Med — the MFA limiter is inconsistent in six lines.**
`views/mfa.py:207-212` increments the attempt counter inside `try: … except Exception: pass`, so
any cache error silently drops the increment; the read that decides lockout (`:204`) is *not*
guarded, so during a cache outage the verify view raises before the swallow can matter — the second
factor becomes an availability failure rather than a bypass. The same swallowing pattern is
`REPORTED` at `accounts/services/exposure.py:105`,
`core/telemetry/services/telemetry_service.py:470,532` and `mail/services/compliance.py:221`.

**F38 — High — deleting a role hands every member the whole permission set.** *(new; the mass-
escalation arm of F21, confirmed by reading both ends)* F21 showed that a staff login whose
`role_id` is NULL or unresolvable receives `ALL_PERMISSIONS` (`roles.py:73-74`, `:81`). The FK that
feeds it is `role = models.ForeignKey('accounts.Role', null=True, blank=True, on_delete=models.SET_NULL, …)`
at `backend/apps/accounts/models/__init__.py:52-54`. So one `Role.objects.delete()` — the normal
outcome of tidying up a custom role — nulls `role_id` on every user who held it and turns all of
them into legacy-staff superusers, including `roles.manage` and `setup.manage`. There is no guard in
the delete path and the seeded roles are protected only by the last-holder check at `roles.py:96`,
which counts holders rather than refusing deletion of an assigned role. Reachable over the API too:
`require_scope` re-reads live permissions
(`backend/apps/accounts/viewsets/auth.py:107`, `if not RoleService.has_perm(auth.user, code)`) —
correct design, wrong oracle — so a token minted for one of those ex-role users passes every scope
check, because `has_perm` resolves through the same fail-open. `PROTECT` (or clearing members
before delete, with a prompt) is the whole fix; the fail-open at `roles.py:74`/`:81` must go with it,
or the next dangling reference reproduces this.

**F39 — Med — a stolen session survives a password change, and the comment claims the opposite.**
`backend/apps/accounts/views/account.py:79-80` reads "Keep this session signed in; other sessions
die with the old password" and then calls only `update_session_auth_hash(request, request.user)`.
That call preserves the *current* session; it does not touch any other. Django's default session
backend stores no credential hash, so nothing invalidates the rest — and `backend/apps/accounts/`
has no middleware that would: `middleware.py` implements `PasswordChangeEnforcementMiddleware`,
`SetupRequiredMiddleware`, `ApiResponseHeadersMiddleware`, `MFAEnforcementMiddleware`,
`FormEndpointGetMiddleware` and `SessionIdleTimeoutMiddleware`, none of which compares an auth hash.
`ProfileService.change_password` (`services/profile.py:27-41`) ends at
`user.save(update_fields=['password', 'password_hash'])`. The capability to do it exists in the same
app — `services/sessions.py:38,65,93` and `views/users.py:172-177` enumerate and delete sessions by
key — it is simply not called from the password path. Consequence: rotating the password of a
compromised administrator logs the attacker in nowhere; the user must also press "sign out other
sessions", and the reset flow gives no reason to expect that. Same for
`views/first_password.py:40`, `views/mailboxes.py:359` and `views/setup.py:84`.
*Pointer:* delete `Session` rows for that user on change/reset, or add an auth-hash check to the
middleware, and stop asserting the opposite in a comment.

**F42 — Low — a system-settings write behind a read-grade gate.**
`views/system_health.py:104-118` (`system_health_updates`) is gated by `_CONSOLE`
(`= require_perm(PermissionCode.CONSOLE_ACCESS)`, `:15`) yet calls `UpdateService.set_enabled(...)`
(`:113`) to switch the six-hourly release check on and off for the whole installation. Every other
setting write in the app requires `SYSTEM_MANAGE` (sending, suppressions, file storage, marketplace
mutate, appearance default, log purge). The action is recorded in the audit trail (`:114-116`), so
this is a governance inconsistency rather than a silent one — but any console-capable staff member
can turn the update check off and the install then stops hearing about new releases.

**F43 — Low — turning MFA off is sticky.** `MailUser.mfa_required` defaults to `True`
(`models/__init__.py:46-47`, with the comment "Console staff must hold a verified second factor
unless they turn it off themselves"), and `MFAEnforcementMiddleware` exempts a session when
`mfa_required is False and not TOTPService.enforced()`. A self-service disable therefore leaves the
login permanently exempt from the enrolment prompt for as long as enforcement stays off, even
though re-enrolling resets the flag — the state a person chose months ago keeps deciding access
today.

**Two more authorization gaps in the same shape as F26, found by the accounts sweep and confirmed
by reading** *(the sweep also produced an endpoint→gate table; every row not listed here was
gated and scoped correctly, including all of `users/*`, `mailboxes/*`, `setup/*`, the passkey and
MFA paths, and `api_keys` create, which does use `request.user`)*.
* Anonymous mailbox enumeration: `check_username_availability` answers whether an address exists,
  and `views/auth.py:112-127` will send a verification mail on an existence check alone — the
  resend-verification entry point lives on the anonymous login page. Both are bounded (the mail at
  10 per 5 minutes per IP, `auth.py:100-105`) but they are a free directory probe and an
  email-blast trigger on a page with no session at all.
* `users.py` `invite` is the one privileged write in the users group without a step-up prompt, while
  delete and admin-grant both have one.
**Governance violations in `accounts`, both confirmed:** `views/api_keys.py:159-169` imports
`backend.apps.mail.models.SandboxMessage` into an accounts view and queries it directly
(`SandboxMessage.objects.all()` at `:163`, `.filter(pk=message_id)` at `:169`) while the mail
`services.sandbox` module is imported on the very next line — a cross-app view→model read that the
AGENTS.md "all model access through services/" rule forbids. `templatetags/directory_tags.py:22`
runs `UserProfile.objects.filter(directory_hidden=True).count()` inside a template tag, i.e. ORM in
the presentation layer. Both are small, both are the kind of drift the governance rule exists to
catch, and no test enforces either.

---

## 6. Webhook and campaign delivery

**F24 — Med — `ping()` bypasses the claim added to stop double-sends.**
`webhooks.py:380-397` creates the delivery with `next_attempt_at=timezone.now()` and calls
`attempt()` **directly**, never `_claim()`. Everything else routes through `deliver()` (`:548-553`),
which claims first with the conditional UPDATE at `:538-545` — the invariant introduced by `17e8e6a`
("claim webhook deliveries before sending"). The ping row stays PENDING and due for the whole HTTP
request, so the minute `sweep()` (`:597`, `PENDING` + `next_attempt_at__lte=now`) sees unclaimed
work, queues it, and `_claim()` succeeds: the same `event_id` is delivered twice. Low impact for a
test event, but it is a hole in the exact guarantee the claim exists to provide.

**F30 — Med — SSRF DNS rebinding: validated IP is never pinned to the connection.**
`check_url` resolves the host and refuses loopback, private and metadata ranges
(`webhooks.py:145-176`, `_ALWAYS_BLOCKED` check at `:168`) — and then returns the **original URL
string** (`:175`). `_OPENER` is a plain `build_opener(_NoRedirect())` with no custom connection
handler (`:451`), so `_OPENER.open(request, …)` (`:457`) resolves the name again at connect time.
Re-validation on every send does happen (`attempt()` → `check_url(row.url, current)` at `:473`,
`resolve` defaulting to `True` at `:145`), which narrows the window to the gap between the two
resolutions rather than leaving it at add time — that part of the earlier report was too generous
to the code. Redirects are refused (`:446-451`) and responses are capped (`TIMEOUT_SECONDS`,
`MAX_RESPONSE_BYTES`, `:457-458`). *Pointer:* pin the validated address, or use a resolver-checking
handler.

**F31 — Med — plugin manifests can open the private-network door without asking anyone.**
`allow_private` / `allow_http` feed straight into the policy (`webhooks.py:136-137`) and originate
from manifest `contributes.values` (`plugins/.../manifest.py:537-564`); the only validation is
`_one_of('yes','no')` (`plugin_points.py:358-360, :705-711`). A plugin author can therefore ship a
manifest that hardcodes `allow_private = 'yes'` with no operator-visible prompt, which converts F30
from "narrow TOCTOU" into "reach the internal network at will". No bundled manifest in this repo
sets either flag (verified by grep), so this is a governance gap rather than a live misconfiguration.

**Refuted, keep out of the register.**
**F25 — "the sweep can never recover a PENDING row whose `next_attempt_at` is NULL".** Every new
delivery is created *due* (`webhooks.py:352`; `ping()` at `:393`), and `next_attempt_at=None` is
written only with a terminal status — `DELIVERED` (`:498`) or `FAILED` (`:510`). A PENDING+NULL row
does not occur, and the `Q(next_attempt_at__isnull=True)` arm in `_claim` (`:540`) is defensive.
The companion claim — that a broker outage at enqueue time loses deliveries — is wrong for the same
reason, since `_schedule`'s handler (`:432`) hands off to the sweep and those rows are due.

**REPORTED, not re-verified here.**
* Six Celery tasks without time limits, including `deliver_webhook` (`mail/tasks.py:53`),
  `apply_postfix_overrides` (`:25`), `purge_sandbox` (`:41`), `expire_agent_inboxes` (`:155`),
  `expire_approvals` (`:163`), `check_outbound_containment` (`:31`) — against the note in that
  file's own header (`:13-21`). A hung task holds a worker.
* `webhooks.py:464` `attempt()` → `policy()` → capability resolution re-scans
  `PluginInstallation.objects.all()` and re-renders manifests per delivery
  (`plugins/services/lifecycle.py:232-245`); a 25-id chunk costs ~50 table scans.
* `delivery_events.py:274-287` stores the log-scan offset with an unlocked cache get-then-set, so
  overlapping `mail.scan_delivery_events` runs can lose lines; after a cache flush the scanner jumps
  to end-of-file and silently skips the backlog.
* `campaign_runner.py:412` `_mark` updates by primary key without re-checking the claim token, so a
  slow worker can clobber a re-claimed row once `LOCK_SECONDS` expires. The claim itself
  (`:403-405`) is atomic.

---

## 7. Also corrected from the first pass

| Claim (from the earlier scan) | Verdict | Why |
|---|---|---|
| `X-Forwarded-For` trust lets callers spoof the token network allow-list and audit IP | **REFUTED as stated** | nginx appends with `$proxy_add_x_forwarded_for` on every `api:8000` location (`provisioning/docker/nginx/conf.d/ifinmail.conf:145,170,181,196,208,266`; `/dav/` overwrites with `$remote_addr` at `:227`), so the **last** element — which the code picks at `api_access.py:31-37` / `client_ip.py:16-21` — is nginx's own and is not attacker-controlled. Residual: there is no trusted-proxy allowlist (`production.py:49,53` set `SECURE_PROXY_SSL_HEADER` / `USE_X_FORWARDED_HOST` without one), and while the api binds `127.0.0.1:8000` (`docker-compose.yml:416-417`), any container on the shared network can post a self-authored XFF. Needs runtime confirmation. *(Citation corrected in this pass: the file is `nginx/conf.d/ifinmail.conf`, and three of the six line numbers were off by 4–5 — the claims themselves re-verified line by line.)* |
| nginx emits a second, non-demotable CSP, which changes F32's impact | **CORRECTED in §8** | `provisioning/docker/nginx/conf.d/ifinmail.conf:106` adds its own `Content-Security-Policy` with `script-src 'self'` and `proxy_hide_header` at `:98-100` does not hide CSP, so Django's `CSP_REPORT_ONLY` env var cannot strip every script guard. See the F32 correction. |
| `TokenService.create` ignores the caller's permissions entirely | **Overstated** | It does intersect (`tokens.py:229`); the defect is *whose* permissions it intersects with (F22), and `TOKEN_SCOPES` already blocks `roles.manage`/`setup.manage`. |
| Production `users` table is missing model columns | **REFUTED** | See §4 — `db-upgrade.sql` is invoked by `provision.sh:474`. Only the local sqlite dev copy drifts. |
| The two `SyncScriptTests` failures indicate a product bug | **No** | They are a Windows artifact of the harness (CRLF script writes and `C:\…` paths handed to bash); the script guards its `/var` paths (`sync-overrides.sh:57,243,256`) and the tests override FILE/STATE/POSTCONF/POSTFIX, so they should pass on the Linux runner. Still worth a skip-guard, since `test_mailboxes.py:277-278` only skips when bash is missing. |
| …but the CRLF/`/var` explanation was **also wrong** (supersedes the row above) | **Corrected** | Python-spawned `bash` never starts on this host. `subprocess.run(['bash','--version'])` returns rc=1 with UTF-16 output beginning `Failed to attach disk 'C:\Users\…\ifincyber\artifacts\wsl\ifincyber-lab\ext4.vhdx'`, i.e. a dead WSL distro shadowing the `bash` name, while `command -v bash` resolves to Git's own binary and works. The script aborts at launch, so CRLF and `/var/run` are never reached. This one host defect explains **42** of the 82 failures (§8). Not the project's bug, and not fixable from here. |
| `test_url_contract.py` fails 2/18 because `/docs/` redirects to setup | **REFUTED** | 18 passed, 0 failed, reproduced twice (`--reuse-db` and `--create-db`). The reason it *cannot* fail on that path is F36: `backend/config/settings/testing.py:49` sets `SETUP_REQUIRED_REDIRECT = False`, disabling the gate for the whole suite. |
| The `mail` app's failing tests imply the merged code is broken | **No** | `backend/apps/mail/tests` = 489 passed, 2 failed, and `manage.py check`/`check --deploy` are clean. The merged tree's `backend/` is byte-identical to `origin/main` (§3, F17). |

---

## 8. Test suite, frontend, i18n and docs

**F32 — High — stored XSS sink in the branding font fields.** *(new; confirmed by reading both ends)*
Colours are validated and fonts are not. `backend/apps/accounts/views/branding.py:137-143`
hex-checks `primary_color`/`secondary_color`/`accent_color`, while `:146-150` stores the submitted
`heading_font` / `body_font` **verbatim**. That value is then interpolated twice into a `<style>`
block the service builds itself — into the Google-Fonts URL at
`backend/config/branding.py:196-198` (`family={font_url}`) and into
`font-family: "{self.heading_font}"` at `:259`, assembled with literal `<style>` / `</style>` at
`:263` — and emitted **unescaped** by `frontend/templates/base.html:25`,
`{{ brand.css_overrides|safe }}`. The allowlist exists (`views/branding.py:39`, `_WEB_FONTS`) but is
used only to fill the template context (`:122`); nothing validates the POST. A break-out needs a
`"` and `</style>` in the field, and the payload then renders on every page, public ones included.
Honest framing of the precondition: setting it requires `SYSTEM_MANAGE` (`views/branding.py:129`),
so this is a validation failure at a privileged boundary rather than an open XSS — but the defence
in depth is a single CSP header, `CSP_SCRIPT_SRC = ('self',)`
(`backend/config/settings/production.py:73`), which `CSP_REPORT_ONLY` can demote to report-only with
one env var (`:87`), and whose sibling `CSP_STYLE_SRC` already carries `'unsafe-inline'` precisely
because of this sink (`:77`).
*Pointer:* reject any `heading_font`/`body_font` not in `_WEB_FONTS`, on save.

**Correction to F32's blast radius (found later in this sweep, so the reader can trust the
remainder).** The paragraph above says the defence in depth is *one* CSP header that
`CSP_REPORT_ONLY` can demote. That is wrong: `provisioning/docker/nginx/conf.d/ifinmail.conf:106`
emits its own `Content-Security-Policy` with `script-src 'self'` at the nginx `server` level, and
`proxy_hide_header` at `:98-100` hides Django's HSTS/nosniff/X-Frame-Options but **not** its CSP —
so a page ships two policies and the browser enforces the intersection. With the shipped nginx
config, the `</style><script>` break-out in `branding.css_overrides` cannot execute script; what it
can still do is CSS injection (`style-src … 'unsafe-inline'` is unavoidable here because the
branding block is inline by design), defacement and data exfiltration through CSS. The sink is still
a real validation failure at a `SYSTEM_MANAGE` boundary — any deployment whose TLS terminates
elsewhere, or a console reached directly on `127.0.0.1:8000` from another container (see §7 on the
shared network), loses that second policy and becomes a stored XSS. Grade: High as a defect, Med as
browser impact on the reference install.

**F41 — Med — `location /static/` silently drops every security header.** nginx inheritance rule: a
block that declares any `add_header` **replaces** the inherited set, it does not add to it. The
server-level set lives at `conf.d/ifinmail.conf:101-106` (HSTS, nosniff, X-Frame-Options DENY,
Referrer-Policy, Permissions-Policy, CSP), and three locations declare their own headers:
`/static/error-pages/` at `:131`, `/static/` at `:238` (`add_header Cache-Control "public,
immutable"`), and the APK block at `:247-248`. The APK author knew the rule — that block re-adds
nosniff explicitly, which is how the pattern reads as deliberate in one place and accidental in
another. Result: every CSS and JS file is served with **no** CSP, no `X-Content-Type-Options:
nosniff`, no HSTS and no frame options. Impact is limited today because `/static/` only ever carries
repo-owned files, but it removes the sniffing guard from the one path that any file-write or
collectstatic supply-chain issue would land on, and it is the kind of latent misconfiguration that
turns a small bug into a same-origin one. `provisioning/docker/nginx/www/` and the error pages are
`internal`, so those two are cosmetic. *Pointer:* repeat the header list inside those locations, or
move it into a snippet `include`d per location. Static read only — needs `nginx -T` on the host to
confirm what a response actually carries.

**F40 — Med — branding logo upload trusts the client's `Content-Type` and serves it back verbatim.**
`backend/apps/accounts/views/branding.py:166-181` allow-lists the file *extension*
(`{'.png', '.svg', '.jpg', '.jpeg', '.webp'}` at `:169`) and then stores the object with
`content_type=uploaded_logo.content_type or ''` (`:173-177`) — the browser's declared type, not a
type the server derived. `core/storage/services/__init__.py:135-145` (`put_asset`) passes it straight
to the store, and `core/storage/views/media.py:59` and `:85` build the response with
`StreamingHttpResponse(stream, content_type=info.content_type)`; those are the only two places the
type is used on the way out, and neither adds `X-Content-Type-Options`, `Content-Disposition` or
`CSP: sandbox`. `PUBLIC_PREFIXES = ('branding/',)` at `media.py:27` with `_may_read` returning True
for it (`:31-32`) means `/media/branding/logo.*` is **anonymous-readable**, and the F21/F38 fail-open
means "who can upload" is wider than the `SYSTEM_MANAGE` gate at `views/branding.py:129` suggests.
Two ways this bites: (a) `.svg` is allow-listed, and an SVG served as `image/svg+xml` carries its own
script — on the reference install nginx's CSP at `:106` blocks that from executing (see the
correction above), and `/media/` inherits the server-level headers because that location declares no
`add_header` of its own (`:256-259`), so it is covered; (b) in object-storage `proxy` mode the
**stored** type is what answers, so a file named `logo.png` carrying `text/html` is served as HTML —
and if that response ever reaches a client without the nginx in front (direct console access, a
different reverse proxy, or one of the `add_header`-replacing locations in F41) it is same-origin
script execution. There is also no content sniffing or magic-number check anywhere in the upload
path, and no size cap at this call site. *Pointer:* derive the type from the validated extension (or
an allow-list of accepted types) at put time, and force
`Content-Disposition: attachment` + nosniff on `/media/` responses.

**New: the local driver and the media view are not the only storage surface.** `media.py:63-69`
builds a redirect to `chosen.public_base_url` with a path assembled from
`chosen.values.get('prefix', '')` and the checked key — an administrator-set value concatenated into
a `Location` header. `check_key` (`:46`) bounds the key, not the prefix. Worth a look at whether a
plugin-chosen store can set a `public_base_url` that is not the store's own origin.

**F33 — Med — the documented backup-upload command cannot take its own filename.**
`venv/Scripts/python.exe manage.py storage upload --purpose backups ./definitely-missing-file.gpg`
ends with `manage.py storage: error: unrecognized arguments: ./definitely-missing-file.gpg` —
reproduced here on Python 3.12.2. argparse binds the positional `name` (`nargs='?'`) wrongly once
`--purpose` intervenes, so
`core/storage/tests/test_storage_contract.py::CommandTests::test_backups_upload_prune_list_and_refuse_plaintext`
fails on the assertion rather than on the host. **SUSPECTED** whether CI sees it: the runner's
`python-version: '3.12'` may resolve to a patched 3.12.x where argparse behaves differently, and
this host could not check that. Operationally it matters because `docs/risk-register.md` R1/R3 lean
on off-site backup, which is exactly this command's job.

**F34 — the suite on this host: 82 failed, 2187 passed, 3 skipped, 1 collection error (226 s).**
Attribution matters more than the number; six groups, only two of which are the project's:

| n | Where | Cause | Class |
|---|---|---|---|
| 42 | `core/plugins/tests/test_postfix_sync.py` (17), `test_policy_plugins.py` (20), `test_lifecycle.py` (1), `mail/tests/test_mailboxes.py::SyncScriptTests` (2), `core/tests/test_provisioning_contract.py::ShellSyntaxTests` (1), `core/tests/test_frontend_contract.py::test_design_audit_script_reports_no_findings` (1) | Python-spawned `bash` dies at launch (dead WSL distro shadowing the name) — see §7 | host |
| 22 | `test_smooth_theme.py` (8), `test_site_layout_css.py` (7), `test_oceanic_theme.py` (7) | `Path.read_text()` without `encoding='utf-8'` in the *tests* (verified: 25 bare `read_text()` calls across those three files, zero explicit encodings); the CSS contains box-drawing characters → `UnicodeDecodeError` under cp1252. **22 design-system assertions silently never run on Windows** — a real portability defect in test code | host + test defect |
| 10 | `accounts/tests/test_directory_sync.py` (9), `core/storage/tests/test_storage_contract.py::LocalDriverTests::test_it_cannot_leave_its_directory` (1) | `WinError 1314` — symlinks need Developer Mode/admin. The second one is the local driver's **path-traversal escape guard**, so that guard is unverified on this host | host |
| 7 | `test_mail_threats.py` (4), `test_adaptive.py` (1), `test_autoprotect.py` (1), `test_log_report.py` (1) | Host TZ is UTC+3: fixtures stamp syslog times as `datetime.now(UTC)` text (`test_mail_threats.py:27`) and `mail_log._split()` reads bare syslog stamps as **local** time, so events land 3 h early and fall outside the 1 h window | host, with a genuine (c) flavour: the threat digest under-reports on any non-UTC install |
| 1 | `accounts/tests/test_profile_photos.py` (collection error) | `ModuleNotFoundError: No module named 'PIL'` — not installed by the sweep. The whole profile-photo contract is untested here | host |
| 1 | `test_storage_contract.py::CommandTests` | **F33, a real defect** | product |

Nothing failed for stale-database reasons, and everything reproduced deterministically — so F20
does not contaminate the suite (the unapplied migrations and these failures are unrelated).

**F35 — Med — i18n is declared but not possible.** `REPORTED` in aggregate, `CONFIRMED` in the parts
I checked: 2,267 `{% trans %}`/`{% blocktrans %}` tags across templates, yet `frontend/locale/`
contains **only `en`**, and that catalog has 299 `msgid`s against **299 empty `msgstr`s** (verified
by count), a blank `Language:` and an unedited `PO-Revision-Date: YEAR-MO-DA`, with
`POT-Creation-Date 2026-05-27` — about five months behind the template tree. There is no `LANGUAGES`
setting and no `set_language` route in `backend/config/urls.py`. Plus ~32 runtime strings bypass
gettext entirely (194 `messages.*()` calls, 16 wrapped; examples `accounts/views/api_keys.py:66`,
`mailboxes.py:446`, `core/releases/views/__init__.py`, and untranslated `placeholder=` at
`admin/login.html:70`, `admin/password_reset_confirm.html:34,39`). The production-readiness
checklist item "view messages use gettext, not hardcoded strings" is met in form only: the strings
are wrapped, but there is nowhere to translate them to.

**F36 — Med — the URL contract gate is softer than the repo believes.**
`backend/apps/core/tests/test_url_contract.py` **passes 18/18** here. It cannot fail on the setup
path because `backend/config/settings/testing.py:49` sets `SETUP_REQUIRED_REDIRECT = False` for the
whole suite, so `PagesCarryTheCurrentDomainTests` never exercises the middleware production actually
runs. And two live violations of the AGENTS.md "never write a path or domain into a template" rule
are invisible to it by construction — its pattern at `:59` matches `https?://<literal>` and cannot
match `{{`, while these templates interpolate:
`frontend/templates/admin/settings_api_keys.html:31` and
`frontend/templates/admin/settings_releases.html:161` both build `https://{{ request.get_host }}` —
`production.py:21` auto-adds the server IP to `ALLOWED_HOSTS`, so a Host-header request can put an
attacker-chosen origin into a copy-paste curl line, and on the API-keys page that line sits next to
the revealed key (F26's surface). `site/docs.html:49,80` do it correctly with `{{ site_origin }}`.

**F37 — Low — documentation drift.** 114 `.html` files on disk (counted here) against
`docs/html_templates.md:101`, which reads "Inventory (81 html on disk, 2026-10-14)"; the
per-section counts at `:103-105` are stale too; 19 templates have no row, including
`site/_account.html`,
`admin/first_password.html`, `admin/recovery_login.html`, `admin/settings_api_keys.html`,
`mail/unsubscribe.html` and `includes/avatar.html`. `:5-6` states that the "every row must exist on
disk" invariant is verified by `test_frontend_contract.py` — no test in that file reads the document,
so the registry is unenforced in both directions. `docs/enterprise-slo.md:3` claims to be
"referenced by CI (`ci.yml:45`)"; line 45 is the `pip_audit` command and nothing in CI reads the SLO
file (its other claims at `:34-41` do match the workflow). `AGENTS.md:1` still says "ifinmail 0.0.1".
`CHANGELOG.md:3` opens at `v0.0.75` with no such tag — though the entry's content is real (campaigns,
`marketing.send`, audiences exist at `mail/api.py:120,931`), so it is an untagged release rather
than fiction.

**What the frontend audit did pass.** `bash .agents/skills/ifinmail-design-audit/.../audit.sh` runs
clean over 123 files (exit 0, only 13 `[note]` multi-primary-button items). No conflict markers
remain anywhere; the two templates that came out of the broken merge — `frontend/templates/site/_account.html`
and `site/_nav.html` — are coherent, complete and `{% url %}`/`{% trans %}`-clean. No inline
`style=`; all 21 hex values under `static/css/` are `var(--ifinmail-*, #fallback)` defaults, which is
compliant; `autoescape off` appears only in the two plain-text email templates
(`admin/password_reset_email.txt:1`, `admin/email_mailbox_setup.txt:1`). Other `mark_safe` sinks
(`core/website/services/markup.py:128`, `core/assistant/services/safe_markdown.py`) escape every text
node — reviewed, not fuzzed. ARIA coverage is **SUSPECTED partial and unchecked**: ~30 `role=` lines
across 114 templates versus 58 files using `aria-label`, with no automated check, so it needs the
manual board pass.

---

## 9. Sweep results by zone

The full-codebase sweep writes its findings here, zone by zone, as they are re-verified line by
line. Every item below graded CONFIRMED was read by this author in the cited file, not only by the
delegate.

**How each zone records its coverage — and where the two shapes differ.** §9.9–§9.16 carry an explicit
**COVERAGE STATEMENT** naming the files in the zone, which were read in full, which were read only at the
lines their findings cite, and which were not inspected at all. §9.1–§9.8 record the same scope in their
section headings instead ("58 files, all read in full by the delegate", "214 files, delegate read all; this
author re-read every item below") and do not carry an enumerated not-inspected list; when this document's
totals were recounted at the end of the sweep, that difference was found and is stated here rather than
papered over. It is a reporting-shape difference, not a sampling difference — no zone in §9 worked from a
sample, and the delegate read-counts in the §9.1–§9.8 headings are the delegate's own statements, which is
why every High and Med in those eight zones was re-read by this author at the cited line before being
published. §11 records the one place where the difference has consequences: a file a §9.1–§9.8 delegate
silently did not open would not be visible in this document, whereas §9.15's and §9.16's lists make such an
omission visible by naming it.

### 9.1 `core/telemetry` — 58 files, all read in full by the delegate

**F44 — High — the threat digest reads sign-in events oldest-first and stops at 5,000, so the busiest
window is the one it loses.** `backend/apps/core/telemetry/threats/collect.py:24-29`:
```python
rows = (
    AuditEvent.objects.filter(time__gte=since, action__in=ACTIONS)
    .order_by('time')
    .values_list('time', 'action', 'user', 'detail')[:MAX_EVENTS]
)
```
`MAX_EVENTS = 5000` (`:20`), `ACTIONS` are the five sign-in outcomes (`:19`). The slice is applied
after `order_by('time')` ascending, so the 5,000 rows kept are the **oldest** in the window and the
newest ones are dropped. Two consumers, both of which need the opposite end:
* `digest.py:294` calls `collect.auth_events(now - timedelta(hours=AUTH_HOURS))` and `rules._guessing`
  then filters `e.at >= now - timedelta(hours=1)` (`rules.py:384-385`) — so once a spray pushes more
  than 5,000 audit rows into the window, the attacker's current hour is not in the list and no
  "password guessing" finding fires. The detection is defeated by generating *more* noise, which is
  the cheapest possible evasion.
* `autoblock.py:138` calls `collect.auth_events(now - LOGIN_MEMORY)` with `LOGIN_MEMORY =
timedelta(days=7)` (`:47`), whose comment states the purpose: "networks people signed in from are
never blocked". Truncation drops the most recent successes first, so after a week of ordinary
traffic the known-good set is stale and autoblock can lock an administrator out of the /24 they sign
in from daily — the exact outcome that module's own docstring says cannot happen ("A person cannot be
locked out by it"). This is the worst failure mode in the zone: an availability and account-lockout
risk created by a two-word ordering bug.
*Pointer:* `.order_by('-time')` before the slice (both callers want the newest), or push the window
filter into SQL and drop the cap for `login_success`. A test that inserts 5,001 rows with a failure
burst at the newest end would pin it.

**F45 — Med — the error-list fallback cannot be serialised by the schema it feeds.**
`TelemetryService.list_events` (`services/telemetry_service.py:255-283`) catches any DB failure and
returns `TelemetryService.get_recent(...)` (`:282`). `get_recent` ends at
`return list(reversed(TelemetryService._memory_events[-limit:]))` (`:210`), and `_buffer_memory`
(`:493-503`) appends dicts with exactly these keys — `time, severity, action, detail, service, user,
correlation_id` — i.e. **no `id`, no `fingerprint`, no `source`**. `ErrorEventV1` requires all three
(`serializers/__init__.py:78-88`: `id: str`, … `fingerprint: str`, `source: str`), and
`viewsets/__init__.py:31` does `ErrorEventV1(**event) for event in found['results']`. So the endpoint
that exists to show errors answers 500 with a pydantic ValidationError precisely when the database is
unavailable. The console tab survives because `accounts/views/logs.py:138-141` reads with `.get`.
Reachable with any `audit.view` token scope. *Pointer:* add the three keys in `_buffer_memory` (or
project them through one shared shape), and give the fallback a test that actually asserts the
response body.

**F46 — Med — an external LLM call is made inside the digest's database transaction.**
`digest.run` opens `transaction.atomic()` at `threats/digest.py:308` and calls `_maybe_summarise`
inside it (`:317`), which reaches `summarize.write` → `provider.complete(messages, [])`
(`summarize.py:162`) — a network request with seconds-to-minutes latency. The Celery worker holds its
DB connection, and the row locks taken on `ThreatFinding`/`ThreatDigest`, for the whole of it. On a
slow provider this is a self-inflicted connection-pool exhaustion and lock pile-up in the app that
also serves the console. *Pointer:* persist the digest, commit, then summarise in a second short
transaction.

**F47 — Med — the mail-trace page reads tens of megabytes of logs per request, synchronously.**
`mail_trace.py:113-121` tails three sources × main + rotated (`postfix.log{,.1}`,
`dovecot.log{,.1}`, `rspamd.log{,.1}`) at 12 MB each — up to ~72 MB — and materialises every line as
a decoded tuple in a list, per GET. Any `AUDIT_VIEW` holder typing ≥3 characters into
`accounts/views/logs.py:244` triggers it, uncached. The cap makes it bounded rather than unbounded,
but a handful of concurrent users on that tab is a request-thread stall. `autoblock.py:142-146`
re-reads the same mail-log tails on every pass, duplicating the heaviest I/O in the zone. Related,
worth noting while the file is open: `threats/mail_log.py:101-104` silently discards lines longer than
2048 bytes and, unlike `access_log.py`, has **no** malformed/oversized counter at all — so unusual
Postfix lines vanish with no signal. *Pointer:* move trace search to a task or a bounded streaming
scan, and reuse one read per pass.

**F48 — Med — the alert is marked sent before it is sent.**
`threats/digest.py:241-242` sets `row.notified_at = now` and saves, and only then calls `send_mail`
(`:259-267`) under `ALERT_EVERY = timedelta(hours=24)` (`:43`); the send failure is logged and
skipped. If the thing that broke is the mail path — the exact scenario the threat alert exists for —
the finding's one alert has already been consumed and nothing is raised again for 24 hours.
*Pointer:* stamp `notified_at` only on a successful send.

**Lower-severity items from this zone, all confirmed by reading:**
`tests/test_telemetry.py:58-61` `test_throttle_never_raises` ends in `assert True` — an assertion-free
test, so the throttle behaviour is not actually pinned; `telemetry_service.py:417-433,463-469` does a
read-modify-write on fingerprint `count`/`severity_max` without `F()`, so concurrent captures lose
increments, and a `get_or_create` race on the unique hash falls into the generic `except` at `:456`
and drops the row; a `_persist` failure inside `on_commit` is only a `logger.warning`
(`:396-404`), so `capture` returns `{'id': ''}` and no caller can tell "deferred" from "lost";
`middleware.py:57-58` is a bare `except Exception: pass` around the capture call, distinct from the
already-known swallows at `:470`/`:532` — if telemetry itself breaks, errors disappear without a
trace; `tasks.py:87-88` hand-builds `f'https://{MAIL_HOSTNAME}/accounts/logs/report/?period=week'`
instead of `backend.config.site_url`, an AGENTS.md URL-contract violation that the F36 test cannot
see because the pattern matches literals in **templates**, not f-strings in Python. **SUSPECTED:**
`threats/delivery.py:523,564-565` index `BY_KEY[top[0][0]]` directly on category keys read back from
stored digest JSON, while `:418` correctly uses `.get(cat, OTHER)` — a key written by another build
would raise `KeyError` and abort the pass; needs a stored digest with an unknown key to prove.

**What telemetry got right** (so the next review does not redo it): bounded, line-safe tailing that
reports `skipped_bytes` (`threats/access_log.py:50-63`), every parse failure counted rather than
raised (`:66-96`), receiver text scrubbed of addresses and queue ids before storage
(`delivery.py:215-221`), stored mail events carry no message content (`mail_log.py:150-160` with
`models/threat.py:21-51`), indexes on every filtered/sorted column (`models/error_event.py:37-87`),
all five v1 endpoints gated by `@require_scope` with a live role re-check and `system.manage` for ack
(`api.py:27,42,55,66,77`), the assistant-facing summary masks accounts and keeps only /24s with an
ASCII length bound (`summarize.py:74-111,141-151`, asserted at `tests/test_threats.py:520-584`),
scanner refusals excluded from the backlog with a data migration
(`telemetry_service.py:122,155-156` + `migrations/0004_purge_refusals.py`), and the geo queries are
parameterised with the download hard-capped at 64 MB (`threats/geo.py:114-121,263-269`).

### 9.2 `dns` + `domains` — 92 files, all read by the delegate

**F49 — Med — deleting a domain leaves a world-readable private signing key on disk.**
`domains/services/dkim.py:71-85` writes the PEM to `DKIMService.key_path(domain, selector)` and
`os.chmod(tmp, 0o644)` at `:81` — deliberately, per the comment at `:79-80`, "so the Rspamd container
can read it", which means every user in every container on that volume, and anyone with a local file
read, can read the private half of the domain's DKIM key. Neither delete path removes it:
`ProvisioningService.remove_domain` (`services/provisioning.py:249-261`) ends at
`domain.delete()  # aliases and DKIM keys cascade`, and `DomainService.delete_domain`
(`services/__init__.py:115-130`) does the same plus a zone removal. `grep` for `key_path` / `unlink`
in this zone finds only temp-file cleanup inside `_write_private_key` itself (`:83`) and test-local
unlinks, so the cascade is DB-only. The result is a key for a domain this server no longer hosts,
still readable and still wired into Rspamd's signing table — a re-signing and replay-of-identity
surface that survives the deletion, and one that `test_provisioning_pipeline.py:335` would not catch
because it asserts only the row count. *Pointer:* unlink `key_path` (and `legacy_key_path`) for every
selector on both delete paths, and make the test assert the file.

**F50 — Med — two divergent delete paths, and one of them leaves the zone published.**
`remove_domain` (`provisioning.py:249-261`) → `domain.delete()` + `CertificateService.sync()` +
audit. `delete_domain` (`services/__init__.py:115-130`) → `domain.delete()` inside
`transaction.atomic()`, then `ZoneService.remove(domain_name)` in a `try/except`. The zone tables key
on the **name string** (`dns_zones.zone`, `dns_custom_records.zone` are plain CharFields with no FK to
`domains`), so nothing cascades: a domain removed through the provisioning path leaves Knot
answering SOA/NS for a zone the application has forgotten. Combined with F49 the two paths differ in
*both* cleanup steps. Neither is wired to an HTTP route today, so this is latent — but it is exactly
the shape of bug that a future "delete domain" button will ship, and the divergence is the reason it
was not caught. *Pointer:* one teardown helper (rows, zone, key files, certificates) called from both.

**F51 / F52 — confirmed lower-severity items:**
`dns/services/__init__.py:47-62` — "encrypted at rest" is best-effort: `decrypt_credentials` falls
back to returning the stored dict as plaintext on a legacy path, and there is no re-encryption on
`SECRET_KEY` rotation, so after a rotation every provider credential is undecryptable and
`get_provider` returns None (a silent loss of DNS management, not a leak).
`management/commands/provision_domains.py:1-5` promises "idempotent, no network" while
`provisioning.py:146-187` pushes the full managed record set to the live provider for every external
domain, plus certificate sync and an ipify lookup — and `provisioning/docker/entrypoint.sh:75` runs
it on **every API start**, so a restart rewrites provider-side records and can trip provider rate
limits. `dns/services/records.py:87-91` with `zones.py:83-85`: a CAA value is validated as `\S.*`,
only outer quotes are stripped, then re-wrapped as `"…"` in `rdata` with no escaping —
`0 issue "x" IN A 1.2.3.4` yields an unparseable zone line that fails the whole Knot reload
(self-DoS, `DNS_MANAGE`-gated). `dns/viewsets/status.py:22-43` is a GET that performs 4 live DNS
lookups **and** persists `verified`/`*_verified` (`test_pipeline.py:174-189` asserts the write), so a
prefetch or cache warm mutates state. `dns/viewsets/configure.py:57` with `dns/views/web.py:309` and
`providers/cloudflare.py:31-59` run provider writes synchronously inside the request with up to three
`time.sleep` backoffs and no overall deadline — one slow provider pins a worker.
`providers/base.py:50` / `cloudflare.py:146` / `digitalocean.py:147` / `porkbun.py:125`:
`verify_records` is dead code in all four providers (never called anywhere), and its DKIM branch is
name-existence only (`cloudflare.py:156` hardcodes `default._domainkey`), so if it were ever wired it
would call any TXT at the selector "DKIM verified". `dns/views/_helpers.py:15` keeps an unused
`_is_staff(user: object)` that dereferences attributes off an `object` — mypy-strict bait.
`dns/viewsets/configure.py:70` uses `next(st for st in … if st.name == 'DNS records')` with no
default, so a step rename becomes an uncaught `StopIteration` → 500.
`porkbun.py:31-39` has no 429 backoff unlike Cloudflare/DigitalOcean, and no provider caps response
size before `resp.json()`.

**What dns/domains got right** (verified, and worth keeping on the record because these are the
questions the zone is most likely to fail): **no SSRF primitive** — every provider endpoint is a
compile-time constant (`cloudflare.py:12`, `digitalocean.py:12`, `porkbun.py:12`), no base URL is read
from the stored credential row or from input, and `PROVIDER_MAP` is closed to the three built-ins
(`services/__init__.py:24-28`). **Domain verification is proof-bound** — `verified` is set only when a
MX lookup through public resolvers (`verification.py:80-90,159-160` queries 1.1.1.1/8.8.8.8) matches
`mail_hostname`, so the server's own authoritative zone cannot satisfy itself and no API response can
flip the flag; the single non-proof `verified=TRUE` is the operator's own primary domain seeded at
install (`init-db.sh:168-170`). **The DKIM private half is never serialised** — `DKIMKeyOut` carries
`selector` + `active` only (`serializers/__init__.py:61-69`), asserted at
`test_viewsets.py:49-55`. **Provider credentials are encrypted on write and never returned**
(`services/__init__.py:77-89`), and `dns_configure` persists only the fields named by
`credential_map` (`serializers/__init__.py:32-33`), so stray POST keys cannot smuggle themselves into
the row. **Custom-record validation is genuinely strong**: owner-name regex (`records.py:20-21`),
address parsing (`:56-67`), TXT length cap plus control-character rejection (`:72-77`),
CNAME/apex/NS/SPF/DMARC conflict guards (`:95-168`), and `_txt` quoting/backslash escaping with 255
octet chunking for the zone file (`zones.py:56-63`). **Unmanaged DDL matches the models** with no
column drift (`ip_address INET` in both `init-db.sh:56` and `db-upgrade.sql:6`; the `dkim_keys` FK is
`ON DELETE CASCADE` with `UNIQUE(domain_id, selector)` matching `models/__init__.py:31,41`). **No
storage-governance violation** in either app.



### 9.3 `mail` — 214 files, delegate read all; this author re-read every item below

**F53 — Med — the idempotency slot is a cache get-then-set, and the `pending` marker locks the key
for its whole TTL.** `backend/apps/mail/api.py:410-431`: the slot is read with `cache.get(slot)`, a
`{'state': 'pending', …}` marker is written with `cache.set(slot, …, 300)`, and the send then runs.
Two requests arriving together both read `None` and both send (no atomic `add`), so the guarantee the
endpoint advertises does not hold under concurrency; and if the worker dies between the marker and the
result, the key holder gets `409`-style refusals for five minutes with no way to clear it — the only
cleanup is `cache.delete(slot)` on the `SendRefused` path (`:428`). The campaign variant
(`api.py:1305-1355`) is the same shape with a **3600 s** TTL and deletes the slot on `HttpError` for a
bad audience/template (`:1350`), so an unrelated failure can strand a slot for an hour. This is the
`delivery_events` pattern already reported in §6, now confirmed to be the zone's house style rather
than one bug. *Pointer:* `cache.add()` for the claim, a shorter `pending` TTL plus a heartbeat, and
store the slot in a table if the promise is contractual.

**F54 — High — the console's IMAP client turns certificate checking off for every mailbox read.**
`backend/apps/mail/services/imap_reader.py:104-141`: `_context()` sets `check_hostname = False` and
`verify_mode = ssl.CERT_NONE`, and the comment says why — the certificate names the public host while
the client connects to `IFINMAIL_IMAP_HOST` (`dovecot`), so a name mismatch would break the feature.
The connection then authenticates as `<mailbox>*ifinmail-console` with `DOVECOT_MASTER_PASSWORD`
(`:130-136`), i.e. the single credential that can read **every** mailbox on the server, sent over a
TLS channel that accepts any certificate. The correct fix is a SAN covering the service name (or
`ssl.SSLContext.load_verify_locations` with the internal CA plus `server_hostname='dovecot'`), not
disabling verification. Any position between the api container and dovecot — another container, a
compromised bridge — can terminate TLS and take the master password plus all message bodies.
*Pointer:* issue the cert with `dovecot` in the SANs and restore `check_hostname = True`.

**F55 — Med — the webhook policy ORs two different capabilities together, so a permissive inbox
setting silently relaxes delivery webhooks.** `services/webhooks.py:136-137`:
`allow_http = flag(events, 'allow_http') or flag(inbox, 'allow_http')` and the same for
`allow_private`, while `delivery_events`/`inbox_events` are correctly read from their own namespaces
(`:134-135`). One `Policy` therefore serves two features, and an administrator who only ever ticks
"plain http is fine for my inbox tool" also opens plain http (HMAC body in the clear) and
private-network targets for outbound delivery webhooks. *Pointer:* two policy objects, or one
capability that owns both.

**F56 — Med — a bounce guard that lives only in the cache cannot stop a bounce-storm, and fails
open to `None`.** `services/marketing.py:599-615` reads the campaign bounce rate as
`int(cache.get(_bounce_key(str(campaign.pk))) or 0)`, wrapped in `except Exception: return None`. The
counter is a Redis key with a TTL: restart the cache (or evict it) and every in-flight campaign looks
clean, so the pause-on-rate rule resets exactly when the operator most needs it; and the caller treats
`None` as "no data", not as "refuse to keep sending". Combined with §6's campaign findings, the auto-pause
is advisory rather than a control.

**F57 — Med — the campaign runner writes recipient state by primary key only, so a stale worker can
overwrite a live claim.** `services/campaign_runner.py:318-324` marks a row `SENT` with
`filter(pk=row.pk).update(...)` and `_mark` (`:412-416`) does the same for `FAILED`/`SKIPPED`, while
the rollback path one block earlier (`:313-317`) correctly guards
`filter(pk=row.pk, claim_token=token)`. The asymmetry says the token was written for exactly this
race and then used on only one of three paths: a worker whose claim expired can stamp `SENT` (and
clear `claim_token`) on a row another worker is mid-flight, which is a duplicate-send path as well as a
wrong counter. *Pointer:* put `claim_token=token` in all three updates.

**F58 — Low — a queued delivery outlives the capability that created it.** `sweep()`
(`services/webhooks.py:597-605`) selects on `status=PENDING, next_attempt_at__lte=now` only, so rows
already in the table keep being retried after the plugin is uninstalled or its `delivery_events`
capability is switched off. It is *not* true that delivery ignores the switch: `attempt()` sets
`row = delivery.endpoint` and `current = policy()` (`:465-467`) and refuses an inactive endpoint with
`WebhookError('the webhook is switched off')` (`:471`), re-runs `check_url(row.url, current)` (`:473`)
and deactivates the endpoint on a `410` (`:502-507`). **REFUTED as originally reported:** the
delegate's claim that "delivery never re-checks the plugin gate or `endpoint.active`" is wrong about
`endpoint.active` and right only about the capability flag. The residual gap is small — a plugin
disable does not stop already-queued rows — but the fix is one line in the `sweep()` queryset.

**F59 — Low — the outbound URL filter has no port rule.** `check_url`
(`services/webhooks.py:145-173`) checks scheme, credential-in-URL, length, a blocked-host list,
bare-names and resolved-address classes, but never looks at `parts.port` except as a
`getaddrinfo` hint (`:163`). An administrator (or an approved submission, per F31) can point a
webhook at `https://some-public-host:3306/…`, and the console will open a connection and post a
signed JSON body to it. The SSRF posture against *addresses* is sound; against *ports* it is absent.

**F60 — Low — quota reporting walks the whole mail tree on every call.**
`services/quota.py:86-96` loops over every mailbox and `os.walk`s
`/var/mail/vhosts/<domain>/<local_part>` summing `os.path.getsize`, with `suppress(OSError)` per file.
On a host with thousands of mailboxes this is a synchronous filesystem sweep inside a request, and the
loop repeats on every pass of whatever page or task calls it.

**F61 — Low — mailbox rows are read table-wide and the alias lookups have no index.**
`services/mailboxes.py:99,140,275,377` all filter `Alias` on `source` (and one on
`source` + `destination`) against the unmanaged `aliases` table, whose only DDL is
`init-db.sh` — `source` carries no index there, so each check is a sequential scan that grows with the
alias count. `services/__init__.py:25-30` returns whole-domain querysets
(`filter(domain__name=…)`) that callers iterate in Python.

**Lower-severity items in this zone, confirmed by reading:** `services/__init__.py:31-62` is a second
mailbox/alias write path (`create_mailbox`, `get_or_create_mailbox`, `delete_mailbox`, `delete_alias`)
sitting beside the real one in `services/mailboxes.py`, with no validation, no password handling and no
`MailboxService` coordination — the AGENTS.md "one interface for CRUD" rule has two doors, and
`delete_alias` swallows only `OperationalError`, so a `ForeignKey`/`ProtectedError` on an unmanaged
table surfaces as a 500 rather than the message the page expects. `admin/` registers the raw unmanaged
models, so a change made there never runs the `MailboxService` invariants (the same gap §5 counts as a
governance instance). The unsubscribe token is a signed but **not encrypted** value with a five-year
`max_age`, so `optout_token` (`services/marketing.py:205`, built through
`tracking`/`compliance.unsubscribe_token` at `services/compliance.py:140`) keeps working after the
person leaves and reveals the address it was minted for. `codes.extract()` caps its returned lists at
five (`services/codes.py:162-170`) — the delegate's "uncapped" claim is wrong as stated; the
unbounded part is only the scan over a body that message-size limits already cap.
`services/injection_shield.py:101` stores the attacker's hidden text (500 chars) in the score dict,
which is rendered back to the administrator — Django's autoescaping means this is a legibility problem,
not XSS, so it is recorded as a Low. **REFUTED:** the claim that `tracking.py` is an open-redirect
sink. `marketing_click` (`views/tracking.py:45-63`) redirects only to
`tracking.destination(link, recipient)` — a URL the campaign owner stored — validated as a web address
(`services/tracking.py:14-15`, `:280`), and the response sets `Referrer-Policy: no-referrer` (`:62`).

**Verdicts on the four §6 items this zone was asked to re-check.** (a) *Celery time limits* — confirmed
and wider than reported: no `task_time_limit`/`soft_time_limit` is set in
`backend/config/settings/base.py:229-233` and only `CELERY_TASK_ACKS_LATE = True`, so 15 of the 16 core
periodic tasks (`telemetry/tasks.py`, `core/tasks.py:21,54,75,95,104`, `plugins/tasks.py:10`,
`storage/tasks.py:12`, `releases/tasks.py:10`) plus the mail senders can run without a deadline; see
F79. (b) *`policy()` re-scan per delivery* — confirmed: `attempt()` calls `policy()` (`:466`) on every
attempt, which re-reads plugin capability rows; correct behaviour, but the cost is a DB read per
delivery row inside the retry loop. (c) *`delivery_events` cache get-then-set* — confirmed, and it is
the general slot pattern of the zone (F53). (d) *campaign `_mark`* — confirmed, and it also covers the
`SENT` write at `:318` (F57).

**What mail got right:** delivery is claim-based with a single conditional `UPDATE` and a lock window
(`_claim`, `services/webhooks.py:532+`), so parallel workers cannot double-send a webhook row;
signatures are HMAC-SHA256 over `timestamp.body` with the secret held in Fernet-encrypted form
(`sign()`, `plugin_secrets.decrypt`); backoff is bounded by `BACKOFF` and clamped by
`max_attempts`; the click/redirect responses set `Cache-Control: no-store`; `codes.py` drops
unsubscribe/privacy/social links rather than surfacing them as candidate codes; and every recipient is
re-checked against opt-out and suppression lists at send time (`campaign_runner.py:15` states the rule
and the code implements it).

### 9.4 `core/assistant` + `core/releases` — 75 files, delegate read all; this author re-read the
marked items

**F62 — High — a plugin manifest may point the assistant at any http(s) host, and that host is
handed the decrypted API key.** The validator for the setting is syntax-only:
`backend/apps/core/assistant/assistant_handlers.py:30-36` (`_base_url`) accepts any `http`/`https`
host with no credentials, query or fragment and no address class check; `:71-83` applies it. The
runtime guard (`assistant/services/provider.py:60-80`) then refuses cloud-metadata hosts and
`_BLOCKED_NETWORKS`, but its own error text at `:64` advertises "http:// on your network", i.e.
private targets are expected and allowed, and the check resolves the name and **throws the answer
away** — `complete()` calls `check_endpoint(self.base_url)` (`:94`) and then `_post(f'{self.base_url}/chat/completions', …)`
(`:102`), where `requests` re-resolves DNS: a hostname that answers a public address for the check and
a loopback/RFC1918 address for the request walks past the filter (classic rebinding). The payload sent
is the whole conversation plus every tool result, under `Authorization: Bearer <api key>` — so an
approved third-party submission that sets `assistant.model.base_url` (principle 8 makes a human press
"approve", which is the only gate) exfiltrates both the key and the context. Same family as F31:
the extension point was opened with syntax validation where an address-class policy was needed.
*Pointer:* resolve once, connect to the validated IP with `server_hostname`/`Host` preserved, and add
an allow-list of schemes/hosts to the capability rather than a free-text URL.

**F63 — Med — the markdown sink turns `/\host` into a cross-origin link with no `rel`.**
`backend/apps/core/assistant/services/safe_markdown.py:106-113` (`_safe_url`) keeps a URL beginning
with a single `/` — `if url.startswith('/') and not url.startswith('//'): return url` (`:113`) — and
`_anchor` (`:126-134`) decides `external = not url.startswith(('/', '#'))` (`:128`). `/\evil.test`
therefore satisfies the "same-origin absolute path" test while browsers follow the WHATWG rule that
maps `\` to `/` and read `/\evil.test` as `//evil.test`: the link leaves the site, gets no
`rel="noopener noreferrer"`, and no `target` warning. Confirmed by reading both functions.
The site's own markup renderer does reject it (`core/website/services/markup.py:25-35` allow-lists
schemes and rejects `//host` **and** `/\`), so this is one divergent implementation rather than a
project-wide hole — which is the real risk: two sanitizers, one correct, and the weaker one is the one
that renders assistant output (`site/download.html:62`, `site/changelog.html:23`,
`admin/assistant.html:115`). *Pointer:* reuse `markup.safe_link`, and add `/\`, `\/` and
`/\\/evil.test` to `assistant/tests/test_markdown.py` (that file does fuzz URLs at `:316-326`, which
corrects §11's earlier caveat, but its corpus does not include the backslash form).

**F64 — Med — counters in this zone are read-modify-write, so the numbers shown are lower bounds
under load.** `assistant/services/agent.py:189-192` reads `tokens_used`, adds and saves (two
concurrent turns lose one); `releases/services/release_service.py:353` does the same on the
per-checkin device counter while the device poll path is exactly the unauthenticated high-volume one;
`telemetry/services/telemetry_service.py:426-433,474-490` repeats the pattern for fingerprint counts
(§9.1). None uses `F()` or `update()`.

**F65 — Med — the device poll endpoint re-reads everything per request.**
`release_service.py:313` builds the whole release list and `:353` runs an `exists()` plus a `count()`
per unauthenticated poll, and `plugins/services/lifecycle.py:235` re-parses every enabled manifest on
each call (`submissions.py:42` does `objects.all()` likewise). With the bundled set this is cheap; with
a few hundred installations or a rollout of mandatory updates it becomes the hottest path in the app
and it has no cache layer.

**F66 — Low — `releases/web.py:137,147` write route literals in Python while the same routes are
named.** `releases/urls.py:18-19` registers `updates/v1/android/latest.json` and
`download/android/latest.apk` with names, and the two places above build the strings by hand instead of
`reverse()` — an AGENTS.md URL-rule break of the same class as F36, invisible to
`test_url_contract.py:85` because that scan matches only `/accounts/…` literals (see F99).

**F67 — Low — two tests in this zone assert nothing.** `assistant/tests/` and
`releases/tests/` each contain a case whose final assertion is tautological/absent (the delegate named
`test_api_web.py` bounds cases), so a regression in release visibility bounds passes silently; compare
F99 for the same class in `core/tests`.

**Lower-severity items, confirmed:** `releases/views/__init__.py:15-17` imports
`accounts.models.MailUser`/`APIToken` from core — one of ~20 core→outward imports counted in this sweep
(F106); the `ToolTier` enum is advisory only, with `SYSTEM_MANAGE` the single real boundary
(`assistant/services/tools.py` tier checks do not gate anything), and `register`/`register_applier`
(`:82,92`) overwrite silently on a duplicate name, so a second extension that takes a name disables the
first; release upload bounds raise bare `ValidationError` strings that reach the page as prose
(`releases/views/__init__.py`), which is honest but untyped; `adaptive.py:306` (assistant) reads
`accounts` models directly.

**What assistant/releases got right:** `OpenAICompatibleProvider.__repr__` never includes the key
(`provider.py:90-91`) and the key is stored encrypted; responses are length-bounded and tool output is
passed through the sanitizer before display; `markup.py` is escape-first with `mark_safe` only at the
end of assembly (`core/website/services/markup.py:15-128`, proven by `website/tests/test_markup.py:26-63`);
the APK permalink and manifest set `Cache-Control: no-store`; `AppRelease.stored_file` uses
`on_delete=PROTECT`, so a published build cannot be deleted out from under a release; the signature
check on upload (`release_service.py:160-172`) refuses debug-signed/unsigned APKs and
`_require_same_signer` blocks a different key taking over a channel.

### 9.5 `core/plugins` — 58 files, delegate read all; this author re-read the three Highs

**F68 — High — `publish_all()` renders and writes the shared runtime files outside every lock.**
`services/lifecycle.py:259-279` builds the whole engine view from the database and calls
`target.publish(...)` (`registry.py:94-101`, a plain `read → compare → os.replace`), and the only
serialisation in the zone is `_global_lock()` (`:79-82`), a `pg_advisory_xact_lock` that lives and dies
with the `transaction.atomic()` block in `_run` (`:370`). That block closes at `:406` and
`_run` returns `cls._effects_then_settle(...)` at `:410` — so the publish at `:416` happens **after**
the advisory lock is gone. The other four publishers never take it at all: `reconcile()` (`:317`), the
retry path (`:436`), `mail/services/containment.py:138` and `mail/services/spam_policy.py:305`. Each
publisher renders from its own snapshot, so the last writer wins with data that may be seconds old: an
administrator who pauses a compromised mailbox while the 10-minute beat is running can have
`paused_logins` rewritten from the pre-pause view, and nothing notices until the next pass. This is the
one place where the design promise "any file can be rebuilt from the database at any time" is true but
"the file currently on disk reflects the database" is not. *Pointer:* hold the lock across the effects
phase, or make publishing a single serialised job.

**F69 — High — a plugin row that fails to render is skipped, and skipping means "delete this
setting".** `_enabled_values` catches `PluginError` per row and `continue`s
(`services/lifecycle.py:240-243`, comment: "Never let one broken row block the others"), and
`AdapterTarget.render` then emits **every** declared key with whatever the merge produced:
`lines += [f'{key} = {values.get(key, "")}' for key in sorted(self.keys)]` (`registry.py:89-92`), where
empty means remove (`registry.py:42`: `return None  # empty = remove the setting`). Postfix's watcher
acts on exactly that (`provisioning/docker/postfix/sync-overrides.sh:89-91` →
`restore_default "$key"`). So one row whose settings no longer validate — a grammar change, a stale
value after an upgrade, a `PluginError` from any cause — silently withdraws its policy from the live
config while `applied_status()` still answers APPLIED and System health still counts the plugin as
enabled. The affected keys are the security-relevant ones: `always_bcc`, `blocked_destinations`,
`paused_logins`, the rate limits. Fail-open in a layer whose whole purpose is policy.
*Pointer:* if a contributing row fails, publish nothing for that target (and mark the target
"stale") rather than publishing the empty set.

**F70 — High — one validator raises `ValueError` instead of returning a message, and that exception
class is not caught anywhere on the path.** `_check_value` (`services/registry.py:38-45`) returns
`spec.validator(value)` unguarded (`:45`). The mail app's integer validator is
`if not value.isdigit() or not low <= int(value) <= high`
(`backend/apps/mail/services/plugin_points.py:157-163`). `str.isdigit()` is True for Unicode characters
that `int()` refuses — verified on this host: `'²'.isdigit()` is `True` and `int('²')` raises
`ValueError`. That `ValueError` is not a `PluginError` (`types/__init__.py:125`), so it escapes every
handler written to catch one: `accounts/views/marketplace.py:352-356` (submit → 500 for a
CONSOLE_ACCESS user), the install/configure views (`:312-317`), `_enabled_values`' `except PluginError`
(so it propagates out of `capability_values`), and therefore **every** sending path that reads a
capability (`mail/services/messages.py:134,145,240,245,251,371`) plus the reconcile beat task. One
oddly-typed setting value takes down outbound mail for the whole server. *Pointer:* wrap
`spec.validator`/`spec.translate` in `_check_value` and turn any exception into an error string; also
make `_int_between` use `str.isascii()` + digits, and broaden `_enabled_values` to `except Exception`.
The same `isdigit`+`int` pair is repeated at `core/storage/plugin_contract.py:82`.

**F71 — Med — a failing dynamic source removes the value it owns.** `registry.dynamic_values()`
(`services/registry.py:253-276`) wraps each source in `except Exception: … continue` (`:262-264`) so a
DB or Redis blip yields *no* keys for that target, and `publish_all` gives dynamic values "the last
word" (`lifecycle.py:274-275`). The merged bucket then lacks `paused_logins`, `render` writes it empty,
and the watcher deletes the map — `test_postfix_sync.py:236-244` asserts precisely that an empty value
removes it. A containment control that depends on a live query therefore opens on failure, while the
zone's own rate limiter deliberately fails closed (`mail/services/messages.py` `_take()`).
*Pointer:* a failed source must veto the publish of the targets it feeds.

**F72 — Med — "Applied" means "the file was seen", not "the values took effect".**
`sync-overrides.sh:72-80` skips a key that is not on the allow-list or whose value fails the regex, and
then writes the observed file's hash to the state file **unconditionally** at `:99`, which the
acknowledgement publishes as the applied hash (`:236`). `AdapterTarget.applied_status()`
(`registry.py:103-122`) compares that hash to the runtime file and returns APPLIED, which is what
`System health` and the plugin page show — contradicting the docstring at `registry.py:69-70`.
The console shows a green tick for a policy the engine refused. *Pointer:* ack only the subset applied
and surface the skipped keys.

**F73 — Med — engine and watcher enforce different grammars for the same key.** The engine accepts
anything `isdigit()` + `int()` allows (including `٣٠`, `²`), while the watcher's rules are ASCII
(`sync-overrides.sh:34-38`, e.g. `^([1-9]|[1-4][0-9]|50)?$` for `message_size_limit_mb` and
`^([1-9][0-9]{0,2}|1000)?$` for `recipient_limit`). So `message_size_limit_mb = '٣٠'` passes validation,
passes install, gets written to the runtime file, is dropped by the watcher, and is acknowledged as
applied (F72). `test_policy_plugins.py` asserts engine keys and `in_process` (`:145,188`) but has no
engine↔watcher parity case, so nothing pins the two grammars together. *SUSPECTED as an effect* — the
watcher tests self-skip on this host.

**F74 — Med — two finishers can settle the same transient row, and they disagree about an empty
`target_state`.** `_effective_state` treats an empty `target_state` as ABSENT (`lifecycle.py:72-76`)
while `_settle` treats it as ENABLED (`:449-462`: `target = locked.target_state or
InstallationState.ENABLED`). `_finish_stale` (`:465-471`) and `reconcile()` (`:312-316`) both call the
effects/settle path without the global lock, so a row left transient by a dead request can be settled
twice — the second pass sees the `''` the first wrote and republishes the enabled values the operator
had just asked to remove.

**F75 — Med — every capability read re-scans and re-renders the whole plugin table.**
`capability_values` → `_enabled_values` does `PluginInstallation.objects.all()` (no `.only()`), then
`manifests.load(row.manifest)` + `rendered_values` + `to_targets` per row
(`lifecycle.py:232-256`), with no memoisation, and `publish_all` runs `_enabled_values` again
(`:264`). There are ~20 production call sites; a single sent message reaches
`messages.py:134,145,240,245,251,371` — six full scans and, with the 16 bundled plugins, ~96
render/validate passes per message, on the hot path (§9.3's verdict (b) is this, not a webhook-only
problem). *Pointer:* cache one merged snapshot keyed by `max(revision)`/`updated_at`.

**F76 — Med — the secrets policy is enforced by code and by nothing else.** The invariant "a secret may
only travel whole to a secret field bound to an in-process target" lives in three error strings
(`services/manifest.py:332-335,395-399`, `registry.py:191-192`). `grep -ri secret
backend/apps/core/plugins/tests` and `accounts/tests/test_marketplace.py` return **zero** matches. A
refactor that loosens `whole`/`is_secret_field` — or that binds a secret field to `postfix.main` — keeps
the entire suite green and writes a Fernet ciphertext, or the decrypted value, into a runtime file that
Postfix, Rspamd and Dovecot all read. Related latent gap: `manifest.py:354` compares
`secret_keys` with exact `s.type == 'secret'` while cleaning uses `base_type`, so
`register_setting_type(name, base='secret')` would bypass the policy entirely (no such type exists
today).

**F77 — Med — the optimistic-concurrency guard is opt-in.** `_run` checks
`if revision is not None and row.revision != revision` (`lifecycle.py:383-387`), and the form field is
`required=False` (`backend/apps/accounts/forms/marketplace.py:14`), with `configure/update/enable/
disable/uninstall` all accepting `revision: int | None`. A client that omits the field skips the guard
and the last of two `system.manage` holders wins — and its `publish_all` writes the files.
*Pointer:* require `revision` for every operation except INSTALL.

**Lower-severity items, confirmed by reading:** `manifest.py:496-505` runs a registered type's
`live_check` only inside the `base == 'email'` branch, so any other refinement's live check is silently
ignored; `_load_cached` is an `lru_cache` keyed on manifest text alone (`manifest.py:153-154`) although
validity also depends on the mutable registries, which is why `test_submissions.py:103,106` must call
`cache_clear()`; retiring a submission does not stop an enabled installation rendering from its
manifest snapshot (`accounts/views/marketplace.py:444-446`) — documented, but the only signal is a
success message; any CONSOLE_ACCESS user may submit unbounded versioned manifests and read every other
submitter's full manifest plus note (`:343-382,384-413`); `test_scheduling.py:22-24` asserts only the
task name, not the crontab interval ("runs often and cheaply" would pass a yearly schedule), and
`test_lifecycle.py:203-212` omits `Operation.UPDATE` from its legality map; typing gaps at
`submissions.py:118,145`, `validate_plugin.py:22` (`parser: object`), `marketplace.py:200,331`.
**SUSPECTED:** `bundled/object-storage/plugin.toml` defaults `store_media` to true while `secret_key` is
optional, so media could be routed to an S3 store with no secret (needs a live driver call to prove).

**What plugins got right (and is worth not re-litigating):** no manifest value can reach a filesystem
path — `runtime_file`/`ack_file` are class constants (`mail/services/plugin_points.py:183-184`) and all
writes go through `core/platform/services/runtime.write_runtime_file`, which rejects empty and
dot-prefixed segments; `\r`, `\n`, `\0` are refused on every emitted value (`registry.py:42-44`), so
there is no config-file injection; unknown TOML keys are refused per table (`manifest.py:191-194`) with
`MAX_SETTINGS=20`/`MAX_CONTRIBUTIONS=10`; the submission upload is read into memory behind a 32 KiB cap
and its filename is never used (`accounts/forms/marketplace.py:22-28`); webhook policy values fail
**closed** on absence (`mail/services/webhooks.py:120-139` requires a literal `'yes'`), so F69's empty
key cannot widen SSRF reach; every transition is advisory-locked + `select_for_update`'d inside the
transaction (`lifecycle.py:369-386`), audited including failures (`:420-443`), and there is not a bare
`except Exception: pass` in the zone — the problem is what is swallowed, not that swallowing is hidden;
and both models inherit `CoreModel` with a migration that mirrors the partial unique constraint.

### 9.6 `devices` + `mydoc` + `backend/config` + build files — 75 files, delegate read all; this
author re-read every item below

**F78 — Med — `STATICFILES_STORAGE` in the production settings is a no-op on the Django this project
pins, so nothing is content-hashed while nginx caches for 30 days.**
`backend/config/settings/production.py:42` sets
`STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'` under the
comment "content-hashed filenames for cache busting (EC-35)". That setting was deprecated in Django 4.2
and removed in 5.1; `requirements/base.txt:1` pins `Django>=5.2,<5.3` and the venv on this host reports
**5.2.18**. The live static backend is `STORAGES['staticfiles'] =
…StaticFilesStorage` (`settings/base.py:182-184`), which production never overrides, and Django 5.2
reads only `STORAGES` (`django/contrib/staticfiles/storage.py:542` resolves
`storages[STATICFILES_STORAGE_ALIAS]`). Consequence: `collectstatic` emits plain filenames, nginx serves
`/static/` with `Cache-Control: public, immutable` and `expires 30d`
(`provisioning/docker/nginx/conf.d/ifinmail.conf:235-239`), and the only thing between a user and a
stale stylesheet is the `_css_content_version()` hash in `settings/base.py:154-169` — which covers
`*.css` only, is computed at import time, and does nothing for JS. *Pointer:* move the intent into
`STORAGES` and drop the dead key, or accept plain names and shorten the nginx TTL.

**F79 — Med — 15 of the 16 periodic/sent tasks in core have no time limit, with `acks_late` on.**
`backend/config/settings/base.py:229-233` sets `CELERY_TASK_ACKS_LATE = True` and a JSON-only serializer
and defines no `task_time_limit`, `task_soft_time_limit` or `task_acks_on_failure_or_timeout`; the beat
schedule has ~26 entries (`:234-363`). So `telemetry/tasks.py` (6 tasks), `core/tasks.py:21,54,75,95,104`,
`plugins/tasks.py:10`, `storage/tasks.py:12`, `releases/tasks.py:10` and the mail senders all run without
a deadline, are redelivered if the worker is killed mid-flight, and — with the F46 LLM call inside a
transaction and the F47 ~72 MB log tail — one slow provider or one large log set can occupy a worker
slot indefinitely. This is the confirmed answer to §6's open question (a).

**F80 — Low (latent, currently unreachable) — the device registry has no owner and re-activates on
every register.** `backend/apps/devices/models/__init__.py:6-13` defines `Device` with a globally
unique client-supplied `identifier` and no user/tenant column; `DeviceService.register`
(`services/__init__.py:40-55`) does `update_or_create(identifier=…, defaults={… 'is_active': True, …})`,
so a colliding identifier overwrites another tenant's name/type and clears a revocation, and
`set_active`/`touch` (`:57-74`) mutate any row by identifier alone. None of it is reachable over HTTP:
`devices/urls.py:4` is `urlpatterns: list[URLPattern] = []` and `backend/config/urls.py:180` includes
that empty list, so the four viewset functions in `devices/viewsets/devices.py` have no route, no
auth and no scope — the zone ships 29 files of scaffolding with zero surface, and the moment push or
per-device sessions are built on it, they inherit an owner-less table. There is no FCM/APNs credential
or token field anywhere in the app, so the "push hijack" concern is not applicable today.
*Pointer:* add the owner FK, an ownership filter in every method, a server-issued pairing secret, and
make revocation durable *before* any route is added.

**F81 — Low — `mydoc` is dead code that still ships and is still excluded from every quality gate.**
`backend/apps/mydoc/apps.py:10` declares `name = "backend.apps.core.mydoc"` — a module that does not
exist — and `__init__.py:1` sets `default_app_config`, removed in Django 4.1. The app is in neither
`INSTALLED_APPS` (`settings/base.py:30-57`) nor `ROOT_URLCONF` (`config/urls.py`), so its 8 views,
`urls.py` and 7 templates are unreachable; `pyproject.toml` then excludes it from ruff, pytest
(`--ignore=backend/apps/mydoc`) and coverage. Had it ever been wired, `mydoc/config.py:20` defaults
`REQUIRE_AUTH` to `False`, none of its views carry a login gate, and
`introspection.discover_api_endpoints()` walks the live resolver — i.e. an API map with permission and
serializer metadata, unauthenticated. Its own test file imports
`backend.apps.core.accounts` and reads a workflow that is not tracked. Verdict: delete or port; 25
files for zero function, plus a misleading "audit" surface.

**F82 — Low — the critical-env system check tests a different variable than the settings module
reads.** `settings/base.py:21` accepts `DJANGO_SECRET_KEY` **or** `SECRET_KEY` (with a comment explaining
why), and `check_critical_env_vars` (`base.py:409-429`) lists only `DJANGO_SECRET_KEY`, plus
`DB_NAME`/`DB_USER`/`DB_PASSWORD`, as required. A `SECRET_KEY`-only install therefore boots and then
fails `--deploy` with `ifinmail.E001`; conversely the DB checks fire on a SQLite dev database where they
are irrelevant. Also: the check is registered but nothing in the zone asserts the deploy gate is ever
run in CI.

**F83 — Low — Celery's fallback settings module is `development`.**
`backend/config/celery.py:9` does `os.environ.setdefault('DJANGO_SETTINGS_MODULE',
'backend.config.settings.development')` — `DEBUG=True`, SQLite, a committed placeholder key
(`settings/development.py:12,19,27-33`). The shipped compose forces `production` for the worker
(`provisioning/docker/docker-compose.yml:461`), so this bites only a hand-run
`celery -A backend.config.celery worker`. Same class as the nginx `X-Forwarded-Host` default: it is the
non-compose path that is unguarded.

**F84 — Low — token-bearing paths are written to the application log by the error handler.**
`backend/config/urls.py:233-238` logs `request.path` for every handled error, and the token-carrying
routes are path-shaped (`/t/o/<token>.gif`, `/t/c/<token>/`, `/unsubscribe/<token>/`), so a 404 on a
prefetched tracking pixel puts a live unsubscribe/open token into the container log. The nginx access
log does the same on a much larger scale (F99).

**Confirmed-and-no-finding from this zone:** the devices model/service are governance-clean
(`CoreModel`, all access through `DeviceService`, `DeviceType` in `types/`, `managed = True` so no DDL
is owed to `init-db.sh`); no predictable `SECRET_KEY` default exists (base raises), the shipped `DEBUG`
and `ALLOWED_HOSTS` states are correct (`production.py:6,10-14` raise rather than default), CSP is
enforced not report-only by default (`production.py:71-88`, `CSP_REPORT_ONLY` must be set to `'true'`
to relax it), cookie flags are right (`base.py:192-193`, `production.py:59-60`), `SECURE_HSTS_*`
defaults are the strong ones, DB TLS is `sslmode=require` in production (`:35`), `LOGGING` has only
stdout + telemetry handlers and nothing writes logs into a web-served directory, and
`SECURE_REDIRECT_EXEMPT = [r'^health']` (`:48`) is a deliberate, non-secret liveness exception. The
`branding_overrides.json` tracked-and-runtime-written file is the only such case in the repo
(`git ls-files *.json`).

### 9.7 `core/storage` + `core/base` — 88 files, delegate read all; this author re-read the High and
every Med

**F85 — High — storage authorisation only exists on the path nginx does not take.**
`backend/apps/core/storage/views/media.py:27-40` implements `_may_read` (public prefixes, `PUBLIC`
rows, or staff) and the module docstring is explicit that "when media is on this server's disk nginx
serves it directly and this view is only reached for a file that is not there". That is exactly the
problem: `provisioning/docker/nginx/conf.d/ifinmail.conf:256-259` is
`location /media/ { root /app; try_files $uri @media; }` — no `auth_request`, no `internal` — and the
same volume is mounted into both containers (`docker-compose.yml:412` api `media_data:/app/media`,
`:535` nginx `media_data:/app/media:ro`). `StorageService.upload` writes real files under `MEDIA_ROOT`
at `storage/<entity_type>/<uuid4hex>.<ext>` (`models/stored_file.py:10-16`, `backends.py:43-52`), so a
`PRIVATE` row (the column default — `stored_file.py:33-37`, `default=StorageVisibility.PRIVATE`) is
reachable by any anonymous GET to `/media/storage/...`. The gate is dead code for precisely the files
it was written to protect, and it starts returning 404s for the same URLs the moment media moves to
object storage — the semantics flip with a plugin setting. Two mitigating facts, stated so the severity
is not oversold: the key is a `uuid4` hex, so this is capability-by-URL rather than enumeration, and no
reachable code path creates a `PRIVATE` row today (the only live uploader,
`releases/services/release_service.py:176-182`, flips it to `PUBLIC` inside the same transaction;
`storage/viewsets/__init__.py:17` has no route). What is actually broken is the contract: **the
visibility column has no effect while media is on disk**, which is the shipped default, and any feature
added on the documented promise of `PRIVATE` will be world-readable. The blind spot is also locked in
by a test: `core/tests/test_provisioning_contract.py:407-415` asserts nginx *must* serve `/media/` from
the volume, with the rationale "branding images 404" — the whole tree is opened for the sake of one
prefix. And `test_storage_contract.py:283-292` proves the private-404 only against the routed in-memory
store, while its only local-disk case (`:245-251`) uses a public `branding/` key.
*Pointer:* `location /media/ { auth_request /_media-auth; try_files $uri @media; }`, or serve only
`/media/branding/` from disk and always `@media` everything else.

**F86 — Med — any database failure silently reroutes media to the local disk.**
`config.current()` wraps the plugin read in `except Exception: return None`
(`services/config.py:55-56`, comment "no database yet (first boot, migrations): the disk is always
safe"). The branch is right for first boot and wrong for every other failure: a blip, a locked plugin
row or a migration in flight all look like "no object-storage plugin", so `store_for('media')`
(`:94-102`) returns `local_store()` and **writes land on the disk the operator believes is
decommissioned**. `describe()` (`:113-131`) then reports `configured: False`, so the status page
confirms the wrong story rather than flagging the anomaly. *Pointer:* distinguish "no rows" from "read
failed", and refuse to reroute when `health.last()` shows an external store was working.

**F87 — Med — deleting a file can orphan its bytes permanently, with no way to find them again.**
`signals.py:13-27` runs on `post_delete` — the row is already gone — and catches only
`(OSError, FileNotFoundError)` (`:21`). `StoredFile.file.delete(save=False)` goes through
`backends.ObjectStorage` → `store.delete`, whose failures are `StorageError` subclasses
(`StorageUnavailableError`, `StorageRejectedError`), neither caught: the exception escapes the signal,
the user's delete turns into a 500, and the bytes stay in the bucket forever. There is no reconciler —
`storage/tasks.py` only probes, and the CLI has no `delete`/`list-diff` — so nothing can even discover
the orphan. The reverse case is also mishandled: when the remote delete fails *softly* the row is gone
and only a `logger.warning` records it.

**F88 — Med — the media view can 500 on a store that will not build.** `views/media.py:62`
(`store = config.store_for('media')`) sits **outside** the `try` blocks that turn storage failures into
404/503 (`:78-83`). A secret that fails to decrypt (`config.py:64-68` swallows only `ValueError` into an
empty key, not every path), a bad prefix raising `InvalidKeyError` from
`drivers/s3.py:95`, or a driver `StorageError` during construction escapes as a 500 on a public URL —
the opposite of the module's own "anything else is a plain 404" rule. Related, low: the same
`public_base_url` branch (`:59-66`) builds the redirect from an admin-entered string with no address
policy (F31 family), and `head()` + `open()` (`:78-86`) is a TOCTOU pair whose `Content-Length` can
disagree with the body; neither driver supports `Range`, so downloads cannot resume.

**F89 — Med — `content_type` means different things per driver, and the client's string is one of
them.** The local driver **discards** the caller's type and re-guesses from the filename
(`drivers/local.py:56` via `mimetypes.guess_type`), while the s3 driver stores it verbatim
(`drivers/s3.py:239,258`) and `backends.ObjectStorage._save` forwards `content.content_type` — the
uploading client's declared MIME — straight to the store (`backends.py:48-51`). `media.py:59` and `:85`
then answer with `info.content_type`, so the same key serves one type on disk and another in the bucket,
and the F40 branding case (browser-declared type stored and replayed) is only the visible symptom of a
contract that has no canonical type. Worse, `_key()` at `backends.py:32` rewrites `\` → `/` and strips
leading slashes **before** `check_key`, so a contract-invalid key is silently normalised instead of
refused. *Pointer:* decide the type at upload from magic bytes, store it once, and have both drivers
return the same thing.

**F90 — Med — `.svg` is allow-listed and served inline from the site origin.**
`services/__init__.py:34,58` admit `.svg` as `image/svg+xml`, and nothing in
`views/media.py` or the nginx `/media/` block sets `Content-Disposition` or a sandboxing
`frame-src`; combined with F85 (anonymous disk reads) and the uploader-chosen extension, an uploaded
SVG executes its script in the site's origin for whoever opens the URL. This is distinct from F32
(branding fonts) and from F40 (type stored from the client). The APK block at
`ifinmail.conf:244-251` shows the correct pattern already — forced `attachment` + `nosniff`.

**F91 — Med — the storage CLI cannot verify what it stored, cannot prune what it should, and has no
read path.** `management/commands/storage.py:62` prints `sha256` computed from the **input stream**
(`local.py:66-88` digests while writing; `s3.py` multipart never re-reads), yet
`provisioning/scripts/backup_offsite.sh:88-93` and `docs/storage-contract.md:138` describe that number
as verified in object storage. `_prune` (`:70-81`) only deletes when `item.modified is not None`, and
the s3 driver returns `modified = None` whenever `LastModified` is missing or unparseable
(`drivers/s3.py:392-395`) — retention then silently stops while the command cheerfully prints
"Removed 0 backup(s)". No `--dry-run`, no confirmation, no floor on `--days`. The action list
(`:26-31`) is six verbs with **no `get`, no `restore`, no `delete`**: an off-site backup can be written
and pruned but never fetched through the sanctioned interface, which is exactly how a future caller
ends up bypassing `StorageService`. `_status(self, purpose, options)` (`:44-46`) ignores `purpose`, and
`_upload` reads `sys.stdin.buffer` unconditionally, so an empty stdin stores a 0-byte object. Note the
known F33 defect still governs this whole file — `backup_offsite.sh:81` calls the mis-bound
`upload --purpose backups "$name"` form, so the nightly copy fails loudly today.

**F92 — Med — `sync-media` copies whatever is under `MEDIA_ROOT` into the *media* store and trusts
`exists()`.** `:83-95` lists the local store with an empty prefix and, for anything the remote does not
already have, streams it in with `content_type=item.content_type`. Nothing restricts the copy to keys
that belong to media, no size or checksum is compared, and a key present remotely is counted as
"already there" without verifying it is the same bytes; deletions never propagate. It also reaches into
one driver's private method (`open(local._path(...))`, `:92`) — the same coupling `backends.py:67-69`
has (`store.name != 'local'` + `getattr(store, '_path')`), which is how a contract layer turns into
per-driver branching.

**F93 — Med — nothing owns a stored file, so "private" can only mean "not staff".**
`StorageService.upload(*, file, user, entity_type, entity_id, merchant_id)` accepts `user` and
`merchant_id` and drops both (`services/__init__.py:83-130` — the row is created from
`StoredFile.objects.create(file=…, original_filename=…, content_type=…, size_bytes=…, entity_type=…,
entity_id=…)` only). `StoredFile` has no owner or tenant column and `CoreModel`
(`core/base/models/base.py:6-19`) supplies just `id/created_at/updated_at`, so `_may_read`
(`views/media.py:37-40`) can only test `user.is_staff or is_superuser`: every staff account reads every
private file. AGENTS.md names "Visibility & Accountability / base mixins" as a mandatory principle and
prescribes `ImageAttachableMixin`/`FileAttachableMixin` — `grep` shows **zero** models use either and
zero tests cover them (`mixins/image_attachable.py:20` even uses `SET_NULL` where AGENTS.md's own
example uses `PROTECT`). There is no `Merchant` model in the repo at all, so the documented scoping
mechanism is fiction.

**F94 — Med — the object-storage plugin's own URL rule permits plaintext.**
`plugin_contract.py:36-42` (`_url`) accepts `http://` for both `endpoint` and `public_base_url`, so
SigV4 `Credential=` + signature headers and presigned bearer URLs — clamped at up to 86400 s
(`config.py:80`) — can cross the wire in the clear, and there is no private-address check at all,
contradicting `bundled/object-storage/plugin.toml:16`. Same shape as F62: an address the plugin layer
validates for syntax only.

**Lower-severity items, confirmed:** `StorageVisibility.INTERNAL` is never honoured
(`media.py:31-32` tests `== PUBLIC`) and never set by any caller; `check_key`
(`contract.py:44-56`) rejects `.`/`..`/backslashes/control characters but is filesystem-blind, so on
NTFS the "valid on one store is valid on all" promise fails for `: * ? " < > |`, reserved names
(`nul`, `con`), trailing dots and case variants (`a.png` vs `A.png`) — **SUSPECTED** as a runtime
effect, CONFIRMED as a contract gap; `drivers/__init__.py:18-30` never checks a factory's result
against the `runtime_checkable` `ObjectStore` protocol declared at `contract.py:77`, so an incomplete
driver fails at request time; `tests/memory_store.py:33` enforces `check_key` on `put` only, so a
malformed read key passes in tests and raises in production, and its `put_stream` buffers the whole
object (`:42`) — the "streams the object" test cannot catch a memory blowup;
`local.py:66-88` and `s3.py` diverge on a key that is also a directory prefix; no driver caps write
size and `get()` buffers up to a 64 MiB per-call default (`contract.py:20`);
`drivers/s3.py:449` `stream_bytes()` has no caller; `accounts/views/file_storage.py:65` catches only
`CommandError` around the `sync-media` call, so a raw `OSError` from a file deleted mid-walk is a 500 on
the admin page; `verify_audit_chain.py:7` imports `platform.services.audit` cross-app **without** the
AGENTS.md-mandated exception comment (while `audit_structure.py:1-2` carries the comment and imports
nothing), `backend/apps/core/management/commands/` has no `__init__.py` unlike its siblings,
`audit_structure.py:45` uses the CWD-relative `Path('backend/apps')` so the compliance gate exits 1 from
anywhere but the repo root, and `storage.last_probe` (`health.py:15`) is not in the `SettingKey`
catalogue so the settings API can never read or audit it; `migrations/0003` is stamped "Django 5.2.18"
against 0001/0002's "5.1.15" and is choices-only, so it is state-only — worth one
`makemigrations --check --dry-run` to confirm no drift.

**What storage got right (verified, and these are the properties the next change must not break):**
purpose routing fails safe — `store_for` rejects an unknown purpose before any fallback (`config.py:96-97`)
and `backups` on the local disk raises instead of writing into `MEDIA_ROOT` (`:100-101`, asserted at
`test_storage_contract.py:182-183`); `s3.put_stream` aborts the multipart upload on **any** exception
including `BaseException` (`s3.py:304-307`) with 16 MiB parts and a `MAX_PARTS` cap; no secret ever
reaches a repr, log or exception (`s3.py:76` `field(repr=False)`, `_fail` emits only server `Code`/
`Message`, `describe()` omits values, `StoreSettings.values` is `repr=False` — asserted at
`test_storage_contract.py:114-123,218`); signed-link lifetimes are clamped on both sides
(`config.py:80`, `s3.py:421`) and `media.py:76` sets `Cache-Control` to `url_seconds − 30` so a cache
cannot outlive the link; `LocalStore.put_stream` is atomic (temp + `os.replace`, `local.py:71-83`) and
`list()` skips `.upload-*` leftovers; `_path` (`local.py:42-47`) is the one driver with a real
leave-the-root guard (F34's static verdict: the **code** is sound — the problem is that
`test_storage_contract.py:77-84` uses a bare `os.symlink` with no skip guard, so on this host it errors
and the property goes unverified, unlike its siblings at `plugins/tests/test_policy_plugins.py:446` and
`test_server_edge.py:213`); probes write 32 random bytes, read them back and delete
(`local.py:153-164`, `s3.py:426-446`), and `health.run_probe` records only a *state change*; `sigv4.py`
is a pure implementation checked against AWS's published vectors including presign; `entity_id` is NULL
not `''` with the reason documented; and no Python caller outside the app bypasses the contract —
`default_storage` routes to `ObjectStorage`, and there is no `ImageField`, no `upload_to=` and no vendor
SDK call in `backend/apps` (grep-verified), which makes F85's nginx path the only governance gap in the
zone. `config/branding.py:78-97` (`_existing_upload`) does build a path from `MEDIA_ROOT`, the practice
AGENTS.md forbids, and is the closest thing in the repo to a `StorageService` bypass.

### 9.8 `provisioning/docker` — 78 files, delegate read all; this author re-read the Highs and the
marked Meds

**F95 — High — the internal mail relay accepts mail from every container on the network, and rspamd
then signs it for the real domain.** `postfix/master.cf:41-47` publishes port 10025 on `inet` with
`smtpd_sasl_auth_enable=no` and `permit_mynetworks,reject` on all three restriction lists;
`postfix/entrypoint.sh:41-43` sets that service's `mynetworks` to `127.0.0.0/8,$internal_net` — the
whole Docker bridge, because `docker-compose.yml:390-391` gives the api no credentials for
`EMAIL_HOST: postfix` / `EMAIL_PORT: 10025`. The port is not published, but every one of the
internet-facing containers (rspamd, dovecot, nginx, dns, dav, redis) sits on that same flat bridge
(`:580-582`). `rspamd/local.d/dkim_signing.conf` then sets `allow_username_mismatch = true` (`:9`),
`sign_local = true` (`:10`) and `use_domain = "header"` (`:15`), and `master.cf:47` marks the
10025 session `ORIGINATING`. Any position inside the network can therefore submit mail as any address
of any hosted domain and receive a valid DKIM signature, an aligned DMARC pass, and a clean reputation —
the standard tool for bypassing a victim's own spam filtering. Precondition is a compromised container,
so this is a blast-radius finding rather than an anonymous one; it is also structural, since nothing
limits which container may claim which `From`. *Pointer:* split the relay network to api/worker only, or
enable SASL + `reject_sender_login_mismatch` on 10025 and keep `sign_local` off for unauthenticated
paths.

**F96 — High — Dovecot's LMTP and auth sockets are world-writable in a volume shared with three
containers.** `dovecot/conf.d/10-master.conf:44-49` creates `…/lmtp` with `mode = 0666` and `:53-58`
creates `…/auth` with `mode = 0666` (`auth-userdb` is correctly `0600` at `:60-63`); the `rundir` volume
is mounted into postfix (`docker-compose.yml:86`), dovecot (`:136`) and **dav** (`:245`), and dav runs as
uid 5001 (`dav/Dockerfile:16`). Consequences: any process in those containers can deliver mail directly
into any mailbox — past recipient checks, milters, rate limits, rspamd, and with no Postfix log line, so
the delivery trail the audit story depends on simply does not exist for those messages; and the same
process can drive the auth socket for unlimited password testing with no rate limiting (F100). Fix:
`mode = 0660` with a shared group, or one `rundir` per consumer.

**F97 — Med — the firewall agent executes whatever rules file it is given, and records a rejected
ruleset as applied.** `firewall/entrypoint.sh:101` runs `nft -f "$RULES"` after `nft -c -f`, which is a
*syntax* check only; the header comment at `:7` promises "Only the `inet ifinmail` table is ever
touched", and `cleanup()` at `:110-114` proves arbitrary statements are expected by deleting tables.
`/runtime` is mounted read-write into api (`docker-compose.yml:414`), worker (`:493`) and dns (`:274`),
so any of them can write `delete table inet filter` and open port 22 and every published service.
Separately, `apply_rules()` sets `applied="$digest"` on **both** branches (`:102` and `:105`), so a
rejected ruleset is never retried, and `restart: unless-stopped` does not revive an unhealthy container —
the operator's intended entry policy can be permanently not-in-force with only
`firewall-status.json` saying so. *Pointer:* render inside a fixed `table inet ifinmail { … }` wrapper,
reject files mentioning another table, and do not record `applied` on failure.

**F98 — Med — the console's own CSP is enforced by nginx too, and the documented emergency switch
cannot disable it.** `ifinmail.conf:98-100` hides only `Strict-Transport-Security`,
`X-Content-Type-Options` and `X-Frame-Options` from upstream; `:106` then `add_header`s a full enforced
`Content-Security-Policy`. So the browser receives a second, env-independent policy that
`CSP_REPORT_ONLY=true` (`settings/production.py:87`) cannot relax — the exact "emergency switch"
`docs/risk-register.md:18` advertises (recorded here as the correction to §7's CSP row) — and the two
policies already differ: nginx's `img-src` is `'self' data:` with no `blob:`, and it has no
`report-uri`, so violations stop reaching `/csp-report/` whenever nginx's copy is the binding one.
*Pointer:* add `proxy_hide_header Content-Security-Policy;` and
`proxy_hide_header Content-Security-Policy-Report-Only;`, or delete the nginx copy.

**F99 — Med — every request path, including tracking and unsubscribe tokens, is written to a log
volume other containers can read.** `ifinmail.conf:29-33` defines `log_format ifinmail_json` with
`"uri":"$request_uri"` — path **and** query string — and `:34` sends it to
`/var/log/ifinmail/access.json` on the `mail_logs`/`nginx_logs` volumes, which the firewall (`:304`) and
worker (`:498`) containers mount. The open/click/unsubscribe URLs carry their token in the path
(`mail/services/tracking.py:121-126`, `marketing.py:205`), so anyone who can read that file — or any
container that mounts it, which `:304` and `:498` above already establish — can harvest live one-click
unsubscribe links and forge opens for
in-flight campaigns. Reset and signed-media query tokens are captured the same way. Same class as F84,
at full traffic scale. *Pointer:* log `$uri` without the query for the token-bearing locations, or route
those through a `map` that strips them before `access_log`.

**F100 — Med — authentication is single-threaded by configuration, and the file that claims otherwise
is the one that would have to enforce it.** `dovecot/conf.d/10-master.conf:64-69` sets
`service auth { … process_limit = 1 }` (and `client_limit = 400`); the docstring at `:7` says "IMAP
login: rate-limit authentication attempts", but no rate limit is configured anywhere in the file.
`/dav/` authenticates through that same socket via nginx (`ifinmail.conf:217-232`), so a modest
password-guessing run against CalDAV serialises *all* authentication on the host — IMAP, SMTP AUTH,
submission and DAV share one process. This is the dovecot-side twin of the axes/Axes findings in §5.

**F101 — Med — DKIM signing stops silently if the selector is changed in the console.**
`rspamd/local.d/dkim_signing.conf:7` hardcodes `selector = "default"`, while the console names the key
files from `DKIM_SELECTOR` (`domains/services/dkim.py:32,38` write `<domain>.<selector>.key`, and
`provisioning/.env.example:31` offers the variable). rspamd's environment
(`docker-compose.yml:171-173`) carries only `TZ`, `REDIS_PASSWORD` and `RSPAMD_CONTROLLER_PASSWORD` — no
`DKIM_SELECTOR`. Change the selector and `path` misses for every domain; `try_fallback = true` (`:14`)
then finds nothing, outbound mail continues unsigned, and DKIM alignment breaks with no error surfaced.
Also note the comment at `:12-13` is the only reason `try_fallback` exists, so the two settings are
coupled by prose, not by code.

**F102 — Med — mail flows unfiltered and unsigned when rspamd is not up, with no dependency gate.**
`postfix/main.cf:59` sets `milter_default_action = accept` and `docker-compose.yml:94-98` makes postfix
depend only on postgres and dovecot — there is no `rspamd` condition. On a boot where rspamd is slow or
crashed, the queue accepts, does not scan and does not sign, and the only evidence is a log line.
For a product whose headline promise is DKIM-aligned sending, "fail open" is the wrong default here
(`tempfail` would hold mail instead of leaking unsigned).

**F103 — Med — the certbot container is always healthy and renewal failure is invisible.**
`docker-compose.yml:352` runs `pgrep -f certbot` inside `sh -c`, so the process matching the pattern is
the healthcheck's own shell — the check passes even with a dead renewal loop. `certbot/entrypoint.sh`
echoes renewal and `sync_hosts` failures (`:181-184`, "some failures are expected") and writes
`cert-status.json` only for console-initiated requests (`:56-79`), so an expiring certificate produces no
signal anywhere while `docs/enterprise-slo.md:16` promises ">30 d renew, <7 d CRITICAL". Two independent
findings, one root cause: the health probe is a tautology and the status file is request-scoped rather
than state-scoped.

**F104 — Med — an uploaded TLS private key transits a volume mounted into nine containers.**
`core/platform/services/tls.py:294-302` stages the pair at `runtime/tls/incoming/{fullchain,privkey}.pem`
(key at 0600) and `certbot/entrypoint.sh:95-116` moves it only when both files are non-empty and the
request id is new (`:105-107,136`); `clear_incoming()` exists (`tls.py:305-307`) and has **no caller in
the repo**. If the pair is incomplete, certbot is down, or the id was already consumed, the key stays on
`runtime_data` — mounted into postgres, redis, postfix, dovecot, rspamd, dav, dns, nginx, api and worker
(`docker-compose.yml:87,137,178,246,274,303,336,414,493`). `docs/secrets-map.md:15` claims TLS keys are
"mounted read-only into the console", which is true of `certs/` and false of this staging path.

**F105 — Med — schema init and upgrade run without a transaction, and the failure is printed as a
warning.** `init-db.sh:13` and `db-upgrade.sql` are piped to `psql -v ON_ERROR_STOP=1` with neither
`--single-transaction` nor a `BEGIN` wrapper, so a statement that fails halfway leaves the earlier DDL and
grants committed; `provisioning/scripts/provision.sh:474-477` then continues after
`|| echo "WARNING: could not apply db-upgrade.sql"`. The result is a half-migrated schema that looks
provisioned — and, per F116, a contract test that cannot see it because it only greps column names in the
concatenated text of both files.

**F106 — Med — a slow migration can wedge the whole stack.** `init-db.sh:164-166` applies
`ALTER SYSTEM`-level `statement_timeout = 30s` / `lock_timeout = 10s` database-wide, the api entrypoint
runs `manage.py migrate` (`:52-57`), and both nginx (`:539-541`) and worker (`:418-423`) gate on the api's
`condition: service_healthy`. Any migration that legitimately takes over 30 s aborts, the entrypoint
exits 1, the api never becomes healthy and neither the console nor the queue starts. **SUSPECTED as a
timing effect**, CONFIRMED as a chain. *Pointer:* exclude `migrate` from the timeout (a per-session
`SET statement_timeout = 0` in the entrypoint).

**F107 — Med — Redis is shared by three subsystems with no memory policy inside a 128 MB limit.**
`docker-compose.yml:53` starts redis with `requirepass` but no `maxmemory`/`maxmemory-policy`, `:373-374`
put the Django cache on `…/0` and the Celery broker on `…/1`, and `rspamd/local.d/redis.conf:2-5` uses
db **0** as well — the same database as the console's cache. Bayes/fuzzy/greylist growth therefore evicts
(or, with the memory limit, OOM-kills) session and queue data: one noisy mail feature takes down the app
and the send pipeline together. Related: `rspamd/rspamd.local.lua:40` calls
`parse_redis_server('ifinmail_outbound')` for a server no config in the repo defines, and the whole
symbol is guarded by `if counter_redis then` — so the per-login counters behind
`docs/risk-register.md:12` may silently never be written (**SUSPECTED**, needs rspamd logs).
`rspamd/local.d/dmarc.conf:3-15` enables reporting with `send_mail_from` but **no** `servers`, so
reports queue in `rspamd_data` (uncapped, unrotated) and never send.

**F108 — Med — the SMTP port advertises AUTH to the internet and does not check the sender.**
`postfix/main.cf:37` enables `smtpd_sasl_auth_enable` globally and `master.cf:10` does not switch it off
for port 25, which runs at `security_level = may` (`:64`) — so opportunistic STARTTLS then `AUTH`, with
`reject_sender_login_mismatch` present only on the submission services (`master.cf:19`). A credential
captured or harvested on 25 relays as any address, DKIM-signed. Port 25 should not offer AUTH at all.

**F109 — Med — SWEET32-capable ciphers are still offered on 443 and on 993/995.**
`ifinmail.conf:84` and `dovecot/conf.d/10-ssl.conf:8` both use
`HIGH:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4`. `!DES` does not exclude 3DES (the keyword for that is
`!3DES`, or list `!DES-CBC3-SHA`/`!ECDHE-RSA-DES-CBC3-SHA`), and no `ECDHE-ECDSA-AES128-GCM-SHA256`-style
modern-only list is used, so the 64-bit-block CBC3 suites stay offerable. **SUSPECTED** — the actual
offer depends on the OpenSSL build; prove with
`openssl s_client -connect <host>:443 -cipher 'DES-CBC3-SHA'` and the same on 993. Also: no
`ssl_dhparam` in nginx (`:90-92`, with `ssl_stapling off` documented) while dovecot loads
`/etc/dovecot/certs/dh.pem` (`10-ssl.conf:12`), `ssl_session_tickets` is not disabled, and the resolver
is `1.1.1.1 8.8.8.8`, which leaks every lookup to third parties.

**F110 — Med — a dev-tree build bakes the developer's database into the api image.**
`docker-compose.yml:361-363` sets the api build `context: ../..` (repo root) with
`dockerfile: provisioning/docker/Dockerfile`, whose `COPY . .` (`Dockerfile:17`) copies everything not
excluded. `.dockerignore` correctly drops `.env`, `provisioning/.env`, `dkim/*.key`, `dkim/*.pub`,
`certs/`, `media/`, `staticfiles/`, `venv/`, `.git/`, `*.md`, `Makefile`, `backups/`, `*.gpg` — but **not**
`db.sqlite3` (present in this working tree, 466 KB, untracked), `*.pem`, `branding_overrides.json`,
`.agents/`, `examples/` or `client/`. A `docker compose build` run from a developer's checkout therefore
copies the dev database — password hashes, sessions, API-key prefixes and all — into image layers, where
any later `docker push` or shared registry exposes it. **SUSPECTED** only in the sense that it needs a
build to prove; the ignore-list gap is confirmed.

**F111 — Med — Locally built images are consumed by tag.** Seven services use
`image: ifinmail/<x>:latest` with a sibling `build:` (`docker-compose.yml:74,124,169,214,238,268,295`) and
`certbot/Dockerfile:1` is `FROM certbot/certbot:latest`, so `docker compose up` can start a stale image
long after the code changed, and `docker compose up --build` is not documented as required.
`docs/risk-register.md:15` acknowledges tag-not-digest for *bases* only; the `:latest` self-tag is the
same failure with a shorter path.

**F112 — Med — the port-80 listener redirects any Host.** `ifinmail.conf:64-66` has no `$ifm_refuse`
guard (the 444 refusal is only in the 443 server, `:77`) and answers
`return 301 https://$host$request_uri`. An attacker-controlled `Host` therefore produces a redirect to
an attacker-controlled hostname from the cleartext listener, and `301`s are cached aggressively by
browsers and intermediaries. `nginx/allowed-hosts.sh:31-36` compounds it when provisioning is
incomplete: an empty `ALLOWED_HOSTS` yields `default 1` — fail **open** on the scanner-Host filter.

**F113 — Med — Radicale's rights file probably grants nothing, and may grant it anonymously.**
`dav/rights:19-27` uses lowercase permission letters (`[directory] permissions: r`,
`[collections] permissions: rw`) with `user: .+`. In Radicale's `from_file` semantics lowercase means
*any* (anonymous) user while the owner-only rule needs uppercase `R/W`, and `user: .+` never matches the
empty anonymous login — so the shared read-only directory, and possibly every user's calendars, can be
inaccessible or, if the lowercase form does match, world-writable. **SUSPECTED** — the web lookup for the
current semantics failed on this host; settle it with one `PROPFIND` as a normal user and one anonymous.

**Lower-severity items, confirmed:** `/static/` (`:235-239`), `/static/error-pages/` (`:129-133`) and the
`.apk` location (`:244-251`) each re-declare `add_header`, so they lose the inherited HSTS/CSP/XFO/nosniff
set (this is the F41 mechanism, now traced to the three locations that trigger it); `/static/` and
`/media/` carry no `limit_req` while every dynamic location does; `client_max_body_size 50M` (`:119`) vs
`main.cf:83 message_size_limit = 50 MiB` means a 50 MB upload passes nginx and fails SMTP after base64
inflation (~33 %); no service sets `security_opt: [no-new-privileges:true]`, `cap_drop: ALL`,
`read_only`, `pids_limit` or `cpus`, and only postfix sets `ulimits`; the redis password and rspamd
controller hash are `sed`-written to `local.d/*.conf` at default 0644 (`rspamd/entrypoint.sh:8-21,28`)
where dovecot/postfix chmod 640 (`:44-47`, `:52-57`), and the mail logs are 0644 on a shared volume;
`gunicorn` (`Dockerfile:32`) sets no `--limit-request-fields`, `--limit-request-line` or `--max-requests`;
`dns/knot.conf:32` `ksk-lifetime: 0` means no automatic KSK rollover; `unbound.conf:2-36` has no
`auto-trust-anchor-file`, so `harden-dnssec-stripped` has no anchor to validate against (not an open
resolver — `access-control: 0.0.0.0/0 refuse`, port unpublished); Radicale's
`max_content_length = 20000000` is *smaller* than nginx's `client_max_body_size 20M` (20 971 520), so a
20–21 MB PUT returns Radicale's 413; `certbot/entrypoint.sh:67` word-splits an unquoted
`email_args="-m $ADMIN_EMAIL"`; `dovecot/sieve/before.d/00-spam.sieve` is never compiled — `sievec`
appears in no Dockerfile or entrypoint — so the global spam move is either inert or an error per
delivery; `cert-watch.sh:11` polls `cksum` on `fullchain.pem` only and a failing `nginx -s reload` is
silently retried; rspamd's `worker-normal.inc:2` binds `0.0.0.0:11333`, unauthenticated, reachable by
every container (not published).

**What provisioning got right (worth keeping on the record):** api, rspamd milter and controller are bound
to `127.0.0.1` (`:182-183,417`) and postgres/redis/dav/resolver publish nothing; no `privileged`, no
`docker.sock`, no host `pid`/`ipc`, and the only `network_mode: host` is the firewall with `NET_ADMIN`
alone — the correct minimum; `mail_data` is read-only in api/worker and no container writes mail into a
web-served directory; every long-running service drops privileges (`Dockerfile:25-27` +
`entrypoint.sh:93-96`, `dav/Dockerfile:8-16`, `rspamd -u _rspamd`, knot `server: user:`); the XFF chain is
consistent and takes the **last** hop (`ifinmail.conf:145,166,177,191,203,266` append, `:227` overwrites
for `/dav/`) and `accounts/services/client_ip.py:16-21` / `api_access.py:32-37` both read `[-1]`, so no
header-spoofing shortcut exists; TLS is 1.2/1.3 only with HSTS two years + `includeSubDomains; preload`,
`X-Frame-Options: DENY`, `frame-ancestors 'none'`, `Referrer-Policy: same-origin`, `Permissions-Policy`,
`limit_conn`/`limit_req` returning 429, and `server_tokens off`; the three plugin watchers allow-list
keys and regex-check values before applying and rspamd rolls back on a failed `configtest` (F34's guard
holds); `dovecot-sql.conf.ext:8-29` uses only parameter-escaped `%`-expansions with `is_active = TRUE` on
both queries; the postfix DB role is granted only `domains/mailboxes/aliases`, never `users`
(`init-db.sh:143-153`); `directory-sync.py:40-49,131-140` sanitises names and writes by atomic rename;
`knot.conf` sets no recursion and blanks `version`/`identity`, with `mod-rrl` rate limiting; certificate
delivery is file-watch reloads rather than a docker socket; `db-upgrade.sql` is idempotent
(`ADD COLUMN IF NOT EXISTS`) and `init-db.sh:107-116` guards its constraint with a `DO $$` block; and
`requirements/prod.lock` is installed with `--require-hashes` (`Dockerfile:13-14`).

### 9.9 `core/platform` + `core/website` + `core/tests` — 76 files (36 + 16 + 24), delegate read
all; every line cited below was re-read by this author

**F114 — Med — a test assertion switched off by a ternary, so the log report's rspamd row is
uncovered.** `core/tests/test_log_report.py:275` reads
`self.assertContains(page, 'Spam filter decisions') if False else None`. Python evaluates the
condition *first*, so the `assertContains` call expression is never invoked — the line is inert, not
a weakened assertion. The rest of the same test (`:271-280`) does assert `'Log sources'`, so the page
is covered except for exactly the one source whose data comes from rspamd. *Pointer:* delete the
`if False else None` and keep the assertion, or delete the line so the gap is visible in coverage.

**F115 — Med — two assertions disappear when the tool they need is absent, and CI never installs the
tool.** `core/tests/test_server_edge.py:319-330` skips `test_the_generated_rules_are_accepted_by_nft`
when `shutil.which('nft')` is empty (and again, at `:328-329`, if `nft -c -f` answers
"Operation not permitted"), which is the only thing that validates the generated rule grammar against
a real parser; `.github/workflows/ci.yml:95` installs `shellcheck` and nothing else, so the check is
skipped on every push and the rule grammar is only ever validated by the test's own string
assertions. `core/tests/test_provisioning_contract.py:657-658` is the same shape in a weaker form:
`shell = shutil.which('sh')` followed by `if shell:` — with no `else`, no skip and no fail, so on a
runner without `sh` the test passes while asserting nothing. **CONFIRMED** for both (read in full).
*Pointer:* add `nftables` to the CI package list, and make the `sh` branch an explicit
`self.skipTest` so the skip is reported rather than silent.

**F116 — Med — the unmanaged-schema contract test compares column *names* only, so type and
nullability drift is invisible.** `core/tests/test_schema_contract.py:38-41` builds
`known = block.group(1) + ' ' + alters` from the `CREATE TABLE IF NOT EXISTS` body and the
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` lines of `init-db.sh`, then loops the model's concrete fields
and appends `f'{table}.{field.column}'` when `re.search(rf'\b{field.column}\b', known)` fails. It
answers "is the word present in the SQL", never "is the column declared as the model says": an
`INET` written as `varchar`, a `NOT NULL` dropped, a missing default, or a `max_length` change all pass
this test while breaking at runtime or truncating silently. It is the guard that F105 depends on —
`init-db.sh:13` runs without a transaction and `provision.sh:474-477` swallows its failure with
`|| echo`, so a half-applied schema is exactly the failure mode this test cannot see. (The column names
themselves do match today: `ip_address INET` is present in both `init-db.sh:56` and
`db-upgrade.sql:6`, checked in §9.2.) *Pointer:* compare parsed column definitions against
`connection.schema_editor()` output, or at minimum assert the SQL type per field.

**F117 — Low — the Celery registration test's docstring promises a check the body does not
contain.** `core/tests/test_celery_registration.py:1-7` says it "checks the schedule and every
`.delay` target" against what the worker imports; the class at `:22-32` has two tests — one over
`CELERY_BEAT_SCHEDULE` and one hardcoded name (`accounts.publish_directory`). No `.delay` site is
scanned, which matters because `backend/config/celery.py:13-26` omits `backend.apps.core.platform` and
`backend.apps.core.website` from the autodiscover list (F83), so a task added in either app would be
callable from the api process and unregistered in the worker. This author ran the check the test does
not: the non-test `.delay`/`.apply_async` call sites are `accounts/services/directory.py`,
`accounts/views/server.py`, `core/assistant/services/conversations.py` and
`mail/services/webhooks.py` — all four in autodiscovered apps — so there is no live failure, only an
unguarded invariant. *Pointer:* iterate the `.delay` targets, or drop the claim from the docstring.

**F118 — Med — an audit write that fails is logged at `INFO` with a `[mem]` flag and the console keeps
answering from a per-process 200-event ring.** `core/platform/services/audit.py:87` persists first,
then `:94-96` always appends to `cls._events` and trims it to `_max_memory_events = 200` (`:60`), and
`:98-101` logs `AUDIT [db] …` or `AUDIT [mem] …` at `logger.info` — the same level, in the same format,
for "recorded in the trail" and "lost, kept only in RAM". The read side then silently prefers memory:
`:148-149` is `except Exception: return bool(cls._memory_search(action, **filters))`, and `:160` does
the same for counts. Consequences: a database outage turns the audit trail into a per-worker ring
buffer (each gunicorn and celery process has its own `cls._events`), the console shows events that were
never written, and `verify_chain` cannot detect the gap because no row exists to break the hash link.
**CONFIRMED** (both paths read). *Pointer:* log `[mem]` at `ERROR` with the exception, and make
`exists`/`count` fail or return an explicit "unverified" rather than falling back.

**F119 — Low — `AuditEvent` is not a `CoreModel`.** `core/platform/models/audit_event.py:13` declares
`class AuditEvent(models.Model)`; AGENTS.md makes the `core/base/models/base.py` mixin set mandatory,
so the table carries no created/updated stamps, no uuid primary and none of the visibility behaviour
the rest of the repository relies on. It is also the one Django-managed table in an app whose other
tables are unmanaged (`:16` notes "Managed by Django (not read from init-db.sh)"), which is why the
schema contract test skips it (`model._meta.managed` at `test_schema_contract.py:28-29`). Judged
deliberate rather than accidental, but it is a documented-rule break that no test catches.

**F120 — Med — `core/platform` reads a domain app's model directly.**
`core/platform/services/certificates.py:39-41` does
`from backend.apps.domains.models import Domain` and then
`Domain.objects.order_by('name').values_list('name', flat=True)` inside
`CertificateService.sync()` — which runs on the beat schedule (`base.py:238-241`,
`domains.sync_certificate_hosts`) and writes the certificate host runtime file. AGENTS.md is explicit
that model access goes through the owning app's `services/` layer and that `core` must not depend on
domain apps; the neighbouring code shows the compliant shape —
`monitoring.py:105` imports `domains.services.verification.DomainVerificationService` and
`entrypoints.py:695` imports `dns.services.server.DNSServerConfig`, both through services.
**CONFIRMED** by a repository-wide grep of `from backend.apps.(domains|mail|dns|accounts)` under
`core/platform/`: three hits, and this is the only one that imports a model. *Pointer:* expose
`domains.services.domain_names()` and call that.

**F121 — Med — when the public-IP lookup fails, health checks silently interrogate the container's
private address and report "not listed".**
`core/platform/services/deliverability.py:380-394` tries `IP_CHECK_URL` (default ifconfig.me) inside
`except Exception: pass` at `:389-390`, falls back to
`socket.gethostbyname(socket.gethostname())` at `:392` — which in this compose topology returns the
bridge address, typically `172.x` — and returns `'0.0.0.0'` at `:394` if even that fails. The value is
consumed by `run_all_checks` (`:59`), `_check_blacklists` (`:165-198`) and `_check_reverse_dns`
(`:225`). A reverse-mapped private address yields NXDOMAIN on every RBL, and `_resolve` correctly
returns `[]` for NXDOMAIN (`:47-48`), which `:190` records as `{'listed': False, 'detail': 'Not
listed'}` — so the console reports a clean blocklist bill of health for an address that is not the
server's. The wrong value equally poisons the PTR check (`:240-256`, "No PTR record found for server
IP"). **CONFIRMED.** *Pointer:* treat a private/loopback result as "unknown" and show the operator
that the public IP could not be determined, rather than running the checks against it.

**F122 — Low — `_check_port25` leaks its socket on a read error and is called across the app boundary
through its private name.** `deliverability.py:270-309` builds `socket.create_connection((host, port),
timeout=10)` at `:275`, calls `sock.recv(1024)` at `:276` and only closes at `:277` inside the same
`try`, so any exception between connect and close leaves the descriptor open; there is no `with` and no
`finally`. `host` is the caller's `mail_hostname` and `port` comes from `SMTP_PORT_CHECK` (`:273`), so
the target is not constrained to this server, and the pass test at `:303` is a substring match on
`'220' in banner` — a banner containing "220" anywhere counts as healthy. The service is also consumed
from another app by its private methods: `accounts/services/system_health.py:117` calls
`DeliverabilityService._check_port25`, `:198` calls `._check_blacklists`, and `:221` imports the
module-level `_resolve`. **CONFIRMED.** *Pointer:* `with closing(sock)`, compare the banner prefix, and
give the platform app public accessors instead of underscore calls across apps.

**F123 — Low — the disk health check promises a list and inspects one path.**
`core/platform/services/monitoring.py:146-163` reads `DISK_CHECK_PATHS` (plural, default
`<mail vhosts>,<app>,/`) at `:150`, loops it at `:151`, and at `:161` `break`s out of the loop on the
first path that exists — so `health['checks']['disk']` describes one volume (normally the first
existing one) while the console's label is unqualified "Disk". A full backup or database volume is
never reported. If none of the paths exists, no `disk` key is set at all, and the roll-up at `:166-170`
averages over the checks that happen to be present, so the absent dimension silently disappears from
the overall status. **CONFIRMED.** *Pointer:* check every existing path and report the worst, or rename
the setting and the label to a single path.

**F124 — Low — `UPDATE_REPO` is interpolated into an outbound API URL and two console links with no
shape check.** `core/platform/services/updates.py:63` reads
`os.environ.get('UPDATE_REPO', 'ifinsta/ifinmail').strip()`, `:108` builds
`f'https://api.github.com/repos/{UpdateService.repo()}/tags'` from it, and `:49-57` builds
`release_url` and `changes_url` from the same value plus tag names taken from the remote response
(`:57` is `.../compare/{base}...{self.latest}`). Nothing restricts the value to `owner/name`, so
slashes or `..` re-shape the API path, and the links the dashboard renders are assembled from a
mixture of operator input and remote data. Not a live vulnerability (the value is environment-level,
and the request goes to a fixed host over TLS), but it is the same "syntax-only validation of a
reachable URL" shape as F62. **CONFIRMED.** *Pointer:* validate the slug against
`^[\w.-]+/[\w.-]+$` at read time.

**F125 — Low — the website markdown renderer can be made to raise on its own placeholder format.**
`core/website/services/markup.py:38-59` stashes code spans as `f'\x00{index}\x00'` (`:43-44`) and then
restores them with `re.sub(r'\x00(\d+)\x00', lambda m: codes[int(m.group(1))], out)` (`:59`). A body
that already contains a NUL-delimited number is escaped, not stripped (`escape()` leaves `\x00`
alone), so `\x007\x00` with fewer than eight stashed spans raises `IndexError` and the page renders a
500. `content.clean` normally blocks control characters via `_CONTROL`
(`core/website/services/content.py:25,65-66`) — but that runs on the *editor* path, and
`content.get` (`:87-102`) reconstructs a `PageContent` straight from the stored setting or cache
without re-running `clean`, so a value written by another producer reaches `render()` unchecked. The
prerequisite is content-author privilege, hence Low. *Pointer:* use a placeholder that cannot collide
(e.g. a `\x00` prefix plus a random token) or refuse NUL in `render()`.

**F126 — Low — a `next()` with no default in the footer builder: the second instance of F52's
pattern.** `core/website/services/site.py:100` resolves a page spec with
`spec = next(p for p in PAGES if p.key == key)` inside the `page()` helper used by `footer_columns`
(`:112-143`). Every key used today exists in `types.PAGES` (`types/__init__.py:41-53` lists
`landing, features, pricing, security, docs, changelog, download, about, contact, terms, privacy`), so
this is latent: renaming or dropping a page key turns a footer into an uncaught `StopIteration` → 500
on eleven public pages, exactly the failure mode already recorded at F52 for
`dns/viewsets/configure.py:70`. **CONFIRMED** as latent. *Pointer:* iterate `PAGES` by group and let
the data structure drive the footer, or use `BY_KEY` (`types/__init__.py:54`).

**Checked in this zone and refuted:** the website capability's page/mode grammar **is** validated —
`website_handlers.py:25-36` (`_modes`) rejects a page key outside `KEYS`, a mode outside `MODES`, and a
page listed twice, `_normalize_modes` (`:39-45`) canonicalises before storage, and the same validators
are bound at both layers (`:65` target key, `:91` capability field), so a manifest cannot smuggle a
mode string in. `policy.py:75-79` re-checks the parsed JSON against `KEYS`/`MODES` a second time.
Disabling the plugin does reset the public site: `lifecycle.py:259-278` (`publish_all`) calls
`target.publish(target.render(values.get(target.key, {})))` for **every** registered target whether or
not any installation supplies it, so `WebsiteTarget.publish` (`website_handlers.py:72-83`) stores a
`STANDARD` policy — the "stale cached page modes after uninstall" concern this author raised was
looked for and is not reachable. The web shell is not a live surface at all:
`accounts/views/dashboard.py:437-452` keeps the route and its decorators (`@login_required`,
`@require_perm(PermissionCode.SYSTEM_MANAGE)`, `@require_POST`) but the body only records a
`shell_disabled` audit event and returns 403 with "The web shell is disabled in production." — the
earlier "outside development only" reading was wrong and the code is stricter than that.
`platform/services/runtime.py:18-46` is **not** traversal-weak as a delegate claimed:
`write_runtime_file` splits the name on `/` and raises on any empty segment or any segment beginning
with `.` (`:20-22`), which excludes both `..` and absolute paths, joins the remainder under the single
`runtime_dir()` (`:14-15`) and publishes by `mkstemp` + `os.replace` with the temp file unlinked on any
failure (`:26-34`); `read_runtime_file` applies the same test at `:39-41`. `EntryPointService.is_enabled` (`entrypoints.py:235`) does index
`BY_KEY[key]` without a guard, but the only callers pass catalogue keys (verified by grep: definition
plus `test_server_edge.py:231,236,390-394`), so the missing `KeyError` handling is not currently
reachable.

**What platform/website/tests got right (verified):** `markup.safe_link` (`markup.py:25-35`) is the
correct version of the assistant's link rule — it rejects `//host` **and** `/\host` explicitly before
accepting a root-relative path, caps length at 300, refuses characters below `\x20`, allow-lists four
schemes, and `:52-54` adds `rel="noopener noreferrer"` for absolute `http(s)` links — which is exactly
the hole F63 leaves open in `assistant/services/safe_markdown.py:113,128`. `content.clean`
(`content.py:56-79`) collects one error per field, enforces the `types.LIMITS` bounds, rejects control
characters, requires a CTA button to have both its text and its address (`:73-76`), and runs `cta_url`
through `safe_link` — and `content.save` (`:105-118`) mutates the setting through
`SystemSettings.mutate` (read-modify-write under the settings lock) rather than get-then-set, audits
the write (`:117`), and drops the page's cache entry. `_resolve` (`deliverability.py:36-51`)
distinguishes "no answer" (`[]`) from "lookup failed" (`None`) and `_check_blacklists` (`:184-198`)
records a `127.255.255.x` refusal as *check failed*, never as *not listed* (`:191-194`), with the
docstring at `:39` recording the earlier bug that this fixed — the honest-partial discipline the rest
of the repository should copy. `monitoring.check_dns` (`monitoring.py:99-107`) delegates to
`DomainVerificationService.check` rather than re-implementing verification, i.e. it uses the
proof-bound path established in §9.2. The nft renderer's own test suite
(`test_server_edge.py:332-335`) asserts catalogue port uniqueness and that `https`/`http`/`smtp` are
`locked` — the console genuinely cannot close itself out — and `EntryPointService.reconcile`
(`entrypoints.py:627-640`) writes only on drift, is scheduled (`base.py:262-266`,
`core.reconcile_entrypoints`, defined in the autodiscovered `core` app), and is covered by
`test_firewall_reconcile.py:38-61`, which asserts both the drift correction and the no-rewrite case.

**COVERAGE STATEMENT.** 76 files in zone: `core/platform` 36, `core/website` 16, `core/tests` 24. The
zone delegate read all 76 in full; this author then **re-read in full** every file or region cited
above — `audit.py:62-101,134-163`, `certificates.py:30-44`, `deliverability.py:31-51,165-224,270-309,
380-394`, `monitoring.py:99-174`, `updates.py:39-63,103-134`, `entrypoints.py:225-244,615-650`,
`runtime.py` (retraction check), `markup.py`, `site.py`, `content.py`, `policy.py`, `types/__init__.py`,
`website_handlers.py`, `registry.py:86-122`, `lifecycle.py:259-278`, and the six cited test files — plus
mechanical greps for cross-app imports under `core/platform`, for `.delay`/`.apply_async` call sites
across `backend/apps`, for `CACHE_KEY`/`policy.store` users, for `is_enabled` callers and for the beat
schedule task names. **Not re-inspected by this author** (delegate read only, no finding retained from
them beyond the lines above): `core/platform` `views/`, `viewsets/`, `forms/`, `serializers/`, `api.py`,
`urls.py`, `apps.py`, `signals.py`, `tasks.py`, `mixins/`, `indexes/`, `types/`, `verifications.py`,
`preferences.py`, the remaining service modules (`backup`, `discovery`, `shell`, `server_edge`,
`backup_targets`, `settings_pages` as applicable), `core/website/tests/*` bodies, and 17 of the 24
`core/tests` files. Those files were read once by the delegate and produced nothing this author could
confirm; treat any re-review of this zone as starting there. No file was sampled by line range.

### 9.10 `frontend/templates` — 114 `.html` templates, all read in full across four chunks (the 3 `.txt` in the same directory are §9.16)

Zone: `frontend/templates/**.html` + `.txt` — 114 files (admin 64, site 16, includes 12, root 9,
setup 8, registration 7, mail 1). Four delegate chunks (root+site+registration+setup+mail, admin
1–32, admin 33–64, includes+mail templates), each reporting complete coverage of its own list. The
view and form sides of every finding below were re-read by this author; the template lines were too.

**F127 — High — the secondary-nameserver textarea renders its own separator as literal text, so the
form rejects what the page displays.**
`frontend/templates/admin/settings_dns_server.html:71` fills the textarea with
`{{ secondaries|join:"&#10;" }}`. In a Django template tag argument `"&#10;"` is the six-character
string `&`, `#`, `1`, `0`, `;` — not a newline — and autoescaping turns the `&` into `&amp;`, so an
operator with two secondaries configured sees `198.51.100.7&#10;198.51.100.8` on one line
(`services/server.py:87 secondaries()` → `views/server.py:81 'secondaries'`). Submitting that
unchanged gives `SecondariesForm.address_list` (`backend/apps/dns/forms/zones.py:36-38`) one token,
`198.51.100.7&#10;198.51.100.8`, which the IP validator rejects; `dns_secondaries`
(`backend/apps/dns/views/server.py:194-197`) flashes `_first_error(form)` and redirects, so every
Save fails until the operator notices the `&#10;` and deletes it by hand. The stored list is fine —
`services/zones.py:244-262` writes the Knot secondary blocks and the transfer ACL from
`DNSServerConfig.secondaries()`, so zones still publish correctly; only the editing screen is broken,
which is what makes it durable. No test catches it: `tests/test_authoritative.py:403-406` POSTs a real
newline and asserts the saved list, never rendering the template, so the round-trip
(view → textarea → POST → view) is untested in either direction.
*Pointer:* `{{ secondaries|join:"\n" }}` is not expressible either; render
`{% for ip in secondaries %}{{ ip }}{% if not forloop.last %}&#10;{% endif %}{% endfor %}` inside an
`{% autoescape off %}`-free textarea using the `linebreaks`-free idiom `{{ secondaries|join:separator }}`
with `separator = "\n"` supplied by the view, and add a test that GETs `dns:server` with two
secondaries and asserts the textarea contains a real newline.

**F128 — Med — seven error templates fill blocks no ancestor declares, so the browser tab of every
error page is blank and the 500 guidance line never renders.**
`frontend/templates/error_base.html:4` builds the document title from the *context variables*
`{{ error_code }} {{ error_title }}`, and `:17-18` prints `{{ error_detail }}` only if that context
variable is set. The children write blocks instead: `404.html:3-5`, `400.html`, `403.html`,
`502.html`, `503.html`, `504.html` each fill `{% block error_title %}` and `500.html:6`,
`502.html:6`, `503.html:6`, `504.html:6` fill `{% block error_detail %}` — but `error_base.html`
declares `error_code`, `error_description` and `error_actions` (`:15`, `:16`, `:21`) and never declares
`error_title` or `error_detail`. Django silently drops blocks that no ancestor defines, and those two
names only reach the context from the JSON handler
(`backend/config/urls.py:265-268`, which supplies `error_code`/`error_title`/`error_detail` for the API
error page). Net effect on the HTML error pages: the `<h1>` code and the description line are correct
(`{% block error_code %}404{% endblock %}` overrides `:15`, `error_description` overrides `:16`), while
the tab title renders ` — ifinmail` with nothing before the dash, and the
"If this issue persists, please contact support." line from `500.html:6` is dropped — including for
502/503/504 where it is the only operator-facing guidance.
*Pointer:* declare `{% block error_title %}{{ error_title }}{% endblock %}` and
`{% block error_detail %}{% endblock %}` in `error_base.html`, then read them with
`{{ block.super }}` fallback rather than context variables.

**F129 — Med — brand font names are interpolated into a `|safe` `<style>` block while brand colours
are sanitised, and the production CSP is loosened to accommodate that block.**
`frontend/templates/base.html:25` emits
`{% if brand.css_overrides %}{{ brand.css_overrides|safe }}{% endif %}` inside a `<style>` element.
`backend/config/branding.py:195-199` builds
`@import url('https://fonts.googleapis.com/css2?family={font_url}:wght@…')` from
`font.replace(' ', '+')` only, and `:256-259` writes `font-family: "{self.heading_font}"` — both land
in CSS text that is explicitly not escaped. Colours by contrast are sanitised at both ends:
`branding.py:202` and `:220` run `_sanitize_hex_color`, and the writer
`backend/apps/accounts/views/branding.py:137-142` accepts a value only if `len(h) in (3, 6)` and every
character is a hex digit. The two font fields have no such check — `:146-150` stores
`overrides[field] = val` verbatim after `.strip()`. The authoring privilege is real (`:128-130`
`@login_required` + `@require_perm(PermissionCode.SYSTEM_MANAGE)` + `@require_POST`), so this is a
self-XSS-by-privilege and a stored-CSS-break path rather than a drive-by; the structural cost is that
`backend/config/settings/production.py:77` carries
`style-src … 'unsafe-inline'` with the comment "Required for brand overrides
(BrandingConfig.css_overrides)" — a CSP weakening for every page in order to support two text
inputs. `frontend/templates/admin/settings_dns_server.html`-style inline `<style>` is also why
`ifinmail-variables.css` tokens exist at all.
*Pointer:* validate fonts against an allow-list of the ~20 families the console offers (the same list
`settings_branding.html` renders), move the override block to a served stylesheet under
`{% static %}` or a `Media` asset, then drop `'unsafe-inline'` from `style-src`.

**F130 — Med — `base.html` renders no flash messages, so a view that flashes and lands outside the
settings hub is silent.**
The `messages` framework has exactly two homes in this zone:
`frontend/templates/admin/settings_base.html:18-20` (inherited by every `settings_*.html`, and by
`settings_config.html:1` → `settings_about.html:1`) and six explicit
`{% include "includes/flash_messages.html" %}` calls — `admin/assistant.html:19` and `:81`,
`marketplace.html:22`, `marketplace_plugin.html:25`, `marketplace_submission.html:20`,
`marketplace_submit.html:20`, `sending_paused.html:20`. `base.html` itself contains no `messages`
reference and no JS toast path (verified: `grep -n "get_messages\|for message in"` across
`frontend/templates` returns only those lines). The other templates that extend `base.html` —
`dashboard.html`, `system_health.html`, `mfa_setup.html`, `mfa_verify.html`, `login.html`,
`recovery_login.html`, `first_password.html`, `mailbox_setup.html`, the `password_reset_*` set —
therefore drop any flash aimed at them, and today one call site does exactly that:
`backend/apps/accounts/views/mfa.py:143-144` flashes `Enroll an authenticator first.` then
`redirect('accounts:mfa_setup')`, whose template extends `base.html:1` — the operator clicks
"regenerate codes", the request is refused, and the page reloads looking unchanged. With ~190
`messages.success/error/warning/info` call sites across 25 view modules, the invariant "the target
page renders messages" is held by coincidence rather than by structure, and every new
`base.html` page inherits the silence.
*Pointer:* move the `{% for message in messages %}` block into `base.html` (where the settings hub
already gets it from a duplicate), delete the seven duplicate includes, and add a template test that
flashes then GETs each `base.html` page.

**F131 — Med — the header search box says "Search settings…" and searches the audit log.**
`frontend/templates/includes/header.html:10-13` renders `<form class="ifinmail-global-search"
role="search" action="{% url 'accounts:logs' %}" method="get">` with
`placeholder="{{ header_search_placeholder|default:_('Search settings...') }}"`. The default is only
overridden by a view that sets `header_search_placeholder`; the settings hub does not, so an operator
typing "branding" or "webhook" into the box is sent to System Logs with `?q=`, which filters audit
events by text and will normally answer "no events" rather than opening the setting they were looking
for. Two of the three consequences are design-system rules: a control that promises one destination
and performs another, and a search affordance in the chrome that is not a search.
*Pointer:* either point the form at the settings hub with `?q=` support in
`backend/apps/accounts/views/settings_hub.py`, or change the default placeholder to
"Search activity…" and label the results page accordingly.

**F132 — Med — the notification bell is a dead control fed by a hard-coded zero.**
`frontend/templates/includes/header.html:23-28` renders
`<button class="ifinmail-icon-button" type="button" aria-label="Notifications" title="No new
notifications">` — `type="button"`, no `data-action`, no `href`, and no handler for it in any
`frontend/static/js` file — with `{% if notification_count %}<span class="ifinmail-notification-dot">`
around an empty span. `notification_count` is supplied by the context processor as the literal
`0` (`backend/config/server_context.py:65 'notification_count': 0`), on every request, for every
user. So the bell can never light, never open, and never show a count, while its `title` asserts a
state ("No new notifications") the server did not compute. This is the "No Fake Admin Controls" rule
in AGENTS.md-adjacent memory: a control that looks wired and is not is worse than an absent one, and
here it is a real focus trap for keyboard users (an actionable-looking tab stop that does nothing).
*Pointer:* delete the button and `notification_count`, or back it with a query
(bounces, expiring keys, plugin submissions awaiting review all already exist) and make it an `<a>`.

**F133 — Med — the one-time API-key and webhook-secret Copy buttons are inert because the script that
handles them is not loaded on those pages.**
Both `frontend/templates/admin/settings_api_keys.html:28` and
`settings_webhooks.html:32` render `<button … data-action="copy-invite"
data-value="{{ revealed.secret|escapejs }}">`. The only listener for `copy-invite` is
`frontend/static/js/ifinmail-mailboxes.js:266-294` (`initCopyButtons`, a delegated
`document` click handler over `[data-action="copy-invite"]`), and that script is loaded by exactly
three templates — `settings_mailboxes.html:180`, `mailbox_profile.html:318`,
`settings_aliases.html:72`. The API-keys and webhooks pages never include it, so clicking Copy on a
secret that the surrounding text says is shown once (`api_keys.py:102` "Copy the secret below; it is
shown once", `webhooks.py:85`) does nothing at all: no clipboard write, no "Copied!" swap, no error.
The secret stays visible in the `.ifinmail-codebox`, so recovery is manual selection — but the UI
promises a button and the button is dead, on the two highest-stakes copy targets in the console.
*Pointer:* move `initCopyButtons` into a script loaded by `base.html` (it is 30 lines and
selector-driven), or add the missing `<script>` tag to those two templates and assert the include in a
template test.

**F134 — Med — the live session key is written into the DOM of the mailbox profile page even though
the server already knows it.**
`frontend/templates/admin/mailbox_profile.html:57` renders
`<input type="hidden" name="session_key" value="{{ s.session_key }}">` for each session row, and
`backend/apps/accounts/views/profile.py:143-144` reads it back with
`key = form.cleaned_data['session_key']`. The rows themselves come from
`django.contrib.auth.models.User.objects`-adjacent session listing called at `profile.py:59` as
`list_for_user(..., current_key=request.session.session_key)` — so the server holds the current key
already and excludes it from the list, yet every *other* session's key is placed in the page HTML.
A session key is the whole authentication secret (the cookie is just a pointer to it), so this puts
other devices' credentials into browser history, into any DOM snapshot, and into reach of a single
same-origin XSS — and XSS on that page then revokes or hijacks every session rather than only the
attacker's own. The revoke path itself needs no such value: `profile.py` could accept an opaque index
or the `session_key`'s hash and resolve it server-side.
*Pointer:* render `value="{{ s.row_id }}"` (or the key's SHA-256 prefix), map it back to the key in
the view, and keep the "this device / another device" labels the template already computes.

**F135 — Med — the logs page's summary counts ignore the filters that are on the page.**
`backend/apps/accounts/views/logs.py:166` computes `counts = AuditService.level_counts(since)` — a
function of the time window only — and `:200` puts
`'count_total': sum(counts.values())` into the context next to the filtered row set. The template
`admin/logs.html` shows both together, so an operator who has typed `?q=webhook` or picked
`level=error` reads "1,204 events" above a table of 9 rows and has no way to tell which number the
table follows. `level_counts` never receives `q` or the other filter arguments, so the strip is
period-scoped while the table is filter-scoped.
*Pointer:* either pass the filters into the count query or label the strip "last 7 days, all events"
and add a separate "9 matching" figure.

**F136 — Low — the user-management page ships four governance widgets whose values are literals in the
view.**
`backend/apps/accounts/views/users.py` builds them by hand: `:99 'mfa_adoption_pct': '0%'`,
`:105 'rbac_status': str(_('Basic'))`, `:122 'governance_items': []`, `:123 'anomaly_bars': []`, and
`:125-128` an `audit_stats` dict containing `'Not configured'` and
`'manual_overrides': '0 Pending Review'`. The template renders these as measured facts. Some are
honest-but-empty (`[]` presumably draws an empty state) and some are outright claims about the
deployment: no user is enrolled in MFA according to `'0%'` whether or not any is, and RBAC is reported
as `Basic` regardless of what `PermissionCode` grants exist. This is the same class as F132 and it
belongs to the "real-time data honesty" rule for admin views.
*Pointer:* compute adoption from `UserProfile`/`TOTP` enrolment (both queryable in one annotate), and
delete any widget that cannot be computed this sprint.

**F137 — Low — the API-key page hardcodes both a scheme and the API mount in prose, and the URL
contract test cannot see it.**
`frontend/templates/admin/settings_api_keys.html:31` renders
`<code>curl -u {{ revealed.key }}:&lt;secret&gt; https://{{ request.get_host }}/api/v1/status</code>`.
AGENTS.md says a link that leaves the page uses `backend.config.site_url` and templates use
`{{ site_origin }}`; this instead asserts `https://` (wrong on an http-only install, and the console
does serve http in development) and the literal path `/api/v1/status`. The contract test does not
catch it because `backend/apps/core/tests/test_url_contract.py:47-49` only matches
`href|action|src|data-*url|formaction` attribute values beginning with `/` — a hardcoded path written
as element *text* is outside the pattern entirely, and `:54` additionally skips any value containing
`{%` or `{{`. Related blind spot: `:75` exempts `ifinmail-api.js` from the script rule with a comment
admitting it is "a client for the legacy /v1 base and is not loaded", i.e. the test is satisfied by
waiving the dead file rather than deleting it.
*Pointer:* emit `{{ site_origin }}{% url 'api-status' %}`-style text (or reverse() it in the view) and
widen the test pattern to `>([^<]*?/(?:api|accounts|dns|mail)/…)<` for `<code>`/`<pre>` blocks.

**F138 — Low — the threats page emits high-contrast status classes that exist in no stylesheet.**
`frontend/templates/admin/threats.html:116` composes
`ifinmail-hc--{% … %}` producing `ifinmail-hc--error`, `--warning` and `--ok`. A grep for
`ifinmail-hc--` across every `.css` file in the repo returns two rules only, both in
`frontend/static/css/ifinmail-redesign.css:3248-3249`, for `--compact` and `__summary`. So in the
high-contrast theme the finding-severity markers render with the default token colours — the one
theme where the extra weight matters, and the case the design system's "verify in light, dark and
contrast" rule exists to catch.
*Pointer:* add the three classes to the `html[data-scheme="contrast"]` block in
`ifinmail-variables.css` (or reuse the existing `ifinmail-badge--*` classes the same template already
uses elsewhere) and extend the design-audit script to fail any `ifinmail-` class emitted by a template
that appears in no stylesheet.

**Refuted or declined in this zone.**

* `admin/settings_about.html:19` looked like a hardcoded `docs_url` — it is not.
  `backend/config/server_context.py:47` computes
  `os.environ.get('DOCS_URL', '').strip() or (reverse('docs') if pages.docs else '')` and exports it at
  `:61`, and `test_url_contract.py:227` asserts the `reverse('docs')` branch. Only cosmetic residue:
  the visible label is `{{ site_origin }}{{ docs_url }}`, which doubles up if an operator sets
  `DOCS_URL` to an absolute URL. Not retained.
* `error_base.html:23` `<button … data-action="history-back">` and `500.html:9`
  `data-action="reload"` are both live — `frontend/static/js/ifinmail-actions.js:10` implements
  `history-back` and the same file dispatches `reload`. Declined.
* The `escapejs` on `data-value="{{ revealed.secret|escapejs }}"` is the correct filter for a value
  destined for a JS-read attribute, and `includes/flash_messages.html:4` sets `role="alert"` for
  errors and `role="status"` otherwise — both better than the surrounding code usually manages. No
  finding.
* `{% trans %}` coverage in the four chunks was near-total; the delegate flagged no untranslated
  literal. Not counted as a finding.

**What the templates got right.**

* Every POST form in the zone carries `{% csrf_token %}` (spot-confirmed across all four chunk lists,
  including the destructive rows in `settings_api_keys.html:107`, `settings_webhooks.html:53` and
  `mailbox_profile.html`).
* Destructive submits declare their own confirmation in prose the server also enforces —
  `settings_api_keys.html:124` `data-confirm="Revoke this key? Integrations using it stop working
  immediately."`, `settings_webhooks.html:57` "Remove this webhook? Events stop at once." — and the
  handler exists in `ifinmail-actions.js`.
* Wide data tables are wrapped as `role="region"` scroll boxes with an accessible name
  (`settings_api_keys.html:90`, `settings_webhooks.html:37`) and every `{% empty %}` branch names the
  next action rather than saying "nothing here"
  (`settings_dns_server.html:58` "No domains yet. Add a domain",
  `settings_api_keys.html:131` "No keys yet. Create one above for the first integration.") —
  rule 6 of the design system, applied.
* One-time secrets are handled as a visible-once panel with a "copy it now" lede and a rotate
  instruction (`settings_api_keys.html:19-33`, `settings_webhooks.html:26-35`), and the plaintext is
  never re-derivable afterwards; `marketplace.html`-family pages include the flash partial twice
  because they render both a top banner and an in-panel result.
* `includes/header.html:3` gives the hamburger `aria-label` and `:12` gives the search input an
  `sr-only` label rather than a placeholder-only field; `:55-66` uses real `<a>` elements for the
  account menu.

**COVERAGE STATEMENT.** 114 `.html` files in `frontend/templates`; **all 114 read in full** by the four
delegate chunks, each of which reported its own list exhaustively (admin 64 split 1–32 / 33–64, root+site+
registration+setup+mail 50, includes 12 minus the ones carried in other chunks — the four lists union
to the 114 HTML files counted here). The directory itself holds **117** tracked files: `git ls-files
frontend/templates | sed 's/.*\.//' | sort | uniq -c` reports 114 `.html` and 3 `.txt`, and those three
plain-text email templates were not in any chunk's list — they are swept in §9.16, which exists because of
this sentence. This author re-read the view, form, service, context-
processor, CSP, template-test and stylesheet sides of every finding above
(`settings_dns_server.html`, `error_base.html`, `404.html`, `500.html`, `base.html`, `header.html`,
`flash_messages.html`, `settings_api_keys.html`, `settings_webhooks.html`, `mailbox_profile.html`,
`settings_config.html`, `threats.html`, plus `dns/views/server.py`, `dns/forms/zones.py`,
`dns/services/server.py`, `dns/services/zones.py`, `dns/tests/test_authoritative.py`,
`config/branding.py`, `config/server_context.py`, `config/urls.py`, `config/settings/production.py`,
`accounts/views/branding.py`, `accounts/views/logs.py`, `accounts/views/users.py`,
`accounts/views/profile.py`, `accounts/views/mfa.py`, `accounts/views/passkeys.py`,
`accounts/views/system_health.py`, `core/tests/test_url_contract.py`,
`static/js/ifinmail-actions.js`, `static/js/ifinmail-mailboxes.js`,
`static/css/ifinmail-redesign.css`). **Mechanical greps only:** `messages.*` call-site census across
`backend/apps`, `extends` inheritance across `admin/`, `data-action="copy-invite"`, `ifinmail-hc--`,
`error_title`/`error_detail`/`error_code`, `docs_url`, `history-back`. **Not inspected:** nothing in
the zone was left out, but the delegate chunks did not execute any template — every rendering claim
here (F127's `&amp;#10;`, F128's dropped blocks) rests on Django's documented filter and block
semantics, not on an observed response, and would be confirmed in one browser pass.

### 9.11 `clients/android` — 171 files, every Kotlin source read in full by three chunks

Zone: `git ls-files clients` = 173 (171 under `clients/android`: `app/` 92 → shared 42, androidApp 33,
iosApp 11, webApp 4, desktopApp 2; `mail` 37; `core` 15; `update` 7; `server` 4; `gradle` 4;
`scripts` 2; plus root build files). Three delegate chunks: **mail + core** (52 files, all read in
full), **platform apps** (50 files, 49 read in full + one PNG stat'd), **shared compose UI**
(42 files). This author re-read every file behind F139–F145 and the update path. No Gradle build, APK
install or network test was run in this zone — claims about behaviour are read from code, and the two
that would need a device are marked as such.

**F139 — High — the Bcc list is transmitted inside the message every recipient receives.**
`clients/android/mail/src/main/kotlin/com/ifinmail/mail/mime/MimeComposer.kt:20` appends
`appendAddressHeader(sb, "Bcc", draft.bcc)` to the header block, and the bytes it returns are exactly
what goes on the wire: `adapter/SmtpSubmissionAdapter.kt:51-52` builds the envelope from
`draft.to + draft.cc + draft.bcc` and calls `client.sendMail(email, recipients…, mimeBytes)` with the
same `mimeBytes`. RFC 5322 is explicit that a `Bcc:` field must not appear in the transmitted copy —
that is the whole mechanism. So anyone BCC'd is revealed to every other recipient, in the one flow
where they were promised otherwise (a reply-all list, a hidden co-recipient, a blind copy to a
personal address). The Compose screen offers the field (`app/shared/…/ComposeScreen.kt` collects
`bcc` into `OutgoingDraft`), so it is reachable from the UI, and there is no counter-control: the
server never sees this message, the client sends it directly to SMTP.
*Pointer:* keep `bcc` out of `compose()` and add it only to the copy appended to Sent (the same
`appendAddressHeader` call, against the Sent-folder bytes rather than the transmitted ones).

**F140 — High — passwords and OAuth tokens stay in the plaintext account store even after the secure
store has them, because the migration never clears the field.**
`Account` is `@Serializable` with `val credentials: Credentials? = null`
(`clients/android/core/src/commonMain/kotlin/com/ifinmail/core/domain/model/DomainModels.kt:12-19`),
aliased into `mail` as `model/Models.kt:12 typealias Account = com.ifinmail.core.domain.model.Account`,
and `store/MailStore.kt:16-21` puts `accounts: List<Account>` straight into
`MailStoreData` — which `writeUnsafe()` serialises as plain JSON to `ifinmail-store.json`
(`MailStore.kt:50-54`, `FILE_NAME` at `:57`). `engine/MailEngine.kt:81-84` runs the migration:
`account.credentials?.let { credentialStore.write(account.id, it) }` then
`account.copy(credentials = account.credentials ?: credentialStore.read(account.id))` — for an account
that already has credentials in the file, that expression evaluates to the *same* non-null value, so
`migrated != data.accounts` is false on that field and the plaintext copy is written back verbatim at
`:86`. The Keystore-backed store is therefore a second copy, not a replacement: the secret sits in a
World-readable-by-root/backup/adb-manifest-allowed file next to the mailbox contents.
*Pointer:* write `account.copy(credentials = null)` after `credentialStore.write(...)`, and read
credentials only through the store; then delete the file's `credentials` key for existing users.

**F141 — High — an unreadable store file is treated as an empty store and then written back, so one
truncated save wipes every account, message, draft and outbox entry.**
`store/MailStore.kt:40-48`: `readUnsafe()` returns `MailStoreData()` inside
`catch (e: Exception)` — a `SerializationException`, an `IOException` from a half-written file, or a
`Json` shape error are all indistinguishable from "no data yet". `write()` at `:34-38` is
`transform(readUnsafe())` followed by `writeUnsafe(updated)`, and `writeUnsafe` at `:53` calls
`fileSystem.sink(file)` — which truncates before writing. So the first mutation after a corrupt read
persists the empty state over the old file, and the app reports success. `store/MutationQueue.kt:60-62`
has the same shape for the outbox (`emptyList()` on failure, rewritten on the next flush), and
`store/FileCredentialStore.kt:42-55` repeats it for `ifinmail-credentials.json` — which is why losing
that file also loses every login. This is the highest-consequence defect in the client: it turns an
ordinary power-loss-during-write into permanent account loss with no prompt and no recovery path.
*Pointer:* distinguish "absent" from "unreadable" (return a failure the caller must handle), refuse to
`write()` over an unread state, and write via a temp file plus atomic `fileSystem.atomicMove`.

**F142 — High — authentication is sent without any check that the socket is encrypted, and the
STARTTLS reply is not read.**
Four separate gaps compose:
* `imap/ImapClient.kt:49-52` — `startTls()` is `execute("STARTTLS"); transport.startTls(host);
  capability()`. The `CommandResult` status is discarded, so a `NO`/`BAD` reply is followed by a TLS
  handshake on the same socket. (`smtp/SmtpClient.kt:29-31` does check; IMAP does not.) The failure is
  caught only by the handshake throwing — a defence that comes from the TLS library, not from this
  code.
* `imap/ImapClient.kt:77-89` — `login()` sends `AUTHENTICATE PLAIN <base64>` or
  `LOGIN "user" "pass"` with no precondition on transport state, and `adapter/ImapSession.kt:61-67`
  upgrades only `if (incoming.server.security == STARTTLS)` before calling
  `client.authenticate(...)`. With `ConnectionSecurity.NONE`
  (`core/src/commonMain/…/CoreModels.kt:30-34`) nothing is upgraded and nothing is refused.
* The same shape in `smtp/SmtpSubmissionAdapter.kt:49-50` and
  `pop3/Pop3AccessAdapter.kt:66-67`; `pop3/Pop3Client.kt:32-34` sends a bare `PASS`.
* `grep -rn LOGINDISABLED clients/android --include=*.kt` returns **0** matches, so a server that
  refuses authentication until TLS is negotiated is not detected as such — the client just gets a
  failed login and reports it as a bad password.
`MailTransport` exposes no `isSecure`, so no client call *could* check. Reachable from the UI:
`app/shared/…/AddAccountScreen.kt:263,291` maps `UiSecurity.NONE` through, and
`app/androidApp/src/main/AndroidManifest.xml:19` `usesCleartextTraffic="false"` does not cover raw
IMAP/SMTP/POP sockets — it governs `HttpURLConnection`/`WebView` only, so the manifest asserts a
protection the protocol clients ignore. The test suite locks the wrong behaviour in:
`mail/src/test/…/ProtocolClientsTest.kt:139-140` asserts AUTH PLAIN over a `NONE` transport as the
happy path.
*Pointer:* add `val isSecure: Boolean` to `MailTransport`, refuse `PASSWORD`/`XOAUTH2` unless it is
true or the session is `STARTTLS`-pending, treat a missing `LOGINDISABLED`-aware path as fatal, reject
`UiSecurity.NONE` in `fromUiSecurity`, and require `OK` in `ImapClient.startTls`.

**F143 — High — a POP3 message that fails to fetch or parse is marked as already seen, so it is never
retrieved again.**
`adapter/Pop3AccessAdapter.kt:76-104` wraps each `client.retr(number)` + `MimeParser.parseMessage(raw)`
in `runCatching { … }` whose result is discarded — the `Result` is never inspected, and nothing is
recorded when it is a failure. Then `:106-110` builds the new cursor from the **server's** full UIDL
map (`popUidMap = uidl.entries.associate { … }`) rather than from what was actually persisted, and
`:111` returns it as success. `MailEngine` stores that cursor and the next sync filters
`uidlValue !in knownUidls` at `:70`, so a message that tripped over a malformed body (see F154's
unbounded multipart recursion) disappears from the device permanently while the server still holds it.
`take(INITIAL_POP_BACKFILL)` at `:72` compounds it: everything past the window is *not* marked known,
but nothing tells the user the mailbox is only partly downloaded.
*Pointer:* advance the cursor per-UIDL only for messages appended to `parsedNew`, and surface a count
of skipped UIDs.

**F144 — High — a mutation that matches nothing is dropped as a success, and a queued send is
reported as sent.**
`engine/MailEngine.kt:180-204`: the whole `when (mutation.kind)` block is inside `runCatching`, and
`SEND` begins `val draft = mutation.draft ?: return@runCatching` at `:183`. `return@runCatching` yields
`Unit` from the lambda, so `result.isSuccess` at `:201` is true and
`mutationQueue.remove(mutation.id)` at `:202` deletes the pending send — no SMTP submission, no
failure event, no retry. `MARK_READ` (`:188-194`) and `DELETE` (`:195-198`) have the identical shape
when the message is not in `messagesFlow` — which is exactly the state after F141 wipes the store, so
the outbox quietly drains. Separately, on a transient failure `:415-436` enqueues a `PendingMutation`,
publishes `DomainEvent.SubmissionQueued` and **returns normally**, and the UI treats that as delivery:
`app/shared/…/ComposeScreen.kt:250-251` `onSuccess = { sending = false; onSent() }`. The operator is
told "Sent" for mail that has only been queued locally, and if the mutation is later dropped by the
first defect they never learn. `:206-209` then broadcasts
`MutationsFlushed(it.id, flushed)` to *every* account with one aggregate count, so a badge can show
work done on a different account.
*Pointer:* give the `when` an explicit outcome (`Continue`/`Rejected(reason)`) instead of
`return@runCatching`, only remove on real success, and make `onSent()` say "Queued — will send when
the connection works".

**F145 — Med — the update offer's URL is validated by scheme only, and the manifest's own signer
field is never used.**
`update/src/main/kotlin/com/ifinmail/update/UpdateManifest.kt:50-54`: when
`latest.downloadPath` starts with `/` the client builds the URL from the build-time `baseUrl`,
otherwise it takes `latest.downloadUrl` from the JSON verbatim. `validate()` at `:80-93` checks
package match, a `sha256` regex, size bounds, and then only
`release.downloadUrl.startsWith("https://")` — there is no host allowlist, and
`JavaUpdateHttp` sets `instanceFollowRedirects = true`
(`update/src/main/kotlin/com/ifinmail/update/UpdateHttp.kt:48`, the `URL(url).openConnection()` at
`:45-48`), so the redirect target is never re-checked. The `sha256` itself is self-referential: the
same manifest that says "download from anywhere over https" also says what checksum the file should
have, so it proves transport integrity and nothing about authorship. `signingCertSha256` is parsed
(`UpdateModels.kt:14`, `:79` `@SerialName("signing_cert_sha256")`) and copied into `ReleaseInfo`
(`UpdateManifest.kt:61`) and then read by nothing outside its own test
(`update/src/test/…/UpdateFlowTest.kt:116`) — a field that reads like a pinned-signer control but
enforces nothing on the device.
What actually protects the install is better than the manifest:
`app/androidApp/src/main/kotlin/com/ifinmail/update/AndroidUpdateController.kt:194-208`
`verifyIdentity` re-parses the downloaded APK, requires the package name to equal
`app.packageName` (`:200`), the long version code to equal `offer.release.versionCode` (`:201-203`),
and the set of signer digests to intersect the **installed** app's signer history (`:204-208`,
`signerDigests` at `:226-239`), deleting the file on any refusal (`:195-198`). The server also refuses
a release whose parsed signer differs from the ones already published
(`backend/apps/core/releases/services/release_service.py:171 _require_same_signer`, with the existing
set built at `:226-228`). So the honest statement is: authorship is enforced device-side and
server-side, the manifest's cert field is dead, and the residual exposure is *which host the bytes
come from* plus that the release build carries no `network_security_config` pin-set
(delegate-confirmed: `app/androidApp/build.gradle.kts:68,96-97` attach the config to debug only).
*Pointer:* drop `signingCertSha256` from the client DTO or compare it against the archive digests at
`:204`, and add the update host to a release `pin-set`.

**F146 — Med — `shared` cannot compile for the non-JVM targets it declares.**
`app/shared/build.gradle.kts:10-32` registers `iosArm64()`, `iosSimulatorArm64()`, `jvm()`,
`js { browser() }` and `wasmJs { browser() }`, but `app/shared/src/commonMain/…/ComposeScreen.kt:524`
calls `System.currentTimeMillis()` and `:542-552` uses `java.util.Calendar` — both JVM-only, and
`commonMain` is compiled for every declared target. The same class of slip appears in
`core/src/commonMain/…/vault/…:24` (`System.currentTimeMillis()`, delegate-confirmed) while
`core/build.gradle.kts:11-23` also targets iOS/JS/Wasm. No build was run here, so this is a static
contradiction between the declared target matrix and `commonMain` imports rather than a measured
failure — but it means the iOS/web/wasm targets have never been compiled in CI, or the Kotlin toolchain
is silently not being asked to.
*Pointer:* `kotlin.time.Clock`/`Instant` or an `expect`/`actual` clock, and one
`linkDebugTask` in CI per declared target.

**F147 — Med — the desktop and web shells ship, and the desktop installer packages, a UI with no mail
engine at all.**
`app/webApp/src/webMain/kotlin/com/ifinmail/main.kt:10` and
`app/desktopApp/src/main/kotlin/com/ifinmail/main.kt:12` both call `App()` with no controller argument,
so `app/shared/…/AppShell.kt:65-70` takes the "sync unavailable" branch for every screen; meanwhile
`app/desktopApp/build.gradle.kts:22-26` packages `dmg`/`msi`/`deb` artefacts of that stub. The Android
path is the only one that constructs a real controller
(`MainActivity.kt:25-28` → `RealMailController(…)`, delegate-confirmed).
*Pointer:* gate the packaging tasks until a desktop controller exists.

**F148 — Med — the iOS release configuration signs with a development identity against an empty team
ID.**
`app/iosApp/iosApp.xcodeproj/project.pbxproj:327` sets `CODE_SIGN_IDENTITY = "Apple Development"` for
the **Release** configuration, and `app/iosApp/Configuration/Config.xcconfig:1` defines `TEAM_ID=`
(empty) which `project.pbxproj` interpolates as `DEVELOPMENT_TEAM="${TEAM_ID}"`; no Distribution
identity or provisioning profile appears anywhere in the zone (delegate grep). A Release build either
fails or, worse, produces an artefact that cannot be distributed — and nothing in the repo fails the
build to say so.
*Pointer:* `xcconfig` validation step, or `DEVELOPMENT_TEAM` required with a `&& test -n` guard in the
release script.

**F149 — Med — on-device exposure while the phone is locked, and in Recents.**
`app/androidApp/src/main/kotlin/com/ifinmail/KeystoreCredentialStore.kt:101-109` builds the AES-256-GCM
key spec with no `setUserAuthenticationRequired`, no `setUnlockedDeviceRequired` and no
`setStrongBoxRequired`, so the key is usable by anything running as this UID at any time — the
deliberate trade-off for background IMAP sync, but undocumented here and paired with two weaknesses:
the blob's integrity is bound only to a sibling plaintext file (`:84-87`,
`filesDir/ifinmail-secrets.bin`), so the ciphertext is replayable against a copied plaintext marker;
and `grep -rn FLAG_SECURE clients/` returns no hits, so the inbox, message bodies and the password and
token fields all appear in the task switcher's snapshot of the app.
No `EncryptedSharedPreferences`/`MasterKey` anywhere (delegate grep); the GCM IV is fresh per call
(`:53`) and prepended to the blob, so there is no IV-reuse defect.
*Pointer:* document the locked-device trade-off, and set `FLAG_SECURE` in `MainActivity.onCreate` at
minimum on the message-body and credential screens.

**F150 — Med — `RealMailController` will silently fall back to a plaintext credential store.**
`app/androidApp/src/main/kotlin/com/ifinmail/RealMailController.kt:30` takes
`context: Context? = null` and, when null, uses `FileCredentialStore` instead of the Keystore one.
`FileCredentialStore` (`mail/src/main/kotlin/com/ifinmail/mail/store/FileCredentialStore.kt:52-55`)
writes the whole credential map as plain JSON to `ifinmail-credentials.json` with no permission
hardening, and its `load()` at `:42-49` swallows corruption into `CredentialFile()` — the same
silent-wipe shape as F141, for passwords. `MainActivity.kt:25-28` does pass a context, so nothing is
broken today; the default parameter is an armed trap one refactor away.
*Pointer:* make `context` non-null and let the compiler enforce it.

**F151 — Low — the client build has no dependency integrity, no minify keeps, and two version
sources.**
`clients/android/gradle/` contains only `gradle-daemon-jvm.properties`, `libs.versions.toml` and
`wrapper` — there is **no** `verification-metadata.xml`, so Gradle resolves without checksums
(compared with the Python side, where `requirements/prod.lock` is fully `--hash`-pinned and enforced at
`provisioning/docker/Dockerfile:13-14`). `gradle/libs.versions.toml:10` pins
`androidx-lifecycle = "2.11.0-beta01"` and `:23` `material3 = "1.11.0-alpha07"` for a shipping app.
`app/androidApp/proguard-rules.pro:1-21` is the untouched template and no `consumer-rules.pro` exists
anywhere, while release builds run R8 (`isMinifyEnabled`) — including the `@Serializable` update DTOs
whose JSON names come from `@SerialName` (`update/src/main/kotlin/com/ifinmail/update/UpdateModels.kt:79`).
`app/androidApp/build.gradle.kts:64-65` defaults `versionCode` to 1 / `"1.0"` while
`release-notes/1.1.0.md` documents 1.1.0, and `AndroidUpdateController.kt:203` requires an *exact*
version-code match with the offer — so a CI build that forgets `-Pifinmail.versionCode` produces an
APK that can never be updated by this code path.
*Pointer:* generate `verification-metadata.xml`, add `-keepclassmembers` for the DTOs, and take the
version from one file.

**F152 — Low — a dead Ktor server module listens on every interface if anyone runs it.**
`clients/android/server/src/main/kotlin/com/ifinmail/Application.kt:9-20` is the Ktor archetype
template: `embeddedServer(Netty, port = 8080, host = "0.0.0.0", …)` serving one `sayHello` route, with
no authentication, and it is still in the build — `settings.gradle.kts:40 include(":server")`. It
overlaps the real Python API and the `:server` name invites someone to mistake it for one.
*Pointer:* delete the module, or bind `127.0.0.1` and label it a fixture.

**F153 — Low — the client grants five IMAP capabilities the server never advertised, and the account**
**screen reports them as verified.** `adapter/ImapSession.kt:80-86` puts `MAIL_READ`, `MAIL_SEARCH`,
`MAIL_FLAG`, `MAIL_SENT_APPEND` and `MAIL_DELETE_REMOTE` into the granted set unconditionally; only
`MAIL_PUSH` (`:87`) and `MAIL_MOVE` (`:88`) are conditioned on a `CAPABILITY` reply. That set is then
returned as the verification outcome (`engine/MailEngine.kt:232,255,266-289`), persisted on the account
and surfaced to the UI (`app/androidApp/src/main/kotlin/com/ifinmail/RealMailController.kt:38` →
`app/shared/src/commonMain/kotlin/com/ifinmail/app/shared/mail/MailController.kt:17-19`). Two of the
five grants name commands the client does not implement at all: `imap/ImapClient.kt` exposes
`fetchSummaries` (`:168`), `fetchBody` (`:175`), `storeFlags` (`:185`), `expunge` (`:193`),
`append` (`:197`) and `idle` (`:218`) — there is no `SEARCH` and no `UID MOVE`/`COPY`, and `hasCapability`
(`MailController.kt:19`) has no call site anywhere in the module, so nothing consumes the other four
either. Only `MAIL_SENT_APPEND` gates a real decision (`MailEngine.kt:440-441`). The model is not wrong
— the *claim* is: a server that supports neither SEARCH nor MOVE still gets an account reported as
search-capable and flag-capable.
*Pointer:* derive each grant from its CAPABILITY token (`SEARCH`, `UIDPLUS`/`MOVE`, `FLAGS` support is
unconditional so `MAIL_FLAG` may stay), implement or drop `MAIL_SEARCH`, and either wire
`hasCapability` into the screens that would use it or delete the helper.

**Refuted or declined in this zone.**

* The `AndroidManifest.xml:38 `${applicationId}.fileprovider` / `@xml/file_paths` pair I went in
  looking for is correct as written — `android:authorities` is a manifest-placeholder site and
  `android:resource` a resource reference (`app/androidApp/src/main/AndroidManifest.xml:32-41`).
  REFUTED.
* "Update installs an arbitrary APK" — it does not: `verifyIdentity`
  (`AndroidUpdateController.kt:194-208`) is exactly the control the manifest's dead `signingCertSha256`
  appears to promise, and it is stronger because the trust anchor is the installed app rather than a
  server-supplied string. REFUTED as a High; F145 keeps only the host-selection and dead-field residue.
* TLS trust ordering in `mail/src/main/kotlin/com/ifinmail/mail/transport/TlsTrust.kt:43-52` and
  `MailTransport.kt:131-135`: system trust first, a pin applied only as an exception for the exact
  leaf, hostname verification still on — and `TlsPinningTest.kt:110-129` proves a pin cannot override
  hostname checks and a stale pin cannot block a valid certificate. Nothing to report except
  `TlsTrust.kt:38`, where a pin containing no hex characters normalises to the empty string and stops
  being enforced (Low, folded into F142's neighbourhood rather than listed separately).
* `UpdateManifest.kt:46` refuses a downgrade (`latest.versionCode <= installedVersionCode` →
  `UpToDate`) and `:63-71` pins the package name and lowercases both digests before comparison; the
  `allowInsecure` flag at `:73-93` is only ever true in the debug/dev path.
* Dot-stuffing (`smtp/SmtpClient.kt:168-180`, tested at `ProtocolClientsTest.kt:155-161`), POP
  un-stuffing (`pop3/Pop3Client.kt:101`), quoted-string escaping symmetry
  (`imap/ImapClient.kt:425-443`), the 64 MiB literal cap with negative-length rejection
  (`ImapClient.kt:297-300`), XXE-proof autoconfig (`DiscoveryAutoConfigSource.kt:75-79,102-105` with a
  test at `DiscoveryAutoConfigSourceTest.kt:91-95`), and DAV credentials sent only over TLS and never
  to a redirect host (`CalDavCardDavAdapter.kt:109-115`, `DavProbeTest.kt:94-111`) are all correct.
* Android export posture: the only exported component is `MainActivity` with MAIN/LAUNCHER, it reads no
  intent extras (so `SERVER_URL` cannot be injected), `allowBackup=false`, no deep links, and the
  FileProvider is `exported=false` with `grantUriPermissions` over a
  `file_paths.xml:4` that exposes only `cache-path exports/`.

**What the client got right.**

* `AndroidUpdateController.kt:241-258` uses a `PackageInstaller` session sized with
  `setAppPackageName` and `setSize(file.length())` against a private `cacheDir/updates` download, and
  the status receiver is a non-exported `UpdateInstallReceiver`
  (`AndroidManifest.xml:43-46`, with the comment "nothing outside the system may call it").
* The background update check only *checks* (never downloads), is network-constrained and deduplicated
  per version (`update/…/UpdateCheckWorker.kt`, delegate-confirmed).
* Keystore crypto is sound in itself: AES-256-GCM, non-exportable key, fresh IV per call prepended to
  the blob (`KeystoreCredentialStore.kt:53`), and no `localStorage`/`sessionStorage`/`indexedDB` writes
  anywhere in `webApp` or `shared/jsMain`/`wasmJsMain` — there is nothing XSS-readable on the web
  target because nothing is wired.
* Capability granting is at least explicit: `adapter/ImapSession.kt:80-96` starts from a named set and
  adds `MAIL_PUSH` only when the server advertises `IDLE` — the defect (F153-adjacent, kept at delegate
  level) is that four of the base grants have no implementing command, not that the model is wrong.
* `update/…/UpdateManifest.kt:36-42` distinguishes `SerializationException` from
  `IllegalArgumentException` and wraps both in `UpdateException(BAD_RESPONSE, "The update server sent
  something unreadable.", e)` with the cause attached — the error text an operator sees, in plain
  language, with the technical chain preserved.

**COVERAGE STATEMENT.** 171 files under `clients/android` in `git ls-files`; all Kotlin sources were
read in full by three delegate chunks (mail 37 + core 15 = 52 read in full, platform apps 50 with
`AppIcon.appiconset/app-icon-1024.png` only stat'd as a binary, shared UI 42), plus the Gradle,
manifest, xcconfig and ProGuard files. This author re-read in full or in the cited ranges:
`mail/mime/MimeComposer.kt`, `mail/adapter/SmtpSubmissionAdapter.kt`, `mail/adapter/Pop3AccessAdapter.kt`,
`mail/adapter/ImapSession.kt`, `mail/imap/ImapClient.kt`, `mail/store/MailStore.kt`,
`mail/store/FileCredentialStore.kt`, `mail/engine/MailEngine.kt` (`:68-112`, `:178-212`, `:415-436`),
`core/domain/model/DomainModels.kt`, `mail/model/Models.kt`,
`update/UpdateManifest.kt`, `update/UpdateModels.kt`, `update/UpdateHttp.kt`,
`app/androidApp/…/AndroidUpdateController.kt` (`:190-258`), `app/androidApp/src/main/AndroidManifest.xml`,
`settings.gradle.kts`, `server/src/main/kotlin/com/ifinmail/Application.kt`,
`gradle/libs.versions.toml`, and the server side of release integrity
(`backend/apps/core/releases/services/apk.py`, `services/release_service.py:171,194,226-228`).
**Mechanical greps only:** `LOGINDISABLED` (0 hits), `signingCertSha256` consumers, `FLAG_SECURE`,
`keytool` (0 hits — the APK is parsed in Python, `services/apk.py`), `typealias Account`,
`gradle/` listing, pre-release version strings. **Explicitly not inspected or not done:** no Gradle
build, no `assembleRelease`, no install or device run — so F146 (commonMain JVM APIs), F151's R8/keep
claim and F145's redirect behaviour are static readings, not measured ones; the
`app/shared` 42 Kotlin files were read by the delegate and only the cited lines re-read here;
`iosApp` Swift sources beyond the two cited project files, and every `mail/src/test` / `update/src/test`
body except the cited assertions, were not re-read by this author.

### 9.12 `frontend/static` — 35 CSS/JS assets (56 tracked files in the directory: 26 `.js`, 9 `.css`, 9 SVG, 2 static error pages, 2 fonts, 5 PNG, 1 ICO, 2 `.gitkeep`)

Zone inventory: `frontend/static` = 26 `.js` + 9 `.css` + 2 `.html` (error pages) + 9 `.svg`
(`static/icons/`) + 5 `.png` + 2 `.woff2` + 1 `.ico` + 2 `.gitkeep`; the 35 CSS/JS assets are
14,092 lines. Three delegate chunks: js 1–13, js 14–26 + `service-worker.js`, css + icons + error
pages. This author re-read every line cited below except where marked *delegate-confirmed*.

**F154 — High — a reflected XSS runs in the setup wizard: the provider field round-trips through the
server and is injected with `innerHTML`.**
`backend/apps/accounts/views/setup.py:299-300` stores `request.POST.get('provider', '')` in the session
with no validation against the provider registry. `frontend/templates/setup/dns_auto.html:7` renders it
as `data-provider="{{ dns_provider|escapejs }}"` (correct for the attribute), and
`frontend/static/js/ifinmail-setup.js:34` posts that value straight back to `{% url 'dns:configure' %}`.
The endpoint answers an unrecognised provider with
`message=f'Unknown provider: {parsed.provider}'` (`backend/apps/dns/viewsets/configure.py:35-39`) —
verbatim echo, no allow-list — and `ifinmail-setup.js:58` writes
`resultEl.innerHTML = '<div …><p>Configuration failed: ' + (data.message || 'Unknown error') + '</p></div>'`
into the `<div id="dns-result-message">` at `dns_auto.html:46`. So typing
`<img src=x onerror=…>` as the DNS provider in the wizard executes script in the setup page, in the
same response, with the setup operator's session. The second tainted branch is the same shape:
`configure.py:61-63` returns `message=str(e)` for a `DomainProvisioningError`, and those messages embed
the domain. Contrast the rest of the zone, which is careful — `ifinmail-logs.js:36-63` and
`ifinmail-dns-config.js:164,173` render server data only through `createTextNode`/`textContent`, and
`ifinmail-assistant.js:144`'s `innerHTML` at least escapes first (`:119-123`).
*Pointer:* `textContent` on a pre-built node at `:58`, and validate `provider` against `PROVIDER_MAP`
before `setup.py:300` stores it.

**F155 — Med (a11y) — `--ifinmail-color-error` is defined in no stylesheet, so seven error-text rules
silently fall back to a literal `#dc2626` in the dark and contrast themes.**
`grep -rn -- "--ifinmail-color-error:" frontend/static/css/` returns **nothing**, while seven uses
exist (`ifinmail-components.css:2554` plus `:2611, 2664, 2669, 2757, 2759, 2775`), each written as
`var(--ifinmail-color-error, #dc2626)`. Because the token is undefined, the fallback always wins — in
all three themes — so dark-mode error text is `#dc2626` on a near-black surface instead of the light red
the theme system actually provides: `--ifinmail-color-danger` is defined per theme at
`ifinmail-variables.css:32` (`#DC2626` light), `:395` (`#F87171` dark) and `:467` (`#FF7B7B`
contrast). This is exactly the failure the design rule exists to prevent (no literal colours outside
the token layer; a new token needs a value in both the `dark` and `contrast` blocks), and it lands on
the text that explains what went wrong. `ifinmail-components.css` carries 18 raw hex values in total,
16 of them `var()` fallbacks.
*Pointer:* rename the seven uses to `--ifinmail-color-danger` and let the audit script fail any
`var(--ifinmail-…)` whose token is undefined.

**F156 — Med (a11y) — the mobile navigation drawer hides the panel by transform only, so twenty-plus
links stay in the tab order off-screen.**
`frontend/static/css/ifinmail-components.css:2285-2296` in the `max-width: 767px` block sets
`.ifinmail-admin-nav { position: fixed; width: 280px; transform: translateX(-100%); }` and reveals it
with `--open` — no `visibility`, no `inert`, no `display`. Keyboard users tabbing through the console
on a phone walk through the closed drawer first, with focus rendered off-viewport (the design-system
mobile rule is "sidebar is a drawer behind the hamburger", not "invisible but focusable"). The correct
pattern already exists in the same stylesheet family: the assistant rail at
`ifinmail-redesign.css:2925-2937` pairs `transform: translateX(-100%)` with `visibility: hidden` and
transitions both, and `redesign.css:1950-1953` (the only mobile `.ifinmail-admin-nav` rule in the
canonical sheet) adds padding and a width transition but no visibility — so loading order does not
rescue it.
*Pointer:* add `visibility: hidden` and transition it, or render the closed drawer with
`inert` from `ifinmail-sidebar.js`.

**F157 — Med — the console loads Inter and JetBrains Mono from the Google CDN by default, and the local
copies that exist in this repo are wired only to the public site.**
`frontend/templates/base.html:27-31` emits the `preconnect` + `stylesheet` pair for
`fonts.googleapis.com` whenever `USE_GOOGLE_FONTS` is truthy, and the context processor's default is
on: `backend/config/server_context.py:51`
`os.environ.get('USE_GOOGLE_FONTS', '1').lower() not in ('0','false','no')`. So a fresh install sends
every console visitor's IP and User-Agent to a third party — on a product whose own stylesheet says
the opposite, `frontend/static/css/ifinmail-site.css:12`
"Fonts are served from this server: reading the site tells no third party who visited", backed by real
`@font-face` rules at `:13-29` pointing at `../fonts/inter-latin.woff2` and
`../fonts/jetbrains-mono-latin.woff2` (both present: 48 KB and 31 KB). Those declarations live in
`ifinmail-site.css`, which is **not** in the console's load order
(`base.html:33-41`: variables, reset, utilities, layout, components, admin, redesign, then smooth), so
turning the flag off does not use the shipped fonts either — it drops to system UI faces. A third
path adds the same CDN dependency per brand font: `backend/config/branding.py:195-199` writes a
`@import` for the configured heading/body family (see F129). Also unaddressed: no OFL licence file for
either typeface appears anywhere under `frontend/static` or `docs/` (*delegate-confirmed by a repo-wide
grep*) — a provenance gap for fonts that are redistributed in the image.
*Pointer:* move the two `@font-face` blocks into `ifinmail-variables.css` (or a `fonts.css` loaded
before it), default `USE_GOOGLE_FONTS` to `0`, and add the OFL texts.

**F158 — Med — the HTML error page renders `str(exception)` for any visitor; four views put raw
request input in it.**
`backend/config/urls.py:267` builds the HTML error context with
`'error_description': str(exception) if exception is not None else ''` and
`frontend/templates/error_base.html:16` prints it in an autoescaped `<p>` — no `DEBUG` gate anywhere in
`_make_error_handler` (`:229-271`). Django hands the exception to the 4xx handlers, and four call sites
raise with the user's own input as the message: `accounts/views/settings_hub.py:60
raise Http404(slug)`, `accounts/views/website.py:85 raise Http404(key)`,
`dns/views/server.py:43 raise Http404(zone)`, `config/public_pages.py:92 raise Http404(key)`. The
output is escaped, so this is not XSS — it is (a) an arbitrary-text reflection on a page served from
the real origin, which is a convincing phishing canvas ("this message came from mail.example.com"),
and (b) a disclosure of whether a given zone/slug/page key exists, plus whatever a future
`Http404(f'no mailbox {address}')` says. It also breaks the error-page pattern the design system
specifies (state what happened, offer one next action) because the echoed input crowds out the fixed
copy. Note this is the mirror image of F128: the context variables *are* supplied here, so it is the
one place `error_base.html:4` and `:17-18` work as written.
*Pointer:* render `str(exception)` only under `settings.DEBUG` and a fixed sentence otherwise.

**F159 — Med — the DNS wizard's show/hide helper manipulates a class the page never sets, so the
required IP field cannot be revealed and the hidden fields still submit.**
`frontend/static/js/ifinmail-dns-config.js:14-16` defines
`show(el)/hide(el)/isHidden(el)` around `ifinmail-hidden`, and `:66-78` calls them on the parent-domain
and IP groups. But `frontend/templates/admin/dns_config.html:125` and `:134` render those groups as
`<div class="ifinmail-form-group ifinmail-form-group--hidden" id="parent-domain-group">` /
`id="ip-address-group"`, and the class that actually hides them is
`ifinmail-admin.css:1206` (`.ifinmail-form-group--hidden`), not `.ifinmail-hidden`
(`admin.css:1229`, `utilities.css:94`). Consequences: `show(ipGroup)` removes a class the element does
not have, so the IP input — marked required in its own label, `dns_config.html:135`
`IP Address <span class="ifinmail-required">*</span>` — never appears for a subdomain entry; and
`isHidden()` is always false, so `:117,120` read and submit values from groups the user cannot see.
One class name on both sides fixes it.

**F160 — Med — the service worker cannot control the console, and when it does intercept, it can turn a
network failure into an empty 200-shaped 503.**
Two halves, one inert and one harmful. Inert: `frontend/static/js/ifinmail-sw-register.js:11` calls
`register(url)` with no `scope` argument and no `.catch`, and the worker is served from `/static/js/`
(`base.html:80`), so its default scope is `/static/js/` and it never claims a console page —
`Service-Worker-Allowed` appears nowhere in the repo (*delegate grep*). Harmful where it does run:
`frontend/static/js/service-worker.js:62` catches a failed `fetch` and answers
`new Response('', {status: 503})`, while `:47` excludes only `/accounts/` and `/dns/` from
interception — so `/api/…`, `/v1/…` and `/mail/…` GETs under the worker's scope come back as an empty
body that every caller then feeds to `r.json()`. Add `:24`'s `cache.addAll` over eight hardcoded
`/static/css/*` paths, which rejects atomically if one 404s (renamed sheet or a `STATIC_URL` override),
so install fails and the stale worker is kept silently; `:6` falls back to
`CSS_VERSION = 'dev'` while `settings.CSS_VERSION` is legitimately empty at
`backend/config/settings/base.py:172`, so the cache name never rotates and `:33`'s delete-mismatched
eviction never accumulates against a changing key; and `:55`'s `caches.open().put()` sits outside
`event.waitUntil()`, so the write may be dropped. One structural conflict behind the versioning part:
`backend/config/settings/production.py:42` selects `ManifestStaticFilesStorage` while
`base.py:182-185` sets `STORAGES['staticfiles']` to plain `StaticFilesStorage`, and the precache list
names unhashed files (*delegate-confirmed pair*).
*Pointer:* serve the worker from the origin root or send the header, wrap the put in `waitUntil`, use
`Promise.allSettled` per asset, and pick one staticfiles backend.

**F161 — Med — destructive console actions have no in-flight guard, and one of them fires on page
load.**
`ifinmail-setup.js:8-18` performs the state-changing DNS `POST` from a `DOMContentLoaded` listener
using session-supplied attributes, with no button involved and no re-entry flag — and
`dns/viewsets/configure.py:49-52` calls `DNSService.update_or_create_config(...)` before
`ProvisioningService.add_domain(...)` at `:57`, whose own comment (`:54-55`) says the pipeline
"creates the DKIM key first"; each reload of that wizard step therefore re-saves provider credentials
and re-enters key creation until the session key is popped at `setup.py:324`. The same missing guard
appears on four destructive or racy controls: purge-logs (`ifinmail-dashboard.js:73`, wired from
`dashboard.html:121` and `settings_maintenance.html:31`, both `<a href="#">`), kill-sessions for an
address (`ifinmail-users.js:36`, `user_management.html:58`), the proxy and relay switches
(`ifinmail-dns-config.js:247,269` — `<span>` toggles per `dns_config.html:95,99`, so double-clicking
fires two `fetch`es and the class follows the last response rather than the server's state), and the
branding save (`ifinmail-branding.js:66`, which also carries file uploads). Against that, the zone does
know how to do this correctly: `ifinmail-dns-config.js:140`, `dashboard.js:18`, `login.js:14`,
`health.js:44`, `ifinmail-passkeys.js:83,103` and `ifinmail-spam.js` all disable first.
*Pointer:* `btn.disabled = true` before `fetch`, restore in `finally`; move the setup POST behind a
button.

**F162 — Med — the assistant locks its own composer after the polling budget runs out, with no
message.**
`frontend/static/js/ifinmail-assistant.js:165` calls `lockComposer(true)` when a turn starts, and the
poll chain at `:110-113` simply stops after 400 iterations — no give-up notice and nothing that
re-enables send unless a `swapIn` succeeds. The operator is left with a greyed composer on a page that
looks idle, and cannot start a new turn without reloading. The same file also has no
`document.hidden` check, unlike `ifinmail-logs.js:110-121`, which clears its interval on
`visibilitychange` — so a backgrounded tab keeps polling.
*Pointer:* on budget exhaustion, unlock and say so; stop polling while hidden.

**F163 — Med — four `fetch` sites post an empty CSRF header when the token is not on the page.**
`frontend/static/js/ifinmail-csrf.js:31` returns `''` when neither a
`[name=csrfmiddlewaretoken]` input nor a cookie is present, and the callers send it unconditionally as
`X-CSRFToken` (`ifinmail-branding.js:68`, `ifinmail-dashboard.js:24,75`,
`ifinmail-dns-config.js:149`), guaranteeing a 403 with no client-side signal — the UI shows a spinner
that ends with nothing. Most pages do render `{% csrf_token %}` (`base.html:45`), which is why this
stays Med rather than High: it fires on the pages that omit it. Meanwhile `ifinmail-api.js:5` hardcodes
`API_BASE = '/v1'` against the real mount `/api/v1/` (`backend/config/api_versions.py:41`), reads
`error.code`/`error.message` where Django Ninja emits `detail` (`:55`), and interpolates values into
URLs with no `encodeURIComponent` (`:90,94,102`) — but the file is loaded by no template and is waived
in `backend/apps/core/tests/test_url_contract.py:75` with the comment "a client for the legacy /v1 base
and is not loaded". Dead code protected by a test exemption rather than deleted.
*Pointer:* throw in `csrfToken()` when empty, and delete `ifinmail-api.js`.

**F164 — Low — silent-failure and dead-code residue in the zone.** All *delegate-confirmed* unless a
line is cited here.
`ifinmail-shortcuts.js:56` calls `closeModal_shortcuts`, a function defined nowhere in the repo, and
`:12-14,83` bind `#sidebar-more-trigger` / `#system-info-modal`, which exist in no template — the whole
modal block is dead. `ifinmail-registration.js:194` does `JSON.parse(xhr.responseText)` unguarded, so
an HTML or CSRF interstitial response throws inside `onreadystatechange` and the "Checking…" indicator
stuck at `:206` never clears. `ifinmail-logs.js:91` selects
`tr[data-log-id]:last-of-type`, which is null when the final body row is not a log row; the resulting
TypeError is swallowed by the `.catch` at `:98`, which repaints "Live view" as if the feed were merely
idle. `ifinmail-mailboxes.js:112` builds `profileLink.href` by string-substituting a DOM `data-id` into
`data-url-template` with no UUID shape check. `ifinmail-tables.js:51` attaches a never-disconnected
`MutationObserver` on `document.body` with `subtree`, which re-labels every table cell on each batch of
live log rows. `ifinmail-dns-config.js:299-305` `setHopCount` has neither `r.ok` nor a `.catch`, so a
failed POST leaves the relay hop-count label showing a value that was never saved.
`ifinmail-actions.js:21` copies the TOTP secret to the clipboard for `admin/mfa_setup.html:79`
(`data-copy-from="mfa-secret"`), which is readable by other tabs and extensions.

**F165 — Low — stylesheet residue the design rules already forbid.** All *delegate-confirmed by grep*,
counts from the css-assets chunk's own hex tally.
Zero-reference selectors: `.ifinmail-table--striped` (`ifinmail-components.css:430` — also a banned
pattern), `.ifinmail-health-indicator--{pass,warn,fail}` (`:919-941`), `.ifinmail-toggle` (`:1641`),
`.ifinmail-switch` (`ifinmail-admin.css:369`), `.ifinmail-engine-row--disabled` (`:1263`). Left-border
accent cards — on the skill's explicit "Never" list — reappear at `ifinmail-redesign.css:3615,3618`,
`ifinmail-components.css:582,893,1029,1394,1529,1800,2847,2963` and `ifinmail-admin.css:129`, after
being removed at `redesign.css:106-113`. Typo'd tokens fall through to off-scale literals: undefined
`--ifinmail-border-radius-md` (`components.css:2340,2563,2650`), `--ifinmail-space-4_5`
(`admin.css:588`), `--ifinmail-font-weight-regular` (`redesign.css:378`). Ad-hoc `rem`/px font sizes
bypassing the `--ifinmail-font-size-*` scale appear at `site.css:47,103,452,643,700,728,828,844,976`,
`redesign.css:2831-2832,3024,3031` and `admin.css:224,775,1168,1218`. `!important` is concentrated in
the legacy sheets (154 uses in `admin.css`, 43 in `redesign.css`, 6 in `smooth.css`, 5 in
`components.css`). The static error pages miss the enforced `100vh`/`100dvh` pairing
(`frontend/static/error-pages/40x.html:48`, `50x.html:48`), and `.error-code` at `:58` sets the largest
text on the page in `--ifinmail-color-border` (about 1.4:1) — computed, not measured. Icons hard-code
`#1a56db/#ffffff/#7aa2f7/#0f2b5b`, so a custom brand primary cannot reach them, and
`static/icons/icon-512.svg` is named 512 while declaring a 192 box. `.ifinmail-global-search input
{ outline: 0 }` at `components.css:1851` removes the focus ring the tokens promise.
*Pointer:* `prune_css.py --apply` for the dead selectors (see F172 for the risk in that script), one
token-name lint, and a focus-ring restoration.

**Refuted or declined in this zone.**

* The claim that user content is cached by the service worker is wrong. `service-worker.js:44` returns
  early for every non-GET, `:47` excludes `/accounts/` and `/dns/`, and `:53` writes to CacheStorage
  only for paths beginning with `/static/`; `MEDIA_URL` is `/media/`, so photos and attachments are
  never stored. No cross-operator page leak on a shared machine. REFUTED.
* `ifinmail-passkeys.js:92`'s `location.assign` is not an open redirect: the destination is validated
  server-side with `url_has_allowed_host_and_scheme`
  (`backend/apps/accounts/views/passkeys.py:212`).
* `ifinmail-registration.js:180`'s five `innerHTML` writes are fixed literals chosen by
  `data.available` — no tainted data reaches them. Sink accounting only, not a finding.
* The `escapejs` in `dns_auto.html:7` is the right filter for a JS-read attribute; the defect is the
  `innerHTML` on the way back (F154), not the render.
* Zero external `url()`, zero `@import`, zero `expression()`/`-moz-binding` in the nine stylesheets;
  the only `data:` URIs are four inline-SVG chevrons (`variables.css:63,367,414,486`); no hostname or
  username appears in any `content:` string; all nine SVGs have no `script`, `foreignObject`, `onload`
  or external `xlink:href`. Both static error pages are self-contained and reached only through
  `nginx`-side `internal;` (`provisioning/docker/nginx/.../ifinmail.conf:121-133`).

**What the zone got right.**

* CSRF is universal on mutating calls: `X-CSRFToken` in branding, dashboard, dns-config and setup
  (`ifinmail-setup.js:29-30`), `FormData(form)` over a rendered `{% csrf_token %}` in assistant
  (`assistant.html:169,185`), `credentials: 'same-origin'` in passkeys (`:35`) — and no token or
  cookie value is ever placed in a query string.
* Every fetch target in the zone comes from a Django-rendered `data-*` attribute or `{% url %}`
  (`dns_config.html:15,95,99,102,144`, `dashboard.html:19,121`, `logs.html:18`, `dns_row.html:9`,
  `assistant.html:155`); `test_url_contract.py:73-75` waives only the two files that genuinely cannot
  read a page.
* Rendering server data is text-only almost everywhere — `logs.js:36-63`, `dns-config.js:164,173`,
  `ifinmail-spam.js:14` (which parses `{{ levels|json_script }}` from `spam_filtering.html:82`),
  `ifinmail-photo.js`, `ifinmail-settings.js`, `ifinmail-theme-init.js` — and theme-init allow-lists
  every `localStorage` value before use (`:27,64`), persisting only the theme name.
* Reduced motion is honoured globally (`ifinmail-reset.css:66-72`, repeated at `layout.css:549,649`
  and `redesign.css:2297,2673,3093`), the `?v=` cache-buster is a real content digest
  (`base.py:172`, `backend/config/static_versioning.py:14-25`), and the worker is network-first.
* `ifinmail-variables.css` holds 192 hex values and is the sanctioned token layer;
  `layout/redesign/site/smooth/utilities/reset` hold **zero** raw hex.

**COVERAGE STATEMENT.** 35 CSS/JS assets in zone (26 `.js`, 9 `.css`, 14,092 lines) plus 9 SVG, 2
static error pages and 2 `.gitkeep`: **all 26 JS and all 9 CSS and both error pages read in full**
across the three delegate chunks (js 1–13 in chunk A, js 14–26 + `service-worker.js` in chunk B, css +
icons + error pages in chunk C). Binaries — `inter-latin.woff2`, `jetbrains-mono-latin.woff2`,
`favicon.ico`, 5 PNG — were stat'd, not parsed, and the missing OFL licence texts are reported as a
provenance gap rather than a licence judgement. This author re-read in full or in the cited ranges:
`ifinmail-setup.js`, `ifinmail-dns-config.js`, `ifinmail-csrf.js`, `service-worker.js`,
`ifinmail-mailboxes.js:258-307`, `ifinmail-components.css` (drawer and error-token regions),
`ifinmail-redesign.css:1946-1967` and `:2925-2940`, `ifinmail-site.css:8-29`, `base.html:14-41`,
`dns_config.html:123-136`, `setup/dns_auto.html:7`, `accounts/views/setup.py:110-120,288-308,324`,
`dns/viewsets/configure.py:28-67`, `config/urls.py:229-271`, `error_base.html`,
`config/server_context.py:51`, `config/settings/base.py:172`, `config/api_versions.py:41`,
`core/tests/test_url_contract.py:47-82`, and the token/danger grep in `ifinmail-variables.css`.
**Mechanical greps only:** `--ifinmail-color-error` definition/uses, `ifinmail-form-group--hidden` vs
`.ifinmail-hidden`, `data-setup-dns`, `Service-Worker-Allowed` (0 hits repo-wide), `@font-face`,
`closeModal_shortcuts`, hex/`!important` counts, dead-selector reference checks across `frontend/`.
**Not inspected:** the Django static/media serving and whitenoise configuration (so F160's scope
conclusion rests on the script URL plus the absent header, not on a measured registration), and the
provisioning internals behind `dns_step.detail`.

### 9.13 requirements, CI, agent skills, repo state

Zone: `requirements/` (5 files), `.github/workflows/` (2), `Makefile`, `pyproject.toml`,
`.gitignore`, `.dockerignore`, `provisioning/.env.example`, `AGENTS.md`, `DESIGN.md`, `SECURITY.md`,
`README.md`, `CHANGELOG.md`, the 5 `.agents/skills/*/SKILL.md`, `.agents/skills/**/scripts` +
`find-polluter.sh`, 6 `docs/*.md`, `examples/python/README.md` + `ifinmail_client.py`. One delegate
read these; this author re-read every line cited below and measured the counts locally.

**F166 — High — `requirements/prod.lock` contradicts `requirements/base.txt`, and the lock is the file
that actually installs.** `base.txt:9` declares `redis>=8.1.0,<9.0`; `prod.lock:917` pins
`redis==5.3.1`. `provisioning/docker/Dockerfile:13-14` installs the lock under
`--require-hashes`, so the shipped container runs redis 5.3.1 while the declared constraint demands at
least 8.1 — a two-major-version gap in the library that carries every Celery broker message and the
rate-limit counters. Nothing notices: `pip-compile` was not re-run, and no test asserts that a lock
satisfies its own source (`Makefile` has no `lock --check` step, and §3 showed CI never compares
them). Anyone reading `base.txt` to decide whether a redis feature is available will be wrong about
production.
*Pointer:* `make lock`, then a CI job that runs `pip-compile --check` (or diffs the regenerated lock) so
drift fails the build.

**F167 — High — the same drift on the HTTP server: the image runs gunicorn 23.0.0 while
`production.txt` requires 26.x.** `requirements/production.txt:2` declares
`gunicorn>=26.2.0,<27.0`; `requirements/prod.lock:389` pins `gunicorn==23.0.0`. Gunicorn 24/25/26 are
exactly the releases that changed worker/timeout handling and security fixes, and this is the process
that terminates the console (§9.8 already records what the container exposes). Because both drifts are
in the same direction — lock older than declaration — the practical reading is that `prod.lock` was
generated before the two constraints were raised and has not been regenerated since.
*Pointer:* regenerate, then re-run `python -m pip_audit -r requirements/prod.lock` (already a CI step,
`ci.yml`) — with a stale lock, pip-audit is auditing packages nobody intends to ship.

**F168 — High — CI tests a different dependency set from the one that ships.**
`.github/workflows/ci.yml:31-34` installs `requirements/testing.txt`, which is
`-r base.txt` + `-r development.txt` — i.e. **range-resolved, unhashed**: the job gets whatever
`redis>=8.1.0,<9.0` resolves to that day, while the image gets `redis==5.3.1` and `gunicorn==23.0.0`
from the lock. So the suite (pytest with `--cov=backend` and `fail_under=70`, mypy strict,
`django --deploy` check, ruff) has never once run against the versions actually shipped, and the two
F166/F167 drifts are structurally invisible to it: an incompatibility between the code and redis 5.3
fails no test, because no test uses redis 5.3. The `pip_audit` step (`ci.yml`) does read
`prod.lock`, which is the one place the real set is exercised — for CVEs only.
*Pointer:* install `-r requirements/prod.lock --require-hashes` plus dev tools in the test job.

**F169 — High — a shipped agent script always reports "all tests clean" in a repo that has no npm.**
`.agents/skills/systematic-debugging/find-polluter.sh:42` runs
`npm test "$TEST_FILE" > /dev/null 2>&1 || true` and then decides success from whether a marker file
appeared (`:45-47`). `git ls-files | grep -c package.json` is **0** — there is no Node project in this
repository at all — so every invocation fails immediately, `|| true` discards that, the marker never
appears, and the loop prints the all-clear for each of the files it was asked to bisect. The script is
not documentation: it is a tool an agent is told to run when hunting test pollution, so its output is
load-bearing, and "no polluter found" is the one conclusion it cannot support. (The emoji in its
progress output at `:48` also violates the repo's no-emoji convention.)
*Pointer:* delete it, or port it to `python -m pytest -p no:randomly "$TEST_FILE"` with the exit code
checked and no `|| true`.

**F170 — Med — `ci.yml` asks for no token permissions and pins third-party Actions by mutable tag.**
There is no `permissions:` key anywhere in `.github/workflows/ci.yml` (verified: grep over the file
returns only `uses:` lines), so the job inherits the repository default write token, including for the
gitleaks and shellcheck steps. Every one of the six `uses:` in `ci.yml` (`:24,26,58,82,87,92`) and the
four in `android-release.yml` (`:45,47,51,87`) is tag-pinned; **0 of 10 are pinned to a commit SHA**,
and one of them is third-party code — `gitleaks/gitleaks-action@v3` at `ci.yml:87` — which runs in the
same job that holds the checkout of a mail-server repository. `android-release.yml:33` does set
`contents: read`, which shows the practice is known.
*Pointer:* `permissions: contents: read` at the top of both workflows and `uses: owner/repo@<sha>`
with the tag in a comment.

**F171 — Med — the design audit reports "clean" for a path it could not read.**
`.agents/skills/ifinmail-design-audit/scripts/audit.sh:23` takes `TARGETS` from arguments and `:85-87`
runs `find … 2>/dev/null`, so a typo'd template path, a renamed directory or a target the operator has
no permission to read produces no findings and exit 0 — the same false-green shape as F169, in the
script the design workflow tells every agent to run before finishing UI work (it is the last step of
both `ifinmail-design-system` and `ifinmail-template-builder`).
*Pointer:* assert each `TARGETS` entry exists and is readable, print the file count scanned, and fail
on zero files.

**F172 — Med — the CSS pruner rewrites six source stylesheets in place with no backup and no dirty-tree
check.** `.agents/skills/ifinmail-design-audit/scripts/prune_css.py:244-256` implements `--apply` as a
direct write over `ifinmail-*.css`. Dead-selector detection is heuristic (grep for the class name in
templates/JS), and the repo contains the counter-examples: `ifinmail-hc--error` is emitted by a
template's `{% if %}` composition (`frontend/templates/admin/threats.html:116`, F138) rather than as a
literal string, and several `--*` modifier classes are built by string concatenation in JS
(`ifinmail-mailboxes.js` builds badge names, `service-worker.js` builds cache names). A name that only
ever appears assembled at runtime reads as unreferenced to a grep-based tool, so an `--apply` run can
delete live rules and leave a diff that looks like housekeeping.
*Pointer:* refuse to run on a dirty tree, write a `.bak` or emit a patch instead of overwriting, and
require an explicit allow-list of selector shapes it may remove.

**F173 — Med — the Android release doc tells the operator to put a `system.manage` key on the command
line, and the examples README forbids exactly that.**
`docs/android-releases.md:31` instructs `export IFINMAIL_API_TOKEN=ifm.<key>.<secret>` before the
publish commands. That token is the release-upload credential for the whole server (the same value the
`android-release.yml` secret table at `docs/android-releases.md` describes), and exported it lands in
shell history, in `/proc/<pid>/environ` of every child process, and in any CI log that echoes the
command. `examples/python/README.md:107` states the opposite rule for the same credential class
(don't pass the secret where a reader or a log can see it). The doc is also the one an agent follows,
which makes it a documented bad default rather than a one-off habit.
*Pointer:* `read -rs IFINMAIL_API_TOKEN` or `--token-file`, and make the two documents agree.

**F174 — Med — a shipped skill instructs loading two skills that do not exist in this repository.**
`.agents/skills/systematic-debugging/SKILL.md:179` and `:287-288` tell the reader to use
`superpowers:test-driven-development` and `superpowers:verification-before-completion`.
`.agents/skills/` contains five skills — `ifinmail-design-system`, `ifinmail-template-builder`,
`ifinmail-design-audit`, `ifinmail-plugins`, `systematic-debugging` — and no `superpowers` namespace.
An agent that follows the instruction either stalls on a missing skill or, worse, invents the step it
was pointing at; the guidance the two names carry (write the failing test first, verify before
claiming done) is therefore unenforced in the debugging flow.
*Pointer:* inline the two rules or drop the references.

**F175 — Med — the release history does not describe the code that is checked out.**
`CHANGELOG.md:3` opens with `## v0.0.75`, and the highest tag is `v0.0.74`: 0.0.75 is documented but
untagged, so no deployable ref corresponds to the entry that describes Marketing campaigns. Meanwhile
`git describe` on HEAD (`82cd235`) resolves through `backup/broken-v0.0.2-6-g82cd235`, i.e. the
nearest tag in the graph is on a `backup/broken-*` ref rather than a release, and the two most recent
commits are both titled `v0.0.2` (see §2, where the merge and the version churn are recorded). Anything
that derives a version from the repository — `APP_VERSION` in
`backend/config/server_context.py:41`, the release notes an operator would read, the Android
`versionCode` question at F151 — has to guess.
*Pointer:* tag 0.0.75, delete the `backup/broken-*` tags (or move them to a remote-only ref), and make
one commit carry one version.

**F176 — Med (unproven) — the gitleaks step may not be running at all.**
`.github/workflows/ci.yml:82-92` invokes `gitleaks/gitleaks-action@v3` with no `GITLEAKS_LICENSE`
environment entry and no `token:` input, and `:86-87` is the only place it appears. gitleaks-action v3
is a paid-feature-gated action that reads `GITLEAKS_LICENSE`, and without a token it rate-limits on
public runners; the plausible outcomes are a silently skipped scan or a job that has been failing and
been ignored. **Missing proof:** an Actions run log. §10 of this document already credits "no tracked
secrets" on the strength of direct reading, so a dead scanner is a defence-in-depth gap, not a
statement that secrets exist.
*Pointer:* open the last 20 runs of that job; if it is red or skipped, add `token: ${{ secrets.GITHUB_TOKEN
}}` and a license, or replace the step with the `gitleaks/gitleaks` Docker image action, which needs
neither.

**F177 — Low — three documents still describe v0.0.1.** `AGENTS.md:1` is headed
"ifinmail 0.0.1 — Backend App Architecture" while `CHANGELOG.md:3` is at v0.0.75;
`docs/enterprise-next-steps.md:3` and `docs/enterprise-readiness-proposal.md:3` each assert that
"v0.0.1 is the last release" / "10 commits on main at v0.0.1", when 74 tags and the §2 history exist.
The first is the file that steers every agent session, so its structural rules are trusted even when
its version header is stale; the other two are proposals that have become misleading.
*Pointer:* drop the version from `AGENTS.md`'s heading and archive the two proposals.

**F178 — Low — the plugin skill's counts no longer match the registry.**
`.agents/skills/ifinmail-plugins/SKILL.md:30` says "Capabilities (the contract, 14)" and names five of
the seven adapter targets; `backend/apps/mail/services/plugin_points.py` now contains 26 `_Capability(`
construction sites (measured) and `:464-472` lists all seven `TARGETS`. A manifest author who trusts
"14" will conclude a capability they need does not exist and will add a duplicate instead of binding
to the registered one — the failure mode the skill's checklist at `:3` is written to avoid.
*Pointer:* state the count as "see `_capabilities()`", or generate the table from the registry.

**F179 — Low — the milestones document lists deliverables that were never committed.**
`docs/REMEDIATION-MILESTONES.md:116,543,621` name `docs/INTERNAL-SYSTEMS-MAP.md` and
`docs/FRONTEND-UI-UX-TEST-PLAN.md` as produced. Neither file exists in the tree or in history
(delegate `git log` check). A reader planning work from that document will look for a systems map that
is not there.
*Pointer:* mark them as not started, or write the systems map from §9.8's container inventory, which
is nearly the content anyway.

**F180 — Low — this assessment itself is untracked.** `docs/assessment-2026-11-04.md` (>2,000 lines now)
is not in `git ls-files`, which is how §2 left it deliberately — the document was produced in a session
that pushed only what was asked. It should be either committed or ignored explicitly; leaving it
untracked means the next `git add .` sweeps it in without a review, and the memory note about this
project's commit style (one commit per release) argues for a deliberate choice.

**Refuted or declined in this zone.**

* "CI might be `continue-on-error`-decorated": no. `ci.yml` runs
  `check --deploy`, `pytest --cov=backend` with `fail_under=70`, `mypy` strict,
  `ruff check` and `ruff format --check`, `pip_audit`, compose config, gitleaks and shellcheck with no
  `|| true` and no `continue-on-error` on any of them. The green badge means those passed — the problem
  is what they do not cover (F168's version mismatch, F115's skipped `nft` checks), not that failures
  are swallowed.
* Triggers and privilege: `push: main`, `pull_request` (no `pull_request_target`), a weekly cron and
  `workflow_dispatch`; `android-release.yml` is `workflow_dispatch`-only behind
  `environment: android-release` with a `concurrency` group. No privileged-token request anywhere.
  Declined.
* Dependency hygiene beyond the drift: the layering `base → production|development → testing` is clean,
  no `-e`, no `git+`, no `--index-url`, no `--no-deps`; every range in every file is upper-bounded;
  debug-toolbar, pytest, ruff, mypy and pip-tools stay out of `production.txt` and `prod.lock`; and
  `prod.lock` is fully hash-pinned and enforced at `Dockerfile:13-14`. Nothing to report.
* No credential, DSN or production hostname appears in any file in this zone;
  `provisioning/.env.example` values are empty or `example.com`, and `.gitignore`/`.dockerignore` cover
  `.env*` (with `!.env.example`), DKIM keys, certificates, the keystore, APKs, sqlite files, media,
  coverage and logs. §10's "no tracked secrets" holds here too.
* Every Makefile management command and every `provisioning/scripts/*.sh` referenced by the docs exists;
  `test_url_contract.py`, `test_frontend_contract.py` and `test_oceanic_theme.py` exist as claimed;
  every file path cited across the docs and skills resolves except the two in F179; and every
  `--ifinmail-*` token named in `references/tokens.md` is defined in `ifinmail-variables.css`.
* `examples/python/ifinmail_client.py` is accurate: every endpoint it calls resolves in the real API
  (`/inboxes/{a}/wait`, `/marketing/opt-outs`, `/campaigns/{id}/schedule`, `/sandbox/messages`, …), and
  its `verify_webhook` reproduces the server's own scheme (`t=,v1=` over `"<t>.<body>"`,
  `backend/apps/mail/services/webhooks.py:443`).

**COVERAGE STATEMENT.** 74 tracked files in this zone (+ this untracked document). **Read in full:**
both workflows, `Makefile`, `pyproject.toml`, all five `requirements/*.txt` except
`prod.lock`'s hash bodies, `.gitignore`, `.dockerignore`, `provisioning/.env.example`, `AGENTS.md`,
`DESIGN.md`, `SECURITY.md`, the five `SKILL.md` files, the three `.agents` scripts, and six docs
(`android-releases.md`, `enterprise-*.md`, `REMEDIATION-MILESTONES.md`, plus the two examples files).
**Read structurally, not line-by-line:** `requirements/prod.lock` (pin lines grepped, 900+ hash
continuations skipped), `CHANGELOG.md`, `README.md`, `docs/html_templates.md`.
Re-measured by this author: the redis and gunicorn lines on both sides of F166/F167, the absence of any
`package.json`, `find-polluter.sh:35-50`, `ci.yml`'s `uses:`/`permissions:` census, the tag list against
`CHANGELOG.md:3`, and the `_Capability(` count in `plugin_points.py`.
**Explicitly not inspected by this author or the delegate:** `examples/python/01`–`13` (13 files),
`docs/environment.md`, `docs/storage-contract.md`, `docs/dr-runbook.md`,
`docs/strategy-developers-and-agents.md`, `docs/ifinmail_proposal.md`, the four
`references/*.md` files under the design and plugin skills, the nine `systematic-debugging` reference
documents, `README.md`'s body, and the parts of `enterprise-*.md` beyond the cited lines — the
examples/docs/references part is closed by §9.14 and the remainder by §9.15, both of which read those
files in full, so this section's documentation gaps are those two sections' coverage rather than a hole
left in the sweep. No Actions run log or branch-protection setting
was available, so
F176 and the §3 "what actually runs" claims about *observed* CI behaviour stay unproven.

### 9.14 `examples/python`, `docs/` and the skill `references/` — 24 files, all read in full

This chunk exists because §9.13's own coverage statement listed these files as *not inspected*. Every
finding below was re-verified by this author against the file it cites; where the delegate and this
author disagreed, the delegate's claim is recorded as refuted rather than promoted.

**F181 — High — the documented install path, and the documented disaster-recovery path, are the same
unaudited `curl … | sudo bash`.** `README.md:23` and `README.md:32` (non-interactive form) pipe
`https://raw.githubusercontent.com/ifinsta/ifinmail/main/provisioning/scripts/bootstrap.sh` straight into
`sudo bash`, and `docs/dr-runbook.md:47-51` — step 2 of the recovery procedure, i.e. the moment an
operator rebuilding a lost server has the least ability to review code — tells them to run exactly that
with `--non-interactive`. Nothing verifies the bytes: grepping every `*.md` and the `Makefile` for
`bootstrap` alongside `sha256`/`sum`/`verify`/`sign` returns no checksum, no signature and no pinned
commit; `main` is a moving ref, so the script that runs as root is whatever the default branch holds at
that second. The URL's org matches the real remote (`git remote -v` →
`git@github.com:ifinsta/ifinmail.git`) and the transport is TLS, so this is not a spoofing hole in the
documented text — it is the absence of a second gate on a root-privileged, self-updating installer.
*Pointer:* publish a checksum or a tagged script URL (`…/v0.0.2/provisioning/scripts/bootstrap.sh`),
have both docs fetch that checksum first, and make `bootstrap.sh` refuse to run on a mismatch; the
DR runbook should install from a release tag, which it already knows how to pin
(`sudo make update TO=<that release>` at `dr-runbook.md:52`).

**F182 — High — `docs/ifinmail_proposal.md` describes the repository in the present tense and gets both
its structure and its licence wrong.** §19 "Project Structure" (`:866-937`) claims
`backend/apps/core/{accounts,mailboxes,audit,messages,reputation}`, `backend/apps/admin/billing`, a root
`scripts/`, `static/`, `templates/`, `guide/`, `pytest.ini`, `mypy.ini` and `.env.development`; `ls
backend/apps` gives `accounts core devices dns domains mail mydoc`, `ls -d scripts` fails, and none of
`guide/ pytest.ini mypy.ini .env.development` exist at the root. §18.3 (`:862`) then states "ifinmail is
proprietary software. Source code is not publicly distributed. All rights reserved by Eleso Solution"
against `README.md:847-849` ("## License / MIT") — and the doc itself is served from the public raw URL
that F181 depends on, so the licence sentence is contradicted by the very distribution channel the
project relies on. A new engineer or a reviewer doing due diligence reads §19 as current state and
builds against paths that do not exist; a procurement or compliance reader takes §18.3 as the licence.
*Pointer:* mark the document explicitly as the pre-0.0.1 design proposal (date it, add a banner pointing
at `AGENTS.md`), or delete §19 and rewrite §18.3. Do not "fix" §19 by editing it to match the tree — it
is a historical artefact and the fix is to label it as one.

**F183 — Med — the proposal's Phase-1 deliverables are things the README explicitly says do not exist.**
`docs/ifinmail_proposal.md:37` lists "Webmail" as a core goal, `:756` makes "simple webmail interface
with server-rendered HTML" a Phase-1 item and `:947` repeats it in the timeline table, while
`README.md:751` states "There is no webmail. Mailbox owners use an email app (IMAP 993, SMTP 587)".
§10.2 (`:553-567`) and `:975` promise a Rust core for parsing, crypto, sync and policy; there is not one
`.rs` file outside `venv/`. §10.2 is at least phrased as "should be used", so only §19 and §18.3 assert
false facts — this is the residue that matters for anyone planning work from the proposal.
*Pointer:* one line at the top of the proposal: what shipped differs; the authoritative list is
`README.md` and `AGENTS.md`.

**F184 — Med — the mailbox example documents a passphrase in `argv`, and the flag exists.**
`examples/python/03_mailboxes.py:5` shows `python 03_mailboxes.py create ana@example.com --password
'a long passphrase'`, backed by the real flag at `:26` (`create.add_argument('--password')`). Anything on
a command line is readable by any local process via `ps`, lands in shell history, and is captured by the
sort of exec auditing this product sells to enterprise customers. The repo's own standard is the opposite
for the same class of secret: `provisioning/scripts/backup_offsite.sh:242` requires a *passphrase file*
(`[ -f "${2:-}" ] || die "usage: … verify-key <key.asc> <passphrase-file>"`). `04_bulk_provision.py`
provides the CSV path that `:4` already shows as the invited flow, so the credential-in-argv form is the
documented shortcut nobody needs. No example anywhere uses `getpass` — grepping
`--password|getpass|passphrase-file` across `examples/python/*.py` returns only these two hits.
*Pointer:* keep `--password` but change the docstring to `--password-file -` / `getpass` prompting, and
say which is safe.

**F185 — Med — the webhook receiver contradicts its own instruction: cleartext on every interface.**
`examples/python/09_webhook_receiver.py:4` tells the reader to "Run it behind your HTTPS proxy", and `:68`
then binds `HTTPServer(('0.0.0.0', args.port), Receiver)`. The signature check itself is correct
(`verify_webhook` over `IFINMAIL_WEBHOOK_SECRET`, `:63-65`, and the scheme matches
`mail/services/webhooks.py:443`), so the exposure is the plaintext event body — which carries recipient
addresses — crossing the network between the proxy and the receiver, and any local process or container on
the host reaching `:8080` directly, bypassing the proxy the comment assumes. For an example whose purpose
is to teach the correct receiver shape, the shape taught is wrong.
*Pointer:* bind `127.0.0.1` by default with a `--host` flag, or show the `ssl.wrap_socket` /
proxy-required note in the code rather than only in the docstring.

**F186 — Med — the plugin edge-case ledger grew by seven rows and nothing recomputed: the count is wrong
in three places, and seven `CT` citations point at a file that does not prove them.**
`.agents/skills/ifinmail-plugins/references/edge-cases.md:1` is titled "Edge cases (331)" and `:22`
asserts "270 tested, 21 verified live only, 36 code, 4 decision (331 numbered, contiguous)" — that
arithmetic is self-consistent but stale: `grep -cE "^\| [0-9]+ \|"` returns **338**, rows 332–338 being
the website-pages block at `:430-453`. `README.md:247` repeats the stale figure to end users ("the 331
handled edge cases"). Separately, the legend at `:7` binds the proof code `CT` to
`backend/apps/mail/tests/test_containment.py`, and rows 332–338 are all marked `CT` — but
`grep -ciE "website|site_page" backend/apps/mail/tests/test_containment.py` is **0**.
*Pointer:* recompute the tally from the rows rather than maintaining it by hand, and add a `W` code for
the website test file.

**F187 — Med — `manifest.md`, the document plugin authors are told to read, understates the in-process
targets and omits the one capability that can move every stored byte.**
`:118` states "A target with `in_process = True` (only `console.assistant` and `console.containment`
today) has no file and is always 'applied'… Secret fields may only be bound to such targets". There are
**five** such targets: `core/assistant/assistant_handlers.py:57`, `mail/services/plugin_points.py:236`
(`console.containment`), `:348` (`console.developer`), `core/website/website_handlers.py:61`
(`console.website`) and `core/storage/plugin_contract.py:108` (`console.storage`) — and the restriction the
sentence describes is real and enforced at `core/plugins/services/registry.py:191`
(`if spec.secret and not target.in_process`). So an author who trusts `:118` concludes a secret-bearing
setting is impossible outside two targets. Worse, `:72` says the contract is "Defined in
`backend/apps/mail/services/plugin_points.py` (`_capabilities()`)" although `assistant.model`
(`assistant_handlers.py:66,213`), `website.pages` (`website_handlers.py:86,118`) and `storage.objects`
(`plugin_contract.py:112,137`) register themselves in their own apps; and the capability table
(27 rows) has **no `storage.objects` row at all** — grepping `storage` in `manifest.md` returns nothing.
That is the capability that chooses whether media lives on the local disk or an external bucket, i.e. the
one a reviewer most needs to see documented, and it is invisible in the authoring guide while the code
offers it.
*Pointer:* generate the contract table and the in-process list from the registry, the same way F178
proposed for the capability count; a hand-maintained list of a growing registry is how F178, F186 and
this finding all happened.

**F188 — Low — `manifest.md:28` mis-states a validation rule.** The inline comment says
`max_length (text, 1-500, default 200)`, but `core/plugins/services/manifest.py:317-324` accepts
`max_length` for `base in ('text', 'secret')` and the failure message says so verbatim ("only text and
secret settings take max_length (1-500)"). An author who hides an API key in a `secret` setting and adds
`max_length` will be told by the validator that it is allowed and by the skill that it is not.

**F189 — Med — the README's recovery instruction points at a path that does not exist.**
`README.md:538-540`: "To rehearse a recovery without touching the server: `scripts/backup_offsite.sh
verify-key <key.asc> <passphrase-file>`". There is no root `scripts/` directory (`ls -d scripts` →
"No such file or directory"); the real file is `provisioning/scripts/backup_offsite.sh`, and
`docs/dr-runbook.md:71-72` cites it correctly. This is on the key-backup rehearsal path — the step that
proves an operator can still open their backups — so the failure mode is a wrong path exactly where
confidence matters. Same class as F173's stale-path defect and F179's phantom deliverables.

**F190 — Low — `README.md:566-568` mis-counts the examples and over-describes one field comment.**
"eight runnable examples" against thirteen numbered scripts plus the shared client
(`ls examples/python/*.py` → `01_hello` … `13_templates`, 13 files). And
`ifinmail_client.py:33` reads `PAGE_SIZE = 100  # the largest page the server returns`, while
`backend/config/settings/base.py:378-379` sets `NINJA_PAGINATION_PER_PAGE = 50` and
`NINJA_PAGINATION_MAX_LIMIT = 200` — 100 is neither the default nor the ceiling, so the comment teaches a
reader that a page of 100 is the server's maximum when the API would have allowed 200. Functional effect
is nil (double the round-trips at worst); the cost is a false statement inside a client that §9.13 shows
is exercised by `backend/apps/accounts/tests/test_python_examples.py`.

**F191 — Med (unproven) — `docs/storage-contract.md` records a two-implementation verification that no
artefact in the repo can re-run.** `:64-66` explains that "MinIO stopped publishing community images in
2025, so the driver is verified against two independent S3 implementations instead: **Garage** and
**SeaweedFS** (test-only containers, never shipped)", and `:149-152` claims, under "Verification (v0.0.40)",
"Driver, against Garage v1.0.1 and SeaweedFS 3.80 (18 checks each): put/get/head/exists, a 40 MB
multipart upload, …". Searching every non-markdown tracked file for `garage` or `seaweed` finds nothing
(only false positives inside `venv/` and a merged `classes.dex`), and `core/storage/tests/` holds
`test_sigv4.py`, `test_storage_contract.py`, `test_services.py` and `memory_store.py` — i.e. the contract
is tested in CI against an in-repo fake, not against a second implementation. The claim may well have
been true once, in v0.0.40, by hand; what is missing is any way to re-establish it, which is exactly the
property §10 credits the SigV4 tests for. **SUSPECTED**: this author can prove the absence of the harness,
not that the run never happened.
*Pointer:* a compose file plus one skipped-by-default test job (`make verify-s3-driver DRIVER=garage`), or
say "verified manually against Garage/SeaweedFS at v0.0.40; not re-run since" where it is written as
current proof.

**Refuted or declined in this zone.**

* The delegate filed rows 332–338 of `edge-cases.md` as a **High** on the basis that "CT with no backing
  test" meant the behaviour was unproven. REFUTED as a High. The tests exist and are named:
  `backend/apps/core/website/tests/test_website.py` has 30 of them, and seven map one-to-one —
  `:27 test_without_the_plugin_everything_is_as_shipped` (332), `:119 test_a_page_that_is_off_is_gone_everywhere`
  (333), `:165 test_custom_with_no_text_shows_the_standard_page` (334), `:188 test_custom_text_is_escaped_in_every_field`
  (335), `:288 test_a_public_request_reads_the_policy_from_the_cache` + `:302 test_a_flushed_cache_is_rebuilt_from_the_plugin`
  (336), `:46 test_menus_follow_the_pages_that_are_on` / `:52 test_project_links_can_be_hidden` (337),
  `:199 test_preview_needs_a_signed_in_administrator` (338). The defect is the citation column, not the
  proof: F186 keeps it at Med.
* "`03_mailboxes.py` leaks passwords" as a High would have been an overstatement — the flag is optional,
  the invited flow at `:4` sets no password at all, and nothing in the example writes the value to disk.
  F184 is Med because of *what is documented*, not because the code is unsafe.
* "`docs/environment.md`'s provisioning→runtime mapping is wrong" — the delegate checked it line-by-line
  against `provisioning/docker/docker-compose.yml:368-380,451-462` and reported it accurate; this author
  spot-checked the same ranges and found no discrepancy. Nothing to report.
* "`state-machines.md` drifts from the code" — it matches `core/plugins/types/__init__.py:18-29,89-100`
  exactly. Nothing to report, and worth saying because it is the one reference file in this zone that a
  mechanical comparison can fully prove.
* "The proposal is misleading because it is aspirational" is not a finding — §10.2 says "should be used"
  and reads as a plan. Only the present-tense §19 and §18.3 were promoted (F182).
* The examples' API surface is honest: every endpoint path and verb the examples call, and every JSON
  field they read, resolves against the real serializers and routers, and every scope string matches a
  `@require_scope` decorator. The delegate's cross-check found no drift, and
  `test_python_examples.py:1` / `test_python_examples_marketing.py:1` confirm README's "they run against
  the real API in the test suite" — unlike the claims in F179, that one is true.
* `docs/dr-runbook.md:6-10` declares itself unverified and lists its own gaps at `:132-138`, which is the
  discipline §11 asks the rest of the documentation to copy. Its only defect is the one it did *not*
  make (F189 is the README's path error, not the runbook's).

**What this zone got right.**

* `ifinmail_client.py:649-666` reproduces the server's webhook scheme exactly (`t=,v1=` over
  `"<t>.<body>"`, `mail/services/webhooks.py:439-443,66`), including the 10-second window the receiver
  docstring promises.
* The client library's error surface is real rather than decorative: `IfinmailError` carries `status`
  (0 when there was no answer), `detail` is the server's own message, `RETRY_STATUSES` at `:34` is
  `(502, 503, 504)` with the reason in the comment, and `Retry-After` handling exists — the same honesty
  the design system asks of the console.
* `docs/environment.md` documents the container-to-runtime mapping at the granularity someone needs when
  a variable does not appear where they expect it, and it is correct against the compose file.
* `examples/python/09_webhook_receiver.py:19` (`SEEN: set[str]  # use your database in a real
  application`) and `:8-9` ("retries carry the same X-Ifinmail-Event-Id, so they are skipped") tell the
  reader where the example is a toy — the pattern F147's stub apps should copy.

**COVERAGE STATEMENT.** 24 files assigned and **all 24 read in full** by the zone delegate
(`examples/python/01`–`13`, `examples/python/ifinmail_client.py` 698 lines, `README.md` 849 lines,
`docs/ifinmail_proposal.md` 981 lines, `docs/environment.md`, `docs/storage-contract.md`,
`docs/dr-runbook.md`, `docs/strategy-developers-and-agents.md`, and the four `references/*.md` under the
design and plugin skills). This author then re-verified, by direct read or mechanical count, every finding
above and both refutations: `README.md:18-40,243-250,535-545,560-572,749-753,840-849`;
`docs/dr-runbook.md:40-60,68-76`; `docs/ifinmail_proposal.md:1-32,551-568,855-890`;
`docs/storage-contract.md:60-70,145-152`; `examples/python/03_mailboxes.py:1-20`,
`09_webhook_receiver.py:1-20,55-75`, `ifinmail_client.py:28-40`; `edge-cases.md:1-30,428-455` plus its
row count; `manifest.md:24-32,68-76,112-124` plus a capability-row count and a `storage` grep;
`provisioning/scripts/backup_offsite.sh:236-248`; `backend/config/settings/base.py:374-382`;
`core/plugins/services/manifest.py:313-328` and `registry.py:78,96,104,164,191`; all five `in_process`
targets; and `core/website/tests/test_website.py`'s 30 test names.
**Explicitly not inspected in this section:** `README.md`'s remaining numeric claims (audit retention,
assistant token caps, Celery time limits, log caps, connection rates, snapshot counts, its `make` targets
and its architecture port table), `examples/python/README.md`,
`.agents/skills/ifinmail-design-system/references/patterns.md`,
`.agents/skills/ifinmail-template-builder/SKILL.md`, the nine `systematic-debugging` reference documents,
`docs/development.md`, `docs/risk-register.md`, `docs/secrets-map.md`, `docs/html_templates.md`,
`docs/enterprise-evidence/README.md`, `docs/enterprise-next-steps.md`, `docs/enterprise-slo.md` and
`docs/enterprise-readiness-proposal.md` in full (the four `enterprise-*` files were read only where §9.13
cited them). Every one of those files is read in full in §9.15 below, which closes the deferred set; this
section on its own does not cover every document in the repository. The Rust/OpenDKIM/OpenDMARC stack items
in proposal §10 were checked only for file absence, not for functional equivalence.

### 9.15 The large unclaimed remainder — `provisioning/` outside `docker/`, the vendored `mydoc` app, and the documentation/skill residue (70 files)

This chunk exists because §9.13's and §9.14's own coverage statements named these files as *not
inspected*. Twenty-one tracked files live under `provisioning/` outside `provisioning/docker/`,
twenty-five make up `backend/apps/mydoc`, and the remaining twenty-four are the documents and skill
references the earlier sections deferred. Every finding below was re-verified by this author against
the line it cites; four delegate claims and one of this author's own citations are recorded as refuted
rather than promoted. Four files that none of the earlier statements had claimed — the three `.txt`
templates under `frontend/templates/admin/` and `logs/.gitkeep` — were found only when the totals were
recounted, and are swept in §9.16; nothing in this section's 70 depends on them.

The headline of this zone is not a style problem. The backup path — the thing `docs/dr-runbook.md`
exists because of, the thing `enterprise-slo.md` sets an RPO against — does not back up mail, cannot
be run the way the runbook tells an operator to run it, reports success when it verified nothing, and
its weekly proof test can never pass.

**F192 — High — the daily backup silently contains no mail: the volume name it looks for is a name
this stack never creates.** `provisioning/scripts/backup_full.sh:57` guards the entire mail step with
`if docker volume ls --format '{{.Name}}' | grep -q 'ifinmail_mail_data'; then` and the `if` has no
`else`, so when the name is absent step `[2/7] Backing up mail storage...` prints its heading and
copies nothing. `provisioning/docker/docker-compose.yml:568` declares the volume as `mail_data`
(mounted at `:84`, `:134`, `:409`, `:490`), and nothing in the repository ever sets `COMPOSE_PROJECT_NAME`
— `grep -rn COMPOSE_PROJECT_NAME` across the scripts, `Makefile` and the compose files returns only
fallback reads of the form `${COMPOSE_PROJECT_NAME:-docker}` (`backup_full.sh:91,102,130-132,212`,
`docker_clean.sh:24`, `uninstall.sh:21`), and Compose derives the project from the directory name, so
the volume on a default install is `docker_mail_data`. The script knows how to handle this: every
*other* volume it copies tries three candidates, e.g. `:91`
`for volume in ifinmail_dns_data docker_dns_data "${COMPOSE_PROJECT_NAME:-docker}_dns_data"`, and
`:130-132` use a `copy_volume` helper with the same fallback list. Only the mail copy — the one holding
every user's messages — is written as a single hard-coded name with no fallback and no failure path.
The MANIFEST built at `:163-171` claims `Mail storage (/var/mail/vhosts)` regardless, and
`docs/dr-runbook.md:28` lists "All mailboxes … the mail itself" among what a backup holds.
*Pointer:* use the `copy_volume` fallback list for mail as for the other volumes, make the absence of a
mail volume a `notify_failure` rather than silence, and add a contract test asserting every named volume
in `backup_full.sh` exists in `docker-compose.yml`.

**F193 — High — `make backup`, the command the disaster-recovery runbook tells the operator to run,
fails at step 1 on a fresh install.** `backup_full.sh:42` and `:50` invoke
`docker compose -f "$COMPOSE_FILE"` with no `--env-file` and the script never sources
`provisioning/.env` (its only `.env` touch is `:72-73`, copying it *into* the archive). Every other
caller in the repo passes the file explicitly — `Makefile:93`
`DOCKER_COMPOSE = $(COMPOSE_BIN) --env-file provisioning/.env -f provisioning/docker/docker-compose.yml`,
`bootstrap.sh:158`, `obtain-ssl.sh:10` — because the variables live one directory above the compose
file, and no tool ever creates `provisioning/docker/.env`. So `${POSTGRES_ADMIN_PASSWORD:?run make
provision first}` (`docker-compose.yml:14`) is unset, `pg_dump` never runs, and `:44-46`
`notify_failure "PostgreSQL dump failed"` → `exit 1`. It works from cron only because the installed
line sources the file first (`provision.sh:493`
`set -a && . provisioning/.env && set +a && BACKUP_ENCRYPT=true make backup`). The operator who follows
the runbook is told the opposite: `docs/dr-runbook.md:114` lists `sudo make backup` as the check for
"Backups resume", expected to complete. A manual backup on a machine whose shell lacks those exports is
therefore impossible without reading `provision.sh` to discover the trick.
*Pointer:* source `provisioning/.env` at the top of `backup_full.sh` the way `backup_offsite.sh:28-33`
does, or use `Makefile:93`'s `$(DOCKER_COMPOSE)` form, and say so in the runbook step.

**F194 — High — "Backups are encrypted with GPG" is false unless the operator overrides a default that
is off, and when encryption cannot happen the script warns and continues.** `backup_full.sh:12`
`ENCRYPT=${BACKUP_ENCRYPT:-false}` and `provisioning/.env.example:35` ship `BACKUP_ENCRYPT=false`, so
the shipped configuration produces plaintext. `:183-191` then encrypts only
`if command -v gpg >/dev/null 2>&1 && [ -n "${BACKUP_GPG_RECIPIENT:-}" ]`, and the `else` at `:190`
prints `Warning: gpg not found or BACKUP_GPG_RECIPIENT not set, skipping encryption` and falls through
to `=== Backup complete ===` at `:203` with exit status 0. Against that: `README.md:524` "Backups are
encrypted with GPG and, by default, stay on the same disk as the server", and
`docs/enterprise-slo.md:12` states the RPO as "daily encrypted backup". Worse,
`backend/apps/accounts/services/system_health.py:627` asserts "Backups are encrypted" in the console and
`:631-637` grades the key healthy from the presence of a single `backup-key-exported-at` file, without
ever checking that the newest archive ends in `.gpg`. What the plaintext archive contains is not trivial:
`:73` copies all of `provisioning/.env` in, `:81` the DKIM private keys, `:148` `cp -rL` the live TLS
material, and no `umask` or `chmod` is ever applied to `$ARCHIVE_NAME` (the file's only `chmod`s are
`:82`, `:94`, `:105`, `:123`, all on directories *inside* the staging tree), so the archive inherits the
ambient umask — `backup_offsite.sh:223` shows the author knew the pattern.
*Pointer:* default `ENCRYPT=true`, make a missing recipient a `notify_failure` with exit 1 rather than a
warning, `umask 077` before `:179`, and have System health test the newest archive's suffix instead of
asserting.

**F195 — High — `backup_full.sh` reports a successful backup when it could not verify anything, and
records "last successful backup" before it verifies.** `:221-229` reach the only integrity gate: if the
archive is `.gpg`, `gpg --batch --quiet --decrypt --output "$VERIFY_ARCHIVE"` is attempted with no
keyring, recipient or passphrase argument, so in the non-interactive cron environment it fails; the
branch prints `Checksum verification: SKIPPED (encrypted archive could not be decrypted)` and then
`exit 0` at `:229`. Because `=== Backup complete ... ===` was already printed at `:203`, the log for a
backup that has now been provably unreadable reads as a success. `:231` `tar -xzf "$VERIFY_ARCHIVE" … ||
true` discards any extraction error, `:232` `if [ -f "$TMP_VERIFY/SHA256SUMS" ]` has no `else`, so an
archive that yields no manifest prints nothing at all, and `:233-235`'s FAIL branch is only an
`echo` — the file's last statement is `rm -rf "$TMP_VERIFY"` at `:237`, so a `FAIL (some files may have
changed during backup)` backup still exits 0. Order is also wrong: `record_backup_status` is called at
`:217` and writes `last-backup-at` (`:212-216`) *before* verification begins at `:220`, and that is the
very file `system_health.py:564,577` reads to tell the operator when the last good backup ran. There is
no write-time check either — `:179` `tar -czf`, `:195` `rm -rf "$BACKUP_ROOT"` and only then
verification, with retention pruning at `:199` running ahead of the one test that exists.
*Pointer:* verify first, record second, exit non-zero on SKIPPED and FAIL, and add `tar -tzf` right
after the archive is written.

**F196 — High — the weekly restore drill can never pass: it hands the container a host path that is not
mounted.** `restore_test.sh:9` sets `TEST_DIR="/backups/ifinmail_restore_test_$$"` on the host, and
`:107-108` run the real test as
`docker compose exec -T postgres pg_restore -U ifinmail -d ifinmail_restore_test "$TEST_DIR/postgresql/ifinmail.dump"`.
The postgres service mounts exactly three things — `postgres_data:/var/lib/postgresql/data`,
`./init-db.sh:/docker-entrypoint-initdb.d/01-init-db.sh:ro` and
`./postgres/custom.conf:/etc/postgresql/custom.conf` (`docker-compose.yml:20-23`) — and `grep -n
'/backups'` across the compose file finds no mount for any service. So `pg_restore` cannot see the dump,
`:116-118` take the FAIL branch, and `:181-185` print
`=== RESTORE TEST FAILED — INVESTIGATE IMMEDIATELY ===`, call `notify_failure` and `exit 1`. The cron line
installs it as a Sunday job (`provision.sh:494`, output appended to `/var/log/ifinmail-restore-test.log`),
so the mechanism that is supposed to *prove* the RPO either fires a false alarm every week or, once an
operator learns to ignore it, hides a real one. The isolation itself is sound — `:102-105` create and drop
`ifinmail_restore_test` and never touch the live database.
*Pointer:* pipe the dump over stdin (`pg_restore -U ifinmail -d ifinmail_restore_test - < "$file"`), which
`exec -T` already supports, or mount `/backups` read-only into a one-shot container.

**F197 — High — the restore drill counts every skip and warning as a pass, so "Restore test passed" is
reachable with nothing tested.** `:128-129` print `SKIP (PostgreSQL not available or no dump file)` and
then `PASS=$((PASS+1))`; `:139-140` do the same for `WARN (no mail directories — may be empty system)`;
`:148-149` count a config check as passed unconditionally after merely printing
`PASS ($CONFIG_COUNT key files present)`, so three absent files still earn a pass; `:159` and `:173` do it
again for DKIM keys and extended-format parts. The summary at `:180-187` gates only on `[ "$FAIL" -gt 0 ]`,
so a run with zero configs, zero keys and no database restore prints `=== Restore test passed ===` and
exits 0. `:112-113` even print `PASS (0 tables restored)` because the table count is defaulted with
`|| echo "0"`. Two of the script's guards are also unreachable under `set -euo pipefail`: `:38`/`:40`
`ls … | head -1` fail when no archive exists, exiting before the friendly "no backups found" branch at
`:43-47`, and `:133`/`:153` `find "$TEST_DIR/mail" …` abort on a missing directory, which is what makes
the WARN branches at `:138` and `:158` dead code.
*Pointer:* separate `SKIP`/`WARN` counters, require the database restore and the DKIM keys to have been
seen before printing success, and give the unreachable guards a test of their own.

**F198 — High — the drill decrypts the whole backup into `/backups` as plaintext and never removes it,
and the following week it drills the plaintext instead of the encrypted archive.**
`:52-55` set `DECRYPTED="${LATEST%.gpg}"` — that is `/backups/ifinmail_backup_<timestamp>.tar.gz`,
beside the keys — and decrypt the full archive, `.env` included, into it. `:60` then promotes it:
`LATEST="$DECRYPTED"`. `:187` is the script's only cleanup, `rm -rf "$TEST_DIR"`, so the plaintext
survives indefinitely, and `:38` `LATEST=$(ls -t /backups/ifinmail_backup_*.tar.gz … | head -1)` looks
for plaintext archives *first* and takes the newest by mtime — which the decrypted copy always is. From
the second run on, the drill that exists to prove "the archive decrypts" (`docs/dr-runbook.md:7-8`)
decrypts nothing, and `provisioning/scripts/monitor.py:290` reports the plaintext file as the latest
backup. Nothing prunes it either: `backup_full.sh:199` matches `ifinmail_backup_*.tar.gz*` with
`-mtime +$RETENTION_DAYS`, so it ages out only after 30 days, and `uninstall.sh:141`'s patterns miss it.
*Pointer:* decrypt inside `$TEST_DIR` and let the `trap` at `:32` remove it.

**F199 — High — `uninstall.sh --keep-backups` deletes the key that opens them.** `:132-136` run the GPG
removal unconditionally — `gpg --batch --yes --delete-secret-and-public-key "$fpr"` for every fingerprint
matching `BACKUP_GPG_RECIPIENT` — while the archive deletion is gated at
`:140` `if [ "$KEEP_BACKUPS" != 1 ] && [ -d /backups ]`. An operator who chose the documented
`--keep-backups` flag (`:7`) therefore keeps a `/backups` tree of GPG archives whose private key the same
command just destroyed, with no warning printed. The key is not stored anywhere else: the backup keyring
lives in `~/.gnupg`, which is not part of the backup set, and the passphrase lives in the `.env` inside
the archive. *Pointer:* move `:133-136` inside the `KEEP_BACKUPS != 1` branch, or refuse the combination
outright and say why.

**F200 — High — `uninstall.sh --remove-docker` deletes every other tenant's Docker data, contradicting
the script's own header.** `:13-14` promise "Docker itself stays unless `--remove-docker`: other things
on the server may use it", and `:156` is
`grep -qx 'installed docker' "$MANIFEST" && rm -rf /var/lib/docker /var/lib/containerd
/etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc`. Purging the package is what the
header describes; deleting `/var/lib/docker` additionally destroys every image, container and **volume**
belonging to unrelated projects on that host, irreversibly, and the manifest flag only records that this
installer ran `apt-get install docker`, not that nothing else ever used the daemon afterwards. The script
also runs with `set -uo pipefail` (`:16`, no `-e`), so unguarded `docker rm -fv`, `docker volume rm` and
`docker rmi -f` failures are swallowed while `:169-170` print `ifinmail is uninstalled` and `nothing`.
Separately, `:141` `rm -rf /backups/[0-9]*_[0-9]*` is a loose date-shaped glob that will match another
application's `2026_archive`-style directory under `/backups`.
*Pointer:* remove only resources labelled `com.docker.compose.project=$PROJECT` (as `:48-50` already does
for the leftover check), purge the package without touching the data root, and anchor the glob to
`ifinmail_backup_*`.

**F201 — High — `obtain-ssl.sh` destroys a certificate it does not like on a backup it never verifies.**
`:41-46`: if the existing certificate's issuer is anything other than a string containing
`Let's Encrypt`, the script makes a best-effort backup (`cp -a "$LIVE_DIR" "$BACKUP_DIR/" 2>/dev/null ||
true`) and then unconditionally runs
`rm -rf "$LIVE_DIR" "$CERTBOT_CERTS/archive/$MAIL_HOSTNAME" "$CERTBOT_CERTS/renewal/$MAIL_HOSTNAME.conf"`
— the live key, the history and the renewal configuration. Certbot's default ACME CA is not Let's
Encrypt, an internal or purchased certificate matches this condition exactly, and a copy that failed for
any reason produces no error because of the `|| true`. On success `:63` deletes the backup too, and on
failure `:81-87` restore only `live/`, with `cp -a "$BACKUP_DIR/$local_live/"*` (a glob that also skips
dotfiles), never the `archive/` or `renewal/` it removed — so a failed issuance permanently loses the
renewal state of the previous certificate. The tail of the success path is fragile under
`set -euo pipefail` (`:4`): `:65-66` `chmod 755` four paths and `find` a fifth with no guard, *before*
`"${COMPOSE[@]}" restart nginx` at `:74`, so one absent path aborts after the new certificate exists and
nginx keeps serving the deleted one, with the script exiting 1.
*Pointer:* issue into a staging directory and swap only after `openssl x509 -checkend` confirms the new
pair, back up all three paths and restore all three, and reorder the chmods after the reload.

**F202 — High — the repository ships a brute-force protection that does not exist: fail2ban is not
installed anywhere, its jail watches logs this stack never writes, and its filters cannot match the lines
it does write.** `provisioning/fail2ban/jail.local:16`, `:25` and `:34` set
`logpath = /var/log/mail.log` for the postfix, postfix-sasl and dovecot jails and `:43`
`logpath = /var/log/nginx/access.log`. The real destinations are
`/var/log/ifinmail/postfix.log` (`provisioning/docker/postfix/entrypoint.sh:52`
`MAIL_LOG=/var/log/ifinmail/postfix.log`), Dovecot's configured `log_path`
(`provisioning/docker/dovecot/entrypoint.sh:47`) on the `mail_logs` volume, and — for nginx — a JSON
access log, `provisioning/docker/nginx/conf.d/ifinmail.conf:33`
`access_log /var/log/ifinmail/access.json ifinmail_json;`. Even with a corrected path the four filters
cannot fire: `ifinmail-dovecot.conf:5-6` expect `dovecot: auth…: passdb(<user>,<HOST>)… Authentication
failed`, while the line this stack actually produces is
`imap-login: … (auth failed, 4 attempts in 6 secs): user=<bob@…>, method=PLAIN, rip=203.0.113.9`
(`backend/apps/core/tests/test_mail_threats.py:44`, asserted "exactly as real Dovecot wrote it" at `:90`)
— no `dovecot:` prefix, no `passdb(`, and the address as `rip=` rather than bracketed;
`ifinmail-nginx-auth.conf:5` requires the status code immediately after the quoted request, which a
combined-format line never produces because `HTTP/1.1"` intervenes (and this stack does not write
combined format at all), while `:6` is a strict subset of `:5`; `ifinmail-postfix-sasl.conf:4` demands
`postfix/(smtpd|submission|submissions)/smtpd\[\d+\]`, which cannot match a plain port-25 line such as
`postfix/smtpd[40]` (`test_mail_threats.py:58`), and its `:5` anchors `[<HOST>]` onto
`fatal: no SASL authentication mechanisms`, a daemon configuration error that carries no peer address;
`ifinmail-postfix.conf:5` restricts mechanisms to `SASL (LOGIN|PLAIN)`. And nothing deploys any of it:
`jail.local:2` is only a comment saying "Deploy to /etc/fail2ban/jail.local", and a repo-wide grep for
`fail2ban` across every `*.sh`, the `Makefile`, every `*.yml` and every `Dockerfile` returns nothing —
the five files in `provisioning/fail2ban/` plus one stale comment at
`provisioning/docker/dovecot/dovecot.conf:17`. `jail.local:8-9` would also write
`banaction = iptables-multiport` into `chain = DOCKER-USER`, the same chain `firewall.sh:63-66` edits,
while the product's actual guard is the nftables `firewall` container (`docker-compose.yml:294-316`,
driven by `core/platform/services/entrypoints.py`); `:10` additionally puts `172.16.0.0/12` in `ignoreip`,
which is the Docker network range this stack lives on.
*Pointer:* either deploy fail2ban (add it to `cloud-init.yaml:16-22`, mount the log volumes, write the
filters against the `test_mail_threats.py` fixtures so they stay matched to reality) or delete the
directory; a security control that exists as an unrunnable file tree is worse than none, because it
reads like coverage.

**F203 — High — `make firewall` tears down the host firewall before it asks permission, and its Docker
guard is neither verified nor persistent.** `provisioning/scripts/firewall.sh:14-15` print
`Resetting firewall to defaults...` and run `ufw --force reset >/dev/null` at the top of the script,
while the only confirmation is at `:78` `read -rp "Enable firewall now? [y/N] "` — after every rule has
already been deleted. Under `set -euo pipefail` (`:4`), a non-interactive run reaches `:78` with EOF, and
`read` returns non-zero, so the script aborts at the *last* statement: the firewall is now reset with
nothing re-added and no `ufw enable`. The Docker guard that follows is reported rather than checked:
`:60` derives `PUBLIC_IFACE="$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'dev \K\S+' || echo eth0)"`,
`:63-66` insert three `iptables -I DOCKER-USER` rules each terminated with `2>/dev/null || true` (so a
missing `DOCKER-USER` chain, absent `iptables`, or wrong interface changes nothing), and `:67` then
prints `Docker-proxied ports on $PUBLIC_IFACE: only mail/web ports allowed.` whether or not a single rule
landed — rule 3 at `:66` is a blanket `-i "$PUBLIC_IFACE" -p tcp -j DROP`, so an operator who believes
that line and later reboots (the rules are not persisted; `:68-69` only *mention*
`iptables-save > /etc/iptables/rules.v4` as a hint) is left with the DROP gone and the ufw state
whatever `:78` decided. This is a second, host-level firewall sitting alongside the product's own:
`docker-compose.yml:294-316` runs a `firewall` service with `network_mode: host` and `NET_ADMIN` that
manages an nftables `table inet ifinmail` from `entrypoints.py`'s ten-entry `CATALOGUE` (`:93-174`), and
the console can switch a port off there. `Makefile:185-186` wires the script as `make firewall` and
`README.md:766` advertises it as "Configure ufw firewall rules", with nothing in either document saying
which layer wins.
*Pointer:* move the reset behind the confirmation, `command -v`/exit-status check each insert and report
per rule, persist with `netfilter-persistent` in the script, and state the relationship to the `firewall`
container in the README section.

**F204 — High — `monitor.py` is a phantom: nothing runs it, nothing reads what it writes, and
`docs/enterprise-slo.md` already treats its thresholds as the standard.** Its own header claims a
schedule that does not exist — `provisioning/scripts/monitor.py:4` "Runs as a cron job every 5 minutes.
Pushes metrics to Redis for the API to read." — but `grep -rn 'monitor\.py'` across every shell script,
the `Makefile`, every `*.yml`, `Dockerfile` and Python file finds no invocation of any kind: the cron file
`provision.sh:488-497` installs exactly three jobs (backup, restore drill, docker clean), and the only
non-document hits are the unrelated `examples/python/07_monitor.py`. Its output has no consumer either:
the script writes `ifinmail:monitor:latest` and `history` (`:430-432`), and the only readers of those keys
are `core/platform/services/monitoring.py:28` `get_latest_report()` and `:38` `get_service_status()`,
whose sole caller is each other (`:39`); the dashboard's identically-named
`accounts/views/dashboard.py:175` `_get_service_status()` is a different local function that re-probes the
database, cache and TLS itself and is what `:313` actually uses. Meanwhile `docs/enterprise-slo.md:12`
quotes "backup age > 25h = CRITICAL (`monitor.py`)" and `:17` "Queue depth (`monitor.py`) | > 50 WARN,
> 200 CRITICAL" as if the file were the measuring instrument, and `REMEDIATION-MILESTONES.md:382` still
lists "Ingest monitor.py output from Redis or direct service" as unfinished. The three generator scripts
contribute to the illusion by writing its tuning knobs into every `.env`
(`provision.sh:175`, `bootstrap.sh:247`, `setup-wizard.sh:204`) for a consumer that never runs — see
F222 for the same pattern with a variable that has no writer at all. `docs/REMEDIATION-MILESTONES.md` is
also the only place that admits the writer may not exist: `monitor.py:243` uses `psutil`, and `psutil`
appears in no `requirements/*.txt`, so that branch silently falls back to `/proc` at `:258`.
*Pointer:* schedule it (a beat entry or the existing cron file), or delete it and re-point
`enterprise-slo.md` at `system_health.py`, which is what the console actually measures with.

**F205 — Med — secrets are passed on the command line, and one passphrase is written to a predictable
temporary file.** `restore_test.sh:55` runs
`gpg --yes --pinentry-mode=loopback --passphrase "$GPG_PASSPHRASE" --decrypt …`, putting the backup
passphrase into `argv`, world-readable through `/proc/<pid>/cmdline` for the life of the process;
`provision.sh:330` does the same. `provision.sh:317-328` is worse — it writes a batch file containing the
literal line `Passphrase: <value>` to `/tmp/gpg-batch.txt`, a predictable path, and never `chmod`s it
(the script's only `chmod`s are at `:260`, `:264-266`, `:294-295`, none of which cover `$ENV_FILE`, and
`:295` sets DKIM keys to `644`). The correct pattern is already in this repository:
`backup_offsite.sh:207` uses `--passphrase-file`, and `capacity_probe.py:83` reads the SMTP password from
a file rather than `argv`. `monitor.py:349-350` also passes `ALERT_WEBHOOK` — a URL whose path is
commonly the credential — as a `curl` argument.
*Pointer:* `--passphrase-file` with a mode-600 descriptor everywhere, `mktemp -d` plus cleanup for the
batch file, and pass the webhook URL through the environment.

**F206 — Med — `setup-wizard.sh` copies every secret world-readable, prints the generated admin
password, and reads two more secrets in the clear.** `:61`
`cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"` runs while the shell still has the ambient umask;
the file's only `umask 077` is at `:150`, immediately before `cat > "$ENV_FILE"` at `:151`, and nothing
ever `chmod`s the `.bak` (the only `umask`/`chmod` matches in the file are `:150`). On a default host the
result is a 0644 copy of the entire secret set sitting next to a 0600 original — and each re-run of the
wizard adds another. `:237` then prints `echo "  Admin password: $DJANGO_SUPERUSER_PASSWORD"`, followed by
`Save the admin password above`, into a terminal that in this product's own documented flows is a
redirect: `provision.sh:493-496` append scheduled jobs to `/var/log/ifinmail-*.log`, and `bootstrap.sh:138`
runs the wizard as `bash "$INSTALL_DIR/provisioning/scripts/setup-wizard.sh" < /dev/tty`, which makes the
*reads* interactive but not the writes. `:104-105` read the Sentry DSN — which embeds a key — and the
alert webhook URL with plain `read -rp`, so both appear on screen as typed.
*Pointer:* `umask 077` at the top, `install -m 600` for the `.bak`, `read -rs` for the two secrets, and
point at `$ENV_FILE` instead of echoing the admin password.

**F207 — Med — `docker_clean.sh`'s `--dry-run` shows nothing for the destructive steps, and the script
removes more than its own comment promises.** `:42` defines
`run() { if [ "$DRY" = 1 ]; then echo "  would run: $*"; else "$@"; fi; }`, but every caller redirects the
whole function call — `:50` `run docker image prune -f >/dev/null`, and likewise `:62`, `:66`, `:70`, `:72`,
`:74` — so in dry-run mode the `echo` itself is discarded and the operator sees only the two `say` lines.
The script runs `set -uo pipefail` (`:22`, deliberately without `-e`), and `:82` prints
`Docker clean-up done` whether or not any prune succeeded. Its header at `:19-21` states "Never removed:
volumes … and anything Docker holds for **other projects** on this server", yet `:50` `docker image prune
-f` and `:70`/`:72`/`:74` `docker builder prune -af` are host-wide; only `:66` is scoped with
`--filter "label=com.docker.compose.project=$PROJECT"`. Build cache on a shared host belongs to every
project on it. `:44`
`disk_used() { df -P /var/lib/docker 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $5}'; }` returns
nothing when the data root is elsewhere, so `[ "${before:-0}" -ge "$DISK_PERCENT" ]` at `:69` can never be
true and the emergency cache-emptying it documents will not fire on a full disk — and `:82` then prints
`disk ?% -> % used`.
*Pointer:* move the `>/dev/null` inside `run()`'s `else`, use `docker info --format
'{{.DockerRootDir}}'` for the disk probe, scope the image prune to the stack's own references, and exit
non-zero when a prune reports failure.

**F208 — Med — when `monitor.py` does get run, its verdict drops backups and disk, its API probe is the
only one in the repo without a Host header, and it hides its own failures.** `:395-404` assemble a report
with eight sections, and `:408-416` build `statuses` from only four of them: the queue, `services`,
`api_health` and `certificates`. `check_backup_freshness` returns `'status': 'CRITICAL'` at `:301-306` and
`report['disk']`, `report['system']` and `report['delivery_rate']` are computed at `:402-403` — none can
raise `overall`, so a missing or stale backup never alerts, which is precisely the SLO the same document
attributes to this script (`enterprise-slo.md:12`). `:416`
`cert_status = report.get('certificates', {}).get('status', 'OK')` defaults to `OK` when the check returned
an error dictionary, and `:20` `MAIL_HOSTNAME = os.environ.get('MAIL_HOSTNAME', '')` means the certificate
path at `:21` is `…/live/` out of the box. The API probe at `:189` is
`['curl', '-fsS', '-m', '5', 'http://localhost:8000/health/']` with no Host header, while both real
probers in this stack send one deliberately — `docker-compose.yml:438` builds the request from
`ALLOWED_HOSTS`, and `:558` passes `--header="Host: $MAIL_HOSTNAME"` — so its verdict depends on
`localhost` being in `ALLOWED_HOSTS`, and `:199` turns any non-zero curl status into
`{'status': 'unreachable'}` which then propagates to a WARN or CRITICAL. Finally `:433-434` wrap all three
Redis writes in `except Exception: pass`, `:354-355` and `:377-378` swallow alert-send failures, and
`:389-390` the state write: a monitor that cannot store metrics and cannot deliver an alert still exits 0.
*Pointer:* fold `backups` and `disk` into `statuses`, default an absent status to `UNKNOWN`, send a Host
header, and log swallowed failures.

**F209 — Med — four different certificate-expiry thresholds exist for the same certificate, and the SLO
documents only one of them.** `backend/apps/core/platform/services/tls.py:42` declares
`_WARN_DAYS, _ERR_DAYS = 30, 7` and grades with it at `:87`, which is what the console and System health
show. `backend/apps/core/tasks.py:17-18` declares `_WARN_DAYS = 21` and `_EMAIL_DAYS = 14`, used at `:33`
and `:40` by the daily `check-certificate-expiry` beat job — so a certificate 25 days out is a warning in
`tls.py` and not a warning in `tasks.py`, and the operator sees the console flag it while no email is sent.
`provisioning/scripts/monitor.py:220-221` is a third implementation at 30/7, and
`provisioning/.env.example:40-41` expose a fourth as tunables (`MONITOR_CERT_WARN_DAYS=30`,
`MONITOR_CERT_CRITICAL_DAYS=7`). `docs/enterprise-slo.md:14` states the rule as "< 30d WARN, < 7d
CRITICAL", which is true of two of the four and silently wrong about the job that actually notifies.
*Pointer:* move the thresholds to one module, have `tasks.py`, `tls.py` and any monitor read it, and cite
that file in the SLO row.

**F210 — Med — the off-site copy calls a self-attested hash "verified", and local and off-site retention
can expire together.** `provisioning/scripts/backup_offsite.sh:87-92` compares the local `sha256sum`
against a digest returned by the uploader itself — `backend/apps/core/storage/drivers/s3.py:269,309` hash
the *outgoing* stream — so the check confirms what the writer computed, not what the store holds; there is
no read-back, yet `:96` prints `verified in object storage`. The SSH branch is honest by contrast:
`:121-134` upload to a partial file, `mv` into place and run a remote `sha256sum`. There is no retry logic
in either path, and `:109`/`:111` set `StrictHostKeyChecking=accept-new`, which is trust-on-first-use on a
path that carries encrypted mail. Retention then diverges by suffix: the local sweep matches
`ifinmail_backup_*.tar.gz*` (`backup_full.sh:199`) while the remote sweep matches `ifinmail_backup_*.gpg`
(`:170`), both at the same 30 days (`enterprise-slo.md:25`), so the last local and last off-site copy can
disappear in the same week. `:67` hardcodes `${COMPOSE_PROJECT_NAME:-docker}-api-1` for the container it
reaches, and `:222-223` run `mkdir -p "$dir"` *before* `umask 077`, leaving the escrow directory 0755;
nothing prevents `export-key` from writing the escrowed key into `/backups`, beside the ciphertext it
opens.
*Pointer:* read the object back and hash the retrieved bytes, keep one more remote copy than local, and
refuse to export the key under `BACKUP_DIR`.

**F211 — Med — `capacity_probe.py` generates real load against a live server, and the evidence document
asks it for a number it does not produce.** Its own docstring says so (`:5-6` "it generates real load"),
and the mechanism is unguarded: `:62-63` drive HTTP threads at `/health/` and `/accounts/login/`, and
`:92` `server.sendmail(...)` sends genuine messages to a real recipient to exhaust the per-login rate
limit. `docs/enterprise-readiness-proposal.md:140` concedes that "load-testing the live server is not
safe", yet nothing in the script requires confirmation, an isolated target or a non-production flag. The
documented requirement also exceeds the instrument: `docs/enterprise-next-steps.md:49` says the capacity
report must state "the concurrency and mailbox count the server supports and which resource limits it",
while the script prints an HTTP latency table (`:119-131`) and one SMTP throughput line (`:147-151`),
measures neither a mailbox ceiling nor a resource ceiling, and concedes at `:152` that its figures include
client network latency. The degradation verdict is also computed from the wrong baseline: `:125-126`
`baseline = baseline or row['p95'] or 1` adopt the *first supplied* level as the baseline, so
`--levels 25,50` compares 50 against 25 and can report "No degradation up to the highest level tested"
when both are saturated. It is not wired to anything (the only references are
`enterprise-evidence/README.md:56`, `enterprise-next-steps.md:48`,
`enterprise-readiness-proposal.md:79,140`), so these numbers have never been produced.
*Pointer:* require an explicit `--target-is-a-test-server`, always warm up at one client, and rewrite the
requirement to what the tool can measure.

**F212 — Med — `provisioning/.env.example` omits three of the seven variables the compose file requires,
and its `BACKUP_ENCRYPT` default contradicts the documented claim (see F194).** `:2` instructs "Copy to
`.env` and fill in your values." `docker-compose.yml` demands seven with the `${VAR:?run make provision
first}` form: `APP_DB_PASSWORD`, `DJANGO_SUPERUSER_PASSWORD`, `DOVECOT_DB_PASSWORD`,
`POSTFIX_DB_PASSWORD`, `POSTGRES_ADMIN_PASSWORD`, `REDIS_PASSWORD`, `SECRET_KEY`. The template supplies
four (`:18`, `:19`, `:20`, `:23`) and never mentions `APP_DB_PASSWORD`, `DJANGO_SUPERUSER_PASSWORD` or
`REDIS_PASSWORD` anywhere in its 41 lines, so an operator who follows the comment gets a startup error
naming variables the file they were told to fill does not contain. `:4` also promises that "Compose maps
these short names into Django runtime vars (see `docs/environment.md`)", which is true of the four that
exist and unhelpful about the three that do not. *Pointer:* add the three rows with the same
`change_me…` placeholders `validate_env` rejects (`provision.sh:232`), so a copied template fails loudly at
the wizard rather than quietly at compose.

**F213 — Med — `update.sh` chooses the release from local tag refs, and its rollback can leave a
half-applied upgrade recorded as a success.** `:33` derives the "latest release" from `git tag -l`, which
lists the operator's local tags: a hand-made, mistyped or deliberately planted `v9.9.9` outranks the real
ones, and `:124-127` with `:144` then `git checkout --detach` onto it without establishing that the tag
exists on `origin` or that its commit was fetched from a trusted remote. `:140-141` do write the `pending`
history line *before* the checkout, which is the right instinct, and `:54-59` `chmod 700`/`600` the dump
and `.env` copy, reject an empty dump at `:57` and use
`--clean --if-exists --single-transaction` on restore — genuinely careful work. But the rollback path is
unguarded: `:110-115` check out the old code and restore the old database, then call `provision` bare, so
under `set -e` a failed rebuild exits after `:154` has already marked history ` updated` and before the
`rolled-back` marker is written — leaving old code, a restored database, stopped containers and a history
file that says the upgrade happened.
*Pointer:* `git ls-remote --tags origin` plus a check that the checked-out SHA came from `origin`, and
wrap the rollback in `if do_rollback; then … else` printing the exact recovery commands.

**F214 — Med — the enterprise documents disagree about their own test and coverage numbers.**
`docs/enterprise-readiness-proposal.md:67` states "769 tests, 78 % coverage" and
`docs/enterprise-next-steps.md:3-4` repeats "tested (769 passing, 78 % coverage)" while
`docs/enterprise-slo.md:38` records "measured 73.6% on 2026-10-11". Both claims cannot be current for the
same commit, and `docs/development.md:20` documents a 70 % gate, so a reader cannot tell whether 73.6 %
ever breached anything. The same pair of files also assert a release status the tag list contradicts —
already recorded as F177, and not repeated here. *Pointer:* attach a commit and a command to each figure,
or drop the figure and cite the CI run.

**F215 — Med — a shipped control is described in the governance documents as not built.** Outbound anomaly
containment exists and runs: `backend/apps/mail/services/containment.py:1-17` and `:38-43` implement it,
`:85-99` read its thresholds, `backend/config/settings/base.py:255-258` schedule it every minute
(`'outbound-containment': {'task': 'mail.check_outbound_containment', 'schedule': crontab(minute='*')}`),
its verdict is surfaced by `accounts/views/sending.py:1,13,23,47,65` and
`accounts/services/system_health.py:684-703`, and its page is registered at
`docs/html_templates.md:45` as `admin/sending_paused.html`. Against that, `docs/risk-register.md:12`
describes R4 as "(not built)", `docs/enterprise-next-steps.md:82` lists "automatic send suspension" among
what is deliberately *not* planned, and `docs/enterprise-readiness-proposal.md:157` §6 says "not now". The
document that steers risk decisions therefore understates the product's own protection, and a reviewer
following R4 would look for a control that is already deployed. The real, narrower truth is that it
engages only when the Outbound policy plugin's action is `notify` or `pause`
(`containment.py:85-99` returns `None` otherwise) — a caveat worth stating in the register.
*Pointer:* rewrite R4 and the next-steps row to name the shipped control and its gating condition.

**F216 — Med — the documented pre-commit ritual omits both gates CI actually fails on.**
`docs/development.md:38-39` say "Before committing: `ruff check backend`, `ruff format --check backend`,
`pytest -q`." `.github/workflows/ci.yml:44-45` runs
`python -m pip_audit -r requirements/prod.lock --disable-pip` and `ci.yml:47-48` runs `mypy`, with the
step comment calling lint "blocking — see `docs/enterprise-slo.md`". The Makefile already exposes both —
`typecheck:` at `:43-44` (`mypy`) and `lock:` at `:62-65` (piptools compile followed by pip_audit), plus
`audit:` at `:69` — yet the target table at `:18-29` lists ten other targets and none of these three. A
contributor who follows the document exactly produces a red build, and the two failures it omits are the
ones with security relevance (the lock drift behind F166/F167 is caught only by pip_audit). The rest of the
file is careful — `:19` already uses `venv\Scripts\python -m pytest -q` and `:31-32` warn that system
Python lacks `ninja`. *Pointer:* add `make typecheck` and `make audit` to the checklist and the table.

**F217 — Med — `docs/secrets-map.md` declares its own completeness rule and then misses three live secret
classes.** `:4` states "A secret not listed here is a gap." The twelve rows cover user passwords, TOTP
secrets, recovery codes, API keys, DNS provider credentials, DKIM keys, DNSSEC keys, TLS material,
`SECRET_KEY`/database/Redis, the backup key and the SSH key. Not listed: webhook signing secrets
(`backend/apps/mail/services/webhooks.py:234,484`), the plugin secret store whose Fernet key is seeded from
`SECRET_KEY` (`backend/apps/core/plugins/services/secrets.py:3,16,21`), and object-store credentials an
operator can supply through the `storage.objects` capability
(`backend/apps/core/storage/plugin_contract.py:92`, `backend/apps/core/storage/drivers/s3.py:75,91,99`). By
the document's own standard each becomes a declared gap the moment the file is read, and a reviewer who
uses the map as the checklist — which is its stated purpose — will not look for them. *Pointer:* add three
rows with where each is stored, who may read it, and how it is rotated.

**F218 — Med — `docs/html_templates.md` claims there are no app-embedded templates while a 5,853-line
vendored Django app with 7 templates sits in `backend/`.** `docs/html_templates.md:3` reads "Single source:
`frontend/templates/`. No app-embedded templates." and the file's own rule is that "every row must exist on
disk", verified by CI and `test_frontend_contract.py`. `git ls-files backend/apps/mydoc` returns 25 tracked
files totalling 5,853 lines — `templates/mydoc/` holding `audit.html` (345), `endpoint.html` (467),
`base.html` (180), `icon.html` (88), `index.html` (103), `section.html` (95) and `search.html` (43), 1,321
template lines in all — and the registry has no `mydoc` row. The app's unreachability is already recorded as
F81 and is not restated; what F81 did not cover is that the registry the design system and CI treat as the
authoritative template list is contradicted by these seven files and cannot see them, because
`test_frontend_contract.py` reads the registry rather than the tree. A second claim in the same header line,
"Canonical board map: `.agents/skills/ifinmail-design-system/references/template-map.md` (50 boards)", is
also wrong in both directions — see F220. The pyproject quarantine (`:4-7`, `:88-92`, `:96-98`) states the
reason plainly — "imported from another project … needs djangorestframework, which is not a dependency
here" — and that is confirmed: `grep -rni djangorestframework requirements/` is empty while
`introspection.py:441,608,942` import `rest_framework`. *Pointer:* either delete the app or give the
registry a documented third class ("vendored, not mounted, not audited") so CI, the registry and the tree
agree, and have a job recompute the registry from `git ls-files` instead of trusting the prose.

**F219 — Med — inside `mydoc`, every frontend rule the design system and the URL contract exist to enforce
is broken, and the contract test names it as an exception.** The app's missing authentication is F81's; this
is about the templates themselves.
`backend/apps/mydoc/templates/mydoc/base.html:17`, `:19` and `:177` load `css/variables.css`,
`css/mydoc.css` and `js/mydoc.js`; none exists — `git ls-files` matching `mydoc\.(css|js)` or
`variables\.css` returns only `frontend/static/css/ifinmail-variables.css` — so all 1,321 lines would render
unstyled and the search modal, theme toggle, playground and copy buttons would be dead, and the
`data-method`/`data-lang`/`data-copy-target` attributes at `index.html:58`, `:68` and
`endpoint.html:309,324,336,339` already have no consumer for exactly that reason. `base.html:78` hardcodes
`href="/dashboard/"` instead of `{% url %}`, and the test that forbids exactly that cannot see it:
`backend/apps/core/tests/test_url_contract.py:41` filters `'mydoc' not in p.parts`. None of the 7 files
loads i18n or contains `{% trans %}`/`{% blocktrans %}`, while `LocaleMiddleware` is active
(`settings/base.py:72`); none uses a single `--ifinmail-*` token, and colour arrives as injected literals —
`style="background: {{ ms.color }}"` at `base.html:156`, `index.html:14`, `section.html:14`,
`endpoint.html:14`, fed from `introspection.py:60-66`'s hex palette, plus
`style="--grade-color: {{ report.grade_color }}"` at `audit.html:135` from `auditor.py:174-182`.
`audit.html:159-203` and `endpoint.html:463-466` are inline `<script>` bodies, which the policy described at
`settings/production.py:72` forbids ("All templates ship scripts as static files; no inline scripts or
handlers"), and `endpoint.html:464-465` interpolate `{{ endpoint_meta_json|safe }}` /
`{{ fields_meta_json|safe }}` into that script body — `json.dumps` (`views.py:195-210`) does not escape `<`,
so a `</script>` inside an introspected path, `help_text` or choice terminates the tag. **SUSPECTED** as an
injection: the values are developer-authored, and proving or disproving that a database-editable `help_text`
can reach them needs a full read of `introspection.py`, which this sweep did not do. Independently,
`audit.html:196-201`'s `getCookie('csrftoken')` can only return an empty string because `settings/base.py:192`
sets `CSRF_COOKIE_HTTPONLY = True`, so that script's own POST would be rejected. Form controls at
`base.html:114` and `endpoint.html:264,283,289,297` have no `<label for>` target (`:281`, `:296` labels omit
`for`), and `search.html` is linked from nowhere. To its credit the app never uses `mark_safe`,
`autoescape off`, `onclick=` or `javascript:`; it escapes before adding line breaks
(`endpoint.html:56` `{{ endpoint.docstring|linebreaksbr }}`); it uses real `<a>` and
`<button type="button">`; it contains no `<img>` tags at all; and its own navigation resolves against
`mydoc/urls.py`. *Pointer:* delete the app, or port it into `frontend/templates/` and audit it as a
`site/`-class zone; and remove `test_url_contract.py:41`'s named exception once it is gone, so the exception
itself cannot outlive the thing it excused.

**F220 — Med — the design-system references teach values the implementation does not have, contradict
each other, and route new work to the wrong file.** `patterns.md:3` tells a contributor to "add a class
there rather than styling in the template" with the target given as
`frontend/static/css/ifinmail-components.css`, while `SKILL.md`'s hard rule says redesign styles go in
`ifinmail-redesign.css` (loaded last, scoped under `html.ifinmail-shell`) and legacy duplicates must be
deleted. `patterns.md:7` and `.agents/skills/ifinmail-design-audit/SKILL.md:42` both say the page gutter is
24, but the only gutter token in the system is `--ifinmail-gutter: 20px`
(`frontend/static/css/ifinmail-variables.css:198`; `ifinmail-layout.css:4` comments "20px gutter" and uses
it at `:423`, `:454`). `patterns.md:15` gives the page title as 20/600 and `patterns.md:54` gives it as 18 —
the same file, twelve lines apart — while `design-audit/SKILL.md:44` says 18/600 and the implementation is
`--ifinmail-font-size-page-title: 1.125rem`, i.e. 18 (`ifinmail-variables.css:151`).
`tokens.md` still lists settled work as pending: `:16` "Today #6B7280 **change**" when
`ifinmail-variables.css:24` is already `#656D7A`; `:22-24` "add `--ifinmail-color-*-text`" when `:39-41`
define them; `:33` "Page title | 20/600 … (add, 1.25rem) | h1 18px **change**"; `:47` "add
`--ifinmail-radius-badge`" when `:220` has `0.3125rem`; `:49` "Restore these as `--ifinmail-shadow-2/-3`;
keep -1 and -4 at none" when `:232-233` define -2/-3 and `:230`, `:234` already hold -1/-4 at `none`.
`patterns.md:67` and `:79` hardcode `#9ca3af` and `#c3c9d3` in a guide whose own rule is tokens-only, no new
hex. `patterns.md:89` promises "nothing is loaded from a third party (fonts are self-hosted)" while
`frontend/templates/base.html:27-31` loads the Google Fonts CDN by default (`server_context.py:49-67`,
`USE_GOOGLE_FONTS` defaulting to `1`; the shipped-default half of this is F157 and is not restated).
`template-map.md:3` asserts "All 50 entries of `docs/html_templates.md` are covered" and `:8` names
`provider_row.html`, which is not among the 9 files in `frontend/templates/admin/partials/`
(account_photo, admin_row, delivery_panel, directory_panel, dns_row, log_row, mailbox_row, plugin_fields,
queue_row); `:22`'s Setup row omits `setup/dns_server.html`, which exists and is registered at
`html_templates.md:79`. `ifinmail-template-builder/SKILL.md:29` lists 11 of the 14 blocks `base.html`
actually defines (`:22`, `:26`, `:40`, `:41`, `:44`, `:46`, `:48`, `:50`, `:53`, `:58`, `:61`, `:70`, `:78`,
`:79`), `:36`'s CSS-file map omits `ifinmail-redesign.css` — the file the skill instructs you to edit — and
`:57` says pages must work at 360 px while `:60` verifies at 390 px. *Pointer:* have one command generate
the token and block tables from `ifinmail-variables.css` and `base.html`, and delete the prose numbers it
covers.

**F221 — Med — `cloud-init.yaml` prints a success banner for an installation that provably failed, points
at a console path that 404s, and promises a feature whose flag is dead.** `:10-11` instruct "Set these
environment variables before pasting" in a file whose only use is being pasted into a provider form, where
no shell environment exists; `:53-56` therefore reach
`DOMAIN="${DOMAIN:-example.com}"` and pipe `bootstrap.sh` into `bash` with that default. The guard against
it is real and this sweep initially believed the opposite — `provision.sh:215-239`'s `validate_env` dies at
`:232-238` on any value matching `change_me*`, `dev_*` or `*example.com*`, and `main()` calls it at `:622` —
so nothing is installed on `example.com`. But the ordering is wrong: by then `:16-22` have already installed
Docker from `:41` and `:43`'s hardcoded
`https://download.docker.com/linux/ubuntu/gpg` and `…/linux/ubuntu $(. /etc/os-release && echo
"$VERSION_CODENAME") stable` lines, even though `:2` claims "Ubuntu 22.04+ / Debian 12+"; the installer's
exit status is never tested, so `:59-71` print `=== ifinmail deployment complete! ===` anyway; and `:67`
prints `Admin panel: https://$MAIL_HOSTNAME/admin/` although `backend/config/urls.py:178` mounts the
console at `manage-panel/`, so the printed link 404s. `:68` adds
`Nextcloud: optional companion — install via admin panel`, but the only console affordance for it is
`setup/done.html:41-42`'s `{% if ENABLE_NEXTCLOUD %}`, and
`backend/config/server_context.py:49-67` returns no `ENABLE_*` key at all, so that branch can never render;
Nextcloud otherwise appears only in a translation catalogue (`frontend/locale/en/LC_MESSAGES/django.po:1297`)
and in the URL-contract allowlist at `core/tests/test_url_contract.py:28-33`. `:74-78` then reboot the
machine unconditionally (`power_state: mode: reboot … condition: true`), so the operator learns the truth
after a restart. *Pointer:* test the installer's status before the banner, print `{% url %}`-derived
`/manage-panel/`, delete the Nextcloud line or wire the flag, and restrict the Docker repo lines to the
distribution they name.

**F222 — Low — `COREDNS_IP` is written by all three generators and read by nothing.**
`provisioning/.env.example:15`, `bootstrap.sh:205`, `provision.sh:138` and `setup-wizard.sh:162` all set
`COREDNS_IP=127.0.0.1`. A grep for `COREDNS` across every `*.yml`, `*.py`, `*.sh` and `*.md` returns exactly
those four writes and nothing else — no compose service reads it, no Python setting consumes it, and no
document mentions it. The stack answers DNS for its own zones from the `dns` container
(`docker-compose.yml:267`, and the `dns` entry at `core/platform/services/entrypoints.py:161-169`), with
`resolver` for outbound lookups, so CoreDNS is not part of this architecture. It is the mirror image of
F204: there, four `MONITOR_*` knobs feed a script that never runs; here a variable has neither a writer of
purpose nor a reader. *Pointer:* delete the four lines, or if a future resolver change is intended, name it
in `docs/environment.md` and read it in compose.

**F223 — Low — two documented patterns have no live implementation, and the banner family is defined as
many as three times over.** `patterns.md:19` specifies a stat card ("overline label, 24 mono value,
12/500 trend line coloured by meaning"), and `.ifinmail-stat-card` with `--error`/`--warning` variants does
exist at `ifinmail-components.css:841-869` — used by zero of the 114 templates and zero scripts. The
vocabulary the console actually uses is `ifinmail-admin.css:89-159` (`-stat-row`, `-stat-cell`,
`__dot--*`, `-stat-big`, `-stat-label`), consumed by `admin/dashboard.html`, `dns_config.html`,
`settings_mailboxes.html`, `spam_filtering.html` and `user_management.html`. `patterns.md:53-55` describes
"Banner" without naming a class at all, and five banner classes exist across three files:
`.ifinmail-hbanner` (`ifinmail-redesign.css:3110-3131`, which provides only `--danger`, `--warning` and
`--ok`, so the pattern's `info` tone has no implementation), `.ifinmail-health-banner` defined twice
(`ifinmail-admin.css:70` and `ifinmail-components.css:2004`), `.ifinmail-error-banner` defined three times
(`ifinmail-redesign.css:971`, `ifinmail-admin.css:1093`, `ifinmail-components.css:2755`) and
`.ifinmail-update-banner` (`ifinmail-components.css:2955`). A contributor who follows the reference picks
the dead one; a contributor who searches the CSS gets whichever definition loads last — the file order in
`base.html:33-39` decides by specificity and sequence rather than by intent. *Pointer:* name the class in
the pattern, delete the unused card, and collapse each duplicate into one definition.

**F224 — Low — `.agents/skills/systematic-debugging/` is another project's skill, and its worked example
tells the agent to print secret values.** The process in `SKILL.md` transfers fine; the material does not.
`root-cause-tracing.md:80` is `await execFileAsync('git', ['init'], { cwd: directory });`, `:89` says to
capture with `npm test 2>&1 | grep 'DEBUG git init'`, and `:105` invokes
`./find-polluter.sh '.git' 'src/**/*.test.ts'` (recorded as a no-op in this repo at F169, not restated);
`defense-in-depth.md:56-69` writes its "Layer 3: Environment Guards" in TypeScript and guards on
`process.env.NODE_ENV === 'test'`, and `:110` reports "All 1847 tests passed";
`condition-based-waiting-example.ts:2` credits "Lace test infrastructure improvements (2025-10-03)" and
`:4-6` import `from '~/threads/thread-manager'`. None of it is executable in a Django repository, so an
agent that follows the example literally invents nothing useful and may copy the pattern anyway. The
sharpest line is in `SKILL.md:97`, inside the debugging walkthrough:
`env | grep IDENTITY || echo "IDENTITY not in environment"` — which dumps environment *values* into the
transcript and into any log of the session, three lines after `:93` demonstrates the safe form in the same
block (`echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"`). For a project whose stated rule is that no
secret value is ever printed, this is the wrong lesson in the one file an agent is guaranteed to read;
`:100-103` then run macOS-only `security list-keychains` and `codesign --sign "$IDENTITY"`. Four
author-validation fixtures also ship loose in the skill directory — `test-academic.md`,
`test-pressure-1.md:5`, `test-pressure-2.md`, `test-pressure-3.md` — each opening "You have access to:
skills/debugging/systematic-debugging", a path that does not exist here, and only `CREATION-LOG.md:54-75`
explains they were scenarios used to test the skill while writing it. `SKILL.md:179` and `:287-288`'s
references to nonexistent `superpowers:` skills are already F174. *Pointer:* change `:97` to the SET/UNSET
form, port the examples to pytest, and move the four fixtures under a `tests/` directory or rename them
`example-*.md`.

**F225 — Low — the evidence index promises a per-release report that has never been written.**
`docs/enterprise-evidence/README.md:3-5` frames the directory as "a record of something that was run, with
a date, a person, and numbers" and says "Do not write aspirations here"; the table's other three rows are
honestly marked **Not yet run** or *Not commissioned*. `:12` is the exception —
"Test and coverage report for a release | `release-<version>.md` | Per release" — and
`git ls-files docs/enterprise-evidence/` returns one tracked file, `README.md`. `git tag | wc -l` counts 75
refs: 74 `v0.0.x` tags through v0.0.74 plus a `backup/broken-v0.0.2`, so by this row's own rule there
should be a report for each release. The version-status contradictions in the same document set are already
F177 and are not repeated. *Pointer:* mark the row **Not yet run**, or write the report for the current
release and let CI attach the numbers.

**Checked and refuted in this zone.** Four claims from the delegates, and one made by this author earlier in
the sweep, did not survive a direct read:

* REFUTED — "the README port diagram omits 6 of the 13 services". `entrypoints.py:93-174`'s `CATALOGUE`
  is exactly ten entries (smtp 25, submission 587, smtps 465, imaps 993, pop3s 995, pop3 110, imap 143,
  http 80, https 443, dns 53 tcp+udp), `README.md:78,92,96,97,98` match them, and only POP3/POP3S are
  missing from the prose enumeration at `README.md:104`.
* REFUTED — "cloud-init installs a server on `example.com` without telling anyone". `provision.sh:232`
  rejects `*example.com*` and `:238` dies, called from `main()` at `:622`. What stands is recorded as
  F221: the wasted Docker install, the unchecked exit status, the wrong console path and the dead flag.
* REFUTED — "`/admin/` is the Django admin path in this product". `backend/config/urls.py:178` mounts
  `admin.site.urls` under `manage-panel/`, which is why the printed URL 404s rather than exposing a
  second console.
* REFUTED — "`docs/development.md:19-20` tells contributors to use bare `python`". `:19` is
  `` | `venv\Scripts\python -m pytest -q` | Full suite (uses `venv`, not system python) | `` and
  `:31-32` explicitly warn that system Python lacks `ninja`.
* REFUTED (this author's own citation) — `system_health.py` was cited in earlier notes as living under
  `backend/apps/mail/services/` or `backend/apps/core/platform/services/`. `git ls-files` puts it at
  `backend/apps/accounts/services/system_health.py`, and every reference above uses that path.
* Also checked and correct in this zone: `README.md`'s quota, time-limit and log-cap figures
  (`mail/types/quota.py:12` `DEFAULT_QUOTA_MB = 1024`; `mail/tasks.py:23-24` 90/120;
  `mail/services/delivery_events.py:34` `MAX_READ = 4 * 1024 * 1024`;
  `core/platform/services/audit.py:7,309-312` retention default 365, minimum 30), and the beat entries the
  README describes (`verify-domains` every 15 minutes, `apply-postfix-overrides` every 10,
  `check-certificate-expiry` daily 06:10). `entrypoints.py`'s rate constants (`:40` 120/min,
  `:45` 30/min mail flood, `:46` 240/min web, `:51` 10 min penalty, `:53` 600/min web guard, `:56` 50 mail
  concurrent, `:57` 100 web, `:58` scan-ban 30) are consistent with what `README.md` states about the
  firewall container.

**What this zone got right.** The scripts are not uniformly careless, and the good parts are worth keeping
as precedent. `backup_full.sh:4` and `restore_test.sh` use `set -euo pipefail`, and
`restore_test.sh:32` installs an ERR trap that calls `notify_failure`; `backup_offsite.sh:223` knows about
`umask 077`, and `:207` uses `--passphrase-file` rather than argv; `:72-73`'s off-site SSH path is
genuinely verified with a partial file, an atomic `mv` and a remote `sha256sum`. `update.sh` snapshots
before switching (`:54-59` `chmod 700`/`600` on the dump and `.env` copy, `:57` rejecting an empty dump with
`[ -s "$file" ]`), writes its `pending` history line before the checkout (`:140-141`) so a crash is
recoverable, and restores with `--clean --if-exists --single-transaction`. `monitor.py` takes a non-blocking
`fcntl` lock (`:445-454`) so two runs cannot collide, writes alert state atomically with `os.replace`
(`:385-388`), passes the Redis password through the client rather than argv (`:33-40`), and exits 2/1 on
CRITICAL/WARN (`:463-468`). `capacity_probe.py:87` uses `ssl.create_default_context()` and reads the
password from a file (`:83`). `uninstall.sh` reads its confirmation from `< /dev/tty` (`:100`) so an
unattended run cannot be fed by a pipe, refuses to remove `/`, `/root`, `/home` and empty paths (`:163`),
restores the previous `vm.overcommit_memory` value, and reports leftovers by actually querying containers,
volumes, images, the network, the cron file, the sysctl file and the state directory (`:44-56`).
`docker_clean.sh` never touches volumes, offers `--dry-run` and `--deep`, and scopes its container prune by
project label (`:66`). `setup-wizard.sh:38-42` rejects placeholder domains and validates RFC 1035 shape
before writing anything, and `provision.sh:215-239`'s `validate_env` is the reason the cloud-init default
never becomes a live server. `obtain-ssl.sh:16` brings up nginx for the ACME challenge itself, `:66`
explicitly excludes `privkey*` from the world-readable chmod sweep, and the failure branch attempts a
restore at all. And `mydoc`, whatever its defects, is quarantined three times over, is unreachable, and does
not use `mark_safe`, `autoescape off` or inline handlers.

**COVERAGE STATEMENT.** 70 tracked files in this zone, in three groups. **Group 1 — `provisioning/`
outside `provisioning/docker/` (21 files): read in full** — `firewall.sh` (88), `cloud-init.yaml` (78),
`provisioning/.env.example` (41), `provisioning/fail2ban/jail.local` (46) and all four
`fail2ban/filter.d/*.conf` (7-9 each), `restore_test.sh` (187), `docker_clean.sh` (83),
`backup_full.sh` (237), `obtain-ssl.sh` (94), `uninstall.sh` (173), `setup-wizard.sh` (251),
`provisioning/.gitkeep`. **Read only at the cited lines:** `provisioning/scripts/provision.sh` (667 —
`:175`, `:215-239`, `:232`, `:238`, `:317-330`, `:349`, `:480-498`, `:622`),
`provisioning/scripts/bootstrap.sh` (329 — `:136-138`, `:158`, `:176-205`, `:247`),
`provisioning/scripts/update.sh` (180 — `:33`, `:54-59`, `:110-115`, `:124-127`, `:140-154`),
`provisioning/scripts/backup_offsite.sh` (253 — `:15-47`, `:67`, `:83`, `:87-96`, `:109-134`, `:149`,
`:170`, `:200`, `:207`, `:222-223`, `:236-248`), `provisioning/scripts/monitor.py` (468 — `:4`, `:15-25`,
`:33-40`, `:87-92`, `:106`, `:157-179`, `:186-200`, `:208-221`, `:243-258`, `:286-310`, `:347-355`, `:377-390`,
`:395-434`, `:442-468`), `provisioning/scripts/capacity_probe.py` (157 — `:5-6`, `:30`, `:62-63`, `:83-92`,
`:111`, `:119-152`, `:156`), `provisioning/scripts/deploy.sh` (6, read in full as a 6-line wrapper).
**Group 2 — `backend/apps/mydoc` (25 files, 5,853 lines): the 7 templates read in full** (1,321 lines:
`audit` 345, `endpoint` 467, `base` 180, `icon` 88, `index` 103, `section` 95, `search` 43), plus
`apps.py` in full and `views.py`, `config.py`, `urls.py` at the cited lines. **Not read:**
`introspection.py` (1,241), `auditor.py` (1,062), `_native.py` (272), `_parallel.py` (178),
`management/commands/mydoc_audit.py` (159), `tests/test_audit_regressions.py` (558) and the two `types/`
files — the sweep establishes the app is uninstalled and unmounted, which is why its internals are excluded
from the design and URL contracts, and F219's injection claim is marked SUSPECTED for exactly this reason.
**Group 3 — the documentation and skill residue deferred by §9.13 and §9.14 (24 files), all read in full:**
`README.md`'s remaining numeric claims, `docs/development.md`, `docs/risk-register.md`,
`docs/secrets-map.md`, `docs/html_templates.md`, `docs/enterprise-evidence/README.md`,
`docs/enterprise-next-steps.md`, `docs/enterprise-slo.md`, `docs/enterprise-readiness-proposal.md`,
`examples/python/README.md`, the four design-system and template-builder skill references
(`patterns.md`, `tokens.md`, `template-map.md`, `ifinmail-template-builder/SKILL.md`), and all eleven files
under `.agents/skills/systematic-debugging/`. **Cross-checked, not re-swept here:**
`docker-compose.yml` (`:14-30`, `:84`, `:134`, `:294-316`, `:409`, `:438`, `:490`, `:558`, `:564-582`),
`provisioning/docker/postfix/entrypoint.sh:52`, `dovecot/entrypoint.sh:47`, `dovecot.conf:17`,
`nginx/conf.d/ifinmail.conf:33`, `backend/config/settings/base.py:72,99,192,255-258`,
`backend/config/settings/production.py:72`, `backend/config/urls.py:178`, `backend/config/server_context.py:49-67`,
`backend/config/branding.py:129-217`, `frontend/templates/base.html:22-79`,
`core/tests/test_url_contract.py:28-41`, `Makefile` targets quoted above, `.github/workflows/ci.yml:40-55`,
`pyproject.toml:1-15,85-100`, and the Python services cited finding by finding. **Explicitly not
inspected:** `provision.sh`'s and `bootstrap.sh`'s bodies beyond the cited lines, `mydoc`'s three large
Python modules, and any runtime observation — no script in this zone was executed, so every claim above is
a reading claim about the source, not an observation of behaviour on a host.

### 9.16 The four files nobody counted — the plain-text email templates and `logs/.gitkeep`

This section exists because of an arithmetic slip in the earlier zones. §9.10's zone is "114 templates"
and that is still exactly right about HTML: `git ls-files frontend/templates` returns **117** entries, 114
`.html` plus three `.txt` files under `admin/`. Those three are Django templates like any other — they are
the plain-text halves of two transactional emails, rendered by `render_to_string` and by Django's own
`PasswordResetView` — and no coverage statement in §9 or §8 named them. The repository holds 1,294 tracked
files and the last one outside a named group is `logs/.gitkeep`, recorded here so the count closes rather
than being quietly forgotten.

**F226 — Med — the plain-text half of the password-reset email carries no translation markup, while its own
HTML half and its own subject file do.** `frontend/templates/admin/password_reset_email.txt` is eleven lines
of prose — `:3` "We received a request to reset the password for {{ user.email }}.", `:8-9` "If you did not
request a password reset, you can safely ignore this email; your password will not change." — with no
`{% load i18n %}` and not one `{% trans %}` or `{% blocktrans %}` tag in the file. The HTML part of the very
same message wraps the identical sentence: `admin/password_reset_email.html:30` is
`{% blocktrans with email=user.email %}We received a request to reset the password for …`, and the subject
of that message is translated too — `admin/password_reset_subject.txt:1`
`{% blocktrans with name=brand.name %}Reset your {{ name }} password{% endblocktrans %}`. Both templates are
bound to one view (`accounts/views/password_reset.py:21-23`, `email_template_name` /
`html_email_template_name` / `subject_template_name`), so a recipient whose client shows the text part, or a
screen reader reading it, gets English out of a message the app otherwise treats as translatable. The other
file in the group shows the authors knew how to do it: `admin/email_mailbox_setup.txt` is wrapped end to
end, including a plural at `:6`. This is not F35's count of ~32 un-wrapped runtime strings — these two files
were never in that number because they are neither `.py` nor `.html`, and the design rule
("All copy goes through `{% trans %}` / `{% blocktrans %}`", `ifinmail-design-system` SKILL.md) is written
for templates and was applied to the HTML half only.
*Pointer:* wrap `password_reset_email.txt:3-9` in `{% blocktrans %}` with the same context the HTML part
already passes (`user.email`, `brand`), and add a test that every template under `frontend/templates/admin/`
whose name ends in `_email.txt` or `_email.html` contains at least one i18n tag — the pair is the kind of
thing that drifts silently because nothing renders both halves side by side.

**F227 — Low — the client-facing port pair is written in six places and pinned in two.** IMAP 993 and
submission 587 are hard-coded in the firewall catalogue
(`core/platform/services/entrypoints.py:106` `((Proto.TCP, 587),)`, `:122` `((Proto.TCP, 993),)`), in the
console's own reader (`mail/services/imap_reader.py:30` `PORT = 993`), in the autoconfig/autodiscover
documents (`mail/views/__init__.py:76`, `:90`, `:122`, `:138`), and then a fifth and sixth time inside the
welcome email — `admin/email_mailbox_setup.txt:13-14` ("port 993, SSL/TLS" / "port 587, STARTTLS") and
`admin/email_mailbox_setup.html:60-61` with the same two literals in the same order. Only the autodiscover
copies have a test: `mail/tests/test_client_config.py:52`, `:66` and `:69` assert `<port>993</port>`,
`('imap': ('993', 'SSL'), 'pop3': ('995', 'SSL'))` and `('587', 'STARTTLS')`. Nothing asserts that the
sentence an administrator's user reads matches the port the firewall actually opens, and nothing asserts the
email pair against the catalogue — so a future change to one is silent in the other five. Related residue in
the same two templates: POP3S 995 is offered by `test_client_config.py:66`'s own expectation and by the
autoconfig XML, but the welcome email's step 2 (`:10`) tells the user to add the account to "Outlook, Apple
Mail, Thunderbird, your phone…" with only the IMAP line to copy, so a POP3 user gets no instructions at all.
*Pointer:* one `MailClientPorts` dataclass in `mail/types/`, rendered into the catalogue, the autoconfig
documents and both halves of the email, and a test that the email text and the firewall agree.

**F228 — Low — the setup email's server instructions are gated on a value nothing validates.**
`accounts/views/mailboxes.py:170` puts `'mail_host': os.environ.get('MAIL_HOSTNAME', '')` in the context,
and both templates wrap the three instruction lines in `{% if mail_host %}`
(`email_mailbox_setup.txt:11-15`, `email_mailbox_setup.html:57-61`). The variable is supplied by the stack
(`provisioning/docker/docker-compose.yml:79`, `:131`, `:386`, `:464` all pass
`MAIL_HOSTNAME: ${MAIL_HOSTNAME}`) so the block normally renders; the point is that there is no settings
entry to check — `grep -n MAIL_HOSTNAME backend/config/settings/*.py` returns nothing — so the one place the
product tells a user how to configure their mail client degrades to *silently printing nothing* rather than
to an error or a warning in the console. An empty `MAIL_HOSTNAME` is exactly the condition §9.8's
certificate findings and F204's phantom probe already show this stack handles by omitting output.
*Pointer:* read a Django setting that production validates at boot (`provision.sh:215-239`'s
`validate_env` already refuses placeholder domains), and render an explicit
"contact your administrator for the server address" line when it is unset.

**Checked in this zone and refuted.**
* REFUTED — `{% blocktrans count days=valid_days %}` at `email_mailbox_setup.txt:6` looks malformed, and if
  it were, the welcome email would raise at render time. It is valid in this Django version:
  `venv/Lib/site-packages/django/templatetags/i18n.py:516-522` accepts a `count` option and requires
  "exactly one keyword argument", and the documented shape at `:470` is
  `count count=var|length` — the same `name=expr` form. So the plural renders and `{{ days }}` resolves.
* REFUTED — "the `.txt` templates are invisible to the gates." The URL contract does scan them
  (`core/tests/test_url_contract.py:52` and `:61` both pass `('.html', '.txt')` to `source_files`), and
  `makemessages` scans them by default (`core/management/commands/makemessages.py:360`
  `exts = extensions or ["html", "txt", "py"]`), which is why F226 is a missing-markup bug rather than a
  missing-extraction bug.
* REFUTED — "the reset email's `{{ protocol }}://{{ domain }}` link is a hand-spelled host."
  `accounts/views/password_reset.py:29-36` derives both from `site_url.origin(self.request)` —
  `scheme, _, domain = base.partition('://')` — and passes them as `extra_email_context`, with the comment
  at `:33` saying why. The template then uses `{% url %}` for the path, which is the contract.
* Checked and correct: every context key the three templates reference exists.
  `mailboxes.py:166-172` supplies `address`, `setup_url`, `valid_days`, `mail_host` and
  `email_brand_context(...)` to both the `.html` render at `:173` and the `.txt` render at `:177`, and
  `_setup_url` at `:153-160` builds an absolute link through `reverse()` with a relative fallback.

**What this zone got right.** Sending both halves is a real choice, not an accident:
`send_mail(..., html_message=html_body)` at `mailboxes.py:175-181` generates the text part from its own
template instead of stripping tags from the HTML, so the plaintext is written as plaintext. The failure path
is honest — `:182-185` catches `SMTPException`/`ConnectionError`/`OSError`, logs at warning with the address
and the exception, and returns `False` so the caller can report that the invite was not sent, rather than
reporting success. `email_mailbox_setup.txt:6` promises "The link works once and expires in {{ days }}
day." with `days = max(1, settings.PASSWORD_RESET_TIMEOUT // 86400)` (`:165`), which is a real derivation
from the configured timeout rather than a second hard-coded number, and `:16` closes with "If you weren't
expecting this mailbox, you can ignore this email." — the security-relevant sentence a welcome mail should
contain and many omit.

**COVERAGE STATEMENT.** 4 tracked files, all read in full:
`frontend/templates/admin/email_mailbox_setup.txt` (19 lines), `admin/password_reset_email.txt` (11),
`admin/password_reset_subject.txt` (1), and `logs/.gitkeep` (an empty placeholder — listed so the tracked
file count closes; there is nothing in it to read). Supporting reads made for the claims above, none of them
new zones: `backend/apps/accounts/views/mailboxes.py:153-185`,
`backend/apps/accounts/views/password_reset.py:17-42`, `backend/apps/mail/views/__init__.py:70-140`,
`backend/apps/mail/tests/test_client_config.py:52,66,69`,
`backend/apps/core/tests/test_url_contract.py:37-65`,
`backend/apps/core/platform/services/entrypoints.py:100-125`, `backend/apps/mail/services/imap_reader.py:30`,
`provisioning/docker/docker-compose.yml:79,131,330,386,464,523`, and the vendored Django sources quoted
above. **Explicitly not inspected:** nothing in this zone's own four files; no email was rendered or sent and
no template was executed, so F226–F228 are reading claims, and F228's "normally renders" depends on the
compose environment rather than on an observed container.

Two counting notes, so §1.1's totals can be checked rather than trusted. First, `frontend/templates` is
117 tracked files, not 114: 114 `.html` (§9.10's count, which is right for HTML) plus the three `.txt`
covered here. Second, the per-zone file counts in §1.1's table deliberately overlap and therefore sum to
more than the 1,294 tracked files — `backend/apps/mydoc` is claimed by both §9.6 and §9.15, the
`enterprise-*.md` files by both §9.13 and §9.15, and the design-system references by §9.13, §9.14 and
§9.15. The claim being made is that every tracked file group appears in at least one zone's coverage
statement, not that the zones partition the repository.

Recounting the two directory totals also corrected one label that was not a coverage failure: §9.12's
heading and §1.1's row said "48" for `frontend/static`, but its own coverage statement already accounted for
every file — 26 `.js` + 9 `.css` + 9 SVG + 2 static error pages + 2 woff2 + 5 PNG + 1 ICO + 2 `.gitkeep` =
the 56 tracked files `git ls-files frontend/static` reports. The heading and the row now read 56 with that
breakdown. Nothing was unread there; the number was just short.

---

## 10. Checked and found sound

Stated positively to narrow the next review's work. Verified by direct reading. This section is the
first-pass list only; every zone in §9 carries its own "what this got right" list, and those are the
load-bearing ones for the sweep — §9.11's client list (keystore crypto, TLS trust ordering,
dot-stuffing, XXE-proof autoconfig, Android export posture) and §9.14's examples list (endpoint and
scope parity, the webhook HMAC scheme matching the server byte-for-byte) are the discoveries someone
would otherwise re-litigate.

* **No tracked secrets.** Only `change_me_*` placeholders (`provisioning/.env.example:18-23`),
  `__*_DB_PASSWORD__` tokens in the postfix/dovecot `.cf` templates, and
  `keystore.properties.example` for Android. `.env`, `provisioning/.env`, `db.sqlite3`, `.coverage`
  and `media/` are untracked and ignored (`.gitignore:45-47,112`).
* **No command-injection surface.** No `os.system`, no `subprocess(..., shell=True)`; subprocess
  calls pass argument lists with a timeout (`dashboard.py:64,376,387`, `deliverability.py:335`,
  `monitoring.py:76`). `sync-overrides.sh:64-90` allow-lists keys per source file and regex-checks
  values before `postconf -e`.
* **No reachable SQL injection** from user input; the one interpolation found
  (`telemetry/threats/geo.py:115-122`) injects only an address-family constant.
* **Credential handling.** API tokens hashed (`tokens.py:252`), TOTP and plugin secrets
  Fernet-encrypted at rest, constant-time comparisons at `tokens.py:279`, `tracking.py:102,112`,
  `webhooks.py:623`.
* **Storage governance holds.** The only `FileField` is inside `core/storage`
  (`stored_file.py:24`); no `default_storage` or `upload_to=` elsewhere; no cross-app
  `services.models` import outside `telemetry`'s intra-app re-export.
* **SMTP sending rejects CRLF** in addresses and subject (`messages.py:47,96-104,220`) and accepts
  no caller-supplied headers.
* **No `TODO`/`FIXME`/`XXX`/`HACK` in `backend/**/*.py`.**
* Production CSP/HSTS/cookie flags are stronger than base, the debug web shell is disabled
  (`views/dashboard.py:440-452`), plugin manifests are not deserialized with
  pickle/`eval`/dynamic import (`manifest.py:27-36`), and the runtime-file writer rejects traversal
  (`runtime.py:20-22`).
* `check --deploy` passes; the only known plaintext-at-rest item is the DKIM key, which is a
  documented waiver (F8/F16, `docs/secrets-map.md`), not news.

---

## 11. Gaps in this assessment

The sweep closed every *reading* gap: §9.1–§9.16 together name every tracked file group in the repository,
no zone's findings rest on a sample, and §9.9–§9.16 each carry a coverage statement saying what was read in
full, what was read only at cited lines and what was not read. §9.1–§9.8 state their scope in their headings
instead, and the shape difference is recorded at the top of §9. Two honest caveats on the reading claim,
both from the final counting pass rather than from the sweep itself: the header's own scope line said
"114 templates" for `frontend/templates` when the directory holds 117 tracked files, and the three that were
missing are the plain-text email halves §9.16 exists to cover; and the per-zone counts in §1.1's table
overlap by design (`mydoc` is claimed twice, the `enterprise-*.md` files twice, the design-system references
three times), so they sum above the 1,294 tracked files rather than partitioning them. What remains open is
execution and observation, and those limitations are structural to this host rather than to the plan.

1. **No observed Actions run.** Every CI verdict is inferred from re-executing the workflow's own
   commands on Windows. `gh` is not installed; `mypy`, `docker compose`, gitleaks and shellcheck are
   all absent from this host, so four steps are unmeasured — including the type gate that CI will
   actually run. This is also why F168 (CI installs `testing.txt`, not the lock) is proven from the
   workflow text but its *observed* consequence is not, and why F176 (gitleaks v3 without a license or
   token) stays SUSPECTED rather than CONFIRMED.
2. **Nothing verified against a Linux host or a real install.** The project's own register says the
   rebuild drill (B.4/G.1) cannot be done from this host and that no penetration test (G.2) has
   happened. F21, F22, F26 and F27 need authenticated end-to-end proof on a real deployment. All of
   §9.8's container findings — F95, F96, F99, F107 and the rest — are read from the config and
   compose files as they would be rendered; no container was started, and F115's skipped `nft` checks
   stayed skipped here for the same reason.
3. **No runtime behaviour of the merged features was exercised**, because the dev database has no
   `mail` migrations applied (§4).
4. **Six security and correctness guards were never exercised on this host**, so "passes" here would
   have been meaningless: the local-driver path-traversal escape and the directory-sync behaviour
   (symlink rights, 10 failures), the profile-photo contract (`PIL` absent, whole file uncollected),
   the 22 theme/layout assertions (encoding crash), the bash-driven postfix/policy plugin suites
   (42 failures, 4 of the project's own hardening surfaces), the design-audit contract test, and the
   setup-redirect path of the URL contract (disabled by test settings, F36). All of these need a
   Linux run — which is also why risk-register items B.4/G.1 (rebuild drill) and G.2 (penetration
   test) remain open.
5. **The Android client was read, never built.** Gradle was not run, so F139–F153 rest on source
   reading plus the client's own test assertions — which were not executed either. F146 in particular
   (JVM-only APIs used from `commonMain`) is exactly the class of defect a compile would settle and
   reading can only suspect: the code as written cannot satisfy the iOS, JS and Wasm targets declared
   at `clients/android/*/build.gradle.kts`, but no cross-target build was attempted here, so it is
   reported as a structural contradiction, not as a proven compile failure. F151's absent
   `verification-metadata.xml` and F148's iOS signing identity are the same class.
6. **Coverage is thin in identifiable places:** per-app collected counts are core 995 · accounts 601 ·
   mail 491 · dns 113 · domains 60 · **devices 5**. `devices` exposes four API endpoints
   (`api.py`: list, register, set-active, touch) with only service-level tests and no HTTP tests;
   `accounts/views/website.py` (the site editor) is untested; `mydoc` is an empty shell with zero
   tests and is excluded from lint. Correcting the first pass here: the markdown renderer **is**
   fuzzed — `core/assistant/tests/test_markdown.py:316-327` composes 400 random inputs from a 33-piece
   alphabet under a fixed seed and asserts a whitelist audit on every output, which is stronger than
   "read". What is not proven is the *browser* half of the XSS findings: F32, F129 and F154 were
   established by tracing values from request to sink, not by executing a payload.
7. **Several named tests were read but never run**, which matters because four of the sweep's findings
   are precisely "the test exists and cannot catch this": F127 (`test_authoritative.py:403-406` asserts
   the parser, never the template), F135 (the logs summary assertion holds under the filtered case it
   does not exercise), F137 (the URL contract's own glob skips the pattern it should flag), and F191
   (the S3 driver's real second implementations have no in-repo job at all).
8. **Whether CI catches F33** (the `storage upload` argparse defect) depends on the runner's exact
   3.12.x patch level, which cannot be determined from here.
9. **Documented claims with no artefact are recorded as gaps, not as facts.** F181's bootstrap script
   was read as text only — its behaviour on a real host, and whether the public raw URL still serves
   what the repo holds, are unverified. F176, F191 and §9.8's rspamd log-item claim stay SUSPECTED.
   Thirteen claims carry that marker (§1.1 counts them, and each one names the missing proof rather than
   asserting the claim is false); F219's injection claim is the newest of the thirteen, withheld because
   `mydoc`'s three large modules were read only at the cited lines.
10. **The eight earliest zones rest on delegate read-claims this document cannot audit.** §9.1–§9.8 say "the
   delegate read all N files"; that is what the delegate reported, and unlike §9.9–§9.16 those zones carry no
   enumerated not-inspected list, so a file the delegate skipped would leave no trace here. What limits the
   exposure is the second half of the method — every High and Med in those zones names a line this author
   re-read — but the *absence* of findings in an unread corner of, say, `mail`'s 214 files or
   `core/base`'s 88 would not be detectable from this document. Re-running those eight zones with the
   §9.9-style statement is the only way to close it, and it is a reporting task, not a research one.

---

## 12. Suggested order of work

Ordered by what unblocks a truthful release statement, not by severity count. The dependency and CI
group comes first because every other verdict in this document is conditioned on it.

1. **Make the version story single-valued, then the gates honest.** One commit that regenerates
   `prod.lock` from `base.txt`/`production.txt` so `redis` and `gunicorn` agree (F166, F167), points CI
   at the lock instead of `testing.txt` (F168), re-locks `certifi` and `pillow` to clear F28, and
   deletes or fixes the permanently-green `npm test` line (F169). Then the mechanical lint commit for
   F17. Until this is done, CI's green badge describes a system that is not the one that ships.
2. **Decide whether the Android client can ship at all, then fix the four silent-loss defects.** F141,
   F143 and F144 lose user mail and report success while doing it; F139 sends `Bcc` recipients to the
   server; F142 lets authentication cross a connection the user believes is encrypted; F140 leaves the
   credentials in a plaintext store the keystore path was meant to replace. F146/F147 (a `commonMain`
   that cannot compile for the declared targets, and stub apps that are packaged anyway) mean the
   honest current status is "not releasable", and §9.11's evidence supports saying so out loud rather
   than shipping the stubs.
3. **Close the fail-open and cross-tenant paths server-side.** F26 (owner-scoped key lookup, no
   cross-owner secret in-session), F21 (`roles.py:74`/`:81`), F22 (pass the actor, or intersect both),
   F38 (role deletion mass-escalating through F21), then the trust-boundary pair F95/F96 and the
   storage-authorisation path F85. All are small diffs and all are the difference between "roles bind"
   and "roles are advisory".
4. **Make the backup chain real, then believe it.** This is the sweep's largest new set and the one that
   changes the release statement most, because on a default install every step of it is broken and every
   break prints a success. F192 (`backup_full.sh:57` guards the mail copy with a volume name this stack
   never creates and the `if` has no `else`, so the daily archive holds no mail), F193 (`make backup` —
   what `docs/dr-runbook.md` tells the operator to run — dies at step 1 because the script never passes
   `--env-file`), F194 (`BACKUP_ENCRYPT` defaults to `false` while the docs promise GPG), F195 (an archive
   it cannot decrypt prints `Backup complete` and writes `last-backup-at` *before* verifying, which is the
   file `system_health.py` reports from), F196 (the weekly drill hands `pg_restore` a host path no service
   mounts, so it can never pass), F197 (every SKIP and WARN is counted as a PASS), F198 (the drill leaves
   the decrypted plaintext, including `.env`, in `/backups` and then drills that file the following week),
   and the two tools an operator reaches for in an emergency: F199 (`uninstall.sh --keep-backups` deletes
   the key that opens the backups it kept) and F200 (`--remove-docker` deletes `/var/lib/docker`, i.e.
   every unrelated tenant's volumes, contradicting the script's own header). F201 belongs with them:
   `obtain-ssl.sh` deletes the live key, the archive and the renewal state of any certificate whose issuer
   string is not Let's Encrypt, on a copy made with `|| true`.
5. **Prove the installer and the recovery documentation before the next customer uses them.** F181 (publish
   a checksum or a tagged script URL and make both README paths verify it), F189 (the README's
   `scripts/backup_offsite.sh` does not exist; the runbook's does), F33 (the `storage upload` command
   cannot take a filename, and R1/R3 depend on it). These are the findings where "the docs say so" is
   the vulnerability.
6. **Decide, per control, whether it gets deployed or deleted.** A control that exists only as an
   unrunnable file reads to the next reviewer as coverage. F202 (fail2ban is installed by nothing, its
   jails point at `/var/log/mail.log` which this stack never writes, and all four filters are written
   against line formats the real logs do not produce — deploy it against the `test_mail_threats.py`
   fixtures or remove the directory), F203 (`firewall.sh` runs `ufw --force reset` at line 15 and asks
   permission at line 78, then reports its `DOCKER-USER` guard as applied whether or not a rule landed —
   and it is a second host firewall sitting on top of the product's own nftables `firewall` container, so
   pick one), F204 (`monitor.py` is scheduled by nothing and read by nothing except a service function
   whose only caller is itself, while `docs/enterprise-slo.md` already quotes its thresholds as the
   standard — either run it or re-point the SLO at `system_health.py`), F215 (outbound containment is
   shipped and on the beat, yet the governance documents list it as not built), and F222 (`COREDNS_IP` is
   written by all three generators and read by nothing).
7. **Input-to-sink fixes.** F154 (the setup wizard's provider field — validate against `PROVIDER_MAP`
   *before* it is echoed into the template, and fix the DOMContentLoaded auto-POST), F32/F129 (the
   `_WEB_FONTS` membership check on save in `views/branding.py:146-150`, then stop leaning on CSP as
   the only barrier), F127 (render `{{ secondaries|join:" " }}` or emit a `<textarea>` value through
   `linebreaks`), F158 (stop putting `str(exception)` in a public error page), F54 (the console's own
   IMAP client must verify certificates), F62 (an allow-list of hosts for the assistant's base URL),
   and the two `request.get_host` sites (F36, F137) on `{{ site_origin }}` — which is also the fix
   that makes `test_url_contract.py` able to see the pattern at all.
8. **Plugin engine integrity, as a set.** F68 (render and publish under the same lock as everything
   else), F69 (a row that fails to render must abort the render, not delete its setting), F70 (the
   validator returns a message; it does not raise), F75 (cache the rendered capability read).
   `publish_all()` is the one function in `core/plugins` that can overwrite another app's file, and all
   three Highs are in its path.
9. **Delivery correctness:** the missing claim in `ping()` (F24), the validated-IP pin or documented
   F30, the `allow_private` decision (F31), the webhook event duplication, then the Celery time limits
   and the re-render-per-chunk cost.
10. **Repair the test harness so it can fail loudly (F34, F36, and §9's read-but-not-run list), and get
   a runnable dev database (F20).** Apply the unapplied `mail`/`accounts` migrations locally so the
   webhook and campaign features can be exercised rather than only read; add
   `encoding='utf-8'` to the theme tests' `read_text()` calls, install `PIL` in dev/CI requirements so
   the profile-photo contract runs, stop asserting through `SETUP_REQUIRED_REDIRECT = False`, and add
   the render-level assertions F127/F135/F137 need — 74 of the 82 local failures and several entire
   gates are hiding behind the first three.
11. **Make every hand-maintained number derived.** F178 (capability count), F186 (edge-case tally and
   the `CT` citation column), F187 (the in-process target list and the missing `storage.objects` row),
   F188 (`max_length` rule), F190 (example count and page-size comment), F177 (three docs still saying
   v0.0.1), F175 (CHANGELOG against `git describe`), F37 and the `html_templates.md` row count. Each of
   these is one place where a doc asserts a count it cannot recompute; a CI step that regenerates the
   table from the registry kills the whole class. F227 is the same failure with ports instead of counts —
   993 and 587 are written in six places and a test pins two of them — so it belongs in this commit. Two
   one-file fixes from §9.16 ride along: wrap `password_reset_email.txt` so the plain-text half of the
   reset mail matches its own translated HTML part and subject (F226), and read `mail_host` from a setting
   production validates, with an explicit "ask your administrator" line when it is unset (F228).
12. **Documentation status, not content.** Label `docs/ifinmail_proposal.md` as the pre-0.0.1 design
    proposal (F182, F183) rather than rewriting it, delete or annotate the phantom deliverables in
    `REMEDIATION-MILESTONES.md` (F179) and the per-release evidence report that has never been written
    (F225), replace `.agents/skills/systematic-debugging/` with a project-local version since the shipped
    one is another project's skill and its worked example prints secret values (F224), drop the two
    documented patterns no template uses (F223), fix the `superpowers:*` references in the debugging skill
    (F174), move `IFINMAIL_API_TOKEN=` out of an `export` line in `docs/android-releases.md` (F173),
    resync the 36 diverged tags and move recovery refs out of `refs/tags/` (F19), and decide whether
    this assessment is tracked (F180) — an untracked findings file is how F99's log-token exposure gets
    rediscovered by the next reviewer.
