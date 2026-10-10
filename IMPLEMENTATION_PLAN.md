# ifinmail — 10 Special Features: Implementation & Test Plan
**Wave-based, protocol-first, capability-gated**

> Builds on `:core` ports (`core/domain/port/Ports.kt`) + `:mail` adapters + `DomainEventBus` + Gmail UI already shipped (Material Icons, 42 unit + 12 UI green, live `mail.ifinsta.com` 4/4).

---

## 0. Principles (all features)

* **Port before implementation** — domain defines `Capability`, adapter implements it. No `if provider ==` in `domain/` or `ui/` (§63 lint).
* **Capability-gated UI** — `if (capabilities.has(MAIL_SCHEDULE)) showButton else hide` (§11).
* **Offline-first** — local `MailStore` + `MutationQueue` (`mail/store/MutationQueue.kt`) + `flushMutations()` on reconnect (§23/24).
* **Test pyramid** — unit fixtures → contract over `FakeTransport` → capability-matrix fakes → live `LiveServerIT` (`mail/src/test/.../LiveServerIT.kt` with `IFINMAIL_LIVE=1`) → instrumented `app:androidApp:connectedDebugAndroidTest`.

---

## Wave 1 — Foundation (Sprint 1, 2 weeks)

### 1. Unified Threads
*Domain:* `MailThread` already added `core/domain/model/DomainModels.kt:51` + `ThreadResolver` `core/domain/thread/ThreadResolver.kt` — normalized subject `re:/fwd:` stripping, `computeThreadId(accountId, subject, messageId, references)`, `groupIntoThreads()`.
*Store:* `StoredMessage.threadId` + `messageIdHeader` new fields (defaults keep old JSON readable).
*Engine:* `MailEngine.sync()` computes `threadId` for each `ChangeSet` message before persist.
*UI Inbox* `InboxScreen.kt`: toggle `Grouped by thread` (default on) — when on, `LazyColumn` shows `ThreadRow` (subject, `count`, `unreadCount`, `participants.take(3)`, latest snippet) instead of flat `GmailMessageRow`. Tap thread → Detail shows horizontal `ThreadStrip` (avatars + dates) to navigate within thread.
*Test:* `ThreadResolverTest` — fixtures for `Re:`, `Fwd: Re:`, `[List]` prefixes, cross-account isolation. UI: `InboxScreenTest` with 3 messages sharing normalized subject → asserts one `ThreadRow` with `count=3` and `unreadCount=1`.

### 2. On-Device AI Triage (LocalClassifier)
*Port:* `MessageClassificationService` `core/domain/triage/Classification.kt` — `TriageCategory {URGENT/FINANCIAL/MEETING/ACTION/SOCIAL/UPDATES/PROMOTIONS/GENERAL}` + `TriageResult`.
*Adapter:* `LocalClassifier` rule-based (keyword lists, already implemented, confidence 0.5-0.9). Future swap: `RemoteClassifier` behind same port.
*Store:* `StoredMessage.triageCategory` / `triagePriority` (added).
*Engine:* `sync()` classifies each new message, persists fields.
*UI:* `StatusBadge` tint per category (Urgent=Red, Financial=Amber...), filter pills `Inbox` + `Urgent`/`Financial`... — visible only if `capabilities` non-empty or local classifier present (always). `queuedCount` pill already shows offline.
*Test:* `LocalClassifierTest` — 7 keyword fixtures. UI: filter pill click → `LazyColumn` count changes. Capability matrix: account without `MAIL_CLASSIFY` hides pills.

### 3. Semantic Search (FTS + MailQuery)
*Port:* `MessageSearchCapability` — `MailQuery` `core/domain/search/MailQuery.kt` already added: `text, from:, to:, subject:, has:attachment, is:unread/starred/urgent, category:, in:, before:, after:` + `MailQueryParser.parse()` + `MailQuery.matches()`.
*Store:* in-memory filter for MVP (already wired via `matchesQuery` → replace with `MailQuery.matches`); next: SQLite FTS `messages_fts`.
*UI:* Search bar `testTag search-inbox` already filters via `matchesQuery` — swap to `MailQueryParser.parse(searchQuery).let { q -> messages.filter { q.matches(it) } }`. Add hint: type `is:unread has:attachment` shows chips.
*Test:* `MailQueryParserTest` — 10 query strings → expected fields. UI: type `is:unread` → only unread rows remain. Perf: search 5k in-memory <50ms.

