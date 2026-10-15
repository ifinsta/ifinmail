<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/static/icons/lockup-dark.svg">
    <img src="frontend/static/icons/lockup-light.svg" alt="ifinmail" height="56">
  </picture>
</p>

# ifinmail

Self-hosted email platform — run your own mail server on a single VPS. Handles SMTP, IMAP, spam filtering, TLS, DKIM signing, and backups. Built on Django, Postfix, Dovecot, Rspamd, PostgreSQL, and Redis, all containerized with Docker Compose.

## Quickstart

**Prerequisites**: a domain name, a VPS running Ubuntu 22.04+ or Debian 12+ with a public IPv4 address, and port 25 unblocked by your provider.

### Option 1: One-Click Deploy

Copy the [cloud-init.yaml](provisioning/cloud-init.yaml) content into your cloud provider's "User data" field when creating a server. Set the `DOMAIN` and `ADMIN_EMAIL` environment variables. Works with DigitalOcean, Hetzner Cloud, AWS EC2, Linode, and any provider that supports cloud-init.

### Option 2: Terminal (one command)

```bash
curl -sSL https://raw.githubusercontent.com/ifinsta/ifinmail/main/provisioning/scripts/bootstrap.sh | sudo bash
```

This installs Docker, clones the repo, runs an interactive setup wizard, and provisions the full stack. Answer the prompts with your domain and admin email — everything else is generated automatically.

For fully automated deployment, use non-interactive mode:

```bash
export DOMAIN=example.com ADMIN_EMAIL=admin@example.com
curl -sSL https://raw.githubusercontent.com/ifinsta/ifinmail/main/provisioning/scripts/bootstrap.sh | sudo bash -s -- --non-interactive
```

## DNS Records

If this server answers DNS for the domain (the default), you do not create any of these by hand; see the next section. If you keep DNS elsewhere, create these DNS records for your domain. The provisioning script prints the exact values — especially the DKIM public key, which is unique to your installation.

| Type | Name | Value |
|------|------|-------|
| A | `yourdomain.com` | Your VPS IPv4 address |
| A | `mail.yourdomain.com` | Your VPS IPv4 address |
| MX | `yourdomain.com` | `10 mail.yourdomain.com.` |
| TXT | `yourdomain.com` | `v=spf1 mx -all` |
| TXT | `_dmarc.yourdomain.com` | `v=DMARC1; p=quarantine; rua=mailto:postmaster@yourdomain.com` |
| TXT | `default._domainkey.yourdomain.com` | `v=DKIM1; k=rsa; p=<your-public-key>` |

### DNS Provider Guides

**Cloudflare**: create A records with the orange cloud **off** (DNS-only, not proxied). MX and TXT records go under DNS → Records → Add Record.

**Namecheap**: go to Domain List → Manage → Advanced DNS. Use `@` for the root domain and `mail` for the mail subdomain.

**Porkbun**: go to Domain Management → DNS → Edit. Use the empty/blank host field for root records.

## DNS, certificates and entry points: this server is the authority

ifinmail answers DNS for your domains itself (Knot DNS, with DNSSEC), manages its TLS certificate, and controls every port it listens on, all from **Settings** in the console.

### DNS server (Settings → DNS server)

* Every domain you add is published by this server: MX, SPF, DKIM, DMARC, MTA-STS, `autoconfig`/`autodiscover`, mail client SRV records, CAA and the nameserver records are generated and kept current. You only add your own extras (a website, a verification token) as custom records.
* **One step at your registrar:** set the domain's nameservers to `ns1.mail.yourdomain.com` and `ns2.mail.yourdomain.com` and add them as *glue* (child nameservers) pointing at the server IP. The page shows exactly what is missing and re-checks live (answering, delegated, DNSSEC).
* **DNSSEC** is on by default. Once the zone is delegated, add the DS record shown on the zone page at your registrar.
* **Keep DNS elsewhere?** Connect a DNS provider (Cloudflare, Porkbun, DigitalOcean) or switch a domain to *External DNS* on its zone page; the same mail records are then pushed or exported instead. Set `DNS_SERVER_ENABLED=0` in `provisioning/.env` and run `make provision` to turn the DNS server off completely (its container is then not run).
* Secondary nameservers (zone transfer) can be listed on the DNS server page. Port 53 must be free: if `systemd-resolved` holds it, `make provision` binds the DNS server to the public address (`DNS_BIND_IP`).
* Back up the `dns_data` volume (included in `make backup`): it holds the DNSSEC keys that the registrar's DS record refers to.

