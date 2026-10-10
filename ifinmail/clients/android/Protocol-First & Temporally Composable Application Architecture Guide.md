# Protocol-First & Temporally Composable Application Architecture Guide

## 1. Purpose

This guide defines the architectural rules for building applications that operate consistently across:

- Web
- Android
- Windows
- Linux
- macOS
- iOS
- Tablets
- Embedded clients
- Future surfaces not yet designed

The architecture MUST NOT be structurally loyal to:

- a particular service provider;
- a particular operating system;
- a particular identity system;
- a particular synchronization implementation;
- a particular server configuration;
- a particular UI framework;
- a particular deployment model.

The product is instead built around **stable domain concepts, open protocols, discoverable capabilities, and replaceable adapters**.

The objective is not merely portability today.

The objective is **temporal composability**: components created at different times, for different environments, should continue composing without requiring the entire application to be redesigned around whatever provider, platform, or API happens to dominate at that moment.

---

# 2. Foundational Principle

> **Protocols define capabilities. Providers merely implement them. Platforms merely surface them.**

The application should therefore think in concepts such as:

- Message
- Mailbox
- Thread
- Identity
- Contact
- Calendar
- Event
- Attachment
- Draft
- Submission
- Search
- Synchronization
- Notification
- Credential
- Capability
- Account

It should NOT think in concepts such as:

```text
ProviderAMessage
ProviderBMailbox
WindowsAccount
AndroidMail
ProviderCFolder
ProviderDContact
```

Those are implementation details.

The core application should ideally be unable to determine which commercial service is behind an account unless a diagnostic or configuration interface explicitly requires that information.

---

# 3. Temporal Composability

Temporal composability means designing components so that they can evolve independently across time.

A component written today should remain useful when:

- another protocol revision appears;
- a new service implements the same protocol;
- an existing service stops supporting a feature;
- an operating system changes;
- the UI framework is replaced;
- authentication mechanisms evolve;
- synchronization moves from polling to push;
- a cloud service becomes self-hosted;
- an account moves between servers;
- a new device class appears.

Therefore:

```text
CURRENT CONFIGURATION
        ↓
Capability Discovery
        ↓
Protocol Adapters
        ↓
Canonical Domain Model
        ↓
Application Capabilities
        ↓
UI / Automation / AI / Native Surfaces
```

The current server configuration is temporary.

The domain model is durable.

---

# 4. Architectural Invariant

Every feature should pass this test:

> **If the underlying service were replaced tomorrow by another standards-compatible implementation, how much application code would change?**

The desired answer is:

> Only configuration and, where necessary, the protocol adapter.

The following should NOT require changes:

- message list UI;
- conversation UI;
- composer;
- search UI;
- contacts UI;
- calendar UI;
- account UI;
- command system;
- offline database;
- business logic;
- notification logic;
- domain entities.

---

