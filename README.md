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

A `worker` container runs the periodic jobs (with Celery's scheduler built in): DNS verification (every 15 minutes), DKIM key files, the certificate hostname list, certificate-expiry warnings by email (14 days), re-publishing the outbound settings, and the event scans and webhook delivery described [below](#event-scans-and-webhook-delivery). `make provision` also installs a daily encrypted backup in `/etc/cron.d/ifinmail-backup` and enables automatic OS security updates. Container images are updated with `make reload`.

### Event scans and webhook delivery

The *Delivery events* and *Inbox webhooks* plugins send signed JSON events to URLs you choose. Three
worker jobs make that happen; a job for a plugin that is not installed does nothing.

| Job | Runs | Reads | Does |
| --- | --- | --- | --- |
| `mail.scan_delivery_events` | every minute | the new lines of the Postfix log, at most 4 MB a run | turns what became of mail sent through the API into `message.delivered`, `message.deferred` and `message.bounced` (the API itself sends `message.queued`); also feeds Sender compliance's bounce counters and suppressions |
| `mail.scan_inbox_events` | every 30 seconds | new mail in watched mailboxes, at most 200 mailboxes and 50 new messages in each a run | `message.received`, with the Injection shield's verdict when that plugin is installed |
| `mail.sweep_webhooks` | every minute | deliveries that are due, at most 200 | queues them for the workers, like new ones: retries whose wait is over, and anything the queue lost (see below). It sends nothing itself |

**How a scan works**

- **In bulk, not line by line.** A scan reads every cache key it needs in two bulk reads (queue id
  to Message-ID to sender), answers links made inside the same read from memory, writes new links
  with one bulk write, adds the sender's delivered and bounced counters up once per sender (one
  bounce-rate check each, not one per line) and queues the events of a batch with one insert. What
  it has produced is written every 500 lines. On a 4 MB log (34,000 lines) this took a scan from about
  30,000 cache calls and 40,000 queries to about 470 and 850. If a batch cannot be written, its
  events are tried one at a time, so one bad event does not cost the others.
- **Bounded in time.** Both scan tasks run under Celery time limits, 90 seconds soft and 120 hard,
  so a message or log line that makes a scan hang cannot keep a worker busy for good. The Injection
  shield, which reads text a stranger wrote, is bounded too: it checks at most 1,000,000 characters
  of a message's text and of its HTML, and a larger message is reported as medium risk with the
  reason "only the start was checked".
