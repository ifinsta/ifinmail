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
  - *Sending and delivery policy*: sending limits per mailbox (30 a minute, 2,000 a day), the
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
- Authoring guide, state machines and the 295 handled edge cases:
  `.agents/skills/ifinmail-plugins/`. In a development checkout, check a manifest with
  `python manage.py validate_plugin path/to/plugin.toml`.

### Assistant

The **Assistant** (speech-bubble button in the header, for administrators with `system.manage`)
answers questions about this server ("why is mail to gmail.com bouncing?") from the same checks as
System health, the plugins and the audit trail, and can draft plugin settings that you apply with
one click. Failing System health checks offer "Ask the assistant".

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

## Outbound relay settings

Smart-host relay, SMTP proxy and the hop limit are set from **Domains & DNS**. The console publishes them to a file that the postfix container applies with `postconf` and reloads within seconds (only an allow-list of keys is ever applied). The relay hostnames themselves come from `MAIL_SMART_HOST` and `MAIL_SMTP_PROXY` in the environment.

## Limits to know about

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
