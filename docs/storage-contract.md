# External storage: research, contract and plan

Status: implemented in v0.0.40. Owner module: `backend/apps/core/storage`.

## 1. What needed solving

The console keeps files on the server's own disk (`MEDIA_ROOT`, the `media_data` volume): branding
uploads today, `StoredFile` attachments as features use them, and backups under `/backups` with an
optional SSH copy. A single-server install that wants its files elsewhere (a provider's object
storage, a NAS, a second site) had no way to say so, and backups could only leave the server over
SSH. The goal: one neutral contract that any storage system can implement, chosen and configured
through a plugin, with media and backups as the first consumers, and no new third-party software.

## 2. Research

### 2.1 Which remote protocol first

| Option | Who speaks it | Cost to support here |
|---|---|---|
| **S3 REST API (SigV4)** | AWS S3, Cloudflare R2, Backblaze B2, Wasabi, DigitalOcean Spaces, Hetzner, OVHcloud, Scaleway, Ceph RGW, Garage, SeaweedFS, (MinIO) | HTTP + HMAC-SHA256 signing: standard library only |
| WebDAV | Nextcloud, ownCloud, Apache/nginx dav, NAS boxes | HTTP verbs, no listing standard beyond PROPFIND |
| SFTP | Any SSH server | Needs an SSH client library or the `ssh` binary |
| Vendor SDKs (boto3, google-cloud-storage, azure-storage-blob) | One vendor each | 10–80 MB of dependencies each, vendor-shaped APIs |

The S3 API is the de facto standard for object storage: one driver reaches a dozen commercial
providers and every common self-hosted server. It is HTTP plus a documented signature
(AWS Signature Version 4), which the Python standard library (`hmac`, `hashlib`, `http.client`)
implements in about 200 lines: no `boto3`, no `django-storages`. Other protocols fit the same
contract later as further drivers (section 4.3).

### 2.2 Industry practice this design follows

* **Content-addressed integrity.** Every upload carries the SHA-256 of its body in the signed
  request (`x-amz-content-sha256`); the server refuses a body that does not match. Reads are
  verified against the hash recorded at write time when the caller asks.
* **Retrieval by negotiation, not by proxying everything.** Clients fetch objects directly from
  the store with a short-lived **pre-signed URL** (query-string SigV4, default 5 minutes); a
  public CDN base URL can be used for public media; proxying through the console is the fallback
  for stores clients cannot reach (a LAN-only server).
* **Least privilege.** One bucket, one key that can only read and write that bucket; the
  secret is stored encrypted (plugin secret) and sent nowhere but the endpoint.
* **Client-side encryption for anything private.** Backups leave the server already GPG-encrypted
  (existing policy: plaintext archives are refused), so the storage provider never holds
  readable mail. Media is public by nature (logos).
* **Idempotent, retried, bounded.** Deletes are idempotent; reads and deletes are retried with
  backoff on 5xx/429/timeouts; writes are retried only when the body can be replayed. Large
  streams use multipart upload (16 MiB parts) so memory stays flat. Every call has a timeout.
* **Keys, not paths.** Object keys are validated once, the same way for every driver (no `..`,
  no leading `/`, no control characters, at most 512 bytes), so a key that is safe on S3 is
  safe on a filesystem.
* **Probe, don't assume.** A write/read/delete probe of a throwaway key proves credentials,
  bucket and clock skew before anything relies on the store, and runs periodically for System
  health.

### 2.3 What stays local, and why

Mailboxes stay on the server's disk. Dovecot's object-storage backend is part of its commercial
edition only, and IMAP needs low-latency random access that object stores do not give. The
contract is for **files the console manages** (media, attachments stored through
`StoredFile`, backups), not for the mail store.

### 2.4 Test targets

MinIO stopped publishing community images in 2025, so the driver is verified against two
independent S3 implementations instead: **Garage** and **SeaweedFS** (test-only containers,
never shipped).

## 3. The contract

`backend/apps/core/storage/contract.py`

```text
ObjectStore
  name: str                       driver id ("local", "s3", ...)
  put(key, data, content_type)    -> ObjectInfo      write or replace, atomically
  put_stream(key, stream, ...)    -> ObjectInfo      unbounded size, flat memory
  get(key, max_bytes)             -> bytes           whole object, bounded
  open(key)                       -> Iterator[bytes] streaming read
  head(key)                       -> ObjectInfo      size, etag, content type, modified
  exists(key)                     -> bool
  delete(key)                     -> None            idempotent
  list(prefix, limit)             -> list[ObjectInfo]
  retrieval_url(key, expires)     -> str | None      how a client may fetch it directly
  probe()                         -> ProbeResult     write/read/delete round trip
```