### TLS certificates (Settings → TLS certificates)

One certificate covers the mail hostname and every domain's `mta-sts`, `autoconfig` and `autodiscover` names. The page shows its issuer, expiry and which hostnames are covered and pointing here, and lets you **issue now**, **renew now**, or **install your own certificate** (PEM, validated: key must match, chain must cover the mail hostname, not expired). An uploaded certificate is kept if switching back to Let's Encrypt fails. Requests are carried out by the certbot container; results show on the page.

### Network & entry points (Settings → Network & entry points)

**Enforced from the first minute.** The rules the page shows are published to the firewall agent by
the console itself, within five minutes of start-up and again whenever they drift, so a server
nobody has configured still has them in force. With the defaults, one address may open at most
120 new connections a minute to the mail ports (25, 465, 587, 993, 995, 110, 143); HTTP, HTTPS and
DNS are not capped here (nginx has its own limits). System health reports *Entry-point firewall*:
in force, being applied, rejected, or the agent not reporting. **Emergency stop:** over SSH,
`docker stop docker-firewall-1` removes every rule at once and the server accepts everything
again (SSH is never filtered); `docker start docker-firewall-1` brings them back.

**Blocking from Threats.** A finding about a scanner, flood or password guessing offers *Block this
network* for 1 hour, 24 hours, 7 days or until removed. It asks for your password again, never blocks
your own address, this server or networks on its own side, and a block with a time limit lifts itself
(within five minutes, audited as `network_unblock` by the system).

**Automatic protection (on by default).** Two switches on the same page, either can be turned off: block networks
that a serious threat finding names (for a chosen time, never your own side, the server, an
allow-list, or a network people signed in from lately; at most 50 at once, audited and emailed),
and *flood mode*, which holds each address to 30 new mail connections and 240 web connections a
minute while traffic arrives from many networks at once and ends by itself afterwards.