# 5. Recommended Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                     USER SURFACES                       │
│                                                         │
│ Web │ Android │ Windows │ iOS │ Desktop │ Future UI    │
└──────────────────────────┬──────────────────────────────┘
                           │
                    Application Intents
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 APPLICATION SERVICES                    │
│                                                         │
│ Compose │ Search │ Sync │ Contacts │ Calendar │ Rules  │
└──────────────────────────┬──────────────────────────────┘
                           │
                    Domain Contracts
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 CANONICAL DOMAIN CORE                   │
│                                                         │
│ Message      Mailbox       Thread       Identity        │
│ Contact      Calendar      Event        Attachment      │
│ Capability   Account       Change       Submission      │
└──────────────────────────┬──────────────────────────────┘
                           │
                  Protocol Abstractions
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Mail Access       Calendar         Contacts
          │                │                │
          ▼                ▼                ▼
       Adapters          Adapters          Adapters
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  NETWORK PROTOCOLS                      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                  Any Compatible Server
```

Notice that neither the user interface nor the domain layer contains a concept of a specific provider.

---

# 6. Core Protocol Baseline

The architecture should prefer interoperable protocols wherever practical.

## Mail

Primary concepts:

```text
Mail access
Mail synchronization
Message submission
Message representation
Attachments
Threads
Folders/mailboxes
Search
State changes
```

Protocol families:

- JMAP
- IMAP4rev2
- SMTP Message Submission
- Internet Message Format
- MIME

JMAP is particularly valuable as a modern synchronization protocol because it defines capability discovery, state-based synchronization, batching, and efficient data exchange.

IMAP4rev2 remains an important interoperable mail-access protocol and explicitly supports offline clients resynchronizing with servers.

Message submission should remain conceptually separate from message storage/access. The standardized submission architecture explicitly separates submission from mail relay.

---

## Calendar

Canonical concepts:

```text
Calendar
Event
Participant
Recurrence
Availability
Reminder
Scheduling
```

Protocol/data families:

- CalDAV
- iCalendar

CalDAV standardizes access and management of calendar information, while iCalendar provides a service-independent representation of events, tasks, free/busy information, and related scheduling data.

---

## Contacts

Canonical concepts:

```text
Contact
ContactCollection
Name
Address
Phone
EmailAddress
Organization
Avatar
Relationship
```

Protocol/data families:

- CardDAV
- vCard

CardDAV provides interoperable address-book access while vCard defines the portable contact representation.

---

## Identity and Authorization

Canonical concepts:

```text
Identity
Principal
Authorization
Credential
Session
Scope
Token
Account
```

Prefer:

- OAuth
- OpenID Connect where identity assertions are required
- Authorization-server metadata
- Standards-based discovery
- PKCE where applicable

Do not hard-code authentication endpoint URLs where discovery is available.

Authorization-server metadata exists specifically so clients can discover endpoint locations and authorization capabilities.

---

## General Network Resources

Use:

- HTTP semantics
- HTTPS
- URI-based resource identification
- standardized media types
- structured representations

HTTP's uniform interface deliberately separates resource interaction from the implementation behind the resource, making it particularly aligned with this architecture.

---

# 7. Protocol Preference Is Not Protocol Loyalty

Protocol-first architecture does **not** mean hard-coding the product to one protocol.

For example, the application should not expose:

```text
JmapMailboxScreen
ImapMailboxScreen
```

It should expose:

```text
MailboxScreen
```

behind:

```text
MailRepository
```

which could currently be backed by:

```text
JmapMailAdapter
```

or:

```text
ImapMailAdapter
```

The UI does not care.

---

# 8. Canonical Domain Model

Every protocol adapter MUST translate remote representations into a canonical domain model.

Example:

```text
Remote Protocol
      ↓
Protocol DTO
      ↓
Protocol Mapper
      ↓
Canonical Message
      ↓
Domain Services
      ↓
UI
```

A canonical message might conceptually contain:

```text
Message
├── id
├── accountId
├── threadId
├── mailboxIds[]
├── from[]
├── to[]
├── cc[]
├── bcc[]
├── subject
├── preview
├── body[]
├── attachments[]
├── flags
├── receivedAt
├── sentAt
└── metadata
```

Do not reproduce a remote provider's JSON structure directly in the domain model.

---

# 9. Stable Internal IDs

Internal IDs should never derive their meaning from a provider.

Avoid:

```text
providerMessageId
providerThreadId
providerFolderId
```

Prefer:

```text
RemoteReference {
    protocol
    accountId
    resourceType
    remoteId
}
```

And internally:

```text
MessageId
ThreadId
MailboxId
AccountId
```

This allows one local entity to remain stable even if its external representation changes.

---

# 10. Capability-Driven Architecture

The client should ask:

> What can this account do?

Not:

> Which company hosts this account?

A capability document could conceptually expose:

```json
{
  "mail.read": true,
  "mail.send": true,
  "mail.search": true,
  "mail.threads": true,
  "mail.push": true,
  "mail.schedule": false,
  "calendar.read": true,
  "calendar.write": true,
  "contacts.read": true,
  "contacts.write": false
}
```

The UI then derives behavior from these capabilities.

---

# 11. Capability Negotiation

Never assume a feature exists.

At connection time:

```text
Connect
   ↓
Discover endpoints
   ↓
Discover protocols
   ↓
Discover extensions
   ↓
Discover capabilities
   ↓
Construct AccountCapabilitySet
   ↓
Activate supported functionality
```

Example:

```text
if capabilities.contains(MAIL_SCHEDULE_SEND)
    expose scheduling controls
else
    omit scheduling controls
