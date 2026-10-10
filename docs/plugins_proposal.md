# ifinmail Plugin Proposal — Creative Extensions for a Self-Hosted Mail Platform

**Status:** Draft for review
**Date:** 2026-10-10
**Scope:** `backend/apps/core/{plugin}/`, existing `accounts`, `devices`, `dns`, `domains`, `mail` apps
**Constraints:** Single VPS (2GB RAM target), Docker Compose, AGENTS.md architecture, DESIGN.md UI system

---

## 1. Executive Summary

ifinmail today is a solid foundation: Django + Postfix + Dovecot + Rspamd + PostgreSQL + Redis on Docker Compose, with domain/mailbox/alias management, DNS verification (Cloudflare, DigitalOcean, Porkbun), and a framework-free `.ifinmail-*` frontend.

It sends and receives mail reliably. It does not yet give users a reason to *leave* Gmail/Outlook.

This proposal defines a **plugin architecture** (no new framework — just disciplined use of the existing `hooks.py`, `tasks.py`, `assistant_handlers.py`, `services/`, `api.py`/`web.py` contract) and specifies **8 creative plugins** ranked by value/effort. The recommended first tranche is 3 plugins that run on the current VPS with no new containers:

1. **Burner Aliases with Expiry** — privacy differentiator, ~1 week
2. **Sieve Studio** — visual filter builder compiling to Dovecot Sieve, ~2 weeks
3. **Deliverability Guardian** — DNS + reputation + queue health dashboard with one-click fix, ~2 weeks

Second tranche adds product depth: Vault Drops, Nudge + Send Later, Newsletter Reading Mode, Mail-to-Webhook Flows, and Local-First Triage Assistant.

All plugins comply with:

- `AGENTS.md`: `api.py → viewsets/ → serializers/ → services/ → models/`, `web.py → views/ → forms/ → services/ → models/`, services-layer-only model access, fully typed `types/`, mandatory app skeleton.
- Storage rule: **no** `ImageField`/`FileField`; all files via `backend/apps/core/storage` (`StorageService`, `StoredFile` FK, `ImageAttachableMixin`/`FileAttachableMixin`).
- `DESIGN.md`: compact 36px controls, blue-means-interactive, `.ifinmail-*` prefix, light/dark/contrast tokens, settings hub catalogue in `backend/apps/accounts/services/settings_catalogue.py`.

---

## 2. Goals and Non-Goals

### Goals

- G1. Give self-hosters features Gmail cannot copy without violating privacy (local-only AI, expiring aliases, vault drops).
- G2. Reduce #1 churn driver: "mail goes to spam" via continuous deliverability guidance.
- G3. Reduce operational load: visual Sieve, webhook automation, scheduled/nudged sending.
- G4. Keep single-VPS deploy viable: Tranche 1 adds zero containers, <50MB RAM, only PostgreSQL tables + Celery beat tasks.
- G5. One API contract: every plugin action available via Django Ninja API *and* server-rendered web, powering future Android/Desktop clients.

### Non-Goals

- No calendar/contacts full suite (Phase 6 work, out of scope).
- No React/Vue/Svelte, no production CDN, no new JS build chain.
- No dedicated-IP pools or multi-tenant billing in this proposal.
- No replacement of Postfix/Dovecot/Rspamd — plugins orchestrate them via policy services, SQL maps, and milter/Sieve hooks.

---

## 3. Current-State Inventory (What Plugins Can Hook Into)

| Layer | Existing capability | Plugin hook point |
|---|---|---|
| `domains` | `Domain(name, verified, mx/spf/dkim/dmarc_verified)`, `DKIMKey(selector, private/public_key)` | Guardian reads verification flags; Burner Aliases reuses domain FK |
| `mail` | `Mailbox(domain, local_part, quota_bytes)`, `Alias(source, destination)` — unmanaged SQL maps for Postfix `virtual_mailbox_maps` / `virtual_alias_maps` | All mail plugins extend these; **do not fork** — add new tables with FKs |
| `dns` | `BaseDNSProvider` protocol (`configure_domain`, `verify_records`, `get_nameservers`), `DNSRecord`, providers for Cloudflare/DO/Porkbun | Guardian auto-fix; onboarding for new plugins |
| `core/storage` | `StorageService.upload(*, file, user, entity_type, entity_id)` with extension/MIME/size validation, 50MB cap; `StoredFile` model | Vault Drops, Newsletter cache, Triage attachments — **only** file path allowed |
| `accounts` | Settings catalogue (`settings_catalogue.py`), `admin/settings_base.html`, themes via `ifinmail-theme-init.js` | Every plugin registers 1 settings section, no bespoke settings pages |
| `devices` | Device registration/bootstrap manifest pattern | Nudge push, Vault share to device |
| Infra | Postfix (25/465/587) → Rspamd milter (11332) → Dovecot LMTP/IMAP; Redis + Celery; nginx TLS | Sieve deploy, hold-queue for Send Later, milter header for Newsletter detection |

