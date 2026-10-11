# ifinmail clients

The apps in `android/` (Kotlin Multiplatform) talk to an ifinmail server only through open
protocols; there is no private REST API. This is the contract they rely on, and how to check it.

## What a client needs from the server

| Need | ifinmail provides | Where |
|------|-------------------|-------|
| Account discovery | Mozilla autoconfig XML at `https://<domain>/.well-known/autoconfig/mail/config-v1.1.xml` and `https://autoconfig.<domain>/mail/config-v1.1.xml` (IMAP 993 SSL, SMTP 587 STARTTLS, login = full address); Outlook autodiscover | `backend/apps/mail/views` |
| Incoming mail | IMAP on 993 (implicit TLS) and 143 (STARTTLS, TLS required); POP3 on 995 (implicit TLS) and 110 (STARTTLS) with stable UIDLs; `AUTH=PLAIN`/`LOGIN`, IDLE, MOVE, UIDPLUS, CONDSTORE after login, special-use folders Sent/Drafts/Trash/Junk/Archive created automatically | `provisioning/docker/dovecot` |
| Sending | Submission on 587 (STARTTLS) and 465 (implicit TLS), SASL via Dovecot, relaying only for authenticated users | `provisioning/docker/postfix` |
| Calendars and contacts | CalDAV and CardDAV (Radicale) at `https://<mail host>/dav/`, found via `/.well-known/caldav` and `/.well-known/carddav` (RFC 6764) or the `_caldavs._tcp` / `_carddavs._tcp` SRV records; sign in with the mailbox address and password; each person sees only their own data | `provisioning/docker/dav` |
| Sent copy | Client appends to the `\Sent` folder over IMAP (no server-side copy) | client |
| Certificates | One certificate for the mail hostname (Let's Encrypt, or one uploaded in Settings). Clients verify the host name, so connect to the hostname in autoconfig | console |

Until the first Let's Encrypt certificate is issued the server presents a temporary self-signed
certificate. Clients refuse it unless the person confirms its SHA-256 fingerprint (shown in the
console under Settings, TLS certificates, and printed by `make provision`); the confirmation stops
mattering as soon as a publicly trusted certificate replaces it.

## Checking the contract against a server

`mail/src/test/.../LiveServerIT.kt` drives the real client code (IMAP login, SMTP auth, send and
receive between two mailboxes) against any server:

```sh
cd clients/android
IFINMAIL_LIVE=1 IFINMAIL_HOST=mail.example.com \
IFINMAIL_USER1=a@example.com IFINMAIL_USER2=b@example.com IFINMAIL_PASS='...' \
sh gradlew :mail:test --tests '*LiveServerIT*'
```

The suite is skipped unless
`IFINMAIL_LIVE=1` and a password are set; no credentials are stored in the repository.
`DiscoveryAutoConfigSourceTest` pins the autoconfig XML the backend serves.