**Denial-of-service guard (kernel, instant).** Whenever the connection limit is on: an address
opening connections at four times a limit loses every new connection for 10 minutes (the penalty
box); just over a limit only loses the excess; the web ports allow 600 new connections a minute per
address (240 in flood mode); one address may hold at most 50 mail and 100 web connections open. The
allow-list, this server and its own side are exempt. nginx also closes slow requests in seconds.
Automatic blocks of a network that keeps coming back double in length (up to a week). The firewall
agent also reads nginx's access log every few seconds: an address refused 30 times within about 15
seconds (a scanner's word list) goes into the penalty box at once, long before the next digest.

Lists every published port (SMTP, submission, SMTPS, IMAP, IMAPS, HTTP, HTTPS, DNS) with a live check that the service answers. You can close ports you do not use (IMAP on 143, SMTPS, DNS), block networks, and cap new mail connections per address per minute. Rules are applied by the `firewall` container with nftables, for Docker-published ports and host traffic alike, and the page shows whether they are in force. Ports the server cannot work without (25, 80, 443) stay open, and you cannot block the address you are using. SSH and the host firewall are not touched.

## First sign-in and setup

After provisioning, open `https://mail.yourdomain.com/accounts/login/` and sign in with the administrator email and password printed during setup (also in `provisioning/.env`). The first time, you land in the **setup wizard**:

1. **Domain**: confirms your domain. Adding a domain creates its DKIM key, the `postmaster@`/`abuse@` aliases and queues its hostnames for the TLS certificate.
2. **DNS**: connect Cloudflare, Porkbun or DigitalOcean to publish every record automatically, or copy the records shown and add them at your DNS host.
3. **Account**: creates your own mailbox and administrator login in one step.

Everything after that lives under **Settings** (`/accounts/settings/`):

| Page | What it does |
| --- | --- |
| Mailboxes | Create mailboxes (login and mailbox together), change passwords, set quotas, disable or delete. Also the switch for public self-registration (off by default). |
| Aliases | Forward an address to one or more others. |
| Domains & DNS | Add domains, connect a DNS provider, see which records are verified. |
| Mail server, Deliverability, Security, Storage | Read-only view of the effective environment configuration. |
| Backups & scheduled jobs | When the last backup ran and when DNS was last verified. |

Adding another domain later is one action (**Domains & DNS > Register New Domain**); it runs the same pipeline and reports each step.

## How a new domain becomes live

`ProvisioningService.add_domain` runs these idempotent steps (re-running repairs whatever is missing):

1. Domain row.
2. DKIM key for that domain (stored in the database and written to `/etc/dkim/<domain>.<selector>.key`, which Rspamd signs from; no per-domain Rspamd config).
3. `postmaster@` and `abuse@` aliases to the administrator.
4. DNS: if a provider is connected, A, MX, SPF, DMARC, DKIM, MTA-STS and `autoconfig`/`autodiscover` records are published; otherwise they are listed for you to add. Existing TXT records of other purposes (for example a site-verification token) are never overwritten.
5. Certificates: the hostnames the certificate must cover are written for the certbot container, which re-issues the certificate as soon as each name resolves to this server.
6. Verification: DNS is checked against public resolvers. **Postfix only accepts mail for a domain once its MX points at this server**; the console switches that on automatically and re-checks every 15 minutes. A DNS outage never turns a working domain off.

Clients configure themselves: `autoconfig.<domain>` and `autodiscover.<domain>` (Thunderbird, Outlook, Apple Mail) and the MTA-STS policy at `https://mta-sts.<domain>/.well-known/mta-sts.txt` are served for every hosted domain. MTA-STS starts in `testing` mode.

## Scheduled jobs and backups

A `worker` container runs the periodic jobs (with Celery's scheduler built in): DNS verification (every 15 minutes), DKIM key files, the certificate hostname list, certificate-expiry warnings by email (14 days) and re-publishing the outbound settings. `make provision` also installs a daily encrypted backup in `/etc/cron.d/ifinmail-backup` and enables automatic OS security updates. Container images are updated with `make reload`.

### Marketplace (plugins)

**Marketplace** (in the sidebar, after Settings) adds capabilities by configuring the server for
you. A plugin is one declarative `plugin.toml`: settings an administrator fills in, and the values
they produce for capabilities the server offers (such as `mail.journal` or `sending.rate_limit`).
Manifests never name the mail software, so plugins keep working if Postfix, Dovecot or Rspamd is
ever replaced. Plugins cannot run code, and every value is
checked twice (by the console and by the container that applies it).

- **Built in:**
  - *Compliance journal*: a copy of every message, inbound and outbound, in an archive mailbox you
    choose. Create the archive mailbox first.
  - *Inbound protection*: refuse or quarantine dangerous attachments (detected by name and
    content), act on senders' DMARC policies, seal forwarded mail and trust ARC chains from named
    forwarders, blocked and allowed senders, and greylisting.
  - *Outbound policy*: sending limits per mailbox (30 a minute, 2,000 a day), automatic containment
    of a suspected stolen password (pauses that mailbox and tells you), recipients per message, the
    largest message (50 MB), internal-only mailboxes, encrypted-only delivery to partner domains,
    and a cap on forwarding rules.
  - *Mailbox care*: empty Trash and Junk (and optionally Sent) after a number of days, and warn
    people at 80% and 95% of their quota.

  All three are safe to install unchanged (defaults follow Google Workspace and Microsoft 365, lists
  start empty), and each part can be switched off on its own inside the plugin.
- **Your own:** Marketplace → Submit a plugin. Someone with `system.manage` approves or rejects it;
  nothing is approved automatically and nothing is fetched from outside the server.
- Each plugin page shows exactly what it changes and whether the mail server has applied it. Disable or
  uninstall removes the values again. Failures and unapplied changes show in System health.
- Authoring guide, state machines and the 331 handled edge cases:
  `.agents/skills/ifinmail-plugins/`. In a development checkout, check a manifest with
  `python manage.py validate_plugin path/to/plugin.toml`.

### Assistant

The **Assistant** (speech-bubble button in the header, for administrators with `system.manage`)
answers questions about this server ("why is mail to gmail.com bouncing?") from the same checks as
System health, the plugins and the audit trail, and can draft plugin settings that you apply with
one click. Failing System health checks offer "Ask the assistant". Answers are rendered as
Markdown (headings, lists, tables, code blocks with a Copy button, links); raw HTML and images in an
answer are shown as text or plain links, never executed or loaded.

- It is a built-in plugin, installed on every server and **inert until you connect a model**:
  Marketplace → Assistant, then the API base URL and model of any OpenAI-compatible service
  (OpenAI, Anthropic's compatible endpoint, OpenRouter, Groq, Mistral, a local Ollama or vLLM...).
  The model must support tool calling; **Test connection** checks it. Uninstalling it is final.
- **It cannot change anything by itself.** Its tools only read, or draft a change that is validated
  and shown with an Apply button; applying is your click, recorded in the audit trail.
- **What is sent:** your question and the results of the checks it runs. Never message contents,
  passwords or keys; secret-looking values are removed first, and every answer shows exactly what
  was sent and to which host. The API key is stored encrypted and sent only to that host
  (redirects refused, cloud metadata addresses blocked).
- Limits: a daily token budget (default 200,000), 8 model calls per question, one question at a
  time per administrator; conversations are kept 30 days. Answers are prepared by the `worker`.

### External file storage (object storage)

Uploaded media (branding, attachments) and backups live on the server's own disk unless you
install the built-in **Object storage (S3-compatible)** plugin: Marketplace → Object storage, then
the endpoint, bucket, region and an access key of any S3-compatible service (AWS S3, Cloudflare R2,
Backblaze B2, Wasabi, DigitalOcean Spaces, Hetzner, Scaleway, Ceph, Garage, SeaweedFS...). No
vendor SDK is involved: requests are signed by the console itself.

- **Choose what goes there:** media, backups, or both. Mailboxes always stay on the server's disk
  (mail delivery and IMAP need fast local files).
- **How files are handed out** (`/media/...` links never change): *redirect* (a short-lived signed
  link to the store, the default), *public* (your CDN or public bucket address) or *proxy* (the
  console streams the file). Private files are only handed to administrators either way.
- **Settings → File storage** shows where each kind of file is kept and when the store last
  answered, offers *Test connection*, and *Copy media to object storage* for files uploaded
  before the plugin. The connection is tested twice an hour; a failure turns System health red and
  is audited once.
- **Backups:** with backups routed there, the nightly encrypted archive is uploaded (in 16 MB
  parts), compared by SHA-256, and old copies are pruned to the same retention.
  `python manage.py storage check|status|list|prune` inside the `api` container does the same by
  hand.
- Design, research and how to add another protocol: `docs/storage-contract.md`.

### Android app: download page and over-the-air updates

Your own server hosts the ifinmail Android app, so in-house releases need no app store.

- **Download page:** `/download/` shows the latest stable build with its SHA-256, a QR code and the install
  steps. `/updates/v1/android/latest.apk` always redirects to the newest stable APK.
- **Publish:** *Settings → App releases* (asks for your password), `POST /api/v1/releases/android` with an API
  key that has the `system.manage` scope, or `python manage.py publish_release app.apk` in the `api`
  container. The server reads the APK itself and refuses another app, an unsigned file, a repeated version
  code or a different signing key.
- **Devices update themselves:** the app checks about twice a day, shows a banner, downloads the build (resumable,
  SHA-256 checked, identity checked again on the device) and hands it to Android's installer. Releases can be
  staged (a percentage of devices), `beta` or `stable`, and *mandatory* to retire an old build.
- **Privacy:** a check-in is a random install id, version and Android level; no account, address or IP. Kept
  180 days.
- Workflow, signing, rollback and troubleshooting: `docs/android-releases.md`.

### Off-site copy and the backup key

Backups are encrypted with GPG and, by default, stay on the same disk as the server. Two small
steps make them survive losing it:

1. **Send them somewhere else over SSH.** Set `BACKUP_OFFSITE_TARGET=user@host:/absolute/path`
   in `provisioning/.env` (any host you control, or a storage box that offers SSH) and run
   `sudo make offsite-check`. Every nightly backup is then copied, compared by SHA-256 and pruned to
   the same retention. Plain (unencrypted) archives are never sent. System health shows the age of
   the last verified copy and turns red if it stops.
2. **Store the key away from the server.** The key that opens the backups is generated on this
   server, so a lost server means unreadable backups. Run `sudo make backup-key` once: it writes
   the key and its passphrase to `/root/ifinmail-backup-key`, proves that on their own they decrypt
   the newest backup, and tells System health. Move both files to a password manager or an
   encrypted drive, then delete them from the server. Do not store them next to the off-site
   backups.

To rehearse a recovery without touching the server: `scripts/backup_offsite.sh verify-key
<key.asc> <passphrase-file>` decrypts the newest backup with only those files.

If the only administrator loses their authenticator and recovery codes, run
`sudo make reset-mfa EMAIL=admin@example.com` on the server; they
enroll again at next sign-in and the action is written to the audit trail.

The audit trail keeps 365 days (`AUDIT_RETENTION_DAYS`, minimum 30). Each entry is chained to the
one before it; `sudo make audit-verify` checks the chain and
prints its head, and **Logs → Export** (`?format=jsonl`) downloads the full trail with hashes.

## API for integrations

Programs can manage mailboxes, aliases and domains through a versioned HTTP API at
`https://mail.yourdomain.com/api/v1/` (contract: `/api/v1/openapi.json`; the versions this server
speaks: `/api/`).

1. **Create a key**: Settings → **API keys**. You get a **key** (`ifm_…`, public, safe to log) and a
   **secret** (`ifs_…`, shown once). Choose the scopes it needs, how long it lives (up to 90 days),
   optionally the networks it may be used from and a calls-per-minute limit.
2. **Call it** with HTTP Basic, or with one Bearer value:

   ```bash
   curl -u ifm_KEY:ifs_SECRET https://mail.yourdomain.com/api/v1/status
   curl -H "Authorization: Bearer ifm.KEY.ifs_SECRET" https://mail.yourdomain.com/api/v1/status
   ```

**Python:** [`examples/python`](examples/python) has a single-file client (key from the
environment, readable errors, `Retry-After` handling, safe retries, paging) and eight runnable
examples: provision mailboxes from a CSV, send mail, the delivery report, a cron/Nagios check.
They run against the real API in the test suite, so they cannot drift from it.

| Scope | Endpoints |
| --- | --- |
| none | `GET /health` (liveness for monitors; the only operation without a key) |
| `console.access` | `GET /status` |
| `audit.view` | `GET /metrics` (Prometheus text), `GET /health/full`, `GET /health/dns`, `GET /health/deliverability`, `GET /telemetry/errors`, `GET /telemetry/stats`, `GET /telemetry/fingerprints` |
| `system.manage` | `POST /telemetry/fingerprints/{fingerprint}/ack` |
| `mail.manage` | `GET/POST /mailboxes`, `GET/PATCH/DELETE /mailboxes/{address}`, `GET/POST /aliases`, `DELETE /aliases/{id}` |
| `mail.send` | `POST /messages`; with the Developer sandbox plugin `GET/DELETE /sandbox/messages`, `GET /sandbox/messages/{id}`; with Delivery events `GET/POST /webhooks`, `DELETE /webhooks/{id}`, `POST /webhooks/{id}/test`, `POST /webhooks/{id}/enable`, `GET /webhooks/{id}/deliveries` |
| `mail.send` (approvals) | Human approval plugin: `GET /approvals`, `GET /approvals/{id}` (own messages; every key's with `mail.manage`) |
| `mail.manage` (approvals) | `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject` (never a key's own messages) |
| `mail.send` (suppressions) | Sender compliance plugin: `GET/POST /suppressions` (domains the key sends from; all with `mail.manage`), `DELETE /suppressions/{domain}/{address}` (`mail.manage`) |
| `agents.manage` | Agent inboxes plugin: `GET/POST /inboxes`, `GET/DELETE /inboxes/{address}`, `GET /inboxes/{address}/messages`, `GET/DELETE /inboxes/{address}/messages/{uid}`, `GET /inboxes/{address}/messages/{uid}/code`, `GET /inboxes/{address}/wait` (only inboxes the key created) |
| `dns.manage` | `GET /domains`, `GET /domains/{name}`, `POST /domains`, `POST /domains/{name}/verify`, `GET /dns/status` |

The table is generated from the running server: `GET /api/v1/openapi.json` states each
operation's `x-required-scope`, and the Settings assistant reads the same contract, so it can tell
you what a key may do and which keys look unsafe. Ask it "how can a program create mailboxes?" or
"are my API keys set up safely?".

- **Safe by construction.** A key never exceeds the permissions of the person who created it, and
  keeps being narrowed by them. Mailboxes whose login has console access cannot be changed through
  the API, and the API cannot create one, so a leaked key cannot be turned into an administrator.
  Domain removal is not offered.
- **Sending mail.** A key with `mail.send` names the addresses it may send as (`billing@example.com`,
  or `*@example.com` for a whole domain) and has a daily cap on recipients (default 500):

  ```bash
  curl -u ifm_KEY:ifs_SECRET -X POST https://mail.yourdomain.com/api/v1/messages \
    -H 'Content-Type: application/json' -H 'Idempotency-Key: order-1001' \
    -d '{"from":"billing@example.com","to":["ana@example.org"],"subject":"Your invoice",
         "text":"Thanks for your order.","html":"<p>Thanks for <b>your order</b>.</p>"}'
  ```

  `202` means *accepted for delivery* (the id is the Message-ID), not delivered; bounces go to the
  sender address. The message is signed with DKIM and delivered like any other outgoing mail, and it
  obeys the Outbound policy plugin: recipients per message, blocked destinations, internal-only
  mailboxes, and messages per minute and per day for the From address. A mailbox that containment
  paused cannot send, and what a key sends is counted by the same counters containment reads.
  `to`, `cc` and `bcc` are bare addresses (no names), at most 100 recipients, 1 MB of body; there
  are no attachments yet. The `Idempotency-Key` header (up to 64 characters) makes a retry safe: the
  same key and message return the first answer instead of sending twice. Nothing is stored: there
  is no Sent folder for API mail.
- **Lists are paged**: `?limit=` (default 50, at most 200) and `?offset=`; the reply is
  `{"items": [...], "count": N}`.
- **Errors** are `{"detail": "..."}` with 401 (credentials), 403 (scope or protected mailbox),
  404, 409 (already exists), 422 (invalid) or 429 (slow down; see `Retry-After`).
  Every response carries `X-API-Version` and `X-RateLimit-*`.
- **Rotation** can keep the old secret working for up to 7 days so an integration switches over
  without an outage. Every change made with a key is in the audit trail under the key's name;
  failed attempts are recorded once per address and reason.
- **Versions.** Within `v1` only additions are made. A breaking change is `/api/v2/`, mounted next
  to `v1`, which keeps answering until its retirement is announced in the changelog. The older
  unversioned `/api/<path>` answers `308` to `/api/v1/<path>`, and so do the machine endpoints that
  used to live outside `/api/` (`/health/full/`, `/health/dns/`, `/health/deliverability/` and
  `/telemetry/*`). Those detailed health reports now need a key with `audit.view`: they run live
  lookups and name your domains, which an anonymous caller should not trigger.
- **One rule for every endpoint.** Every JSON endpoint is either a `/api/vN/` operation or listed in
  `backend/config/api_versions.py` with the reason it is not (probes and formats other parties
  define, and the console's own page calls). A test fails when a new one is in neither place.
- **Type safe.** Every request and response is a typed schema, every handler is annotated, errors
  share one `{"detail": "..."}` shape, and `make typecheck` (strict mypy, also in CI) covers the API
  layer.

## Threats: scanners and attacks, reduced to what needs a decision

A public server is probed all day: `/.env`, `/.git/config`, `/wp-login.php`, raw TLS sent to the
web port, password guessing. Most of it is harmless noise and a little of it matters, so the
console reads nginx's JSON access log (a size-capped file in the `nginx_logs` volume, read-only for
the worker) and the sign-in record every ten minutes and keeps only what a decision needs:

- **Findings**, each with a severity, who (a /24 or /48 network, an account, a key id), how much,
  a few request ids to look up in Logs, and *where to tighten* (Network & entry points, Security,
  API keys, Users). Examples: a scanner that was answered rather than refused, a flood, password
  guessing or spraying, a sign-in that succeeded after repeated failures, a real API key being
  attacked, a probe that made the server raise an exception (joined by request id), a sensitive file
  being served.
- **The mail ports too.** Postfix and Dovecot write their logs to a size-capped file in the
  `mail_logs` volume (and still to `docker logs`); the console reads them read-only and keeps four
  things, never message content: failed mail sign-ins, successful ones, refused attempts to relay,
  and refused recipients that do not exist. Findings: password guessing or spraying against
  mailboxes (a single account failing again and again is only a medium "check the client"), relay
  probing, address guessing, guessing from many networks at once, and a mailbox that signed in right
  after a spray from the same network (critical). `MAIL_LOG_MAX_BYTES` (default 16 MiB) caps each
  file. The one-click block and automatic blocking cover these findings like any other.
- **Adaptive: it learns what is normal here.** Three things, all from data the server already
  keeps, and it only *raises findings*; it never changes a limit or block by itself.
  - *Where traffic comes from.* A free country and network-operator database
    (DB-IP Lite, CC BY 4.0) is downloaded about monthly into the runtime volume as one SQLite file
    and read locally: no visitor address leaves the server. Findings show the country and
    operator beside each network, the page lists top operators and countries, and several
    networks of one operator with findings become one *campaign* finding that can be blocked
    together.
  - *Places.* For each account (console and mailbox sign-ins) it remembers the countries and
    operators it has signed in from. Once an account has an established history (5 sign-ins over
    2 days), a sign-in from somewhere new is a finding: medium for a new country, low for a new
    operator in a known country. Nothing is learned until location data is installed, so the
    baseline does not change meaning when it arrives. Places unused for 180 days, or belonging to
    a closed account, are forgotten.
  - *Traffic.* The hour's requests, failed console sign-ins and failed mail sign-ins are compared
    with the same hour of the day over the last 14 days (median and spread, so one bad day does not
    teach it that attacks are normal); far above that is a finding even when no single network
    crosses a threshold. Quiet hourly rows are now kept 28 days for this.

  `THREAT_ADAPTIVE=0` turns it off; `GEO_DISABLED=1` stops the database download.
- **One report across every log (Logs → Report).** Each collected source (web server, Postfix,
  Dovecot, Rspamd) is reduced to a few counters per hour and stored with the digest's hourly row,
  so the report for a day, week or month is a sum of small rows and costs the same at any traffic.
  It shows which sources are reporting (a log that goes quiet is itself a finding), mail flow and
  spam decisions, web status classes, security and changes, and exports as JSON. Container output
  of the console, worker, DNS, calendar, Redis and database is not collected (`make logs`).
- **Mail trace and the weekly report.** Logs → Mail trace follows one message across Postfix,
  Rspamd and Dovecot (joined by queue id and Message-ID); the report is emailed to the
  administrators each Monday (`LOG_REPORT_EMAIL=0` turns that off); the assistant can answer from
  the same figures.
- **Exposure check (Settings → Network).** Weekly and on request the server probes itself like a
  stranger (scanner paths, internal ports, certificate, headers, open relay, VRFY, plain-text
  logins, open resolver). Results appear in System health. Scanner-only paths such as `/.env`
  put an address in the penalty box after two requests.
- **Passkeys (Settings → Passkeys).** Console sign-in with a fingerprint, face, screen lock or
  security key: passwordless from the login page, or as the second step after a password. The
  authenticator must verify the person, so it is two factors in one and satisfies
  `MFA_ENFORCEMENT=required`. Only the public key is stored; a passkey only works on this server's
  own domain; a cloned authenticator is detected and refused. Needs the console's https:// domain
  name (not an IP address).
- **One slim row per hour**: counts and classes, no individual request, no address, no user agent.
- **What is discarded**: raw error events of INFO and WARNING level after 48 hours, hours with
  no findings after a week, resolved findings after 30 days. The audit trail is never touched.

When the assistant is connected it writes the gist and ranks the findings from those aggregates
(at most 40% of the day's token budget, at most every 30 minutes, only when something changed). It
receives networks, path *classes*, counts and masked account names: no addresses, user agents or
message data. Its text is shown as text and can only point at findings that exist. Without a model
the same page is written by rules. Serious findings are emailed to the administrators once a day;
`THREAT_ALERTS=0` turns that off and `THREAT_DIGEST_ENABLED=0` turns the whole digest off.
`ACCESS_LOG_MAX_BYTES` (default 16 MiB) caps the log file.

## Outbound relay settings

Smart-host relay, SMTP proxy and the hop limit are set from **Domains & DNS**. The console publishes them to a file that the postfix container applies with `postconf` and reloads within seconds (only an allow-list of keys is ever applied). The relay hostnames themselves come from `MAIL_SMART_HOST` and `MAIL_SMTP_PROXY` in the environment.

## Limits to know about

- Delivery status: **Dashboard** and **Logs → Report** show what happened to outgoing mail (accepted, retried, failed for good, bounce rate, and why, where and from which mailbox), the administrators are emailed when the bounce rate passes 5% or a provider starts refusing the server, and `GET /api/v1/telemetry/delivery` returns the same figures. "Accepted" is not "in the inbox": placement is only visible from the receiver's side.
- Profile photos: each person adds a photo on **Account**, and an administrator can switch on the **Contact directory** (Settings → Mailboxes). It publishes every mailbox, with its photo, as a read-only address book called "directory" in each mailbox's CardDAV home, so iOS, macOS, Android (DAVx5) and Thunderbird show a sender's photo and complete names without anyone importing anything. It needs the `dav` container, lists everyone to everyone (people can hide themselves), and only helps clients that sync CardDAV contacts: Gmail, Outlook and other apps that keep their own contacts will not show it. Photos can also be set by an integration: `POST /api/v1/mailboxes/{address}/photo`.
- Calendars and contacts (CalDAV/CardDAV) are served at `https://mail.yourdomain.com/dav/` with the mailbox address and password; apps find them from the domain alone. Back them up with `make backup` (the `dav_data` volume). Not needed? Set `DAV_ENABLED=0` in `provisioning/.env` and run `make provision`: the `dav` container is removed and the calendar DNS records are no longer published.
- There is no webmail. Mailbox owners use an email app (IMAP 993, SMTP 587); signing in to the console with a plain mailbox shows these settings.
- Quotas default to 1024 MB per mailbox and are enforced by Dovecot from the mailbox table (set 0 for unlimited). The Mailboxes page shows the space budget as you assign quotas: disk free, mail stored, quota allocated, and what is still promiseable. Deleting a mailbox leaves its stored mail on disk (the console mounts the mail volume read-only).
- Admin sign-in supports TOTP multi-factor authentication (Settings → Security, or `/accounts/mfa/setup/`); recovery codes are issued once at enrollment.

## Managing the Stack

```bash
make ps          # Show container status
make logs        # Tail all service logs
make health      # Run health checks
make up          # Start the stack
make down        # Stop the stack
make reload      # Rebuild images and redeploy
make backup      # Run a full backup (schedule this daily via cron)
make firewall    # Configure ufw firewall rules
```

## Updating, rolling back and uninstalling

The console checks GitHub for new releases every six hours (System health → Software version;
switch it off at the bottom of that page or with `UPDATE_CHECK_ENABLED=0`). When a release is
available the dashboard says so.

```bash
cd ~/ifinmail
sudo make version            # installed version, latest release, update history
sudo make update             # latest release (or: sudo make update TO=v0.0.1)
sudo make rollback           # back to the version before the last update
```

`make update` snapshots the database and `provisioning/.env` into `provisioning/.updates/`
before switching, and rolls back by itself if the new console is not healthy within five
minutes. `make rollback` restores that snapshot together with the previous code, because a newer
version may already have changed the database schema. Mail, DNSSEC keys and certificates are in
volumes every version shares. The last five snapshots are kept.

Re-running the one-line installer on an installed server keeps its configuration and secrets,
and keeps a release pinned by `make update`.

```bash
sudo make uninstall                              # everything, including all mail and data
sudo make uninstall UNINSTALL_ARGS=--keep-data   # keep mail, database, keys and certificates
provisioning/scripts/uninstall.sh --check        # list anything left of an install
```

Uninstall removes the containers, volumes, images, backup cron job, system settings, backup
key, logs, backups and the install directory, and undoes only what the installer recorded
creating in `/var/lib/ifinmail/manifest`. Docker stays unless `--remove-docker` is given.
Records at your registrar (nameservers, glue, DS) and the reverse DNS at your VPS provider are
yours to remove.

## Troubleshooting

### "Port 25 is blocked"
Many VPS providers (AWS, GCP, DigitalOcean) block outbound port 25 by default to prevent spam. You must request them to unblock it. Without port 25, your server cannot receive mail from other servers.

### "Let's Encrypt certificate issuance failed"
The bootstrap script creates a self-signed certificate so the stack starts immediately. For a trusted certificate:
1. Verify DNS A records for your domain and mail subdomain point to your VPS
2. Verify port 80 is open
3. Run `make provision` again after DNS propagates

### "Mail goes to spam"
New IP addresses have no reputation. To improve deliverability:
- Verify all DNS records (SPF, DKIM, DMARC) are correct using `make health`
- Set up a reverse DNS (PTR) record for your VPS IP pointing to `mail.yourdomain.com` (ask your VPS provider)
- Warm up your IP by sending small volumes of mail gradually over several weeks

### "Can't connect with my email client"
Check the admin dashboard's Email Setup page for the correct server settings:
- IMAP server: `mail.yourdomain.com`, port 993, SSL/TLS
- SMTP server: `mail.yourdomain.com`, port 587, STARTTLS
- Username: your full email address

## Architecture

```
nginx (443) → api (Django, gunicorn, port 8000)
              ├── postgres (5432) — domains, users, mailboxes, aliases
              ├── redis (6379) — cache, sessions, celery broker
              ├── postfix (25, 465, 587) — SMTP, virtual lookups via pgsql
              │   └── rspamd (11332) — milter-based spam filtering
              └── dovecot (143, 993) — IMAP, LMTP delivery from postfix
```

## License

MIT
