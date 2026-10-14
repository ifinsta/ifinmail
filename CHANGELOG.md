# Changelog

## v0.0.53
- **Every explanatory page is laid out like the changelog.** Features, pricing, security, about,
  contact, docs, download, terms and privacy now put the heading and the content in the same
  centred column (56rem), with the title or label beside its text, so moving between pages no
  longer shifts the layout. The space between the heading and the first section is one tight step
  instead of a banner plus a full section of padding (about 56 px less), and sections are spaced
  like releases on the changelog. Phones are unchanged apart from the tighter gap.

## v0.0.52
- **Sign in to the console with passkeys only.** On **Passkeys → Sign in with passkeys only** a
  login can switch its console password off: a stolen or guessed password then opens nothing
  there, and only a passkey does. The *mailbox* password is untouched, because mail apps sign in
  to IMAP and SMTP with it.
  - **Guarded against lockout:** it needs enough passkeys that losing one device is survivable
    (two, or one that syncs across your devices), the account password again, and an
    acknowledgement; it hands out **ten single-use recovery codes**, shown once and stored only as
    hashes; and the passkeys that make it safe cannot be removed while it is on.
  - **The way back in:** "Lost your passkey? Use a recovery code" on the sign-in page (an unknown
    address, a wrong code and a login without codes all get the same answer; ten attempts per
    address and address per quarter-hour); an administrator can **Allow password sign-in again**
    from the mailbox profile; and the server shell has `make allow-password-login EMAIL=…`. Every
    step is audited, and a correct password for a passkeys-only login is answered exactly like a
    wrong one.
  - Migration `accounts 0013`.

## v0.0.51
- **A passkey is a way to sign in, not a second step.** Until now holding a passkey changed
  password sign-ins: after the email and password you were asked to prove yourself *again* with the
  passkey. A passkey now does what it is for: on the sign-in page "Sign in with a passkey" replaces
  the email and password (no address to type), and nothing is asked afterwards because the gesture
  is already two factors. A password sign-in is exactly as before: it is followed by an
  authenticator code only if you have an authenticator app.
  - The second-step passkey endpoints (`/accounts/mfa/passkey/…`) and the "Use a passkey" button on
    the authenticator page are removed.
  - Registering a passkey no longer marks the current session as having passed two-factor.
  - `MFA_ENFORCEMENT=required` is satisfied by an authenticator app (after a password) or by
    signing in with a passkey; merely holding a passkey no longer ends the authenticator prompt for
    password sign-ins.
  - System health reports authenticator apps for the two-factor check and counts passkey sign-in
    separately; the Passkeys, Account and authenticator pages say the same.

## v0.0.50
- **URLs are variables, and the domain people are on is the authority.** One helper,
  `backend/config/site_url.py`, answers "what address is this server at?": the domain of the
  current request when it is a real name, else the configured `MAIL_HOSTNAME` (so a setup link
  written by an administrator who opened the console by IP address still names the domain), else
  what the request used. It feeds the `site_origin` / `site_host` template variables.
  - **Emails:** the registration verification link, the mailbox setup link and the password-reset
    link are built with `reverse()` and that origin (they were literal paths joined to whatever
    `Host` header the request carried; the reset email now also carries the reachable domain).
  - **Pages:** the documentation's console address and API examples show *this* server instead of
    `mail.your-domain`; the Android manifest and download page use the same origin; the project's
    repository links and the install command come from `UPDATE_REPO` in one place.
  - **Defaults that named other people's domains are gone:** `support@ifinmail.io` and
    `https://ifinmail.dev/docs` (and `support@example.com` in the sidebar). Without `SUPPORT_EMAIL`
    the Support link opens the troubleshooting section of this server's own docs; the Documentation
    link is this server's `/docs/`.
  - **Literal paths removed** from settings (`LOGIN_URL` and friends are URL names), password-reset
    success URLs, the exposure self-check, and two scripts (the registration username check and the
    mailbox profile link read the URL from the page).
  - A test scans templates, scripts and Python for spelled-out paths, hosts and foreign domains,
    and checks that every middleware exemption names a real route.

## v0.0.49
- **Public pages know who is signed in.** The header showed "Sign in" and "Get started" to
  everyone, including an administrator who had just come from the console. A signed-in person now
  sees their avatar and name, **Open console** (only when their login may open it; a plain
  mailbox gets just **Sign out**) and **Sign out**; the phone menu shows the same with the
  address. The Android download page sends an administrator straight to *Settings → App
  releases*. The sign-in page sends someone who is already signed in to the console, or to the
  page they were headed for (`?next=`, same site only); `?switch=1` keeps the form for another
  account. The header switches to the Menu button below 1200 px while signed in.
- **Changelog, terms and privacy are one centred column.** The heading and the text sat at the
  left edge of a page column with a wide empty margin to their right; they now share a narrower
  column centred on the page.

## v0.0.48
- **Fix: short pages (sign-in, registration, error) scrolled on phones.** The page wrapper itself
  was sized to `100dvh`, but the `<body>`, app layout, standalone layout and main column were
  still `min-height: 100vh`. On a phone `100vh` is the screen with the address bar hidden, so the
  document was one address-bar taller (about 56 px) than the visible area and scrolled even when
  the content was short. Every full-height rule now carries its `100dvh` partner, and a test fails
  if a bare `100vh` height is added again.

## v0.0.47
- **Phone sign-in, registration and error pages: the header block is centred as one unit.** v0.0.46
  moved the title under the wordmark to the left; the intended look is the reverse, so the wordmark,
  title, subtitle, terms line, step counter, status icons and the links under the card are all
  centred on one axis on phones. Labels, fields and buttons still fill the width. Error pages
  match.

## v0.0.46
- **Phone sign-in and registration cards share one left edge.** The wordmark, labels, fields and
  links were left-aligned while the title, subtitle, terms line and step counter stayed centred,
  so the logo looked misplaced against the heading under it. On phones everything in the card now
  starts at the same edge, including the step counter, the status icons and notes, and the
  "Sign in" / "Use a different email" links (which had no side padding on some steps).

