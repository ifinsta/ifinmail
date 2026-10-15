# ifinmail for developers and AI agents: proposition, gaps, plugins, partners

Status: proposal, 2026-10-15. Market research is from public 2026 sources (mostly vendor blogs;
weigh them accordingly). Everything said about ifinmail is from this repository.

## 1. The unique proposition

> **Your own mail server that you can safely hand to software, and to agents.**
> Self-hosted, explained in plain words, and controlled through a scoped, audited, idempotent API
> where nothing destructive happens on a model's say-so.

No one else combines these four things today:

| | Hosted agent-mail APIs (AgentMail, Resend, Postmark) | Self-hosted stacks (mailcow, Mailu, Stalwart) | ifinmail |
| --- | --- | --- | --- |
| You own the data and the domain reputation | No | Yes | Yes |
| Per-inbox / per-message fees | Yes | No | No |
| An API designed for programs (scopes, sender allow-lists, idempotency, rate budgets) | Yes | Partial (admin APIs) | Yes |
| The server explains its own failures and fixes (health, delivery reasons) | Partly | Little | Yes |
| Agent-safe control plane (propose-only assistant, declarative plugins, hash-chained audit, sending containment) | No | No | Yes |

Why it matters now:

- **Agents need inboxes.** 2026 buyer guides split the market into send-only APIs (Resend,
  Postmark) and agent-native inboxes (AgentMail). An address an agent owns is used for sign-ups,
  OTP codes and agent-to-agent messages. ifinmail already creates a real mailbox in one API call.
- **Inbox access is now an attack surface.** Email-borne prompt injection is documented
  (EchoLeak, CVE-2025-32711, in Microsoft 365 Copilot; ShadowLeak in ChatGPT), and OWASP ranks prompt
  injection first for LLM apps. A mail server can defend at the boundary, before any agent reads a
  message. Hosted send APIs and generic MCP servers do not.
- **Sovereignty pressure.** NIS2 national laws (for example Sweden, January 2026) and the EU Data
  Act push organisations to keep communications infrastructure under their control. A
  one-server, one-console mail system answers that directly.
- **Senders are policed.** Gmail, Yahoo and Microsoft enforce SPF/DKIM/DMARC, one-click
  unsubscribe (RFC 8058) and complaint rates (Gmail stepped up enforcement in November 2025,
  Microsoft in May 2025). Programs that send mail need guard rails; ifinmail already has most of them.

## 2. What already exists to build on

- Versioned API (`/api/v1`, OpenAPI contract) with per-operation scopes, key expiry, network
  allow-lists, calls-per-minute budgets, `Idempotency-Key` on send, sender allow-lists per key.
- Python client and runnable examples, tested against the real API.
- Plugin layer: declarative manifests, engine-neutral capabilities, validated twice, applied and
  acknowledged by the owning container. Plugins cannot run code.
- Assistant with read and propose tiers only; applying is always a person's click.
- Sending containment, delivery telemetry with classified reasons, threat digest, audit chain.

## 3. Gaps that stop developers and agent builders choosing it

1. **No inbound API.** A program cannot receive mail as JSON (webhook or poll). This is the
   first thing every agent-mail comparison checks.
2. **No MCP server.** Agents (Claude, ChatGPT, Cursor and others) connect through MCP. Community
   IMAP/SMTP MCP servers exist but have no scopes, no audit and no injection defence.
3. **No events.** Delivery outcomes (sent, deferred, bounced) exist inside the console but are not
   pushed to integrations.
4. **No message API.** No threads, search or read over HTTP; only IMAP.
5. **Bulk-sender compliance for API senders**: no suppression list and no automatic
   `List-Unsubscribe` / `List-Unsubscribe-Post` on mail sent through the API.
6. **No test mode.** CI pipelines want a key whose mail is captured, not delivered.

## 4. Plugin recommendations

"Kind" says how much core work each needs:

- **Manifest**: possible today with existing capabilities.
- **Capability**: a new capability and adapter target, then a manifest.
- **Core**: a new service in the console. It is offered as a plugin and switched on by one.

