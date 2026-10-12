# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** using GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(this repository's **Security** tab → **Report a vulnerability**). Do not open a public issue or
pull request for something exploitable.

Include what you found, how to reproduce it, the version (`make version`), and the impact you
believe it has.

## What to expect

These are targets for a small project, not guarantees:

| Step | Target |
|---|---|
| Acknowledge your report | 3 working days |
| Initial assessment and severity | 7 days |
| Fix for a critical issue | 7 days |
| Fix for a high issue | 30 days |
| Public advisory | with the fixed release; you are credited unless you prefer not |

## Supported versions

Only the latest release receives fixes. `make update` applies it with a database snapshot and
automatic rollback (see the README).

## Scope

In scope: the console, its API, the provisioning scripts, the container configuration and the
backup and restore tooling in this repository.

Out of scope: vulnerabilities in third-party software that ifinmail packages (Postfix, Dovecot,
Rspamd, PostgreSQL, Redis, nginx, Docker) unless ifinmail's configuration makes them exploitable
— report those upstream — and findings that need an already-compromised server or administrator.

## How the project handles dependencies

Production dependencies are pinned with SHA-256 hashes (`requirements/prod.lock`) and verified at
image build. A scheduled CI job audits them every week. See `docs/enterprise-slo.md`.
