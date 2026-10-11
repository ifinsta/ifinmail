# ifinmail

Self-hosted email platform — run your own mail server on a single VPS. Handles SMTP, IMAP, spam filtering, TLS, DKIM signing, and backups. Built on Django, Postfix, Dovecot, Rspamd, PostgreSQL, and Redis, all containerized with Docker Compose.

## Quickstart

**Prerequisites**: a domain name, a VPS running Ubuntu 22.04+ or Debian 12+ with a public IPv4 address, and port 25 unblocked by your provider.

### Option 1: One-Click Deploy

Copy the [cloud-init.yaml](provisioning/cloud-init.yaml) content into your cloud provider's "User data" field when creating a server. Set the `DOMAIN` and `ADMIN_EMAIL` environment variables. Works with DigitalOcean, Hetzner Cloud, AWS EC2, Linode, and any provider that supports cloud-init.

### Option 2: Terminal (one command)

```bash
curl -sSL https://raw.githubusercontent.com/ifinmail/ifinmail/main/provisioning/scripts/bootstrap.sh | sudo bash
```

This installs Docker, clones the repo, runs an interactive setup wizard, and provisions the full stack. Answer the prompts with your domain and admin email — everything else is generated automatically.

For fully automated deployment, use non-interactive mode:

```bash
export DOMAIN=example.com ADMIN_EMAIL=admin@example.com
curl -sSL https://raw.githubusercontent.com/ifinmail/ifinmail/main/provisioning/scripts/bootstrap.sh | sudo bash -s -- --non-interactive
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
* **Keep DNS elsewhere?** Connect a DNS provider (Cloudflare, Porkbun, DigitalOcean) or switch a domain to *External DNS* on its zone page; the same mail records are then pushed or exported instead. Set `DNS_SERVER_ENABLED=0` to turn the DNS server off completely.
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

A `worker` and a `beat` container run the periodic jobs: DNS verification (every 15 minutes), DKIM key files, the certificate hostname list, certificate-expiry warnings by email (14 days) and re-publishing the outbound settings. `make provision` also installs a daily encrypted backup in `/etc/cron.d/ifinmail-backup` and enables automatic OS security updates. Container images are updated with `make reload`.

## Outbound relay settings

Smart-host relay, SMTP proxy and the hop limit are set from **Domains & DNS**. The console publishes them to a file that the postfix container applies with `postconf` and reloads within seconds (only an allow-list of keys is ever applied). The relay hostnames themselves come from `MAIL_SMART_HOST` and `MAIL_SMTP_PROXY` in the environment.

## Limits to know about

- Calendars and contacts (CalDAV/CardDAV) are served at `https://mail.yourdomain.com/dav/` with the mailbox address and password; apps find them from the domain alone. Back them up with `make backup` (the `dav_data` volume).
- There is no webmail. Mailbox owners use an email app (IMAP 993, SMTP 587); signing in to the console with a plain mailbox shows these settings.
- Quotas are enforced by Dovecot from the mailbox table; deleting a mailbox leaves its stored mail on disk (the console mounts the mail volume read-only).
- Admin multi-factor authentication is not implemented yet.

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