Ranked by impact for developers and agents divided by effort.

| # | Plugin | What it does | Kind | Why it wins |
| --- | --- | --- | --- | --- |
| 1 | **Agent Gateway (MCP)** | An MCP server built into the console: tools `list_messages`, `read_message`, `search`, `send` (propose or direct, by policy), `create_inbox`, `extract_code`. Each agent gets its own API key and scopes, and every call is audited. | Core | Puts ifinmail one config line away from every agent framework. The audit, scopes and containment are already there. |
| 2 | **Inbox Webhooks** | Each received message is delivered to a URL as signed JSON (HMAC, retries, idempotent ids): headers, text, HTML, sanitised attachments as signed links. Rules per mailbox or `+tag`. | Capability (Dovecot/Sieve or LMTP hook) | Closes the biggest gap against AgentMail and Postmark inbound. |
| 3 | **Agent Inboxes** | One-call inboxes with a TTL, plus-address routing (`agent+task123@`), catch-all to an agent, and an `extract_code` endpoint for OTPs and magic links. | Core + Manifest | The agent sign-up and verification use case, self-hosted, with no per-inbox fee. |
| 4 | **Injection Shield** | Before an agent sees a message: flag or strip hidden text (zero-size, white-on-white, HTML comments, invisible Unicode), add an `X-Agent-Risk` score, and quarantine risky mail for agent mailboxes. The MCP tools return text with the flags attached. | Capability (Rspamd rules + sanitiser) | The differentiator nobody else ships at the server. |
| 5 | **Delivery Events** | Webhooks or a server-sent-event stream for accepted, deferred, bounced and complaint events, with the classified reason the console already computes. | Core (telemetry exists) | Developers expect events; the classification is better than raw DSNs. |
| 6 | **Sender Compliance** | A suppression list (hard bounces, complaints, unsubscribes), automatic RFC 8058 one-click unsubscribe on API mail, and a complaint-rate guard that pauses a key. | Capability (Rspamd/Postfix) + Core | Keeps API senders inside Gmail, Yahoo and Microsoft rules. Feeds containment. |
| 7 | **Human Approval** | Agent-sent mail waits in an outbox for approval by policy: first contact, external domain, attachments, or a keyword. Approve in the console, by API, or by email reply. | Core | Human-in-the-loop is the top recommended defence for agent actions. |
| 8 | **Sandbox Keys** | A key flag that captures mail instead of delivering it (a Mailtrap-style viewer and API), for CI and staging. | Core | Every developer needs it; trivial on top of the send path. |
| 9 | **Message API (JMAP-lite)** | Read-only HTTP for threads, search and attachments per mailbox, scoped to the key's mailboxes. | Core | Lets programs and agents read without IMAP. Stalwart's JMAP is its main differentiator. |
| 10 | **DLP Outbound** | Block or quarantine outbound mail that contains secrets (keys, card numbers, national IDs) by pattern. Agents leak data; this catches it at the boundary. | Capability (Rspamd) | Pairs with Injection Shield: protect what comes in and what goes out. |
| 11 | **OIDC Sign-in** | Console and API keys bound to an identity provider (Entra, Google, Okta, Keycloak). | Core | Unblocks enterprise reviews (SSO is deferred today). |
| 12 | **Webmail (partner)** | Packaged SnappyMail or Roundcube as an optional container, behind the console's sign-in. | Capability (new container) | Closes the "no webmail" objection without building one. |

Already possible as manifests today (no core work): presets of the existing capabilities for an
"Agent-safe sending" profile, combining low per-minute limits, containment with pause, internal-only
logins for agent mailboxes, and blocked destinations.

## 5. Where to collaborate