---

## Wave 2 — Temporal (Sprint 2)

### 4. Scheduled Send
*Port:* `ScheduledSubmissionCapability`
*Adapter:* IMAP: local `WorkManager` enqueue `PendingMutation(SEND, scheduledAt)`; JMAP: server `EmailSubmission` delay. Reuses `MutationQueue`.
*Store:* `PendingMutation.scheduledAtMs`.
*UI:* Compose `Schedule send` icon (`Icons.Default.Schedule`) next to `Send` — visible only `MAIL_SCHEDULE` else hidden. Picker → `DatePicker` + `TimePicker`.
*Test:* unit enqueue with future time → not flushed until due. WorkManager `TestListenableWorkerBuilder`.

### 5. Undo Send
*Extends* `MutationQueue` — `send()` already queues on `isTransient`; now always queues with 10s `scheduledAt` = now+10s, `flushMutations()` respects delay. Snackbar `Undo` removes mutation.
*Test:* send → `queuedCount==1` pill visible 10s → disappears after flush or Undo removes. UI: `Snackbar` with `Undo` action.

### 6. Snooze
*Adapter:* local re-enqueue + `AlarmManager` re-deliver.
*Test:* swipe → row gone → appears after snooze time.

---

## Wave 3 — Ownership & Composition (Sprint 3)

### 7. Smart Reply/Draft
*Port:* `DraftCapability` — takes `Thread` + `Identity`
*Adapter:* local template + optional remote LLM.
*Test:* `DraftTest` — thread with 2 msgs → draft contains quoted `On ... wrote:`.

### 8. Confidential Mode (Expiry Vault)
*Model:* `Attachment.contentReference` already exists `CoreModels.kt` — store bytes via expiring URL, not in IMAP `BODY`.
*Test:* vault round-trip, 403 after expiry.

### 9. Attachment Vault OCR
*Adapter:* `Tika`/`ML Kit` consuming `DomainEvent.AttachmentDownloaded`.
*Test:* PDF fixture → `attachments_ocr_text` searchable.

### 10. Calendar/Contacts Composition
*New modules* `protocols/caldav,carddav` implementing `CalendarCapability`/`ContactCapability`. `AccountRuntime` composes per-function hosts (§46). Navigation `Mail/Calendar/Contacts` gated `capabilities`.
*Test:* matrix accounts D/E.

### 11. Time-Travel Export (bonus, proves §55)
Settings → Export MBOX/MIME + vCard/iCal. Round-trip `MimeParser` → MBOX → re-parse counts match.

---

## Test Execution

```powershell
.\gradlew.bat :mail:test --rerun-tasks          # 42 → ~90 after Wave 1
.\gradlew.bat :app:shared:compileKotlinJvm      # KMP common
.\gradlew.bat :app:androidApp:assembleDebug
$env:ANDROID_SERIAL='emulator-5554'; .\gradlew.bat :app:androidApp:connectedDebugAndroidTest  # 12 → 28
$env:IFINMAIL_LIVE='1'; .\gradlew.bat :mail:test --tests "*LiveServerIT"  # against mail.ifinsta.com test1/test2 Kenya@12
```

*Contract:* `MailRepositoryContractTest` param over `ImapAccessAdapter(FakeTransport)` + `Pop3AccessAdapter(FakeTransport)` (§60).
*Live:* E2E `test1 SMTP→ test2 IMAP` already 4/4; extend for 3,6,5.

---

## Rollout

Feature flag = `KnownCapability`. Telemetry `protocol=imap op=mail.query` (§59). Rollout: `local` → `internal ifinsta` → 5% → 100%. `UnsupportedCapability` hides UI, never crashes.

**Status:** Wave 1 domain models + ports already landed in this commit series (`ThreadResolver`, `LocalClassifier`, `MailQuery`). Next commits wire Engine → UI.