Key finding: `hooks.py`, `assistant_handlers.py`, `tasks.py`, `signals.py` exist in every app but are currently placeholders (e.g. `mail/hooks.py` is one line). The plugin system is therefore **convention, not new code**: implement those files per spec below.

---

## 4. Plugin System Design (No New Framework)

### 4.1 Location rule

Per `AGENTS.md`, new product capability lives in `backend/apps/core/{plugin_name}/` with the mandatory skeleton:

```
backend/apps/core/{plugin}/
├── admin/ serializers/ services/ views/ viewsets/ tests/ fixtures/
│   forms/ types/ indexes/ mixins/ models/
├── api.py  apps.py  assistant_handlers.py  assistant.py
├── web.py  urls.py  verifications.py  preferences.py
├── tasks.py  signals.py  hooks.py
```

Rationale: `core/` = foundational, no external deps. Cross-app imports forbidden from `services.models` proxy — import from `models/` or the service module directly. CLI tooling is the only import exception (with comment).

### 4.2 Lifecycle contract

Each plugin implements up to 5 integration surfaces; omit what it does not need:

1. **`hooks.py` — mail pipeline hooks.** Pure functions called from delivery/auth events. Example:
   ```python
   # backend/apps/core/vault/hooks.py
   def on_message_delivered(*, message_id: str, mailbox_id: str) -> None: ...
   def on_alias_created(*, alias_id: str) -> None: ...
   ```
   Wired via Django `signals.py`, Rspamd milter header, or Postfix policy service — never by patching Postfix config inline.

2. **`tasks.py` — Celery tasks.** Expiry sweepers, digest builders, DNS re-checks. All idempotent, with `acks_late=True`, rate-limited per domain.
   ```python
   @shared_task(acks_late=True, max_retries=3)
   def expire_burner_aliases() -> int: ...
   ```

3. **`assistant_handlers.py` — AI/event actions.** Structured intents (`summarize.thread`, `nudge.suggest`) returning typed DTOs from `types/`. No raw prompt strings in views.

4. **`api.py` / `web.py` — dual surface.** `api.py` exposes Ninja router for Android/Desktop; `web.py` exposes server-rendered views using `forms/` → `services/`. Same `services/` function serves both.

5. **`preferences.py` + settings catalogue.** One entry in `settings_catalogue.py` per plugin (e.g. `vault`, `sieve`, `guardian`). Read-only pages use `EffectiveConfig` + `url_kwargs={'slug': ...}` pattern; secrets rendered as "Configured".

### 4.3 Frontend contract

- Templates extend `admin/settings_base.html`, define `settings_content`, set `active_section`.
- CSS only in `frontend/static/css/ifinmail-redesign.css` (loaded last), tokens from `ifinmail-variables.css` (`--ifinmail-*`). No literal colours; dark/contrast blocks required (enforced by audit test).
- Classes prefixed `.ifinmail-*` (e.g. `.ifinmail-vault-card`, `.ifinmail-guardian-badge`). Reuse `TablesRows`, `Dashboard`, `Settings` boards from `docs/html_templates.md`; update that file when adding templates.
- Run `.agents/skills/ifinmail-design-audit/scripts/audit.sh` before merge.

### 4.4 Data and typing rules

- Models inherit from `backend/apps/core/base/models/base.py` (UUID PK, timestamps, accountability mixins).
- All enums in `types/` (e.g. `AliasStatus`, `VaultAccess`, `GuardianSeverity`).
- Services are the **single** CRUD interface. Views/viewsets never touch `models/` directly.
- Files: `StoredFile` FK or `FileAttachableMixin`; never `FileField`.

### 4.5 Observability