```

Do NOT use:

```text
if provider == "Provider X"
    showScheduleSend()
```

This distinction is fundamental.

---

# 12. Extensions Must Be Namespaced

Some servers will support functionality beyond the core specification.

That is acceptable.

Represent extensions as:

```text
Capability
├── namespace
├── name
├── version
├── parameters
└── constraints
```

For example:

```text
core.mail.send
core.mail.search
core.calendar.events

extension.example.smart-sort
extension.example.large-attachment
```

Extensions can enrich the application.

They must never redefine the core.

---

# 13. Graceful Capability Degradation

Optional features should degrade safely.

Suppose one server supports:

```text
scheduled sending
```

and another does not.

The application should remain fully functional.

```text
Capability available
      ↓
Render feature

Capability unavailable
      ↓
Hide / disable / provide alternative
```

Unsupported extensions must never prevent core functionality.

---

# 14. Provider Configuration Is Data

Server configuration should be represented as runtime data.

For example:

```text
AccountConfiguration
├── identityEndpoint
├── mailEndpoint
├── submissionEndpoint
├── calendarEndpoint
├── contactsEndpoint
├── discoveryEndpoint
├── securityRequirements
└── protocolCapabilities
```

This configuration may originate from:

- automatic discovery;
- DNS/service discovery;
- well-known endpoints;
- QR provisioning;
- configuration file;
- administrator policy;
- manual configuration.

It should not originate from application source code.

---

# 15. Never Encode Provider Logic Into UI Components

Forbidden:

```text
if account.provider == ...
```

inside:

```text
MailboxScreen
Composer
ContactPicker
MessageReader
CalendarScreen
```

The UI should operate on capabilities and domain state:

```text
if account.capabilities.canScheduleSubmission
```

This ensures complete separation between UX and provider implementation.

---

# 16. Platform Neutrality

The same principle applies to operating systems.

The core must not know whether the application currently runs on:

```text
Android
Windows
Linux
iOS
Web
```

Platform-specific behavior belongs behind platform adapters.

---

# 17. Platform Adapter Layer

Create abstract system capabilities such as:

```text
SecureStorage
FilePicker
NotificationService
ShareService
ClipboardService
BiometricService
BackgroundTaskService
NetworkMonitor
DeepLinkService
WindowService
```

Then implement:

```text
AndroidSecureStorage
WindowsSecureStorage
WebSecureStorage
```

behind:

```text
SecureStorage
```

Domain code only sees:

```text
SecureStorage
```

---

# 18. Example Cross-Surface Architecture

```text
                CORE APPLICATION
                       │
        ┌──────────────┼──────────────┐
        │              │              │
      Mail          Calendar       Contacts
        │              │              │
        └──────────────┼──────────────┘
                       │
                  Domain Core
                       │
        ┌──────────────┼──────────────┐
        │              │              │
  Protocol Ports   Persistence    System Ports
        │              │              │
        ▼              ▼              ▼
 Network Adapters   Database     Platform Adapter
                                      │
                 ┌────────────────────┼─────────────┐
                 ▼                    ▼             ▼
              Android              Windows         Web
```

The platform boundary and provider boundary are therefore completely separate.

---

# 19. Application Intents

User actions should be represented as semantic intents.

Examples:

```text
SendMessage
ArchiveMessage
MoveMessage
MarkMessageRead
SearchMessages
CreateDraft
AddContact
CreateCalendarEvent
DownloadAttachment
```

Not:

```text
CallEndpointX
ExecuteProviderArchive
SendPlatformYNotification
```

An intent describes **what the user wants**.

Adapters determine **how the current environment accomplishes it**.

---

# 20. Commands Over Endpoint Calls

Instead of UI code doing:

```text
POST /some/provider/path
```

the UI dispatches:

```text
ArchiveMessage(messageId)
```

Application service:

```text
ArchiveMessageHandler
```

then invokes:

```text
MailService.archive(messageId)
```

The active protocol adapter determines the network operation.

---

# 21. Synchronization as a First-Class Domain

Synchronization must be architected independently.

Create concepts such as:

```text
SyncCursor
SyncState
ChangeSet
RemoteMutation
LocalMutation
Conflict
Checkpoint
```

Do not make application state dependent upon the exact pagination or synchronization scheme of a remote protocol.

---

# 22. Change-Based Synchronization

Prefer:

```text
last known state
      ↓
