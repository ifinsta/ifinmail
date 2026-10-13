#!/bin/bash
# ifinmail backup_offsite.sh — off-site copy of the encrypted backup, and the key that opens it.
#
#   backup_offsite.sh send <archive.gpg>   copy one archive to BACKUP_OFFSITE_TARGET (backup_full.sh)
#   backup_offsite.sh check                prove the target accepts, stores and returns a test file
#   backup_offsite.sh export-key <dir>     write the backup key + passphrase to <dir> and prove they
#                                          decrypt the newest backup using nothing else on this host
#   backup_offsite.sh verify-key <key.asc> <passphrase-file>
#                                          the same proof for a key held elsewhere (recovery drill)
#
# Only OpenSSH, GnuPG and coreutils are used: no cloud SDKs, no agents. Plaintext archives are
# refused, so the provider of the target can never read your mail. The key is deliberately NOT
# sent with the backups: a backup stored next to its key is not encrypted in any useful sense.
#
# Settings (provisioning/.env):
#   BACKUP_OFFSITE_TARGET   user@host:/absolute/path, or "object-storage" (the store the Object
#                           storage plugin configures in the console). Empty: object storage when
#                           that plugin has "Send encrypted backups here" ticked, otherwise none.
#   BACKUP_OFFSITE_PORT     SSH port, default 22
#   BACKUP_OFFSITE_SSH_KEY  private key file for the target (default: ssh's own defaults)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/provisioning/.env"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

TARGET="${BACKUP_OFFSITE_TARGET:-}"
PORT="${BACKUP_OFFSITE_PORT:-22}"
SSH_KEY="${BACKUP_OFFSITE_SSH_KEY:-}"
KNOWN_HOSTS="${BACKUP_OFFSITE_KNOWN_HOSTS:-/root/.ssh/ifinmail_offsite_known_hosts}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
RECIPIENT="${BACKUP_GPG_RECIPIENT:-}"
NOTIFY_URL="${BACKUP_NOTIFY_URL:-}"

die() { echo "ERROR: $*" >&2; exit 1; }

# The console reads small status files from the runtime volume (System health).
record_status() { # <file> <content>
    local volume="${COMPOSE_PROJECT_NAME:-docker}_runtime_data"
    docker run --rm -v "${volume}:/runtime" alpine:3.20 \
        sh -c 'printf "%s\n" "$1" > "/runtime/$2"' _ "$2" "$1" >/dev/null 2>&1 \
        || echo "  (could not record $1 in the runtime volume)"
}