Each plugin logs to existing `admin/logs.html` pipeline with `entity_type` = plugin name, exposes one Celery beat metric (queue length, expiry count, DNS fail count), and surfaces in `make health`.

---

## 5. Plugin Selection Criteria

| Criterion | Weight | Notes |
|---|---|---|
| Privacy differentiator vs Gmail | 25% | Local-only, expiry, self-hosted |
| Single-VPS cost (RAM/containers) | 20% | Tranche 1 must be ~zero |
| Churn reduction (deliverability, usability) | 20% | Guardian scores highest |
| API reusability (Android/Desktop) | 15% | All must expose `api.py` |
| Build effort (weeks, small team) | 10% | Prefer SQL + Sieve + Celery over new daemons |
| Abuse safety | 10% | Rate limits, trust levels from proposal §6 |

Scoring yields Tranche 1 = Burner Aliases, Sieve Studio, Deliverability Guardian.

---

## 6. Detailed Plugin Specifications

### P1. Burner Aliases with Expiry — `backend/apps/core/burner/`

**Problem.** Users reuse their real address for shops, trials, QR signups, then get spam forever. Gmail `+tagging` does not expire and is trivially stripped.

**Solution.** First-class expiring aliases: `shop-8f3a@domain → inbox@domain` with `max_uses`, `expires_at`, per-sender throttling. Share via copy/QR. Expired alias rejects at SMTP time (Postfix `check_recipient_access` SQL map) with a clean 550 + web explanation.

**UX.** `Settings → Aliases → New burner` (36px form: label, destination mailbox, expiry preset 1d/7d/30d/unlimited, max uses). List uses existing `TablesRows` board + `admin/partials/provider_row.html` pattern; status word-on-tint: `Active / Used up / Expired`. QR modal uses vanilla JS, no dep.

**API (Ninja).**
```
POST /api/v1/burner/ {label, mailbox_id, expires_in_days, max_uses} → {address, qr_svg_url}
GET  /api/v1/burner/ → [{id, address, uses, max_uses, expires_at, status}]
POST /api/v1/burner/{id}/revoke → {status}
```

**Data model.**
```python
class BurnerAlias(BaseModel):
    domain = FK(Domain, PROTECT)
    source = CharField(128)          # random slug, unique per domain
    destination_mailbox = FK(Mailbox, CASCADE)
    label = CharField(128)
    max_uses = IntegerField(null=True)
    use_count = IntegerField(default=0)
    expires_at = DateTimeField(null=True)
    status: types.BurnerStatus  # ACTIVE | EXHAUSTED | EXPIRED | REVOKED
    class Meta: unique_together = [("domain", "source")]
```
Reuse existing `aliases` SQL view: materialise active burners into Postfix lookup via `hooks.on_alias_saved`. Expired rows remain for audit but excluded from map.

**Services.** `BurnerService.create(user, ...)`, `.record_use()`, `.sweep_expired()` (Celery beat hourly). All typed; `record_use` increments atomically with `F()`.

**Security.** Random 8-char slug (`secrets.token_urlsafe`), rate-limit creation 20/day/user (Redis), sender throttling via Rspamd `ratelimit` module, no enumeration (550 message identical for unknown vs expired).

**Ops.** Zero containers. One beat task. `make health` checks map freshness.

**Effort:** S (5–7 days incl. tests + QR).

---

### P2. Sieve Studio — `backend/apps/core/sieve/`

**Problem.** Dovecot Sieve is powerful but raw. Users cannot write `require ["fileinto","vacation"]` safely; misconfiguration loses mail.

**Solution.** Visual rule builder (if/any/all → move/label/forward/vacation/reject) that compiles to validated Sieve, previews in plain English, versions every deploy, and pushes via `hooks.deploy_sieve(mailbox_id)`.

**UX.** `Settings → Filters` — rule rows (field, operator, value) + action rows, "Explain" line ("If sender contains @invoice… move to Finance"). Test-against-last-20 button (dry run, no side effects). Version history with one-click rollback.

**API.**
```
POST /api/v1/sieve/rules/compile {rules: [...]} → {sieve_source, explanation, warnings[]}
POST /api/v1/sieve/rules/deploy {mailbox_id} → {version, active}
GET  /api/v1/sieve/rules/test {mailbox_id, limit=20} → [{message_id, matched_rule, action}]
```