request changes
      ↓
apply change set
      ↓
persist checkpoint
```

over:

```text
download everything again
```

where protocols permit it.

The synchronization engine should expose:

```text
SyncEngine
```

rather than protocol-specific synchronization objects.

---

# 23. Offline-First Domain Model

All major surfaces should remain useful during temporary disconnection.

Architecture:

```text
UI
 ↓
Local Domain Store
 ↓
Mutation Queue
 ↓
Synchronization Engine
 ↓
Remote Protocol
```

The UI primarily interacts with local domain state.

The network synchronizes that state.

This makes mobile, desktop, poor-connectivity, and future environments behave consistently.

---

# 24. Mutations Should Be Durable

Example:

```text
User archives message
        ↓
Local state changes immediately
        ↓
ArchiveMessage mutation recorded
        ↓
Synchronization attempted
        ↓
Remote confirms
        ↓
Mutation committed
```

If offline:

```text
Mutation remains pending
```

The user's intent survives process termination and connectivity changes.

---

# 25. Conflicts Are Domain Events

Do not leave conflict logic hidden inside network adapters.

Use:

```text
Conflict
├── entity
├── localVersion
├── remoteVersion
├── operation
└── resolutionStrategy
```

Resolution might be:

```text
remoteWins
localWins
merge
retry
userDecision
```

according to domain semantics.

---

# 26. Local Storage Must Be Provider-Neutral

Avoid tables such as:

```text
provider_messages
provider_threads
provider_labels
```

Prefer:

```text
accounts
identities
messages
threads
mailboxes
message_mailboxes
contacts
calendars
events
attachments
capabilities
remote_references
sync_checkpoints
mutations
```

Protocol-specific data may be stored separately:

```text
adapter_metadata
```

but it must not define the canonical schema.

---

# 27. Account Model

A generic account should resemble:

```text
Account
├── id
├── principal
├── identities[]
├── endpoints[]
├── capabilities[]
├── protocolBindings[]
├── credentialsRef
├── syncState
└── metadata
```

Notice what is deliberately missing:

```text
providerName
providerType
providerEnum
```

A human-readable service name may exist as metadata, but application behavior must never depend on it.

---

# 28. Identity Is Separate From Account

Do not assume:

```text
one account = one email address
```

Represent:

```text
Account
   ├── Identity A
   ├── Identity B
   └── Identity C
```

An identity can contain:

```text
displayName
address
replyTo
signature
submissionCapabilities
```

This naturally supports aliases and multiple sending identities without provider-specific logic.

---

# 29. Do Not Equate Folders With Domain Semantics

Different protocols and servers may represent organization differently.

Therefore distinguish:

```text
Mailbox
```

from semantic roles:

```text
Inbox
Sent
Drafts
Trash
Archive
Spam
```

Model:

```text
Mailbox
├── id
├── name
├── parentId
├── role?
└── metadata
```

A role is optional.

Never assume a mailbox's name determines its meaning.

Bad:

```text
if mailbox.name == "Sent"
```

Good:

```text
if mailbox.role == SENT
```

---

# 30. Search Is a Capability

Represent search semantically:

```text
MailQuery
├── text
├── from
├── to
├── after
├── before
├── hasAttachment
├── unread
├── mailbox
└── labels
```

Then allow the adapter to translate this to the protocol's native query representation.

Do not expose protocol search syntax to the UI.

---

# 31. The Composer Must Produce Domain Data

The composer creates:

```text
Draft
```

not:

```text
ProtocolRequest
```

Example:

```text
Draft
├── identity
├── recipients
├── subject
├── body
├── attachments
└── headers
```

Submission happens later through:

```text
SubmissionService
```

---

# 32. Attachments

Treat attachments as resources:

```text
Attachment
├── id
├── filename
├── mediaType
├── size
├── contentReference
└── metadata
```

The domain should not require knowledge of whether attachment bytes currently reside:

- remotely;
- locally;
- in cache;
- in object storage;
- behind a content URI;
- behind an HTTP URL.

Use:

```text
ContentResolver
```

to obtain the data.

---

# 33. Notifications Are Surface Capabilities

Remote changes produce application events:

```text
MessageReceived
CalendarReminderDue
SyncFailed
SubmissionFailed
```

The domain emits these events.

A platform adapter determines whether they become:

```text
system notification
badge
toast
desktop alert
web notification
silent background signal
```

The domain does not know.

---

# 34. Event Architecture

Important domain state changes should produce events.

Example:

```text
MessageReceived
MessageRead
MessageArchived
DraftSaved
MessageSubmitted
AttachmentDownloaded
ContactUpdated
EventCreated
AccountAuthenticated
SyncCompleted
```

These can independently feed:

```text
UI
Notifications
Search indexing
Rules
Automation
Analytics
AI
Audit
Synchronization
```

This significantly increases temporal composability.

---

# 35. Avoid Direct Module Dependencies

Prefer:

```text
Mail → Domain Events → Search
```

instead of:

```text
Mail → SearchImplementation
```

Likewise:

```text
Mail → Domain Events → AI
```

rather than:

```text
Mail → AIProviderSDK
```

The producer should not know its consumers.

---

# 36. Provider-Specific Functionality

Provider-specific extensions are permitted under one condition:

> They must remain optional plugins outside the core domain.

Architecture:

```text
Core capability
      │
      ├── Standard protocol implementation
      │
      └── Optional extension