| Partner type | Who | What we offer / ask |
| --- | --- | --- |
| Agent frameworks | MCP registry and SDKs (Anthropic, OpenAI Agents SDK), LangChain, LlamaIndex, CrewAI | A reference MCP server and tool packages; listing in their registries and docs. |
| Automation tools | n8n, Make, Zapier, Node-RED | Official nodes for mailboxes, send and inbound webhooks. n8n is self-hosted too, which makes it a natural pair. |
| Hosting marketplaces | Hetzner, DigitalOcean, OVH, Scaleway, Infomaniak (EU) | One-click images. EU hosts sell sovereignty; we are the mail part of it. |
| Filtering | Rspamd project | Upstream the injection and DLP rules as Rspamd modules; credibility and maintenance help. |
| Deliverability | DMARC report processors, Google Postmaster Tools, Microsoft SNDS | Import their data into System health; joint "first 30 days" guides. |
| Clients | Thunderbird (autoconfig), K-9/Thunderbird Android, SnappyMail | Tested configs, webmail packaging. |
| Standards | IETF agent identity drafts (OpenA2A AIP, draft-prakash-aip), JMAP working group | Prototype "this agent's mailbox and identity" binding; follow, don't lead. |
| Security research | Prompt-injection researchers, OWASP LLM project | Publish the Injection Shield test corpus; invite red-teaming. |

## 6. Sequencing

- **30 days:** Sandbox Keys (8), Delivery Events (5), an "Agent-safe sending" preset, and a
  published MCP server prototype over the existing API (read and send only).
- **60 days:** Inbox Webhooks (2), Agent Inboxes with `extract_code` (3), and Injection Shield v1
  (4: hidden-text and invisible-Unicode detection with risk headers).
- **90 days:** Human Approval (7), Sender Compliance (6), n8n node and LangChain tools, and one
  hosting-marketplace image.
- **Later:** Message API (9), OIDC (11), DLP (10), webmail partner (12).

## 7. How to know it is working

- Time from install to "an agent sent and received its first message" under 10 minutes.
- Number of MCP connections and API keys with `mail.send` per install (from opt-in telemetry
  only).
- Injection Shield catch rate on a public test corpus, published with each release.
- Bounce and complaint rates of API senders stay under the providers' thresholds by default.

## Sources

- Agent email market: [Nylas](https://www.nylas.com/blog/best-ai-agent-email-providers/),
  [AgentMail](https://www.agentmail.to/blog/best-email-api-for-ai-agents-2026),
  [DEV Community](https://dev.to/k_vrbova/7-best-email-mcp-servers-and-apis-for-ai-agents-2026-4n9d)
- MCP email servers: [fagents-mcp](https://glama.ai/mcp/servers/fagents/fagents-mcp),
  [email-mcp-server](https://github.com/gabigabogabu/email-mcp-server)
- Self-hosted comparison: [WZ-IT](https://wz-it.com/en/blog/mailcow-stalwart-mailu-comparison/),
  [selfhosting.sh](https://selfhosting.sh/compare/stalwart-vs-mailcow/)
- Sender rules: [Suped](https://www.suped.com/email-deliverability/answers/what-are-the-one-click-unsubscribe-requirements-for-gmail-and-yahoo-and-how-do-they-relate-to-ca),
  [PowerDMARC](https://powerdmarc.com/google-and-yahoo-updated-email-authentication-requirements-for-2024/)
- Prompt injection by email: [Darktrace](https://www.darktrace.com/blog/how-email-delivered-prompt-injection-attacks-can-target-enterprise-ai-and-why-it-matters),
  [Nylas guide](https://cli.nylas.com/guides/email-prompt-injection-defense)
- Agent identity: [OpenA2A AIP draft](https://datatracker.ietf.org/doc/draft-fane-opena2a-aip/01/),
  [Nylas: email as identity](https://cli.nylas.com/guides/email-as-identity-for-ai-agents)
- Sovereignty: [Glesys](https://glesys.com/blog/eu-data-sovereignty-in-2026-new-rules-for-your-infrastructure/),
  [Elestio](https://blog.elest.io/digital-sovereignty-in-2026-how-eu-data-residency-laws-are-driving-the-self-hosting-boom/)