**Data model.**
```python
class FilterSet(BaseModel):
    mailbox = FK(Mailbox, CASCADE)
    version = IntegerField()
    rules_json = JSONField()   # typed schema in types/sieve_schema.py
    sieve_source = TextField()
    active = BooleanField(default=True)
```

**Services.** `SieveService.validate() → list[Warning]`, `.compile() → str` (allowlist of Sieve extensions: `fileinto, vacation, reject, envelope, subaddress`), `.deploy()` (writes via Dovecot Pigeonhole `sieve-connect` or managesieve lib, stores version). Block `redirect` to external domains unless admin-approved (abuse control).

**Security.** Strict allowlist, max 50 rules/set, max script 32KB, no `execute` extension. Deploy requires mailbox ownership check (`BaseAppPermissions`).

**Ops.** No daemon; uses existing Dovecot. Compile is pure Python (testable, no I/O).

**Effort:** M (10–14 days; compiler + UI + managesieve integration).

---

### P3. Deliverability Guardian — `backend/apps/core/guardian/`

**Problem.** "Mail goes to spam" is the top support ticket. SPF/DKIM/DMARC, PTR, blocklists, queue backpressure, cert expiry are checked manually today.

**Solution.** Continuous checker + one score + one next action. Hourly Celery checks per domain; dashboard badge (word-on-tint: `Healthy / Needs attention / Blocked`); one-click fix via existing DNS providers + `make provision` hints.

**UX.** Extends `admin/dashboard.html` (`Dashboard` board) + `admin/dns_config.html` (`DomainConfig` board). Per-domain row: MX/SPF/DKIM/DMARC/PTR/MTA-STS/TLS-RPT/blocklist/queue/certs as mono values, right-aligned numbers. Empty state: "Connect Cloudflare to auto-fix →" (single primary action per DESIGN.md).

**API.**
```
GET /api/v1/guardian/status → {score, checks: [{key, ok, detail, fix_url}], queue_len, blocklisted}
POST /api/v1/guardian/fix {domain, check_key} → {job_id, provider_result}
GET /api/v1/guardian/history?domain=&days=30 → {bounces, deferrals, complaints}
```

**Data model.**
```python
class DeliverabilityCheck(BaseModel):
    domain = FK(Domain, CASCADE)
    check_key: types.CheckKey  # MX, SPF, DKIM, DMARC, PTR, MTASTS, TLSRPT, BLOCKLIST, QUEUE, CERT
    ok = BooleanField()
    detail = TextField()
    checked_at = DateTimeField()
    class Meta: indexes = [Index(fields=["domain", "-checked_at"])]
```

**Services.** `GuardianService.run_all(domain)` fans out to `dns.providers.*.verify_records`, RBL DNSBL lookups (Spamhaus/Barracuda, cached 1h in Redis), Postfix `mailq` parse, cert expiry parse. `FixService` reuses `configure_domain` for DNS-fixable checks; PTR/cert/queue return runbook links, never fake auto-fix.

**Security/Abuse.** Read-mostly; fix path requires domain ownership + rate limit 5/hour. No DKIM private key exposure (public key only in UI).

**Ops.** One beat schedule (hourly per domain, jittered). Stores 90d history, aggregates for bounce/deferral trends feeding proposal §6.5 dashboard.

**Effort:** M (10–14 days; RBL + queue parsing + provider fix paths).

---

### P4. Vault Drops — `backend/apps/core/vault/`

**Problem.** 25MB attachment limits, VPS quota exhaustion, insecure forwarding of PDFs/ZIPs.

**Solution.** Send-as-link: upload via `StorageService.upload(entity_type='VAULT')`, get `https://mail.domain/f/{token}` with expiry + optional password + download cap. Recipient downloads without an account; sender tracks views.

**UX.** Compose → Attach → "Send as Vault link" toggle. `.ifinmail-vault-card` shows filename (mono), size, expiry, views remaining. Download page is public, minimal, single primary action.

**API.**
```
POST /api/v1/vault/ {stored_file_id, expires_in_days, max_downloads, password?} → {url, token}
GET  /f/{token} → file stream (password gate if set)
GET  /api/v1/vault/ → [{filename, downloads, expires_at}]
```