```

The application must continue functioning when the extension disappears.

---

# 37. Extension Quarantine Rule

Any non-standard capability must live under an explicit boundary such as:

```text
extensions/
```

Never allow it to spread into:

```text
domain/
application/
ui/
```

unless it has first been promoted into a provider-neutral domain capability.

---

# 38. The Two-Implementation Rule

Before introducing an abstraction for an external feature, ask:

> Could at least two unrelated implementations reasonably satisfy this interface?

If not, the abstraction is probably describing a specific service rather than a general capability.

For example:

Bad:

```text
VendorSmartInboxService
```

Better:

```text
MessageClassificationService
```

Potential implementations:

```text
LocalClassifier
RemoteClassifier
RulesClassifier
AIClassifier
```

---

# 39. The Replacement Test

Every external integration should pass:

```text
Can implementation A be replaced by implementation B
without changing the calling domain code?
```

If no:

```text
the boundary is leaking
```

---

# 40. The Time Test

Every architecture decision should also ask:

> Is this likely to remain conceptually valid ten years from now?

Concepts such as:

```text
Message
Contact
Calendar
Attachment
Identity
Authentication
Search
Synchronization
```

are likely durable.

Concepts such as:

```text
CurrentProviderEndpointV3
CurrentPlatformWidget
CurrentSDKResponse
```

are not.

Place volatile concepts near the outside of the architecture.

---

# 41. Volatility Gradient

Architecture should look like:

```text
MOST STABLE
──────────────────────────────
Domain concepts
Application intents
Capability contracts
Protocol abstractions
──────────────────────────────
Protocol implementations
Network libraries
Database implementations
Platform adapters
UI frameworks
Provider extensions
──────────────────────────────
MOST VOLATILE
```

Dependencies should point toward the more stable layers.

Never the reverse.

---

# 42. Recommended Module Layout

```text
/core
    /domain
        /mail
        /identity
        /contacts
        /calendar
        /files
        /sync
        /capabilities

    /application
        /commands
        /queries
        /events
        /services

/protocols
    /jmap
    /imap
    /smtp
    /caldav
    /carddav
    /http

/platforms
    /android
    /windows
    /web
    /ios
    /linux

/infrastructure
    /database
    /crypto
    /network
    /cache

/extensions
    /...

/ui
    /mail
    /contacts
    /calendar
    /settings
```

Dependency direction:

```text
UI
 ↓
Application
 ↓
Domain

Protocols ────────┐
Infrastructure ───┼──► Domain interfaces
Platforms ────────┘
```

The domain never imports these outer modules.

---

# 43. Protocol Ports

Define interfaces in the core.

Example:

```text
interface MailRepository {
    listMailboxes()
    queryMessages(query)
    getMessage(id)
    saveDraft(draft)
    submit(message)
    move(message, mailbox)
    archive(message)
    delete(message)
    synchronize(state)
}
```

Then:

```text
JmapMailRepository implements MailRepository
ImapMailRepository implements MailRepository
```

The application only imports:

```text
MailRepository
```

---

# 44. Capability Interfaces

Capabilities can themselves become ports.

```text
interface MessageSearchCapability

