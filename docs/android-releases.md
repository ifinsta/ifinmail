# Android releases and over-the-air updates

How ifinmail ships its own Android app to its own devices without an app store. The server hosts the
APK, a public download page and a small update manifest; the app checks the manifest, downloads the
build, verifies it and hands it to Android's installer.

Code: `backend/apps/core/releases/` (server), `clients/android/update/` (protocol, JVM),
`clients/android/app/androidApp/.../update/` (Android wiring). Console page:
**Settings → App releases** (`/accounts/settings/releases/`, permission `system.manage`).

## What people see

| Surface | Where | Notes |
| --- | --- | --- |
| Download page | `/download/` (linked from the site nav and footer) | Latest stable build, SHA-256, QR code, install steps, version history, beta list |
| Permalink | `/updates/v1/android/latest.apk` | Redirects to the newest stable APK; safe to put in an email or a QR code |
| Manifest | `/updates/v1/android/latest.json` | Read by the app; anonymous, no cookies, `Cache-Control: no-store` |
| In the app | Inbox banner, Settings → Updates, "Update required" screen | Per-version "Later" dismissal; the required screen replaces the app |
| Notification | Background check about every 12 h | One notice per version; never downloads by itself |

## Cut a release

One tool does every step: `clients/android/scripts/release.py` (Python 3, standard library only; Windows,
macOS and Linux).

```bash
python clients/android/scripts/release.py status            # local version, key, what the server has
python clients/android/scripts/release.py keygen            # once: create the signing key (then back it up)
python clients/android/scripts/release.py bump minor        # or major | patch | 1.4.2 -> gradle.properties
python clients/android/scripts/release.py notes             # draft notes from the commits since the last tag
export IFINMAIL_API_TOKEN=ifm.<key>.<secret>               # API key with scope system.manage
python clients/android/scripts/release.py release --version 1.1.0     --notes-file clients/android/release-notes/1.1.0.md
python clients/android/scripts/release.py tag               # android-v1.1.0, then push the tag
```

- **Versions:** `versionName` is `MAJOR.MINOR.PATCH`; `versionCode` is derived (`MAJOR*10000 + MINOR*100 +
  PATCH`, so 1.4.2 is 10402). It always rises with the version and nobody can pick a clashing number.
- **`build`** makes a signed, minified APK in `clients/android/dist/` (git-ignored) and verifies it with the
  platform's own tools (`aapt2`, `apksigner`): package, build number, minSdk, v2+ signature and certificate.
- **`publish`** repeats those checks, then asks the server what it would refuse (repeated or lower build,
  different signing key) before uploading, uploads, and finally compares the manifest's SHA-256 with the file.
  `--dry-run` stops before the upload. `--rollout 20`, `--channel beta`, `--no-publish` (store, offer later) and
  `--mandatory --yes` work as described below.
- **`release`** is `build` + `publish` for a given `--version`, without editing any file.
- Servers must be `https://` (a dev server on `localhost` may use `http://`). `--server` or `IFINMAIL_SERVER`
  overrides `ifinmail.updateBaseUrl`.

Other routes, all running the same server-side checks:

- **Console:** Settings → App releases → *Publish a build* (asks for your password).
- **API:** `POST /api/v1/releases/android` multipart (`file`, `channel`, `notes`, `mandatory`,
  `rollout_percent`, `publish`). `GET` lists releases with adoption; `PATCH` / `DELETE`
  `/api/v1/releases/android/{channel}/{version_code}` edit or remove one.
- **Server shell:** `python manage.py publish_release app-release.apk --notes "…"`,
  `--list` shows what is on record.

### From CI

`.github/workflows/android-release.yml` (manual, *Run workflow*) does `release.py release` on a runner and keeps
the APK as a build artifact. Set these once under *Settings → Secrets and variables → Actions*:

| Name | Kind | Value |
| --- | --- | --- |
| `ANDROID_KEYSTORE_BASE64` | secret | `base64 -w0 ifinmail-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | secrets | from `keystore.properties` |
| `IFINMAIL_API_TOKEN` | secret | API key with scope `system.manage` |
| `IFINMAIL_SERVER` | variable | `https://mail.example.org` |