**Data model.**
```python
class VaultDrop(BaseModel, FileAttachableMixin):
    stored_file = FK("storage.StoredFile", PROTECT)  # AGENTS.md explicit-FK pattern
    token = CharField(64, unique=True)
    password_hash = CharField(128, null=True)  # Argon2id
    max_downloads = IntegerField(null=True)
    download_count = IntegerField(default=0)
    expires_at = DateTimeField()
```

**Compliance.** Only path using `StorageService`; respects 50MB cap + MIME allowlist; password hashing via Django auth hashers; sweep task deletes expired `StoredFile` rows + objects.

**Effort:** S (5–8 days).

---

### P5. Nudge + Send Later — `backend/apps/core/nudge/`

**Problem.** No scheduled send, no follow-up reminders — table stakes vs Gmail/Outlook.

**Solution.** `Send at…` holds message in Postfix hold queue (or Django outbox for API-sent mail) until Celery ETA; `Nudge me if no reply in N days` creates a tracked follow-up task checking `In-Reply-To` threading.

**API.**
```
POST /api/v1/send/schedule {draft_id, send_at} → {scheduled_id}
POST /api/v1/nudge {thread_id, wait_days} → {nudge_id}
DELETE /api/v1/send/schedule/{id} → {cancelled}
```

**Data model.** `ScheduledSend(draft_ref, send_at, status)` + `FollowUpNudge(thread_id, wait_until, done)`. Both idempotent with client-supplied idempotency keys (per proposal §7.1).

**Ops.** Celery ETA + Redis; no new daemon. Hold-queue integration via Postfix `postsuper` wrapper in provisioning script (documented, audited).

**Effort:** S-M (7–10 days).

---

### P6. Newsletter Reading Mode — `backend/apps/core/newsletter/`

**Problem.** Newsletters clog the inbox; Gmail's Promotions tab is opaque.

**Solution.** Rspamd milter adds `X-ifinmail-List: 1` when `List-Unsubscribe` present + low spam score. `hooks.on_message_delivered` files into `Newsletters` mailbox (auto-created). Weekly digest task renders clean excerpt view (cached HTML via storage, stripped trackers).

**Privacy.** Strip 1px trackers + `utm_*` at render time (Rust `mail-parser` later, regex allowlist now). Unsubscribe link surfaced as primary button — never auto-clicked.

**Effort:** S (5–7 days).

---

### P7. Mail-to-Webhook Flows — `backend/apps/core/flows/`

**Problem.** Self-hosters glue mail to n8n/Home Assistant/invoicing manually.

**Solution.** Minimal Zapier: `when <Sieve-matched mail> then POST JSON / save attachment / create task`. Reuses Sieve match output; actions run in Celery with HMAC-signed webhooks, retry + DLQ.

**API.**
```
POST /api/v1/flows/ {name, filter_set_id, action: {type: webhook|save, url?, entity_type?}, secret} → {id}
POST /api/v1/flows/{id}/test → {last_run, ok}
```

**Security.** SSRF allowlist (no 169.254.0.0/8, no localhost unless admin), per-flow rate limit, secret rotation, audit log entries.

**Effort:** M (10–12 days).

---

### P8. Local-First Triage Assistant — `backend/apps/core/triage/`

**Problem.** AI summarisation normally means sending mail to a third party — unacceptable for a privacy product.

**Solution.** Optional Ollama sidecar (`provisioning/docker/ollama.yml`, off by default). `assistant_handlers.summarize_thread` + `draft_reply` + `extract_tasks` run locally; if sidecar absent, UI degrades to extractive (subject/entities/dates) summary with clear messaging. No mail leaves the VPS in either mode.

**API.**
```
POST /api/v1/triage/summarize {thread_id} → {summary, action_items[], dates[]}
POST /api/v1/triage/draft {thread_id, tone} → {draft}
```

**Data.** No new PII tables; cache summaries 24h in Redis keyed by thread hash. Audit every AI call.

**Effort:** M-L (2–3 weeks incl. prompt evals + graceful-degradation UI).

---

## 7. Roadmap

### Phase A — Tranche 1 (4–5 weeks, current VPS, no new containers)

- Week 1: P1 Burner Aliases (models, Postfix map hook, QR UI, tests).
- Weeks 2–3: P2 Sieve Studio (compiler + deploy + dry-run).
- Weeks 3–4: P3 Guardian (checks + dashboard + Cloudflare/Porkbun auto-fix).
- Week 5: Hardening — `ruff`, `mypy django-stubs`, `pytest`, design audit, `make health` integration, docs update.