interface MessageSubmissionCapability

interface ScheduledSubmissionCapability

interface PushSynchronizationCapability

interface ContactWriteCapability

interface CalendarSchedulingCapability
```

An account may implement some but not all.

This is preferable to creating one enormous interface that every protocol must pretend to support.

---

# 45. Composition Over Inheritance

Build accounts by composing capabilities:

```text
AccountRuntime
├── AuthenticationCapability
├── MailReadCapability
├── MailWriteCapability
├── MailSubmissionCapability
├── SearchCapability
├── ContactCapability
└── CalendarCapability
```

rather than:

```text
ProviderAAccount extends MailAccount
```

Composition makes heterogeneous servers natural.

---

# 46. Runtime Composition

An account may theoretically use different services for different functions.

For example:

```text
Identity
   ↓
Authorization service

Mail
   ↓
Mail server

Calendar
   ↓
Calendar server

Contacts
   ↓
Address-book server
```

The architecture must not assume these functions share the same hostname, operator, credentials, or protocol.

This is an important form of composability.

---

# 47. Discovery Before Configuration

Prefer:

```text
Identity
    ↓
Discovery
    ↓
Capabilities
    ↓
Endpoints
    ↓
Authentication
    ↓
Account Runtime
```

rather than:

```text
Provider name
    ↓
Hard-coded configuration table
```

Manual configuration remains a fallback.

It must not be the architectural foundation.

---

# 48. Configuration Hierarchy

Use:

```text
1. Protocol discovery
2. Standards-based metadata
3. Administrator provisioning
4. User-supplied configuration
5. Local overrides
```

Hard-coded provider presets should not be necessary for the system to function.

If presets are introduced for convenience, they must merely pre-populate standard configuration.

They must not unlock hidden code paths.

---

# 49. UI Architecture

UI components should bind against:

```text
Domain State
+
Capability State
```

Example:

```text
ComposerState
├── draft
├── identities
├── attachmentState
└── capabilities
```

Then:

```text
Schedule button
    visible when scheduledSubmission capability exists
```

No provider knowledge is necessary.

---

# 50. Navigation Should Also Be Capability-Driven

Example:

```text
Mail capability
    → Mail navigation

Calendar capability
    → Calendar navigation

Contacts capability
    → Contacts navigation
```

If the account does not expose calendar capabilities, the interface simply does not activate the corresponding surface.

This allows one application shell to support radically different account types.

---

# 51. Common UI Across Platforms

The conceptual hierarchy should remain stable:

```text
Application
├── Mail
├── Calendar
├── Contacts
└── Settings
```

while presentation adapts to form factor.

Desktop:

```text
Sidebar + List + Detail
```

Mobile:

```text
List → Detail
```

Tablet:

```text
Navigation + List + Detail
```

The navigation hierarchy is a domain concern.

The exact layout is a platform concern.

---

# 52. Platform-Specific UI Must Not Change Domain Semantics

For example:

```text
Swipe
Keyboard shortcut
Context menu
Toolbar button
Voice command
```

may all trigger:

```text
ArchiveMessage
```

The interaction mechanism changes.

The intent does not.

---

# 53. AI Must Follow the Same Architecture

AI capabilities must not become privileged exceptions.

Represent AI functions as capabilities:

```text
SummarizeMessage
DraftReply
ClassifyMessage
ExtractTasks
PrioritizeMessages
SemanticSearch
```

Implementations might be:

```text
Local model
Remote model
Enterprise model
Rules engine
Future implementation
```

The mail domain should not know which implementation is active.

---

# 54. AI-Native Does Not Mean AI-Coupled

The application may be deeply AI-enabled without coupling its architecture to a particular model provider.

Correct:

```text
Message
   ↓
SummarizationCapability
   ↓
Current Implementation
```

Incorrect:

```text
MessageScreen
   ↓