## v0.0.45
- **Phone and tablet layout review.** Every public page, the sign-in/registration/setup/error
  pages and the console were rendered at 360, 390 and 768 px and measured for text on the screen
  edge, horizontal scroll and page height. Fixed:
  - **Docs page had no side padding** (also on tablets): `.ifinmail-site-docs` is also the page
    wrap and a `padding: x 0` shorthand removed its gutter.
  - **Auth pages did not fit the viewport.** The page and the card were both forced to `100dvh`
    with `!important`, so the card filled the screen and the "Back to sign in" / footer link fell
    below it: a 29 px scroll on a page with room to spare, and that link on the screen edge. The
    page is now exactly one viewport, the card as tall as its content, centred with its link.
  - **Error pages** were 64 px taller than the screen at every width (the class sat on `<body>`
    and on the block inside, each adding padding and a minimum height) and their content hung
    near the top; they are now one viewport and centred.
  - **Site header on tablets:** between 768 and about 860 px the links and buttons ran past the
    screen (horizontal scrollbar). The Menu button now takes over below 880 px.
  - **Console:** the help line under *API keys* and the update-check line on *System health* had
    no side margin; empty-table messages were clipped on phones ("No keys yet. Create one above
    for the first integrati"); a session row on *User management* had text on its border.
  - Tests keep the wrap-gutter rule, the header breakpoint and the auth-page height rule in place.

## v0.0.44
- **Fix: the contact-directory job was not registered in the worker.** v0.0.42 added
  `accounts.publish_directory`, but the worker only imports tasks from the apps listed in
  `backend/config/celery.py` and `accounts` was not one of them, so the five-minute schedule
  logged "Received unregistered task" and switching the directory on would not have published
  anything. `accounts` is now listed, and a test checks that every scheduled task is registered
  (eager mode in tests had hidden it). The directory was off, so nothing was affected.
- **Hardening: anonymous update checks cannot fill the device table.** The Android update
  manifest needs no credentials, so anyone could invent device ids and add a row per request.
  New devices are no longer recorded past 100,000 tracked devices (known devices keep updating),
  on top of the existing 180-day prune.

## v0.0.43
- **Android app: download page and over-the-air updates for in-house releases.**
  - **Server** (`backend/apps/core/releases/`): publish signed APKs from *Settings → App releases*, the v1 API
    (`/api/v1/releases/android`, scope `system.manage`) or `manage.py publish_release`. The APK is read
    server-side (package, version, `minSdk`, signing certificate), repeated version codes and a changed signing
    key are refused. `stable` and `beta` channels, staged rollout, mandatory floor, withdraw/restore, and
    adoption per version from anonymous device check-ins (pruned after 180 days).
  - **Public surfaces:** `/download/` page (SHA-256, QR code, steps, history), the permalink
    `/updates/v1/android/latest.apk` and the manifest `/updates/v1/android/latest.json`.
  - **App:** background and foreground checks, inbox banner, Settings → Updates, a blocking "Update required"
    screen for mandatory builds, resumable verified download, on-device identity check, `PackageInstaller`
    install. French and English strings.
  - **Operations:** `clients/android/scripts/release.py` (keygen, bump, notes, build, verify, publish, tag), an
    *Android release* GitHub workflow, `docs/android-releases.md`; nginx serves
    `.apk` files as attachments; `releases.prune_checkins` runs daily.

## v0.0.42
- **Profile photos, and a contact directory that puts them in people's mail apps.**
  - **Photo:** **Account → Profile photo** takes a JPEG, PNG, WebP or GIF (up to 5 MB), lets you
    drag and zoom a square, and keeps two small JPEGs (256 and 96 px) in the database. The
    original file is never stored: it is decoded and re-encoded, so metadata (location, camera,
    embedded profiles) and anything hidden in the file are dropped. Pictures over 25 megapixels
    are refused before they are decoded. The photo appears in the console header; it is served
    only to its owner and to people who manage mailboxes, with a content-hash URL so a change
    shows at once.
  - **Contact directory (off by default):** **Settings → Mailboxes → Contact directory**
    publishes every active mailbox (name, address, photo) as a vCard in a read-only address book
    named after the brand. The `dav` container mirrors it into each mailbox's CardDAV home as
    `directory`, so it appears in the contacts of iOS, macOS, Android (DAVx5) and Thunderbird
    with no import. People can hide themselves (Account). It is withdrawn again when switched off.
    Gmail, Outlook and other apps that keep their own contacts do not use CardDAV and will not
    show it.
  - **API:** `GET`, `POST` (multipart `photo`, optional `crop_x`/`crop_y`/`crop_size`) and
    `DELETE /api/v1/mailboxes/{address}/photo`, scope `mail.manage`. A console login cannot be
    changed through a key, as with the other mailbox operations.
  - **Dav container:** Radicale now uses a rights file (`from_file`: the three `owner_only`
    rules plus a read-only `{user}/directory`), `lc_username` so one home exists per address,
    and runs `directory-sync.py` beside it; its heartbeat is part of the healthcheck. Verified
    against Radicale 3.8.3: the book is listed and readable in every home, writes to it are
    refused (403), other people's homes stay private, and switching off removes it.
  - **Dependency:** Pillow 12.3.0 (hashed in `prod.lock`), used only to re-encode uploads.
  - Migration `accounts 0012` adds `accounts_user_profile`. Privacy page and README updated.

## v0.0.41
- **A logo and a design for it.** ifinmail now has its own identity: an open envelope whose flap
  is a roof, with the wordmark set in two weights (**ifin**mail).
  - **Where it shows:** the console sidebar, sign-in / registration / setup / error cards, the
    public site header and footer, the browser tab and home-screen icon, the web-app manifest
    (PNG, maskable and SVG icons), the Branding settings preview, and the system emails
    (a PNG lockup, since mail clients drop SVG). The README carries the lockup too.
  - **Branding rules unchanged:** an uploaded logo always wins, and a renamed brand without a
    logo still shows its name as text — the mark appears only for the unrenamed product. The
    mark is drawn inline, so it follows the light, dark and high-contrast themes and a custom
    primary colour.
  - **Assets** (`frontend/static/icons/`): `mark.svg`, `mark-glyph.svg`, `favicon.ico/.svg`,
    `icon-192/512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`, wordmark and lockup in
    light and dark (letters outlined), `lockup-email.png`. Usage rules: DESIGN.md → Logo.
  - **Fix:** Branding settings no longer shows a made-up `header_logo_v2.png` as the current
    logo file when none is uploaded.

## v0.0.40
- **External file storage: a neutral storage contract, with S3-compatible object storage as the
  first plugin.** No new dependency: the S3 driver signs requests itself (AWS Signature V4 with the
  standard library).
  - **Contract** (`backend/apps/core/storage/contract.py`): an `ObjectStore` protocol (put, streamed
    put, get, streamed open, head, exists, delete, list, retrieval URL, probe), one set of key rules
    (relative, no `..`, no control characters, at most 512 bytes) and one set of errors (not found,
    unavailable, rejected, invalid key). Drivers register by name; `local` (atomic writes on the
    server's disk) and `s3` ship built in.
  - **S3 driver:** path or virtual-host addressing, multipart upload for large files (16 MB parts,
    aborted cleanly on failure), streamed downloads, ListObjectsV2, pre-signed URLs (at most 7
    days), retries with backoff on throttling and server errors, credentials never logged.
  - **Plugin:** *Object storage (S3-compatible)* (Marketplace) contributes the engine-neutral
    `storage.objects` capability: endpoint, region, bucket, prefix, access key, secret key (stored
    encrypted), addressing, how files are handed out, and whether media and/or backups go there.
    Without it, everything stays on the local disk as before.
  - **Media:** Django's default storage routes through the contract, so `StoredFile` and branding
    uploads land in the bucket. `/media/...` links do not change: nginx serves a file that is on
    disk, and otherwise asks the console, which redirects to a signed link, to a public/CDN
    address, or streams it. Only branding and files marked public are shown to visitors; the rest
    need an administrator.
  - **Backups:** with backups routed to object storage, the nightly off-site step uploads the
    encrypted archive, compares SHA-256 and prunes to the retention. Unencrypted archives are
    refused. `manage.py storage check|status|upload|list|prune|sync-media`.
  - **Health:** a connection test twice an hour, a *File storage* System health check, and
    **Settings → File storage** (where each kind of file is kept, *Test connection*, *Copy media to
    object storage*). Failures and recoveries are audited once each.
  - Verified against the AWS-published SigV4 examples and end to end against two independent
    S3 implementations (Garage and SeaweedFS), including a 40 MB multipart backup and signed
    redirects fetched by a plain client. Design and research: `docs/storage-contract.md`.
- Tests no longer touch the repository's `branding_overrides.json`.

## v0.0.39
- **Passkeys: sign in to the console with a fingerprint, face, screen lock or a security key.**
  Part of core account authentication, with no new dependency (the WebAuthn checks use the
  `cryptography` package the console already ships).
  - **Passwordless sign-in.** *Sign in with a passkey* on the login page: the browser offers the
    passkeys it holds for this site, one unlock signs the person in. The authenticator must verify
    the person (PIN, fingerprint or face), so a passkey sign-in counts as two factors on its own
    and satisfies `MFA_ENFORCEMENT=required`.
  - **Second step.** Someone who has a passkey is not let in by a password alone: after the
    password they unlock the passkey (or enter an authenticator code, if they have an app too).
  - **Management (Settings → Passkeys).** Add (name, and the person's password again, so a stolen
    session cannot plant its own passkey), list (device-only or synced, added, last used) and
    remove (password again). Up to 10 per login. Every change is audited.
  - **What the server checks:** the one-time challenge (single use, 5 minutes), the origin and the
    domain the passkey was made for (a look-alike site cannot use it), that the person was present
    and verified, the signature (ES256, Ed25519 and RS256), that the passkey belongs to the person
    named, and that the authenticator's counter moves forward (a clone is refused and audited as
    `passkey_clone_suspected`). Only the public key is stored. Attestation is not trusted
    (passkeys are trust-on-first-use, as consumer passkeys are).
  - **Limits, stated:** needs the console's own https:// domain name (WebAuthn does not work on a
    bare IP address); only console logins (administrators), since ordinary mailboxes have no
    console; recovery of a lost device is by another passkey, the authenticator app's recovery
    codes, or another administrator.
  - System health counts passkeys as a second factor for administrators.
  - Verified end to end in a real browser with Chrome's virtual authenticator: registration,
    passwordless sign-in and the second step, with the real JavaScript and no console errors.