notify_failure() {
    echo "ERROR: $1" >&2
    if [ -n "$NOTIFY_URL" ]; then
        curl -fsS --connect-timeout 10 --max-time 30 -X POST \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"ifinmail off-site backup FAILED: $1\"}" "$NOTIFY_URL" || true
    fi
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ---------------------------------------------------------------- object storage (via the console)

# The console holds the store's settings and encrypted key; the archive is streamed into it.
API_CONTAINER="${COMPOSE_PROJECT_NAME:-docker}-api-1"
console_storage() { docker exec -i "$API_CONTAINER" python manage.py storage "$@"; }

backups_in_object_storage() {
    [ "$TARGET" = "object-storage" ] && return 0
    [ -z "$TARGET" ] || return 1
    console_storage status 2>/dev/null | grep '^backups: ' | grep -vq '^backups: local '
}

send_object_storage() { # <archive.gpg>
    local archive="$1" name local_sum out stored_sum
    name="$(basename "$archive")"
    local_sum="$(sha256sum "$archive" | cut -d' ' -f1)"
    echo "  Off-site copy: $name -> object storage"
    if ! out="$(console_storage upload --purpose backups "$name" < "$archive" 2>&1)"; then
        record_status offsite-status "failed $(now) object storage refused the upload"
        notify_failure "object storage upload of $name failed: ${out##*Error: }"
        echo "$out" >&2
        return 1
    fi
    stored_sum="$(printf '%s' "$out" | sed -n 's/.*sha256 \([0-9a-f]\{64\}\).*/\1/p')"
    if [ "$stored_sum" != "$local_sum" ]; then
        record_status offsite-status "failed $(now) object storage checksum mismatch"
        notify_failure "checksum mismatch for $name in object storage"
        return 1
    fi
    console_storage prune --purpose backups --days "$RETENTION_DAYS" \
        || echo "  (could not prune old copies in object storage)"
    record_status offsite-status "ok $(now) object storage"
    echo "  Off-site copy: verified in object storage (sha256 matches)"
}

# ---------------------------------------------------------------- target handling

parse_target() {
    # The path is used inside a remote shell command, so it is held to a strict alphabet.
    [[ "$TARGET" =~ ^([A-Za-z0-9._-]+@[A-Za-z0-9.-]+):(/[A-Za-z0-9._/-]+)$ ]] \
        || die "BACKUP_OFFSITE_TARGET must look like user@host:/absolute/path (got: $TARGET)"
    REMOTE_HOST="${BASH_REMATCH[1]}"
    REMOTE_DIR="${BASH_REMATCH[2]}"
    [[ "$PORT" =~ ^[0-9]+$ ]] || die "BACKUP_OFFSITE_PORT must be a number"
    SSH_OPTS=(-p "$PORT" -o BatchMode=yes -o ConnectTimeout=20
              -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$KNOWN_HOSTS")
    SCP_OPTS=(-P "$PORT" -o BatchMode=yes -o ConnectTimeout=20
              -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$KNOWN_HOSTS")
    if [ -n "$SSH_KEY" ]; then
        SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
        SCP_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
    fi
    mkdir -p "$(dirname "$KNOWN_HOSTS")"
}

# Copy a file, then ask the far side to hash what it received and compare.
# Returns non-zero (instead of exiting) so the caller can record the failure.
copy_verified() { # <local file> <remote name>
    local file="$1" name="$2" local_sum remote_sum
    local_sum="$(sha256sum "$file" | cut -d' ' -f1)"
    ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'" || return 1
    scp -q "${SCP_OPTS[@]}" "$file" "$REMOTE_HOST:$REMOTE_DIR/.$name.partial" || return 1
    remote_sum="$(ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
        "mv '$REMOTE_DIR/.$name.partial' '$REMOTE_DIR/$name' && sha256sum '$REMOTE_DIR/$name'")" \
        || return 1
    remote_sum="${remote_sum%% *}"
    if [ "$local_sum" != "$remote_sum" ]; then
        echo "ERROR: checksum mismatch for $name (local $local_sum, remote $remote_sum)" >&2
        return 1
    fi
}

cmd_send() {
    local archive="${1:-}"
    if backups_in_object_storage; then
        [ -f "$archive" ] || die "archive not found: $archive"
        case "$archive" in
            *.gpg) ;;
            *) record_status offsite-status "failed $(now) refused an unencrypted archive"
               die "refusing to send an unencrypted archive off the server: $archive" ;;
        esac
        send_object_storage "$archive"
        return
    fi
    if [ -z "$TARGET" ]; then
        echo "  Off-site copy: not configured (set BACKUP_OFFSITE_TARGET in provisioning/.env)"
        record_status offsite-status "disabled $(now)"
        return 0
    fi
    [ -f "$archive" ] || die "archive not found: $archive"
    case "$archive" in
        *.gpg) ;;
        *) record_status offsite-status "failed $(now) refused an unencrypted archive"
           die "refusing to send an unencrypted archive off the server: $archive" ;;
    esac
    parse_target
    local name
    name="$(basename "$archive")"
    echo "  Off-site copy: $name -> $REMOTE_HOST:$REMOTE_DIR"
    if ! copy_verified "$archive" "$name"; then
        record_status offsite-status "failed $(now) copy to $REMOTE_HOST did not complete"
        notify_failure "could not copy $name to $REMOTE_HOST"
        return 1
    fi
    # Same retention as the local copies, applied on the far side.
    ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
        "find '$REMOTE_DIR' -maxdepth 1 -name 'ifinmail_backup_*.gpg' -mtime +$RETENTION_DAYS -delete" \
        || echo "  (could not prune old copies on $REMOTE_HOST)"
    record_status offsite-status "ok $(now) $REMOTE_HOST"
    echo "  Off-site copy: verified (sha256 matches)"
}