Errors: `StorageError` (base, message safe to show), `ObjectNotFoundError`, `StorageUnavailableError`
(network, timeouts, 5xx: worth retrying), `StorageRejectedError` (credentials, permissions, bad
bucket: needs a person).

Purposes route keys to the store: `media` (branding, `StoredFile`), `backups` (encrypted
archives). With no plugin configured, every purpose uses the `local` driver (the behaviour
before this release).

## 4. How plugins implement it

### 4.1 Configure a driver (declarative plugin)

A plugin contributes values to the capability **`storage.objects`**:

| Field | Meaning |
|---|---|
| `driver` | which driver implements the contract (`s3`) |
| `endpoint` | `https://s3.eu-central-1.amazonaws.com`, `https://<account>.r2.cloudflarestorage.com`, `http://garage:3900`... |
| `region` | signing region (`us-east-1` when the provider does not care) |
| `bucket`, `prefix` | where this server's objects live |
| `access_key`, `secret_key` | the key pair (secret stored encrypted) |
| `addressing` | `path` or `virtual` host style |
| `retrieval` | `redirect` (pre-signed URL), `public` (via `public_base_url`), `proxy` |
| `public_base_url` | CDN or public bucket URL for `public` retrieval |
| `media`, `backups` | which purposes go to this store |

The bundled **Object storage (S3-compatible)** plugin offers these as settings. A provider-specific
plugin (for example one that only asks for an R2 account id) contributes the same capability
with some fields fixed: the contract does not change.

### 4.2 The consumer side

Core reads the capability (`storage.config.current()`), builds the driver and routes purposes.
`StorageService`, `StoredFile` (Django's `default_storage` is the routing backend) and the
branding upload all go through it; nothing else touches the disk directly.

### 4.3 Adding a protocol (a new driver)

A driver is a class implementing `ObjectStore`, registered with
`storage.drivers.register('webdav', factory)` from an app's `ready()`; it then becomes a valid
`driver` value for plugins. Core stays neutral: it never imports a driver's app.

## 5. Plan (delivered in v0.0.40)

1. Contract, key rules, errors, local driver, S3 driver (SigV4 headers + pre-signed URLs,
   single and multipart upload, streaming reads, ListObjectsV2), driver registry.
2. Capability `storage.objects`, in-console adapter target, bundled plugin.
3. Routing Django storage backend; `StorageService` and branding through it.
4. Retrieval negotiation: `/media/...` served from disk by nginx when local; otherwise nginx
   falls through to the console, which redirects (pre-signed / public) or proxies.
5. Backups: the off-site step of the nightly backup sends the encrypted archive to the store
   when the plugin routes backups there (`manage.py storage upload --purpose backups`, streamed,
   multipart, SHA-256 compared), with retention pruning (`storage prune --days N`).
6. Probe task (`storage.probe`, twice an hour), the *File storage* System health check, and
   Settings → File storage (where each purpose is kept, *Test connection*, *Copy media*).
7. Tests: SigV4 against AWS's published examples, every driver rule, and an end-to-end run
   against Garage and SeaweedFS.

## 6. Verification (v0.0.40)

- SigV4: the four AWS-published examples (GET with range, PUT, list, pre-signed URL) match
  byte for byte.
- Driver, against Garage v1.0.1 and SeaweedFS 3.80 (18 checks each): put/get/head/exists,
  a 40 MB multipart upload, keys with spaces, unicode and `+`, listing with a prefix, a
  pre-signed URL fetched by a plain HTTP client (a tampered one answers 403), idempotent delete,
  a wrong secret and a missing bucket reported as `StorageRejectedError` / `StorageError`, and
  invalid keys refused before any request.
- Console, against both servers: plugin install and probe, System health OK, a branding logo
  stored in the bucket (not on disk) and served to an anonymous visitor through a signed redirect
  with the exact bytes, a private `StoredFile` hidden from strangers and readable by an
  administrator, record delete removing the object, a 40 MB backup with a matching SHA-256,
  listing and pruning, proxy mode streaming, and branding reset leaving the bucket empty.
- nginx: a file on disk is served directly; a missing one falls through to the console.