## v0.0.38
- **Exposure check: the server looks at itself the way a stranger does.** Weekly (Sunday 03:10
  UTC) and on *Run now* (Settings → Network → Exposure check), from inside the stack, against this
  server's own names and address only. It asks for 22 files scanners ask for on each name (a 2xx is
  an error), probes 12 ports that must never be open (PostgreSQL, Redis, the console, the spam
  filter, the Docker API...), validates the certificate (chain, name, days left, TLS version),
  reads the security headers (missing, repeated, version shown), and talks to the mail ports as an
  open-relay or address-harvesting tool would (it stops at `RCPT TO`; it never sends a message):
  relay refused, VRFY not offered, no AUTH before STARTTLS on 587, no plain-text IMAP login, and a
  recursive DNS query refused (an open resolver amplifies attacks). The result is stored, audited
  and shown in System health.
- **First real scan found three things; all fixed.** nginx told strangers its exact version
  (`server_tokens off`); HSTS, X-Content-Type-Options and X-Frame-Options were sent twice (nginx and
  the console, with two different HSTS max-ages), so nginx's copy now stands alone and Referrer-Policy
  agrees with the console's stricter value; and Postfix offered `VRFY`, which lets anyone ask which
  mailboxes exist (`disable_vrfy_command = yes`).
- **Canary paths ban on the first hits.** `/.env`, `/.git/...`, `wp-login.php`, `phpmyadmin`,
  `xmlrpc.php`, `/.aws`, backups and similar paths that nothing here uses count as 15 refusals each
  (whatever the answer was), so a scanner is in the penalty box after two requests instead of 30.
  `/.well-known/security.txt` is deliberately not on the list; this server, its own side and the
  allow-list are exempt as before. Tested against the real agent and kernel.

