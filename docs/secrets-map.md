# Secrets map

Every secret the system holds, where it lives, what protects it, and what is accepted. Reviewed
with the risk register (`docs/risk-register.md`). A secret not listed here is a gap.

| Secret | Lives in | Protection at rest | Exposure if the database is copied | Rotation |
|---|---|---|---|---|
| Administrator and mailbox passwords | `users.password`, `users.password_hash` | Salted hashes (Django hasher for the console, SHA512-CRYPT for Dovecot) | Offline guessing only | On request; first-sign-in change forced |
| TOTP secrets | `accounts_totp_device.secret_encrypted` | Fernet, key derived from `SECRET_KEY` | Unreadable without `SECRET_KEY` (`.env`) | Re-enroll |
| Recovery codes | `accounts_mfa_recovery_code` | Hashes only; single use | Not recoverable | Regenerate |
| API tokens | `accounts_api_token.token_hash` | SHA-256; plaintext shown once | Not recoverable | Rotate or revoke; expire in ≤ 90 days |
| DNS provider credentials | `dns_provider_config.credentials` | Encrypted (`decrypt_credentials`) | Unreadable without `SECRET_KEY` | Re-enter |
| **DKIM private keys** | `dkim_keys.private_key` **and** `/etc/dkim/*.key` | **None** (plaintext). File mode 0644 so Rspamd can read it | **Readable**: an attacker could sign mail as your domain | New selector, republish DNS |
| DNSSEC keys | `dns_data` volume (Knot) | File permissions only (backups mode 600) | n/a (not in the database) | Key rollover at registrar |
| TLS private keys | `certs` volume (Let's Encrypt) | File permissions; mounted read-only into the console | n/a | Automatic renewal |
| `SECRET_KEY`, database and Redis passwords | `provisioning/.env` | File mode 600, root | n/a | Reprovision |
| Backup key + passphrase | Host GPG keyring; passphrase in `.env`; **escrow copy off the server** (`make backup-key`) | Passphrase-protected key | n/a | Quarterly rotation per runbook |
| Off-site SSH key | Path in `BACKUP_OFFSITE_SSH_KEY` | File permissions | n/a | On compromise or staff change |

## Accepted risk: DKIM private keys (finding F8)

Rspamd signs mail by reading each key from a file, so the key cannot be encrypted at rest on the
host without breaking signing, and the copy in the database lets the console regenerate and
publish records. What contains it:

- The server is single-tenant and the containers do not share the DKIM volume with anything but
  Rspamd and the console.
- Backups containing the keys are GPG-encrypted, and the off-site copy never leaves encrypted.
- A leaked key can be retired by publishing a new selector; the old one then stops verifying.

What would close it fully, if a customer requires it: sign through a separate signing service that
holds the key in memory only, or encrypt the database copy and keep only the file. Neither is
planned: both add moving parts for a threat that already requires database or disk access.

**Owner:** maintainer. **Review:** with each release that touches DKIM or the DB schema.