SpecificModelSDK
```

---

# 55. Data Ownership

Canonical user data should never require a proprietary service representation to remain intelligible.

Where possible, provide import/export using established formats:

```text
Mail → Internet Message Format / MIME
Contacts → vCard
Calendar → iCalendar
```

The user should be able to move data independently of the application vendor.

---

# 56. Security Architecture

Security boundaries should similarly be capability-based.

Core concepts:

```text
CredentialStore
TokenProvider
EncryptionService
KeyProvider
SessionManager
AuthorizationService
```

Platform-specific key stores and authentication mechanisms sit behind these contracts.

No domain object should contain platform credential APIs.

---

# 57. Secrets Must Be Referenced

Prefer:

```text
Account
    credentialsRef
```

rather than:

```text
Account
    password
    accessToken
    refreshToken
```

Credential material belongs inside the secure credential boundary.

---

# 58. Error Normalization

Remote errors must translate into domain errors.

Example:

```text
AuthenticationRequired
PermissionDenied
RateLimited
Unavailable
Conflict
QuotaExceeded
InvalidRecipient
SubmissionRejected
UnsupportedCapability
NetworkUnavailable
```

UI should not parse raw protocol errors.

Adapters translate protocol errors into canonical application errors.

---

# 59. Telemetry Must Remain Neutral

Record:

```text
protocol = jmap
operation = mail.query
latency = ...
result = success
```

rather than structuring telemetry around specific service providers.

Service metadata may optionally be attached for diagnostics but must not define analytics semantics.

---

# 60. Testing Strategy

Every core feature should be tested against interfaces, not live providers.

Example:

```text
MailRepositoryContractTest
```

Every protocol adapter then runs the same contract suite.

```text
JmapAdapter
    ↓
MailRepositoryContractTest

ImapAdapter
    ↓
MailRepositoryContractTest
```

This verifies behavioral compatibility.

---

# 61. Capability Matrix Testing

Automated tests should simulate accounts such as:

```text
Account A
Mail read/write
Search
No push
No scheduled submission

Account B
Mail read/write
Search
Push
Scheduled submission

Account C
Mail read only

Account D
Calendar only

Account E
Mail + Calendar + Contacts
```

The application must remain coherent in every configuration.

---

# 62. Platform Matrix Testing

The same domain contract tests should execute independently from UI platform tests.

```text
Domain tests
Protocol contract tests
Sync tests
Platform adapter tests
UI tests
Integration tests
```

Do not require every platform test to communicate with a live remote account.

---

# 63. No Provider Branching Rule

This should become an architectural lint rule.

Forbidden patterns:

```text
if provider ==
switch(provider)
providerType ==
serviceName ==
```

inside the core or application layers.

Allowed only inside:

```text
protocol discovery
configuration migration
diagnostics
optional extensions
```

Even there, capability detection should be preferred.

---

# 64. No Platform Branching Rule

Similarly:

```text
if android
if windows
if ios
```

must not occur inside domain or application services.

Platform branching belongs inside:

```text
/platforms
```

or the presentation layer when responsive behavior genuinely requires it.

---

# 65. No SDK Leakage Rule

Types originating from third-party SDKs must not cross adapter boundaries.

Forbidden:

```text
DomainService.accepts(ExternalSDKMessage)
```

Required:

```text
ExternalSDKMessage
      ↓ mapper
CanonicalMessage
      ↓