The job uses an `android-release` environment; add required reviewers to it if a second person should approve
every release.

### What the server checks on upload

The server reads the APK itself (it does not trust form fields): it must be the right application
(`com.ifinmail`), signed, a new version code for that channel, and signed with the **same certificate**
as earlier releases. A key change would make every installed copy refuse the update, so it is
rejected up front. `minSdk` and `targetSdk` are recorded.

## Signing key

Create it once and back it up somewhere safe. Losing it means installed apps can never be updated; they
would have to be uninstalled first. See `clients/android/README.md` and
`clients/android/keystore.properties.example`. Never commit the key. Unsigned builds are not installable
and the publish script refuses them.

## Channels, rollout, mandatory, rollback

- **Channels:** `stable` (default) and `beta`. A build chooses its channel at compile time
  (`ifinmail.updateChannel`) and only ever follows that channel, so publish to `beta` first and
  to `stable` once it has proved itself (a beta build keeps getting beta builds).
- **Staged rollout:** `rollout_percent` 0–100. Each device lands in a fixed bucket (SHA-256 of its
  random install id modulo 100), so raising 10 → 50 → 100 only ever adds devices; nobody flips back.
- **Mandatory:** setting *mandatory* makes that version the floor. Older installs show the
  "Update required" screen and cannot continue until they update. Use it for security fixes and
  for server-side breaking changes. It needs your password in the console.
- **Rollback:** withdraw a release (console *Withdraw*, or `PATCH is_published=false`). The manifest then
  offers the previous published build to devices that have not yet updated. Android never installs a lower
  `versionCode` over a higher one, so devices that already updated stay on the withdrawn build until you
  publish a **new, higher** version containing the fix. Roll forward, not back.

## How an update reaches a device

1. The app asks the manifest (`channel`, `version_code`, `sdk`, install id) and gets the best build for it.
2. It validates the answer (package, https, size, SHA-256) and shows the banner.
3. On *Update*, it downloads (resumable, `Range`) to app-private storage and checks SHA-256 and size.
4. It then asks Android to read the file and checks again **on the device**: same package, higher
   `versionCode`, same signing certificate as the installed app.
5. A `PackageInstaller` session starts; Android asks the person to confirm, and replaces the app.

### First-time permission and Play Protect

- Android requires the one-time **Install unknown apps** permission for ifinmail. The app takes the
  person to the right system screen and returns when it is granted.
- Google Play Protect may show **App scan recommended** for builds it has not seen. The person taps
  *Install* (or *Scan*). If they choose *Don't install*, the app says so plainly and offers *Try again*;
  it never retries on its own. This prompt comes from Google's service, not from ifinmail, and is
  shown to any app installed outside Google Play.
- The app itself runs on Android 7.0+ (API 24); the manifest never offers a build whose `minSdk` is above the
  device's SDK level.

## Operations

- **Hosting:** the APK is a public `StoredFile` (`entity_type=APP_RELEASE`) served by nginx from `/media/`
  with `Content-Disposition: attachment`; the download page and manifest are served by Django.
- **Disk:** keep an eye on `/media`; each release is one APK (about 2–20 MB). Delete old withdrawn builds
  from the console when they are no longer needed.
- **Privacy:** a check-in stores a random install id, version, channel, Android SDK level and when it was
  last seen, never an account, address or IP. Rows are pruned after 180 days
  (`releases.prune_checkins`, daily); *active devices* means seen in the last 30 days.
- **Audit:** publish, change and delete are written to the audit trail with the actor.
- **Monitoring:** the console shows adoption per version (active devices on each build). A build that
  fails the on-device identity check never installs; the app reports the reason on screen.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Upload refused: "signed with a different key" | A different keystore than earlier releases; use the original one |
| Upload refused: "version code" | `versionCode` is not higher than what is already on that channel |
| App says "This update does not match this app" | Package or signing certificate differs from the installed app (sideloaded debug build?) |
| Update loops back to the banner | Play Protect declined, or "Install unknown apps" was revoked; tap *Update* again |
| Download page shows no build | Nothing is published on `stable` yet, or all builds were withdrawn |
| Manifest 404 behind a proxy | The proxy must pass `/updates/` and `/media/` through unauthenticated |