Exit criteria: all three behind feature flags, settings catalogue entries, API + web parity, SBOM unchanged (no new prod deps).

### Phase B — Depth (6–8 weeks)

P4 Vault → P5 Nudge → P6 Newsletter → P7 Flows. Each ships independently; Vault unblocks attachment-quota complaints, Nudge closes Gmail parity gap.

### Phase C — Differentiator (after B)

P8 Triage with Ollama sidecar + Rust `mail-parser` evaluation. Requires docs on VRAM/RAM sizing and opt-in consent screen.

---

## 8. Cross-Cutting Requirements

- **Typing:** `mypy` clean; DTOs in `types/`, no `Any` in services.
- **Tests:** `tests/test_models.py`, `test_services.py`, `test_views.py` per app; compiler/guardian logic >85% coverage; Sieve deploy + Postfix map covered by integration test with fake managesieve.
- **Security:** Argon2id for Vault passwords; `BaseAppPermissions` on every viewset; per-user/domain/IP rate limits in Redis; SSRF/RBL safeguards; signed webhook payloads.
- **Supply chain:** No new prod npm; Python deps pinned in `requirements/base.txt`; SBOM regenerated per release; signed commits.
- **Design:** One primary action/screen, word-on-tint status, mono for DNS/hosts/numbers, `audit.sh` + axe in light/dark/contrast before merge. Update `docs/html_templates.md` when adding templates.
- **Docs:** Each plugin adds `AGENTS.md`-style header comment in `services/` + one `frontend/templates/admin/settings_*.html` help block.

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Postfix map staleness (burner expiry) | Expired alias still delivers | Materialised view + `hooks` sync on save + hourly sweeper + `postmap` in deploy script; health check alerts if map older than 15m |
| Sieve miscompile loses mail | Data loss | Allowlisted extensions, dry-run tester, versioned rollback, `reject` only to authenticated senders |
| RBL rate limits / false positives | Guardian noise | 1h Redis cache, 2-source confirmation before `Blocked` status |
| Vault quota abuse | Disk exhaustion | Reuse 50MB cap, per-user quota (reuse `Mailbox.quota_bytes`), expiry sweep deletes objects |
| Ollama RAM blowout | VPS OOM | Off by default, separate compose profile, RAM gate in setup wizard |
| Scope creep into calendar/full CRM | Timeline slip | Explicit non-goal; Flows covers integration without building calendar |

---

## 10. Success Criteria

- A user creates a burner alias, shares QR, watches it expire without code changes to Postfix master config.
- A non-technical user builds a filter in Sieve Studio and dry-runs it against real mail.
- A domain admin sees Guardian go from red to green after one-click Cloudflare fix, with SPF/DKIM/DMARC verified.
- `make health` covers all three; `pytest`, `ruff`, `mypy`, design audit pass; single-VPS RAM delta <100MB.
- API contract for each plugin generates usable Android/Desktop bindings (OpenAPI via Ninja).

---

## 11. Appendix — Scaffold Commands

```bash
# New plugin skeleton (repeat per P1–P8)
mkdir -p backend/apps/core/burner/{admin,migrations,models,serializers,services,views,viewsets,tests,fixtures,forms,types,indexes,mixins}
touch backend/apps/core/burner/{api.py,apps.py,assistant_handlers.py,assistant.py,web.py,urls.py,verifications.py,preferences.py,tasks.py,signals.py,hooks.py}

# Register in settings + URLs, add catalogue entry, add templates:
#  frontend/templates/admin/settings_burner.html
#  frontend/templates/admin/partials/burner_row.html
# Then: make migrate; if ($?) { pytest backend/apps/core/burner -q }
```

Vault upload (canonical pattern — copy, do not invent a second uploader):

```python
from backend.apps.core.storage.services import StorageService
result = StorageService.upload(
    file=uploaded_file,
    user=request.user,
    entity_type="VAULT",
    entity_id=str(drop.id),
)
```

---

## 12. Recommendation

Approve **Tranche 1 (P1–P3)** for immediate build. They are the cheapest path to "why self-host ifinmail instead of Gmail": private expiring addresses, usable filters, and mail that actually reaches the inbox. Tranche 2/3 follow on the same plugin contract without rework.