DomainService
```

This makes SDK replacement possible.

---

# 66. Versioning

Protocol adapters should explicitly expose supported protocol versions.

For example:

```text
ProtocolBinding
├── protocol
├── version
├── extensions[]
└── negotiatedCapabilities[]
```

The domain should operate on capabilities rather than version numbers wherever possible.

---

# 67. Future Protocol Adoption

Suppose a new mail protocol emerges later.

Architecture should permit:

```text
/protocols/newmail
```

implementing existing contracts:

```text
MailReadCapability
MailWriteCapability
SearchCapability
SyncCapability
SubmissionCapability
```

No mailbox UI rewrite should be required.

That is the practical proof of temporal composability.

---

# 68. Future Device Adoption

Likewise, imagine a future:

```text
AR client
Voice client
Vehicle interface
Embedded terminal
```

These become new surfaces consuming:

```text
Application Commands
Application Queries
Domain Events
```

They do not require a new domain architecture.

---

# 69. Decision Rule for New Features

Before implementing any new external integration, answer:

### Domain

What enduring user capability does this represent?

### Protocol

Is there an established interoperable protocol?

### Capability

How will support be discovered?

### Adapter

Where will implementation-specific behavior live?

### Domain Mapping

How will external data become canonical data?

### Degradation

What happens if the feature is absent?

### Migration

Can the implementation be replaced later?

### Surface Independence

Will the feature work from another operating system?

### Time Independence

Will this model still make sense if today's provider disappears?

If these cannot be answered, the integration should not enter the core architecture.

---

# 70. Architectural Review Checklist

Every pull request introducing infrastructure or integration should verify:

- [ ] No provider-specific behavior has entered the domain layer.
- [ ] No operating-system-specific behavior has entered the domain layer.
- [ ] External DTOs stop at the adapter boundary.
- [ ] Canonical domain objects are used internally.
- [ ] Features are represented as capabilities.
- [ ] Capabilities are discovered rather than inferred from service names.
- [ ] Unsupported capabilities degrade gracefully.
- [ ] Configuration remains runtime data.
- [ ] Domain operations describe user intent.
- [ ] Synchronization remains protocol-neutral.
- [ ] Local storage remains provider-neutral.
- [ ] Credentials remain behind a security abstraction.
- [ ] Protocol-specific extensions remain isolated.
- [ ] The feature can be tested using mocks or protocol fixtures.
- [ ] A second implementation could replace the first.
- [ ] Another UI surface could consume the same capability.
- [ ] The architecture remains coherent offline.
- [ ] No external SDK type leaks into application contracts.
- [ ] Provider names are never used as behavioral switches.
- [ ] Platform names are never used as domain behavioral switches.

---

# 71. Architectural Constitution

The following rules should be treated as non-negotiable.

## Rule 1 — Domain Before Provider

Model what the user is doing, not who currently provides it.

## Rule 2 — Capability Before Identity

Ask what a server supports, not what brand it belongs to.

## Rule 3 — Discovery Before Hard-Coding

Discover endpoints, versions, and capabilities whenever possible.

## Rule 4 — Protocol Before SDK

Use interoperable protocol semantics as the architectural boundary.

SDKs, when necessary, remain implementation details.

## Rule 5 — Adapter Before Exception

External differences belong in adapters.

## Rule 6 — Canonical Data Before Remote DTOs

Remote representations never become the internal domain model.

## Rule 7 — Intent Before Endpoint

Application behavior expresses user intent rather than network operations.

## Rule 8 — Offline Before Connectivity Assumption

The application state must survive temporary disconnection.

## Rule 9 — Composition Before Inheritance

Build functionality by composing independent capabilities.

## Rule 10 — Events Before Tight Coupling

Independent subsystems communicate through stable events and interfaces.

## Rule 11 — Graceful Degradation Before Feature Assumption

Every optional capability has a coherent absent state.

## Rule 12 — Time Before Convenience

Do not introduce permanent architectural coupling for temporary implementation convenience.

---

# 72. Ultimate Architecture

The desired architecture can be summarized as:

```text
                   USER INTENT
                       │
                       ▼
              APPLICATION COMMAND
                       │
                       ▼
                 DOMAIN MODEL
                       │
                       ▼
                  CAPABILITY
                       │
                       ▼
               PROTOCOL CONTRACT
                       │
                       ▼
                    ADAPTER
                       │
                       ▼
              CURRENT IMPLEMENTATION
```

and in the opposite direction:

```text
CURRENT IMPLEMENTATION
          │
          ▼
       Protocol
          │
          ▼
        Adapter
          │
          ▼
   Canonical Domain
          │
          ▼
   Application State
          │
          ▼
      Any Surface
```

The two ends are deliberately volatile:

```text
Current implementation
Current user interface
```

The centre is deliberately durable:

```text
Protocols
Capabilities
Domain semantics
User intent
```

---

# 73. Final Principle

The architecture should be capable of surviving changes in:

```text
provider
protocol implementation
operating system
device
UI framework
database
authentication implementation
AI implementation
network stack
deployment model
```

without changing the meaning of:

```text
Message
Mailbox
Identity
Contact
Calendar
Event
Attachment
Search
Synchronization
Submission
```

That is the core of temporal composability.

**The application should not be an interface to a company.**

**It should be an interface to enduring digital capabilities expressed through interoperable protocols.**