- **Stopping loses nothing.** The delivery scan saves its place in the log when it reads, and puts
  it back to the first line it has not handled when a run is stopped at the soft limit or the cache
  is unavailable; at most the line in flight is handled twice (its event id makes that a no-op for
  the webhook, and only the sender's counters count it again). The inbox scan saves each mailbox's
  place after its batch, and every event has a fixed id, so a batch read again repeats nothing.
  A worker killed outright (the hard limit, a power cut) can skip the lines it had read but not
  yet handled.

**How events are delivered**

- **One stored delivery per event per endpoint.** The same event id is never queued twice for an
  endpoint. A receiver that is slow, down or failing never slows mail down: delivery happens in the
  worker, after the fact.
- **In chunks, one endpoint at a time.** New deliveries reach the workers in groups of up to 25 to
  the *same* endpoint, one `mail.deliver_webhooks` task per group, instead of one queue message each
  (about 0.4 ms apiece: 3.1 s of publishing for 8,000 deliveries, against 0.14 s). A chunk is worked
  through one delivery after another, so a slow or dead endpoint only delays its own deliveries and
  is never sent two requests at once by the same task. Chunks are queued round-robin across
  endpoints, so one endpoint's backlog does not sit in front of the others.
- **A time slice for every chunk.** A chunk stops after 15 seconds and hands the deliveries it has
  not reached back to the end of the queue, so a slow or dead endpoint holds a worker for at most
  15 seconds plus one request (requests time out at 10 seconds) before others get a turn. The task
  itself has limits of 60 seconds soft and 80 hard. The worker runs two processes shared by every
  job (`--concurrency=2`), so a short slice matters.
- **Retries.** A delivery that fails (any answer but 2xx, a timeout, a refused connection) is tried
  again after 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours, 12 hours and 24 hours, up to
  8 attempts (the Delivery events plugin's *Attempts per event* lowers that). A `410 Gone` switches
  the endpoint off. `GET /api/v1/webhooks/{id}/deliveries` lists every attempt and its answer.
- **A worker claims a delivery before sending it.** The claim is one conditional update that moves
  the delivery's next attempt a minute ahead and succeeds only for a delivery that is still pending
  and due, so a chunk, a chunk handed back to the queue and the sweep can all hold the same
  delivery and it is still sent by one worker at a time. When the attempt ends the real next
  attempt time replaces the claim. A worker that dies mid-delivery leaves the claim to run out,
  and the sweep then queues the delivery again.
- **The sweep is the safety net.** Every minute it queues up to 200 deliveries that are due, in the
  same chunks and the same order as new ones: retries whose wait is over, and any delivery whose
  queue message was lost (the broker was down, a worker was killed). It only queues, so it takes
  seconds (the task has the scans' 90 and 120 second limits); a delivery that is queued but not yet
  picked up is due too and may be queued twice, which the claim makes harmless. Finished and
  failed deliveries are deleted after 14 days.

**For the receiver**

Every attempt is a `POST` with the same `X-Ifinmail-Event-Id` (`evt_…`) and
`X-Ifinmail-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>" with the endpoint's secret>`.
Delivery is **at least once**: a delivery in flight when a worker dies is sent again once its
claim has run out, so **deduplicate on the event id**, and reject a signature whose `t` is more
than five minutes old.

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
  - *Marketing*: campaigns to many people, one email each, with a personal unsubscribe and paced
    sending; installed by default (see [Marketing campaigns](#marketing-campaigns)).

  The first four are safe to install unchanged (defaults follow Google Workspace and Microsoft 365, lists
  start empty), and each part can be switched off on its own inside the plugin.
- **Your own:** Marketplace → Submit a plugin. Someone with `system.manage` approves or rejects it;
  nothing is approved automatically and nothing is fetched from outside the server.
- Each plugin page shows exactly what it changes and whether the mail server has applied it. Disable or
  uninstall removes the values again. Failures and unapplied changes show in System health.
- Authoring guide, state machines and the 331 handled edge cases:
  `.agents/skills/ifinmail-plugins/`. In a development checkout, check a manifest with
  `python manage.py validate_plugin path/to/plugin.toml`.

### Marketing campaigns

Marketing mail is built in. A receipt goes to one person who just bought something; a newsletter
goes to thousands who may or may not want it, and Gmail, Yahoo and Microsoft judge the sender by
how they react. Sending one `POST /messages` per person does not work for that (a bulk message
must go to one recipient, the per-key cap is 500 recipients a day, and Outbound policy's
30-a-minute limit and containment would stop a newsletter), so the **Marketing** plugin, installed
by default, adds campaigns: one message to a list, one email each, sent over time.

**Set it up once.** Campaigns carry your postal address in every footer, as the law in many
countries requires (CAN-SPAM), so an administrator enters it under *Marketplace → Marketing →
Postal address for the footer*. Until then `POST /campaigns` answers `409` and says so. Then create
a key with the `marketing.send` scope and the addresses it may send as. That scope is separate from
`mail.send` on purpose: a leaked transactional key cannot mail a list, and a campaign key cannot
send a password reset.

```bash
curl -u ifm_KEY:ifs_SECRET -X POST https://mail.yourdomain.com/api/v1/campaigns \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: spring-2026' \
  -d '{"from":"news@example.com","name":"Spring sale",
       "subject":"Spring sale, {{first_name|friend}}",
       "text":"Hi {{first_name|friend}}, the sale starts today.",
       "html":"<p>Hi {{first_name|friend}}, the sale starts today.</p>",
       "recipients":[{"email":"ana@example.org","merge":{"first_name":"Ana"}},
                     {"email":"bob@example.org"}]}'
```

The answer is `202` with `{"id", "status": "sending", "queued": n, "skipped": {...}}`. **Nothing is
sent in the call**; the server sends the campaign over time. The subject, text and html may hold
`{{name}}` tags filled from each recipient's `merge` values, `{{name|fallback}}` for a person with
no value, and `{{email}}` and `{{unsubscribe_url}}` for everyone. Values are escaped in HTML, a
subject stays on one line, and a tag that no recipient has a value for (a typo) refuses the
campaign. A person missing a value that has no fallback is skipped instead of being greeted with
"Hi ,". `GET /campaigns/{id}` shows progress, `GET /campaigns/{id}/recipients?status=skipped` shows
who was left out and why, and `POST /campaigns/{id}/pause`, `/resume` and `/cancel` control it.
[`examples/python/11_marketing_campaign.py`](examples/python/11_marketing_campaign.py) sends one
from a CSV.

**Who is left out.** At creation, and again just before each email (somebody can unsubscribe in
between): addresses on the suppression list (an address that bounced for good, whether or not
Sender compliance is installed), people who opted out of marketing, destinations Outbound policy
blocks, invalid and duplicate addresses. `skipped` says how many of each. A campaign from a
mailbox Outbound policy limits to internal mail is refused.

**Unsubscribing stops marketing only.** Every email has a footer with your postal address and a
personal unsubscribe link, plus the `List-Unsubscribe` and `List-Unsubscribe-Post` headers mail
apps use for their own Unsubscribe button. The link's page asks for one click (a link scanner that
opens it unsubscribes no one); the one-click POST records a **marketing opt-out**, separate from the
suppression list, which stops all API mail. The person keeps getting receipts and password resets.
Your application can record its own unsubscribes with `POST /marketing/opt-outs`; removing one
(`DELETE`, scope `mail.manage`) undoes someone's consent, so it needs more than `marketing.send`.

**How it is sent.** A job (`mail.run_campaigns`, every minute) works through the campaigns that
are sending.

- **The pace is per clock minute.** The plugin's *Emails per minute* (60 by default, up to 6,000)
  less what any run already sent in this minute, so extra runs in the same minute add nothing.
  Several campaigns share the budget. Emails that reach the mail system count, accepted or refused;
  people skipped for the lists never do.
- **The daily ceiling grows.** *Emails per day* (2,000 by default), and with *Warm up gradually*
  on, the ceiling starts at *Emails allowed on the first sending day* (200) and grows by half each
  day until it reaches it, because a sender that has never mailed anyone and suddenly mails
  thousands is treated as a spammer.
- **The transactional limits do not apply.** Campaign mail is not counted against the key's daily
  cap or Outbound policy's per-minute and per-day limits, and it does not feed containment, which
  would pause a mailbox for sending a newsletter. It has the pace, the ceiling and the safeguards
  below instead. Allowed senders, hosted domains, blocked destinations and a sender paused by
  containment still apply.
- **A person is never mailed twice.** Each recipient is claimed with one conditional update right
  before their email, so two runs that overlap cannot both send it. A worker that dies (`kill -9`
  was tested on a live stack) leaves at most the one email in flight in doubt: it is marked
  `failed` with "interrupted: may or may not have been sent", and everyone else stays pending and
  goes out on the next run. A duplicate marketing email is judged worse than a rare miss, so
  nothing is retried automatically. If the mail system cannot be reached, nothing was sent and the
  next run tries again.
- **A campaign stops itself.** It pauses, with the reason in `status_detail`, when the mail system
  refuses 20 emails in a row (the rest of the list stays pending, not failed); when its sender is
  paused by containment; when its key is paused by Sender compliance's bounce guard; and when more
  than 5% of what it has sent (at least 100 emails) has bounced. A hard bounce (the address does
  not exist) adds the address to the suppression list, whichever plugins are installed. Resume it
  after fixing the cause, or cancel it.
- **Events.** With the Delivery events plugin, each campaign email produces the same
  `message.queued`, `message.delivered`, `message.deferred` and `message.bounced` webhook events as
  other API mail; `message.queued` also carries the campaign id.

**Audiences: lists kept on the server.** A request can list its recipients (up to *Most recipients
listed in one campaign request*, 10,000 by default), but a real list is kept and changed over time,
so a campaign can name one instead:

```bash
# once: a list for one of your sending domains
curl -u ifm_KEY:ifs_SECRET -X POST https://mail.yourdomain.com/api/v1/audiences \
  -H 'Content-Type: application/json' \
  -d '{"name":"Newsletter","domain":"example.com"}'          # -> {"id": "7d2e...", ...}

# load it, 1,000 people per call; send the whole export again whenever it changes
curl -u ifm_KEY:ifs_SECRET -X POST https://mail.yourdomain.com/api/v1/audiences/7d2e.../contacts \
  -H 'Content-Type: application/json' \
  -d '{"contacts":[{"email":"ana@example.org","merge":{"first_name":"Ana"}},
                   {"email":"bob@example.org"}]}'              # -> {"added": 2, "updated": 0, ...}

# then send to all of it
curl -u ifm_KEY:ifs_SECRET -X POST https://mail.yourdomain.com/api/v1/campaigns \
  -H 'Content-Type: application/json' \
  -d '{"from":"news@example.com","subject":"Spring sale, {{first_name|friend}}",
       "text":"Hi {{first_name|friend}}!","audience":"7d2e..."}'
```

- **Importing is idempotent.** People are matched by address (case does not matter). The answer
  counts `added`, `updated` (the values changed), `unchanged`, `invalid` (not an address, or
  merge values that cannot be used) and `duplicate` (named twice in the call). A contact sent
  without `merge` keeps the values it has.
- **Whether someone can be mailed is looked up, never stored on the contact.** Each contact is
  `reachable`, `opted_out` or `suppressed` (suppressed wins, the same order a campaign uses),
  read from the same opt-out and suppression lists campaigns read. So someone who unsubscribes
  from any campaign of the domain is `opted_out` on every audience of that domain at once, and
  an audience can never disagree with what a campaign will do. `GET /audiences/{id}` gives the
  counts (`total`, `reachable`, `opted_out`, `suppressed`); `GET /audiences/{id}/contacts` lists
  people and filters by `?status=` or `?address=`.
- **A campaign copies the list when it is created.** People added or removed afterwards do not
  change a campaign that exists, and deleting an audience leaves its campaigns alone. The
  campaign's `audience` field says which list it was sent to.
- **One audience, one sending domain.** The opt-outs and suppressions that decide who can be
  mailed are per domain, so a campaign to an audience must be sent from an address at the
  audience's domain. A key sees and changes the audiences it created (`mail.manage` sees all)
  and can create one only for a domain it sends from.
- **The size limit refuses a batch whole.** *Most contacts in one audience* (100,000 by default,
  1,000,000 at most) is also the most a campaign to an audience can have. A call that would pass
  it is refused with nothing added, never cut in two; people already on the list can still be
  updated.

[`examples/python/12_audiences.py`](examples/python/12_audiences.py) manages a list from a CSV, and
`11_marketing_campaign.py send ... --audience ID` sends to it.

Limits of what is built: there are not yet reusable templates, scheduled sends, open and click
tracking, or attachments.

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
| `marketing.send` | Marketing plugin: `POST/GET /campaigns`, `GET /campaigns/{id}`, `POST /campaigns/{id}/pause`, `/resume`, `/cancel`, `GET /campaigns/{id}/recipients`, `GET/POST /marketing/opt-outs` (a key sees only its own campaigns; all with `mail.manage`) |
| `mail.manage` (marketing) | `DELETE /marketing/opt-outs/{domain}/{address}` (undoes someone's unsubscribe) |
| `mail.send` (suppressions) | Sender compliance plugin: `GET/POST /suppressions` (domains the key sends from; all with `mail.manage`), `DELETE /suppressions/{domain}/{address}` (`mail.manage`) |
| `agents.manage` | Agent inboxes plugin: `GET/POST /inboxes`, `GET/DELETE /inboxes/{address}`, `GET /inboxes/{address}/messages`, `GET/DELETE /inboxes/{address}/messages/{uid}`, `GET /inboxes/{address}/messages/{uid}/code`, `GET /inboxes/{address}/wait` (only inboxes the key created) |
| any of the above | Agent gateway plugin: `POST /mcp` (Model Context Protocol); the tools offered follow the key's scopes |
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
- **AI agents (Model Context Protocol).** Install the *Agent gateway* plugin and point an MCP
  client at `https://mail.yourdomain.com/mcp` with a key as a bearer token
  (`Authorization: Bearer ifm.<prefix>.<secret>`, the form shown when the key is created):

  ```bash
  claude mcp add --transport http ifinmail https://mail.yourdomain.com/mcp \
    --header "Authorization: Bearer ifm.PREFIX.SECRET"
  ```

  The agent sees only the tools its key's scopes allow: `create_inbox`, `list_inboxes`,
  `delete_inbox`, `list_messages`, `read_message`, `get_code` and `wait_for_message`
  (`agents.manage`, with the Agent inboxes plugin), `send_email` and `approval_status`
  (`mail.send`), `delivery_report` (`audit.view`) and `server_status` (`console.access`). Every
  tool calls the same service as the matching API operation, so allowed senders, daily caps,
  the Outbound policy, Human approval, Sender compliance and sandbox keys all apply. Agents send
  plain text only. `read_message` hands the model what a person sees (hidden text removed) with
  the Injection shield's verdict, and says the content is untrusted. Actions that change
  something are in the audit trail under the key. The transport is Streamable HTTP with JSON
  answers (protocol versions 2025-06-18, 2025-03-26 and 2024-11-05).
- **Webhooks.** With the Delivery events plugin, a key with `mail.send` can register URLs that
  receive signed JSON events for its own mail: `message.queued`, `message.delivered`,
  `message.deferred` and `message.bounced`. With the Inbox webhooks plugin, a webhook can also
  receive `message.received` for the agent inboxes the key created (or any mailbox, with
  `mail.manage`). Delivery is at least once and every attempt carries the same event id, so
  receivers deduplicate on it; how events are produced, retried and delivered is under [Event
  scans and webhook delivery](#event-scans-and-webhook-delivery).
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

- Webhook events: the delivery scan reads at most 4 MB of the Postfix log a minute (about 30,000
  lines), so a server that logs more than that falls behind and its events arrive late; webhook
  delivery is at least once (receivers deduplicate on the event id); and a worker killed outright
  can skip log lines it had read but not yet handled. See [Event scans and webhook
  delivery](#event-scans-and-webhook-delivery).
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
make docker-clean  # Trim Docker build cache and replaced images (runs daily and after updates)
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

Every update rebuilds the images, which leaves build cache and the replaced images behind.
`provisioning/scripts/docker_clean.sh` removes them after each successful update and every day
at 04:50 (log: `/var/log/ifinmail-docker-clean.log`): images without a name, `ifinmail/*` test
tags no container uses, stopped stack containers, build cache unused for 7 days and anything
above 3 GB of it, or all of it once the disk is 85% full. Volumes, images in use and other
projects' Docker objects are never touched, and a rollback rebuilds from git, so it needs none
of it. `sudo make docker-clean DOCKER_CLEAN_ARGS=--deep` empties the build cache now;
`--dry-run` shows what would go. The limits are `DOCKER_CLEAN_CACHE_DAYS`,
`DOCKER_CLEAN_CACHE_MAX` and `DOCKER_CLEAN_DISK_PERCENT`.

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
