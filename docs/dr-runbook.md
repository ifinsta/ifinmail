# Disaster recovery runbook

For when the server, or its disk, is gone. Written to be followed by someone who did not build the
system, with this file and the two things listed under **You need**.

> **Status: written from the backup layout and scripts; not yet executed end to end on a clean
> host.** The weekly `restore_test.sh` proves the database dump restores and the archive decrypts.
> The full rebuild below is what drill **G.1** must run, and every step that turns out to be wrong
> must be corrected here. Until that drill is logged in `docs/enterprise-evidence/`, treat the
> RTO in `enterprise-slo.md` as a target, not a measurement.

## You need

1. **The backup key and its passphrase** (`ifinmail-backup-key.asc`, `ifinmail-backup-key.passphrase`),
   exported earlier with `make backup-key` and kept off the server. Without them the backups cannot
   be opened. If you cannot find them, stop: nothing below works.
2. **An off-site copy of a backup** (`ifinmail_backup_<timestamp>.tar.gz.gpg`) from the host named in
   `BACKUP_OFFSITE_TARGET`, or a local copy if the disk survived.

Also useful: your registrar login (nameserver, glue and DS records) and your VPS provider login
(reverse DNS).

## What is in a backup

| Directory | Contents | Why it matters |
|---|---|---|
| `postgresql/ifinmail.dump` | Accounts, mailboxes, domains, audit trail, settings | The system of record |
| `mail/` | All mailboxes (Maildir) | The mail itself |
| `dkim/` | DKIM private keys | Irreplaceable: new keys mean re-publishing DNS and a reputation reset |
| `dnssec/` | Knot zone and DNSSEC keys | A new key means a new DS record at the registrar |
| `certs/` | Let's Encrypt accounts and certificates | Re-issuing is possible but rate-limited |
| `dav/` | Calendars and contacts | |
| `runtime/`, `spool/`, `rspamd-data/` | Console-published state, queued mail, spam statistics | |
| `configs/dotenv` | `provisioning/.env`: every generated secret | Needed so restored data and secrets agree |

## Procedure

Run as root on the new server. Replace `<domain>` with your mail domain.

### 1. New host

Ubuntu 22.04+ or Debian 12+, public IPv4, port 25 open, same `<domain>`. Point nothing at it yet.
Note its IP: DNS changes come at the end, after verification.

### 2. Install the same release

```bash
export DOMAIN=<domain> ADMIN_EMAIL=<admin address>
curl -sSL https://raw.githubusercontent.com/ifinsta/ifinmail/main/provisioning/scripts/bootstrap.sh \
  | sudo bash -s -- --non-interactive
cd ~/ifinmail && sudo make version          # if the old server ran a pinned release:
sudo make update TO=<that release>
```

This gives a working, empty system with *new* secrets and keys. The next steps replace them with
the originals.

### 3. Get and open the backup

```bash
mkdir -p /backups && cd /backups
# copy ifinmail_backup_<timestamp>.tar.gz.gpg here, and the two key files to /root/escrow/
gpg --batch --pinentry-mode=loopback --passphrase-file /root/escrow/ifinmail-backup-key.passphrase \
    --import /root/escrow/ifinmail-backup-key.asc
mkdir restore && gpg --batch --pinentry-mode=loopback \
    --passphrase-file /root/escrow/ifinmail-backup-key.passphrase \
    --decrypt ifinmail_backup_<timestamp>.tar.gz.gpg | tar -xz -C restore
cd restore && sha256sum -c SHA256SUMS --quiet && echo "backup intact"
```

To prove the key and archive before touching the server, run
`provisioning/scripts/backup_offsite.sh verify-key <key.asc> <passphrase-file>` first.

### 4. Stop the stack and restore secrets and keys

```bash
cd ~/ifinmail && sudo make down
cp /backups/restore/configs/dotenv provisioning/.env        # original secrets
cp -a /backups/restore/dkim/keys/. provisioning/docker/dkim/
```

### 5. Restore data

Volumes are named `<compose project>_<name>` (`docker volume ls`). Start only the database first:

```bash
cd ~/ifinmail && COMPOSE="docker compose --env-file provisioning/.env -f provisioning/docker/docker-compose.yml"
$COMPOSE up -d postgres
$COMPOSE exec -T postgres pg_restore -U ifinmail -d ifinmail --clean --if-exists \
    < /backups/restore/postgresql/ifinmail.dump
```

Copy the file volumes back with a throwaway container (repeat per directory/volume pair:
`mail/`→`mail_data`, `dnssec/`→`dns_data`, `dav/`→`dav_data`, `runtime/`→`runtime_data`,
`spool/`→`postfix_spool`, `rspamd-data/`→`rspamd_data`, `certs/`→ `provisioning/docker/certs/`):

```bash
docker run --rm -v <volume>:/dest -v /backups/restore/<dir>:/src:ro alpine:3.20 \
    sh -c 'cp -a /src/. /dest/'
```

Then `sudo make up`.

### 6. Verify before changing DNS

| Check | How | Pass |
|---|---|---|
| Console sign-in with MFA | open `https://<mail host>/` | enters, shows your domains and mailboxes |
| Audit trail intact | `make audit-verify` | `Audit chain intact.` |
| Mail is present | sign a mailbox in with a mail app (IMAP 993) | existing mail visible |
| DKIM | System health → `<domain>` → DKIM | same selector and key as before |
| DNSSEC | System health → DNSSEC | zone signed with the *old* keys; DS at registrar still matches |
| Outbound | send a message to an outside address | delivered, DKIM pass |
| Backups resume | `sudo make backup` | completes; System health backup age resets |

### 7. Cut over

1. Change the registrar's glue records (nameserver A records) to the new IP.
2. Set reverse DNS (PTR) for the new IP to the mail hostname at the VPS provider.
3. Wait for System health to go green (DNS propagation can take hours).
4. Run `sudo make backup-key` again if the key was regenerated, and re-point
   `BACKUP_OFFSITE_TARGET`.

## After recovery

- Rotate anything an attacker could have held if the loss was a compromise rather than a failure:
  administrator passwords, API tokens (Mailbox profile → API tokens), the backup key, DNS provider
  credentials.
- Write down the actual elapsed time from step 1 to a green System health. That is the measured RTO.
- Correct this document with whatever was wrong.

## Known gaps to close in the first drill

- The exact `pg_restore` role/ownership behaviour against a freshly provisioned database.
- Whether restoring `configs/dotenv` before `make up` leaves any container with a stale secret.
- Time for step 7 (registrar propagation) is outside our control and must be reported separately.
- `make uninstall` deletes `/backups` and the backup key from the server: never run it on a host
  you intend to recover from.
