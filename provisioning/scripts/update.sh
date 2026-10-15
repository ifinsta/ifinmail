#!/usr/bin/env bash
# ifinmail update.sh — move this install to another release, with a safe way back.
#
#   update.sh                  update to the latest release tag (vX.Y.Z) on the git remote
#   update.sh --to v0.0.4      update (or move) to that release
#   update.sh --rollback       go back to the version before the last update: code AND database
#   update.sh --status         installed version, latest release, update history
#
# Before switching, the database is dumped (pg_dump) and provisioning/.env copied into
# provisioning/.updates/. If the new version's console is not healthy within 5 minutes, the
# script rolls back by itself. Rolling back restores the database snapshot as well as the code:
# a newer version may have migrated the schema, and old code on a new schema is not safe.
# Mail (Maildirs), DNSSEC keys and certificates live in volumes that every version shares.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROVISIONING_DIR="$REPO_DIR/provisioning"
ENV_FILE="$PROVISIONING_DIR/.env"
STATE_DIR="$PROVISIONING_DIR/.updates"
HISTORY="$STATE_DIR/history"
KEEP_SNAPSHOTS="${UPDATE_KEEP_SNAPSHOTS:-5}"
HEALTH_TIMEOUT="${UPDATE_HEALTH_TIMEOUT:-300}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$PROVISIONING_DIR/docker/docker-compose.yml")

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "==> $*"; }
git_() { git -C "$REPO_DIR" "$@"; }

version_of() { git_ describe --tags --always "$1" 2>/dev/null || git_ rev-parse --short "$1"; }

latest_tag() {
    git_ tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1
}

wait_healthy() {
    local waited=0 state
    while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
        state="$("${COMPOSE[@]}" ps -q api 2>/dev/null | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || true)"
        if [ "$state" = "healthy" ] && curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/health/ 2>/dev/null; then
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    return 1
}

snapshot() { # label -> prints the snapshot path
    local stamp file
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    file="$STATE_DIR/db-$1-$stamp.dump"
    mkdir -p "$STATE_DIR"
    chmod 700 "$STATE_DIR"
    "${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$file" \
        || die "could not snapshot the database; nothing was changed"
    [ -s "$file" ] || die "database snapshot is empty; nothing was changed"
    cp "$ENV_FILE" "$file.env"
    chmod 600 "$file" "$file.env"
    echo "$file"
}

restore_snapshot() { # snapshot path
    local file="$1"
    [ -s "$file" ] || die "snapshot $file is missing"
    say "Restoring the database snapshot $(basename "$file")"
    "${COMPOSE[@]}" stop api worker >/dev/null 2>&1 || true
    "${COMPOSE[@]}" exec -T postgres sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --single-transaction' \
        < "$file" || die "database restore failed; the snapshot is kept at $file"
    if [ -s "$file.env" ]; then
        cp "$file.env" "$ENV_FILE"
    fi
}

provision() {
    say "Building and starting $(version_of HEAD)"
    bash "$SCRIPT_DIR/provision.sh"
}

prune_snapshots() {
    local snapshots
    mapfile -t snapshots < <(ls -1t "$STATE_DIR"/db-*.dump 2>/dev/null || true)
    if [ "${#snapshots[@]}" -gt "$KEEP_SNAPSHOTS" ]; then
        for old in "${snapshots[@]:$KEEP_SNAPSHOTS}"; do
            rm -f "$old" "$old.env"
        done
    fi
}

do_status() {
    git_ fetch -q --tags --force origin 2>/dev/null || echo "(could not reach the git remote)"
    echo "Installed: $(version_of HEAD)"
    echo "Latest:    $(latest_tag || true)"
    if [ -s "$HISTORY" ]; then
        echo "History (time, from, to, result):"
        awk '{print "  " $1, $3, "->", $5, $7}' "$HISTORY"
    fi
}

do_rollback() {
    [ -s "$HISTORY" ] || die "no update to roll back"
    local line from_sha from_version snapshot_file
    line="$(grep ' ok$\| updated$' "$HISTORY" | tail -1 || true)"
    [ -n "$line" ] || die "no completed update to roll back"
    from_sha="$(echo "$line" | awk '{print $2}')"
    from_version="$(echo "$line" | awk '{print $3}')"
    snapshot_file="$(echo "$line" | awk '{print $6}')"
    say "Rolling back to $from_version"
    git_ checkout -q --detach "$from_sha"
    restore_snapshot "$snapshot_file"
    provision
    wait_healthy || die "the console did not come back healthy after the rollback; see 'make logs'"
    sed -i "s#^\(.* $snapshot_file\) \(ok\|updated\)\$#\1 rolled-back#" "$HISTORY"
    say "Rolled back to $from_version"
}

do_update() {
    local target="$1" force="$2"
    if [ "$force" != 1 ] && [ -n "$(git_ status --porcelain --untracked-files=no)" ]; then
        die "the install directory has local code changes; commit or discard them (or use --force)"
    fi
    say "Fetching releases"
    git_ fetch -q --tags --force origin || die "could not fetch from the git remote"
    [ -n "$target" ] || target="$(latest_tag)"
    [ -n "$target" ] || die "no release tag found on the remote"
    git_ rev-parse -q --verify "refs/tags/$target^{commit}" >/dev/null || die "unknown release: $target"

    local from_sha to_sha from_version snapshot_file
    from_sha="$(git_ rev-parse HEAD)"
    to_sha="$(git_ rev-parse "refs/tags/$target^{commit}")"
    from_version="$(version_of HEAD)"
    if [ "$from_sha" = "$to_sha" ]; then
        say "Already at $target"
        return 0
    fi

    say "Snapshot of the database before leaving $from_version"
    snapshot_file="$(snapshot "$from_version")"
    printf '%s %s %s %s %s %s pending\n' "$(date -u +%FT%TZ)" "$from_sha" "$from_version" \
        "$to_sha" "$target" "$snapshot_file" >> "$HISTORY"

    say "Switching $from_version -> $target"
    git_ checkout -q --detach "$to_sha"
    if provision && wait_healthy; then
        sed -i "s#^\(.* $snapshot_file\) pending\$#\1 ok#" "$HISTORY"
        prune_snapshots
        bash "$SCRIPT_DIR/docker_clean.sh" >/dev/null 2>&1 || echo "(Docker clean-up failed; see 'make docker-clean')" >&2
        say "Updated to $target. To undo: make rollback"
        return 0
    fi

    echo "The new version did not come up healthy; rolling back to $from_version." >&2
    sed -i "s#^\(.* $snapshot_file\) pending\$#\1 updated#" "$HISTORY"
    do_rollback
    exit 1
}

main() {
    [ "$(id -u)" -eq 0 ] || die "run as root (sudo make update)"
    [ -f "$ENV_FILE" ] || die "no provisioning/.env: install first"
    local action=update target='' force=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --to) target="${2:?--to needs a version}"; shift 2 ;;
            --rollback) action=rollback; shift ;;
            --status) action=status; shift ;;
            --force) force=1; shift ;;
            -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
    done
    case "$action" in
        status) do_status ;;
        rollback) do_rollback ;;
        update) do_update "$target" "$force" ;;
    esac
}

main "$@"
