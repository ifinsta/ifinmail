# Changelog

## v0.0.4
- `make uninstall` also removes anonymous volumes of the stack's containers (certbot declares
  some), so nothing is left behind.
- This changelog.

## v0.0.3
- `make update [TO=vX.Y.Z]` with a database and configuration snapshot, automatic rollback if the
  new version is not healthy, and `make rollback` (code and database) / `make version`.
- The console shows the installed version and announces new releases (six-hourly GitHub check,
  can be switched off).
- `make uninstall` undoes the installation; `--check` lists anything left.

## v0.0.2
- One-command install verified end to end; mail delivery fixes (Postfix chroot, Dovecot volume
  ownership); setup wizard required until finished; forced first password; optional two-factor;
  System health page; one brand name default.