## v0.0.37
- **Mail trace (Logs → Mail trace).** Search by address, domain or queue id and see each matching
  message as one timeline: received (and who signed in), queued, the spam filter's verdict with its
  score, every delivery attempt (deferred with the remote server's reason, sent, bounced), and
  delivery to the mailbox. The three logs are joined by Postfix's queue id and by the Message-ID
  (which is how Dovecot's line is found). Subjects and message text are not in the logs and are not
  shown; addresses are, so the page needs the audit-view permission.
- **The weekly report by email.** Monday 07:30 UTC the administrators get the week's report as
  plain text: sources needing attention, mail, web, security, errors and the top findings, with a
  link to the full page. `LOG_REPORT_EMAIL=0` turns it off.
- **The assistant can answer from the same data** (`log_report`: is everything logging, how much
  mail was handled, what happened this week). It gets counts and the kinds of changes, never
  addresses or change details.

## v0.0.36
- **Logs → Report: one report across every log the console collects.** A health banner (how many
  sources are reporting, which need attention), a summary strip, a *Log sources* table (status,
  newest line, lines in the last hour, how long each is kept, a note), and panels for mail
  (received, delivered, sent on, deferred, bounced, relay attempts refused, mailbox sign-ins, spam
  filter decisions), web and API (status classes, refused, closed without an answer, busiest minute,
  slowest page), security (findings, blocks, failed sign-ins, new places) and changes. A period
  selector (24 hours, 7 days, 30 days) and a JSON export.
- **Built to cost the same at any volume.** The report is a sum of the hourly summaries the
  threat digest already writes: each source is reduced to a few counters per hour (never an
  address, a subject or a message), so a month of a busy server is 720 small rows. The page does
  not read a log file.
- **The silence detector.** A source that stops writing is a finding (*A log has gone quiet*):
  the web server after 30 minutes, Postfix after 6 hours, Rspamd after 12, Dovecot after 48. A dead
  log looks like a quiet system, which is exactly when you are blind.
- **A blocklist that refuses this server is a finding** (*A spam blocklist is refusing this
  server's lookups*), from Rspamd's own log, so a repeat of the URIBL problem fixed in v0.0.35 is
  seen the first hour.
- Mail flow is now understood from the Postfix log (queue id kept so one message can be followed
  across Postfix, Rspamd and Dovecot) and the spam filter's verdicts from Rspamd's log: counts only.
- Next: Mail trace, the weekly report email and an assistant tool on the same data.

## v0.0.35
- **The spam filter's blocklists work again.** Rspamd logged "DNS query blocked on
  `multi.uribl.com` ... possibly due to high volume" 84 times in a day: URIBL (and other
  blocklists) refuse the shared and public resolvers Docker forwards to, so URL blocklist checks
  were silently off. A small recursive resolver of its own (`resolver`, Unbound, about 11 MB,
  internal only, healthchecked) now answers Rspamd's lookups; the embedded Docker resolver is only
  a fallback if it is down. Checked against the real lists: the URIBL, DNSWL and Spamhaus test
  points all answer through it.
- **Spam decisions are kept.** Rspamd's log was a file inside the container, lost on every update
  and never rotated. It is now on the `mail_logs` volume (`rspamd.log`, 16 MiB plus one rotated
  copy, readable by the console), still forwarded to `docker logs`; its healthcheck no longer
  asks the controller, which logged a line every 30 seconds (a third of the whole log).
- **Health checks stopped talking.** Radicale (DAV) logged two lines every 30 s for its own
  check, Knot logged `control, received command 'status'` every 30 s, Redis logged every
  background save. The checks and log levels changed so those services log only what happens.
- **Audit trail hygiene.** `domain_provisioned` is recorded when a domain is new, when a person
  asked, or when the outcome changed; the scheduled re-check that finds nothing changed was 27% of
  the trail. `warn` and `warning` are one word (`warning`) for new events; existing entries are
  untouched because the trail is hash-chained.
- First step of the unified-logs work (sources on volumes, one vocabulary); the report follows.

## v0.0.34
- **The Errors tab shows errors again.** An analysis of the 4,914 `DisallowedHost` events since 11
  October found all of them to be scanners (92% on this server's own setup names, the rest on
  made-up Host headers), and 3,793 more were `Resolver404` scanner 404s: 99.9% of the 8,714
  recorded errors, against 7 real ones. A request for a Host or a page that does not exist is an
  answer, not a defect, so it is no longer recorded (the access log still has it, and the threat
  digest counts it). The backlog is purged by the update, and the daily compaction clears any that
  an older release records.
- **nginx closes unknown Hosts before the console is involved.** The Host must be one of the
  console's `ALLOWED_HOSTS`, the mail host or the server address; anything else gets the
  connection closed (444) with no answer, no Django request and no database write. The setup names
  (`autoconfig.`, `autodiscover.`, `mta-sts.`) of every hosted domain still serve their real
  paths (`/.well-known/mta-sts.txt`, `/mail/config-v1.1.xml`, `/autodiscover/autodiscover.xml`)
  and nothing else. The list is generated from the same environment variable the console reads,
  so the two cannot disagree; an empty list or `*` allows everything.
  Tested against a real nginx: known hosts and the setup paths pass through, an unknown host and
  scanners on the setup names get no answer, the port-80 redirect and ACME challenges are
  unchanged.
- **The Threats summary strip has a *Refused* figure** (requests answered 4xx in the last hour,
  including those nginx closed), so the volume of scanning is visible without the noise.

## v0.0.33
- **Scanners are cut off within seconds, not after the burst.** The firewall agent now reads nginx's
  access log (read-only) every few seconds. An address the web server refuses 30 times within
  about 15 seconds (a tool working through `/.env`, `/.git/config`, `/admin/phpinfo.php` ...) goes
  straight into the kernel's penalty box: every new connection from it, on every port, is dropped
  for 10 minutes. Before, the blocks came from the threat digest, which looks every ten minutes,
  after a 16-second scan had already finished (as on this server today: four bursts of 170-268
  requests from Google Cloud and DigitalOcean networks, each blocked only afterwards).
  - Static files are not counted (a stale page can miss several), nor are successful requests;
    this server, its own side and the allow-list are never banned; the log's past is ignored when
    the agent starts; log rotation is followed.
  - The digest still turns the same scanner into a finding and a longer, escalating block.
  - The Network page and System health show how many scanners were banned since the firewall
    started. `SCAN_BAN_THRESHOLD` (firewall environment) changes the 30.
  - Measured against a real kernel and agent: a 40-request /.env burst (IPv4 and IPv6, compact and
    spaced JSON, and after a log rotation) was banned within two seconds; 40 static-file misses,
    an allow-listed scanner, 10 mistakes and 40 successful requests were not.
- Tests no longer depend on the time of day they run at.

## v0.0.32
- **Repeat offenders are blocked longer.** An automatic block lasts the chosen time (24 hours by
  default) the first time, then doubles each time the same network is blocked again within a
  month: 24, 48, 96 hours, then a week at most. Every block still lifts itself; the email says
  when a network came back.
- **Denial-of-service guard, decided in the kernel the moment a limit is crossed** (the threat
  digest only looks every ten minutes). On whenever the connection limit is on:
  - *Penalty box:* an address opening connections at four times a limit or more (a flood, not a
    busy office) loses every new connection on every port for 10 minutes.
  - *Just over a limit* only loses the excess, as before; short bursts (a mail app opening several
    connections) are allowed.
  - *The web ports are guarded all the time* now: 600 new connections a minute per address
    (240 during flood mode). Before, they had no per-address limit unless flood mode was on.
  - *Open connections per address* are capped (50 mail, 100 web), so one address cannot hold every
    login slot or web worker open with slow requests.
  - This server, its own side and the Automatic protection allow-list are never limited; explicit
    blocks still apply to them. The firewall agent reports how many addresses are in the penalty
    box, shown on the Network page and in System health.
  - Measured against a real kernel: 60 connections at once from one address (an office) passed 45
    and dropped the excess with no penalty; a flood of 400 put the address in the penalty box,
    cutting it off the web port too; the same flood from an allow-listed address passed
    untouched; 60 held-open connections were capped at 50.
- **Slow-request protection in nginx:** a client that trickles its headers or body is cut off in
  seconds (header 10 s, body and send 20 s between reads), and over-limit answers are 429 rather
  than 503.
- **Flood mode also starts from the adaptive baseline**: web traffic far above normal for the hour
  turns it on even when no single network stands out.
- Overlapping blocked networks (a /16 and a /24 inside it) no longer make the kernel reject the
  whole rule set: they are merged first.

## v0.0.31
- **Automatic protection is now on by default.** Both parts (block networks that are attacking;
  tighten the limits during a flood) are on until an administrator turns them off on Settings →
  Network, and a choice that was saved is kept. Everything v0.0.28 promised still holds: each
  block is temporary (24 hours by default), audited and emailed, and never covers the server, the
  server's own side, the allow-list, or a finding an administrator has acknowledged.
- A probe that made the server raise an exception (a stranger triggering an error on purpose) now
  counts as a network finding: it can be blocked from the page and by automatic protection.
- **Wider protection for real users, since it is now on:** a network is also left alone when a
  mailbox signed in from it in the last hour or an account was last seen signing in from it in the
  last 14 days (before, only console and API-key use counted).

## v0.0.30
- **The adaptive service: the digest learns what is normal on this server and flags what is not.**
  It only raises findings; it never changes a limit or a block by itself (that stays with the
  opt-in Automatic protection). `THREAT_ADAPTIVE=0` turns it off.
  - **Where traffic comes from.** Country and network operator for every network, from a free
    offline database (DB-IP Lite, CC BY 4.0; about 60 MB as one SQLite file in the runtime volume,
    downloaded monthly, refreshed by an hourly check that is a no-op while it is current). Lookups
    are local: no visitor address leaves the server. Findings show the place beside each network,
    and the Threats page has a *Where it comes from* panel (operators, countries).
  - **Campaigns.** Three or more networks of one operator with findings in the same hour become one
    finding, *Several networks of one operator are attacking at once*, which can be blocked
    together from the page (the same password, own-address and expiry rules).
  - **Learned places.** For every account (console and mailbox sign-ins) it remembers the country
    and operator it signs in from. After an established history (5 sign-ins over 2 days) a
    sign-in from somewhere new is a finding: medium for a new country, low for a new operator in a
    known country. Nothing is learned until location data is installed. Places unused for 180
    days, or of a closed account, are dropped; the privacy page says so.
  - **Traffic baseline.** The hour's web requests and failed console and mail sign-ins are
    compared with the same hour of the day over 14 days (median and spread); far above it is a
    finding even when no single network crosses a threshold. Quiet hourly rows are now kept 28
    days instead of 7 so there is a baseline.
- The assistant sees the same aggregates only (countries, operators, masked accounts).

## v0.0.29
- **Phase 4 of the entry-point firewall: the mail ports in the threat digest.** Until now the
  digest saw the web server and the console's sign-ins only; password guessing against IMAP, POP3
  and SMTP submission, and relay probing, were invisible. Postfix and Dovecot now write their logs
  to a size-capped file on a new `mail_logs` volume (the console mounts it read-only) while
  `docker logs` shows the same lines as before; each file is rotated at 16 MiB and stays readable.
  Without the volume both fall back to the container output.
- **New findings** (kept: failed and successful mail sign-ins, refused relay attempts, refused
  recipients that do not exist; never message content): *Password guessing against the mail ports*
  (medium for one account failing repeatedly, which is usually a client with an old password; high
  for spraying across accounts or sheer volume), *Someone is testing whether the server relays*,
  *Someone is guessing which mailboxes exist*, *Password guessing from many networks at once*, and
  *A mailbox signed in from a network that was guessing passwords* (critical). They appear on the
  Threats page with a *Failed mail sign-ins* figure, offer the one-click block, and are covered by
  opt-in automatic blocking. The assistant sees masked account names only.
- **Fewer false alarms in the log:** a request for a Host this server does not serve is answered
  400 and counted by the digest from the access log, but no longer logged as an ERROR with a
  traceback each time.
- This completes the four phases of the firewall and entry-point work.

## v0.0.28
- **Phase 3 of the entry-point firewall: automatic protection, opt-in.** Settings → Network has a
  new *Automatic protection* panel with two switches, both **off** until an administrator turns
  them on (password again), and an allow-list of networks that are never touched.
  - **Block networks that are attacking.** After each threat pass (every ten minutes) a network with
    a serious open finding (a scanner that got answers, a flood, password or API-key guessing) is
    blocked for 1, 6, 24 (default), 72 or 168 hours and then released by itself. It never blocks
    the server's own address, ranges on the server's own side, the allow-list, a network anyone
    signed in from in the last week or an API key was used from in the last month, or a finding an
    administrator has acknowledged. At most 10 per pass and 50 automatic blocks in force; the
    audit trail records each (`network_auto_block`) and the administrators are emailed.
  - **Tighten during a flood.** When traffic arrives from many networks at once, each address is
    held to 30 new connections a minute on the mail ports (never looser than your own cap) and 240
    on the web ports, which have no per-address limit otherwise. Connections already open are not
    touched. It ends by itself two hours after the flood stops (`flood_mode_on` / `flood_mode_off`
    in the audit trail), and System health shows *Flood mode is on* while it lasts.
- **Measured against a real kernel** with flood mode rules: 300 rapid attempts at a mail port were
  held to 54 accepted, 300 at the web port to 186 accepted over the same period; the agent applied
  the rules and its healthcheck stayed healthy.
- The Network page lists only blocks still in force.
- Next phase: mail-port login guessing (Postfix and Dovecot) in the digest.

## v0.0.27
- **Phase 2 of the entry-point firewall: block a network from the finding that names it.** A
  finding about a scanner, a flood or password guessing now has *Block this network* (for people
  who may manage security). Choose 1 hour, 24 hours (the default), 7 days or until removed, type
  your password again, and the rule is published at once. Your own address and this server's cannot
  be blocked, ranges on the server's own side (LAN, loopback, link-local) are refused, and a finding
  that is not about a network (an account, the console) offers nothing to block. The finding is
  acknowledged and the block is audited with the finding it came from.
- **Blocks can expire.** A block with a time limit lifts itself: the console removes it within five
  minutes, republishes the rules and records `network_unblock` by the system. The Network page
  shows an *Until* column; blocks you add by hand there stay until you remove them. An entry whose
  time is up is never in the published rules, even before the sweep has run.
- A malformed finding id on the Threats page is now a message instead of an error page.
- Next phases (each its own release): opt-in automatic blocking with expiry and a tighter cap
  during a flood; mail-port login guessing (Postfix and Dovecot) in the digest.

## v0.0.26
- **Phase 1 of the entry-point firewall: make it true.** The Network page showed a connection cap
  and open ports as if they were enforced, but the rules were written only when someone changed a
  setting there. On a server nobody had configured, the firewall agent had been "waiting for rules
  from the console" since it started and *nothing* was enforced, including the per-address cap on
  mail-port connections that limits floods. The console now publishes the rules itself, five
  minutes after start-up and whenever the file is missing or has drifted (cheap and quiet: it
  writes only on a difference, and records `firewall_published` in the audit trail).
- **System health: Entry-point firewall.** In force (and what that means: ports closed, networks
  blocked, the cap), being applied, rejected (the previous rules stay in force), or the agent not
  reporting.
- **Emergency stop documented** on the Network page and in the README: `docker stop
  docker-firewall-1` removes every rule at once; SSH is never filtered.
- **What turning it on does, measured against a real kernel:** with the default rules one address
  was held to 120 new connections a minute on mail port 25 (131 of 240 rapid attempts dropped) while
  HTTPS was untouched (240 of 240 accepted); the agent's own healthcheck stayed healthy. Only mail
  ports are capped; HTTP, HTTPS and DNS never are, and locked ports cannot be closed.
- Next phases (each its own release): one-click "Block this network" from Threats findings with an
  expiry; opt-in automatic blocking and a tighter cap during a flood; mail-port login guessing
  (Postfix and Dovecot) in the digest.

## v0.0.25
- **Every container now has a healthcheck.** The firewall agent was the only one without: Docker
  could say it was "Up" while the agent was frozen or the rules it was meant to enforce had been
  rejected. Its check is real: the agent's heartbeat is fresh, `nft` answers, the `inet ifinmail`
  table exists when rules were applied, and the last rule set was not rejected. "Waiting for rules
  from the console" is healthy; a rejected rule set, a silent agent or a vanished table is not.
  Checked against the real agent in five states (waiting, applied, rejected, recovered, frozen).
- A test fails the build if any service is added without a healthcheck, or with a disabled or
  trivial one.

## v0.0.24
- **A threat digest.** The console now reads what scanners and attackers do and keeps only what a
  decision needs. nginx writes a JSON access log (size-capped, in its own volume, read-only for the
  worker) and the worker, every ten minutes, joins it with the sign-in record, finds the threats,
  keeps one slim row per hour and a list of findings, and discards the rest.
- **Findings that say where to tighten.** Scanner sweeps (refused is *medium*; answered or a flood is
  *high*), floods from one network or many, password guessing and spraying, one account attacked from
  many networks, second-factor guessing, API key guessing and a *real* key being attacked, a sensitive
  file being served (critical), a sign-in that succeeded after repeated failures (critical), and a
  probe that made the server raise an exception. Each names the network (/24 or /48), a few request
  ids and the console page that holds the control (Network & entry points, Security, API keys, Users).
- **Request ids join the layers.** nginx's `$request_id` is now sent to the console as
  `X-Correlation-ID` (a client can no longer choose it), so one request can be followed from the web
  log to an error record or the audit trail. That is how "a probe crashed the login view" is found.
- **The assistant writes the gist when it is connected**, and only from aggregates: networks, probe
  classes, counts, masked account names, never addresses, user agents or message data. It must
  answer in a small JSON shape, may only point at findings that exist, spends at most 40% of the
  day's budget and at most once every 30 minutes, and a model outage or a garbled answer leaves the
  rule-written summary in place. Without a model the page is written by rules. New assistant tool
  *Threat digest* and two suggestions: *Is anyone attacking this server?* and *What should I tighten
  first?*
- **Discarding.** INFO and WARNING error events after 48 hours, hours with no findings after a week,
  resolved findings after 30 days; the hash-chained audit trail is never compacted.
- **Page and alerts.** Settings > Threats (verdict, the last hour, findings, hour by hour). Serious
  findings are emailed once a day and written to the audit trail (`THREAT_ALERTS=0` for no email,
  `THREAT_DIGEST_ENABLED=0` to switch the digest off).
- **Fix:** the address recorded for sign-ins in the audit trail was the *first* entry of
  `X-Forwarded-For`, which a client can write. It is now the last entry, the one nginx appended, so
  neither the audit trail nor the digest built from it can be given a chosen address.
- Checked against this server's real 24 hours of traffic: about 4,400 requests from 194 networks gave
  21 findings (15 medium, 4 high, one flood, one burst of server errors), not hundreds.
- 60 tests; strict mypy covers the package.

## v0.0.23
- **Send email through an API key.** `POST /api/v1/messages` (scope `mail.send`): `from`, `to`,
  `cc`, `bcc`, `reply_to`, `subject`, `text` and/or `html`. `202` means the server accepted the
  message for delivery; it is signed with DKIM and sent like any other outgoing mail.
- **A sending key names who it may be.** It lists the addresses it may send as (`name@domain`, or
  `*@domain`), which must be on hosted domains and are checked again on every send, so removing a
  domain stops the key. Support and other read-only roles cannot create one: `mail.send` is a new
  permission held by Owner and Administrator.
- **The guards submission gets from Postfix, applied in the console** (the internal relay trusts
  the Docker network and checks nothing): recipients per message, blocked destinations,
  internal-only mailboxes and messages per minute and per day for the From address (all from the
  Outbound policy plugin), a paused mailbox cannot send, and each key has a daily cap on recipients
  (default 500, `API_SEND_LIMIT_PER_DAY`) that answers `429` with the wait until midnight UTC.
  If the quota store is down the send is refused, not unlimited.
- **Containment sees API mail.** What a key sends is added to the same hourly counters Rspamd writes
  for a logged-in mailbox, so a flood through a key pauses the mailbox like a flood through a
  password.
- **`Idempotency-Key`** (up to 64 characters) makes a retry safe: the same key and message return
  the first answer; a different message under the same key is refused.
- **Cannot be turned into a mail cannon or a spoofing tool:** no attachments, no custom headers,
  bare addresses only (a newline or a display name is refused), a single-line subject, 100
  recipients and 1 MB per message. Every send is audited with the key, the From address and the
  recipient domains, never the content.
- Console: **Settings > API keys** has *Allowed senders* and *Recipients per day*; the mailbox
  profile token form no longer offers `mail.send` (it has no field for senders). The assistant
  knows the new operation, flags keys that can send as a whole domain, and the contract lists it.
- Checked over real HTTP into a real SMTP socket: envelope sender, every recipient including Bcc
  (with no Bcc header), the Message-ID in the sender's domain, the HTML alternative, and exactly
  one message for an idempotent retry. 36 new tests; strict mypy covers the new service.

## v0.0.22
- **Every API is versioned.** The health reports and the error log that lived outside `/api/` are
  now `/api/v1` operations (`GET /health`, `/health/full`, `/health/dns`, `/health/deliverability`,
  `/telemetry/errors`, `/telemetry/stats`, `/telemetry/fingerprints`, and acknowledging a
  fingerprint), plus `GET /dns/status`. The old `/health/full/`, `/health/dns/`,
  `/health/deliverability/` and `/telemetry/*` paths answer `308` to the versioned ones. `/health/`
  stays as the infrastructure probe (Docker, nginx and the updater use it).
- **Security fix on the way:** the detailed health reports were open to anyone who could reach the
  server. They ran live DNS, blocklist and port checks on every call and returned internal error
  text and your domain names. They now need a key with `audit.view`; only liveness is anonymous.
- **A rule that cannot rot.** Every JSON endpoint is a v1 operation or is listed in
  `backend/config/api_versions.py` with the reason it is not (browser or mail-client formats, probes,
  and the console's own page calls). A test scans the URL configuration and fails on a new one.
- **Type safe.** Every request and response of the API is a typed schema (the contract has no
  untyped field), every handler and the authentication layer are annotated, all errors are one
  documented `{"detail"}` shape, each operation states `x-required-scope` in the OpenAPI document
  (read from the code that enforces it), and strict **mypy** covers the API layer (`make
  typecheck`, and a CI step). It found and fixed three real problems while being introduced.
- **The assistant knows your API integrations.** Two new read tools: *API overview* (versions,
  authentication, every operation with its scope, rules; read from the live contract so it cannot
  describe an endpoint that does not exist) and *API keys* (which keys exist, owner, scopes, expiry,
  last use, and what looks wrong: expired, unused, too broad, owner no longer holds a scope; plus
  failed authentications and changes made with keys). Secrets never reach it, and `ifs_` / `ifm.`
  values are masked if they appear anywhere. Two suggestions on the start page: *How can a program
  manage mailboxes through the API?* and *Are my API keys set up safely?*
- Found while moving them: the old error-log endpoint returned blank fields for every event (it
  serialised dictionaries with `getattr`). The v1 version is typed and tested.

## v0.0.21
- **The Assistant is now a chat workspace.** Conversations are listed on the left, grouped
  (Today, Yesterday, Previous 7 days, Older), each with its own delete; **New chat** is one
  click. The reading column is centred: your question as a quiet bubble on the right, the answer
  as plain text (full Markdown, tables, code with Copy), and a single "Checked N things · sent to
  host" line that opens to show exactly what was checked and sent. A drafted change is a card with
  the Apply button. The composer is pinned at the bottom (Enter sends, Shift+Enter adds a line,
  an arrow button sends), and a new chat starts with a greeting, the composer and suggested
  questions together in the middle.
- **No page reloads.** A question appears the moment you send it, progress and the answer replace
  the thread in place, the address updates, and the thread stays scrolled to the newest message.
  Without JavaScript every form still works as a normal post.
- Below 1024 px the conversation list is a drawer (scrim, Escape closes); touch targets are 44 px
  on phones and the composer sits edge to edge.
- Connection settings and Test connection moved into the list's footer; the page title area that
  repeated the introduction is gone.

## v0.0.20
- Fixed: the **Changelog page showed "No changelog on this server"** on installed servers. The
  image build ignores `*.md`, so `CHANGELOG.md` was never in the image (the tests read the source
  tree and could not see it). The build now keeps that one file, and a test checks the ignore
  rules.

## v0.0.19
- **An API for integrations, versioned.** `/api/v1/` now lets a program manage **mailboxes**
  (list, create, read, change quota / disable / set password, delete), **aliases** and **domains**
  (list, read, add, verify), next to the existing `status` and `metrics`. The contract is
  `/api/v1/openapi.json`; `/api/` lists the versions the server speaks. Within `v1` only additions
  are made; a breaking change will be `/api/v2/` beside it. The old unversioned `/api/<path>`
  answers `308` to the same path under `/api/v1/` (with `Deprecation` and `Link` headers), so
  existing scrapers and scripts keep working.
- **API keys: a key and a secret.** Settings → **API keys** creates a key (`ifm_…`, public) and a
  secret (`ifs_…`, shown once, stored only as a hash and compared in constant time). Present them
  as HTTP Basic (`curl -u key:secret`) or as one Bearer value. A key has scopes that can never
  exceed its creator's permissions, an expiry (at most 90 days), an optional network allow-list and
  a calls-per-minute limit (default 120; `429` with `Retry-After`, `X-RateLimit-*` on every reply).
  **Rotation can overlap**: keep the old secret working for up to 7 days while the integration
  switches. The key list shows owner, last use and address.
- **Hard to turn into a takeover.** The API cannot create a login with console access and cannot
  change or delete one (a leaked key must not be able to reset an administrator's password), and
  it does not offer domain removal. Every call that changes something is audited under the key and
  its owner; failed attempts are audited once per address and reason; all failures answer the same
  401.
- **Network allow-lists use the address nginx saw** (the last `X-Forwarded-For` entry), not the
  first, which a caller can forge.
- Fixed: on a 360 px screen the Settings pages' header was 32 px wider than the screen; the
  settings icon is now only in the account menu there.
- Tests: 41 for the API (credential format, rotation overlap, networks incl. a forged forwarding
  header, rate limit, versioning and the legacy redirect, scopes, mailboxes, aliases, domains, the
  console page, and "no operation is reachable anonymously" over the whole contract).

## v0.0.18
- **A real public site.** The landing page, Terms and Privacy are rebuilt, and seven pages that
  were only links are added: **Features**, **Pricing**, **Security**, **Docs**, **Changelog**,
  **About** and **Contact**. Compact, flat (no gradients, no shadows), responsive from 360 px, in
  the light, dark and high-contrast themes, with one heading level one and a skip link on every
  page. The phone menu needs no script.
- **Honest copy.** The old pages claimed things the project cannot back: a SOC 2 and GDPR badge,
  paid tiers ($29, "Enterprise"), a 99.9% figure, PGP, a service level. All removed. Pricing now
  says what is true (free to run, you pay for the server and domain; community support), and
  Security lists specific, checkable protections next to a plain "what we do not claim". The
  product preview is labelled "Example data". Terms and Privacy are rewritten for a self-hosted
  server (the operator is the service provider; what is stored, kept and sent where).
- **Nothing is fetched from a third party** on these pages: Inter and JetBrains Mono are served
  from this server. (Console pages still use Google Fonts unless `USE_GOOGLE_FONTS=0`.)
- **The Changelog page is this file**, rendered by the existing Markdown renderer: the newest
  eight releases, with a link to the rest.
- 800 lines of landing-page and legal CSS that nothing uses any more were deleted.
- Tests: every page renders without signing in, has one `h1` and a `main`, loads nothing
  external; the stylesheet has no gradients or literal colours; a list of claims the project
  cannot make is checked against every page.

## v0.0.17
- **Containment of a suspected stolen password.** Sending limits only slow a flood down; now the
  server notices it. Rspamd counts, per logged-in mailbox, the messages, the different recipients
  and the different recipient domains of the last hour (recipients are kept only as short hashes).
  Every minute the worker compares them with thresholds (defaults 300 messages, 500 recipients,
  100 domains, in line with Microsoft 365's outbound spam policy). A mailbox over one is **paused**
  (Postfix refuses its sending with a clear message; it can still receive and be read), the
  administrators are emailed, and **Paused senders** (linked from System health) has a Resume
  button. Choose `notify` to be told without pausing, or `off`. A pause survives uninstalling the
  plugin until someone resumes it.
- **Recipients per message** (default 100, submission ports only) and **blocked destinations**
  (addresses or domains, subdomains included, refused with a clear message).
- The plugin **Sending and delivery policy** is now **Outbound policy**, the counterpart of
  Inbound protection (its id is `outbound-policy`; no server had it installed).
- Plugin layer: *dynamic sources* let live system state (the paused mailboxes) reach an adapter
  target without being a plugin setting.
- Found while testing against real Rspamd and Redis: separate `INCR` and `EXPIRE` commands raced and
  could leave a counter that never expired; the counters are now written by one atomic script.
- Limits you should know: containment reacts within about a minute, so what a mailbox can send in
  that minute is bounded by the per-minute limit times the recipients-per-message limit; bounce
  rate is not a signal yet (that needs the delivery log). 331 handled edge cases are documented.

## v0.0.16
- **PostgreSQL now uses its tuning file.** Since the first release the database ran on the image's
  defaults: `postgres/custom.conf` was mounted but never read (an include was appended to a file
  PostgreSQL does not load). It is now the server's main configuration (`postgres -c
  config_file=...`), verified on a fresh initialisation and on a restart over existing data.
  Effects: shared buffers 64 MB instead of 128 MB (less memory), at most 50 connections (the
  console, worker and mail services use about a dozen), and quieter logs: no line for every
  connection, warnings and above only, autovacuum only when slower than a second.
- A contract test keeps the file in use and keeps what the image's own configuration provided
  (`listen_addresses`) in it.
- Updating restarts the database container once; the console and worker reconnect by themselves.

## v0.0.15
- **System logs** reworked. Activity (the audit trail) and Application errors are tabs with a
  summary (events, errors, warnings, and whether the tamper-evident chain is intact), a search box
  over event, person and details, level and period filters that apply immediately, real
  pagination (25 per page, filters kept in links) and an export that follows the filters. **Live
  view now works**: it adds new events at the top every five seconds and pauses when the tab is
  hidden (before, it only wrote to the browser console). The search box in the header works
  too, and the duplicate "audit trail" side panel is gone.
- **System health** reworked: a one-sentence verdict with the first thing to fix and a link to it;
  checks grouped by area (Mail delivery, Server identity, each domain, Server, Security) with a
  count of what needs attention per group; cards with a "How to fix" block, values you can copy,
  the console page that fixes it and "Ask the assistant"; passing checks are compact. The legacy
  left-border card styles were removed.
- **Assistant** reworked and **full Markdown** for answers: CommonMark plus tables, task lists,
  strikethrough and bare-URL links, rendered by a small renderer in this repository (no new
  package). Raw HTML is shown as text and images as plain links (an image URL could send data
  out); links are limited to http, https, mailto and same-site paths. Conversation list beside the
  thread, suggested questions, "working on it" progress that shows which check ran, Copy on
  answers and code blocks, Enter to send, a token meter, and **Delete conversation**.
- A property test parses every rendering of adversarial and random input and fails if anything
  outside the whitelisted tags, attributes and link targets appears.
- Fixed while checking in a real browser: the Copy buttons raised an unhandled error when the
  browser refused clipboard access; they now fall back to the older route.
- The documented plugin and assistant edge cases are now 318.

## v0.0.14
- Fix: an assistant draft that **cleared** a setting with a default (for example "keep Trash
  forever" on Mailbox care) was applied with the default instead (30 days), so Apply could do
  something other than what the draft table showed. Drafts now clear explicitly, and Apply
  re-validates and refuses unless the result is exactly what was shown. Found during the live
  end-to-end check of the assistant on 2026-10-12: the 30-day Trash/Junk expiry was active on that
  server for about 90 seconds and was removed at once; nobody accessed a mailbox in that window
  and no message was old enough to be removed.
- The draft table says "Default" instead of "Now" for a plugin that is not installed yet.

## v0.0.13
- Fix: the assistant runs its checks in the `worker`, which could not see the mail queue report or
  the plugin acknowledgements, so it told administrators the queue was "not reported" and plugin
  status "unknown" while System health showed them correctly. The worker now mounts the status
  folder (read-only) and has the install directory used in System health hints. Found while
  verifying v0.0.12 end to end against a real model; a contract test keeps the two in step.

## v0.0.12
- **Assistant**: ask the server why something is wrong and get a plain answer, or have it draft
  plugin settings for you to apply. Header button and "Ask the assistant" on failing System
  health checks. Works with any OpenAI-compatible API (chat completions with tool calling);
  other API styles can be added behind the same provider interface later.
  - Built-in plugin, installed by default and inert until a model URL is set; Test connection
    checks that the model can call tools. Uninstalling it is respected by later updates.
  - Tools: System health, mailboxes and aliases, plugins and their settings, recent audit
    events (read), and drafting plugin settings (validated, applied only by your click).
  - Safety: message contents are never available to it; tool results are redacted (keys,
    tokens, passwords, private keys) and shown under each answer with the host they went to;
    the key is encrypted at rest and sent only to the API host; redirects and cloud metadata
    addresses are refused; daily token budget, 8 steps per question, one question at a time;
    30-day retention; `system.manage` only; everything recorded in the audit trail.
- Plugin layer: a `secret` setting type (encrypted, never shown again, only usable by fields
  that stay inside the console), `install_by_default` for bundled plugins, and in-console adapter
  targets. 310 handled edge cases are documented.

## v0.0.11
- **Eight built-in plugins become four**, grouped by what an administrator decides together. One
  plugin can now write several capabilities:
  - **Inbound protection**: dangerous attachments, DMARC, ARC trusted forwarding, blocked and
    allowed senders, greylisting (was Attachment guard, DMARC enforcement, ARC trusted forwarding
    and half of Mail policy essentials).
  - **Sending and delivery policy**: sending limits, largest message, internal-only mailboxes,
    encrypted delivery to partner domains, forwarding-rule cap (was Partner TLS, Forwarding control
    and the rest of Mail policy essentials).
  - **Mailbox care**: Trash/Junk/Sent expiry and quota warnings (was Mailbox cleanup plus quota
    warnings).
  - **Compliance journal**: unchanged, kept on its own because it exposes all mail and needs a
    dedicated mailbox.
- Each part of a plugin can be switched off on its own (empty list, unticked box). DMARC gains an
  `off` value in the capability contract for this. Partner domains are optional (empty = none).
- Together the four plugins offer every capability field exactly once, so they never conflict;
  a test fails if one is left out or offered twice. No server had the old plugins installed, so
  nothing is migrated. 295 handled edge cases are documented.

## v0.0.10
- **Plugins no longer know which mail software runs underneath.** Manifests (now
  `manifest_version = 2`) name engine-neutral **capabilities** such as `mail.journal`,
  `sending.rate_limit`, `inbound.senders` or `mailbox.retention`, with plain values (MB, days,
  yes/no, address lists). An adapter in the mail app is the only code that knows Postfix, Dovecot
  and Rspamd: it binds each capability field to an engine setting and translates the value
  (`inbound.greylisting.enabled = yes` becomes Rspamd's `greylisting = on`). Replacing an engine
  now means re-binding the adapter; plugins, installations and their settings stay as they are.
- 13 capabilities cover everything the 8 built-in plugins do; all 8 are rewritten as version 2.0.0
  (no installed plugins existed on any server, so nothing is migrated). Version 1 manifests are
  refused with a hint. Partner TLS asks "Also require a valid certificate" (yes/no) instead of
  "encrypt / secure"; Mail policy's greylisting is a checkbox.
- The Marketplace shows each plugin's effect as capability and field ("Sending limits ·
  per_day"), never engine settings. When changes wait to be applied, the plugin page and System
  health name the containers they wait for.
- Guard rails: a test fails if a bundled manifest or a capability mentions the mail software or an
  engine setting; registration refuses a capability field bound to an unknown or already bound
  engine setting. 289 handled edge cases are documented.

## v0.0.9
- **Leaner stack: 14 containers down to 12, or 10 without the optional services.**
  - `beat` is gone: the `worker` runs Celery's scheduler in the same process (`--beat`), as one
    server needs only one scheduler. About 85 MB less memory.
  - `telemetry` is gone: it copied container logs into a file nothing read, and could see Docker.
    `make logs` shows the same logs (Docker's own rotated log files). About 40 MB less memory.
  - The DNS server (`dns`) and calendars/contacts (`dav`) are optional: `DNS_SERVER_ENABLED=0` or
    `DAV_ENABLED=0` in `provisioning/.env`, then `make provision`, removes the container. Both
    stay on by default and on existing installs. With DAV off its DNS records are not published.
- **No container can control Docker any more.** Certbot no longer has the Docker socket (which is
  root on the host) and no longer restarts services after a renewal: nginx, Postfix and Dovecot
  notice the new certificate within a minute and reload themselves, without dropping connections.
- `make update` and `make provision` remove containers of services a release dropped
  (`--remove-orphans`); `make down` and `make reload` include the optional services.
- PostgreSQL: removed a start-up script that was meant to enable TLS but wrote to a file PostgreSQL
  never reads (TLS was never on). Only containers on the internal network reach the database.

## v0.0.8
- **Users can send only as themselves.** On the submission ports (587, 465) a logged-in user may
  use as sender only their own address or an alias that forwards to them; anything else is refused
  with "Sender address rejected: not owned by user". The From header of their mail must match that
  sender (checked by Rspamd), so a user can no longer put a colleague's or the CEO's address in From
  and have it DKIM-signed and pass DMARC. Port 25, the console's own mail and Sieve are unaffected,
  and bounces (empty sender) still go out.
- Ownership is read from domains and aliases only (`postfix/pgsql/sender_logins.cf`): the Postfix
  database role still cannot read the users table. The Aliases page says that the mailboxes an
  alias forwards to may send as it.

## v0.0.7
- New built-in plugin **Mail policy essentials**, one plugin for the controls administrators need
  first, with defaults taken from Google Workspace and Microsoft 365 so it is safe to install
  unchanged:
  - blocked senders (address or domain, envelope or From header) are refused;
  - allowed senders are never treated as spam, but only when SPF or DKIM proves them, and
    attachment and malware rules still apply (Microsoft's guidance on allow entries);
  - sending limits per login: 30 a minute and 2,000 a day, in separate counters;
  - largest message 50 MB (this server's existing limit; 50 MB is also the most Rspamd scans and
    signs, so the setting cannot go higher);
  - internal-only mailboxes may send only to domains hosted here (clear 554 message otherwise);
  - greylisting on or off;
  - a notice in the Inbox at 80% and 95% of the quota, delivered even when the mailbox is full.
- New extension point `postfix.sender_policy`; new keys on `rspamd.policy`, `postfix.main` and
  `dovecot.policy`. Both submission ports now read their recipient restrictions from one parameter
  (`ifinmail_submission_restrictions`), unchanged by default.
- A plugin value that is removed from `postfix.main` restores this server's value from
  `main.cf.template`, not Postfix's built-in default.
- Fix: Rspamd counted but did not enforce sending limits (including the built-in 100 an hour) if
  Redis was not reachable when Rspamd started, for example after a reboot. The Rspamd watcher now
  reloads it once it is serving and again whenever Redis restarts.
- The Rspamd configuration test runs as `_rspamd`, so it leaves no root-owned cache files.

## v0.0.6
- New built-in plugin **ARC trusted forwarding**: seals mail this server passes on (aliases that
  forward outside) with the domain's DKIM key, and lets a valid ARC chain from a forwarder you
  trust lift a DMARC rejection, so DMARC enforcement does not bounce genuine forwarded or list
  mail. Seals verified with an independent implementation; tampering is detected.
- Plugin settings: a default now applies only when a value is not supplied, so a field cleared on
  purpose stays empty and a boolean `default = true` is honoured (it was ignored when absent).
  `configure` with some keys keeps the current values of the others.

## v0.0.5
- Five new built-in plugins: **Attachment guard**, **DMARC enforcement**, **Forwarding control**,
  **Mailbox cleanup** and **Partner TLS**.
- Three new extension points: `rspamd.policy`, `dovecot.policy` and `postfix.tls_policy`. The Rspamd
  and Dovecot containers each run a small watcher that re-validates plugin values, checks the
  configuration (`rspamadm configtest`, `doveconf -n`) before reloading, rolls back a failing one
  and acknowledges only what took effect. Partner TLS uses a `texthash:` map, so no `postmap` step.
- Extension-point values can be normalised (e.g. `EXE, .js` becomes `exe,js`).
- The Rspamd and Dovecot containers mount the runtime volume (read-only) and the status volume.
- 240 handled edge cases documented in `.agents/skills/ifinmail-plugins/`.

## v0.0.4
- **Marketplace** (sidebar, after Settings): browse, install, configure, enable, disable, update and
  uninstall plugins; submit new ones for review. Approval is always a person (`system.manage`);
  sources are internal only (built-in plugins and approved submissions).
- **Plugin layer** (`backend/apps/core/plugins`): declarative `plugin.toml` manifests, strict
  validation that reports every problem at once, extension points and setting types registered by
  the apps that own them, an installation state machine with crash recovery and reconciliation,
  and an acknowledgement so the console shows whether Postfix has applied a change. No new
  packages or services.
- **Compliance journal**, the first built-in plugin: a copy of every message to an archive mailbox.
- The postfix watcher applies a second file (`postfix-plugins.conf`) with its own allow-list.
- System health reports failed or unapplied plugins. A `plugins.reconcile` job runs every 10 minutes
  and writes only when something drifted.
- Guide, state machines and 215 handled edge cases: `.agents/skills/ifinmail-plugins/`.

## v0.0.3
- `make audit-verify` and `make reset-mfa EMAIL=...` replace the `docker compose exec` commands
  documented in v0.0.2, which failed without the environment file.

## v0.0.2
Enterprise hardening. Existing installs keep their current policy until switched on in
`provisioning/.env` (see `docs/enterprise-next-steps.md`).

- **Audit trail:** hash-chained, kept 365 days (`AUDIT_RETENTION_DAYS`, minimum 30) instead of a
  10,000-row cap; the dashboard log purge can only remove expired entries; export reads the whole
  trail from the database (`?format=jsonl` adds hashes); `manage.py verify_audit_chain`.
- **Two-factor:** `MFA_ENFORCEMENT=required` removes postponing and switching off (new installs
  default to it); `manage.py reset_mfa <email>` for a lost authenticator.
- **Backups:** verified off-site copy over SSH (`BACKUP_OFFSITE_TARGET`, `make offsite-check`) and
  `make backup-key` to export the key and prove it opens the newest backup. System health reports both.
- **Sensitive actions** (admin rights, roles, API tokens, mailbox deletion) ask for the password again.
- **API tokens** last at most 90 days.
- **CSP is enforced**; `CSP_REPORT_ONLY=true` is the emergency switch.
- **Dependencies** are hash-pinned and verified at image build; audited weekly.
- **Outbound limits:** per-login send limits through Rspamd (100/hour per login, 40/hour per
  recipient domain).
- `GET /api/metrics` (Prometheus text, token scope `audit.view`).
- `SECURITY.md`, `docs/dr-runbook.md`, `docs/risk-register.md`, `docs/secrets-map.md`.
- Fixed: mailbox profile showed the "Admin rights" row twice.

## v0.0.1
First working release.

- One-command install verified end to end; mail delivery fixes (Postfix chroot, Dovecot volume
  ownership); setup wizard required until finished; forced first password; optional two-factor;
  System health page; one brand name default.
- `make update [TO=vX.Y.Z]` with a database and configuration snapshot, automatic rollback if the
  new version is not healthy, and `make rollback` (code and database) / `make version`.
- The console shows the installed version and announces new releases (six-hourly GitHub check,
  can be switched off).
- `make uninstall` undoes the installation (including anonymous volumes of the stack's
  containers); `--check` lists anything left.
- New mailboxes: the setup link and getting-started instructions (mail app settings) can be
  emailed to an address the owner already reads, when the mailbox is created or later from the
  mailbox list or profile.
- System email (setup links, registration verification) is delivered through an internal-only
  Postfix port (10025, never published) instead of failing on a missing local mail server.