cmd_check() {
    if backups_in_object_storage; then
        console_storage check --purpose backups || die "the object store did not pass the check"
        echo "OK: object storage accepts, stores and returns files byte for byte."
        return
    fi
    [ -n "$TARGET" ] || die "BACKUP_OFFSITE_TARGET is not set in $ENV_FILE"
    parse_target
    local tmp name
    tmp="$(mktemp)"
    name="ifinmail_offsite_check_$$.txt"
    # shellcheck disable=SC2064
    trap "rm -f '$tmp'" EXIT
    echo "ifinmail off-site check $(now)" > "$tmp"
    copy_verified "$tmp" "$name" || die "the target did not accept and return the test file"
    ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "rm -f '$REMOTE_DIR/$name'"
    echo "OK: $REMOTE_HOST:$REMOTE_DIR accepts, stores and returns files byte for byte."
}

# ---------------------------------------------------------------- the key

# Decrypt the newest backup with ONLY the given key, in a throwaway keyring.
prove_key() { # <key.asc> <passphrase-file>
    local key="$1" passfile="$2" newest
    newest="$(ls -t "$BACKUP_DIR"/ifinmail_backup_*.tar.gz.gpg 2>/dev/null | head -1 || true)"
    [ -n "$newest" ] || die "no encrypted backup in $BACKUP_DIR to test the key against (run: make backup)"
    # A subshell so the throwaway keyring is removed however this ends.
    (
        home="$(mktemp -d)"
        chmod 700 "$home"
        trap 'rm -rf "$home"' EXIT
        gpg --homedir "$home" --batch --quiet --pinentry-mode=loopback \
            --passphrase-file "$passfile" --import "$key" 2>/dev/null \
            || die "the key file could not be imported with that passphrase"
        gpg --homedir "$home" --batch --quiet --pinentry-mode=loopback \
            --passphrase-file "$passfile" --decrypt "$newest" 2>/dev/null | tar -tz >/dev/null \
            || die "the key and passphrase do NOT decrypt $(basename "$newest")"
        echo "OK: this key and passphrase decrypt $(basename "$newest") on their own."
    )
}

cmd_export_key() {
    local dir="${1:-}" pass="${BACKUP_GPG_PASSPHRASE:-}"
    [ -n "$dir" ] || die "usage: backup_offsite.sh export-key <directory>"
    [ -n "$RECIPIENT" ] || die "BACKUP_GPG_RECIPIENT is not set"
    [ -n "$pass" ] || die "BACKUP_GPG_PASSPHRASE is not set in $ENV_FILE"
    mkdir -p "$dir"
    umask 077
    printf '%s' "$pass" > "$dir/ifinmail-backup-key.passphrase"
    gpg --batch --quiet --pinentry-mode=loopback --passphrase-file "$dir/ifinmail-backup-key.passphrase" \
        --armor --export-secret-keys "$RECIPIENT" > "$dir/ifinmail-backup-key.asc" \
        || die "could not export the key for $RECIPIENT"
    chmod 600 "$dir/ifinmail-backup-key.asc" "$dir/ifinmail-backup-key.passphrase"
    prove_key "$dir/ifinmail-backup-key.asc" "$dir/ifinmail-backup-key.passphrase"
    record_status backup-key-exported-at "$(now)"
    cat <<EOF

Written to $dir:
  ifinmail-backup-key.asc          the backup key (protected by the passphrase)
  ifinmail-backup-key.passphrase   its passphrase

Move BOTH off this server now (a password manager, or an encrypted USB drive in a safe),
then delete them from $dir. Without them the backups cannot be opened after this server is lost.
EOF
}

cmd_verify_key() {
    [ -f "${1:-}" ] && [ -f "${2:-}" ] || die "usage: backup_offsite.sh verify-key <key.asc> <passphrase-file>"
    prove_key "$1" "$2"
}

case "${1:-}" in
    send)       shift; cmd_send "$@" ;;
    check)      cmd_check ;;
    export-key) shift; cmd_export_key "$@" ;;
    verify-key) shift; cmd_verify_key "$@" ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
