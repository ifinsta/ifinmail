# Architecture Review — ifinmail Android Client
### Against: *Protocol-First & Temporally Composable Application Architecture Guide*
Date: 2026-08-23 · Scope: `clients/android` · Verified against working code + live-server validation

---

## Verdict

**Constitutional compliance: ~45%.** Strong protocol core; missing domain/application layers.
Every violation is refactorable without touching validated protocol code.

## Scorecard

| Principle | Status | Evidence |
|---|---|---|
| §2/§7 Canonical concepts, no provider loyalty | Partial | Near-canonical models, but `IncomingProtocol` enum leaks into domain + UI types |
| §8 DTO→mapper→canonical | Pass | `MimeParser.parseMessage → StoredMessage`; FETCH items never escape `ImapClient` |
| §9 Stable internal IDs | Violation | `"${accountId}-${uid}"` / `"${accountId}|$uidl"` provider-derived IDs |
| §10–13 Capability discovery/degradation | Missing | CAPABILITY fetched then discarded; no `AccountCapabilitySet`; features gated by protocol enum |
| §14/47/48 Config as data, discovery-first | Partial | Presets pre-populate only (letter of §48 OK); table lives in source; no MX/SRV/autoconfig/.well-known tiers |
| §15/63 No provider branching | Pass / Violation | UI: zero provider checks ✓. Core: 9 `when(incoming.protocol)` sites in `MailEngine` |
| §21/22 Sync first-class, change-based | Partial | UID watermark ✓, UIDVALIDITY reset ✓; cursor fields loose on `Account`; no SyncEngine/ChangeSet |
| §23/24 Offline-first, durable mutations | Violation | Offline send loses drafts; no mutation queue (unused `outbox` field in store). Rule 8 breached |
| §26 Neutral local storage | Partial | Neutral names; adapter metadata mixed into canonical rows |
| §28 Identity ≠ Account | Missing | Single identity hardwired |
| §29 Folders vs roles | Violation | 13 hardcoded mailbox-name sites incl. `append("Sent", …)` |
| §31 Composer → Draft | Pass | `OutgoingDraft` pure domain |
| §32 Attachments as resources | Missing | Names only; no id/mediaType/contentReference |
| §33–35 Domain events | Missing | None |
| §41/42 Volatility gradient, layout | Violation | Contract owned by UI module; god-class engine; no domain module |
| §43/44 Ports & capability interfaces | Missing | Concrete `MailEngine`; JMAP adapter has nowhere to plug in |
| §46 Runtime composition | Partial | Separate endpoints ✓; single shared credential |
| §56/57 Security, secrets referenced | **Worst violation** | Plaintext credentials serialized inside Account JSON; no CredentialStore |
| §58 Error normalization | Missing | Raw exception strings reach UI |
| §60–62 Testing strategy | Partial | Excellent scripted-transport tests + live IT; no cross-adapter contract suite yet |
| §64/65 Platform/SDK leakage | Pass | Clean `MailTransport` seam; no platform conditionals |
| §55 Data ownership/export | Missing | Proprietary JSON only |

Tally: 5 pass · 6 partial · 12 missing/violating (24 clusters assessed).

## Credited strengths
1. Hand-built protocols = Rule 4 fully realized; future adapters are pure clients.
2. `MailTransport` exemplifies the Two-Implementation Rule (§38) — proven by `FakeTransport`.
3. UI completely provider-blind (§15 passes today).
4. Presets-as-data discipline correct in shape.

## Remediation roadmap

**Phase 1 — Domain extraction (no behavior change)** ← *implemented in this commit series*
- `:core` repurposed as KMP domain module: canonical models, ports (`MailAccessAdapter`,
  `SubmissionAdapter`, `CredentialStore`, `AutoConfigSource`), `KnownCapability` set,
  `MailError` taxonomy, `DomainEventBus`, `MailboxRole`, `RemoteReference`, `Identity`, `Attachment`
- `MailEngine` → application orchestrator; protocol dispatch replaced by an adapter registry
  (single selection site, per §43)
- IMAP/POP3/SMTP wrapped as adapters; capabilities discovered at probe (IDLE→`MAIL_PUSH`, MOVE→…)
- `FileCredentialStore` behind the port (Keystore swap = drop-in later)
- Mailbox ROLE resolution (IMAP SPECIAL-USE with name fallbacks) replacing hardcoded names
- Domain events published (`MessageReceived`, `MessageSubmitted`, `SyncCompleted`, `SyncFailed`)
- Error normalization at adapter boundaries
- Legacy compatibility: `com.ifinmail.mail.model` kept as typealiases; store JSON stays readable

**Phase 2 — Constitutional repairs**
- Android Keystore-backed `CredentialStore` (drop-in behind port)
- Internal UUID `MessageId` + `RemoteReference`; store migration
- Durable mutation queue (finish `outbox`): offline send/mark/delete flush on reconnect
- `SQLDelight/Room` store; SQLDelight schema mirrors §26 table list
- `Identity[]` on accounts; attachment resources

**Phase 3 — Discovery & breadth**
- Discovery pipeline ahead of presets: DNS MX (proven vs `ifinsta.com`) → RFC 6186 SRV →
  autoconfig/auto-discover → `.well-known/jmap`; presets move to resource JSON
- Second adapter through shared `MailRepositoryContractTest` (§60)
- Capability-matrix fakes (§61); HTML rendering; attachments; IDLE background sync

## Transitional notes
- `Account.sync` defaults reset UID cursors once for pre-existing installs (safe re-fetch, deduped).
- Credentials remain dual-written (JSON field + credential store) during Phase 1; Phase 2 removes the plaintext copy.
